"""端到端 XERJ 检索 + Neuro-Symbolic Reader (1.7B) 验证闭环评测器（10,000+ 分块混合库，零保留标的泄漏）。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import compliance, eval_hub, query_cn

HELDOUT_SEC_TICKERS: frozenset[str] = frozenset(
    {"ARM", "BABA", "GS", "JNJ", "JPM", "MRNA", "MSFT", "OXY", "TSM", "WFC", "XOM"}
)
HELDOUT_FILING_TICKERS: tuple[str, ...] = ("MSFT", "TSM", "GS", "JPM", "BABA")
VERIFIER_URL = os.environ.get("VERICORPUS_VERIFIER_URL", "http://127.0.0.1:8000/api/verify")
DEFAULT_MODEL_KEY = "neuro_symbolic_reader_1_7b"
MAX_ASSEMBLED_DOC_CHARS = 24_000
MAX_CHUNK_CHARS = 7_800
_SEP_LINE_RE = re.compile(r"^\|\s*:?-{2,}")


def value_equal(value: Any, expected: dict[str, Any]) -> bool:
    """Compare verified output value against ground-truth expected value with 0.01 numeric tolerance."""
    if value is None:
        return False
    if expected.get("type") == "number":
        try:
            d_got = Decimal(str(value).strip().rstrip("%"))
            d_exp = Decimal(str(expected["value"]).strip())
            return d_got == d_exp or abs(d_got - d_exp) <= Decimal("0.01")
        except (InvalidOperation, ValueError):
            return False
    return isinstance(value, str) and value.strip().casefold() == str(expected["value"]).strip().casefold()


def score_output(case: dict[str, Any], resp: dict[str, Any], doc: str) -> dict[str, Any]:
    """Verify character-level evidence offsets and exact expected status/value match."""
    expected = case["expected"]
    exp_status = expected["status"]
    got_status = resp.get("status")
    got_val = resp.get("value")
    evidence = resp.get("evidence") or []

    ev_valid = isinstance(evidence, list) and all(
        isinstance(e, dict)
        and isinstance(e.get("start"), int)
        and isinstance(e.get("end"), int)
        and 0 <= e["start"] < e["end"] <= len(doc)
        and doc[e["start"] : e["end"]] == e.get("quote")
        for e in evidence
    )
    if got_status == "ANSWER" and not evidence:
        ev_valid = False

    if exp_status == "ABSENT":
        strict_pass = got_status in ("ABSENT", "UNKNOWN") and got_val is None
        false_answer_hallucinated = got_status == "ANSWER"
    elif exp_status == "CONFLICT":
        strict_pass = got_status == "CONFLICT" and got_val is None
        false_answer_hallucinated = got_status == "ANSWER"
    else:
        strict_pass = got_status == "ANSWER" and ev_valid and value_equal(got_val, expected)
        false_answer_hallucinated = got_status == "ANSWER" and not strict_pass

    return {
        "strict_pass": strict_pass,
        "evidence_offsets_valid": ev_valid,
        "false_answer_hallucinated": false_answer_hallucinated,
    }


def classify_rwn(case: dict[str, Any], resp: dict[str, Any], doc: str) -> tuple[str, dict[str, Any]]:
    """Classify one prediction as Right ('R'), Wrong ('W'), or Declined ('N')."""
    sc = score_output(case, resp, doc)
    if sc["strict_pass"]:
        return "R", sc
    if resp.get("status") == "ANSWER":
        return "W", sc
    return "N", sc


def _resolve_source_text(
    path_str: str,
    raw_lookup: dict[str, Path | str] | Path | None,
    text_cache: dict[str, str],
) -> str:
    if not path_str or raw_lookup is None:
        return ""
    norm = path_str.replace("\\", "/").lstrip("/")
    if norm in text_cache:
        return text_cache[norm]

    val: Path | str | None = None
    if isinstance(raw_lookup, Path):
        cand = raw_lookup / norm
        if cand.is_file():
            val = cand
    elif isinstance(raw_lookup, dict):
        if path_str in raw_lookup:
            val = raw_lookup[path_str]
        elif norm in raw_lookup:
            val = raw_lookup[norm]
        else:
            for k, v in raw_lookup.items():
                kn = k.replace("\\", "/").lstrip("/")
                if norm.endswith("/" + kn) or kn.endswith("/" + norm):
                    val = v
                    break

    if isinstance(val, Path):
        txt = val.read_text(encoding="utf-8", errors="ignore") if val.is_file() else ""
    elif isinstance(val, str):
        txt = val
    else:
        txt = ""
    text_cache[norm] = txt
    return txt


def _extract_table_header_for_chunk(
    source_text: str,
    body: str,
    start_line: int | None,
    section: str,
) -> str:
    body_stripped = body.lstrip()
    if not body_stripped.startswith("|"):
        return ""
    top_lines = [ln.lstrip() for ln in body_stripped.splitlines()[:3]]
    if any(_SEP_LINE_RE.match(ln) for ln in top_lines) or "| ---" in "\n".join(top_lines):
        return ""
    if not source_text:
        return ""

    src_lines = source_text.splitlines()
    first_line = body_stripped.splitlines()[0].strip()
    matches = [idx for idx, ln in enumerate(src_lines) if ln.strip() == first_line]
    if not matches and len(first_line) >= 8:
        matches = [idx for idx, ln in enumerate(src_lines) if first_line in ln]

    anchor_idx: int | None = None
    if matches:
        if isinstance(start_line, int) and start_line >= 1:
            target = start_line - 1
            anchor_idx = min(matches, key=lambda idx: abs(idx - target))
        else:
            anchor_idx = matches[0]
    elif isinstance(start_line, int) and 1 <= start_line <= len(src_lines):
        anchor_idx = start_line - 1

    if anchor_idx is not None:
        # Walk backwards across contiguous pipe-table rows from anchor_idx
        tbl_start = anchor_idx
        while tbl_start > 0 and src_lines[tbl_start - 1].strip().startswith("|"):
            tbl_start -= 1
        # If anchor_idx itself wasn't on a pipe line (e.g. slight line drift), scan up slightly
        if not src_lines[anchor_idx].strip().startswith("|"):
            scan = anchor_idx
            while scan > max(0, anchor_idx - 25) and not src_lines[scan].strip().startswith("|"):
                scan -= 1
            if src_lines[scan].strip().startswith("|"):
                tbl_start = scan
                while tbl_start > 0 and src_lines[tbl_start - 1].strip().startswith("|"):
                    tbl_start -= 1
                anchor_idx = scan

        for sep_idx in range(tbl_start + 1, min(len(src_lines), tbl_start + 6)):
            if _SEP_LINE_RE.match(src_lines[sep_idx].strip()):
                return "\n".join(ln.rstrip() for ln in src_lines[tbl_start : sep_idx + 1])

    # Section heading fallback if line match failed
    if section:
        sec_idx = next((i for i, ln in enumerate(src_lines) if ln.lstrip().startswith("#") and section in ln), None)
        if sec_idx is not None:
            for i in range(sec_idx + 1, min(len(src_lines) - 1, sec_idx + 30)):
                if src_lines[i].strip().startswith("|") and _SEP_LINE_RE.match(src_lines[i + 1].strip()):
                    return f"{src_lines[i].rstrip()}\n{src_lines[i + 1].rstrip()}"
    return ""


def assemble_retrieved_context(
    hits: list[dict[str, Any]],
    raw_lookup: dict[str, Path | str] | Path | None = None,
    max_chars: int = MAX_ASSEMBLED_DOC_CHARS,
) -> str:
    """Format Top-k hits with provenance headers and repair mid-table Markdown headers."""
    if not hits:
        return ""
    text_cache: dict[str, str] = {}
    segments: list[str] = []
    used = 0

    for idx, hit in enumerate(hits, 1):
        title = str(hit.get("title") or "").strip()
        path = str(hit.get("path") or "").strip()
        section = str(hit.get("section") or "").strip()
        body = str(hit.get("body") or hit.get("snippet") or "").strip()
        if not body:
            continue

        if body.lstrip().startswith("|"):
            src_txt = _resolve_source_text(path, raw_lookup, text_cache)
            tbl_hdr = _extract_table_header_for_chunk(src_txt, body, hit.get("start_line"), section)
            if tbl_hdr:
                body = f"{tbl_hdr}\n{body}"

        if len(body) > MAX_CHUNK_CHARS:
            body = body[:MAX_CHUNK_CHARS].rsplit("\n", 1)[0].strip() or body[:MAX_CHUNK_CHARS]

        tag = f"[DOC_{idx} | title: {title} | path: {path} | section: {section}]"
        seg = f"{tag}\n{body}"
        sep = "\n\n" if segments else ""
        if used + len(sep) + len(seg) > max_chars:
            rem = max_chars - used - len(sep)
            if rem <= len(tag) + 120:
                break
            seg = seg[:rem].rsplit("\n", 1)[0].strip() or seg[:rem]
        segments.append(seg)
        used += len(sep) + len(seg)

    return "\n\n".join(segments)


def _hit_is_relevant(hit: dict[str, Any], case: dict[str, Any]) -> tuple[bool, bool]:
    """Return (doc_match, evidence_match) for one retrieval hit."""
    sub = str(case.get("expect_path_sub") or "").lower()
    path = str(hit.get("path") or "").lower()
    doc_match = bool(sub and sub in path)
    if not doc_match:
        return False, False
    snips = [str(s) for s in (case.get("expect_snippet_any") or []) if str(s).strip()]
    if not snips:
        return True, True
    hay = query_cn.to_simplified(
        f"{hit.get('body') or ''}\n{hit.get('snippet') or ''}\n{hit.get('section') or ''}\n{hit.get('title') or ''}"
    ).casefold()
    hay_compact = re.sub(r"\s+", " ", hay)
    for sp in snips:
        needle = re.sub(r"\s+", " ", query_cn.to_simplified(sp)).casefold()
        if needle in hay_compact:
            return True, True
    return True, False


def compute_retrieval_metrics(
    cases: list[dict[str, Any]],
    retrieval_hits_by_id: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compute R@1, R@3, nDCG@3 on answerable queries plus 0-hit rate on ABSENT traps."""
    ans_cases = [c for c in cases if not c.get("expect_absent")]
    abs_cases = [c for c in cases if c.get("expect_absent")]

    ev_r1 = ev_r3 = doc_r1 = doc_r3 = 0
    ndcg_sum = 0.0
    for c in ans_cases:
        hits = retrieval_hits_by_id.get(c["id"], [])[:3]
        first_ev_rank: int | None = None
        first_doc_rank: int | None = None
        for rank, h in enumerate(hits):
            d_ok, e_ok = _hit_is_relevant(h, c)
            if d_ok and first_doc_rank is None:
                first_doc_rank = rank
            if e_ok and first_ev_rank is None:
                first_ev_rank = rank
        if first_doc_rank is not None:
            doc_r3 += 1
            if first_doc_rank == 0:
                doc_r1 += 1
        if first_ev_rank is not None:
            ev_r3 += 1
            if first_ev_rank == 0:
                ev_r1 += 1
            ndcg_sum += 1.0 / math.log2(first_ev_rank + 2)

    abs_zero = sum(1 for c in abs_cases if len(retrieval_hits_by_id.get(c["id"], [])) == 0)
    n_ans = len(ans_cases) or 1
    n_abs = len(abs_cases) or 1
    return {
        "answerable_total": len(ans_cases),
        "absent_total": len(abs_cases),
        "r_at_1": round(ev_r1 / n_ans, 4),
        "r_at_3": round(ev_r3 / n_ans, 4),
        "ndcg_at_3": round(ndcg_sum / n_ans, 4),
        "doc_r_at_1": round(doc_r1 / n_ans, 4),
        "doc_r_at_3": round(doc_r3 / n_ans, 4),
        "absent_zero_hit_count": abs_zero,
        "absent_zero_hit_rate": round(abs_zero / n_abs, 4),
    }


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 2)
    pos = (len(s) - 1) * pct
    lo = int(math.floor(pos))
    hi = min(len(s) - 1, lo + 1)
    frac = pos - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 2)


