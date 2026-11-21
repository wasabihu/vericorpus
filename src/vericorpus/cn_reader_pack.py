"""Standalone SEC public-filing QA benchmark exporter with strict held-out ticker isolation and character-offset grounding."""
from __future__ import annotations

import hashlib
import json
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_HELDOUT_TICKERS: frozenset[str] = frozenset(
    {"BABA", "GS", "JNJ", "JPM", "MRNA", "MSFT", "OXY", "TSM", "WFC", "XOM", "ARM"}
)

XBRL_COLUMNS = [
    ("revenue", "营业收入", "Revenue"),
    ("gross_profit", "毛利润", "Gross Profit"),
    ("op_income", "营业利润", "Operating Income"),
    ("net_income", "净利润", "Net Income"),
    ("eps", "摊薄每股收益", "Diluted EPS"),
    ("rnd", "研发费用", "R&D Expense"),
    ("ocf", "经营性现金流", "Operating Cash Flow"),
    ("capex", "资本开支", "CapEx"),
    ("cash", "现金及等价物", "Cash & Equivalents"),
    ("assets", "总资产", "Total Assets"),
    ("equity", "股东权益", "Stockholders Equity"),
]

_CELL_NUM_RE = re.compile(r"^\s*([A-Z]{2,4})\s+([+-]?[\d,]+(?:\.\d+)?)([MBK]?)(?:\s*\([^)]+\))?\s*$")
_FILING_NUM_RE = re.compile(r"^\$?\(?[\d,]+(?:\.\d+)?\)?$")
_METRIC_ROW_RE = re.compile(
    r"^(Revenue|Total revenue|Cost of revenue|Gross profit|Gross margin|Research and development|Operating expenses|"
    r"Total operating expenses|Operating income(?:\s*\(loss\))?|Net income(?:\s*\(loss\))?|Net loss|"
    r"Basic and diluted|Cash and cash equivalents|Total assets|Total stockholders|Total liabilities)\b",
    re.IGNORECASE,
)


