"""防止 SEC 公开评测基准导出器混入受限版权语料、泄露保留评估标的、依赖外部闭源校验器或泄露微调轨迹格式。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class CnReaderPackTests(unittest.TestCase):
    def test_commercial_firewall_rejects_non_sec_license_and_heldout_tickers(self):
        from vericorpus import cn_reader_pack

        self.assertFalse(hasattr(cn_reader_pack, "SYSTEM_" + "PROMPT"))
        self.assertFalse(hasattr(cn_reader_pack, "to_sft_chat_" + "record"))
        self.assertIn("ARM", cn_reader_pack.DEFAULT_HELDOUT_TICKERS)
        for tk in ("BABA", "MSFT", "JPM", "TSM", "XOM"):
            self.assertIn(tk, cn_reader_pack.DEFAULT_HELDOUT_TICKERS)

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_hk.md"
            bad.write_text("---\nlicense: HKEX-Public-Disclosure\nticker: 00700\n---\n\n# 腾讯", encoding="utf-8")
            with self.assertRaises(ValueError):
                cn_reader_pack.read_sec_markdown(bad)

    def test_extract_filing_table_samples_verifies_standalone_character_offsets(self):
        from vericorpus import cn_reader_pack

        sample_md = """---
corpus: sec-ipo-prospectus-pack
license: SEC-Public-Filing
ticker: CRWV
company_zh: CoreWeave
company_en: CoreWeave, Inc.
form: 424B4
fiscal_year: 2025
---

# CoreWeave (CoreWeave, Inc. / CRWV) 2025 424B4

| Year Ended December 31, |  |  |  |
| --- | --- | --- | --- |
| 2022 | 2023 | 2024 |  |
| (in thousands, except per share data) |  |  |  |
| Revenue | $15,830 | $228,943 | $1,915,426 |
| Operating expenses: |  |  |  |
| Total operating expenses | 38,710 | 243,394 | 1,591,068 |
| Operating income (loss) | (22,880) | (14,451) | 324,358 |
| Net loss | $(31,055) | $(593,748) | $(863,448) |
"""
        samples = cn_reader_pack.extract_samples_from_filing_text(
            sample_md,
            ticker="CRWV",
            company_zh="CoreWeave",
            company_en="CoreWeave, Inc.",
            form="424B4",
            fiscal_year="2025",
            source_track="sec-ipo-prospectus-pack",
        )
        self.assertGreaterEqual(len(samples), 3)
        statuses = {s["expected"]["status"] for s in samples}
        self.assertIn("ANSWER", statuses)
        self.assertIn("ABSENT", statuses)
        for s in samples:
            self.assertNotIn("program", s)
            self.assertEqual(s["license"], "SEC-Public-Filing")
            for ev in s["expected"].get("evidence") or []:
                self.assertEqual(s["document"][ev["start"] : ev["end"]], ev["quote"])

        # Leading empty corner cell ("|| 2025 | 2024 |") must NOT shift year columns left!
        compact_hdr_md = """---
corpus: sec-ipo-prospectus-pack
license: SEC-Public-Filing
ticker: CRWV
company_zh: CoreWeave
company_en: CoreWeave, Inc.
form: 10-K
fiscal_year: 2025
---

# CoreWeave 2025 10-K

|| 2025 | 2024 | 2023 |
| --- | --- | --- | --- |
| ($ in millions) |  |  |  |
| Revenue | $5,131 | $1,915 | $229 |
| Gross profit | $3,820 | $1,410 | $150 |
"""
        compact_samples = cn_reader_pack.extract_samples_from_filing_text(
            compact_hdr_md,
            ticker="CRWV",
            company_zh="CoreWeave",
            company_en="CoreWeave, Inc.",
            form="10-K",
            fiscal_year="2025",
            source_track="sec-ipo-prospectus-pack",
        )
        ext_2025 = [s for s in compact_samples if s["category"] == "extract" and "2025" in s["question"]]
        self.assertTrue(ext_2025)
        self.assertEqual(ext_2025[0]["expected"]["value"], "5131")

    def test_build_sec_benchmark_pack_with_synthetic_tree_enforces_zero_leakage(self):
        from vericorpus import cn_reader_pack

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xbrl_dir = root / "sec-10y-core" / "xbrl_summaries"
            filings_dir = root / "sec-10y-core" / "filings"
            ipo_dir = root / "sec-ipo-prospectus-pack"
            out_dir = root / "out"
            xbrl_dir.mkdir(parents=True)
            (filings_dir / "NVDA").mkdir(parents=True)
            (filings_dir / "MSFT").mkdir(parents=True)
            (ipo_dir / "CRWV").mkdir(parents=True)
            (ipo_dir / "ARM").mkdir(parents=True)

            xbrl_tpl = """---
corpus: {corpus}
license: SEC-Public-Filing
ticker: {ticker}
company_zh: {zh}
company_en: {en}
taxonomies: us-gaap
---

