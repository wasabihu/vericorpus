"""基于几何坐标的 PDF 表格重建与 HKEX CMap 审计修复工具（核心纯标准库；PDF 解析按需延迟加载可选 PyMuPDF）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef（）【】《》、，。：；｜]")
_NO_SPACE_AFTER = frozenset("+-($￥¥€£（【《[")
_NO_SPACE_BEFORE = frozenset("%％.,，、）)】》)]")

# Strict month/date CMap repair: every alternative ends at '尸' and excludes forensic/corpse compounds.
_CMAP_SHI_YUE_RE = re.compile(
    r"(?:"
    r"(?:(?:19|20)\d{2}|[零〇一二三四五六七八九]{4})\s*年\s*(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十])\s*尸"
    r"|(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十])\s*尸(?=\s*(?:[0-3]?\d|[零〇一二三四五六七八九十]{1,3})\s*[日號号])"
    r"|[零〇一二三四五六七八九十兩两几幾0-9]+\s*[個个]\s*尸"
    r"|(?<![殭僵丧喪陈陳验驗分暴抛拋浮女男古干乾死藏移焚])(?:(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十]|[上本下每])\s*)?尸(?=活躍|活跃|份|底|末|度|均|初|結|结|報|报|薪)"
    r"|(?<![殭僵丧喪陈陳验驗分暴抛拋浮女男古干乾死藏移焚])每\s*尸"
    r"|(?<![殭僵丧喪陈陳验驗分暴抛拋浮女男古干乾死藏移焚])(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十])\s*尸(?=止|起)"
    r")(?![检檢体體首骨骸斑僵解源毒臭布袋床房位素]|[两兩]命)"
)


class CMapRepairResult(tuple):
    """Tuple `(repaired_text, fix_count)` that also compares equal to `repaired_text`."""

    text: str
    fixes: int

    def __new__(cls, text: str, fixes: int) -> "CMapRepairResult":
        obj = super().__new__(cls, (text, fixes))
        obj.text = text
        obj.fixes = fixes
        return obj

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self[0] == other
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        if isinstance(other, str):
            return self[0] != other
        return super().__ne__(other)


def _require_pymupdf() -> Any:
    """Lazy-import optional PyMuPDF (AGPL-3.0) only when opening PDF files."""
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImportError(
            "PyMuPDF is optional (AGPL-3.0). Install via: pip install 'vericorpus[pdf]'"
        ) from exc
    if pymupdf is None:
        raise ImportError(
            "PyMuPDF is optional (AGPL-3.0). Install via: pip install 'vericorpus[pdf]'"
        )
    return pymupdf


def _should_join_without_space(prev: str, nxt: str) -> bool:
    last_ch = prev[-1]
    first_ch = nxt[0]
    if _CJK_CHAR_RE.match(last_ch) or _CJK_CHAR_RE.match(first_ch):
        return True
    if last_ch in _NO_SPACE_AFTER or first_ch in _NO_SPACE_BEFORE:
        return True
    if last_ch == "." and first_ch.isdigit():
        return True
    if last_ch == "," and first_ch.isdigit() and len(prev) >= 2 and prev[-2].isdigit():
        return True
    return False


def normalize_cell(raw: str) -> str:
    """合并表格单元格内的硬折行：中文字词、小数点及会计负数括号无缝拼接，英文单词间补单空格。"""
    text = (raw or "").replace("\u00a0", " ").strip()
    if not text:
        return ""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""

    merged = lines[0]
    for nxt in lines[1:]:
        if _should_join_without_space(merged, nxt):
            merged += nxt
        else:
            merged += " " + nxt
    return re.sub(r"[ \t]+", " ", merged).replace("|", "｜").strip()


def repair_hkex_cmap(text: str) -> CMapRepairResult:
    """针对港交所 PDF 常见的 ToUnicode CMap 错字（月份语境 '月'->'尸'）做严格白名单修复。"""
    if not text or "尸" not in text:
        return CMapRepairResult(text, 0)
    fixed, count = _CMAP_SHI_YUE_RE.subn(lambda m: m.group(0)[:-1] + "月", text)
    return CMapRepairResult(fixed, count)


def _extract_page_chars(page: Any) -> list[tuple[float, float, float, float, str, float]]:
    """提取页面全部可见字符及其真实外接框，供单元格几何聚类使用（避免官方 extract 丢小数点）。"""
    chars: list[tuple[float, float, float, float, str, float]] = []
    raw_dict = page.get_text("rawdict")
    for blk in raw_dict.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                sz = float(sp.get("size") or 10.0)
                for ch in sp.get("chars", []):
                    c = ch.get("c", "")
                    bbox = ch.get("bbox")
                    if not c or not bbox:
                        continue
                    chars.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]), c, sz))
    return chars


def _chars_to_lines_text(items: list[tuple[float, float, float, float, str, float]]) -> str:
    """两阶段视觉中心聚类：使用真实算术平均字号确立行基线，再将矮小标点吸附到最近行，按 x0 拼行。"""
    if not items:
        return ""

    tall = sorted(
        [c for c in items if (c[3] - c[1]) >= c[5] * 0.45],
        key=lambda c: ((c[1] + c[3]) * 0.5, c[0]),
    )
    tiny = [c for c in items if (c[3] - c[1]) < c[5] * 0.45]

    lines: list[list[Any]] = []  # [yc_sum, count, y1_sum, sz_sum, items]
    for c in tall:
        _x0, y0, _x1, y1, _ch, sz = c
        yc = (y0 + y1) * 0.5
        best = None
        best_dist = 1e9
        for ln in lines:
            lyc = ln[0] / ln[1]
            avg_sz = ln[3] / ln[1]
            tol = max(sz, avg_sz, 6.0) * 0.45
            dist = abs(yc - lyc)
            if dist <= tol and dist < best_dist:
                best = ln
                best_dist = dist
        if best is not None:
            best[0] += yc
            best[1] += 1
            best[2] += y1
            best[3] += sz
            best[4].append(c)
        else:
            lines.append([yc, 1, y1, sz, [c]])

    for c in tiny:
        _x0, y0, _x1, y1, _ch, sz = c
        yc = (y0 + y1) * 0.5
        best = None
        best_dist = 1e9
        for ln in lines:
            lyc = ln[0] / ln[1]
            ly1 = ln[2] / ln[1]
            avg_sz = ln[3] / ln[1]
            tol = max(sz, avg_sz, 6.0) * 0.65
            dist = min(abs(y1 - ly1), abs(yc - lyc))
            if dist <= tol and dist < best_dist:
                best = ln
                best_dist = dist
        if best is not None:
            best[4].append(c)
        else:
            lines.append([yc, 1, y1, sz, [c]])

    lines.sort(key=lambda ln: ln[0] / ln[1])
    out_lines: list[str] = []
    for ln in lines:
        litems = sorted(ln[4], key=lambda c: c[0])
        buf: list[str] = []
        prev_x1: float | None = None
        for x0, _y0, x1, _y1, ch, sz in litems:
            if (
                prev_x1 is not None
                and (x0 - prev_x1) > sz * 0.35
                and not ch.isspace()
                and (buf and not buf[-1].isspace())
            ):
                buf.append(" ")
            buf.append(ch)
            prev_x1 = x1
        txt = "".join(buf).strip()
        if txt:
            out_lines.append(txt)
    return "\n".join(out_lines)


def _assign_chars_to_cells(
    chars: list[tuple[float, float, float, float, str, float]],
    cell_grid: list[list[tuple[float, float, float, float] | None]],
    pad: float = 1.5,
) -> list[list[list[tuple[float, float, float, float, str, float]]]]:
    """Assign each character uniquely to its best-matching cell so shared borders never duplicate digits."""
    buckets: list[list[list[tuple[float, float, float, float, str, float]]]] = [
        [[] for _ in row] for row in cell_grid
    ]
    indexed_cells: list[tuple[int, int, float, float, float, float]] = []
    for r_idx, row in enumerate(cell_grid):
        for c_idx, cell in enumerate(row):
            if cell is not None:
                indexed_cells.append((r_idx, c_idx, float(cell[0]), float(cell[1]), float(cell[2]), float(cell[3])))

    for ch in chars:
        mx = (ch[0] + ch[2]) * 0.5
        my = (ch[1] + ch[3]) * 0.5
        best_rc: tuple[int, int] | None = None
        best_key: tuple[int, float] | None = None
        for r_idx, c_idx, cx0, cy0, cx1, cy1 in indexed_cells:
            if not (cx0 - pad <= mx <= cx1 + pad and cy0 - pad <= my <= cy1 + pad):
                continue
            strict_inside = 0 if (cx0 <= mx <= cx1 and cy0 <= my <= cy1) else 1
            dx = max(0.0, cx0 - mx, mx - cx1)
            dy = max(0.0, cy0 - my, my - cy1)
            key = (strict_inside, dx * dx + dy * dy)
            if best_key is None or key < best_key:
                best_key = key
                best_rc = (r_idx, c_idx)
        if best_rc is not None:
            buckets[best_rc[0]][best_rc[1]].append(ch)
    return buckets


def _is_dangling_cell_continuation(prev_cell: str, cur_cell: str) -> bool:
    if not prev_cell or not cur_cell:
        return False
    if prev_cell[-1] in ".,+-($￥¥€£（":
        return True
    if prev_cell.count("(") > prev_cell.count(")") and ")" in cur_cell:
        return True
    if prev_cell.count("（") > prev_cell.count("）") and "）" in cur_cell:
        return True
    if cur_cell[0] in ".,%％)）" and prev_cell[-1].isdigit():
        return True
    return False


def _merge_dangling_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    """Merge rows over-split by PyMuPDF virtual horizontal lines across wrapped decimals or parentheses."""
    if len(rows) <= 2:
        return rows
    merged: list[list[str]] = [rows[0]]
    for r in rows[1:]:
        if len(merged) >= 2 and not r[0] and any(r):
            prev = merged[-1]
            active_cols = [idx for idx, val in enumerate(r) if val]
            if active_cols and all(prev[idx] for idx in active_cols) and any(
                _is_dangling_cell_continuation(prev[idx], r[idx]) for idx in active_cols
            ):
                for idx in active_cols:
                    prev[idx] = normalize_cell(f"{prev[idx]}\n{r[idx]}")
                continue
        merged.append(list(r))
    return merged


def _table_to_markdown(chars: list[tuple[float, float, float, float, str, float]], table: Any) -> tuple[str, int]:
    """将 PyMuPDF Table 对象经几何坐标重建为标准 Markdown 表格，并返回孤立纯数字行估计数。"""
    cell_grid: list[list[tuple[float, float, float, float] | None]] = [
        [tuple(float(v) for v in cell) if cell is not None else None for cell in row.cells]
        for row in table.rows
    ]
    buckets = _assign_chars_to_cells(chars, cell_grid)
    matrix: list[list[str]] = []
    for r_idx, row in enumerate(cell_grid):
        cells = [
            normalize_cell(_chars_to_lines_text(buckets[r_idx][c_idx])) if cell is not None else ""
            for c_idx, cell in enumerate(row)
        ]
        if any(cells):
            matrix.append(cells)

    if not matrix:
        return "", 0

    col_count = max(len(r) for r in matrix)
    for r in matrix:
        while len(r) < col_count:
            r.append("")

    keep_cols = [idx for idx in range(col_count) if any(r[idx] for r in matrix)]
    if not keep_cols:
        return "", 0

    cleaned = _merge_dangling_continuation_rows([[r[idx] for idx in keep_cols] for r in matrix])
    if len(cleaned) < 2 and len(keep_cols) < 2:
        return "", 0

    detached_num_rows = 0
    for r in cleaned:
        non_empty = [c for c in r if c]
        if non_empty and not r[0] and all(re.fullmatch(r"[\d,.\-+()%$￥\s/]+", c) for c in non_empty):
            detached_num_rows += 1

    header = cleaned[0]
    if not any(header):
        header = [f"列{i + 1}" for i in range(len(keep_cols))]
    sep = ["---" for _ in keep_cols]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for r in cleaned[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines), detached_num_rows


def _inside_any_bbox(blk_bbox: tuple[float, float, float, float], tab_bboxes: list[tuple[float, float, float, float]]) -> bool:
    bx0, by0, bx1, by1 = blk_bbox
    area = max(1e-3, (bx1 - bx0) * (by1 - by0))
    for tx0, ty0, tx1, ty1 in tab_bboxes:
        ix0 = max(bx0, tx0 - 2.0)
        iy0 = max(by0, ty0 - 2.0)
        ix1 = min(bx1, tx1 + 2.0)
        iy1 = min(by1, ty1 + 2.0)
        if ix1 > ix0 and iy1 > iy0:
            inter = (ix1 - ix0) * (iy1 - iy0)
            if inter / area >= 0.45:
                return True
    return False


def _block_to_markdown(blk: dict[str, Any]) -> str:
    """将非表格文本块恢复为干净段落文本（避免单行断裂并保持标点顺序）。"""
    chars: list[tuple[float, float, float, float, str, float]] = []
    for ln in blk.get("lines", []):
        for sp in ln.get("spans", []):
            sz = float(sp.get("size") or 10.0)
            for ch in sp.get("chars", []):
                c = ch.get("c", "")
                bbox = ch.get("bbox")
                if c and bbox:
                    chars.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]), c, sz))
    raw_txt = _chars_to_lines_text(chars)
    if not raw_txt:
        return ""
    lines = [ln.strip() for ln in raw_txt.splitlines() if ln.strip()]
    if not lines:
        return ""
    out = [lines[0]]
    for nxt in lines[1:]:
        prev = out[-1]
        if prev.endswith((":", "：", "。", "！", "？", "；")) or re.match(r"^(\d+\.|[-•*]|第[一二三四五六七八九十\d]+[、.章条])", nxt):
            out.append(nxt)
        elif _should_join_without_space(prev, nxt):
            out[-1] = prev + nxt
        else:
            out[-1] = prev + " " + nxt
    return "\n\n".join(out)


def extract_page_to_markdown(
    page: Any,
    page_no: int,
    total_pages: int,
    *,
    fix_cmap: bool = True,
    use_layout: bool = True,
) -> dict[str, Any]:
    """将单个 PyMuPDF Page 经表格坐标重建与 CMap 修复转为 Markdown。"""
    chars = _extract_page_chars(page)
    try:
        finder = page.find_tables(use_layout=use_layout)
    except TypeError:
        finder = page.find_tables()
    valid_tables = [t for t in finder.tables if t.row_count >= 2 and t.col_count >= 2]
    tab_bboxes = [tuple(float(v) for v in t.bbox) for t in valid_tables]

    items: list[tuple[float, float, str]] = []
    tables_count = 0
    detached_num_rows = 0
    for tab in valid_tables:
        md_tab, detached = _table_to_markdown(chars, tab)
        if md_tab:
            tables_count += 1
            detached_num_rows += detached
            tx0, ty0, _tx1, _ty1 = tab.bbox
            items.append((float(ty0), float(tx0), md_tab))

    raw_dict = page.get_text("rawdict")
    for blk in raw_dict.get("blocks", []):
        if blk.get("type") != 0:
            continue
        bbox = tuple(float(v) for v in blk.get("bbox", (0, 0, 0, 0)))
        if _inside_any_bbox(bbox, tab_bboxes):
            continue
        txt = _block_to_markdown(blk)
        if txt:
            items.append((bbox[1], bbox[0], txt))

    items.sort(key=lambda it: (round(it[0], 1), round(it[1], 1)))
    page_body = "\n\n".join(it[2] for it in items)
    cmap_fixes = 0
    if fix_cmap:
        page_body, cmap_fixes = repair_hkex_cmap(page_body)

    page_md = f"<!-- page: {page_no}/{total_pages} -->\n## 第 {page_no} 页\n\n{page_body}".strip()
    return {
        "page": page_no,
        "tables": tables_count,
        "detached_number_rows": detached_num_rows,
        "cmap_fixes": cmap_fixes,
        "markdown": page_md,
    }


def extract_pdf_to_markdown(pdf_path: str | Path, fix_cmap: bool = True) -> dict[str, Any]:
    """按视觉坐标重建整份 PDF（标准 Markdown 表格 + 按 (y0, x0) 排序的正文 + 页码锚点）。"""
    pymupdf = _require_pymupdf()
    path = Path(pdf_path)
    doc = pymupdf.open(str(path))
    total_pages = len(doc)
    pages_out: list[dict[str, Any]] = []
    total_tables = 0
    total_detached_num_rows = 0
    total_cmap_fixes = 0

    try:
        for p_idx in range(total_pages):
            p_res = extract_page_to_markdown(doc[p_idx], p_idx + 1, total_pages, fix_cmap=fix_cmap)
            total_tables += p_res["tables"]
            total_detached_num_rows += p_res["detached_number_rows"]
            total_cmap_fixes += p_res["cmap_fixes"]
            pages_out.append(
                {
                    "page": p_res["page"],
                    "tables": p_res["tables"],
                    "markdown": p_res["markdown"],
                }
            )
    finally:
        doc.close()

    full_md = f"# {path.stem}\n\n" + "\n\n---\n\n".join(p["markdown"] for p in pages_out)
    return {
        "source_file": path.name,
        "pages_total": total_pages,
        "tables_total": total_tables,
        "detached_number_rows": total_detached_num_rows,
        "cmap_fixes": total_cmap_fixes,
        "pages": pages_out,
        "markdown": full_md.strip() + "\n",
    }
