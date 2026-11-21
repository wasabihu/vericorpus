#!/usr/bin/env python3
"""Targeted, strictly license-audited OA paper & ClinicalTrials collector for benchmark issuer coverage."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vericorpus import compliance, science_packs  # noqa: E402


@dataclass(frozen=True)
class IndustryScienceSpec:
    ticker: str
    company_name: str
    pack: str  # "biomed-clinical-ccby" | "ai-papers-ccby"
    track: str
    ctgov_url: str | None = None
    epmc_query: str | None = None
    openalex_url: str | None = None


INDUSTRY_SCIENCE_TARGETS: tuple[IndustryScienceSpec, ...] = (
    IndustryScienceSpec(
        ticker="MRNA",
        company_name="Moderna",
        pack="biomed-clinical-ccby",
        track="Industry Biomed · Vaccines & mRNA Therapeutics (MRNA)",
        ctgov_url="https://clinicaltrials.gov/api/v2/studies?query.term=Moderna+OR+mRNA-1273+OR+mRNA-1345&filter.overallStatus=COMPLETED&aggFilters=results:with&pageSize=6",
        epmc_query='(OPEN_ACCESS:y) AND (LICENSE:"cc by") AND ("Moderna" OR "mRNA-1273" OR "mRNA-4157") AND ("clinical trial" OR "vaccine")',
    ),
    IndustryScienceSpec(
        ticker="TMO",
        company_name="Thermo Fisher",
        pack="biomed-clinical-ccby",
        track="Industry Biomed · Life Science Analytical Instruments (TMO)",
        epmc_query='(OPEN_ACCESS:y) AND (LICENSE:"cc by") AND ("Thermo Fisher") AND ("qPCR" OR "mass spectrometry" OR "cryo-EM" OR "sequencing")',
    ),
    IndustryScienceSpec(
        ticker="DHR",
        company_name="Danaher",
        pack="biomed-clinical-ccby",
        track="Industry Biomed · Molecular Diagnostics (DHR)",
        epmc_query='(OPEN_ACCESS:y) AND (LICENSE:"cc by") AND ("Danaher" OR "Cepheid" OR "Beckman Coulter") AND ("assay" OR "clinical" OR "diagnostic")',
    ),
    IndustryScienceSpec(
        ticker="TWST",
        company_name="Twist Bioscience",
        pack="biomed-clinical-ccby",
        track="Industry Biomed · Synthetic Biology & NGS (TWST)",
        epmc_query='(OPEN_ACCESS:y) AND (LICENSE:"cc by") AND ("Twist Bioscience") AND ("oligo" OR "NGS" OR "target enrichment" OR "library")',
    ),
    IndustryScienceSpec(
        ticker="BABA",
        company_name="Alibaba / Qwen",
        pack="ai-papers-ccby",
        track="Industry AI · Open Foundation Models (BABA)",
        openalex_url="https://api.openalex.org/works?filter=title.search:Qwen,open_access.is_oa:true,primary_location.license:cc-by,publication_year:%3E2022&sort=cited_by_count:desc&per-page=6",
    ),
    IndustryScienceSpec(
        ticker="NVDA",
        company_name="NVIDIA",
        pack="ai-papers-ccby",
        track="Industry AI · Accelerated Computing & Inference Systems (NVDA)",
        openalex_url="https://api.openalex.org/works?filter=title.search:NVIDIA|Megatron|TensorRT,open_access.is_oa:true,primary_location.license:cc-by,has_abstract:true,publication_year:%3E2022&sort=cited_by_count:desc&per-page=6",
    ),
)


def _default_fetch_text(url: str, timeout: float = 12.0) -> str:
    return science_packs._fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def _inject_ticker_frontmatter(md_text: str, ticker: str) -> str:
    if not md_text.startswith("---\n"):
        return md_text
    if re.search(r"(?m)^ticker\s*:", md_text):
        return md_text
    return md_text.replace("---\n", f"---\nticker: {ticker}\n", 1)


def _sync_biomed_spec(
    spec: IndustryScienceSpec,
    pack_dir: Path,
    *,
    per_target_limit: int,
    fetch_json_fn: Callable[[str], Any],
    fetch_bytes_fn: Callable[[str], bytes],
) -> tuple[int, int, int, list[str]]:
    written = 0
    table_docs = 0
    rejected = 0
    files: list[str] = []
    pack_dir.mkdir(parents=True, exist_ok=True)

    if spec.ctgov_url:
        try:
            ct_data = fetch_json_fn(spec.ctgov_url)
        except Exception:
            ct_data = {}
        ct_taken = 0
        for st in (ct_data or {}).get("studies") or []:
            if ct_taken >= per_target_limit:
                break
            formatted = science_packs.clinical_trial_to_markdown(st, track=spec.track)
            if formatted is None:
                continue
            nct_id = formatted["nct_id"]
            out_path = compliance.validate_rel_path(f"wl_{spec.ticker}_{nct_id}.md", pack_dir)
            md = _inject_ticker_frontmatter(formatted["markdown"], spec.ticker)
            out_path.write_text(md, encoding="utf-8")
            written += 1
            ct_taken += 1
            if formatted.get("tables_count", 0) > 0:
                table_docs += 1
            files.append(str(out_path))

    if spec.epmc_query:
        q_enc = urllib.parse.quote(spec.epmc_query)
        epmc_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q_enc}&format=json&resultType=idlist&pageSize=12"
        try:
            res_json = fetch_json_fn(epmc_url)
        except Exception:
            res_json = {}
        epmc_taken = 0
        for row in ((res_json or {}).get("resultList") or {}).get("result") or []:
            if epmc_taken >= per_target_limit:
                break
            pid = str(row.get("pmcid") or "").strip().upper()
            if not pid:
                continue
            if not pid.startswith("PMC"):
                pid = f"PMC{pid}"
            xml_bytes = b""
            for url in (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pid}/fullTextXML",
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pid.replace('PMC', '')}&retmode=xml",
            ):
                try:
                    raw = fetch_bytes_fn(url)
                    if raw and raw.lstrip().startswith(b"<") and b"<article" in raw:
                        xml_bytes = raw
                        break
                except Exception:
                    continue
            if not xml_bytes:
                continue
            parsed = science_packs.parse_jats_article(xml_bytes, source_url=f"https://europepmc.org/article/PMC/{pid}")
            if parsed is None:
                rejected += 1
                continue
            full_md = science_packs._with_frontmatter(
                parsed["markdown"],
                {
                    "corpus": spec.pack,
                    "license": parsed["license"],
                    "ticker": spec.ticker,
                    "doi": parsed["doi"],
                    "pmcid": parsed.get("pmcid") or pid,
                    "track": spec.track,
                    "source_url": parsed["source_url"],
                },
            )
            out_path = compliance.validate_rel_path(f"wl_{spec.ticker}_{pid}.md", pack_dir)
            out_path.write_text(full_md, encoding="utf-8")
            written += 1
            epmc_taken += 1
            if parsed.get("tables_count", 0) > 0:
                table_docs += 1
            files.append(str(out_path))

    return written, table_docs, rejected, files


def _sync_ai_spec(
    spec: IndustryScienceSpec,
    pack_dir: Path,
    *,
    per_target_limit: int,
    fetch_json_fn: Callable[[str], Any],
    fetch_bytes_fn: Callable[[str], bytes],
    fetch_text_fn: Callable[[str], str],
) -> tuple[int, int, int, list[str]]:
    if not spec.openalex_url:
        return 0, 0, 0, []
    pack_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    table_docs = 0
    rejected = 0
    files: list[str] = []

    try:
        data = fetch_json_fn(spec.openalex_url)
    except Exception:
        data = {}

    for w in (data or {}).get("results") or []:
        if written >= per_target_limit:
            break
        loc = w.get("primary_location") or {}
        oa_lic = science_packs.is_allowed_oa_license(str(loc.get("license") or ""))
        if oa_lic is None:
            rejected += 1
            continue

        title = str(w.get("title") or "Untitled").strip()
        doi = str(w.get("doi") or w.get("id") or "").strip()
        year = str(w.get("publication_year") or "").strip()
        cited = int(w.get("cited_by_count") or 0)
        author_list = [
            str((a.get("author") or {}).get("display_name") or "").strip()
            for a in (w.get("authorships") or [])[:8]
            if (a.get("author") or {}).get("display_name")
        ]
        abstract = science_packs._reconstruct_abstract(w.get("abstract_inverted_index"))
        arxiv_id = science_packs._extract_arxiv_id(w)
        final_lic = oa_lic
        source_url = str(loc.get("landing_page_url") or doi)
        tables_md: list[str] = []
        extra_body = ""

        if arxiv_id:
            abs_html: str | None = None
            paper_html: str | None = None
            try:
                abs_html = fetch_text_fn(f"https://arxiv.org/abs/{arxiv_id}")
            except Exception:
                abs_html = None
            try:
                paper_html = fetch_text_fn(f"https://arxiv.org/html/{arxiv_id}")
            except Exception:
                paper_html = None
            verified = science_packs.verify_arxiv_license(abs_html=abs_html, paper_html=paper_html)
            if verified is None:
                rejected += 1
                continue
            final_lic = verified
            source_url = f"https://arxiv.org/abs/{arxiv_id}"
            if paper_html:
                tables_md = science_packs.extract_arxiv_html_tables(paper_html, max_tables=4)
                if tables_md:
                    source_url = f"https://arxiv.org/html/{arxiv_id}"
        else:
            pmcid_raw = str((w.get("ids") or {}).get("pmcid") or "").strip()
            if pmcid_raw:
                tail = pmcid_raw.rstrip("/").split("/")[-1].upper()
                pid = tail if tail.startswith("PMC") else f"PMC{tail}"
                try:
                    xb = fetch_bytes_fn(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pid}/fullTextXML")
                except Exception:
                    xb = b""
                if xb and xb.lstrip().startswith(b"<") and b"<article" in xb:
                    parsed = science_packs.parse_jats_article(
                        xb,
                        source_url=f"https://europepmc.org/article/PMC/{pid}",
                        fallback_authors=author_list,
                    )
                    if parsed is None:
                        rejected += 1
                        continue
                    final_lic = parsed["license"]
                    tables_md = parsed["tables"]
                    extra_body = parsed["markdown"]

        if final_lic == "CC-BY-4.0" and not author_list and not extra_body:
            rejected += 1
            continue

        if extra_body:
            body = extra_body
        else:
            lines = [
                f"# {title}",
                "",
                f"- **Issuer Ticker**: {spec.ticker} ({spec.company_name})",
                f"- **DOI / OpenAlex**: {doi}",
                f"- **Year**: {year or 'N/A'} | **Cited By**: {cited}",
                f"- **Authors**: {', '.join(author_list) if author_list else spec.company_name}",
                f"- **License**: {science_packs.format_license_display(final_lic)}",
            ]
            if final_lic == "CC-BY-4.0":
                lines.append(f"- **Adaptation Notice**: {science_packs.ADAPTATION_NOTICE}")
            lines.append("")
            if abstract:
                lines.extend(["## Abstract", "", abstract, ""])
            if tables_md:
                lines.extend(["## Benchmark & Results Tables", ""])
                for tbl in tables_md:
                    lines.extend([tbl, ""])
            body = "\n".join(lines).strip() + "\n"

        slug_id = re.sub(r"[^A-Za-z0-9._-]+", "_", doi.split("doi.org/")[-1])[:40].strip("_") or f"work_{written + 1}"
        out_path = compliance.validate_rel_path(f"wl_{spec.ticker}_{slug_id}.md", pack_dir)
        full_md = science_packs._with_frontmatter(
            body,
            {
                "corpus": spec.pack,
                "license": final_lic,
                "ticker": spec.ticker,
                "doi": doi,
                "track": spec.track,
                "source_url": source_url,
            },
        )
        out_path.write_text(full_md, encoding="utf-8")
        written += 1
        if tables_md:
            table_docs += 1
        files.append(str(out_path))

    return written, table_docs, rejected, files


def sync_watchlist_science(
    out_root: Path | None = None,
    *,
    tickers: list[str] | None = None,
    per_target_limit: int = 2,
    fetch_json_fn: Callable[[str], Any] | None = None,
    fetch_bytes_fn: Callable[[str], bytes] | None = None,
    fetch_text_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Fetch strictly license-audited OA scientific/clinical documents for benchmark issuers."""
    target_root = Path(out_root) if out_root is not None else (ROOT / "data" / "raw")
    fj = fetch_json_fn or (lambda url: science_packs._fetch_json(url, timeout=18.0, retries=1))
    fb = fetch_bytes_fn or (lambda url: science_packs._fetch_bytes(url, timeout=12.0))
    ft = fetch_text_fn or _default_fetch_text

    want = {t.strip().upper() for t in tickers if t.strip()} if tickers else None
    specs = [s for s in INDUSTRY_SCIENCE_TARGETS if (want is None or s.ticker.upper() in want)]

    total_written = 0
    total_table_docs = 0
    total_rejected = 0
    per_ticker: dict[str, Any] = {}

    for spec in specs:
        compliance.validate_slug(spec.pack)
        pack_dir = compliance.validate_rel_path(spec.pack, target_root)
        if spec.pack == "biomed-clinical-ccby":
            w, td, rej, files = _sync_biomed_spec(
                spec, pack_dir, per_target_limit=per_target_limit, fetch_json_fn=fj, fetch_bytes_fn=fb
            )
        else:
            w, td, rej, files = _sync_ai_spec(
                spec,
                pack_dir,
                per_target_limit=per_target_limit,
                fetch_json_fn=fj,
                fetch_bytes_fn=fb,
                fetch_text_fn=ft,
            )
        total_written += w
        total_table_docs += td
        total_rejected += rej
        per_ticker[spec.ticker] = {
            "pack": spec.pack,
            "written": w,
            "table_docs": td,
            "rejected_non_compliant": rej,
            "files": files,
        }

    return {
        "out_root": str(target_root),
        "written": total_written,
        "table_docs": total_table_docs,
        "rejected_non_compliant": total_rejected,
        "by_ticker": per_ticker,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--tickers", nargs="*", default=None, help="Filter issuer tickers (e.g. MRNA TMO DHR TWST BABA NVDA)")
    ap.add_argument("--limit", type=int, default=2, help="Max docs per endpoint per ticker")
    args = ap.parse_args(argv)

    summary = sync_watchlist_science(Path(args.out_root), tickers=args.tickers, per_target_limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