def paired_bootstrap_ci(
    arm_nets: list[int],
    oracle_nets: list[int] | None = None,
    baseline_nets: list[int] | None = None,
    *,
    n_draws: int = 4000,
    seed: int = 20261120,
) -> dict[str, Any]:
    """Run paired bootstrap resampling (4,000 draws) for Net = R - 2W and normalized Score."""
    n = len(arm_nets)
    if n == 0:
        return {"net_ci95": [0.0, 0.0], "score_ci95": None, "delta_vs_baseline_ci95": None}

    rng = random.Random(seed)
    net_draws: list[float] = []
    score_draws: list[float] = []
    delta_draws: list[float] = []

    for _ in range(n_draws):
        idxs = [rng.randrange(n) for _ in range(n)]
        a_sum = sum(arm_nets[i] for i in idxs)
        net_draws.append(float(a_sum))
        if oracle_nets is not None:
            o_sum = sum(oracle_nets[i] for i in idxs)
            if o_sum > 0:
                score_draws.append(100.0 * a_sum / o_sum)
        if baseline_nets is not None:
            b_sum = sum(baseline_nets[i] for i in idxs)
            delta_draws.append(float(a_sum - b_sum))

    net_draws.sort()
    lo_idx = max(0, int(0.025 * (n_draws - 1)))
    hi_idx = min(n_draws - 1, int(0.975 * (n_draws - 1)))

    res: dict[str, Any] = {
        "bootstrap_draws": n_draws,
        "net_ci95": [round(net_draws[lo_idx], 2), round(net_draws[hi_idx], 2)],
    }
    if score_draws:
        score_draws.sort()
        s_lo = max(0, int(0.025 * (len(score_draws) - 1)))
        s_hi = min(len(score_draws) - 1, int(0.975 * (len(score_draws) - 1)))
        res["score_ci95"] = [round(score_draws[s_lo], 1), round(score_draws[s_hi], 1)]
    if delta_draws:
        delta_draws.sort()
        res["delta_vs_baseline_ci95"] = [round(delta_draws[lo_idx], 2), round(delta_draws[hi_idx], 2)]
    return res


