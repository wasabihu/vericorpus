"""合规语料自动拉取、溯源头注入与 PDF 表格预处理落盘器（强制 HTTPS 白名单与 pathgate 沙箱边界）。"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import compliance, pdf_table_fix

DEFAULT_USER_AGENT = "VeriCorpus/0.1 (+https://github.com/wasabihu/vericorpus)"
_SEC_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_safe_urlopen = compliance._safe_urlopen


def require_sec_user_agent() -> str:
    """Validate and return SEC_USER_AGENT containing a real contact email per SEC Fair Access Policy."""
    sec_ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not sec_ua or not _SEC_EMAIL_RE.search(sec_ua) or sec_ua.lower().endswith(".local"):
        raise RuntimeError(
            "SEC EDGAR requests require SEC_USER_AGENT with a valid contact email "
            "(e.g. export SEC_USER_AGENT='YourOrg contact@domain.com')."
        )
    return sec_ua


def get_user_agent(url: str = "") -> str:
    """Resolve HTTP User-Agent dynamically; enforce email-bearing SEC_USER_AGENT on sec.gov endpoints."""
    if "sec.gov" in (url or "").lower():
        return require_sec_user_agent()
    env_ua = os.environ.get("VERICORPUS_USER_AGENT", "").strip() or os.environ.get("SEC_USER_AGENT", "").strip()
    return env_ua if env_ua else DEFAULT_USER_AGENT


def _encode_url(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(raw_url)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/@:")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _fetch_bytes(url: str, timeout: float = 15.0, max_bytes: int = 25_000_000) -> bytes:
    encoded = _encode_url(url)
    compliance.validate_https_url(encoded)
    req = urllib.request.Request(encoded, headers={"User-Agent": get_user_agent(url)})
    with _safe_urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"Remote response exceeded {max_bytes} bytes safety limit: {url}")
        return data


def _with_provenance_header(text: str, meta: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        clean_v = str(v).replace("\n", " ").strip()
        lines.append(f"{k}: {clean_v}")
    lines.append("---\n\n")
    return "\n".join(lines) + text.lstrip("\ufeff")


def _reconstruct_abstract(inv_idx: dict[str, list[int]] | None) -> str:
    if not inv_idx:
        return ""
    pairs = [(pos, word) for word, positions in inv_idx.items() for pos in positions]
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs).strip()


def _materialize_url_pack(manifest: dict[str, Any], out_dir: Path, force: bool = False) -> dict[str, Any]:
    compliance.validate_manifest(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    skipped = 0
    total_chars = 0

    for item in manifest.get("sources", []):
        name = str(item["name"])
        url = str(item["url"])
        dest = compliance.validate_rel_path(name, out_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and not force and dest.stat().st_size > 100:
            text = dest.read_text(encoding="utf-8", errors="replace")
            saved.append(name)
            total_chars += len(text)
            continue

        raw_text = _fetch_bytes(url).decode("utf-8", errors="replace")
        if not raw_text.strip():
            skipped += 1
            continue
        tagged = _with_provenance_header(
            raw_text,
            {
                "corpus": manifest["slug"],
                "license": str(item.get("license") or manifest["license"]),
                "source_url": url,
                "upstream_repo": str(item.get("repo") or (manifest.get("upstream_mirror") or {}).get("repo") or ""),
                "commit": str(item.get("commit") or (manifest.get("upstream_mirror") or {}).get("commit") or ""),
            },
        )
        dest.write_text(tagged, encoding="utf-8")
        saved.append(name)
        total_chars += len(tagged)

    return {"slug": manifest["slug"], "files": len(saved), "skipped": skipped, "chars": total_chars}


def _materialize_openalex_science(manifest: dict[str, Any], out_dir: Path, force: bool = False) -> dict[str, Any]:
    compliance.validate_manifest(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.md"))
    if len(existing) >= 35 and not force:
        total_chars = sum(p.stat().st_size for p in existing)
        return {"slug": manifest["slug"], "files": len(existing), "skipped": 0, "chars": total_chars}

    seen_ids: set[str] = set()
    papers: list[dict[str, Any]] = []
    for qcfg in manifest.get("query_filters", []):
        target_n = int(qcfg.get("count", 20))
        data = json.loads(_fetch_bytes(str(qcfg["url"]), timeout=20.0).decode("utf-8"))
        taken = 0
        for work in data.get("results", []):
            wid = str(work.get("id") or work.get("doi") or "")
            if not wid or wid in seen_ids:
                continue
            loc = work.get("primary_location") or {}
            lic = str(loc.get("license") or "").lower()
            if lic not in ("cc-by", "cc0", "cc-by-4.0"):
                continue
            authors_chk = [
                str((a.get("author") or {}).get("display_name") or "").strip()
                for a in (work.get("authorships") or [])[:8]
                if (a.get("author") or {}).get("display_name")
            ]
            if lic != "cc0" and not authors_chk:
                continue
            abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
            if len(abstract) < 80:
                continue
            seen_ids.add(wid)
            papers.append(work)
            taken += 1
            if taken >= target_n:
                break

    total_chars = 0
    for idx, w in enumerate(papers, 1):
        doi = str(w.get("doi") or w.get("id") or "")
        title = str(w.get("title") or "Untitled").strip()
        year = w.get("publication_year") or ""
        cited = w.get("cited_by_count") or 0
        journal = str(((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "Open Access Journal")
        authors = ", ".join(
            str((a.get("author") or {}).get("display_name") or "")
            for a in (w.get("authorships") or [])[:8]
            if (a.get("author") or {}).get("display_name")
        )
        abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
        slug_id = re.sub(r"[^A-Za-z0-9._-]+", "_", doi.split("doi.org/")[-1])[:48].strip("_") or f"paper_{idx}"
        fname = f"{idx:02d}_{slug_id}.md"
        dest = compliance.validate_rel_path(fname, out_dir)

        body = (
            f"# {title}\n\n"
            f"- **DOI / OpenAlex**: {doi}\n"
            f"- **期刊 / 来源**: {journal}\n"
            f"- **发表年份**: {year} ｜ **被引次数**: {cited}\n"
            f"- **作者**: {authors}\n"
            f"- **开放许可**: CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)\n\n"
            f"## 摘要与核心发现\n\n{abstract}\n"
        )
        full = _with_provenance_header(
            body,
            {
                "corpus": manifest["slug"],
                "license": "CC-BY-4.0",
                "doi": doi,
                "source_url": str(w.get("id") or doi),
            },
        )
        dest.write_text(full, encoding="utf-8")
        total_chars += len(full)

    return {"slug": manifest["slug"], "files": len(papers), "skipped": 0, "chars": total_chars}


def _materialize_recipe_disclosures(
    manifest: dict[str, Any],
    out_dir: Path,
    *,
    repo_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    compliance.validate_manifest(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_root = (repo_root if repo_root is not None else out_dir.parents[2]).resolve()
    pdf_reports: list[dict[str, Any]] = []
    files_done = 0
    total_chars = 0

    for item in manifest.get("sources", []):
        local_raw = item.get("local_path")
        if not local_raw:
            continue
        src_path = compliance.validate_rel_path(str(local_raw), base_root)
        if not src_path.is_file():
            continue
        name = str(item["name"])
        compliance.validate_rel_path(name)
        if src_path.suffix.lower() == ".pdf":
            rebuilt_name = f"{Path(name).stem}_rebuilt.md"
            dest_md = compliance.validate_rel_path(rebuilt_name, out_dir)
            rep = pdf_table_fix.extract_pdf_to_markdown(src_path, fix_cmap=True)
            if not dest_md.is_file() or force:
                tagged = _with_provenance_header(
                    rep["markdown"],
                    {
                        "corpus": manifest["slug"],
                        "license": str(item.get("license") or manifest["license"]),
                        "mode": "recipe-local-only",
                        "source_file": src_path.name,
                        "tables_rebuilt": str(rep["tables_total"]),
                    },
                )
                dest_md.write_text(tagged, encoding="utf-8")
            total_chars += len(rep["markdown"])
            files_done += 1
            pdf_reports.append(
                {
                    "name": name,
                    "source_file": src_path.name,
                    "pages_total": rep["pages_total"],
                    "tables_total": rep["tables_total"],
                    "detached_number_rows": rep["detached_number_rows"],
                    "cmap_fixes": rep["cmap_fixes"],
                    "rebuilt_md": str(dest_md),
                }
            )
        else:
            dest_file = compliance.validate_rel_path(name, out_dir)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if not dest_file.is_file() or force:
                shutil.copy2(src_path, dest_file)
            total_chars += dest_file.stat().st_size
            files_done += 1

    return {
        "slug": manifest["slug"],
        "files": files_done,
        "chars": total_chars,
        "pdf_repairs": pdf_reports,
    }


def materialize_all(repo_root: str | Path, force: bool = False) -> dict[str, Any]:
    """先执行全库合规审计，再将语料拉取并重建到被 .gitignore 隔离的 data/raw/ 下。"""
    root = Path(repo_root).resolve()
    corpora_dir = root / "corpora"
    raw_root = root / "data" / "raw"

    audited = compliance.audit_corpora_dir(corpora_dir)
    summaries: dict[str, Any] = {}
    for entry in audited:
        slug = compliance.validate_slug(entry["slug"])
        manifest = json.loads(Path(entry["manifest_path"]).read_text(encoding="utf-8"))
        out_dir = compliance.validate_rel_path(slug, raw_root)
        if slug == "cn-science-ccby":
            summaries[slug] = _materialize_openalex_science(manifest, out_dir, force=force)
        elif slug == "ai-papers-ccby":
            from . import science_packs

            summaries[slug] = science_packs.materialize_ai_papers(manifest, out_dir, force=force)
        elif slug == "biomed-clinical-ccby":
            from . import science_packs

            summaries[slug] = science_packs.materialize_biomed_clinical(manifest, out_dir, force=force)
        elif slug == "sec-10y-core":
            existing_md = list(out_dir.rglob("*.md")) if out_dir.is_dir() else []
            if existing_md and not force:
                summaries[slug] = {
                    "slug": slug,
                    "files": len(existing_md),
                    "chars": sum(p.stat().st_size for p in existing_md),
                }
            else:
                from . import financial_10y

                if not (corpora_dir / "cn-hk-financial-10y" / "filing_catalog.json").is_file():
                    m = financial_10y.build_master_registry(root)
                    financial_10y.build_filing_catalog(root, master=m)
                financial_10y.materialize_sec_xbrl(root, force=force)
                f_res = financial_10y.materialize_sec_filings(root, force=force)
                summaries[slug] = {
                    "slug": slug,
                    "files": f_res["downloaded"] + f_res["skipped"],
                    "chars": f_res["total_bytes"],
                }
        elif slug == "cn-hk-financial-10y":
            existing_md = list(out_dir.rglob("*.md")) if out_dir.is_dir() else []
            summaries[slug] = {
                "slug": slug,
                "mode": "recipe",
                "files": len(existing_md),
                "chars": sum(p.stat().st_size for p in existing_md),
            }
        elif slug == "sec-ipo-prospectus-pack":
            existing_md = list(out_dir.rglob("*.md")) if out_dir.is_dir() else []
            if existing_md and not force:
                summaries[slug] = {
                    "slug": slug,
                    "files": len(existing_md),
                    "chars": sum(p.stat().st_size for p in existing_md),
                }
            else:
                from . import ipo_prospectus

                summaries[slug] = ipo_prospectus.materialize_sec_ipo_pack(root, force=force)
        elif slug == "cn-hk-ipo-prospectus-recipe":
            existing_md = list(out_dir.rglob("*.md")) if out_dir.is_dir() else []
            summaries[slug] = {
                "slug": slug,
                "mode": "recipe",
                "files": len(existing_md),
                "chars": sum(p.stat().st_size for p in existing_md),
            }
        elif manifest["mode"] == "recipe":
            summaries[slug] = _materialize_recipe_disclosures(manifest, out_dir, repo_root=root, force=force)
        else:
            summaries[slug] = _materialize_url_pack(manifest, out_dir, force=force)

    return {"audited": audited, "materialized": summaries}
