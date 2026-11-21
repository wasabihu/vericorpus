"""全球 92 家核心上市公司（美/中概/A股/港股/韩股）近 10 年财报多市场目录、XBRL 审计总表与 SEC 净室语料管线。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import gzip
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from . import compliance, fetchers, pdf_table_fix


def get_sec_user_agent() -> str:
    """Resolve and validate SEC EDGAR User-Agent requiring a contact email per SEC Fair Access Policy."""
    return fetchers.require_sec_user_agent()


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 92 家跨市场核心上市公司标准实体映射表
COMPANIES_SPEC: list[dict[str, Any]] = [
    # A 组：SEC 美股 / 全球 / 台湾 / 汇丰（35 家）
    {"id": "NVDA", "name_zh": "英伟达", "name_en": "NVIDIA Corporation", "group": "US_SEC", "sec_ticker": "NVDA"},
    {"id": "TSLA", "name_zh": "特斯拉", "name_en": "Tesla, Inc.", "group": "US_SEC", "sec_ticker": "TSLA"},
    {"id": "SPCX", "name_zh": "SpaceX", "name_en": "Space Exploration Technologies Corp.", "group": "US_SEC", "sec_ticker": "SPCX", "note": "2026-06 Nasdaq IPO; capture prospectus/10-Q until first 10-K"},
    {"id": "GOOGL", "name_zh": "Google (Alphabet)", "name_en": "Alphabet Inc.", "group": "US_SEC", "sec_ticker": "GOOGL"},
    {"id": "AXP", "name_zh": "美国运通", "name_en": "American Express Company", "group": "US_SEC", "sec_ticker": "AXP"},
    {"id": "BRK_B", "name_zh": "伯克希尔·哈撒韦", "name_en": "Berkshire Hathaway Inc.", "group": "US_SEC", "sec_ticker": "BRK-B"},
    {"id": "NET", "name_zh": "Cloudflare", "name_en": "Cloudflare, Inc.", "group": "US_SEC", "sec_ticker": "NET"},
    {"id": "PFE", "name_zh": "辉瑞", "name_en": "Pfizer Inc.", "group": "US_SEC", "sec_ticker": "PFE"},
    {"id": "AAPL", "name_zh": "苹果", "name_en": "Apple Inc.", "group": "US_SEC", "sec_ticker": "AAPL"},
    {"id": "UNH", "name_zh": "联合健康", "name_en": "UnitedHealth Group Incorporated", "group": "US_SEC", "sec_ticker": "UNH"},
    {"id": "WFC", "name_zh": "富国银行", "name_en": "Wells Fargo & Company", "group": "US_SEC", "sec_ticker": "WFC"},
    {"id": "TSM", "name_zh": "台积电", "name_en": "Taiwan Semiconductor Manufacturing Company Limited", "group": "US_SEC", "sec_ticker": "TSM"},
    {"id": "AVGO", "name_zh": "博通", "name_en": "Broadcom Inc.", "group": "US_SEC", "sec_ticker": "AVGO", "extra_sec_ciks": ["0001649338"], "note": "Merge Broadcom Pte. Ltd. (0001649338) for 2016-2017 10-K"},
    {"id": "AMD", "name_zh": "AMD", "name_en": "Advanced Micro Devices, Inc.", "group": "US_SEC", "sec_ticker": "AMD"},
    {"id": "BAC", "name_zh": "美国银行", "name_en": "Bank of America Corporation", "group": "US_SEC", "sec_ticker": "BAC"},
    {"id": "CB", "name_zh": "安达保险", "name_en": "Chubb Limited", "group": "US_SEC", "sec_ticker": "CB"},
    {"id": "COST", "name_zh": "好市多", "name_en": "Costco Wholesale Corporation", "group": "US_SEC", "sec_ticker": "COST"},
    {"id": "ARM", "name_zh": "Arm", "name_en": "Arm Holdings plc", "group": "US_SEC", "sec_ticker": "ARM"},
    {"id": "META", "name_zh": "Meta", "name_en": "Meta Platforms, Inc.", "group": "US_SEC", "sec_ticker": "META"},
    {"id": "LMT", "name_zh": "洛克希德·马丁", "name_en": "Lockheed Martin Corporation", "group": "US_SEC", "sec_ticker": "LMT"},
    {"id": "XOM", "name_zh": "埃克森美孚", "name_en": "Exxon Mobil Corporation", "group": "US_SEC", "sec_ticker": "XOM", "sec_cik_override": "0000034088", "note": "Use primary EXXON MOBIL CORP CIK 0000034088 for 10-year 10-K and XBRL after 2026 holding reorg"},
    {"id": "CVX", "name_zh": "雪佛龙", "name_en": "Chevron Corporation", "group": "US_SEC", "sec_ticker": "CVX"},
    {"id": "OXY", "name_zh": "西方石油", "name_en": "Occidental Petroleum Corporation", "group": "US_SEC", "sec_ticker": "OXY"},
    {"id": "MSFT", "name_zh": "微软", "name_en": "Microsoft Corporation", "group": "US_SEC", "sec_ticker": "MSFT"},
    {"id": "BA", "name_zh": "波音", "name_en": "The Boeing Company", "group": "US_SEC", "sec_ticker": "BA"},
    {"id": "INTC", "name_zh": "英特尔", "name_en": "Intel Corporation", "group": "US_SEC", "sec_ticker": "INTC"},
    {"id": "QCOM", "name_zh": "高通", "name_en": "QUALCOMM Incorporated", "group": "US_SEC", "sec_ticker": "QCOM"},
    {"id": "CSCO", "name_zh": "思科", "name_en": "Cisco Systems, Inc.", "group": "US_SEC", "sec_ticker": "CSCO"},
    {"id": "MRNA", "name_zh": "Moderna", "name_en": "Moderna, Inc.", "group": "US_SEC", "sec_ticker": "MRNA"},
    {"id": "MU", "name_zh": "美光科技", "name_en": "Micron Technology, Inc.", "group": "US_SEC", "sec_ticker": "MU"},
    {"id": "WMT", "name_zh": "沃尔玛", "name_en": "Walmart Inc.", "group": "US_SEC", "sec_ticker": "WMT"},
    {"id": "JNJ", "name_zh": "强生", "name_en": "Johnson & Johnson", "group": "US_SEC", "sec_ticker": "JNJ"},
    {"id": "JPM", "name_zh": "摩根大通", "name_en": "JPMorgan Chase & Co.", "group": "US_SEC", "sec_ticker": "JPM"},
    {"id": "GS", "name_zh": "高盛", "name_en": "The Goldman Sachs Group, Inc.", "group": "US_SEC", "sec_ticker": "GS"},
    {"id": "HSBC", "name_zh": "汇丰控股", "name_en": "HSBC Holdings plc", "group": "US_SEC", "sec_ticker": "HSBC", "hk_code": "00005"},
    # B 组：SEC 赴美中概 ADR（13 家）
    {"id": "BABA", "name_zh": "阿里巴巴", "name_en": "Alibaba Group Holding Limited", "group": "CN_ADR_SEC", "sec_ticker": "BABA", "hk_code": "09988"},
    {"id": "NTES", "name_zh": "网易", "name_en": "NetEase, Inc.", "group": "CN_ADR_SEC", "sec_ticker": "NTES", "hk_code": "09999"},
    {"id": "BEKE", "name_zh": "贝壳", "name_en": "KE Holdings Inc.", "group": "CN_ADR_SEC", "sec_ticker": "BEKE", "hk_code": "02423"},
    {"id": "BIDU", "name_zh": "百度集团", "name_en": "Baidu, Inc.", "group": "CN_ADR_SEC", "sec_ticker": "BIDU", "hk_code": "09888"},
    {"id": "JD", "name_zh": "京东", "name_en": "JD.com, Inc.", "group": "CN_ADR_SEC", "sec_ticker": "JD", "hk_code": "09618"},
    {"id": "TCOM", "name_zh": "携程集团", "name_en": "Trip.com Group Limited", "group": "CN_ADR_SEC", "sec_ticker": "TCOM", "hk_code": "09961"},
    {"id": "PDD", "name_zh": "拼多多", "name_en": "PDD Holdings Inc.", "group": "CN_ADR_SEC", "sec_ticker": "PDD"},
    {"id": "FUTU", "name_zh": "富途控股", "name_en": "Futu Holdings Limited", "group": "CN_ADR_SEC", "sec_ticker": "FUTU"},
    {"id": "ZTO", "name_zh": "中通快递", "name_en": "ZTO Express (Cayman) Inc.", "group": "CN_ADR_SEC", "sec_ticker": "ZTO", "hk_code": "02057"},
    {"id": "LI", "name_zh": "理想汽车", "name_en": "Li Auto Inc.", "group": "CN_ADR_SEC", "sec_ticker": "LI", "hk_code": "02015"},
    {"id": "VIPS", "name_zh": "唯品会", "name_en": "Vipshop Holdings Limited", "group": "CN_ADR_SEC", "sec_ticker": "VIPS"},
    {"id": "TME", "name_zh": "腾讯音乐", "name_en": "Tencent Music Entertainment Group", "group": "CN_ADR_SEC", "sec_ticker": "TME", "hk_code": "01698"},
    {"id": "BZ", "name_zh": "Boss直聘", "name_en": "KANZHUN LIMITED", "group": "CN_ADR_SEC", "sec_ticker": "BZ", "hk_code": "02076"},
    # C 组：A 股与 A+H（26 家）
    {"id": "600519", "name_zh": "贵州茅台", "name_en": "Kweichow Moutai Co., Ltd.", "group": "CN_A", "cn_code": "600519"},
    {"id": "000858", "name_zh": "五粮液", "name_en": "Wuliangye Yibin Co., Ltd.", "group": "CN_A", "cn_code": "000858"},
    {"id": "600887", "name_zh": "伊利股份", "name_en": "Inner Mongolia Yili Industrial Group Co., Ltd.", "group": "CN_A", "cn_code": "600887"},
    {"id": "000596", "name_zh": "古井贡酒", "name_en": "Anhui Gujing Distillery Co., Ltd.", "group": "CN_A", "cn_code": "000596"},
    {"id": "300750", "name_zh": "宁德时代", "name_en": "Contemporary Amperex Technology Co., Limited", "group": "CN_A", "cn_code": "300750"},
    {"id": "002027", "name_zh": "分众传媒", "name_en": "Focus Media Information Technology Co., Ltd.", "group": "CN_A", "cn_code": "002027"},
    {"id": "300760", "name_zh": "迈瑞医疗", "name_en": "Shenzhen Mindray Bio-Medical Electronics Co., Ltd.", "group": "CN_A", "cn_code": "300760"},
    {"id": "300498", "name_zh": "温氏股份", "name_en": "Wens Foodstuff Group Co., Ltd.", "group": "CN_A", "cn_code": "300498"},
    {"id": "000333", "name_zh": "美的集团", "name_en": "Midea Group Co., Ltd.", "group": "CN_A", "cn_code": "000333", "hk_code": "00300"},
    {"id": "600050", "name_zh": "中国联通", "name_en": "China United Network Communications Limited", "group": "CN_A", "cn_code": "600050", "hk_code": "00762"},
    {"id": "000100", "name_zh": "TCL科技", "name_en": "TCL Technology Group Corporation", "group": "CN_A", "cn_code": "000100"},
    {"id": "POLY_CN", "name_zh": "保利发展 (保利集团旗舰)", "name_en": "Poly Developments and Holdings Group Co., Ltd.", "group": "CN_A", "cn_code": "600048", "hk_code": "00119", "note": "Listed flagship of Poly Group; HKEX 00119 Poly Property also mapped"},
    {"id": "688981", "name_zh": "中芯国际", "name_en": "Semiconductor Manufacturing International Corporation", "group": "CN_A", "cn_code": "688981", "hk_code": "00981", "note": "HKEX 00981 covers pre-STAR-Market years"},
    {"id": "002594", "name_zh": "比亚迪", "name_en": "BYD Company Limited", "group": "CN_A", "cn_code": "002594", "hk_code": "01211"},
    {"id": "601088", "name_zh": "中国神华", "name_en": "China Shenhua Energy Company Limited", "group": "CN_A", "cn_code": "601088", "hk_code": "01088"},
    {"id": "600938", "name_zh": "中国海油", "name_en": "CNOOC Limited", "group": "CN_A", "cn_code": "600938", "hk_code": "00883", "note": "HKEX 00883 covers pre-2022 A-share listing years"},
    {"id": "601857", "name_zh": "中国石油", "name_en": "PetroChina Company Limited", "group": "CN_A", "cn_code": "601857", "hk_code": "00857"},
    {"id": "600941", "name_zh": "中国移动", "name_en": "China Mobile Limited", "group": "CN_A", "cn_code": "600941", "hk_code": "00941", "note": "HKEX 00941 covers pre-2022 A-share listing years"},
    {"id": "601601", "name_zh": "中国太保", "name_en": "China Pacific Insurance (Group) Co., Ltd.", "group": "CN_A", "cn_code": "601601", "hk_code": "02601"},
    {"id": "601318", "name_zh": "中国平安", "name_en": "Ping An Insurance (Group) Company of China, Ltd.", "group": "CN_A", "cn_code": "601318", "hk_code": "02318"},
    {"id": "601628", "name_zh": "中国人寿", "name_en": "China Life Insurance Company Limited", "group": "CN_A", "cn_code": "601628", "hk_code": "02628"},
    {"id": "000063", "name_zh": "中兴通讯", "name_en": "ZTE Corporation", "group": "CN_A", "cn_code": "000063", "hk_code": "00763"},
    {"id": "600660", "name_zh": "福耀玻璃", "name_en": "Fuyao Glass Industry Group Co., Ltd.", "group": "CN_A", "cn_code": "600660", "hk_code": "03606"},
    {"id": "601899", "name_zh": "紫金矿业", "name_en": "Zijin Mining Group Co., Ltd.", "group": "CN_A", "cn_code": "601899", "hk_code": "02899"},
    {"id": "600036", "name_zh": "招商银行", "name_en": "China Merchants Bank Co., Ltd.", "group": "CN_A", "cn_code": "600036", "hk_code": "03968"},
    {"id": "601919", "name_zh": "中远海控", "name_en": "COSCO SHIPPING Holdings Co., Ltd.", "group": "CN_A", "cn_code": "601919", "hk_code": "01919"},
    # D 组：纯港股（16 家）
    {"id": "00700", "name_zh": "腾讯控股", "name_en": "Tencent Holdings Limited", "group": "HK_PRIMARY", "hk_code": "00700"},
    {"id": "00001", "name_zh": "长和", "name_en": "CK Hutchison Holdings Limited", "group": "HK_PRIMARY", "hk_code": "00001"},
    {"id": "09992", "name_zh": "泡泡玛特", "name_en": "Pop Mart International Group Limited", "group": "HK_PRIMARY", "hk_code": "09992"},
    {"id": "01024", "name_zh": "快手", "name_en": "Kuaishou Technology", "group": "HK_PRIMARY", "hk_code": "01024"},
    {"id": "ZHIPU", "name_zh": "智谱", "name_en": "Beijing Zhipu Huazhang Technology Co., Ltd.", "group": "HK_PRIMARY", "hk_code": "02513", "note": "Listed 2026-01-08 on HKEX; capture prospectus/interim/annual reports"},
    {"id": "00316", "name_zh": "东方海外国际", "name_en": "Orient Overseas (International) Limited", "group": "HK_PRIMARY", "hk_code": "00316"},
    {"id": "01810", "name_zh": "小米集团", "name_en": "Xiaomi Corporation", "group": "HK_PRIMARY", "hk_code": "01810"},
    {"id": "01299", "name_zh": "友邦保险", "name_en": "AIA Group Limited", "group": "HK_PRIMARY", "hk_code": "01299"},
    {"id": "02020", "name_zh": "安踏体育", "name_en": "ANTA Sports Products Limited", "group": "HK_PRIMARY", "hk_code": "02020"},
    {"id": "02382", "name_zh": "舜宇光学科技", "name_en": "Sunny Optical Technology (Group) Company Limited", "group": "HK_PRIMARY", "hk_code": "02382"},
    {"id": "00175", "name_zh": "吉利汽车", "name_en": "Geely Automobile Holdings Limited", "group": "HK_PRIMARY", "hk_code": "00175"},
    {"id": "01860", "name_zh": "汇量科技", "name_en": "Mobvista Inc.", "group": "HK_PRIMARY", "hk_code": "01860"},
    {"id": "00992", "name_zh": "联想集团", "name_en": "Lenovo Group Limited", "group": "HK_PRIMARY", "hk_code": "00992"},
    {"id": "00388", "name_zh": "香港交易所", "name_en": "Hong Kong Exchanges and Clearing Limited", "group": "HK_PRIMARY", "hk_code": "00388"},
    {"id": "02097", "name_zh": "蜜雪集团", "name_en": "MIXUE Group", "group": "HK_PRIMARY", "hk_code": "02097", "note": "Listed 2025-03 on HKEX; capture prospectus/interim/annual reports"},
    {"id": "03399", "name_zh": "粤运交通", "name_en": "Guangdong Yueyun Transportation Company Limited", "group": "HK_PRIMARY", "hk_code": "03399"},
    # E 组：韩国主板（2 家）
    {"id": "SAMSUNG", "name_zh": "三星电子 (三星集团)", "name_en": "Samsung Electronics Co., Ltd.", "group": "KR_MAIN", "kr_code": "005930.KS", "note": "KRX/DART + Samsung IR English annual reports (separate pipeline)"},
    {"id": "SK_HYNIX", "name_zh": "SK海力士", "name_en": "SK hynix Inc.", "group": "KR_MAIN", "kr_code": "000660.KS", "note": "KRX/DART + SK hynix IR annual reports (separate pipeline)"},
]

# XBRL 关键财务科目映射（兼顾 us-gaap 与 ifrs-full）
XBRL_METRIC_DEFS: list[dict[str, Any]] = [
    {
        "key": "revenue",
        "label_zh": "营业收入",
        "label_en": "Revenue",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "RevenuesNetOfInterestExpense",
            "InterestAndDividendIncomeOperating",
        ],
        "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers"],
    },
    {
        "key": "gross_profit",
        "label_zh": "毛利润",
        "label_en": "Gross Profit",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["GrossProfit"],
        "ifrs-full": ["GrossProfit"],
    },
    {
        "key": "operating_income",
        "label_zh": "营业利润",
        "label_en": "Operating Income",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["OperatingIncomeLoss"],
        "ifrs-full": ["ProfitLossFromOperatingActivities"],
    },
    {
        "key": "net_income",
        "label_zh": "净利润",
        "label_en": "Net Income",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
        "ifrs-full": ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    },
    {
        "key": "eps_diluted",
        "label_zh": "摊薄每股收益",
        "label_en": "Diluted EPS",
        "kind": "duration",
        "scale": 1,
        "unit_label": "per_share",
        "us-gaap": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
        "ifrs-full": ["DilutedEarningsLossPerShare", "BasicEarningsLossPerShare"],
    },
    {
        "key": "rnd",
        "label_zh": "研发费用",
        "label_en": "R&D Expense",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
        "ifrs-full": ["ResearchAndDevelopmentExpense"],
    },
    {
        "key": "operating_cash_flow",
        "label_zh": "经营性现金流",
        "label_en": "Operating Cash Flow",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["NetCashProvidedByUsedInOperatingActivities"],
        "ifrs-full": ["CashFlowsFromUsedInOperatingActivities"],
    },
    {
        "key": "capex",
        "label_zh": "资本开支",
        "label_en": "CapEx",
        "kind": "duration",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "ifrs-full": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    },
    {
        "key": "cash",
        "label_zh": "现金及等价物",
        "label_en": "Cash & Equivalents",
        "kind": "instant",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
        "ifrs-full": ["CashAndCashEquivalents"],
    },
    {
        "key": "total_assets",
        "label_zh": "总资产",
        "label_en": "Total Assets",
        "kind": "instant",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["Assets"],
        "ifrs-full": ["Assets"],
    },
    {
        "key": "equity",
        "label_zh": "股东权益",
        "label_en": "Stockholders Equity",
        "kind": "instant",
        "scale": 1_000_000,
        "unit_label": "M",
        "us-gaap": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "ifrs-full": ["Equity", "EquityAttributableToOwnersOfParent"],
    },
]


class _RateLimiter:
    """线程安全的全局请求节流器，避免触发 SEC EDGAR 10 req/s 限流。"""

    def __init__(self, max_per_sec: float = 4.2) -> None:
        self._min_interval = 1.0 / max_per_sec
        self._lock = threading.Lock()
        self._next_ts = 0.0

    def wait(self) -> None:
        sleep_for = 0.0
        with self._lock:
            now = time.monotonic()
            if now < self._next_ts:
                sleep_for = self._next_ts - now
                self._next_ts += self._min_interval
            else:
                self._next_ts = now + self._min_interval
        if sleep_for > 0:
            time.sleep(sleep_for)


_SEC_LIMITER = _RateLimiter(4.2)


def _http_get_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 35.0,
    rate_limit_sec: bool = False,
    retries: int = 3,
) -> bytes:
    compliance.validate_https_url(url)
    last_err: Exception | None = None
    for attempt in range(retries):
        if rate_limit_sec:
            _SEC_LIMITER.wait()
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with compliance._safe_urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code == 404:
                raise
            if exc.code in (403, 429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except Exception as exc:
            last_err = exc
            if attempt + 1 < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    assert last_err is not None
    raise last_err


def _sec_get_json(url: str, timeout: float = 35.0) -> Any:
    raw = _http_get_bytes(
        url,
        headers={"User-Agent": get_sec_user_agent(), "Accept-Encoding": "gzip"},
        timeout=timeout,
        rate_limit_sec=True,
    )
    return json.loads(raw.decode("utf-8", errors="replace"))


def _resolve_sec_tickers() -> dict[str, dict[str, Any]]:
    data = _sec_get_json("https://www.sec.gov/files/company_tickers.json", timeout=25.0)
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in data.values():
        tk = str(row.get("ticker") or "").strip().upper()
        if not tk:
            continue
        rec = {
            "cik": str(int(row["cik_str"])).zfill(10),
            "title": str(row.get("title") or ""),
            "ticker": tk,
        }
        by_ticker[tk] = rec
        by_ticker.setdefault(tk.replace("-", "."), rec)
        by_ticker.setdefault(tk.replace(".", "-"), rec)
    return by_ticker


def _resolve_cninfo_stocks() -> dict[str, dict[str, Any]]:
    raw = _http_get_bytes(
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
        headers={"User-Agent": BROWSER_USER_AGENT},
        timeout=20.0,
    )
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return {
        str(s.get("code") or "").zfill(6): {
            "org_id": str(s.get("orgId") or ""),
            "zwjc": str(s.get("zwjc") or ""),
        }
        for s in data.get("stockList", [])
        if s.get("code")
    }


def _resolve_hkex_stocks() -> dict[str, dict[str, Any]]:
    raw = _http_get_bytes(
        "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json",
        headers={"User-Agent": BROWSER_USER_AGENT},
        timeout=20.0,
    )
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return {
        str(item.get("c") or "").zfill(5): {
            "stock_id": str(item.get("i") or ""),
            "name_hk": str(item.get("n") or ""),
        }
        for item in data
        if item.get("c")
    }


def _fallback_cninfo_org_id(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"gssh0{code}"
    if code.startswith(("4", "8")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def build_master_registry(repo_root: str | Path) -> list[dict[str, Any]]:
    """解析 92 家全部公司的 SEC CIK / CNINFO orgId / HKEX stockId 并写入 companies_master.json。"""
    root = Path(repo_root)
    sec_map = _resolve_sec_tickers()
    cn_map = _resolve_cninfo_stocks()
    hk_map = _resolve_hkex_stocks()

    master: list[dict[str, Any]] = []
    missing_sec: list[str] = []
    missing_hk: list[str] = []

    for spec in COMPANIES_SPEC:
        item = dict(spec)
        sec_tk = item.get("sec_ticker")
        if item.get("sec_cik_override"):
            ovr = str(item["sec_cik_override"]).zfill(10)
            item["sec_cik"] = ovr
            item["sec_entity_name"] = item["name_en"]
            item["sec_submissions_url"] = f"https://data.sec.gov/submissions/CIK{ovr}.json"
        elif sec_tk:
            hit = sec_map.get(sec_tk) or sec_map.get(sec_tk.replace("-", "."))
            if not hit:
                missing_sec.append(sec_tk)
            else:
                item["sec_cik"] = hit["cik"]
                item["sec_entity_name"] = hit["title"]
                item["sec_submissions_url"] = f"https://data.sec.gov/submissions/CIK{hit['cik']}.json"

        cn_code = item.get("cn_code")
        if cn_code:
            hit = cn_map.get(cn_code)
            item["cn_org_id"] = hit["org_id"] if hit and hit["org_id"] else _fallback_cninfo_org_id(cn_code)
            if hit and hit.get("zwjc"):
                item["cn_short_name"] = hit["zwjc"]

        hk_code = item.get("hk_code")
        if hk_code:
            hit = hk_map.get(hk_code.zfill(5))
            if not hit:
                missing_hk.append(hk_code)
            else:
                item["hk_stock_id"] = hit["stock_id"]
                item["hk_name"] = hit["name_hk"]

        master.append(item)

    if missing_sec:
        raise RuntimeError(f"SEC company_tickers 未能解析出以下标的 CIK: {missing_sec}")

    out_path = root / "corpora" / "cn-hk-financial-10y" / "companies_master.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if missing_hk:
        print(f"[WARN] 部分港股代码在 HKEX activestock 中暂缺: {missing_hk}", flush=True)
    return master


def _extract_sec_filings_from_pages(
    pages: list[dict[str, Any]],
    *,
    cik: str,
    max_years: int = 10,
) -> list[dict[str, Any]]:
    """从 SEC submissions recent + files 历史分页中筛选近 max_years 个财年的 10-K/20-F；刚上市无年报时补招股书与 10-Q。"""
    cik_num = str(int(cik))
    annual_by_year: dict[str, dict[str, Any]] = {}
    amendments: dict[str, dict[str, Any]] = {}
    prospectus: list[dict[str, Any]] = []
    quarterlies: list[dict[str, Any]] = []

    for page in pages:
        forms = page.get("form") or []
        filings_dates = page.get("filingDate") or []
        report_dates = page.get("reportDate") or []
        accessions = page.get("accessionNumber") or []
        prim_docs = page.get("primaryDocument") or []

        for idx, form in enumerate(forms):
            f_str = str(form or "").strip().upper()
            f_date = str(filings_dates[idx] if idx < len(filings_dates) else "")
            r_date = str(report_dates[idx] if idx < len(report_dates) else "")
            acc = str(accessions[idx] if idx < len(accessions) else "")
            pdoc = str(prim_docs[idx] if idx < len(prim_docs) else "")
            if not acc or not pdoc or not pdoc.lower().endswith((".htm", ".html")):
                continue
            fy = (r_date or f_date)[:4]
            if not fy.isdigit():
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc.replace('-', '')}/{pdoc}"
            rec = {
                "market": "SEC",
                "form": f_str,
                "fiscal_year": fy,
                "filing_date": f_date,
                "report_date": r_date,
                "accession_number": acc,
                "primary_document": pdoc,
                "url": url,
            }
            if f_str in ("10-K", "20-F"):
                # 同财年优先保留最新提交的主表
                prev = annual_by_year.get(fy)
                if prev is None or f_date > prev["filing_date"]:
                    annual_by_year[fy] = rec
            elif f_str in ("10-K/A", "20-F/A"):
                prev = amendments.get(fy)
                if prev is None or f_date > prev["filing_date"]:
                    amendments[fy] = rec
            elif f_str in ("424B4", "424B1", "S-1", "S-1/A", "F-1", "F-1/A") and len(prospectus) < 3:
                prospectus.append(rec)
            elif f_str in ("10-Q", "6-K") and len(quarterlies) < 8:
                quarterlies.append(rec)

    if annual_by_year:
        for fy, arec in amendments.items():
            if fy not in annual_by_year:
                annual_by_year[fy] = arec
        rows = sorted(annual_by_year.values(), key=lambda x: (x["fiscal_year"], x["filing_date"]), reverse=True)
        return rows[:max_years]

    # 刚 IPO 尚未满首年年报周期（例如 2026-06 上市的 SpaceX）
    fallback: list[dict[str, Any]] = []
    seen_acc: set[str] = set()
    for rec in prospectus[:2] + quarterlies[:6]:
        if rec["accession_number"] not in seen_acc:
            seen_acc.add(rec["accession_number"])
            fallback.append(rec)
    return fallback


def _fetch_sec_filings_for_company(
    cik: str,
    max_years: int = 10,
    extra_ciks: list[str] | None = None,
) -> list[dict[str, Any]]:
    ciks = [cik] + [str(c).zfill(10) for c in (extra_ciks or []) if str(c).zfill(10) != cik]
    combined: list[dict[str, Any]] = []
    for cur_cik in ciks:
        sub = _sec_get_json(f"https://data.sec.gov/submissions/CIK{cur_cik}.json", timeout=30.0)
        filings_root = sub.get("filings") or {}
        recent = filings_root.get("recent") or {}
        pages: list[dict[str, Any]] = [recent]
        picked = _extract_sec_filings_from_pages(pages, cik=cur_cik, max_years=max_years)

        if len(picked) < max_years:
            for fmeta in filings_root.get("files") or []:
                fname = str(fmeta.get("name") or "").strip()
                if not fname:
                    continue
                older = _sec_get_json(f"https://data.sec.gov/submissions/{fname}", timeout=30.0)
                pages.append(older)
                picked = _extract_sec_filings_from_pages(pages, cik=cur_cik, max_years=max_years)
                if len([p for p in picked if p["form"] in ("10-K", "20-F", "10-K/A", "20-F/A")]) >= max_years:
                    break
        combined.extend(picked)
        if len({x["fiscal_year"] for x in combined if x["form"] in ("10-K", "20-F")}) >= max_years:
            break

    # 合并主实体与前身实体的年报并按财年去重取前 max_years 个
    by_year: dict[str, dict[str, Any]] = {}
    fallback: list[dict[str, Any]] = []
    for rec in combined:
        if rec["form"] in ("10-K", "20-F", "10-K/A", "20-F/A"):
            fy = rec["fiscal_year"]
            prev = by_year.get(fy)
            is_orig = rec["form"] in ("10-K", "20-F")
            prev_orig = bool(prev and prev["form"] in ("10-K", "20-F"))
            if prev is None or (is_orig and not prev_orig) or (is_orig == prev_orig and rec["filing_date"] > prev["filing_date"]):
                by_year[fy] = rec
        else:
            fallback.append(rec)
    if by_year:
        return sorted(by_year.values(), key=lambda x: (x["fiscal_year"], x["filing_date"]), reverse=True)[:max_years]
    return fallback


def _fetch_cninfo_annuals(cn_code: str, org_id: str, max_years: int = 10) -> list[dict[str, Any]]:
    column = "sse" if cn_code.startswith(("6", "9")) else "szse"
    by_year: dict[str, dict[str, Any]] = {}
    for page_num in (1, 2):
        payload = urllib.parse.urlencode(
            {
                "stock": f"{cn_code},{org_id}",
                "tabName": "fulltext",
                "pageSize": "30",
                "pageNum": str(page_num),
                "column": column,
                "category": "category_ndbg_szsh;",
                "plate": "",
                "seDate": "2016-01-01~2026-12-31",
                "searchkey": "",
                "secid": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "false",
            }
        ).encode("utf-8")
        raw = _http_get_bytes(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=payload,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/new/disclosure",
                "Origin": "https://www.cninfo.com.cn",
            },
            timeout=20.0,
        )
        d = json.loads(raw.decode("utf-8", errors="replace"))
        anns = d.get("announcements") or []
        if not anns:
            break

        for ann in anns:
            title = re.sub(r"<[^>]+>", "", str(ann.get("announcementTitle") or "")).strip()
            adj = str(ann.get("adjunctUrl") or "").strip().lstrip("/")
            if not title or not adj or not adj.lower().endswith(".pdf"):
                continue
            if any(bad in title for bad in ("摘要", "英文", "取消", "更正公告", "补充公告", "半年度", "英文版", "审计报告")):
                continue
            if "年度报告" not in title and "年报" not in title:
                continue
            m_year = re.search(r"(20\d{2})\s*年", title) or re.search(r"(20\d{2})", title)
            if not m_year:
                continue
            fy = m_year.group(1)
            ts = ann.get("announcementTime") or 0
            fdate = time.strftime("%Y-%m-%d", time.localtime(float(ts) / 1000.0)) if ts else ""
            rec = {
                "market": "CNINFO",
                "form": "ANNUAL_REPORT",
                "fiscal_year": fy,
                "filing_date": fdate,
                "title": title,
                "url": f"https://static.cninfo.com.cn/{adj}",
            }
            prev = by_year.get(fy)
            # 同一年度若有“更新后/修订版”或更晚发布，优先保留新版
            is_updated = any(k in title for k in ("更新", "修订"))
            prev_updated = bool(prev and any(k in prev["title"] for k in ("更新", "修订")))
            if prev is None or (is_updated and not prev_updated) or (is_updated == prev_updated and fdate > prev["filing_date"]):
                by_year[fy] = rec

        if not d.get("hasMore") or len(by_year) >= max_years:
            break

    rows = sorted(by_year.values(), key=lambda x: (x["fiscal_year"], x["filing_date"]), reverse=True)
    return rows[:max_years]


def _query_hkex_servlet(
    stock_id: str,
    *,
    t1code: str,
    t2code: str,
    lang: str = "ZH",
    from_date: str = "20160101",
    row_range: int = 30,
) -> list[dict[str, Any]]:
    url = (
        "https://www1.hkexnews.hk/search/titleSearchServlet.do?"
        f"sortDir=0&sortByOptions=DateTime&category=0&market=SEHK&stockId={stock_id}"
        f"&documentType=-1&fromDate={from_date}&toDate=20261231&title=&searchType=1"
        f"&t1code={t1code}&t2Gcode=-2&t2code={t2code}&rowRange={row_range}&lang={lang}"
    )
    raw = _http_get_bytes(
        url,
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh",
        },
        timeout=20.0,
    )
    hd = json.loads(raw.decode("utf-8", errors="replace"))
    res = hd.get("result")
    if isinstance(res, str):
        return json.loads(res) if res.strip() else []
    return res or []


def _fetch_hkex_filings(stock_id: str, max_years: int = 10) -> list[dict[str, Any]]:
    rows = _query_hkex_servlet(stock_id, t1code="40000", t2code="40100", lang="ZH", row_range=30)
    if not rows:
        rows = _query_hkex_servlet(stock_id, t1code="40000", t2code="40100", lang="C", row_range=30)

    by_year: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = str(row.get("TITLE") or "").strip()
        flink = str(row.get("FILE_LINK") or "").strip()
        dtime = str(row.get("DATE_TIME") or "").strip()
        if not title or not flink or not flink.lower().endswith(".pdf"):
            continue
        if any(bad in title for bad in ("補充", "更正", "通函", "代表委任", "Summary")):
            continue
        m_y = re.search(r"(20\d{2})", title)
        if m_y:
            fy = m_y.group(1)
        elif len(dtime) >= 10:
            # DD/MM/YYYY 格式，港股年报在次年春季发布，归上一财年
            m_d = re.search(r"\d{2}/\d{2}/(20\d{2})", dtime)
            fy = str(int(m_d.group(1)) - 1) if m_d else ""
        else:
            fy = ""
        if not fy:
            continue
        rec = {
            "market": "HKEX",
            "form": "ANNUAL_REPORT",
            "fiscal_year": fy,
            "filing_date": dtime,
            "title": title,
            "url": f"https://www1.hkexnews.hk{flink}",
        }
        prev = by_year.get(fy)
        if prev is None or dtime > prev["filing_date"]:
            by_year[fy] = rec

    result = sorted(by_year.values(), key=lambda x: (x["fiscal_year"], x["filing_date"]), reverse=True)[:max_years]

    # 新上市不足三年的港股标的（如智谱 02513、蜜雪集团 02097）补全中期报告与上市招股书
    if len(result) <= 2:
        existing_links = {r["url"] for r in result}
        interims = _query_hkex_servlet(stock_id, t1code="40000", t2code="40200", lang="ZH", from_date="20240101", row_range=10)
        for row in interims[:2]:
            title = str(row.get("TITLE") or "").strip()
            flink = str(row.get("FILE_LINK") or "").strip()
            dtime = str(row.get("DATE_TIME") or "").strip()
            full_u = f"https://www1.hkexnews.hk{flink}"
            if flink.lower().endswith(".pdf") and full_u not in existing_links:
                m_y = re.search(r"(20\d{2})", title) or re.search(r"(20\d{2})", dtime)
                existing_links.add(full_u)
                result.append(
                    {
                        "market": "HKEX",
                        "form": "INTERIM_REPORT",
                        "fiscal_year": m_y.group(1) if m_y else "2026",
                        "filing_date": dtime,
                        "title": title,
                        "url": full_u,
                    }
                )
        prospectuses = _query_hkex_servlet(stock_id, t1code="-2", t2code="-2", lang="ZH", from_date="20240101", row_range=80)
        for row in prospectuses:
            title = str(row.get("TITLE") or "").strip()
            flink = str(row.get("FILE_LINK") or "").strip()
            dtime = str(row.get("DATE_TIME") or "").strip()
            if not flink.lower().endswith(".pdf"):
                continue
            if any(k in title for k in ("全球發售", "招股", "上市文件")) and not any(
                b in title for b in ("申請表格", "公告", "結果", "穩定價格", "超額配股權", "補遺")
            ):
                m_y = re.search(r"(20\d{2})", dtime) or re.search(r"(20\d{2})", title)
                result.append(
                    {
                        "market": "HKEX",
                        "form": "PROSPECTUS",
                        "fiscal_year": m_y.group(1) if m_y else "2025",
                        "filing_date": dtime,
                        "title": title,
                        "url": f"https://www1.hkexnews.hk{flink}",
                    }
                )
                break
    return result


def build_filing_catalog(repo_root: str | Path, master: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """为 92 家实体抓取三市场近 10 年官方年报链接目录，写入 filing_catalog.json 及合规 manifest.json。"""
    root = Path(repo_root)
    master_path = root / "corpora" / "cn-hk-financial-10y" / "companies_master.json"
    if master is None:
        master = json.loads(master_path.read_text(encoding="utf-8")) if master_path.is_file() else build_master_registry(root)

    entries: list[dict[str, Any]] = []
    sec_total = cn_total = hk_total = 0
    sec_manifest_sources: list[dict[str, Any]] = []

    for idx, co in enumerate(master, 1):
        sec_list: list[dict[str, Any]] = []
        cn_list: list[dict[str, Any]] = []
        hk_list: list[dict[str, Any]] = []

        if co.get("sec_cik"):
            sec_list = _fetch_sec_filings_for_company(co["sec_cik"], max_years=10, extra_ciks=co.get("extra_sec_ciks"))
            sec_total += len(sec_list)
            years = sorted({f["fiscal_year"] for f in sec_list})
            sec_manifest_sources.append(
                {
                    "name": f"{co['id']}_sec_10y",
                    "ticker": co["sec_ticker"],
                    "cik": co["sec_cik"],
                    "company_zh": co["name_zh"],
                    "url": co["sec_submissions_url"],
                    "license": "SEC-Public-Filing",
                    "filing_count": len(sec_list),
                    "year_span": f"{years[0]}..{years[-1]}" if years else "",
                }
            )

        if co.get("cn_code") and co.get("cn_org_id"):
            cn_list = _fetch_cninfo_annuals(co["cn_code"], co["cn_org_id"], max_years=10)
            cn_total += len(cn_list)
            time.sleep(0.15)

        # 纯港股、或 A 股晚于 2016 上市需要港股补年报的 A+H 标的，拉取港股中文年报目录
        need_hk = co["group"] == "HK_PRIMARY" or (
            co.get("hk_stock_id") and len(cn_list) < 10 and co["group"] == "CN_A"
        )
        if need_hk and co.get("hk_stock_id"):
            hk_list = _fetch_hkex_filings(co["hk_stock_id"], max_years=10)
            hk_total += len(hk_list)
            time.sleep(0.15)

        entries.append(
            {
                "id": co["id"],
                "name_zh": co["name_zh"],
                "name_en": co["name_en"],
                "group": co["group"],
                "sec_ticker": co.get("sec_ticker"),
                "sec_cik": co.get("sec_cik"),
                "cn_code": co.get("cn_code"),
                "hk_code": co.get("hk_code"),
                "kr_code": co.get("kr_code"),
                "note": co.get("note", ""),
                "sec_filings": sec_list,
                "cninfo_filings": cn_list,
                "hkex_filings": hk_list,
            }
        )
        if idx % 15 == 0 or idx == len(master):
            print(
                f"[catalog {idx}/{len(master)}] SEC={sec_total} CNINFO={cn_total} HKEX={hk_total}",
                flush=True,
            )

    catalog = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "companies_total": len(entries),
        "summary": {
            "sec_companies": sum(1 for e in entries if e["sec_filings"]),
            "sec_filings_total": sec_total,
            "cninfo_companies": sum(1 for e in entries if e["cninfo_filings"]),
            "cninfo_filings_total": cn_total,
            "hkex_companies": sum(1 for e in entries if e["hkex_filings"]),
            "hkex_filings_total": hk_total,
            "kr_manual_ir_companies": sum(1 for e in entries if e["group"] == "KR_MAIN"),
        },
        "companies": entries,
    }
    cat_path = root / "corpora" / "cn-hk-financial-10y" / "filing_catalog.json"
    cat_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 生成两份合规 manifest.json（严格经 compliance.validate_manifest 校验）
    sec_manifest = {
        "slug": "sec-10y-core",
        "title": "美股与赴美中概近 10 年 SEC 官方年报与 XBRL 财务总表（48 家）",
        "description": "覆盖 48 家美股核心科技/消费/金融/能源/医药龙头及赴美上市中概 ADR 的近 10 年 SEC EDGAR 10-K/20-F 原文与 XBRL companyfacts 审计数据（含 2026-06 上市的 SpaceX SPCX 招股书/季报）。全部为美国联邦法定公开披露（SEC-Public-Filing），可用于公开检索基准与文档核验评测。",
        "domain": "FINANCE",
        "region": "GLOBAL",
        "mode": "pack",
        "license": "SEC-Public-Filing",
        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        "sources": sec_manifest_sources,
    }
    compliance.validate_manifest(sec_manifest)
    sec_mf_path = root / "corpora" / "sec-10y-core" / "manifest.json"
    sec_mf_path.parent.mkdir(parents=True, exist_ok=True)
    sec_mf_path.write_text(json.dumps(sec_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    recipe_manifest = {
        "slug": "cn-hk-financial-10y",
        "title": "中美港韩 92 家核心公司近 10 年财报全市场配方清单（A股/港股/韩股仅配方不分发原件）",
        "description": "统一编目 26 家 A 股/A+H（巨潮资讯 CNINFO）、16 家纯港股及补齐年份 A+H（港交所披露易 HKEXnews）与 2 家韩国科技巨头（三星电子/SK海力士），附带 92 家公司权威代码映射与官方原文链接目录；原 PDF 与本地重建 Markdown 严格保存在被 .gitignore 隔离的 data/ 下，不随公共仓库二次分发。",
        "domain": "FINANCE",
        "region": "CN",
        "mode": "recipe",
        "license": "Multi-Exchange-Public-Disclosure",
        "source_url": "https://www.cninfo.com.cn/",
        "catalog_file": "corpora/cn-hk-financial-10y/filing_catalog.json",
        "sources": [
            {
                "name": "cninfo_a_share_10y_recipe",
                "url": "https://www.cninfo.com.cn/new/disclosure",
                "local_path": "data/raw/cn-hk-financial-10y/cninfo",
                "license": "CNINFO-Public-Disclosure",
                "company_count": catalog["summary"]["cninfo_companies"],
                "filing_count": cn_total,
            },
            {
                "name": "hkexnews_hk_10y_recipe",
                "url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh",
                "local_path": "data/raw/cn-hk-financial-10y/hkex",
                "license": "HKEX-Public-Disclosure",
                "company_count": catalog["summary"]["hkex_companies"],
                "filing_count": hk_total,
            },
            {
                "name": "krx_ir_south_korea_recipe",
                "url": "https://englishdart.fss.or.kr/",
                "local_path": "data/raw/cn-hk-financial-10y/krx",
                "license": "KRX-Public-Disclosure",
                "company_count": 2,
                "filing_count": 0,
            },
        ],
    }
    compliance.validate_manifest(recipe_manifest)
    rec_mf_path = root / "corpora" / "cn-hk-financial-10y" / "manifest.json"
    rec_mf_path.write_text(json.dumps(recipe_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return catalog


def _parse_iso_days(start: str, end: str) -> int:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except Exception:
        return -1


def _format_num(val: Any, unit_label: str) -> str:
    try:
        num = float(val)
    except Exception:
        return str(val)
    if unit_label == "per_share":
        return f"{num:,.2f}"
    # 对百万元以上规模以原值+M双写或清晰整数千分位呈现，既保留审计精度又方便阅读
    if abs(num) >= 1_000_000:
        return f"{num / 1_000_000:,.2f}M ({int(round(num)):,})"
    return f"{num:,.2f}"


def build_xbrl_summary_markdown(company: dict[str, Any], facts_json: dict[str, Any]) -> str:
    """将 SEC companyfacts JSON 解析为近 10 年 us-gaap/ifrs-full 中英双语审计摘要表。"""
    facts = facts_json.get("facts") or {}
    taxonomies_present = [tx for tx in ("us-gaap", "ifrs-full") if facts.get(tx)]
    rows_by_year_metric: dict[str, dict[str, dict[str, Any]]] = {}

    for mdef in XBRL_METRIC_DEFS:
        mkey = mdef["key"]
        candidates_by_year: dict[str, tuple[tuple[int, str], dict[str, Any]]] = {}
        for tx in ("us-gaap", "ifrs-full"):
            tx_block = facts.get(tx) or {}
            tags = mdef.get(tx) or []
            for tag_prio, tag in enumerate(tags):
                concept = tx_block.get(tag)
                if not concept:
                    continue
                units = concept.get("units") or {}
                for unit_name, records in units.items():
                    if mdef["unit_label"] == "per_share" and "shares" not in unit_name.lower():
                        continue
                    if mdef["unit_label"] != "per_share" and unit_name.lower() == "shares":
                        continue
                    for rec in records:
                        form = str(rec.get("form") or "").upper()
                        if form not in ("10-K", "20-F", "10-K/A", "20-F/A"):
                            continue
                        end = str(rec.get("end") or "")
                        start = str(rec.get("start") or "")
                        if len(end) < 4:
                            continue
                        if mdef["kind"] == "duration":
                            days = _parse_iso_days(start, end)
                            if days < 300 or days > 400:
                                continue
                        else:
                            # 资产负债表瞬时科目的 frame 常带 Q4I；若缺 frame 也允许随年报 end 落入当年
                            frame = str(rec.get("frame") or "")
                            if frame and re.search(r"Q[123]I?$", frame):
                                continue
                        year = end[:4]
                        filed = str(rec.get("filed") or "")
                        rank = (0 if form in ("10-K", "20-F") else 1, tag_prio, "" if tx == "us-gaap" else "z")
                        score_key = (-rank[0], -rank[1], filed)
                        prev = candidates_by_year.get(year)
                        if prev is None or score_key > prev[0]:
                            candidates_by_year[year] = (
                                score_key,
                                {
                                    "val": rec.get("val"),
                                    "unit": unit_name,
                                    "end": end,
                                    "filed": filed,
                                    "accn": str(rec.get("accn") or ""),
                                    "form": form,
                                    "taxonomy": tx,
                                    "tag": tag,
                                },
                            )
        for yr, (_, info) in candidates_by_year.items():
            rows_by_year_metric.setdefault(yr, {})[mkey] = info

    years_desc = sorted(rows_by_year_metric.keys(), reverse=True)[:10]
    ticker = str(company.get("sec_ticker") or company.get("id") or "")
    cik = str(company.get("sec_cik") or "")
    name_zh = str(company.get("name_zh") or "")
    name_en = str(company.get("name_en") or facts_json.get("entityName") or "")

    lines = [
        "---",
        "corpus: sec-10y-core",
        "license: SEC-Public-Filing",
        "source_type: sec-xbrl-companyfacts",
        f"ticker: {ticker}",
        f"cik: {cik}",
        f"company_zh: {name_zh}",
        f"company_en: {name_en}",
        f"taxonomies: {','.join(taxonomies_present) or 'none'}",
        f"source_url: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        "---",
        "",
        f"# {name_zh} ({name_en} / {ticker}) — SEC 官方 XBRL 近 10 年审计财务总表",
        "",
        f"- **CIK**: `{cik}` | **港股联动代码**: `{company.get('hk_code') or '-'}` | **会计准则标签**: `{', '.join(taxonomies_present) or 'N/A'}`",
        "",
    ]

    if not years_desc:
        lines.append("> 注：SEC XBRL companyfacts 暂未收录该发行人的 10-K/20-F 年度指标（如近期刚上市尚未满首年年报周期）。")
        return "\n".join(lines) + "\n"

    lines.append("## 核心财务指标年度对比表（单位：原币种百万 M 与精确原值；EPS 为每股原值）\n")
    headers = ["财年结束(FY End)"] + [f"{m['label_zh']} {m['label_en']}" for m in XBRL_METRIC_DEFS] + ["最新申报日 / Accession"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for yr in years_desc:
        ymap = rows_by_year_metric[yr]
        end_dates = [v["end"] for v in ymap.values() if v.get("end")]
        accns = sorted({f"{v['form']} {v['filed']} ({v['accn']})" for v in ymap.values() if v.get("accn")})
        row = [max(end_dates) if end_dates else yr]
        for m in XBRL_METRIC_DEFS:
            info = ymap.get(m["key"])
            if info is None:
                row.append("-")
            else:
                unit_tag = info["unit"].replace("/shares", "")
                row.append(f"{unit_tag} {_format_num(info['val'], m['unit_label'])}")
        row.append("; ".join(accns[:2]) if accns else "-")
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"


def _merge_currency_cells(cells: list[str]) -> list[str]:
    """折叠 SEC HTML 表中的空白占位格，并将孤立货币符号 '$' 与右括号 ')' 和相邻数字拼合。"""
    raw = [re.sub(r"\s+", " ", c.replace("\u00a0", " ")).strip() for c in cells]
    # 剔除完全空格前先识别是否有相邻货币符号
    merged: list[str] = []
    i = 0
    while i < len(raw):
        cur = raw[i]
        if not cur:
            i += 1
            continue
        if cur in ("$", "¥", "€", "£", "HK$", "US$", "RMB", "NT$") and i + 1 < len(raw):
            nxt = raw[i + 1]
            if not nxt and i + 2 < len(raw):
                nxt = raw[i + 2]
                i += 1
            if nxt:
                cur = f"{cur}{nxt}"
                i += 1
        if cur in (")", "%") and merged:
            merged[-1] = f"{merged[-1]}{cur}"
        else:
            merged.append(cur)
        i += 1
    return merged


class _SecHtmlMarkdownParser(HTMLParser):
    """流式剥离 iXBRL hidden/header/script/style，并将财务表格还原为 Markdown 管道表。"""

    SKIP_TAGS = frozenset(
        {"script", "style", "head", "ix:header", "ix:hidden", "ix:references", "ix:resources", "noscript"}
    )
    BLOCK_END_TAGS = frozenset({"p", "div", "li", "section", "article", "blockquote", "br"})
    HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.blocks: list[str] = []
        self.text_buf: list[str] = []
        self.in_heading: str | None = None
        self.heading_buf: list[str] = []
        self.table_depth = 0
        self.current_table: list[list[str]] = []
        self.current_row: list[str] = []
        self.in_cell = False
        self.cell_buf: list[str] = []

    def _flush_text(self) -> None:
        if self.text_buf:
            txt = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.text_buf).replace("\u00a0", " ")).strip()
            self.text_buf.clear()
            if txt:
                self.blocks.append(txt)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self.skip_depth > 0:
            self.skip_depth += 1
            return
        style = dict(attrs).get("style") or ""
        if t in self.SKIP_TAGS or re.search(r"display\s*:\s*none", style, re.I):
            self.skip_depth = 1
            return

        if t in self.HEADING_TAGS and self.table_depth == 0:
            self._flush_text()
            self.in_heading = t
            self.heading_buf.clear()
        elif t == "table":
            if self.table_depth == 0:
                self._flush_text()
                self.current_table = []
            self.table_depth += 1
        elif t == "tr" and self.table_depth == 1:
            self.current_row = []
        elif t in ("td", "th") and self.table_depth == 1:
            self.in_cell = True
            self.cell_buf.clear()
        elif t == "br":
            if self.in_cell:
                self.cell_buf.append(" ")
            elif self.in_heading:
                self.heading_buf.append(" ")
            else:
                self.text_buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self.skip_depth > 0:
            self.skip_depth -= 1
            return

        if t in self.HEADING_TAGS and self.in_heading == t:
            level = int(t[1])
            htxt = re.sub(r"\s+", " ", "".join(self.heading_buf).replace("\u00a0", " ")).strip()
            self.heading_buf.clear()
            self.in_heading = None
            if htxt:
                self.blocks.append(f"{'#' * min(level + 1, 4)} {htxt}")
        elif t in ("td", "th") and self.table_depth == 1 and self.in_cell:
            self.current_row.append("".join(self.cell_buf))
            self.cell_buf.clear()
            self.in_cell = False
        elif t == "tr" and self.table_depth == 1:
            cleaned = _merge_currency_cells(self.current_row)
            if cleaned:
                self.current_table.append(cleaned)
            self.current_row = []
        elif t == "table" and self.table_depth > 0:
            self.table_depth -= 1
            if self.table_depth == 0 and self.current_table:
                self._emit_table(self.current_table)
                self.current_table = []
        elif t in self.BLOCK_END_TAGS and self.table_depth == 0 and not self.in_heading:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0 or not data:
            return
        if self.in_cell:
            self.cell_buf.append(data)
        elif self.in_heading:
            self.heading_buf.append(data)
        elif self.table_depth == 0:
            self.text_buf.append(data)

    def _emit_table(self, rows: list[list[str]]) -> None:
        max_cols = max((len(r) for r in rows), default=0)
        if max_cols <= 1:
            # 单列表格通常是 SEC 排版盒子，按普通段落输出更干净
            for r in rows:
                line = " ".join(r).strip()
                if line:
                    self.blocks.append(line)
            return

        padded = [
            [c.replace("|", "\\|") for c in (r + [""] * (max_cols - len(r)))]
            for r in rows
        ]
        md_lines = [
            "| " + " | ".join(padded[0]) + " |",
            "| " + " | ".join(["---"] * max_cols) + " |",
        ]
        for r in padded[1:]:
            md_lines.append("| " + " | ".join(r) + " |")
        self.blocks.append("\n".join(md_lines))

    def result(self) -> str:
        self._flush_text()
        out = "\n\n".join(b for b in self.blocks if b.strip())
        return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def sec_html_to_markdown(html_text: str) -> str:
    """将 SEC EDGAR 10-K/20-F/424B4 HTML（含 iXBRL）清洗为带结构与对齐表格的 Markdown。"""
    # 预先快速剔除最重型的 ix:header 与 script/style 块，降低解析开销
    cleaned = re.sub(r"<ix:(?:header|hidden|references|resources)\b[^>]*>.*?</ix:(?:header|hidden|references|resources)>", " ", html_text, flags=re.I | re.S)
    cleaned = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", cleaned, flags=re.I | re.S)
    parser = _SecHtmlMarkdownParser()
    parser.feed(cleaned)
    parser.close()
    return parser.result()


def materialize_sec_xbrl(repo_root: str | Path, force: bool = False) -> dict[str, Any]:
    """拉取 48 家 SEC 标的 companyfacts JSON 并生成双语 10 年 XBRL 审计财务总表。"""
    root = Path(repo_root)
    master_path = root / "corpora" / "cn-hk-financial-10y" / "companies_master.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    sec_companies = [c for c in master if c.get("sec_cik")]

    xbrl_json_dir = root / "data" / "raw" / "sec-10y-core" / "xbrl_json"
    summary_dir = root / "data" / "raw" / "sec-10y-core" / "xbrl_summaries"
    xbrl_json_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    done = 0
    missing_404: list[str] = []
    for idx, co in enumerate(sec_companies, 1):
        tk = co["id"]
        cik = co["sec_cik"]
        json_path = xbrl_json_dir / f"{tk}_companyfacts.json"
        md_path = summary_dir / f"{tk}_10y_xbrl.md"

        facts: dict[str, Any] | None = None
        if json_path.is_file() and not force and json_path.stat().st_size > 50:
            facts = json.loads(json_path.read_text(encoding="utf-8"))
        else:
            try:
                facts = _sec_get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=40.0)
                tmp = json_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
                tmp.replace(json_path)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    missing_404.append(tk)
                    facts = {"cik": int(cik), "entityName": co["name_en"], "facts": {}}
                else:
                    raise

        md_txt = build_xbrl_summary_markdown(co, facts)
        tmp_md = md_path.with_suffix(".tmp")
        tmp_md.write_text(md_txt, encoding="utf-8")
        tmp_md.replace(md_path)
        done += 1
        if idx % 10 == 0 or idx == len(sec_companies):
            print(f"[sec-xbrl {idx}/{len(sec_companies)}] done={done}, no_xbrl_404={missing_404}", flush=True)

    return {"companies": done, "no_xbrl_404": missing_404, "summary_dir": str(summary_dir)}


def _download_and_convert_one_sec(co: dict[str, Any], f: dict[str, Any], out_root: Path, force: bool) -> tuple[str, int, str | None]:
    tk = co["id"]
    target_dir = out_root / tk
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_form = re.sub(r"[^A-Za-z0-9_-]+", "_", f["form"])
    fname = f"{f['fiscal_year']}_{safe_form}_{f['filing_date']}.md"
    dest = target_dir / fname

    if dest.is_file() and not force and dest.stat().st_size > 200:
        return ("skipped", dest.stat().st_size, None)

    raw_bytes = _http_get_bytes(
        f["url"],
        headers={"User-Agent": get_sec_user_agent(), "Accept-Encoding": "gzip"},
        timeout=45.0,
        rate_limit_sec=True,
        retries=3,
    )
    html_text = raw_bytes.decode("utf-8", errors="replace")
    body_md = sec_html_to_markdown(html_text)
    header = "\n".join(
        [
            "---",
            "corpus: sec-10y-core",
            "license: SEC-Public-Filing",
            f"ticker: {co.get('sec_ticker') or tk}",
            f"cik: {co.get('sec_cik') or ''}",
            f"company_zh: {co['name_zh']}",
            f"company_en: {co['name_en']}",
            f"form: {f['form']}",
            f"fiscal_year: {f['fiscal_year']}",
            f"filing_date: {f['filing_date']}",
            f"report_date: {f.get('report_date') or ''}",
            f"accession_number: {f['accession_number']}",
            f"source_url: {f['url']}",
            "---",
            "",
            f"# {co['name_zh']} ({co['name_en']} / {co.get('sec_ticker') or tk}) {f['fiscal_year']} {f['form']}",
            "",
        ]
    )
    full_md = header + body_md
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(full_md, encoding="utf-8")
    tmp.replace(dest)
    return ("downloaded", len(full_md.encode("utf-8")), None)


def materialize_sec_filings(repo_root: str | Path, force: bool = False, workers: int = 4) -> dict[str, Any]:
    """增量并发下载并清洗 48 家 SEC 标的近 10 年 10-K/20-F（及刚上市招股书/10-Q）原文为 Markdown。"""
    root = Path(repo_root)
    cat_path = root / "corpora" / "cn-hk-financial-10y" / "filing_catalog.json"
    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    out_root = root / "data" / "raw" / "sec-10y-core" / "filings"
    out_root.mkdir(parents=True, exist_ok=True)

    sec_companies = [c for c in catalog["companies"] if c.get("sec_filings")]
    downloaded = skipped = total_bytes = 0
    failed: list[dict[str, Any]] = []

    for cidx, co in enumerate(sec_companies, 1):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(_download_and_convert_one_sec, co, f, out_root, force): f
                for f in co["sec_filings"]
            }
            for fut in as_completed(futs):
                f = futs[fut]
                try:
                    status, nbytes, _ = fut.result()
                    if status == "downloaded":
                        downloaded += 1
                    else:
                        skipped += 1
                    total_bytes += nbytes
                except Exception as exc:
                    failed.append({"company_id": co["id"], "url": f["url"], "form": f["form"], "error": str(exc)})

        if cidx % 5 == 0 or cidx == len(sec_companies):
            print(
                f"[sec-filings {cidx}/{len(sec_companies)}] downloaded={downloaded} skipped={skipped} "
                f"total_mb={total_bytes / (1024 * 1024):.1f} failed={len(failed)}",
                flush=True,
            )

    failed_path = root / "data" / "raw" / "sec-10y-core" / "failed_filings.json"
    failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "companies": len(sec_companies),
        "downloaded": downloaded,
        "skipped": skipped,
        "total_bytes": total_bytes,
        "failed_count": len(failed),
        "failed_path": str(failed_path),
    }


KEY_STATEMENT_KEYWORDS: tuple[str, ...] = (
    # 简体 A 股核心财务报表与摘要
    "主要会计数据",
    "主要财务指标",
    "财务摘要",
    "合并资产负债表",
    "合并利润表",
    "合并现金流量表",
    "资产负债表",
    "利润表",
    "现金流量表",
    # 繁体港股核心财务报表与摘要（含无“综合/合并”字样与分隔符变体）
    "財務摘要",
    "財務概要",
    "五年財務概要",
    "主要財務數據",
    "主要會計數據",
    "主要財務指標",
    "合併資產負債表",
    "合併利潤表",
    "合併現金流量表",
    "合併損益",
    "損益及其他",
    "綜合收益",
    "綜合損益",
    "綜合全面收益",
    "綜合財務狀況表",
    "財務狀況表",
    "綜合資產負債表",
    "綜合現金流量表",
    "現金流量表",
    "資產負債表",
    # 英文年报/招股书核心财务报表
    "Financial Highlights",
    "Consolidated Income Statement",
    "Consolidated Balance Sheet",
    "Consolidated Statement of Financial Position",
    "Consolidated Statement of Cash Flows",
    "Consolidated Statement of Comprehensive Income",
)

KEY_MDA_KEYWORDS: tuple[str, ...] = (
    "管理层讨论与分析",
    "管理层讨论",
    "管理層討論及分析",
    "管理層討論",
    "Management Discussion and Analysis",
)

KEY_FINANCIAL_PAGE_KEYWORDS: tuple[str, ...] = KEY_STATEMENT_KEYWORDS + KEY_MDA_KEYWORDS
_RECIPE_DOWNLOAD_LIMITER = _RateLimiter(3.5)


def is_key_financial_page(page_no: int, text: str) -> bool:
    """判断页面是否为前 10 页或简/繁/英三大财务报表、财务摘要及 MD&A 核心页。"""
    if page_no <= 10:
        return True
    lower_txt = text.lower()
    compact_txt = "".join(text.split())
    return _match_any_kw(compact_txt, lower_txt, KEY_FINANCIAL_PAGE_KEYWORDS)


def _match_any_kw(compact_txt: str, lower_txt: str, kws: tuple[str, ...]) -> bool:
    for kw in kws:
        if kw.isascii():
            if kw.lower() in lower_txt:
                return True
        elif kw in compact_txt:
            return True
    return False


def recipe_output_paths(
    repo_root: str | Path,
    market: str,
    company_id: str,
    filing: dict[str, Any],
    *,
    used_stems: set[str] | None = None,
) -> tuple[Path, Path]:
    """物理隔离原始 PDF 归档目录 (data/archive) 与干净重建 Markdown 目录 (data/raw)，避免同名覆盖。"""
    root = Path(repo_root)
    fy = re.sub(r"[^A-Za-z0-9_-]+", "", str(filing.get("fiscal_year") or "unknown"))
    form = re.sub(r"[^A-Za-z0-9_-]+", "_", str(filing.get("form") or "REPORT")).strip("_")
    stem = f"{fy}_{form}"
    if used_stems is not None and stem in used_stems:
        fdate = re.sub(r"[^0-9A-Za-z_-]+", "-", str(filing.get("filing_date") or "")).strip("-")[:10]
        cand = f"{stem}_{fdate}" if fdate else f"{stem}_2"
        seq = 2
        while cand in used_stems:
            seq += 1
            cand = f"{stem}_{fdate}_{seq}" if fdate else f"{stem}_{seq}"
        stem = cand
    if used_stems is not None:
        used_stems.add(stem)

    pdf_path = root / "data" / "archive" / "cn-hk-financial-10y" / market / company_id / f"{stem}.pdf"
    md_path = root / "data" / "raw" / "cn-hk-financial-10y" / market / company_id / f"{stem}.md"
    return pdf_path, md_path


def build_recipe_markdown_header(
    *,
    company: dict[str, Any],
    filing: dict[str, Any],
    market: str,
    archive_pdf: Path,
    stats: dict[str, Any],
    corpus_slug: str = "cn-hk-financial-10y",
) -> str:
    """生成带完整官方披露来源、版权模式与页级重建统计的 YAML 溯源头。"""
    lic_map = {
        "cninfo": "CNINFO-Public-Disclosure",
        "hkex": "HKEX-Public-Disclosure",
        "krx": "KRX-Public-Disclosure",
    }
    lic = lic_map.get(market, "Multi-Exchange-Public-Disclosure")
    code = str(company.get("cn_code") or company.get("hk_code") or company.get("kr_code") or company["id"])
    title = str(filing.get("title") or f"{filing.get('fiscal_year')} {filing.get('form')}").replace("\n", " ").strip()
    lines = [
        "---",
        f"corpus: {corpus_slug}",
        "mode: recipe-local-only",
        f"license: {lic}",
        f"market: {market}",
        f"company_id: {company['id']}",
        f"company_zh: {company['name_zh']}",
        f"company_en: {company.get('name_en') or ''}",
        f"code: {code}",
    ]
    if company.get("wiki_track"):
        lines.append(f"wiki_track: {company['wiki_track']}")
    lines.extend(
        [
            f"fiscal_year: {filing.get('fiscal_year') or ''}",
            f"form: {filing.get('form') or ''}",
            f"filing_date: {filing.get('filing_date') or ''}",
            f"title: {title}",
            f"source_url: {filing.get('url') or ''}",
            f"archive_pdf: {archive_pdf}",
            f"pages_total: {stats.get('pages_total', 0)}",
            f"table_rebuilt_pages: {stats.get('table_rebuilt_pages', 0)}",
            f"tables_total: {stats.get('tables_total', 0)}",
            f"cmap_fixes: {stats.get('cmap_fixes', 0)}",
            "---",
            "",
            f"# {company['name_zh']} ({code}) {filing.get('fiscal_year') or ''} {title}",
            "",
        ]
    )
    return "\n".join(lines)


def convert_recipe_pdf_to_markdown(
    pdf_path: Path,
    md_path: Path,
    *,
    company: dict[str, Any],
    filing: dict[str, Any],
    market: str,
    parse_mode: str = "key-sections",
    max_table_pages: int = 45,
    use_layout: bool = True,
    corpus_slug: str = "cn-hk-financial-10y",
    extra_statement_keywords: tuple[str, ...] = (),
    extra_mda_keywords: tuple[str, ...] = (),
) -> dict[str, Any]:
    """按方案 1（核心财务页高精度表格重建 + 其余页轻量纯文本 + CMap 修复）转换单份 PDF。"""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    total_pages = len(doc)
    rebuilt_pages = 0
    total_tables = 0
    total_cmap_fixes = 0
    chunks: list[str] = []
    stmt_kws = KEY_STATEMENT_KEYWORDS + tuple(extra_statement_keywords)
    mda_kws = KEY_FINANCIAL_PAGE_KEYWORDS + tuple(extra_mda_keywords)

    try:
        prio1_set: set[int] = set()
        prio2_set: set[int] = set()

        if parse_mode == "text-only":
            selected: set[int] = set()
        elif parse_mode == "full-tables":
            selected = set(range(total_pages))
        else:
            for p_idx in range(total_pages):
                page_no = p_idx + 1
                raw_txt = doc[p_idx].get_text("text")
                fixed_txt, _ = pdf_table_fix.repair_hkex_cmap(raw_txt)
                low = fixed_txt.lower()
                compact = "".join(fixed_txt.split())
                if (page_no <= 8 and len(compact) >= 120 and any(ch.isdigit() for ch in compact)) or _match_any_kw(
                    compact, low, stmt_kws
                ):
                    prio1_set.add(p_idx)
                elif page_no > 8 and _match_any_kw(compact, low, mda_kws):
                    prio2_set.add(p_idx)

            # 优先保证封面摘要与三大主表全部高精度重建，剩余额度分配给业务/风险/MD&A 页
            sorted_p1 = sorted(prio1_set)[:max_table_pages]
            selected = set(sorted_p1)
            rem = max(0, max_table_pages - len(selected))
            if rem > 0:
                selected.update(sorted(prio2_set)[:rem])

        code = str(company.get("cn_code") or company.get("hk_code") or company.get("kr_code") or company["id"])
        page_ctx = f"{company['name_zh']} ({code}) {filing.get('fiscal_year') or ''} {filing.get('form') or ''}".strip()

        for p_idx in range(total_pages):
            page_no = p_idx + 1
            if p_idx in selected:
                rebuilt = pdf_table_fix.extract_page_to_markdown(
                    doc[p_idx], page_no, total_pages, fix_cmap=True, use_layout=use_layout
                )
                md_pg = rebuilt["markdown"].replace(f"## 第 {page_no} 页", f"## 第 {page_no} 页 | {page_ctx}", 1)
                chunks.append(md_pg)
                rebuilt_pages += 1
                total_tables += int(rebuilt["tables"])
                total_cmap_fixes += int(rebuilt["cmap_fixes"])
            else:
                txt_fixed, n_fix = pdf_table_fix.repair_hkex_cmap(doc[p_idx].get_text("text").strip())
                total_cmap_fixes += n_fix
                if txt_fixed:
                    chunks.append(f"<!-- page: {page_no}/{total_pages} -->\n## 第 {page_no} 页 | {page_ctx}\n\n{txt_fixed}")
    finally:
        doc.close()

    stats = {
        "pages_total": total_pages,
        "table_rebuilt_pages": rebuilt_pages,
        "tables_total": total_tables,
        "cmap_fixes": total_cmap_fixes,
    }
    header = build_recipe_markdown_header(
        company=company,
        filing=filing,
        market=market,
        archive_pdf=pdf_path,
        stats=stats,
        corpus_slug=corpus_slug,
    )
    full_md = header + "\n\n---\n\n".join(chunks).strip() + "\n"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_md = md_path.with_suffix(".tmp")
    tmp_md.write_text(full_md, encoding="utf-8")
    tmp_md.replace(md_path)
    return stats


def _download_one_recipe_pdf(job: dict[str, Any]) -> tuple[str, int]:
    pdf_path = Path(job["pdf_path"])
    if pdf_path.is_file() and pdf_path.stat().st_size >= 1024:
        with pdf_path.open("rb") as fh:
            if fh.read(4) == b"%PDF":
                return ("skipped", pdf_path.stat().st_size)

    url = str(job["url"])
    market = str(job["market"])
    referer = (
        "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh"
        if market == "hkex"
        else "https://www.cninfo.com.cn/new/disclosure"
    )
    _RECIPE_DOWNLOAD_LIMITER.wait()
    raw = _http_get_bytes(
        url,
        headers={"User-Agent": BROWSER_USER_AGENT, "Referer": referer},
        timeout=65.0,
        retries=3,
    )
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"响应内容非有效 PDF（前 64 字节: {raw[:64]!r}）")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = pdf_path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(pdf_path)
    return ("downloaded", len(raw))


def _run_isolated_pdf_job(job: dict[str, Any]) -> dict[str, Any]:
    """每份 PDF 独立子进程转换，防 MuPDF C 扩展偶发 SIGSEGV 污染池中其他文档，并自动三级降级。"""
    md_path = Path(job["md_path"])
    if md_path.is_file() and not job["force"] and md_path.stat().st_size >= 500:
        return {
            "status": "skipped",
            "bytes": md_path.stat().st_size,
            "pages_total": 0,
            "table_rebuilt_pages": 0,
            "tables_total": 0,
            "cmap_fixes": 0,
        }

    base_mode = str(job["parse_mode"])
    if job.get("market") == "cninfo":
        # A 股框线年报关闭 ONNX layout，实测提速 ~10x 且能更稳定检出有线大表
        attempts: list[tuple[str, bool]] = [(base_mode, False), ("text-only", False)]
    else:
        # 港股三线表常缺竖框线，优先走 layout 框表并在异常时降级至无 layout/纯文本
        attempts = [(base_mode, True), (base_mode, False), ("text-only", False)]
    seen_att: list[tuple[str, bool]] = []
    for a in attempts:
        if a not in seen_att:
            seen_att.append(a)

    last_err = ""
    src_dir = str(Path(__file__).resolve().parents[1])
    existing_pp = os.environ.get("PYTHONPATH", "").strip()
    merged_pp = f"{src_dir}{os.pathsep}{existing_pp}" if existing_pp else src_dir
    sub_env = {**os.environ, "PYTHONPATH": merged_pp, "PYTHONIOENCODING": "utf-8"}
    for pm, ul in seen_att:
        payload = json.dumps(
            {
                "pdf_path": job["pdf_path"],
                "md_path": job["md_path"],
                "company": job["company"],
                "filing": job["filing"],
                "market": job["market"],
                "parse_mode": pm,
                "max_table_pages": job["max_table_pages"],
                "use_layout": ul,
                "corpus_slug": job.get("corpus_slug", "cn-hk-financial-10y"),
                "extra_statement_keywords": job.get("extra_statement_keywords", []),
                "extra_mda_keywords": job.get("extra_mda_keywords", []),
            },
            ensure_ascii=False,
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "vericorpus.financial_10y", "--convert-one-json", payload],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=sub_env,
                timeout=240 if ul else 300,
            )
        except subprocess.TimeoutExpired as exc:
            last_err = f"timeout={exc.timeout}s mode=({pm},layout={ul})"
            continue
        if proc.returncode == 0:
            for ln in reversed(proc.stdout.splitlines()):
                if ln.startswith("CONVERT_ONE_OK:"):
                    stats = json.loads(ln[len("CONVERT_ONE_OK:") :])
                    return {"status": "parsed", "bytes": md_path.stat().st_size, **stats}
            raise RuntimeError(f"子进程未输出 CONVERT_ONE_OK: {proc.stdout[-200:]}")
        last_err = f"rc={proc.returncode} mode=({pm},layout={ul}) err={proc.stderr.strip()[-180:]}"

    raise RuntimeError(last_err)


def download_recipe_pdfs(
    repo_root: str | Path,
    *,
    market: str = "cninfo",
    parse_mode: str = "key-sections",
    limit_companies: int | None = None,
    workers: int = 4,
    max_table_pages: int = 45,
    force: bool = False,
) -> dict[str, Any]:
    """供 Phase 2/3 调用：两阶段并行下载原始 PDF 至 data/archive/ 并按方案 1 隔离转码 Markdown 至 data/raw/。"""
    root = Path(repo_root)
    cat_path = root / "corpora" / "cn-hk-financial-10y" / "filing_catalog.json"
    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    field = "cninfo_filings" if market == "cninfo" else "hkex_filings"

    targets = [c for c in catalog["companies"] if c.get(field)]
    if limit_companies:
        targets = targets[:limit_companies]

    effective_max_pages = min(max_table_pages, 25) if market == "hkex" else min(max_table_pages, 40)

    jobs: list[dict[str, Any]] = []
    for co in targets:
        used_stems: set[str] = set()
        co_meta = {
            "id": co["id"],
            "name_zh": co["name_zh"],
            "name_en": co["name_en"],
            "cn_code": co.get("cn_code"),
            "hk_code": co.get("hk_code"),
            "kr_code": co.get("kr_code"),
        }
        for item in co[field]:
            pdf_path, md_path = recipe_output_paths(root, market, co["id"], item, used_stems=used_stems)
            jobs.append(
                {
                    "market": market,
                    "company_id": co["id"],
                    "company": co_meta,
                    "filing": item,
                    "url": item["url"],
                    "pdf_path": str(pdf_path),
                    "md_path": str(md_path),
                    "parse_mode": parse_mode,
                    "max_table_pages": effective_max_pages,
                    "force": force,
                }
            )

    downloaded = dl_skipped = pdf_bytes = 0
    failed: list[dict[str, Any]] = []
    parse_jobs: list[dict[str, Any]] = []

    # 阶段 1：并发下载官方原 PDF 到 data/archive/
    with ThreadPoolExecutor(max_workers=workers) as dl_pool:
        fut_map = {dl_pool.submit(_download_one_recipe_pdf, j): j for j in jobs}
        done_cnt = 0
        for fut in as_completed(fut_map):
            j = fut_map[fut]
            done_cnt += 1
            try:
                st, nb = fut.result()
                if st == "downloaded":
                    downloaded += 1
                else:
                    dl_skipped += 1
                pdf_bytes += nb
                parse_jobs.append(j)
            except Exception as exc:
                failed.append({"stage": "download", "company_id": j["company_id"], "url": j["url"], "error": str(exc)})
            if done_cnt % 20 == 0 or done_cnt == len(jobs):
                print(
                    f"[{market}-dl {done_cnt}/{len(jobs)}] downloaded={downloaded} skipped={dl_skipped} "
                    f"pdf_mb={pdf_bytes / (1024 * 1024):.1f} failed={len(failed)}",
                    flush=True,
                )

    # 阶段 2：独立子进程并行执行方案 1 Markdown 转换（单份崩溃仅降级本份，绝不连累池中其他 PDF）
    parsed = md_skipped = md_bytes = pages_total = rebuilt_pages = tables_total = cmap_fixes = 0
    parse_jobs.sort(key=lambda x: (x["company_id"], x["pdf_path"]))
    if parse_jobs:
        with ThreadPoolExecutor(max_workers=workers) as p_pool:
            fut_map = {p_pool.submit(_run_isolated_pdf_job, j): j for j in parse_jobs}
            done_cnt = 0
            for fut in as_completed(fut_map):
                j = fut_map[fut]
                done_cnt += 1
                try:
                    res = fut.result()
                    if res["status"] == "parsed":
                        parsed += 1
                    else:
                        md_skipped += 1
                    md_bytes += int(res["bytes"])
                    pages_total += int(res["pages_total"])
                    rebuilt_pages += int(res["table_rebuilt_pages"])
                    tables_total += int(res["tables_total"])
                    cmap_fixes += int(res["cmap_fixes"])
                except Exception as exc:
                    failed.append({"stage": "parse", "company_id": j["company_id"], "pdf": j["pdf_path"], "error": str(exc)})
                if done_cnt % 10 == 0 or done_cnt == len(parse_jobs):
                    print(
                        f"[{market}-parse {done_cnt}/{len(parse_jobs)}] parsed={parsed} skipped={md_skipped} "
                        f"md_mb={md_bytes / (1024 * 1024):.1f} pages={pages_total} rebuilt_pages={rebuilt_pages} "
                        f"tables={tables_total} cmap={cmap_fixes} failed={len(failed)}",
                        flush=True,
                    )

    raw_base = root / "data" / "raw" / "cn-hk-financial-10y"
    raw_base.mkdir(parents=True, exist_ok=True)
    failed_path = raw_base / f"failed_{market}.json"
    failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "market": market,
        "companies": len(targets),
        "jobs": len(jobs),
        "downloaded": downloaded,
        "dl_skipped": dl_skipped,
        "pdf_bytes": pdf_bytes,
        "parsed": parsed,
        "md_skipped": md_skipped,
        "md_bytes": md_bytes,
        "pages_total": pages_total,
        "table_rebuilt_pages": rebuilt_pages,
        "tables_total": tables_total,
        "cmap_fixes": cmap_fixes,
        "failed_count": len(failed),
        "failed_path": str(failed_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="vericorpus 全球 92 家 10 年财报语料扩展管线")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument(
        "--stage",
        choices=("catalog", "sec-xbrl", "sec-filings", "phase1-all", "cninfo", "hkex", "phase2-3"),
        default="catalog",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--parse-mode", choices=("key-sections", "full-tables"), default="key-sections")
    parser.add_argument("--limit-companies", type=int, default=None)
    parser.add_argument("--max-table-pages", type=int, default=45)
    parser.add_argument("--convert-one-json", default=None)
    args = parser.parse_args()

    if args.convert_one_json:
        spec = json.loads(args.convert_one_json)
        st = convert_recipe_pdf_to_markdown(
            Path(spec["pdf_path"]),
            Path(spec["md_path"]),
            company=spec["company"],
            filing=spec["filing"],
            market=spec["market"],
            parse_mode=spec["parse_mode"],
            max_table_pages=int(spec["max_table_pages"]),
            use_layout=bool(spec["use_layout"]),
            corpus_slug=str(spec.get("corpus_slug") or "cn-hk-financial-10y"),
            extra_statement_keywords=tuple(spec.get("extra_statement_keywords") or ()),
            extra_mda_keywords=tuple(spec.get("extra_mda_keywords") or ()),
        )
        print("CONVERT_ONE_OK:" + json.dumps(st, ensure_ascii=False))
        return

    root = Path(args.repo_root)
    if args.stage in ("catalog", "phase1-all"):
        master = build_master_registry(root)
        cat = build_filing_catalog(root, master=master)
        print("CATALOG_SUMMARY:", json.dumps(cat["summary"], ensure_ascii=False))
    if args.stage in ("sec-xbrl", "phase1-all"):
        xbrl_res = materialize_sec_xbrl(root, force=args.force)
        print("XBRL_SUMMARY:", json.dumps(xbrl_res, ensure_ascii=False))
    if args.stage in ("sec-filings", "phase1-all"):
        fil_res = materialize_sec_filings(root, force=args.force, workers=args.workers)
        print("FILINGS_SUMMARY:", json.dumps(fil_res, ensure_ascii=False))
    if args.stage in ("cninfo", "phase2-3"):
        cn_res = download_recipe_pdfs(
            root,
            market="cninfo",
            parse_mode=args.parse_mode,
            limit_companies=args.limit_companies,
            workers=args.workers,
            max_table_pages=args.max_table_pages,
            force=args.force,
        )
        print("CNINFO_SUMMARY:", json.dumps(cn_res, ensure_ascii=False))
    if args.stage in ("hkex", "phase2-3"):
        hk_res = download_recipe_pdfs(
            root,
            market="hkex",
            parse_mode=args.parse_mode,
            limit_companies=args.limit_companies,
            workers=args.workers,
            max_table_pages=args.max_table_pages,
            force=args.force,
        )
        print("HKEX_SUMMARY:", json.dumps(hk_res, ensure_ascii=False))


if __name__ == "__main__":
    main()