def score_e2e_arm(
    cases: list[dict[str, Any]],
    records: list[dict[str, Any]],
    oracle_records: list[dict[str, Any]] | None = None,
    baseline_records: list[dict[str, Any]] | None = None,
    *,
    n_draws: int = 4000,
    seed: int = 20261120,
) -> dict[str, Any]:
    """Score one E2E arm with XERJ R/W/N, Net = R - 2W, 95% CI, and latency stats."""
    rec_by_id = {r["id"]: r for r in records}
    ora_by_id = {r["id"]: r for r in oracle_records} if oracle_records is not None else None
    bas_by_id = {r["id"]: r for r in baseline_records} if baseline_records is not None else None

    r_cnt = w_cnt = n_cnt = 0
    ev_valid_cnt = 0
    absent_false = 0
    arm_nets: list[int] = []
    ora_nets: list[int] = []
    bas_nets: list[int] = []
    ret_ms_list: list[float] = []
    read_ms_list: list[float] = []
    tot_ms_list: list[float] = []
    by_track: dict[str, dict[str, int]] = {}
    verdicts: dict[str, dict[str, Any]] = {}

    def _net_for(verdict: str) -> int:
        return 1 if verdict == "R" else (-2 if verdict == "W" else 0)

    for c in cases:
        cid = c["id"]
        rec = rec_by_id[cid]
        v, sc = classify_rwn(c, rec, rec.get("doc") or "")
        verdicts[cid] = {"verdict": v, "score": sc}
        if v == "R":
            r_cnt += 1
        elif v == "W":
            w_cnt += 1
        else:
            n_cnt += 1

        if sc["evidence_offsets_valid"]:
            ev_valid_cnt += 1
        if c.get("expect_absent") and sc["false_answer_hallucinated"]:
            absent_false += 1

        arm_nets.append(_net_for(v))
        trk = str(c.get("track") or "other")
        tb = by_track.setdefault(trk, {"R": 0, "W": 0, "N": 0, "total": 0})
        tb[v] += 1
        tb["total"] += 1

        if ora_by_id is not None:
            ov, _ = classify_rwn(c, ora_by_id[cid], ora_by_id[cid].get("doc") or "")
            ora_nets.append(_net_for(ov))
        if bas_by_id is not None:
            bv, _ = classify_rwn(c, bas_by_id[cid], bas_by_id[cid].get("doc") or "")
            bas_nets.append(_net_for(bv))

        if rec.get("retrieval_ms") is not None:
            ret_ms_list.append(float(rec["retrieval_ms"]))
        if rec.get("reader_ms") is not None:
            read_ms_list.append(float(rec["reader_ms"]))
        if rec.get("total_ms") is not None:
            tot_ms_list.append(float(rec["total_ms"]))

    net = r_cnt - 2 * w_cnt
    ora_net_total = sum(ora_nets) if ora_nets else net
    score_pct = round(100.0 * net / ora_net_total, 1) if ora_net_total > 0 else 0.0
    boot = paired_bootstrap_ci(
        arm_nets,
        ora_nets if ora_by_id is not None else None,
        bas_nets if bas_by_id is not None else None,
        n_draws=n_draws,
        seed=seed,
    )

    for tb in by_track.values():
        tb["net"] = tb["R"] - 2 * tb["W"]
        tb["accuracy"] = round(tb["R"] / tb["total"], 4) if tb["total"] else 0.0

    return {
        "total": len(cases),
        "R": r_cnt,
        "W": w_cnt,
        "N": n_cnt,
        "net": net,
        "score_pct_of_oracle": score_pct,
        "strict_accuracy": round(r_cnt / len(cases), 4) if cases else 0.0,
        "evidence_offsets_valid_count": ev_valid_cnt,
        "evidence_offsets_valid_rate": round(ev_valid_cnt / len(cases), 4) if cases else 0.0,
        "absent_false_answers": absent_false,
        "bootstrap_draws": n_draws,
        "net_ci95": boot["net_ci95"],
        "score_ci95": boot.get("score_ci95"),
        "delta_vs_baseline_ci95": boot.get("delta_vs_baseline_ci95"),
        "latency_ms": {
            "retrieval_p50": _percentile(ret_ms_list, 0.5),
            "retrieval_p95": _percentile(ret_ms_list, 0.95),
            "reader_p50": _percentile(read_ms_list, 0.5),
            "reader_p95": _percentile(read_ms_list, 0.95),
            "total_p50": _percentile(tot_ms_list, 0.5),
            "total_p95": _percentile(tot_ms_list, 0.95),
        },
        "by_track": by_track,
        "verdicts": verdicts,
    }


