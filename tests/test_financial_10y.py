"""防止合规边界被破坏、SEC submissions 翻页漏掉前几年年报、iXBRL 隐藏节点污染正文与表格对齐失效、XBRL 漏掉 20-F IFRS 口径及 92 家实体清单缺漏重复。"""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class Financial10YTests(unittest.TestCase):
    def test_recipe_licenses_rejected_in_pack_and_allowed_in_recipe(self):
        from vericorpus import compliance

        for lic in (
            "CNINFO-Public-Disclosure",
            "KRX-Public-Disclosure",
            "Multi-Exchange-Public-Disclosure",
        ):
            bad_pack = {
                "slug": "bad-cn-pack",
                "title": "受限披露",
                "mode": "pack",
                "license": lic,
                "source_url": "https://www.cninfo.com.cn/",
                "sources": [{"name": "sample", "url": "https://www.cninfo.com.cn/"}],
            }
            with self.assertRaises(compliance.ComplianceError, msg=f"pack 应拦截 {lic}"):
                compliance.validate_manifest(bad_pack)

            good_recipe = dict(bad_pack, mode="recipe", slug="good-cn-recipe")
            compliance.validate_manifest(good_recipe)

        sec_pack = {
            "slug": "sec-10y-core",
            "title": "SEC 公开财报",
            "mode": "pack",
            "license": "SEC-Public-Filing",
            "source_url": "https://data.sec.gov/submissions/",
            "sources": [{"name": "nvda", "url": "https://data.sec.gov/submissions/CIK0001045810.json"}],
        }
        compliance.validate_manifest(sec_pack)

    def test_companies_spec_has_exactly_92_unique_companies_and_valid_codes(self):
        from vericorpus import financial_10y

        spec = financial_10y.COMPANIES_SPEC
        self.assertEqual(len(spec), 92, f"应为 92 家去重后的公司，实际为 {len(spec)}")
        ids = [c["id"] for c in spec]
        self.assertEqual(len(set(ids)), 92, "存在重复公司 id")

        sec_cos = [c for c in spec if c.get("sec_ticker")]
        self.assertEqual(len(sec_cos), 48, f"SEC 覆盖标的应为 48 家，实际为 {len(sec_cos)}")
        for c in sec_cos:
            if c.get("sec_ticker"):
                self.assertEqual(c["sec_ticker"], c["sec_ticker"].strip().upper())

        cn_cos = [c for c in spec if c.get("cn_code")]
        self.assertEqual(len(cn_cos), 26, f"A股标的应为 26 家，实际为 {len(cn_cos)}")
        for c in cn_cos:
            self.assertRegex(c["cn_code"], r"^\d{6}$")

        hk_primary = [c for c in spec if c.get("group") == "HK_PRIMARY"]
        self.assertEqual(len(hk_primary), 16, f"纯港股标的应为 16 家，实际为 {len(hk_primary)}")

        # 验证合并/拆分的特殊标的与历史前身实体均正确存在
        by_id = {c["id"]: c for c in spec}
        for key in ("SPCX", "ZHIPU", "LMT", "BAC", "CB", "POLY_CN", "SAMSUNG", "SK_HYNIX", "TSM"):
            self.assertIn(key, by_id, f"缺少关键实体 {key}")
        self.assertEqual(by_id["XOM"].get("sec_cik_override"), "0000034088")
        self.assertIn("0001649338", by_id["AVGO"].get("extra_sec_ciks") or [])

        # 确保公开清单与源码不含个人语音转写拆分或点名备注
        for c in spec:
            note = str(c.get("note") or "")
            self.assertNotIn("洛克" + "西", note)
            self.assertNotIn("split from", note)
            self.assertNotIn("two mentions", note)

    def test_sec_html_to_markdown_strips_ixbrl_hidden_and_merges_currency_cells(self):
        from vericorpus import financial_10y

        sample_html = """
        <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
          <head><title>Test 10-K</title><style>.h{display:none}</style></head>
          <body>
            <ix:header>
              <ix:hidden><ix:nonNumeric name="dei:EntityRegistrantName">SHOULD_NOT_APPEAR</ix:nonNumeric></ix:hidden>
              <ix:references><link:schemaRef href="nvda.xsd"/></ix:references>
            </ix:header>
            <script>var secret_noise = 123;</script>
            <div style="display: none;">HIDDEN_STYLE_NOISE</div>
            <h2>ITEM 7. MANAGEMENT'S DISCUSSION</h2>
            <p>Revenue reached record levels in fiscal 2026.</p>
            <table>
              <tr><td></td><td>Fiscal 2026</td><td></td><td>Fiscal 2025</td><td></td></tr>
              <tr><td>Revenue</td><td>$</td><td>130,497</td><td>$</td><td>60,922</td></tr>
              <tr><td>Net Loss</td><td>$</td><td>(1,234</td><td>)</td><td>(500</td><td>)</td></tr>
            </table>
          </body>
        </html>
        """
        md = financial_10y.sec_html_to_markdown(sample_html)
        self.assertNotIn("SHOULD_NOT_APPEAR", md)
        self.assertNotIn("HIDDEN_STYLE_NOISE", md)
        self.assertNotIn("secret_noise", md)
        self.assertNotIn("nvda.xsd", md)
        self.assertIn("## ITEM 7. MANAGEMENT'S DISCUSSION", md)
        self.assertIn("| Revenue | $130,497 | $60,922 |", md)
        self.assertIn("| Net Loss | $(1,234) | (500) |", md)

    def test_build_xbrl_summary_markdown_handles_us_gaap_and_ifrs_and_pagination_dedup(self):
        from vericorpus import financial_10y

        # 模拟 20-F IFRS 数据，含多年重复重述条目（同财年按最新 filed 去重）
        ifrs_facts = {
            "cik": 1577552,
            "entityName": "Alibaba Group Holding Limited",
            "facts": {
                "ifrs-full": {
                    "Revenue": {
                        "units": {
                            "CNY": [
                                {"start": "2024-04-01", "end": "2025-03-31", "val": 996347000000, "accn": "0001-25", "fy": 2025, "fp": "FY", "form": "20-F", "filed": "2025-06-26"},
                                {"start": "2023-04-01", "end": "2024-03-31", "val": 941168000000, "accn": "0001-24", "fy": 2024, "fp": "FY", "form": "20-F", "filed": "2024-05-23"},
                                # 同一财年在 2025 年 20-F 重述对比列再次出现，应优先保留最新 filed
                                {"start": "2023-04-01", "end": "2024-03-31", "val": 941169000000, "accn": "0001-25", "fy": 2024, "fp": "FY", "form": "20-F", "filed": "2025-06-26"},
                                # 季度噪音（仅 ~90 天）应过滤掉，不冒充全年
                                {"start": "2025-01-01", "end": "2025-03-31", "val": 236454000000, "accn": "0001-25", "fy": 2025, "fp": "FY", "form": "20-F", "filed": "2025-06-26"},
                            ]
                        }
                    },
                    "ProfitLoss": {
                        "units": {
                            "CNY": [
                                {"start": "2024-04-01", "end": "2025-03-31", "val": 125976000000, "accn": "0001-25", "fy": 2025, "fp": "FY", "form": "20-F", "filed": "2025-06-26"},
                            ]
                        }
                    },
                }
            },
        }
        company = {
            "id": "BABA",
            "name_zh": "阿里巴巴",
            "name_en": "Alibaba Group Holding Limited",
            "sec_ticker": "BABA",
            "sec_cik": "0001577552",
            "hk_code": "09988",
        }
        md = financial_10y.build_xbrl_summary_markdown(company, ifrs_facts)
        self.assertIn("阿里巴巴", md)
        self.assertIn("Alibaba Group Holding Limited", md)
        self.assertIn("ifrs-full", md)
        self.assertIn("996,347", md)  # 亿元/百万级或原值格式化
        self.assertIn("941,169", md)  # 去重保留较新 filed
        self.assertNotIn("236,454", md)  # 季度噪音被剔除
        self.assertIn("0001-25", md)  # 保留 accn 溯源

    def test_select_sec_annual_filings_handles_pagination_and_spcx_ipo_fallback(self):
        from vericorpus import financial_10y

        # 模拟 recent + 历史分页 json 拼接凑满 10 年 10-K
        recent = {
            "form": ["10-Q", "10-K", "10-K"],
            "filingDate": ["2026-08-01", "2026-02-25", "2025-02-26"],
            "reportDate": ["2026-06-30", "2026-01-25", "2025-01-26"],
            "accessionNumber": ["0001-26-000003", "0001-26-000002", "0001-25-000001"],
            "primaryDocument": ["q2.htm", "k26.htm", "k25.htm"],
        }
        older_page = {
            "form": ["10-K"] * 10,
            "filingDate": [f"{y}-02-20" for y in range(2024, 2014, -1)],
            "reportDate": [f"{y}-01-28" for y in range(2024, 2014, -1)],
            "accessionNumber": [f"0001-{str(y)[2:]}-000001" for y in range(2024, 2014, -1)],
            "primaryDocument": [f"k{y}.htm" for y in range(2024, 2014, -1)],
        }
        picked = financial_10y._extract_sec_filings_from_pages([recent, older_page], cik="0001045810", max_years=10)
        self.assertEqual(len(picked), 10)
        self.assertEqual(picked[0]["fiscal_year"], "2026")
        self.assertEqual(picked[-1]["fiscal_year"], "2017")

        # 模拟刚 IPO 尚无 10-K（SpaceX 场景）自动降级收录招股书 + 10-Q
        spcx_recent = {
            "form": ["10-Q", "424B4", "S-1/A"],
            "filingDate": ["2026-10-22", "2026-06-15", "2026-06-01"],
            "reportDate": ["2026-09-30", "2026-06-15", "2026-03-31"],
            "accessionNumber": ["0002-26-000003", "0002-26-000002", "0002-26-000001"],
            "primaryDocument": ["q3.htm", "424b4.htm", "s1a.htm"],
        }
        spcx_picked = financial_10y._extract_sec_filings_from_pages([spcx_recent], cik="0001181412", max_years=10)
        forms = [x["form"] for x in spcx_picked]
        self.assertIn("10-Q", forms)
        self.assertIn("424B4", forms)

    def test_is_key_financial_page_matches_simplified_traditional_and_english(self):
        from vericorpus import financial_10y

        # 前 10 页默认精排
        self.assertTrue(financial_10y.is_key_financial_page(1, "年度报告封面"))
        self.assertTrue(financial_10y.is_key_financial_page(10, "财务目录"))

        # 简体、繁体、英文核心财务页必须命中
        for text in (
            "第三节 管理层讨论与分析 公司业务概要",
            "第一节 主要会计数据和财务指标",
            "合并资产负债表 2025年12月31日",
            "合併資產負債表 2025年12月31日",
            "五年財務概要",
            "綜合損益表 截至二零二五年十二月三十一日止年度",
            "綜合全面收益表",
            "綜合財務狀況表",
            "綜合現金流量表",
            "管理層討論及分析",
            "Financial Highlights for the Year Ended",
            "Consolidated Statement of Financial Position",
            "Consolidated Statement of Cash Flows",
        ):
            self.assertTrue(financial_10y.is_key_financial_page(66, text), f"应命中核心页: {text}")

        # 普通环保/治理/履历页（>10 页）不应触发昂贵全表重建
        self.assertFalse(financial_10y.is_key_financial_page(88, "第六节 公司治理 董事、监事、高级管理人员简历及薪酬情况"))
        self.assertFalse(financial_10y.is_key_financial_page(120, "Environmental Protection and Social Responsibility ESG Measures"))

    def test_recipe_pdf_output_paths_separate_archive_and_raw_md(self):
        from vericorpus import financial_10y

        repo_root = Path("/tmp/fake-vericorpus")
        used: set[str] = set()
        f1 = {
            "fiscal_year": "2025",
            "form": "ANNUAL_REPORT",
            "filing_date": "2026-04-03",
            "title": "2025年年度报告",
            "url": "https://static.cninfo.com.cn/finalpage/2026-04-03/demo.pdf",
        }
        f2 = {
            "fiscal_year": "2025",
            "form": "ANNUAL_REPORT",
            "filing_date": "2026-04-18",
            "title": "2025年年度报告（更新后）",
            "url": "https://static.cninfo.com.cn/finalpage/2026-04-18/demo2.pdf",
        }
        pdf1, md1 = financial_10y.recipe_output_paths(repo_root, "cninfo", "600519", f1, used_stems=used)
        pdf2, md2 = financial_10y.recipe_output_paths(repo_root, "cninfo", "600519", f2, used_stems=used)

        self.assertIn("/data/archive/cn-hk-financial-10y/cninfo/600519/", str(pdf1))
        self.assertIn("/data/raw/cn-hk-financial-10y/cninfo/600519/", str(md1))
        self.assertNotEqual(pdf1.parent, md1.parent)
        self.assertNotEqual(pdf1.name, pdf2.name)
        self.assertNotEqual(md1.name, md2.name)

        company = {"id": "600519", "name_zh": "贵州茅台", "name_en": "Kweichow Moutai", "cn_code": "600519"}
        hdr = financial_10y.build_recipe_markdown_header(
            company=company,
            filing=f1,
            market="cninfo",
            archive_pdf=pdf1,
            stats={"pages_total": 180, "table_rebuilt_pages": 24, "tables_total": 35, "cmap_fixes": 0},
        )
        for token in (
            "corpus: cn-hk-financial-10y",
            "mode: recipe-local-only",
            "license: CNINFO-Public-Disclosure",
            "company_zh: 贵州茅台",
            "fiscal_year: 2025",
            "source_url: https://static.cninfo.com.cn/finalpage/2026-04-03/demo.pdf",
        ):
            self.assertIn(token, hdr)


if __name__ == "__main__":
    unittest.main()
