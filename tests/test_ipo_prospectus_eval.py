"""防止招股书双轨版权混淆、招股书与问询回复核心节漏进表格精排、越疆对照统计失真以及 12 家硬科技赛道标的缺漏。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class IpoProspectusEvalTests(unittest.TestCase):
    def test_prospectus_specs_cover_12_unique_hardtech_targets_with_wiki_tracks(self):
        from vericorpus import ipo_prospectus

        specs = ipo_prospectus.PROSPECTUS_SPECS
        self.assertEqual(len(specs), 12)
        ids = [s["id"] for s in specs]
        self.assertEqual(len(set(ids)), 12)

        sec_pack = [s for s in specs if s["track"] == "sec_pack"]
        hkex_recipe = [s for s in specs if s["track"] == "hkex_recipe"]
        cninfo_recipe = [s for s in specs if s["track"] == "cninfo_recipe"]
        self.assertEqual(len(sec_pack), 5)
        self.assertEqual(len(hkex_recipe), 4)
        self.assertEqual(len(cninfo_recipe), 3)

        for item in specs:
            self.assertTrue(str(item.get("wiki_track") or "").strip(), f"缺少 wiki_track: {item}")

        by_id = {s["id"]: s for s in specs}
        for req in ("ALAB", "CRDO", "CRWV", "ARM", "SPCX", "02533", "09660", "ZHIPU", "02432", "688041", "688498", "688295"):
            self.assertIn(req, by_id)

    def test_is_prospectus_key_page_covers_simplified_traditional_english_and_inquiry(self):
        from vericorpus import ipo_prospectus

        for sample in (
            "第二节 概览 本次发行概况及主要财务数据",
            "第五节 财务会计信息与管理层分析 合并利润表",
            "关于深圳证券交易所审核问询函的回复",
            "招股章程 概要 業務概要 行業概覽",
            "風險因素 與我們業務有關的風險",
            "財務資料 綜合損益表",
            "PROSPECTUS SUMMARY RISK FACTORS SELECTED FINANCIAL DATA",
            "Management's Discussion and Analysis of Financial Information",
        ):
            self.assertTrue(ipo_prospectus.is_prospectus_key_page(35, sample), f"应命中招股书核心页: {sample}")

        self.assertFalse(ipo_prospectus.is_prospectus_key_page(180, "附录五 备查文件目录及备查地点说明"))

    def test_compare_dobot_txt_vs_rebuilt_reports_table_gain_and_anchors(self):
        from vericorpus import ipo_prospectus

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt_dir = root / "txt"
            md_dir = root / "md"
            txt_dir.mkdir()
            md_dir.mkdir()

            (txt_dir / "01-聆讯后资料集-概要.txt").write_text("概要\n2023年 收入 286,749\n", encoding="utf-8")
            (md_dir / "01-聆讯后资料集-概要.md").write_text(
                "---\ncorpus: cn-hk-ipo-prospectus-recipe\n---\n\n"
                "<!-- page: 1/12 -->\n## 第 1 页\n\n"
                "| 指标 | 2023年 |\n| --- | --- |\n| 收入 | 286,749 |\n",
                encoding="utf-8",
            )
            stats = ipo_prospectus.compare_dobot_txt_vs_rebuilt(txt_dir, md_dir)
            self.assertEqual(stats["txt_files"], 1)
            self.assertEqual(stats["md_files"], 1)
            self.assertEqual(stats["txt_pipe_rows"], 0)
            self.assertGreaterEqual(stats["md_pipe_rows"], 3)
            self.assertEqual(stats["md_page_anchors"], 1)

    def test_ipo_manifests_enforce_dual_track_license_compliance(self):
        from vericorpus import compliance

        bad_sec = {
            "slug": "sec-ipo-prospectus-pack",
            "title": "SEC招股书",
            "mode": "pack",
            "license": "HKEX-Public-Disclosure",
            "source_url": "https://www.sec.gov/",
            "sources": [{"name": "a", "url": "https://www.sec.gov/"}],
        }
        with self.assertRaises(compliance.ComplianceError):
            compliance.validate_manifest(bad_sec)

        good_sec = dict(bad_sec, license="SEC-Public-Filing")
        compliance.validate_manifest(good_sec)

        good_recipe = {
            "slug": "cn-hk-ipo-prospectus-recipe",
            "title": "港股18C及科创板招股书与问询回复",
            "mode": "recipe",
            "license": "Multi-Exchange-Public-Disclosure",
            "source_url": "https://www1.hkexnews.hk/",
            "sources": [{"name": "hk", "url": "https://www1.hkexnews.hk/", "license": "HKEX-Public-Disclosure"}],
        }
        compliance.validate_manifest(good_recipe)


if __name__ == "__main__":
    unittest.main()