def _baseline_search_with_body(
    base_url: str,
    prefix: str,
    query: str,
    limit: int = 3,
    exclude_format_prefixes: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{prefix}-*/_search?strict_unknown_fields=false&ignore_unavailable=true"
    bool_q: dict[str, Any] = {
        "must": [{"multi_match": {"query": query, "fields": ["body", "title"]}}],
        "filter": [{"terms": {"ax_format": query_cn.DOC_FORMATS}}],
    }
    excl = query_cn._resolve_exclude_format_prefixes(exclude_format_prefixes)
    if excl:
        bool_q["must_not"] = [{"prefix": {"ax_format": pfx}} for pfx in excl]
    body = {
        "size": limit,
        "query": {"bool": bool_q},
        "_source": [
            "ax_path",
            "ax_format",
            "title",
            "start_line",
            "end_line",
            "page",
            "pdf_pages_total",
            "body",
            "section",
        ],
        "fields": ["_passage"],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with compliance._safe_urlopen(req, timeout=20, allow_localhost_http=True) as r:
        raw = json.loads(r.read().decode("utf-8"))

    hits = []
    for item in raw.get("hits", {}).get("hits", []):
        src = item.get("_source") or {}
        passages = (item.get("fields") or {}).get("_passage") or []
        snip = str(passages[0].get("text") if isinstance(passages[0], dict) else passages[0]) if passages else ""
        raw_body = str(src.get("body") or "")
        hits.append(
            {
                "path": str(src.get("ax_path") or ""),
                "format": str(src.get("ax_format") or ""),
                "title": str(src.get("title") or ""),
                "section": str(src.get("section") or ""),
                "start_line": src.get("start_line"),
                "end_line": src.get("end_line"),
                "score": round(float(item.get("_score") or 0.0), 3),
                "body": raw_body,
                "snippet": " ".join((snip or raw_body).split())[:280],
            }
        )
    return {
        "took_ms": raw.get("took", 0),
        "total": (raw.get("hits") or {}).get("total", {}).get("value", 0),
        "hits": hits,
    }


def _call_verifier(
    document: str,
    question: str,
    *,
    verifier_url: str = VERIFIER_URL,
    model_key: str = DEFAULT_MODEL_KEY,
    cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], float, bool]:
    """Call local HTTP verification endpoint with (document, question) deduplication."""
    trimmed = document[:MAX_ASSEMBLED_DOC_CHARS]
    key = hashlib.sha256(f"{model_key}\n{question}\n{trimmed}".encode("utf-8")).hexdigest()
    if cache is not None and key in cache:
        cached = dict(cache[key])
        true_ms = float((cached.get("latency_ms") or {}).get("total_ms") or 0.0)
        return cached, true_ms, True

    payload = json.dumps(
        {"document": trimmed, "question": question, "model_key": model_key},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        verifier_url,
        data=payload,
        headers={"Content-Type": "application/json", "X-VeriCorpus-Eval": "1"},
        method="POST",
    )
    t0 = time.perf_counter()
    with compliance._safe_urlopen(req, timeout=90, allow_localhost_http=True) as r:
        resp = json.loads(r.read().decode("utf-8"))
    http_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    if not resp.get("ok"):
        raise RuntimeError(f"Verifier HTTP error: {resp}")
    res = dict(resp["result"])
    res["http_elapsed_ms"] = http_ms
    if cache is not None:
        cache[key] = dict(res)
    true_ms = float((res.get("latency_ms") or {}).get("total_ms") or http_ms)
    return res, true_ms, False


def stage_pack_compliant_subset(repo_root: Path, stage_dir: Path) -> dict[str, Any]:
    """Copy/hardlink 100% pack-compliant corpus subsets into a clean staging dir for indexing."""
    raw_dir = repo_root / "data" / "raw"
    subsets: list[tuple[str, Path, Path]] = [
        ("sec-10y-core/xbrl_summaries", raw_dir / "sec-10y-core" / "xbrl_summaries", stage_dir / "sec-10y-core" / "xbrl_summaries"),
        *[
            (f"sec-10y-core/filings/{tk}", raw_dir / "sec-10y-core" / "filings" / tk, stage_dir / "sec-10y-core" / "filings" / tk)
            for tk in HELDOUT_FILING_TICKERS
        ],
        ("sec-ipo-prospectus-pack", raw_dir / "sec-ipo-prospectus-pack", stage_dir / "sec-ipo-prospectus-pack"),
        ("cn-law-core", raw_dir / "cn-law-core", stage_dir / "cn-law-core"),
        ("cn-capital-market-law", raw_dir / "cn-capital-market-law", stage_dir / "cn-capital-market-law"),
        ("cn-science-ccby", raw_dir / "cn-science-ccby", stage_dir / "cn-science-ccby"),
        ("cn-github-stars", raw_dir / "cn-github-stars", stage_dir / "cn-github-stars"),
    ]

    raw_lookup: dict[str, Path | str] = {}
    subset_stats: dict[str, dict[str, Any]] = {}
    total_files = 0
    for label, src_root, dst_root in subsets:
        if not src_root.is_dir():
            raise FileNotFoundError(f"缺少合规子集目录: {src_root}")
        md_files = sorted(p for p in src_root.rglob("*.md") if p.is_file())
        bytes_sum = 0
        for src in md_files:
            rel = src.relative_to(src_root)
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            stage_rel = dst.relative_to(stage_dir).as_posix()
            raw_lookup[stage_rel] = src
            bytes_sum += src.stat().st_size
            total_files += 1
        subset_stats[label] = {"files": len(md_files), "bytes": bytes_sum}

    return {"total_files": total_files, "subsets": subset_stats, "raw_lookup": raw_lookup}


def _zero_hit_absent_result() -> dict[str, Any]:
    return {
        "status": "ABSENT",
        "value": None,
        "type": None,
        "reason": "NO_RETRIEVED_HITS",
        "evidence": [],
        "latency_ms": {"compile_ms": 0.0, "exec_ms": 0.0, "total_ms": 0.0},
        "skipped_verifier": True,
    }


def _attribute_miss(case: dict[str, Any], hits: list[dict[str, Any]], rec: dict[str, Any]) -> str:
    if case.get("expect_absent"):
        return "false_answer_hallucinated"
    if not hits:
        return "retrieval_zero_hits"
    sub = str(case.get("expect_path_sub") or "").lower()
    if not any(sub in str(h.get("path") or "").lower() for h in hits[:3]):
        return "retrieval_wrong_doc"
    if not any(_hit_is_relevant(h, case)[1] for h in hits[:3]):
        return "retrieval_wrong_chunk_in_doc"
    if rec.get("status") in ("ABSENT", "UNKNOWN"):
        return "reader_missed_evidence_present"
    if rec.get("status") == "REJECTED":
        return "reader_program_rejected"
    return "reader_wrong_value_or_op"


def run_e2e_rag_eval(
    repo_root: str | Path,
    *,
    port: int | None = None,
    verifier_url: str = VERIFIER_URL,
    model_key: str = DEFAULT_MODEL_KEY,
) -> dict[str, Any]:
    """Run full 3-arm E2E RAG evaluation on a merged 10,000+ chunk isolated XERJ namespace."""
    root = Path(repo_root)
    audited = compliance.audit_corpora_dir(root / "corpora")
    cases_path = root / "evals" / "e2e_rag_60.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if len(cases) != 60:
        raise ValueError(f"Expected 60 cases in {cases_path}, got {len(cases)}")

    if port is None:
        port = eval_hub._find_free_port_triplet(19830)

    tmp_root = Path(tempfile.mkdtemp(prefix="vericorpus-e2e-rag-"))
    tmp_data = tmp_root / "data"
    tmp_state = tmp_root / "state"
    tmp_stage = tmp_root / "stage"
    for d in (tmp_data, tmp_state, tmp_stage):
        d.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, XERJ_DISABLE_FEEDBACK="true", XERJ_DISABLE_QUERY_CACHE="1")
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            eval_hub.XERJ_BIN,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--data-dir",
            str(tmp_data),
            "--insecure",
            "--disable-feedback",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        for _ in range(80):
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"隔离 XERJ 启动失败 rc={proc.returncode}: {err.strip()}")
            try:
                with compliance._safe_urlopen(f"{base_url}/", timeout=1, allow_localhost_http=True) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.15)
        else:
            raise RuntimeError("隔离 XERJ 启动超时")

        staged = stage_pack_compliant_subset(root, tmp_stage)
        raw_lookup: dict[str, Path | str] = staged["raw_lookup"]

        t_idx0 = time.perf_counter()
        idx_proc = subprocess.run(
            [
                eval_hub.XERJ_BIN,
                "autoindex",
                str(tmp_stage),
                "--url",
                base_url,
                "--prefix",
                "e2e",
                "--state-dir",
                str(tmp_state),
                "--no-graph",
                "--fresh",
                "--yes",
                "--disable-feedback",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=240,
        )
        index_elapsed_ms = round((time.perf_counter() - t_idx0) * 1000.0, 1)
        if idx_proc.returncode not in (0, 3):
            raise RuntimeError(f"autoindex e2e 失败 rc={idx_proc.returncode}: {idx_proc.stderr or idx_proc.stdout}")

        with compliance._safe_urlopen(f"{base_url}/_cat/indices?format=json", timeout=5, allow_localhost_http=True) as r:
            cat_rows = json.loads(r.read().decode("utf-8"))
        e2e_indices = [row for row in cat_rows if str(row.get("index") or "").startswith("e2e-")]
        total_chunks = sum(int(row.get("docs.count") or 0) for row in e2e_indices)
        if total_chunks < 10_000:
            raise RuntimeError(f"Indexed chunks {total_chunks} < 10,000 requirement")

        verify_cache: dict[str, dict[str, Any]] = {}
        dedup_hits = 0
        total_verifier_calls = 0

        oracle_records: list[dict[str, Any]] = []
        base_records: list[dict[str, Any]] = []
        cn_records: list[dict[str, Any]] = []
        base_hits_by_id: dict[str, list[dict[str, Any]]] = {}
        cn_hits_by_id: dict[str, list[dict[str, Any]]] = {}

        for i, c in enumerate(cases, 1):
            cid = c["id"]
            q = c["question"]

            # Arm 1: Oracle Passage + Neuro-Symbolic Reader (1.7B)
            ora_doc = str(c.get("oracle_document") or "").strip()
            if not ora_doc:
                ora_res = _zero_hit_absent_result()
                ora_read_ms = 0.0
            else:
                ora_res, ora_read_ms, cached = _call_verifier(
                    ora_doc, q, verifier_url=verifier_url, model_key=model_key, cache=verify_cache
                )
                total_verifier_calls += 1
                dedup_hits += int(cached)
            oracle_records.append(
                {
                    "id": cid,
                    "doc": ora_doc,
                    "status": ora_res.get("status"),
                    "value": ora_res.get("value"),
                    "reason": ora_res.get("reason"),
                    "evidence": ora_res.get("evidence") or [],
                    "retrieval_ms": 0.0,
                    "reader_ms": ora_read_ms,
                    "total_ms": ora_read_ms,
                }
            )

            # Arm 2: Native XERJ BM25 Top-3 + Neuro-Symbolic Reader (1.7B)
            tb0 = time.perf_counter()
            b_search = _baseline_search_with_body(base_url, "e2e", q, limit=3)
            b_ret_ms = round((time.perf_counter() - tb0) * 1000.0, 2)
            b_hits = b_search["hits"]
            base_hits_by_id[cid] = b_hits
            b_doc = assemble_retrieved_context(b_hits, raw_lookup)
            if not b_hits or not b_doc.strip():
                b_res = _zero_hit_absent_result()
                b_read_ms = 0.0
            else:
                b_res, b_read_ms, cached = _call_verifier(
                    b_doc, q, verifier_url=verifier_url, model_key=model_key, cache=verify_cache
                )
                total_verifier_calls += 1
                dedup_hits += int(cached)
            base_records.append(
                {
                    "id": cid,
                    "doc": b_doc,
                    "status": b_res.get("status"),
                    "value": b_res.get("value"),
                    "reason": b_res.get("reason"),
                    "evidence": b_res.get("evidence") or [],
                    "retrieval_ms": b_ret_ms,
                    "reader_ms": b_read_ms,
                    "total_ms": round(b_ret_ms + b_read_ms, 2),
                    "hit_paths": [h["path"] for h in b_hits],
                }
            )

            # Arm 3: vericorpus Enhanced Top-3 + Neuro-Symbolic Reader (1.7B)
            tc0 = time.perf_counter()
            x_search = query_cn.search_index(base_url, "e2e", q, limit=3, scope="docs", include_body=True)
            x_ret_ms = round((time.perf_counter() - tc0) * 1000.0, 2)
            x_hits = x_search["hits"]
            cn_hits_by_id[cid] = x_hits
            x_doc = assemble_retrieved_context(x_hits, raw_lookup)
            if not x_hits or not x_doc.strip():
                x_res = _zero_hit_absent_result()
                x_read_ms = 0.0
            else:
                x_res, x_read_ms, cached = _call_verifier(
                    x_doc, q, verifier_url=verifier_url, model_key=model_key, cache=verify_cache
                )
                total_verifier_calls += 1
                dedup_hits += int(cached)
            cn_records.append(
                {
                    "id": cid,
                    "doc": x_doc,
                    "status": x_res.get("status"),
                    "value": x_res.get("value"),
                    "reason": x_res.get("reason"),
                    "evidence": x_res.get("evidence") or [],
                    "retrieval_ms": x_ret_ms,
                    "reader_ms": x_read_ms,
                    "total_ms": round(x_ret_ms + x_read_ms, 2),
                    "hit_paths": [h["path"] for h in x_hits],
                    "relaxed": x_search["relaxed"],
                }
            )
            if i % 15 == 0 or i == len(cases):
                print(f"[e2e_rag] {i}/{len(cases)} done", flush=True)

        arm1_summary = score_e2e_arm(cases, oracle_records, oracle_records=oracle_records)
        arm2_summary = score_e2e_arm(cases, base_records, oracle_records=oracle_records)
        arm3_summary = score_e2e_arm(
            cases, cn_records, oracle_records=oracle_records, baseline_records=base_records
        )

        arm2_retrieval = compute_retrieval_metrics(cases, base_hits_by_id)
        arm3_retrieval = compute_retrieval_metrics(cases, cn_hits_by_id)

        case_details: list[dict[str, Any]] = []
        error_attribution: dict[str, dict[str, int]] = {"arm1_oracle": {}, "arm2_native_bm25": {}, "arm3_vericorpus": {}}
        for c, o_rec, b_rec, x_rec in zip(cases, oracle_records, base_records, cn_records):
            cid = c["id"]
            ov = arm1_summary["verdicts"][cid]["verdict"]
            bv = arm2_summary["verdicts"][cid]["verdict"]
            xv = arm3_summary["verdicts"][cid]["verdict"]

            b_attr = "ok" if bv == "R" else _attribute_miss(c, base_hits_by_id[cid], b_rec)
            x_attr = "ok" if xv == "R" else _attribute_miss(c, cn_hits_by_id[cid], x_rec)
            o_attr = "ok" if ov == "R" else ("false_answer_hallucinated" if c.get("expect_absent") else "reader_miss")
            if o_attr != "ok":
                error_attribution["arm1_oracle"][o_attr] = error_attribution["arm1_oracle"].get(o_attr, 0) + 1
            if b_attr != "ok":
                error_attribution["arm2_native_bm25"][b_attr] = error_attribution["arm2_native_bm25"].get(b_attr, 0) + 1
            if x_attr != "ok":
                error_attribution["arm3_vericorpus"][x_attr] = error_attribution["arm3_vericorpus"].get(x_attr, 0) + 1

            case_details.append(
                {
                    "id": cid,
                    "track": c["track"],
                    "category": c["category"],
                    "ticker": c.get("ticker"),
                    "expect_absent": bool(c.get("expect_absent")),
                    "question": c["question"],
                    "expected": c["expected"],
                    "arm1_oracle": {
                        "verdict": ov,
                        "status": o_rec["status"],
                        "value": o_rec["value"],
                        "reader_ms": o_rec["reader_ms"],
                        "attribution": o_attr,
                    },
                    "arm2_native_bm25": {
                        "verdict": bv,
                        "status": b_rec["status"],
                        "value": b_rec["value"],
                        "hit_paths": b_rec["hit_paths"],
                        "retrieval_ms": b_rec["retrieval_ms"],
                        "reader_ms": b_rec["reader_ms"],
                        "attribution": b_attr,
                    },
                    "arm3_vericorpus": {
                        "verdict": xv,
                        "status": x_rec["status"],
                        "value": x_rec["value"],
                        "hit_paths": x_rec["hit_paths"],
                        "retrieval_ms": x_rec["retrieval_ms"],
                        "reader_ms": x_rec["reader_ms"],
                        "attribution": x_attr,
                    },
                }
            )

        def _strip_verdicts(s: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in s.items() if k != "verdicts"}

        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "corpora_audited": len(audited),
            "namespace": "e2e-*",
            "index_stats": {
                "total_files": staged["total_files"],
                "total_chunks": total_chunks,
                "index_elapsed_ms": index_elapsed_ms,
                "indices": [{"index": row.get("index"), "chunks": int(row.get("docs.count") or 0)} for row in e2e_indices],
                "subsets": staged["subsets"],
            },
            "verifier_calls": {
                "model_key": model_key,
                "endpoint": verifier_url,
                "logical_evaluations": total_verifier_calls,
                "unique_http_calls": total_verifier_calls - dedup_hits,
                "dedup_hits": dedup_hits,
            },
            "retrieval": {
                "arm2_native_bm25": arm2_retrieval,
                "arm3_vericorpus": arm3_retrieval,
            },
            "arms": {
                "arm1_oracle": _strip_verdicts(arm1_summary),
                "arm2_native_bm25": _strip_verdicts(arm2_summary),
                "arm3_vericorpus": _strip_verdicts(arm3_summary),
            },
            "error_attribution": error_attribution,
            "cases": case_details,
        }

        (root / "evals" / "e2e_latest_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_e2e_markdown_report(root / "E2E_BENCHMARK_REPORT.md", report)
        return report
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        shutil.rmtree(tmp_root, ignore_errors=True)


def write_e2e_markdown_report(out_path: Path, report: dict[str, Any]) -> None:
    """Render concise Chinese E2E benchmark report with R/W/N, 95% CI, retrieval, latency, and limits."""
    idx = report["index_stats"]
    arms = report["arms"]
    ret = report["retrieval"]
    a1, a2, a3 = arms["arm1_oracle"], arms["arm2_native_bm25"], arms["arm3_vericorpus"]
    r2, r3 = ret["arm2_native_bm25"], ret["arm3_vericorpus"]
    model_key = str((report.get("verifier_calls") or {}).get("model_key") or DEFAULT_MODEL_KEY)
    model_label = {
        "neuro_symbolic_reader_1_7b": "Neuro-Symbolic Reader (1.7B)",
        "neuro_symbolic_reader_1_7b_baseline": "Neuro-Symbolic Reader (1.7B, Baseline)",
    }.get(model_key, "Neuro-Symbolic Reader (1.7B)")

    def _ci_str(ci: list[float] | None) -> str:
        return f"[{ci[0]}, {ci[1]}]" if ci else "-"

    lines = [
        "# VeriCorpus 端到端双语检索与验证闭环评测报告 (`E2E_BENCHMARK_REPORT.md`)",
        "",
        "> Not Legal, Investment, or Medical Advice — strictly for retrieval benchmarking and document verification research.",
        ">",
        f"> 全部检索均在隔离单进程 `xerj`（关闭查询缓存 `XERJ_DISABLE_QUERY_CACHE=1`，单命名空间 `e2e-*`）实测完成；验证阶段通过本地标准 `http://127.0.0.1:8000/api/verify` 接口（`{model_label}`）执行，未触碰线上个人索引。",
        "",
        "## 一、合并索引规模（100% `pack` 合规子集）",
        "",
        f"- **总文件数**：`{idx['total_files']}` 份 Markdown（全部属于 `pack` 白名单合规语料）",
        f"- **XERJ 合并分块总数**：**`{idx['total_chunks']:,}` chunks**（建索耗时 `{idx['index_elapsed_ms']} ms`）",
        "- **评测题集**：`60` 题严格零泄漏盲测（`20` SEC 财报 `10 extract + 10 arithmetic` 仅限 11 家保留标的 + `10` ARM IPO 招股书 + `15` 中国法规与资本市场新规 + `15` 硬拒答陷阱）",
        f"- **审计通过语料包总数**：`{report['corpora_audited']}` 个",
        "",
        "## 二、端到端回答质量对比（XERJ `R / W / N` 与 `Net = R - 2W`，4,000 次配对 Bootstrap 95% CI）",
        "",
        "| 评测分支 (Arm) | R / W / N | Net (`R - 2W`) | Net 95% CI | Score (`% Oracle`) | Score 95% CI | 严格准确率 | `ABSENT` 误答数 | 证据偏移 100% 合法 |",
        "|---|---|---:|---|---:|---|---:|---:|---:|",
        f"| **Arm 1: Oracle Passage + {model_label}** | `{a1['R']} / {a1['W']} / {a1['N']}` | **{a1['net']}** | `{_ci_str(a1['net_ci95'])}` | `100.0` | `{_ci_str(a1['score_ci95'])}` | `{a1['strict_accuracy']*100:.1f}%` | `{a1['absent_false_answers']}` | `{a1['evidence_offsets_valid_count']}/60` |",
        f"| **Arm 2: Native XERJ BM25 Top-3 + {model_label}** | `{a2['R']} / {a2['W']} / {a2['N']}` | **{a2['net']}** | `{_ci_str(a2['net_ci95'])}` | `{a2['score_pct_of_oracle']}` | `{_ci_str(a2['score_ci95'])}` | `{a2['strict_accuracy']*100:.1f}%` | `{a2['absent_false_answers']}` | `{a2['evidence_offsets_valid_count']}/60` |",
        f"| **Arm 3: `vericorpus` Enhanced Top-3 + {model_label}** | `{a3['R']} / {a3['W']} / {a3['N']}` | **{a3['net']}** | `{_ci_str(a3['net_ci95'])}` | `{a3['score_pct_of_oracle']}` | `{_ci_str(a3['score_ci95'])}` | `{a3['strict_accuracy']*100:.1f}%` | `{a3['absent_false_answers']}` | `{a3['evidence_offsets_valid_count']}/60` |",
        "",
        f"- **Arm 3 相对 Arm 2 的配对净分差 ΔNet (95% CI)**：`{a3['net'] - a2['net']:+d}` (`{_ci_str(a3.get('delta_vs_baseline_ci95'))}`)",
    ]

    v2_base_path = out_path.parent / "evals" / "e2e_v2_baseline_report.json"
    if v2_base_path.is_file() and model_key != "neuro_symbolic_reader_1_7b_baseline":
        try:
            v2_rep = json.loads(v2_base_path.read_text(encoding="utf-8"))
            v2_arms = v2_rep.get("arms") or {}
            v2_a1 = v2_arms.get("arm1_oracle") or {}
            v2_a2 = v2_arms.get("arm2_native_bm25") or {}
            v2_a3 = v2_arms.get("arm3_vericorpus") or {}
            lines.append(
                "- **相比上代验证基线（`Neuro-Symbolic Reader (1.7B, Baseline)`）变化**："
                f"Arm 1 Net `{v2_a1.get('net')} → {a1['net']}` (`{a1['net'] - int(v2_a1.get('net', 0)):+d}`) · "
                f"Arm 2 Net `{v2_a2.get('net')} → {a2['net']}` (`{a2['net'] - int(v2_a2.get('net', 0)):+d}`) · "
                f"Arm 3 Net `{v2_a3.get('net')} → {a3['net']}` (`{a3['net'] - int(v2_a3.get('net', 0)):+d}`)"
            )
        except Exception:
            pass

    lines.extend(
        [
            "",
            "## 三、Top-3 证据块检索质量与拒答表现",
            "",
            "| 检索器 | 证据块 `R@1` | 证据块 `R@3` | `nDCG@3` | 文档级 `R@1` | 文档级 `R@3` | `15` 题陷阱 0 命中拒答率 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            f"| Native XERJ BM25 (`multi_match`) | `{r2['r_at_1']:.4f}` | `{r2['r_at_3']:.4f}` | `{r2['ndcg_at_3']:.4f}` | `{r2['doc_r_at_1']:.4f}` | `{r2['doc_r_at_3']:.4f}` | `{r2['absent_zero_hit_count']}/15 ({r2['absent_zero_hit_rate']*100:.1f}%)` |",
            f"| **`vericorpus` Enhanced BM25** | **`{r3['r_at_1']:.4f}`** | **`{r3['r_at_3']:.4f}`** | **`{r3['ndcg_at_3']:.4f}`** | **`{r3['doc_r_at_1']:.4f}`** | **`{r3['doc_r_at_3']:.4f}`** | **`{r3['absent_zero_hit_count']}/15 ({r3['absent_zero_hit_rate']*100:.1f}%)`** |",
            "",
            "## 四、分阶段延迟拆解（检索 ms vs 验证推理 ms，p50 / p95）",
            "",
            "| 分支 | 检索 `p50 / p95` (ms) | 验证端 `p50 / p95` (ms) | 端到端合计 `p50 / p95` (ms) |",
            "|---|---:|---:|---:|",
            f"| Arm 1 (Oracle) | `0.0 / 0.0` | `{a1['latency_ms']['reader_p50']} / {a1['latency_ms']['reader_p95']}` | `{a1['latency_ms']['total_p50']} / {a1['latency_ms']['total_p95']}` |",
            f"| Arm 2 (Native BM25) | `{a2['latency_ms']['retrieval_p50']} / {a2['latency_ms']['retrieval_p95']}` | `{a2['latency_ms']['reader_p50']} / {a2['latency_ms']['reader_p95']}` | `{a2['latency_ms']['total_p50']} / {a2['latency_ms']['total_p95']}` |",
            f"| Arm 3 (`vericorpus`) | `{a3['latency_ms']['retrieval_p50']} / {a3['latency_ms']['retrieval_p95']}` | `{a3['latency_ms']['reader_p50']} / {a3['latency_ms']['reader_p95']}` | `{a3['latency_ms']['total_p50']} / {a3['latency_ms']['total_p95']}` |",
            "",
            "## 五、分赛道结果与错误归因",
            "",
            "| 赛道 | Arm 1 (`R/W/N`) | Arm 2 (`R/W/N`) | Arm 3 (`R/W/N`) |",
            "|---|---|---|---|",
        ]
    )

    track_labels = {
        "sec_fin": "SEC 财报与 XBRL (20 题)",
        "arm_ipo": "ARM 硬科技 IPO 招股书 (10 题)",
        "cn_law": "中国法规与资本市场新规 (15 题)",
        "absent": "硬拒答陷阱 (15 题)",
    }
    for tk, label in track_labels.items():
        b1 = a1["by_track"].get(tk, {})
        b2 = a2["by_track"].get(tk, {})
        b3 = a3["by_track"].get(tk, {})
        lines.append(
            f"| {label} | `{b1.get('R',0)}/{b1.get('W',0)}/{b1.get('N',0)}` | `{b2.get('R',0)}/{b2.get('W',0)}/{b2.get('N',0)}` | `{b3.get('R',0)}/{b3.get('W',0)}/{b3.get('N',0)}` |"
        )

    lines.extend(["", "### 失败原因归因统计", ""])
    for arm_key, arm_label in (("arm1_oracle", "Arm 1 (Oracle)"), ("arm2_native_bm25", "Arm 2 (Native BM25)"), ("arm3_vericorpus", "Arm 3 (`vericorpus`)")):
        counts = report["error_attribution"].get(arm_key) or {}
        summary_str = ", ".join(f"`{k}`={v}" for k, v in sorted(counts.items())) if counts else "无失误"
        lines.append(f"- **{arm_label}**：{summary_str}")

    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- 本次评测仅索引了 100% `pack` 合规子集中的部分代表性年报/法典/论文（`>= 10,000` 分块），未包含受限于 `recipe` 分发模式的 A 股 CNINFO / 港股 HKEX 私有重建原文，也未索引 `sec-10y-core` 全量 48 家原始 10-K。",
            "- `60` 题评测集为人工核验构造的零泄漏评测集，样本量有限，95% Bootstrap 置信区间基于题目重抽样而非跨更大机构文档池的集群抽样。",
            "- Arm 2 与 Arm 3 仅测试纯词法 BM25（无 Dense Vector 向量索引与重排模型），跨英汉深层语义改写且未命中同义词表的问题仍可能因词法失配而退回 `ABSENT`。",
            f"- 当检索返回与 Oracle 完全一致或两分支召回相同组装上下文时，脚本对相同的 `(document, question)` 请求复用了 `http://127.0.0.1:8000/api/verify` 结果以节省本地推理时间，但延迟分位数仍按实际 `{model_label}` 推理耗时记录。",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    rep = run_e2e_rag_eval(repo)
    print(json.dumps({"index_stats": rep["index_stats"], "retrieval": rep["retrieval"], "arms": rep["arms"]}, ensure_ascii=False, indent=2))
