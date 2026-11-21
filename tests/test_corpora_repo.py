"""防止后续新增或修改仓库内 corpora/*/manifest.json 时绕过合规审计或丢失字段。"""
import json
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class CorporaRepoAuditTests(unittest.TestCase):
    def test_all_committed_manifests_pass_compliance_audit(self):
        from vericorpus import compliance

        audited = compliance.audit_corpora_dir(ROOT_DIR / "corpora")
        slugs = {item["slug"]: item for item in audited}
        for req in (
            "cn-law-core",
            "cn-capital-market-law",
            "cn-github-stars",
            "cn-science-ccby",
            "cn-hkus-disclosures",
            "sec-10y-core",
            "cn-hk-financial-10y",
            "sec-ipo-prospectus-pack",
            "cn-hk-ipo-prospectus-recipe",
        ):
            self.assertIn(req, slugs)
        self.assertEqual(slugs["cn-hkus-disclosures"]["mode"], "recipe")
        self.assertEqual(slugs["cn-hk-financial-10y"]["mode"], "recipe")
        self.assertEqual(slugs["cn-hk-ipo-prospectus-recipe"]["mode"], "recipe")
        self.assertEqual(slugs["cn-law-core"]["mode"], "pack")
        self.assertEqual(slugs["cn-capital-market-law"]["mode"], "pack")
        self.assertEqual(slugs["cn-capital-market-law"]["license"], "Public-Domain-CN-Law")
        cap_manifest = json.loads(
            Path(slugs["cn-capital-market-law"]["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(cap_manifest.get("sources", [])), 18)
        self.assertEqual(slugs["cn-github-stars"]["mode"], "pack")
        self.assertEqual(slugs["cn-science-ccby"]["mode"], "pack")
        self.assertEqual(slugs["sec-10y-core"]["mode"], "pack")
        self.assertEqual(slugs["sec-ipo-prospectus-pack"]["mode"], "pack")
        self.assertTrue((ROOT_DIR / "corpora" / "do-not-contact.json").is_file())
        self.assertTrue((ROOT_DIR / ".contributors").is_file())
        for item in audited:
            mf = json.loads(Path(item["manifest_path"]).read_text(encoding="utf-8"))
            self.assertIn("review", mf, f"{item['slug']} 缺少人工 review 审计块")
            expected_use = "adapt-with-attribution" if mf["mode"] == "pack" else "approach-only"
            self.assertEqual(mf["review"]["use"], expected_use)
            self.assertEqual(mf["review"]["by"], "wasabihu")


if __name__ == "__main__":
    unittest.main()
