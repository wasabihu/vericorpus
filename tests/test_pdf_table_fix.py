"""防止 PDF 表格因单元格换行破坏小数点与会计负数括号、双表混排行序倒置，以及 HKEX CMap '尸->月' 误伤法医/日常词汇。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_HAS_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


class PdfTableFixTests(unittest.TestCase):
    def test_cell_line_merge_joins_cjk_decimals_and_accounting_negatives_cleanly(self):
        from vericorpus import pdf_table_fix

        self.assertEqual(pdf_table_fix.normalize_cell("39.\n9 亿美元"), "39.9 亿美元")
        self.assertEqual(pdf_table_fix.normalize_cell("39.9 亿美\n元"), "39.9 亿美元")
        self.assertEqual(pdf_table_fix.normalize_cell("(\n1,234.5)"), "(1,234.5)")
        self.assertEqual(pdf_table_fix.normalize_cell("$(\n4,120)"), "$(4,120)")
        self.assertEqual(pdf_table_fix.normalize_cell("(\n1,234.5\n)"), "(1,234.5)")
        self.assertEqual(pdf_table_fix.normalize_cell("1,234,\n567"), "1,234,567")
        self.assertEqual(pdf_table_fix.normalize_cell("2025年初\n规模"), "2025年初规模")
        self.assertEqual(
            pdf_table_fix.normalize_cell("+225.5% ｜ 目前绝对主力，机构资金在链上安全吃利\n息"),
            "+225.5% ｜ 目前绝对主力，机构资金在链上安全吃利息",
        )
        self.assertEqual(pdf_table_fix.normalize_cell("BlackRock\nBUIDL"), "BlackRock BUIDL")

    def test_cmap_repair_fixes_hkex_shi_to_yue_without_collateral_damage(self):
        from vericorpus import pdf_table_fix

        raw = "截至二零二六年六尸三十日止三個尸及六個尸，合併尸活躍賬戶數為1,439百萬。另有殭尸肉与尸位素餐。"
        fixed, count = pdf_table_fix.repair_hkex_cmap(raw)
        self.assertEqual(count, 4)
        self.assertIn("六月三十日", fixed)
        self.assertIn("三個月及六個月", fixed)
        self.assertIn("合併月活躍賬戶數", fixed)
        self.assertIn("殭尸肉", fixed)
        self.assertIn("尸位素餐", fixed)

        # 严格负向对照：法医/刑侦/临床病理词汇绝不可被误改为“月”
        forensic = "本尸检报告与一尸两命及陈尸日久，现场发现尸体与尸骨未寒。"
        res = pdf_table_fix.repair_hkex_cmap(forensic)
        self.assertEqual(res, forensic)
        repaired_str, n_fixes = res
        self.assertEqual(repaired_str, forensic)
        self.assertEqual(n_fixes, 0)
        self.assertEqual(pdf_table_fix.repair_hkex_cmap("本尸检报告"), "本尸检报告")

    @unittest.skipUnless(_HAS_PYMUPDF, "Optional PyMuPDF [pdf] extra not installed")
    def test_synthetic_pdf_two_tables_row_order_decimals_and_cmap(self):
        import pymupdf
        from vericorpus import pdf_table_fix

        with tempfile.TemporaryDirectory() as td:
            pdf_path = Path(td) / "synthetic_financial_tables.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=595, height=842)

            # Draw Table 1 (top: y=80..200, 3 rows x 3 cols)
            t1_x = [50, 220, 380, 540]
            t1_y = [80, 115, 155, 195]
            for x in t1_x:
                page.draw_line((x, t1_y[0]), (x, t1_y[-1]))
            for y in t1_y:
                page.draw_line((t1_x[0], y), (t1_x[-1], y))

            page.insert_text((60, 102), "Metric", fontsize=10)
            page.insert_text((230, 102), "2026Q3", fontsize=10)
            page.insert_text((390, 102), "2025Q3", fontsize=10)

            # Wrapped decimal "39.\n9" and accounting negative "(\n125.4)"
            page.insert_text((60, 132), "Revenue", fontsize=10)
            page.insert_text((230, 130), "39.", fontsize=10)
            page.insert_text((230, 144), "9", fontsize=10)
            page.insert_text((390, 132), "28.4", fontsize=10)

            page.insert_text((60, 172), "Net Loss", fontsize=10)
            page.insert_text((230, 168), "(", fontsize=10)
            page.insert_text((230, 182), "125.4)", fontsize=10)
            page.insert_text((390, 172), "(88.0)", fontsize=10)

            # Draw Table 2 (bottom: y=260..350, 2 rows x 2 cols) to verify non-interleaving order
            t2_x = [50, 300, 540]
            t2_y = [260, 300, 340]
            for x in t2_x:
                page.draw_line((x, t2_y[0]), (x, t2_y[-1]))
            for y in t2_y:
                page.draw_line((t2_x[0], y), (t2_x[-1], y))

            page.insert_text((60, 285), "Segment", fontsize=10)
            page.insert_text((310, 285), "Margin", fontsize=10)
            page.insert_text((60, 325), "Cloud", fontsize=10)
            page.insert_text((310, 325), "+28.5%", fontsize=10)

            doc.save(str(pdf_path))
            doc.close()

            res = pdf_table_fix.extract_pdf_to_markdown(pdf_path)
            self.assertEqual(res["pages_total"], 1)
            self.assertGreaterEqual(res["tables_total"], 2)
            md = res["markdown"]
            self.assertIn("39.9", md)
            self.assertNotIn("39. 9", md)
            self.assertIn("(125.4)", md)
            self.assertNotIn("( 125.4)", md)
            self.assertLess(md.index("Net Loss"), md.index("Segment"))


if __name__ == "__main__":
    unittest.main()