_PIPE_BORDER_RE = re.compile(r"^\|(.*)\|$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


def _split_pipe_row(line: str) -> list[str]:
    """Split a Markdown pipe row stripping at most one leading and one trailing pipe so '|| 2025 |' keeps col 0."""
    inner = _PIPE_BORDER_RE.sub(r"\1", line.strip())
    return [c.replace(r"\|", "|").strip() for c in _UNESCAPED_PIPE_RE.split(inner)]


def sha256_norm(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def strip_frontmatter(md_text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    body = md_text
    if md_text.startswith("---\n"):
        end = md_text.find("\n---\n", 4)
        if end != -1:
            for line in md_text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = md_text[end + 5 :]
    return meta, body.strip()


def read_sec_markdown(md_path: Path) -> tuple[dict[str, str], str]:
    raw = md_path.read_text(encoding="utf-8", errors="ignore")
    meta, body = strip_frontmatter(raw)
    lic = meta.get("license") or ""
    if lic != "SEC-Public-Filing":
        raise ValueError(f"版权隔离拦截：{md_path} 的 license={lic!r}，仅允许 SEC-Public-Filing")
    return meta, body


def _format_decimal(dec: Decimal) -> str:
    norm = dec.normalize()
    text = format(norm, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _locate_quote(doc: str, quote: str, context: str | None = None) -> dict[str, Any] | None:
    if not quote:
        return None
    search_start = 0
    if context:
        ctx_idx = doc.find(context)
        if ctx_idx != -1:
            search_start = ctx_idx
    idx = doc.find(quote, search_start)
    if idx == -1 and search_start > 0:
        idx = doc.find(quote)
    if idx == -1:
        return None
    end = idx + len(quote)
    if doc[idx:end] != quote:
        return None
    return {"start": idx, "end": end, "quote": quote}


def _make_answer_sample(
    doc: str,
    question: str,
    *,
    value: Decimal,
    quotes: list[tuple[str, str | None]],
    ticker: str,
    category: str,
    language: str,
    domain: str,
    source_track: str,
) -> dict[str, Any] | None:
    evidence: list[dict[str, Any]] = []
    for q, ctx in quotes:
        ev = _locate_quote(doc, q, ctx)
        if ev is None:
            return None
        evidence.append(ev)
    if not evidence:
        return None
    return {
        "document": doc,
        "question": question,
        "expected": {
            "status": "ANSWER",
            "value": _format_decimal(value),
            "type": "number",
            "evidence": evidence,
        },
        "ticker": ticker,
        "category": category,
        "language": language,
        "domain": domain,
        "source_track": source_track,
        "license": "SEC-Public-Filing",
    }


def _make_absent_sample(
    doc: str,
    question: str,
    *,
    ticker: str,
    language: str,
    domain: str,
    source_track: str,
) -> dict[str, Any]:
    return {
        "document": doc,
        "question": question,
        "expected": {
            "status": "ABSENT",
            "value": None,
            "type": "absent",
            "evidence": [],
        },
        "ticker": ticker,
        "category": "absent",
        "language": language,
        "domain": domain,
        "source_track": source_track,
        "license": "SEC-Public-Filing",
    }


def _parse_xbrl_cell(raw_cell: str) -> dict[str, Any] | None:
    s = raw_cell.strip()
    if not s or s == "-":
        return None
    m = _CELL_NUM_RE.match(s)
    if not m:
        return None
    cur, num_str, suffix = m.group(1), m.group(2), m.group(3)
    try:
        dec = Decimal(num_str.replace(",", ""))
    except InvalidOperation:
        return None
    unit_zh = {"M": "百万", "B": "十亿", "K": "千", "": ""}.get(suffix, "")
    cur_zh = {"USD": "美元", "RMB": "人民币", "HKD": "港元", "EUR": "欧元"}.get(cur, cur)
    return {
        "currency": cur,
        "num_str": num_str,
        "suffix": suffix,
        "decimal": dec,
        "quote": f"{cur} {num_str}{suffix}".strip(),
        "unit_zh": f"{unit_zh}{cur_zh}" if unit_zh else cur_zh,
    }


def extract_samples_from_xbrl_text(
    md_text: str,
    *,
    ticker: str,
    company_zh: str,
    company_en: str,
    source_track: str,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    rng = rng or random.Random(20261120)
    _, body = strip_frontmatter(md_text)
    tlines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(tlines) < 4:
        return []
    rows: list[dict[str, Any]] = []
    for rl in tlines[2:]:
        cells = _split_pipe_row(rl)
        if len(cells) < 13 or not re.match(r"^\d{4}-\d{2}-\d{2}$", cells[0]):
            continue
        metrics = {k: _parse_xbrl_cell(cells[idx]) for idx, (k, _, _) in enumerate(XBRL_COLUMNS, start=1)}
        rows.append({"fy": cells[0], "raw_line": rl, "metrics": metrics})
    if len(rows) < 2:
        return []

    label = f"{company_zh}({ticker})" if company_zh else ticker
    col_meta = {k: (zh, en) for k, zh, en in XBRL_COLUMNS}
    out: list[dict[str, Any]] = []
    for start in range(0, max(1, len(rows) - 1), 2):
        win = rows[start : start + 4]
        if len(win) < 2:
            continue
        doc = (
            f"# {company_zh} ({company_en} / {ticker}) — SEC 官方 XBRL 审计财务摘要\n"
            f"{tlines[0]}\n{tlines[1]}\n" + "\n".join(r["raw_line"] for r in win)
        )
        all_quotes = [
            r["metrics"][k]["quote"]
            for r in win
            for k, _, _ in XBRL_COLUMNS
            if r["metrics"].get(k) is not None
        ]

        r0 = win[0]
        avail = [k for k, _, _ in XBRL_COLUMNS if r0["metrics"].get(k) is not None]
        if avail:
            k = rng.choice(avail)
            c = r0["metrics"][k]
            zh_n, _ = col_meta[k]
            ctx = r0["raw_line"][:48] if all_quotes.count(c["quote"]) > 1 else None
            q_zh = f"{label}在 {r0['fy']} 财年的{zh_n}（{c['unit_zh']}）披露为多少？"
            s = _make_answer_sample(
                doc,
                q_zh,
                value=c["decimal"],
                quotes=[(c["quote"], ctx)],
                ticker=ticker,
                category="extract",
                language="zh",
                domain=f"{source_track}-xbrl",
                source_track=source_track,
            )
            if s is not None:
                out.append(s)

        r1 = win[1]
        common = [
            k
            for k, _, _ in XBRL_COLUMNS
            if k != "eps"
            and r0["metrics"].get(k)
            and r1["metrics"].get(k)
            and r0["metrics"][k]["currency"] == r1["metrics"][k]["currency"]
            and r0["metrics"][k]["suffix"] == r1["metrics"][k]["suffix"]
            and r0["metrics"][k]["quote"] != r1["metrics"][k]["quote"]
        ]
        if common:
            k = rng.choice(common)
            c0, c1 = r0["metrics"][k], r1["metrics"][k]
            zh_n, _ = col_meta[k]
            ctx0 = r0["raw_line"][:48] if all_quotes.count(c0["quote"]) > 1 else None
            ctx1 = r1["raw_line"][:48] if all_quotes.count(c1["quote"]) > 1 else None
            q_sub = f"{label} {r0['fy']} 财年的{zh_n}相比 {r1['fy']} 财年变化了多少（{c0['unit_zh']}，新减去旧）？"
            s_sub = _make_answer_sample(
                doc,
                q_sub,
                value=c0["decimal"] - c1["decimal"],
                quotes=[(c0["quote"], ctx0), (c1["quote"], ctx1)],
                ticker=ticker,
                category="arithmetic",
                language="zh",
                domain=f"{source_track}-xbrl",
                source_track=source_track,
            )
            if s_sub is not None:
                out.append(s_sub)

        missing_k = [k for k, _, _ in XBRL_COLUMNS if r0["metrics"].get(k) is None]
        if missing_k:
            mk = missing_k[0]
            zh_n, _ = col_meta[mk]
            q_abs = f"{label} 在 {r0['fy']} 财年的「{zh_n}」在该摘要表中披露为多少？"
        else:
            q_abs = f"{label} 在 2005 财年的营业收入在该摘要表中披露为多少？"
        out.append(
            _make_absent_sample(
                doc,
                q_abs,
                ticker=ticker,
                language="zh",
                domain=f"{source_track}-xbrl",
                source_track=source_track,
            )
        )
    return out


def _extract_year_labels(table_lines: list[str]) -> list[str]:
    years: list[str] = []
    for ln in table_lines[:5]:
        found = re.findall(r"\b(20[12]\d)\b", ln)
        if len(found) >= 2:
            years = found
    return years


def _clean_filing_quote(cell: str) -> tuple[str, Decimal] | None:
    s = cell.strip()
    if not s or not _FILING_NUM_RE.match(s) or "%" in s:
        return None
    if re.fullmatch(r"20[12]\d", s):
        return None
    neg = s.startswith("(") or s.startswith("$(")
    raw_num = s.replace("$", "").replace("(", "").replace(")", "").replace(",", "").strip()
    if not raw_num:
        return None
    try:
        dec = Decimal(raw_num)
    except InvalidOperation:
        return None
    if neg:
        dec = -dec
    quote = s if len(s) <= 28 else raw_num
    return quote, dec


def extract_samples_from_filing_text(
    md_text: str,
    *,
    ticker: str,
    company_zh: str,
    company_en: str,
    form: str,
    fiscal_year: str,
    source_track: str,
    max_per_file: int = 8,
) -> list[dict[str, Any]]:
    _, body = strip_frontmatter(md_text)
    lines = body.splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if ln.strip().startswith("|"):
            cur.append(ln.strip())
        else:
            if len(cur) >= 5:
                blocks.append(cur)
            cur = []
    if len(cur) >= 5:
        blocks.append(cur)

    label = f"{company_zh}({ticker})" if company_zh else ticker
    out: list[dict[str, Any]] = []
    seen_docs: set[str] = set()

    for tbl in blocks:
        if len(out) >= max_per_file:
            break
        if len(tbl) > 28:
            tbl = tbl[:26]
        years = _extract_year_labels(tbl)
        if len(years) < 2:
            continue
        unit_hint = next((ln for ln in tbl[:6] if "million" in ln.lower() or "thousand" in ln.lower()), "")
        doc = f"# {company_zh} ({company_en} / {ticker}) {fiscal_year} {form}\n" + "\n".join(tbl)
        if len(doc) < 180 or len(doc) > 2600 or doc in seen_docs:
            continue
        seen_docs.add(doc)

        parsed_rows: list[tuple[str, list[tuple[str, Decimal]]]] = []
        for rl in tbl:
            if rl.startswith("| ---") or re.match(r"^\|\s*:?-{2,}", rl):
                continue
            cells = _split_pipe_row(rl)
            if len(cells) < 3:
                continue
            metric = cells[0].strip()
            if not _METRIC_ROW_RE.search(metric):
                continue
            vals = []
            for c in cells[1 : 1 + len(years)]:
                q_dec = _clean_filing_quote(c)
                if q_dec is not None:
                    vals.append(q_dec)
            if len(vals) >= 2 and vals[0][0] != vals[1][0]:
                parsed_rows.append((metric, vals))

        if not parsed_rows:
            continue

        metric, vals = parsed_rows[0]
        q0, d0 = vals[0]
        q1, d1 = vals[1]
        y0, y1 = years[0], years[1]
        if doc.count(q0) != 1 or doc.count(q1) != 1:
            continue

        quote0 = q0.lstrip("$") if q0.startswith("$(") else q0
        quote1 = q1.lstrip("$") if q1.startswith("$(") else q1

        q_val = (
            f"根据 {label} {fiscal_year} {form} 表格"
            f"{('（' + unit_hint.strip('| ') + '）') if unit_hint else ''}，{y0} 期的「{metric}」数值是多少？"
        )
        s_val = _make_answer_sample(
            doc,
            q_val,
            value=d0,
            quotes=[(quote0, None)],
            ticker=ticker,
            category="extract",
            language="zh",
            domain=f"{source_track}-filing",
            source_track=source_track,
        )
        if s_val is not None:
            out.append(s_val)

        q_sub = f"计算 {label} {form} 表中「{metric}」在 {y0} 与 {y1} 之间的差额（{y0} 减去 {y1}）。"
        s_sub = _make_answer_sample(
            doc,
            q_sub,
            value=d0 - d1,
            quotes=[(quote0, None), (quote1, None)],
            ticker=ticker,
            category="arithmetic",
            language="zh",
            domain=f"{source_track}-filing",
            source_track=source_track,
        )
        if s_sub is not None:
            out.append(s_sub)

        q_abs = f"该 {label} {form} 节选表格中，2009 年的「{metric}」披露为多少？"
        out.append(
            _make_absent_sample(
                doc,
                q_abs,
                ticker=ticker,
                language="zh",
                domain=f"{source_track}-filing",
                source_track=source_track,
            )
        )

    return out[:max_per_file]


def build_sec_benchmark_pack(
    *,
    sec_10y_dir: Path,
    sec_ipo_dir: Path,
    out_dir: Path,
    heldout_tickers: frozenset[str] = DEFAULT_HELDOUT_TICKERS,
    max_dev: int = 400,
    max_eval: int = 160,
    seed: int = 202611203,
) -> dict[str, Any]:
    """Export zero-leakage SEC QA benchmark datasets (dev + held-out eval) from SEC-Public-Filing Markdown."""
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_dev: list[dict[str, Any]] = []
    raw_eval: list[dict[str, Any]] = []

    def _route(samples: list[dict[str, Any]], ticker: str) -> None:
        for s in samples:
            if ticker in heldout_tickers:
                raw_eval.append(s)
            else:
                raw_dev.append(s)

    xbrl_files = sorted((sec_10y_dir / "xbrl_summaries").glob("*.md")) + sorted(sec_ipo_dir.glob("*/*_xbrl_summary.md"))
    for path in xbrl_files:
        meta, _ = read_sec_markdown(path)
        tk = meta.get("ticker") or path.stem.split("_")[0]
        track = meta.get("corpus") or "sec-10y-core"
        samples = extract_samples_from_xbrl_text(
            path.read_text(encoding="utf-8", errors="ignore"),
            ticker=tk,
            company_zh=meta.get("company_zh") or "",
            company_en=meta.get("company_en") or "",
            source_track=track,
            rng=rng,
        )
        _route(samples, tk)

    filing_files = sorted((sec_10y_dir / "filings").rglob("*.md")) + [
        p for p in sorted(sec_ipo_dir.rglob("*.md")) if not p.name.endswith("_xbrl_summary.md")
    ]
    for path in filing_files:
        meta, _ = read_sec_markdown(path)
        tk = meta.get("ticker") or path.parent.name
        track = meta.get("corpus") or "sec-10y-core"
        samples = extract_samples_from_filing_text(
            path.read_text(encoding="utf-8", errors="ignore"),
            ticker=tk,
            company_zh=meta.get("company_zh") or "",
            company_en=meta.get("company_en") or "",
            form=meta.get("form") or "10-K",
            fiscal_year=meta.get("fiscal_year") or "",
            source_track=track,
            max_per_file=6 if track == "sec-10y-core" else 12,
        )
        _route(samples, tk)

    eval_hashes = {sha256_norm(s["document"]) for s in raw_eval}
    rng.shuffle(raw_dev)
    rng.shuffle(raw_eval)

    eval_final = raw_eval[:max_eval]
    for s in eval_final:
        eval_hashes.add(sha256_norm(s["document"]))

    dev_clean = [
        s
        for s in raw_dev
        if sha256_norm(s["document"]) not in eval_hashes and s["ticker"] not in heldout_tickers
    ][:max_dev]

    (out_dir / "dev_sec_qa_benchmark.json").write_text(
        json.dumps(dev_clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "eval_sec_ipo_heldout.json").write_text(
        json.dumps(eval_final, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "license": "SEC-Public-Filing",
        "dev_benchmark_count": len(dev_clean),
        "eval_heldout_count": len(eval_final),
        "dev_tickers_count": len({s["ticker"] for s in dev_clean}),
        "heldout_tickers": sorted(heldout_tickers),
        "by_track": {
            "sec_10y_core": sum(1 for s in dev_clean if s["source_track"] == "sec-10y-core"),
            "sec_ipo_prospectus_pack": sum(1 for s in dev_clean if s["source_track"] == "sec-ipo-prospectus-pack"),
        },
        "by_category": {
            cat: sum(1 for s in dev_clean if s["category"] == cat)
            for cat in ("extract", "arithmetic", "absent")
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    sec_10y_dir = repo_root / "data" / "raw" / "sec-10y-core"
    sec_ipo_dir = repo_root / "data" / "raw" / "sec-ipo-prospectus-pack"
    out_dir = repo_root / "data" / "sec_benchmark_pack"
    manifest = build_sec_benchmark_pack(
        sec_10y_dir=sec_10y_dir,
        sec_ipo_dir=sec_ipo_dir,
        out_dir=out_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
