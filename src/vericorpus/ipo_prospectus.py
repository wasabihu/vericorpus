"""一级市场硬科技招股书 + 上市后首年/最新年报双轨语料（SEC Pack 与 港股18C/科创板 Recipe）管线。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any
import urllib.parse

from . import compliance, financial_10y

DOBOT_READONLY_DIR = Path(
    os.environ.get("DOBOT_READONLY_DIR")
    or "data/local_eval/dobot-02432"
)


def _resolve_dobot_dir(repo_root: Path) -> Path:
    env_dir = os.environ.get("DOBOT_READONLY_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return repo_root / "data" / "local_eval" / "dobot-02432"

PROSPECTUS_SPECS: list[dict[str, Any]] = [
    # 轨道 1：美股 SEC Pack（零版权争议，可公开分发）
    {
        "id": "ALAB",
        "name_zh": "Astera Labs",
        "name_en": "Astera Labs, Inc.",
        "track": "sec_pack",
        "sec_ticker": "ALAB",
        "wiki_track": "ai-cluster-optical-interconnect",
        "note": "AI数据中心高速互联(PCIe/CXL/Ethernet Retimer)，2024-03纳斯达克IPO",
    },
    {
        "id": "CRDO",
        "name_zh": "Credo Technology",
        "name_en": "Credo Technology Group Holding Ltd",
        "track": "sec_pack",
        "sec_ticker": "CRDO",
        "wiki_track": "ai-cluster-optical-interconnect",
        "note": "AI集群AEC有源电缆与SerDes DSP核心标的",
    },
    {
        "id": "CRWV",
        "name_zh": "CoreWeave",
        "name_en": "CoreWeave, Inc.",
        "track": "sec_pack",
        "sec_ticker": "CRWV",
        "wiki_track": "ai-value-chain",
        "note": "AI专用GPU算力云龙头，2025美股IPO后披露首年10-K",
    },
    {
        "id": "ARM",
        "name_zh": "Arm",
        "name_en": "Arm Holdings plc",
        "track": "sec_pack",
        "sec_ticker": "ARM",
        "wiki_track": "china-autonomous-ai-compute-stack",
        "note": "AI算力处理器架构IP基准，2023-09 IPO 424B4 + 上市后20-F",
    },
    {
        "id": "SPCX",
        "name_zh": "SpaceX",
        "name_en": "Space Exploration Technologies Corp.",
        "track": "sec_pack",
        "sec_ticker": "SPCX",
        "wiki_track": "high-performance-composites",
        "note": "2026-06纳斯达克IPO招股书424B4/S-1/A与上市后10-Q",
    },
    # 轨道 2A：港股 18C / 特专科技与硬科技 Recipe（本地留档）
    {
        "id": "02533",
        "name_zh": "黑芝麻智能",
        "name_en": "Black Sesame International Holding Limited",
        "track": "hkex_recipe",
        "hk_code": "02533",
        "wiki_track": "china-autonomous-ai-compute-stack",
        "note": "港股18C特专科技车规级智驾SoC芯片招股书与上市后年报",
    },
    {
        "id": "09660",
        "name_zh": "地平线机器人-W",
        "name_en": "Horizon Robotics",
        "track": "hkex_recipe",
        "hk_code": "09660",
        "wiki_track": "china-autonomous-ai-compute-stack",
        "note": "智驾计算方案龙头，2024-10港股招股书与上市后年报",
    },
    {
        "id": "ZHIPU",
        "name_zh": "智谱",
        "name_en": "Beijing Zhipu Huazhang Technology Co., Ltd.",
        "track": "hkex_recipe",
        "hk_code": "02513",
        "wiki_track": "frontier-ai-technology-landscape",
        "note": "2026-01港交所大模型第一股招股书+2025年报+2026中报",
    },
    {
        "id": "02432",
        "name_zh": "越疆机器人",
        "name_en": "Shenzhen Dobot Corp Ltd",
        "track": "hkex_recipe",
        "hk_code": "02432",
        "wiki_track": "frontier-ai-technology-landscape",
        "note": "港股18C协作机器人招股章程与年度报告表格重建对照",
    },
    # 轨道 2B：科创板招股书 + 审核问询函回复 + 年报 Recipe（本地留档）
    {
        "id": "688041",
        "name_zh": "海光信息",
        "name_en": "Hygon Information Technology Co., Ltd.",
        "track": "cninfo_recipe",
        "cn_code": "688041",
        "wiki_track": "china-autonomous-ai-compute-stack",
        "note": "国产AI算力DCU/CPU核心标的，科创板招股书+2025年报",
    },
    {
        "id": "688498",
        "name_zh": "源杰科技",
        "name_en": "Yuanjie Semiconductor Technology Co., Ltd.",
        "track": "cninfo_recipe",
        "cn_code": "688498",
        "wiki_track": "ai-cluster-optical-interconnect",
        "note": "高速光芯片核心标的，科创板招股书+上交所年报审核问询函回复+2025年报",
    },
    {
        "id": "688295",
        "name_zh": "中复神鹰",
        "name_en": "Zhongfu Shenying Carbon Fiber Co., Ltd.",
        "track": "cninfo_recipe",
        "cn_code": "688295",
        "wiki_track": "high-performance-composites",
        "note": "高性能CFRP碳纤维龙头，科创板招股书+2025年报",
    },
]

PROSPECTUS_STATEMENT_KEYWORDS: tuple[str, ...] = (
    "主要财务数据",
    "本次发行概况",
    "审核问询",
    "问询函",
    "財務資料",
    "招股章程",
    "Selected Financial Data",
    "Selected Consolidated Financial",
    "Financial Information",
)

PROSPECTUS_MDA_KEYWORDS: tuple[str, ...] = (
    "业务与技术",
    "业务概要",
    "行业概览",
    "风险因素",
    "業務概要",
    "行業概覽",
    "風險因素",
    "全球發售",
    "Prospectus Summary",
    "Summary",
    "Risk Factors",
)

PROSPECTUS_KEY_KEYWORDS: tuple[str, ...] = (
    financial_10y.KEY_FINANCIAL_PAGE_KEYWORDS + PROSPECTUS_STATEMENT_KEYWORDS + PROSPECTUS_MDA_KEYWORDS
)


def is_prospectus_key_page(page_no: int, text: str) -> bool:
    """判断页面是否为招股书/问询回复核心章节（财务数据、概要、业务、行业、风险因素）。"""
    if page_no <= 10:
        return True
    lower_txt = text.lower()
    compact_txt = "".join(text.split())
    return financial_10y._match_any_kw(compact_txt, lower_txt, PROSPECTUS_KEY_KEYWORDS)


def compare_dobot_txt_vs_rebuilt(txt_dir: str | Path, md_dir: str | Path) -> dict[str, Any]:
    """量化对比越疆机器人原测试包辅助文本与 pdf_table_fix 重建 Markdown 的结构与质量差异。"""
    tdir = Path(txt_dir)
    mdir = Path(md_dir)
    txt_files = sorted(tdir.glob("*.txt")) if tdir.is_dir() else []
    md_files = sorted(mdir.glob("*.md")) if mdir.is_dir() else []

    txt_chars = txt_pipes = txt_repl = 0
    for p in txt_files:
        raw = p.read_text(encoding="utf-8", errors="replace")
        txt_chars += len(raw)
        txt_repl += raw.count("\ufffd")
        txt_pipes += sum(1 for ln in raw.splitlines() if ln.strip().startswith("|") and ln.strip().endswith("|"))

    md_chars = md_pipes = md_anchors = md_repl = md_bad_shi = 0
    for p in md_files:
        raw = p.read_text(encoding="utf-8", errors="replace")
        md_chars += len(raw)
        md_repl += raw.count("\ufffd")
        md_bad_shi += len(re.findall(r"\d+\s*尸|\d{4}年\d{1,2}尸", raw))
        md_anchors += len(re.findall(r"<!-- page: \d+/\d+ -->", raw))
        md_pipes += sum(1 for ln in raw.splitlines() if ln.strip().startswith("|") and ln.strip().endswith("|"))

    return {
        "txt_files": len(txt_files),
        "md_files": len(md_files),
        "txt_chars": txt_chars,
        "md_chars": md_chars,
        "txt_pipe_rows": txt_pipes,
        "md_pipe_rows": md_pipes,
        "md_page_anchors": md_anchors,
        "txt_replacement_chars": txt_repl,
        "md_replacement_chars": md_repl,
        "md_bad_shi_dates": md_bad_shi,
    }


def _select_sec_ipo_and_annuals(cik: str) -> list[dict[str, Any]]:
    sub = financial_10y._sec_get_json(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=30.0)
    filings_root = sub.get("filings") or {}
    pages: list[dict[str, Any]] = [filings_root.get("recent") or {}]
    for fmeta in filings_root.get("files") or []:
        fname = str(fmeta.get("name") or "").strip()
        if fname:
            pages.append(financial_10y._sec_get_json(f"https://data.sec.gov/submissions/{fname}", timeout=30.0))

    cik_num = str(int(cik))
    prospectus: list[dict[str, Any]] = []
    annuals: list[dict[str, Any]] = []
    quarterlies: list[dict[str, Any]] = []

    for page in pages:
        forms = page.get("form") or []
        fdates = page.get("filingDate") or []
        rdates = page.get("reportDate") or []
        accs = page.get("accessionNumber") or []
        pdocs = page.get("primaryDocument") or []
        for idx, form in enumerate(forms):
            f_str = str(form or "").strip().upper()
            f_date = str(fdates[idx] if idx < len(fdates) else "")
            r_date = str(rdates[idx] if idx < len(rdates) else "")
            acc = str(accs[idx] if idx < len(accs) else "")
            pdoc = str(pdocs[idx] if idx < len(pdocs) else "")
            if not acc or not pdoc or not pdoc.lower().endswith((".htm", ".html")):
                continue
            fy = (r_date or f_date)[:4]
            rec = {
                "market": "SEC",
                "form": f_str,
                "fiscal_year": fy,
                "filing_date": f_date,
                "report_date": r_date,
                "accession_number": acc,
                "primary_document": pdoc,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc.replace('-', '')}/{pdoc}",
            }
            if f_str in ("424B4", "424B1", "S-1/A", "F-1/A", "S-1", "F-1"):
                prospectus.append(rec)
            elif f_str in ("10-K", "20-F"):
                annuals.append(rec)
            elif f_str == "10-Q":
                quarterlies.append(rec)

    # 招股书优先选终版 424B4（若无再降级至 S-1/A 或 F-1/A）
    best_pro = [r for r in prospectus if r["form"] in ("424B4", "424B1")] or prospectus
    picked: list[dict[str, Any]] = []
    seen_acc: set[str] = set()
    for r in best_pro[:1] + annuals[:2]:
        if r["accession_number"] not in seen_acc:
            seen_acc.add(r["accession_number"])
            picked.append(r)
    if not annuals:
        for r in quarterlies[:2]:
            if r["accession_number"] not in seen_acc:
                seen_acc.add(r["accession_number"])
                picked.append(r)
    return picked


def _inject_wiki_track_and_write(
    *,
    src_md: Path | None,
    dest_md: Path,
    wiki_track: str,
    corpus_slug: str,
    html_fallback_meta: dict[str, Any] | None = None,
) -> int:
    if src_md and src_md.is_file() and src_md.stat().st_size > 200:
        txt = src_md.read_text(encoding="utf-8", errors="replace")
        if f"corpus: {corpus_slug}" not in txt:
            txt = re.sub(r"^corpus:\s*.*$", f"corpus: {corpus_slug}", txt, count=1, flags=re.M)
        if "wiki_track:" not in txt[:600]:
            txt = txt.replace("\n---\n", f"\nwiki_track: {wiki_track}\n---\n", 1)
        dest_md.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest_md.with_suffix(".tmp")
        tmp.write_text(txt, encoding="utf-8")
        tmp.replace(dest_md)
        return dest_md.stat().st_size

    assert html_fallback_meta is not None
    co = html_fallback_meta["company"]
    f = html_fallback_meta["filing"]
    raw_bytes = financial_10y._http_get_bytes(
        f["url"],
        headers={"User-Agent": financial_10y.get_sec_user_agent(), "Accept-Encoding": "gzip"},
        timeout=50.0,
        rate_limit_sec=True,
        retries=3,
    )
    body_md = financial_10y.sec_html_to_markdown(raw_bytes.decode("utf-8", errors="replace"))
    header = "\n".join(
        [
            "---",
            f"corpus: {corpus_slug}",
            "license: SEC-Public-Filing",
            f"ticker: {co['sec_ticker']}",
            f"cik: {co['sec_cik']}",
            f"company_zh: {co['name_zh']}",
            f"company_en: {co['name_en']}",
            f"wiki_track: {wiki_track}",
            f"form: {f['form']}",
            f"fiscal_year: {f['fiscal_year']}",
            f"filing_date: {f['filing_date']}",
            f"report_date: {f.get('report_date') or ''}",
            f"accession_number: {f['accession_number']}",
            f"source_url: {f['url']}",
            "---",
            "",
            f"# {co['name_zh']} ({co['name_en']} / {co['sec_ticker']}) {f['fiscal_year']} {f['form']}",
            "",
        ]
    )
    full = header + body_md
    dest_md.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_md.with_suffix(".tmp")
    tmp.write_text(full, encoding="utf-8")
    tmp.replace(dest_md)
    return len(full.encode("utf-8"))


def materialize_sec_ipo_pack(repo_root: str | Path, force: bool = False) -> dict[str, Any]:
    """拉取/复用 5 家美股硬科技 SEC 招股书 + 上市后年报 + XBRL 总表至 sec-ipo-prospectus-pack。"""
    root = Path(repo_root)
    sec_map = financial_10y._resolve_sec_tickers()
    raw_pack_dir = root / "data" / "raw" / "sec-ipo-prospectus-pack"
    raw_sec10y = root / "data" / "raw" / "sec-10y-core"
    raw_pack_dir.mkdir(parents=True, exist_ok=True)

    sec_targets = [dict(s) for s in PROSPECTUS_SPECS if s["track"] == "sec_pack"]
    manifest_sources: list[dict[str, Any]] = []
    files_done = total_bytes = 0
    catalog_entries: list[dict[str, Any]] = []

    for co in sec_targets:
        hit = sec_map.get(co["sec_ticker"])
        if not hit:
            raise RuntimeError(f"SEC 未解析到招股书标的: {co['sec_ticker']}")
        co["sec_cik"] = hit["cik"]
        co["sec_submissions_url"] = f"https://data.sec.gov/submissions/CIK{hit['cik']}.json"

        filings = _select_sec_ipo_and_annuals(hit["cik"])
        co_dir = raw_pack_dir / co["id"]
        co_dir.mkdir(parents=True, exist_ok=True)

        # 若 Phase 1 sec-10y-core 已有同类 SEC 年报/招股书，优先免重复下载直接复用并注入 wiki_track
        existing_phase1 = {}
        p1_fdir = raw_sec10y / "filings" / co["id"]
        if p1_fdir.is_dir():
            for p in p1_fdir.glob("*.md"):
                existing_phase1[p.name] = p

        for f in filings:
            safe_form = re.sub(r"[^A-Za-z0-9_-]+", "_", f["form"])
            fname = f"{f['fiscal_year']}_{safe_form}_{f['filing_date']}.md"
            dest = co_dir / fname
            if dest.is_file() and not force and dest.stat().st_size > 200:
                total_bytes += dest.stat().st_size
                files_done += 1
                continue
            src_hit = existing_phase1.get(fname)
            nb = _inject_wiki_track_and_write(
                src_md=src_hit,
                dest_md=dest,
                wiki_track=co["wiki_track"],
                corpus_slug="sec-ipo-prospectus-pack",
                html_fallback_meta={"company": co, "filing": f},
            )
            total_bytes += nb
            files_done += 1

        # 同步 XBRL 摘要
        xbrl_dest = co_dir / f"{co['id']}_xbrl_summary.md"
        p1_xbrl = raw_sec10y / "xbrl_summaries" / f"{co['id']}_10y_xbrl.md"
        if not (xbrl_dest.is_file() and not force and xbrl_dest.stat().st_size > 200):
            if p1_xbrl.is_file():
                nb = _inject_wiki_track_and_write(
                    src_md=p1_xbrl,
                    dest_md=xbrl_dest,
                    wiki_track=co["wiki_track"],
                    corpus_slug="sec-ipo-prospectus-pack",
                )
                total_bytes += nb
            else:
                facts = financial_10y._sec_get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{hit['cik']}.json", timeout=35.0)
                md_x = financial_10y.build_xbrl_summary_markdown(co, facts)
                md_x = md_x.replace("corpus: sec-10y-core", f"corpus: sec-ipo-prospectus-pack\nwiki_track: {co['wiki_track']}", 1)
                xbrl_dest.write_text(md_x, encoding="utf-8")
                total_bytes += xbrl_dest.stat().st_size
        else:
            total_bytes += xbrl_dest.stat().st_size
        files_done += 1

        manifest_sources.append(
            {
                "name": f"{co['id']}_sec_ipo_pack",
                "ticker": co["sec_ticker"],
                "cik": hit["cik"],
                "wiki_track": co["wiki_track"],
                "url": co["sec_submissions_url"],
                "license": "SEC-Public-Filing",
                "filing_count": len(filings),
            }
        )
        catalog_entries.append({**co, "filings": filings})
        print(f"[sec-ipo-pack] {co['id']}: filings={len(filings)} ({[f['form'] for f in filings]})", flush=True)

    manifest = {
        "slug": "sec-ipo-prospectus-pack",
        "title": "美股硬科技 IPO 招股书（424B4/S-1）与上市后年报 XBRL 对照包（5 家）",
        "description": "面向一级市场硬科技尽调与公开检索评测的双语检索真值语料：覆盖 Astera Labs、Credo、CoreWeave、Arm、SpaceX 招股书终版及上市后年报/季报，全量 SEC-Public-Filing 零版权争议。",
        "domain": "FINANCE",
        "region": "GLOBAL",
        "mode": "pack",
        "license": "SEC-Public-Filing",
        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        "sources": manifest_sources,
    }
    compliance.validate_manifest(manifest)
    mf_path = root / "corpora" / "sec-ipo-prospectus-pack" / "manifest.json"
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (mf_path.parent / "ipo_catalog.json").write_text(
        json.dumps(catalog_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"slug": "sec-ipo-prospectus-pack", "companies": len(sec_targets), "files": files_done, "bytes": total_bytes}


def _fetch_hkex_ipo_filings(stock_id: str) -> list[dict[str, Any]]:
    ann_rows = financial_10y._query_hkex_servlet(stock_id, t1code="40000", t2code="40100", lang="ZH", from_date="20230101", row_range=10)
    picked: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in ann_rows[:2]:
        flink = str(row.get("FILE_LINK") or "").strip()
        title = str(row.get("TITLE") or "").strip()
        dtime = str(row.get("DATE_TIME") or "").strip()
        if not flink.lower().endswith(".pdf"):
            continue
        url = f"https://www1.hkexnews.hk{flink}"
        m_y = re.search(r"(20\d{2})", title) or re.search(r"\d{2}/\d{2}/(20\d{2})", dtime)
        fy = m_y.group(1) if m_y else "2025"
        seen_urls.add(url)
        picked.append({"market": "HKEX", "form": "ANNUAL_REPORT", "fiscal_year": fy, "filing_date": dtime, "title": title, "url": url})

    pro_rows = financial_10y._query_hkex_servlet(stock_id, t1code="-2", t2code="-2", lang="ZH", from_date="20240101", row_range=120)
    for row in pro_rows:
        flink = str(row.get("FILE_LINK") or "").strip()
        title = str(row.get("TITLE") or "").strip()
        dtime = str(row.get("DATE_TIME") or "").strip()
        if not flink.lower().endswith(".pdf"):
            continue
        if any(k in title for k in ("全球發售", "招股", "上市文件")) and not any(
            b in title for b in ("申請表格", "公告", "結果", "穩定價格", "超額配股權", "補遺")
        ):
            url = f"https://www1.hkexnews.hk{flink}"
            if url not in seen_urls:
                m_y = re.search(r"\d{2}/\d{2}/(20\d{2})", dtime) or re.search(r"(20\d{2})", title)
                picked.append(
                    {
                        "market": "HKEX",
                        "form": "PROSPECTUS",
                        "fiscal_year": m_y.group(1) if m_y else "2024",
                        "filing_date": dtime,
                        "title": title,
                        "url": url,
                    }
                )
            break
    return picked


def _query_cninfo_search(cn_code: str, org_id: str, searchkey: str, category: str = "") -> list[dict[str, Any]]:
    payload = urllib.parse.urlencode(
        {
            "stock": f"{cn_code},{org_id}",
            "tabName": "fulltext",
            "pageSize": "15",
            "pageNum": "1",
            "column": "sse",
            "category": category,
            "plate": "",
            "seDate": "2020-01-01~2026-12-31",
            "searchkey": searchkey,
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "false",
        }
    ).encode("utf-8")
    raw = financial_10y._http_get_bytes(
        "https://www.cninfo.com.cn/new/hisAnnouncement/query",
        data=payload,
        headers={
            "User-Agent": financial_10y.BROWSER_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        },
        timeout=20.0,
    )
    return json.loads(raw.decode("utf-8", errors="replace")).get("announcements") or []


def _fetch_cninfo_ipo_filings(cn_code: str, org_id: str) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def add_item(ann: dict[str, Any], form: str, default_fy: str) -> None:
        title = re.sub(r"<[^>]+>", "", str(ann.get("announcementTitle") or "")).strip()
        adj = str(ann.get("adjunctUrl") or "").strip().lstrip("/")
        if not adj.lower().endswith(".pdf"):
            return
        url = f"https://static.cninfo.com.cn/{adj}"
        if url in seen_urls:
            return
        ts = ann.get("announcementTime") or 0
        fdate = time.strftime("%Y-%m-%d", time.localtime(float(ts) / 1000.0)) if ts else ""
        my = re.search(r"(20\d{2})", title) or re.search(r"(20\d{2})", fdate)
        seen_urls.add(url)
        picked.append({"market": "CNINFO", "form": form, "fiscal_year": my.group(1) if my else default_fy, "filing_date": fdate, "title": title, "url": url})

    # 1. 首次公开发行招股说明书主文件（排除摘要/提示性/英文）
    for ann in _query_cninfo_search(cn_code, org_id, "招股说明书"):
        t = re.sub(r"<[^>]+>", "", str(ann.get("announcementTitle") or "")).strip()
        if "招股说明书" in t and not any(b in t for b in ("摘要", "提示性", "英文", "附录", "更正", "律师")):
            add_item(ann, "PROSPECTUS", "2022")
            break

    # 2. 最新年报
    for ann in _query_cninfo_search(cn_code, org_id, "", category="category_ndbg_szsh;"):
        t = re.sub(r"<[^>]+>", "", str(ann.get("announcementTitle") or "")).strip()
        if "年度报告" in t and not any(b in t for b in ("摘要", "英文", "取消", "半年度")):
            add_item(ann, "ANNUAL_REPORT", "2025")
            break

    # 3. 交易所审核问询函回复（如源杰科技上交所年报问询回复）
    for ann in _query_cninfo_search(cn_code, org_id, "问询"):
        t = re.sub(r"<[^>]+>", "", str(ann.get("announcementTitle") or "")).strip()
        if "问询" in t and "回复" in t and "核查意见" not in t:
            add_item(ann, "INQUIRY_REPLY", "2024")
            break

    return picked


def materialize_cnhk_ipo_recipe(repo_root: str | Path, force: bool = False, workers: int = 4) -> dict[str, Any]:
    """落地港股 18C（4家，含越疆只读对照）+ 科创板（3家，含问询回复）招股书 recipe。"""
    root = Path(repo_root)
    hk_map = financial_10y._resolve_hkex_stocks()
    cn_map = financial_10y._resolve_cninfo_stocks()
    archive_base = root / "data" / "archive" / "cn-hk-ipo-prospectus-recipe"
    raw_base = root / "data" / "raw" / "cn-hk-ipo-prospectus-recipe"
    raw_base.mkdir(parents=True, exist_ok=True)

    cnhk_targets = [dict(s) for s in PROSPECTUS_SPECS if s["track"] in ("hkex_recipe", "cninfo_recipe")]
    download_jobs: list[dict[str, Any]] = []
    local_parse_jobs: list[dict[str, Any]] = []
    catalog_entries: list[dict[str, Any]] = []
    reused_zhipu = 0

    for co in cnhk_targets:
        cid = co["id"]
        if cid == "ZHIPU":
            src_z = root / "data" / "raw" / "cn-hk-financial-10y" / "hkex" / "ZHIPU"
            dst_z = raw_base / "hkex" / "ZHIPU"
            dst_z.mkdir(parents=True, exist_ok=True)
            copied = []
            for p in sorted(src_z.glob("*.md")):
                txt = p.read_text(encoding="utf-8", errors="replace")
                txt = txt.replace("corpus: cn-hk-financial-10y", f"corpus: cn-hk-ipo-prospectus-recipe\nwiki_track: {co['wiki_track']}", 1)
                txt = re.sub(r"^(## 第 \d+ 页)$", rf"\1 | 智谱 (02513) {p.stem}", txt, flags=re.M)
                (dst_z / p.name).write_text(txt, encoding="utf-8")
                copied.append({"name": p.name, "source": p.relative_to(root).as_posix()})
                reused_zhipu += 1
            catalog_entries.append({**co, "filings": copied})
            continue

        if cid == "02432":
            dobot_dir = _resolve_dobot_dir(root)
            sm_path = dobot_dir / "source-manifest.json"
            if not sm_path.is_file():
                catalog_entries.append({**co, "filings": []})
                continue
            sm_list = json.loads(sm_path.read_text(encoding="utf-8"))
            dobot_filings = []
            for entry in sm_list:
                rel_pdf = entry["file"]
                pdf_path = dobot_dir / rel_pdf
                stem = Path(rel_pdf).stem
                md_path = raw_base / "hkex" / "02432" / f"{stem}.md"
                filing = {
                    "market": "HKEX",
                    "form": "PROSPECTUS_PHIP" if "聆讯后" in rel_pdf else ("INTERIM_REPORT" if "中期" in rel_pdf else "ANNUAL_REPORT"),
                    "fiscal_year": "2025" if "2025" in rel_pdf else "2024",
                    "filing_date": str(entry.get("retrieved") or "2026-09-26"),
                    "title": stem,
                    "url": str(entry.get("url") or ""),
                }
                dobot_filings.append(filing)
                local_parse_jobs.append(
                    {
                        "market": "hkex",
                        "company_id": cid,
                        "company": co,
                        "filing": filing,
                        "pdf_path": str(pdf_path),
                        "md_path": str(md_path),
                        "parse_mode": "key-sections",
                        "max_table_pages": 25,
                        "force": force,
                        "corpus_slug": "cn-hk-ipo-prospectus-recipe",
                        "extra_statement_keywords": list(PROSPECTUS_STATEMENT_KEYWORDS),
                        "extra_mda_keywords": list(PROSPECTUS_MDA_KEYWORDS),
                    }
                )
            catalog_entries.append({**co, "filings": dobot_filings})
            continue

        if co["track"] == "hkex_recipe":
            sid = (hk_map.get(co["hk_code"].zfill(5)) or {}).get("stock_id")
            if not sid:
                raise RuntimeError(f"HKEX 未解析 stock_id: {co['hk_code']}")
            filings = _fetch_hkex_ipo_filings(sid)
            mkt = "hkex"
            max_pg = 25
        else:
            code = co["cn_code"]
            org_id = (cn_map.get(code) or {}).get("org_id") or financial_10y._fallback_cninfo_org_id(code)
            filings = _fetch_cninfo_ipo_filings(code, org_id)
            mkt = "cninfo"
            max_pg = 35

        used_stems: set[str] = set()
        for f in filings:
            fy = f["fiscal_year"]
            fm = f["form"]
            stem = f"{fy}_{fm}"
            if stem in used_stems:
                stem = f"{stem}_{f['filing_date'][:10]}"
            used_stems.add(stem)
            pdf_path = archive_base / mkt / cid / f"{stem}.pdf"
            md_path = raw_base / mkt / cid / f"{stem}.md"
            job = {
                "market": mkt,
                "company_id": cid,
                "company": co,
                "filing": f,
                "url": f["url"],
                "pdf_path": str(pdf_path),
                "md_path": str(md_path),
                "parse_mode": "key-sections",
                "max_table_pages": max_pg,
                "force": force,
                "corpus_slug": "cn-hk-ipo-prospectus-recipe",
                "extra_statement_keywords": list(PROSPECTUS_STATEMENT_KEYWORDS),
                "extra_mda_keywords": list(PROSPECTUS_MDA_KEYWORDS),
            }
            download_jobs.append(job)
        catalog_entries.append({**co, "filings": filings})
        print(f"[cnhk-ipo-catalog] {cid} ({co['name_zh']}): {len(filings)} docs", flush=True)

    # 1. 下载线上 HKEX/CNINFO 招股书+年报+问询回复 PDF 到 data/archive/cn-hk-ipo-prospectus-recipe/
    failed: list[dict[str, Any]] = []
    ready_to_parse = list(local_parse_jobs)
    downloaded = dl_skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as dl_pool:
        futs = {dl_pool.submit(financial_10y._download_one_recipe_pdf, j): j for j in download_jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                st, _ = fut.result()
                if st == "downloaded":
                    downloaded += 1
                else:
                    dl_skipped += 1
                ready_to_parse.append(j)
            except Exception as exc:
                failed.append({"stage": "download", "company_id": j["company_id"], "url": j["url"], "error": str(exc)})

    # 2. 独立子进程并行按招股书关键词方案精排转 Markdown
    parsed = md_skipped = tables_total = rebuilt_pages = 0
    with ThreadPoolExecutor(max_workers=workers) as p_pool:
        futs = {p_pool.submit(financial_10y._run_isolated_pdf_job, j): j for j in ready_to_parse}
        done_i = 0
        for fut in as_completed(futs):
            j = futs[fut]
            done_i += 1
            try:
                res = fut.result()
                if res["status"] == "parsed":
                    parsed += 1
                else:
                    md_skipped += 1
                tables_total += int(res["tables_total"])
                rebuilt_pages += int(res["table_rebuilt_pages"])
            except Exception as exc:
                failed.append({"stage": "parse", "company_id": j["company_id"], "pdf": j["pdf_path"], "error": str(exc)})
            print(f"[cnhk-ipo-parse {done_i}/{len(ready_to_parse)}] cid={j['company_id']} failed={len(failed)}", flush=True)

    dobot_cmp = compare_dobot_txt_vs_rebuilt(
        DOBOT_READONLY_DIR / "04-可检索文本",
        raw_base / "hkex" / "02432",
    )

    manifest = {
        "slug": "cn-hk-ipo-prospectus-recipe",
        "title": "港股18C与科创板硬科技招股书、审核问询回复及首年年报配方（7家，本地评测）",
        "description": "覆盖黑芝麻智能(02533)、地平线(09660)、智谱(02513)、越疆机器人(02432只读基准对照)及科创板海光信息(688041)、源杰科技(688498含上交所审核问询回复)、中复神鹰(688295)，以 recipe 模式本地隔离留档并经 pdf_table_fix 重建表格。",
        "domain": "FINANCE",
        "region": "CN",
        "mode": "recipe",
        "license": "Multi-Exchange-Public-Disclosure",
        "source_url": "https://www1.hkexnews.hk/",
        "catalog_file": "corpora/cn-hk-ipo-prospectus-recipe/ipo_catalog.json",
        "sources": [
            {
                "name": "hkex_18c_prospectus_recipe",
                "url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh",
                "local_path": "data/raw/cn-hk-ipo-prospectus-recipe/hkex",
                "license": "HKEX-Public-Disclosure",
            },
            {
                "name": "cninfo_star_prospectus_inquiry_recipe",
                "url": "https://www.cninfo.com.cn/new/disclosure",
                "local_path": "data/raw/cn-hk-ipo-prospectus-recipe/cninfo",
                "license": "CNINFO-Public-Disclosure",
            },
        ],
    }
    compliance.validate_manifest(manifest)
    mf_path = root / "corpora" / "cn-hk-ipo-prospectus-recipe" / "manifest.json"
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (mf_path.parent / "ipo_catalog.json").write_text(
        json.dumps(catalog_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (raw_base / "failed_ipo.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "slug": "cn-hk-ipo-prospectus-recipe",
        "companies": len(cnhk_targets),
        "downloaded": downloaded,
        "dl_skipped": dl_skipped,
        "parsed": parsed,
        "md_skipped": md_skipped,
        "reused_zhipu": reused_zhipu,
        "tables_total": tables_total,
        "rebuilt_pages": rebuilt_pages,
        "failed_count": len(failed),
        "dobot_compare": dobot_cmp,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="vericorpus 一级市场硬科技招股书+财报双轨语料构建器")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--stage", choices=("sec-pack", "cnhk-recipe", "all"), default="all")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    root = Path(args.repo_root)
    if args.stage in ("sec-pack", "all"):
        res_sec = materialize_sec_ipo_pack(root, force=args.force)
        print("SEC_IPO_PACK_SUMMARY:", json.dumps(res_sec, ensure_ascii=False))
    if args.stage in ("cnhk-recipe", "all"):
        res_cnhk = materialize_cnhk_ipo_recipe(root, force=args.force, workers=args.workers)
        print("CNHK_IPO_RECIPE_SUMMARY:", json.dumps(res_cnhk, ensure_ascii=False))


if __name__ == "__main__":
    main()
