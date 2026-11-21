"""版权零争议 AI 论文与生物医学临床全文/试验语料自动采集、JATS/HTML 表格转换与许可防火墙模块。"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import compliance

DEFAULT_USER_AGENT = "VeriCorpus/0.1 (+https://github.com/wasabihu/vericorpus)"
CC_BY_4_URI = "https://creativecommons.org/licenses/by/4.0/"
CC0_1_URI = "https://creativecommons.org/publicdomain/zero/1.0/"
ADAPTATION_NOTICE = (
    "Excerpted and converted from open-access XML/HTML tables into structured Markdown pipe tables; "
    "cell values preserved verbatim."
)
_XML_UNSAFE_DECL_RE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def get_user_agent() -> str:
    env_ua = os.environ.get("VERICORPUS_USER_AGENT", "").strip() or os.environ.get("SEC_USER_AGENT", "").strip()
    return env_ua if env_ua else DEFAULT_USER_AGENT


_FORBIDDEN_LIC_TOKENS = (
    "-nc",
    "nc-",
    "noncommercial",
    "non-commercial",
    "-nd",
    "nd-",
    "noderiv",
    "no-deriv",
    "-sa",
    "by-sa",
    "sharealike",
    "share-alike",
    "noassertion",
    "unknown",
    "all-rights-reserved",
    "all rights reserved",
    "nonexclusive",
    "non-exclusive",
    "gpl",
    "proprietary",
)

_ARXIV_ID_RE = re.compile(r"(?:arxiv\.org/(?:abs|html|pdf)/|10\.48550/arxiv\.)(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
_ABS_LICENSE_DIV_RE = re.compile(r'<div[^>]*class="[^"]*abs-license[^"]*"[^>]*>(.*?)</div>', re.I | re.S)
_HTML_LICENSE_LINK_RE = re.compile(r'<a[^>]*id="license-tr"[^>]*>(.*?)</a>', re.I | re.S)
_LATEX_DOC_BODY_RE = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.S)


def format_license_display(lic: str) -> str:
    if lic == "CC-BY-4.0":
        return f"CC-BY-4.0 ({CC_BY_4_URI})"
    if lic == "CC0-1.0":
        return f"CC0-1.0 ({CC0_1_URI})"
    return lic


def _safe_parse_xml(xml_bytes: bytes) -> ET.Element:
    """Reject XML DOCTYPE / ENTITY declarations before parsing to prevent entity-expansion / XXE attacks."""
    if _XML_UNSAFE_DECL_RE.search(xml_bytes):
        raise ValueError("Unsafe XML declaration (DOCTYPE/ENTITY) rejected")
    return ET.fromstring(xml_bytes)


def is_allowed_oa_license(raw_license: str | None) -> str | None:
    """Validate an open-access license string strictly for commercial pack inclusion.

    Returns 'CC-BY-4.0' or 'CC0-1.0', or None if restricted (-NC/-ND/-SA/non-exclusive/missing).
    """
    text = re.sub(r"\s+", " ", (raw_license or "").strip()).lower()
    if not text:
        return None
    if any(tok in text for tok in _FORBIDDEN_LIC_TOKENS):
        return None
    if any(
        tok in text
        for tok in ("cc0", "cc-0", "publicdomain/zero/1.0", "public domain", "cc0-1.0")
    ):
        return "CC0-1.0"
    if any(
        tok in text
        for tok in (
            "cc-by-4.0",
            "cc-by",
            "cc by 4.0",
            "cc by",
            "creativecommons.org/licenses/by/4.0",
            "creativecommons.org/licenses/by/",
            "creative commons attribution 4.0",
            "creative commons attribution license",
        )
    ):
        if re.search(r"by/(?:1\.0|2\.0|2\.5|3\.0)\b", text) or re.search(r"cc[- ]by[- ](?:2\.0|3\.0)\b", text):
            return None
        return "CC-BY-4.0"
    return None


def verify_arxiv_license(abs_html: str | None = None, paper_html: str | None = None) -> str | None:
    """Verify explicit CC-BY-4.0 / CC0-1.0 on arXiv /abs or /html metadata blocks only."""
    snippets: list[str] = []
    if abs_html:
        m = _ABS_LICENSE_DIV_RE.search(abs_html)
        if m:
            snippets.append(m.group(1))
        elif "abs-license" not in abs_html and "creativecommons.org" in abs_html.lower():
            snippets.append(abs_html)
        elif "nonexclusive" in abs_html.lower() or "non-exclusive" in abs_html.lower():
            return None
    if paper_html:
        m_tr = _HTML_LICENSE_LINK_RE.search(paper_html)
        if m_tr:
            snippets.append(m_tr.group(1))
        elif "creativecommons.org/licenses/by" in paper_html.lower():
            for line in paper_html.splitlines():
                if "creativecommons.org" in line.lower():
                    snippets.append(line)

    if not snippets:
        return None

    resolved: str | None = None
    for sn in snippets:
        cleaned = re.sub(r"<[^>]+>", " ", sn)
        cand = is_allowed_oa_license(f"{sn} {cleaned}")
        if cand is None:
            return None
        resolved = cand
    return resolved


def verify_jats_ccby(root: ET.Element) -> str | None:
    """Verify JATS XML <permissions>/<license> explicitly grants CC-BY-4.0 or CC0-1.0."""
    lic_elems = [el for el in root.iter() if _local_tag(el.tag) == "license"]
    if not lic_elems:
        return None
    parts: list[str] = []
    uri_candidates: list[str] = []
    for lic in lic_elems:
        parts.append(" ".join(lic.attrib.values()))
        for el in lic.iter():
            for v in el.attrib.values():
                s = str(v)
                parts.append(s)
                if "creativecommons.org/" in s.lower():
                    uri_candidates.append(s)
            txt_el = "".join(el.itertext()).strip()
            if "creativecommons.org/" in txt_el.lower():
                for m in re.findall(r"https?://creativecommons\.org/[^\s<>\"')]+", txt_el, flags=re.I):
                    uri_candidates.append(m)
        parts.append("".join(lic.itertext()))

    if uri_candidates:
        resolved: str | None = None
        for uri in uri_candidates:
            cand = is_allowed_oa_license(uri)
            if cand is None:
                return None
            resolved = cand
        attr_blob = " ".join(str(v) for lic in lic_elems for el in lic.iter() for v in el.attrib.values()).lower()
        if any(tok in attr_blob for tok in ("-nc", "noncommercial", "-nd", "-sa")):
            return None
        return resolved

    combined = " ".join(parts)
    return is_allowed_oa_license(combined)


def _fetch_bytes(
    url: str,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    max_bytes: int = 25_000_000,
) -> bytes:
    compliance.validate_https_url(url)
    hdrs = {"User-Agent": get_user_agent()}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with compliance._safe_urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"Response exceeded {max_bytes} bytes safety limit: {url}")
        return data


def _fetch_json(url: str, timeout: float = 20.0, retries: int = 2) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = _fetch_bytes(url, timeout=timeout)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError(f"Failed to fetch JSON: {url}")


def _with_frontmatter(body: str, meta: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        clean_v = re.sub(r"\s+", " ", str(v or "")).strip()
        if clean_v:
            lines.append(f"{k}: {clean_v}")
    lines.append("---\n\n")
    return "\n".join(lines) + body.lstrip("\ufeff")


def _clean_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).replace("|", "｜").strip()


def grid_to_markdown_table(
    header_rows: list[list[tuple[str, int, int]]],
    body_rows: list[list[tuple[str, int, int]]],
    *,
    caption: str = "",
) -> str:
    """Render header and body cell-span rows into a clean GFM pipe table, suppressing empty tables."""
    if not header_rows and not body_rows:
        return ""

    def _layout(rows: list[list[tuple[str, int, int]]], repeat_colspan: bool, repeat_rowspan: bool) -> list[list[str]]:
        grid: dict[tuple[int, int], str] = {}
        max_col = 0
        for r_idx, row in enumerate(rows):
            c_idx = 0
            for text, rowspan, colspan in row:
                while (r_idx, c_idx) in grid:
                    c_idx += 1
                rs = max(1, int(rowspan or 1))
                cs = max(1, int(colspan or 1))
                clean = _clean_cell_text(text)
                for dr in range(rs):
                    for dc in range(cs):
                        if dr == 0 and dc == 0:
                            val = clean
                        elif dr > 0 and dc == 0 and repeat_rowspan:
                            val = clean
                        elif dr == 0 and dc > 0 and repeat_colspan:
                            val = clean
                        else:
                            val = ""
                        grid[(r_idx + dr, c_idx + dc)] = val
                c_idx += cs
                if c_idx > max_col:
                    max_col = c_idx
        total_rows = max((r for r, _ in grid), default=-1) + 1
        out: list[list[str]] = []
        for r in range(total_rows):
            row_vals = [grid.get((r, c), "") for c in range(max_col)]
            if any(row_vals):
                out.append(row_vals)
        return out

    h_grid = _layout(header_rows, repeat_colspan=True, repeat_rowspan=True)
    b_grid = _layout(body_rows, repeat_colspan=False, repeat_rowspan=True)

    if not h_grid and b_grid:
        h_grid = [b_grid[0]]
        b_grid = b_grid[1:]

    if not h_grid or not b_grid:
        return ""

    ncols = max(max((len(r) for r in h_grid), default=0), max((len(r) for r in b_grid), default=0))
    if ncols < 2:
        return ""

    def _pad(row: list[str]) -> list[str]:
        return row + [""] * (ncols - len(row))

    h_padded = [_pad(r) for r in h_grid]
    b_padded = [_pad(r) for r in b_grid]

    keep_cols = [
        c for c in range(ncols) if any(r[c] for r in h_padded) or any(r[c] for r in b_padded)
    ]
    if len(keep_cols) < 2:
        return ""

    headers: list[str] = []
    for c in keep_cols:
        parts: list[str] = []
        for hr in h_padded:
            val = hr[c]
            if val and val not in parts:
                parts.append(val)
        headers.append(" / ".join(parts) if parts else f"Col {c + 1}")

    body_lines: list[list[str]] = []
    for br in b_padded:
        vals = [br[c] for c in keep_cols]
        if any(vals):
            body_lines.append(vals)

    if not body_lines:
        return ""

    lines: list[str] = []
    if caption:
        lines.append(f"**{_clean_cell_text(caption)}**")
        lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in body_lines:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _jats_node_text(el: ET.Element | None, *, skip_tags: frozenset[str] = frozenset(), _depth: int = 0) -> str:
    """Extract clean human text from JATS XML node, filtering LaTeX preambles and bounding recursion depth."""
    if el is None or _depth > 80:
        return ""
    tag = _local_tag(el.tag)
    if tag in skip_tags:
        return ""
    if tag == "xref" and el.attrib.get("ref-type") == "table-fn":
        return el.tail or ""
    if tag == "alternatives":
        children = list(el)
        non_tex = [ch for ch in children if _local_tag(ch.tag) != "tex-math"]
        chosen = non_tex if non_tex else children
        parts: list[str] = []
        for ch in chosen:
            t = _jats_node_text(ch, skip_tags=skip_tags, _depth=_depth + 1)
            if t:
                parts.append(t)
        return " ".join(parts) + (el.tail or "")
    if tag == "tex-math":
        raw = "".join(el.itertext())
        m = _LATEX_DOC_BODY_RE.search(raw)
        inner = m.group(1) if m else ""
        inner = re.sub(r"\\(?:documentclass|usepackage|setlength|boldsymbol|mathbf|mathrm|mathit|text)\b(?:\[[^\]]*\])?(?:\{([^}]*)\})?", r"\1", inner)
        inner = inner.replace("$", "").replace("{", "").replace("}", "")
        return re.sub(r"\s+", " ", inner).strip() + (el.tail or "")

    chunks: list[str] = []
    if el.text:
        chunks.append(el.text)
    for ch in el:
        chunks.append(_jats_node_text(ch, skip_tags=skip_tags, _depth=_depth + 1))
    if el.tail:
        chunks.append(el.tail)
    return "".join(chunks)


def _parse_span_attr(raw: str | None) -> int:
    try:
        val = int(str(raw or "1").strip())
        return max(1, val)
    except ValueError:
        return 1


def jats_table_to_markdown(table_wrap: ET.Element) -> str:
    """Convert a JATS XML <table-wrap> element to a clean Markdown pipe table."""
    tbl = None
    for ch in table_wrap.iter():
        if _local_tag(ch.tag) == "table":
            tbl = ch
            break
    if tbl is None:
        return ""

    label_el = next((c for c in table_wrap if _local_tag(c.tag) == "label"), None)
    cap_el = next((c for c in table_wrap if _local_tag(c.tag) == "caption"), None)
    label_txt = re.sub(r"\s+", " ", _jats_node_text(label_el)).strip() if label_el is not None else ""
    cap_txt = re.sub(r"\s+", " ", _jats_node_text(cap_el)).strip() if cap_el is not None else ""
    caption = f"{label_txt}: {cap_txt}" if (label_txt and cap_txt) else (label_txt or cap_txt)

    def _extract_rows(container: ET.Element | None) -> list[list[tuple[str, int, int]]]:
        if container is None:
            return []
        rows: list[list[tuple[str, int, int]]] = []
        for tr in container:
            if _local_tag(tr.tag) != "tr":
                continue
            row: list[tuple[str, int, int]] = []
            for cell in tr:
                ctag = _local_tag(cell.tag)
                if ctag in ("th", "td"):
                    txt = re.sub(r"\s+", " ", _jats_node_text(cell)).strip()
                    rs = _parse_span_attr(cell.attrib.get("rowspan"))
                    cs = _parse_span_attr(cell.attrib.get("colspan"))
                    row.append((txt, rs, cs))
            if row:
                rows.append(row)
        return rows

    header_rows: list[list[tuple[str, int, int]]] = []
    body_rows: list[list[tuple[str, int, int]]] = []
    for child in tbl:
        ctag = _local_tag(child.tag)
        if ctag == "thead":
            header_rows.extend(_extract_rows(child))
        elif ctag == "tbody":
            body_rows.extend(_extract_rows(child))
        elif ctag == "tr":
            body_rows.extend(_extract_rows(tbl))
            break

    return grid_to_markdown_table(header_rows, body_rows, caption=caption)


def _extract_jats_authors(art: ET.Element) -> list[str]:
    """Extract author names across JATS contrib variants (with or without contrib-type='author' or namespaces)."""
    contribs = [
        el
        for el in art.iter()
        if _local_tag(el.tag) == "contrib"
        and el.attrib.get("contrib-type", "author").lower() in ("author", "")
    ]
    authors: list[str] = []
    for contrib in contribs[:8]:
        surname = ""
        given = ""
        collab = ""
        string_name = ""
        for sub in contrib.iter():
            stag = _local_tag(sub.tag)
            if stag == "surname" and not surname:
                surname = "".join(sub.itertext()).strip()
            elif stag == "given-names" and not given:
                given = "".join(sub.itertext()).strip()
            elif stag == "collab" and not collab:
                collab = "".join(sub.itertext()).strip()
            elif stag == "string-name" and not string_name:
                string_name = re.sub(r"\s+", " ", "".join(sub.itertext())).strip()
        full = f"{given} {surname}".strip() or string_name or collab
        if full and full not in authors:
            authors.append(full)
    return authors


def parse_jats_article(
    xml_bytes: bytes,
    source_url: str = "",
    *,
    fallback_authors: list[str] | None = None,
) -> dict[str, Any] | None:
    """Parse JATS full-text XML into structured Markdown with verified CC-BY-4.0/CC0-1.0 license and attribution."""
    try:
        root = _safe_parse_xml(xml_bytes)
    except (ET.ParseError, ValueError, RecursionError):
        return None

    lic = verify_jats_ccby(root)
    if lic is None:
        return None

    art = root if _local_tag(root.tag) == "article" else (next((el for el in root.iter() if _local_tag(el.tag) == "article"), root))

    def _first_id(id_type: str) -> str:
        for el in art.iter():
            if _local_tag(el.tag) == "article-id" and el.attrib.get("pub-id-type") == id_type:
                val = "".join(el.itertext()).strip()
                if val:
                    return val
        return ""

    pmcid = _first_id("pmcid")
    if pmcid and not pmcid.upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    doi = _first_id("doi")
    doi_url = f"https://doi.org/{doi}" if (doi and not doi.startswith("http")) else doi

    title_el = next((el for el in art.iter() if _local_tag(el.tag) == "article-title"), None)
    title = re.sub(r"\s+", " ", _jats_node_text(title_el)).strip() if title_el is not None else "Untitled"

    journal_el = next((el for el in art.iter() if _local_tag(el.tag) == "journal-title"), None)
    journal = re.sub(r"\s+", " ", _jats_node_text(journal_el)).strip() if journal_el is not None else "Open Access Journal"

    pub_year = ""
    for pd in art.iter():
        if _local_tag(pd.tag) == "pub-date":
            yr_el = next((c for c in pd if _local_tag(c.tag) == "year"), None)
            if yr_el is not None and "".join(yr_el.itertext()).strip().isdigit():
                pub_year = "".join(yr_el.itertext()).strip()
                break

    authors = _extract_jats_authors(art)
    if not authors and fallback_authors:
        authors = [a.strip() for a in fallback_authors if a and a.strip()]

    # CC-BY-4.0 Section 3(a)(1)(A) requires creator attribution; reject rather than emitting placeholder text.
    if lic == "CC-BY-4.0" and not authors:
        return None

    abstract_paras: list[str] = []
    for abs_el in art.iter():
        if _local_tag(abs_el.tag) == "abstract":
            if abs_el.attrib.get("abstract-type") == "graphical":
                continue
            for sub in abs_el:
                stag = _local_tag(sub.tag)
                if stag == "sec":
                    st_el = next((c for c in sub if _local_tag(c.tag) == "title"), None)
                    stitle = re.sub(r"\s+", " ", _jats_node_text(st_el)).strip() if st_el is not None else ""
                    p_txt = " ".join(
                        re.sub(r"\s+", " ", _jats_node_text(p)).strip()
                        for p in sub.iter()
                        if _local_tag(p.tag) == "p"
                    ).strip()
                    if p_txt:
                        abstract_paras.append(f"**{stitle}**: {p_txt}" if stitle else p_txt)
                elif stag == "p":
                    p_txt = re.sub(r"\s+", " ", _jats_node_text(sub)).strip()
                    if p_txt:
                        abstract_paras.append(p_txt)
    abstract_text = "\n\n".join(abstract_paras).strip()

    body_sections: list[str] = []
    table_blocks: list[str] = []
    seen_tables: set[int] = set()

    def _collect_sec(sec_el: ET.Element, depth: int = 2) -> None:
        stitle_el = next((c for c in sec_el if _local_tag(c.tag) == "title"), None)
        stitle = re.sub(r"\s+", " ", _jats_node_text(stitle_el)).strip() if stitle_el is not None else ""
        sec_low = stitle.lower()
        is_relevant_sec = (
            not stitle
            or any(
                k in sec_low
                for k in (
                    "method",
                    "result",
                    "finding",
                    "efficacy",
                    "safety",
                    "patient",
                    "trial",
                    "experiment",
                    "evaluation",
                    "benchmark",
                    "outcome",
                    "discussion",
                    "conclusion",
                    "introduction",
                    "background",
                    "statistical",
                )
            )
        )
        if any(
            k in sec_low
            for k in (
                "funding",
                "acknowledg",
                "competing interest",
                "conflict of interest",
                "author contribution",
                "ethics",
                "data availability",
                "supplementary",
            )
        ):
            is_relevant_sec = False

        paras: list[str] = []
        for ch in sec_el:
            ctag = _local_tag(ch.tag)
            if ctag == "p" and is_relevant_sec:
                ptxt = re.sub(r"\s+", " ", _jats_node_text(ch, skip_tags=frozenset({"table-wrap", "fig"}))).strip()
                if ptxt:
                    paras.append(ptxt)
                for tw in ch.iter():
                    if _local_tag(tw.tag) == "table-wrap" and id(tw) not in seen_tables:
                        seen_tables.add(id(tw))
                        md_tbl = jats_table_to_markdown(tw)
                        if md_tbl:
                            table_blocks.append(md_tbl)
            elif ctag == "table-wrap":
                if id(ch) not in seen_tables:
                    seen_tables.add(id(ch))
                    md_tbl = jats_table_to_markdown(ch)
                    if md_tbl:
                        table_blocks.append(md_tbl)
            elif ctag == "sec":
                _collect_sec(ch, min(depth + 1, 4))

        if is_relevant_sec and paras:
            hdr = f"{'#' * depth} {stitle}" if stitle else ""
            block = "\n\n".join(([hdr] if hdr else []) + paras[:8])
            body_sections.append(block)

    body_el = next((c for c in art if _local_tag(c.tag) == "body"), None)
    if body_el is not None:
        for ch in body_el:
            ctag = _local_tag(ch.tag)
            if ctag == "sec":
                _collect_sec(ch, depth=2)
            elif ctag == "table-wrap" and id(ch) not in seen_tables:
                seen_tables.add(id(ch))
                md_tbl = jats_table_to_markdown(ch)
                if md_tbl:
                    table_blocks.append(md_tbl)

    for tw in art.iter():
        if _local_tag(tw.tag) == "table-wrap" and id(tw) not in seen_tables:
            seen_tables.add(id(tw))
            md_tbl = jats_table_to_markdown(tw)
            if md_tbl:
                table_blocks.append(md_tbl)

    if not abstract_text and not body_sections and not table_blocks:
        return None

    lines = [
        f"# {title}",
        "",
        f"- **DOI / PMCID**: {doi_url or pmcid} ({pmcid or 'N/A'})",
        f"- **Journal**: {journal}",
        f"- **Published**: {pub_year or 'N/A'}",
        f"- **Authors**: {', '.join(authors) if authors else journal}",
        f"- **License**: {format_license_display(lic)}",
    ]
    if lic == "CC-BY-4.0":
        lines.append(f"- **Adaptation Notice**: {ADAPTATION_NOTICE}")
    lines.append("")

    if abstract_text:
        lines.extend(["## Abstract", "", abstract_text, ""])
    if body_sections:
        joined_body = "\n\n".join(body_sections)
        if len(joined_body) > 22000:
            joined_body = joined_body[:22000].rsplit("\n", 1)[0].strip()
        lines.extend([joined_body, ""])
    if table_blocks:
        lines.extend(["## Extracted Clinical & Benchmark Tables", ""])
        for tbl in table_blocks[:8]:
            lines.extend([tbl, ""])

    src_url = source_url or (f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else doi_url)
    return {
        "pmcid": pmcid,
        "doi": doi_url or pmcid,
        "title": title,
        "journal": journal,
        "pub_year": pub_year,
        "authors": authors,
        "license": lic,
        "abstract": abstract_text,
        "tables_count": min(len(table_blocks), 8),
        "tables": table_blocks[:8],
        "source_url": src_url,
        "markdown": "\n".join(lines).strip() + "\n",
    }


_VOID_HTML_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class _ArxivTableParser(HTMLParser):
    """Extract clean tables inside <figure class='...ltx_table...'>, skipping footnote dumps and spacer rules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figures: list[dict[str, Any]] = []
        self._in_fig = False
        self._fig_depth = 0
        self._in_caption = False
        self._cap_parts: list[str] = []
        self._in_table = False
        self._table_depth = 0
        self._in_thead = False
        self._header_rows: list[list[tuple[str, int, int]]] = []
        self._body_rows: list[list[tuple[str, int, int]]] = []
        self._curr_row: list[tuple[str, int, int]] | None = None
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._cell_rs = 1
        self._cell_cs = 1
        self._skip_depth = 0
        self._curr_tables: list[tuple[list[list[tuple[str, int, int]]], list[list[tuple[str, int, int]]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in _VOID_HTML_TAGS:
            if t == "br" and self._in_cell and self._skip_depth == 0:
                self._cell_parts.append(" ")
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        cls = attr_map.get("class", "")

        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        if t in ("script", "style", "annotation") or any(
            skip_cls in cls for skip_cls in ("ltx_note", "ltx_rule")
        ):
            self._skip_depth = 1
            return

        if not self._in_fig and t == "figure" and "ltx_table" in cls:
            self._in_fig = True
            self._fig_depth = 1
            self._cap_parts = []
            self._curr_tables = []
            return

        if self._in_fig:
            self._fig_depth += 1
            if t == "figcaption":
                self._in_caption = True
            elif t == "table" and not self._in_table:
                self._in_table = True
                self._table_depth = 1
                self._header_rows = []
                self._body_rows = []
            elif self._in_table:
                self._table_depth += 1
                if t == "thead":
                    self._in_thead = True
                elif t == "tr":
                    self._curr_row = []
                elif t in ("th", "td") and self._curr_row is not None:
                    self._in_cell = True
                    self._cell_parts = []
                    self._cell_rs = _parse_span_attr(attr_map.get("rowspan"))
                    self._cell_cs = _parse_span_attr(attr_map.get("colspan"))

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if not self._in_fig:
            return

        if t == "figcaption":
            self._in_caption = False
        elif self._in_table:
            if t in ("th", "td") and self._in_cell and self._curr_row is not None:
                txt = re.sub(r"\s+", " ", "".join(self._cell_parts)).strip()
                self._curr_row.append((txt, self._cell_rs, self._cell_cs))
                self._in_cell = False
            elif t == "tr" and self._curr_row is not None:
                if self._curr_row:
                    if self._in_thead:
                        self._header_rows.append(self._curr_row)
                    else:
                        self._body_rows.append(self._curr_row)
                self._curr_row = None
            elif t == "thead":
                self._in_thead = False
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_table = False
                self._curr_tables.append((self._header_rows, self._body_rows))

        self._fig_depth -= 1
        if self._fig_depth <= 0:
            cap = re.sub(r"\s+", " ", "".join(self._cap_parts)).strip()
            self.figures.append({"caption": cap, "tables": self._curr_tables})
            self._in_fig = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_caption:
            self._cap_parts.append(data)
        elif self._in_cell:
            self._cell_parts.append(data)


def extract_arxiv_html_tables(html_text: str, max_tables: int = 6) -> list[str]:
    """Extract clean benchmark/results Markdown pipe tables from verified CC-BY arXiv HTML."""
    parser = _ArxivTableParser()
    parser.feed(html_text)
    parser.close()

    out: list[str] = []
    for fig in parser.figures:
        cap = fig["caption"]
        for h_rows, b_rows in fig["tables"]:
            md = grid_to_markdown_table(h_rows, b_rows, caption=cap)
            if md:
                data_lines = [ln for ln in md.splitlines() if ln.startswith("|")]
                if len(data_lines) >= 4:
                    out.append(md)
                    if len(out) >= max_tables:
                        return out
    return out


def clinical_trial_to_markdown(study: dict[str, Any], track: str = "Clinical Trial") -> dict[str, Any] | None:
    """Convert a ClinicalTrials.gov API v2 completed interventional trial with posted results into CC0-1.0 Markdown."""
    if study.get("hasResults") is not True:
        return None
    ps = study.get("protocolSection") or {}
    rs = study.get("resultsSection") or {}
    if not rs:
        return None

    status = str((ps.get("statusModule") or {}).get("overallStatus") or "").upper()
    design = ps.get("designModule") or {}
    study_type = str(design.get("studyType") or "").upper()
    if status and status != "COMPLETED":
        return None
    if study_type and study_type != "INTERVENTIONAL":
        return None

    id_mod = ps.get("identificationModule") or {}
    nct_id = str(id_mod.get("nctId") or "").strip()
    if not nct_id:
        return None

    title = str(id_mod.get("officialTitle") or id_mod.get("briefTitle") or nct_id).strip()
    sponsor = str(((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name") or "NIH / Sponsor").strip()
    phases = ", ".join(design.get("phases") or []) or "N/A"
    enrollment = (design.get("enrollmentInfo") or {}).get("count")
    conditions = ", ".join((ps.get("conditionsModule") or {}).get("conditions") or []) or "N/A"
    interventions = ", ".join(
        f"{iv.get('type', '')}: {iv.get('name', '')}".strip(": ")
        for iv in ((ps.get("armsInterventionsModule") or {}).get("interventions") or [])[:8]
        if iv.get("name")
    ) or "N/A"
    summary = re.sub(r"\s+", " ", str((ps.get("descriptionModule") or {}).get("briefSummary") or "")).strip()

    source_url = f"https://clinicaltrials.gov/study/{nct_id}"
    lines = [
        f"# {title}",
        "",
        f"- **NCT ID**: {nct_id}",
        f"- **Track**: {track}",
        f"- **Sponsor**: {sponsor}",
        f"- **Status**: COMPLETED ({study_type or 'INTERVENTIONAL'}, Phase: {phases}, Enrollment: {enrollment or 'N/A'})",
        f"- **Conditions**: {conditions}",
        f"- **Interventions**: {interventions}",
        f"- **License**: CC0-1.0 ({CC0_1_URI} — US NIH ClinicalTrials.gov Public Domain)",
        "",
    ]
    if summary:
        lines.extend(["## Study Summary", "", summary, ""])

    om_list = (rs.get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []
    tables_count = 0
    if om_list:
        lines.extend(["## Posted Outcome Measures", ""])
        for om in om_list[:6]:
            om_title = str(om.get("title") or "Outcome Measure").strip()
            om_type = str(om.get("type") or "").strip()
            time_frame = str(om.get("timeFrame") or "N/A").strip()
            unit = str(om.get("unitOfMeasure") or "N/A").strip()
            groups = om.get("groups") or []
            if not groups:
                continue

            g_ids = [str(g.get("id") or "") for g in groups]
            g_titles = [str(g.get("title") or g_id) for g, g_id in zip(groups, g_ids)]

            body_rows: list[list[tuple[str, int, int]]] = []
            for cls in om.get("classes") or []:
                cls_title = str(cls.get("title") or "").strip()
                for cat in cls.get("categories") or []:
                    cat_title = str(cat.get("title") or "").strip()
                    label = " / ".join(p for p in (cls_title, cat_title) if p) or "Overall"
                    meas_by_gid: dict[str, str] = {}
                    for m in cat.get("measurements") or []:
                        gid = str(m.get("groupId") or "")
                        val = str(m.get("value") or "").strip()
                        spread = str(m.get("spread") or "").strip()
                        lo = str(m.get("lowerLimit") or "").strip()
                        hi = str(m.get("upperLimit") or "").strip()
                        if val and spread:
                            cell = f"{val} (±{spread})"
                        elif val and lo and hi:
                            cell = f"{val} ({lo}–{hi})"
                        else:
                            cell = val or str(m.get("comment") or "").strip() or "N/A"
                        if gid:
                            meas_by_gid[gid] = cell
                    if any(meas_by_gid.get(gid) for gid in g_ids):
                        row: list[tuple[str, int, int]] = [(label, 1, 1)]
                        for gid in g_ids:
                            row.append((meas_by_gid.get(gid, "-"), 1, 1))
                        body_rows.append(row)

            header_row: list[tuple[str, int, int]] = [("Category / Measure", 1, 1)] + [(gt, 1, 1) for gt in g_titles]
            tbl_md = grid_to_markdown_table([header_row], body_rows)
            if tbl_md:
                lines.append(f"### [{om_type or 'OUTCOME'}] {om_title}")
                lines.append(f"- **Time Frame**: {time_frame} | **Unit**: {unit}")
                lines.append("")
                lines.append(tbl_md)
                lines.append("")
                tables_count += 1

    ae_mod = rs.get("adverseEventsModule") or {}
    ae_groups = ae_mod.get("eventGroups") or []
    serious_events = ae_mod.get("seriousEvents") or []
    if ae_groups and serious_events:
        ae_gids = [str(g.get("id") or "") for g in ae_groups]
        ae_gtitles = [str(g.get("title") or gid) for g, gid in zip(ae_groups, ae_gids)]
        ae_rows: list[list[tuple[str, int, int]]] = []
        for ev in serious_events[:12]:
            term = str(ev.get("term") or "").strip()
            if not term:
                continue
            stats_map: dict[str, str] = {}
            for st in ev.get("stats") or []:
                gid = str(st.get("groupId") or "")
                aff = st.get("numAffected")
                at_risk = st.get("numAtRisk")
                if gid and aff is not None:
                    stats_map[gid] = f"{aff}/{at_risk}" if at_risk else str(aff)
            if stats_map:
                ae_rows.append([(term, 1, 1)] + [(stats_map.get(gid, "0"), 1, 1) for gid in ae_gids])
        if ae_rows:
            ae_hdr: list[tuple[str, int, int]] = [("Serious Adverse Event", 1, 1)] + [(t, 1, 1) for t in ae_gtitles]
            ae_md = grid_to_markdown_table([ae_hdr], ae_rows, caption="Serious Adverse Events Summary")
            if ae_md:
                lines.extend(["## Adverse Events Summary", "", ae_md, ""])
                tables_count += 1

    if tables_count == 0:
        return None

    full_md = _with_frontmatter(
        "\n".join(lines).strip() + "\n",
        {
            "corpus": "biomed-clinical-ccby",
            "license": "CC0-1.0",
            "nct_id": nct_id,
            "source_url": source_url,
            "track": track,
        },
    )
    return {
        "nct_id": nct_id,
        "license": "CC0-1.0",
        "source_url": source_url,
        "tables_count": tables_count,
        "markdown": full_md,
    }


def _reconstruct_abstract(inv_idx: dict[str, list[int]] | None) -> str:
    if not inv_idx:
        return ""
    pairs = [(pos, word) for word, positions in inv_idx.items() for pos in positions]
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs).strip()


def _extract_arxiv_id(work: dict[str, Any]) -> str | None:
    candidates = [str(work.get("doi") or "")]
    loc = work.get("primary_location") or {}
    candidates.extend([str(loc.get("landing_page_url") or ""), str(loc.get("pdf_url") or "")])
    for bloc in work.get("locations") or []:
        candidates.extend([str(bloc.get("landing_page_url") or ""), str(bloc.get("pdf_url") or "")])
    for c in candidates:
        m = _ARXIV_ID_RE.search(c)
        if m:
            return re.sub(r"v\d+$", "", m.group(1))
    return None


def _fetch_jats_xml_for_pmcid(pmcid: str) -> bytes | None:
    norm = pmcid.strip().upper()
    if not norm.startswith("PMC"):
        norm = f"PMC{norm}"
    epmc_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{norm}/fullTextXML"
    try:
        data = _fetch_bytes(epmc_url, timeout=8.0)
        if data.lstrip().startswith(b"<") and b"<article" in data:
            return data
    except Exception:
        pass

    num_id = norm.replace("PMC", "")
    ncbi_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={num_id}&retmode=xml"
    try:
        time.sleep(0.35)
        data = _fetch_bytes(ncbi_url, timeout=18.0)
        if data.lstrip().startswith(b"<") and b"<article" in data:
            return data
    except Exception:
        return None
    return None


def _batch_fetch_ncbi_jats(pmcids: list[str]) -> dict[str, bytes]:
    if not pmcids:
        return {}
    nums = [p.strip().upper().replace("PMC", "") for p in pmcids if p.strip()]
    out: dict[str, bytes] = {}
    for start in range(0, len(nums), 10):
        batch = nums[start : start + 10]
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={','.join(batch)}&retmode=xml"
        try:
            time.sleep(0.38)
            raw = _fetch_bytes(url, timeout=30.0)
            root = _safe_parse_xml(raw)
        except Exception:
            continue
        for art in root.iter():
            if _local_tag(art.tag) != "article":
                continue
            pid = ""
            for el in art.iter():
                if _local_tag(el.tag) == "article-id" and el.attrib.get("pub-id-type") == "pmcid":
                    pid = "".join(el.itertext()).strip().upper()
                    break
            if pid and not pid.startswith("PMC"):
                pid = f"PMC{pid}"
            if pid:
                out[pid] = ET.tostring(art, encoding="utf-8")
    return out


def _epmc_idlist_search(query: str, page_size: int = 30) -> list[str]:
    q_enc = urllib.parse.quote(query)
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q_enc}&format=json&resultType=idlist&pageSize={page_size}"
    data = _fetch_json(url, timeout=22.0, retries=1)
    rows = (data.get("resultList") or {}).get("result") or []
    pmcids: list[str] = []
    for r in rows:
        pid = str(r.get("pmcid") or "").strip().upper()
        if pid:
            pmcids.append(pid if pid.startswith("PMC") else f"PMC{pid}")
    return pmcids


def _epmc_core_search(query: str, page_size: int = 20) -> list[dict[str, Any]]:
    q_enc = urllib.parse.quote(query)
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q_enc}&format=json&resultType=core&pageSize={page_size}"
    data = _fetch_json(url, timeout=22.0, retries=1)
    return list((data.get("resultList") or {}).get("result") or [])


def _topup_ai_from_epmc(
    query: str,
    track: str,
    slug: str,
    needed: int,
    seen_keys: set[str],
    out_dir: Path,
    docs_written_start: int,
) -> tuple[int, int, int, int]:
    if needed <= 0 or not query:
        return 0, 0, 0, 0
    taken = 0
    chars = 0
    tbl_docs = 0
    rejected = 0
    try:
        pmcids = _epmc_idlist_search(query, page_size=max(20, needed * 3))
        xml_map = _batch_fetch_ncbi_jats(pmcids[: max(15, needed * 2)])
    except Exception:
        return 0, 0, 0, 0

    for pid in pmcids:
        if taken >= needed:
            break
        xb = xml_map.get(pid)
        if not xb:
            continue
        parsed = parse_jats_article(xb, source_url=f"https://europepmc.org/article/PMC/{pid}")
        if parsed is None:
            rejected += 1
            continue
        dedup_key = str(parsed["doi"] or pid).lower()
        if dedup_key in seen_keys or pid.lower() in seen_keys:
            continue
        seen_keys.add(dedup_key)
        seen_keys.add(pid.lower())
        idx = docs_written_start + taken + 1
        fname = f"{idx:02d}_{pid}.md"
        dest = compliance.validate_rel_path(fname, out_dir)
        full = _with_frontmatter(
            parsed["markdown"],
            {
                "corpus": slug,
                "license": parsed["license"],
                "doi": parsed["doi"],
                "pmcid": pid,
                "track": track,
                "source_url": parsed["source_url"],
            },
        )
        dest.write_text(full, encoding="utf-8")
        chars += len(full)
        if parsed["tables_count"] > 0:
            tbl_docs += 1
        taken += 1
    return taken, chars, tbl_docs, rejected


def materialize_ai_papers(manifest: dict[str, Any], out_dir: Path, force: bool = False) -> dict[str, Any]:
    """Materialize >= 45 verified CC-BY-4.0 / CC0-1.0 2022-2026 AI papers across 5 tracks."""
    compliance.validate_manifest(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.md"))
    if len(existing) >= 45 and not force:
        return {"slug": manifest["slug"], "files": len(existing), "skipped": 0, "chars": sum(p.stat().st_size for p in existing)}

    for p in existing:
        p.unlink()

    seen_keys: set[str] = set()
    docs_written = 0
    total_chars = 0
    enriched_tables_docs = 0
    rejected_non_compliant = 0

    for qcfg in manifest.get("query_filters", []):
        target_n = int(qcfg.get("count", 10))
        track = str(qcfg.get("track") or qcfg.get("name") or "AI")
        taken = 0

        works: list[dict[str, Any]] = []
        used_epmc_fallback = False
        try:
            data = _fetch_json(str(qcfg["url"]), timeout=20.0, retries=2)
            works = list(data.get("results") or [])
        except Exception:
            used_epmc_fallback = True

        if used_epmc_fallback or not works:
            fb_q = str(qcfg.get("fallback_epmc_query") or manifest.get("fallback_epmc_query") or "")
            add_n, add_c, add_t, add_r = _topup_ai_from_epmc(
                fb_q, track, manifest["slug"], target_n - taken, seen_keys, out_dir, docs_written
            )
            docs_written += add_n
            total_chars += add_c
            enriched_tables_docs += add_t
            rejected_non_compliant += add_r
            continue

        for w in works:
            if taken >= target_n:
                break
            wid = str(w.get("id") or "").strip()
            doi = str(w.get("doi") or wid).strip()
            dedup_key = doi.lower() or wid.lower()
            if not dedup_key or dedup_key in seen_keys:
                continue

            loc = w.get("primary_location") or {}
            oa_lic = is_allowed_oa_license(str(loc.get("license") or ""))
            if oa_lic is None:
                rejected_non_compliant += 1
                continue

            abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
            if len(abstract) < 80:
                continue

            title = str(w.get("title") or "Untitled").strip()
            year = str(w.get("publication_year") or "").strip()
            cited = int(w.get("cited_by_count") or 0)
            journal = str((loc.get("source") or {}).get("display_name") or "Open Access").strip()
            author_list = [
                str((a.get("author") or {}).get("display_name") or "").strip()
                for a in (w.get("authorships") or [])[:8]
                if (a.get("author") or {}).get("display_name")
            ]

            arxiv_id = _extract_arxiv_id(w)
            pmcid_raw = str((w.get("ids") or {}).get("pmcid") or "").strip()
            pmcid = ""
            if pmcid_raw:
                tail = pmcid_raw.rstrip("/").split("/")[-1].upper()
                pmcid = tail if tail.startswith("PMC") else f"PMC{tail}"

            final_lic = oa_lic
            tables_md: list[str] = []
            extra_body = ""
            source_url = str(w.get("id") or doi)

            if arxiv_id:
                abs_html: str | None = None
                paper_html: str | None = None
                try:
                    abs_html = _fetch_bytes(f"https://arxiv.org/abs/{arxiv_id}", timeout=10.0).decode("utf-8", errors="replace")
                except Exception:
                    abs_html = None
                try:
                    paper_html = _fetch_bytes(f"https://arxiv.org/html/{arxiv_id}", timeout=12.0).decode("utf-8", errors="replace")
                except Exception:
                    paper_html = None

                verified_arxiv = verify_arxiv_license(abs_html=abs_html, paper_html=paper_html)
                if verified_arxiv is None:
                    rejected_non_compliant += 1
                    continue
                final_lic = verified_arxiv
                source_url = f"https://arxiv.org/abs/{arxiv_id}"
                if paper_html:
                    tables_md = extract_arxiv_html_tables(paper_html, max_tables=4)
                    if tables_md:
                        source_url = f"https://arxiv.org/html/{arxiv_id}"
                        enriched_tables_docs += 1

            elif pmcid:
                xb = _fetch_jats_xml_for_pmcid(pmcid)
                if xb:
                    parsed = parse_jats_article(
                        xb,
                        source_url=f"https://europepmc.org/article/PMC/{pmcid}",
                        fallback_authors=author_list,
                    )
                    if parsed is None:
                        rejected_non_compliant += 1
                        continue
                    final_lic = parsed["license"]
                    tables_md = parsed["tables"]
                    if tables_md:
                        enriched_tables_docs += 1
                    extra_body = parsed["markdown"]

            if final_lic == "CC-BY-4.0" and not author_list and not extra_body:
                rejected_non_compliant += 1
                continue

            seen_keys.add(dedup_key)
            docs_written += 1

            if extra_body:
                body = extra_body
            else:
                lines = [
                    f"# {title}",
                    "",
                    f"- **Track**: {track}",
                    f"- **DOI / OpenAlex**: {doi}",
                    f"- **Journal / Venue**: {journal}",
                    f"- **Year**: {year} | **Cited By**: {cited}",
                    f"- **Authors**: {', '.join(author_list) if author_list else journal}",
                    f"- **License**: {format_license_display(final_lic)}",
                ]
                if final_lic == "CC-BY-4.0":
                    lines.append(f"- **Adaptation Notice**: {ADAPTATION_NOTICE}")
                lines.extend(["", "## Abstract", "", abstract, ""])
                if tables_md:
                    lines.extend(["## Benchmark & Results Tables", ""])
                    for tbl in tables_md:
                        lines.extend([tbl, ""])
                body = "\n".join(lines).strip() + "\n"

            slug_id = re.sub(r"[^A-Za-z0-9._-]+", "_", doi.split("doi.org/")[-1])[:48].strip("_") or f"ai_{docs_written}"
            fname = f"{docs_written:02d}_{slug_id}.md"
            dest = compliance.validate_rel_path(fname, out_dir)
            meta = {
                "corpus": manifest["slug"],
                "license": final_lic,
                "doi": doi,
                "track": track,
                "source_url": source_url,
            }
            if pmcid:
                meta["pmcid"] = pmcid
            full = _with_frontmatter(body, meta)
            dest.write_text(full, encoding="utf-8")
            total_chars += len(full)
            taken += 1

        if taken < target_n:
            fb_q = str(qcfg.get("fallback_epmc_query") or manifest.get("fallback_epmc_query") or "")
            add_n, add_c, add_t, add_r = _topup_ai_from_epmc(
                fb_q, track, manifest["slug"], target_n - taken, seen_keys, out_dir, docs_written
            )
            docs_written += add_n
            total_chars += add_c
            enriched_tables_docs += add_t
            rejected_non_compliant += add_r

    return {
        "slug": manifest["slug"],
        "files": docs_written,
        "skipped": 0,
        "rejected_non_compliant": rejected_non_compliant,
        "enriched_table_docs": enriched_tables_docs,
        "chars": total_chars,
    }


def materialize_biomed_clinical(manifest: dict[str, Any], out_dir: Path, force: bool = False) -> dict[str, Any]:
    """Materialize >= 45 verified biomedical/clinical docs (>= 30 EPMC/PMC JATS XML + >= 15 ClinicalTrials.gov CC0)."""
    compliance.validate_manifest(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.md"))
    if len(existing) >= 45 and not force:
        return {"slug": manifest["slug"], "files": len(existing), "skipped": 0, "chars": sum(p.stat().st_size for p in existing)}

    for p in existing:
        p.unlink()

    seen_pmcids: set[str] = set()
    seen_ncts: set[str] = set()
    docs_written = 0
    epmc_docs = 0
    ct_docs = 0
    table_docs = 0
    total_chars = 0
    rejected_non_compliant = 0

    for qcfg in manifest.get("epmc_queries", []):
        target_n = int(qcfg.get("count", 8))
        track = str(qcfg.get("track") or qcfg.get("name") or "Clinical")
        query = str(qcfg["query"])

        pmcids: list[str] = []
        try:
            pmcids = _epmc_idlist_search(query, page_size=30)
        except Exception:
            pmcids = []

        candidates = [p for p in pmcids if p not in seen_pmcids]
        if not candidates:
            continue

        xml_by_pid: dict[str, bytes] = {}
        fallback_pids: list[str] = []
        for pid in candidates[:4]:
            try:
                xb = _fetch_bytes(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pid}/fullTextXML", timeout=6.0)
                if xb.lstrip().startswith(b"<") and b"<article" in xb:
                    xml_by_pid[pid] = xb
                else:
                    fallback_pids.append(pid)
            except Exception:
                fallback_pids.append(pid)
        fallback_pids.extend(candidates[4:22])
        if len(xml_by_pid) < target_n + 4 and fallback_pids:
            xml_by_pid.update(_batch_fetch_ncbi_jats(fallback_pids))

        parsed_items: list[dict[str, Any]] = []
        for pid in candidates:
            xb = xml_by_pid.get(pid)
            if not xb:
                continue
            parsed = parse_jats_article(xb, source_url=f"https://europepmc.org/article/PMC/{pid}")
            if parsed is None:
                rejected_non_compliant += 1
                continue
            parsed["pmcid"] = parsed.get("pmcid") or pid
            parsed_items.append(parsed)

        parsed_items.sort(key=lambda item: (item["tables_count"] > 0, item["tables_count"]), reverse=True)

        taken = 0
        for item in parsed_items:
            if taken >= target_n:
                break
            pid = item["pmcid"]
            if pid in seen_pmcids:
                continue
            seen_pmcids.add(pid)
            docs_written += 1
            epmc_docs += 1
            if item["tables_count"] > 0:
                table_docs += 1
            fname = f"{docs_written:02d}_{pid}.md"
            dest = compliance.validate_rel_path(fname, out_dir)
            full = _with_frontmatter(
                item["markdown"],
                {
                    "corpus": manifest["slug"],
                    "license": item["license"],
                    "doi": item["doi"],
                    "pmcid": pid,
                    "track": track,
                    "source_url": item["source_url"],
                },
            )
            dest.write_text(full, encoding="utf-8")
            total_chars += len(full)
            taken += 1

    for ctcfg in manifest.get("clinicaltrials_queries", []):
        target_n = int(ctcfg.get("count", 5))
        track = str(ctcfg.get("track") or ctcfg.get("name") or "Clinical Trial")
        try:
            data = _fetch_json(str(ctcfg["url"]), timeout=20.0, retries=2)
        except Exception:
            continue

        taken = 0
        for st in data.get("studies") or []:
            if taken >= target_n:
                break
            formatted = clinical_trial_to_markdown(st, track=track)
            if formatted is None:
                continue
            nct_id = formatted["nct_id"]
            if nct_id in seen_ncts:
                continue
            seen_ncts.add(nct_id)
            docs_written += 1
            ct_docs += 1
            if formatted["tables_count"] > 0:
                table_docs += 1
            fname = f"{docs_written:02d}_{nct_id}.md"
            dest = compliance.validate_rel_path(fname, out_dir)
            dest.write_text(formatted["markdown"], encoding="utf-8")
            total_chars += len(formatted["markdown"])
            taken += 1

    return {
        "slug": manifest["slug"],
        "files": docs_written,
        "epmc_papers": epmc_docs,
        "clinicaltrials_studies": ct_docs,
        "table_docs": table_docs,
        "skipped": 0,
        "rejected_non_compliant": rejected_non_compliant,
        "chars": total_chars,
    }