| 财年结束(FY End) | 营业收入 Revenue | 毛利润 Gross Profit | 营业利润 Operating Income | 净利润 Net Income | 摊薄每股收益 Diluted EPS | 研发费用 R&D Expense | 经营性现金流 Operating Cash Flow | 资本开支 CapEx | 现金及等价物 Cash & Equivalents | 总资产 Total Assets | 股东权益 Stockholders Equity | 最新申报日 / Accession |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-31 | USD 130,497.00M (130,497,000,000) | USD 97,858.00M (97,858,000,000) | USD 81,453.00M (81,453,000,000) | USD 72,880.00M (72,880,000,000) | USD 2.94 | USD 12,914.00M (12,914,000,000) | USD 64,089.00M (64,089,000,000) | USD 3,236.00M (3,236,000,000) | USD 43,210.00M (43,210,000,000) | USD 111,601.00M (111,601,000,000) | USD 79,327.00M (79,327,000,000) | 10-K 2026-02-25 |
| 2024-12-31 | USD 60,922.00M (60,922,000,000) | USD 44,301.00M (44,301,000,000) | USD 32,972.00M (32,972,000,000) | USD 29,760.00M (29,760,000,000) | USD 1.19 | USD 8,675.00M (8,675,000,000) | USD 28,090.00M (28,090,000,000) | USD 1,069.00M (1,069,000,000) | USD 25,984.00M (25,984,000,000) | USD 65,728.00M (65,728,000,000) | USD 42,978.00M (42,978,000,000) | 10-K 2025-02-26 |
| 2023-12-31 | USD 26,974.00M (26,974,000,000) | USD 15,356.00M (15,356,000,000) | USD 4,224.00M (4,224,000,000) | USD 4,368.00M (4,368,000,000) | USD 0.17 | USD 7,339.00M (7,339,000,000) | USD 5,641.00M (5,641,000,000) | - | USD 13,296.00M (13,296,000,000) | USD 41,182.00M (41,182,000,000) | USD 22,101.00M (22,101,000,000) | 10-K 2024-02-21 |
"""
            (xbrl_dir / "NVDA_10y_xbrl.md").write_text(
                xbrl_tpl.format(corpus="sec-10y-core", ticker="NVDA", zh="英伟达", en="NVIDIA Corporation"),
                encoding="utf-8",
            )
            (xbrl_dir / "MSFT_10y_xbrl.md").write_text(
                xbrl_tpl.format(corpus="sec-10y-core", ticker="MSFT", zh="微软", en="Microsoft Corporation"),
                encoding="utf-8",
            )
            (ipo_dir / "CRWV" / "CRWV_xbrl_summary.md").write_text(
                xbrl_tpl.format(corpus="sec-ipo-prospectus-pack", ticker="CRWV", zh="CoreWeave", en="CoreWeave, Inc."),
                encoding="utf-8",
            )
            (ipo_dir / "ARM" / "ARM_xbrl_summary.md").write_text(
                xbrl_tpl.format(corpus="sec-ipo-prospectus-pack", ticker="ARM", zh="Arm", en="Arm Holdings plc"),
                encoding="utf-8",
            )

            filing_tpl = """---
corpus: {corpus}
license: SEC-Public-Filing
ticker: {ticker}
company_zh: {zh}
company_en: {en}
form: {form}
fiscal_year: 2025
---

| Year Ended |  |  |
| --- | --- | --- |
| 2025 | 2024 |  |
| ($ in millions) |  |  |
| Revenue | $215,938 | $130,497 |
| Operating income | $130,387 | $81,453 |
| Net income | $120,067 | $72,880 |
"""
            (filings_dir / "NVDA" / "2025_10-K.md").write_text(
                filing_tpl.format(corpus="sec-10y-core", ticker="NVDA", zh="英伟达", en="NVIDIA Corporation", form="10-K"),
                encoding="utf-8",
            )
            (filings_dir / "MSFT" / "2025_10-K.md").write_text(
                filing_tpl.format(corpus="sec-10y-core", ticker="MSFT", zh="微软", en="Microsoft Corporation", form="10-K"),
                encoding="utf-8",
            )
            (ipo_dir / "CRWV" / "2025_424B4.md").write_text(
                filing_tpl.format(corpus="sec-ipo-prospectus-pack", ticker="CRWV", zh="CoreWeave", en="CoreWeave, Inc.", form="424B4"),
                encoding="utf-8",
            )
            (ipo_dir / "ARM" / "2023_424B4.md").write_text(
                filing_tpl.format(corpus="sec-ipo-prospectus-pack", ticker="ARM", zh="Arm", en="Arm Holdings plc", form="424B4"),
                encoding="utf-8",
            )

            manifest = cn_reader_pack.build_sec_benchmark_pack(
                sec_10y_dir=root / "sec-10y-core",
                sec_ipo_dir=ipo_dir,
                out_dir=out_dir,
                max_dev=40,
                max_eval=20,
            )
            self.assertEqual(manifest["license"], "SEC-Public-Filing")
            dev_cases = json.loads((out_dir / "dev_sec_qa_benchmark.json").read_text(encoding="utf-8"))
            self.assertGreater(len(dev_cases), 0)
            for rec in dev_cases:
                self.assertEqual(rec["license"], "SEC-Public-Filing")
                self.assertNotIn(rec["ticker"], cn_reader_pack.DEFAULT_HELDOUT_TICKERS)
                self.assertNotIn("program", rec)
                self.assertNotIn("messages", rec)
            eval_cases = json.loads((out_dir / "eval_sec_ipo_heldout.json").read_text(encoding="utf-8"))
            self.assertGreater(len(eval_cases), 0)
            for ec in eval_cases:
                self.assertIn(ec["ticker"], cn_reader_pack.DEFAULT_HELDOUT_TICKERS)
                self.assertNotIn("program", ec)


if __name__ == "__main__":
    unittest.main()
