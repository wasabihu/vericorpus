"""防止 VeriCorpus 公开仓残留旧版品牌/闭源模型代号、破坏 Apache-2.0 标准许可证、耦合 AGPL-3.0 必选依赖、缺省无邮箱 SEC 请求头或混入不可复现私有评测样本。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class VeriCorpusRebrandTests(unittest.TestCase):
    def test_standard_apache2_license_and_notice_files(self):
        lic_path = ROOT_DIR / "LICENSE"
        notice_path = ROOT_DIR / "NOTICE"
        self.assertTrue(lic_path.is_file(), "缺少根目录 LICENSE")
        self.assertTrue(notice_path.is_file(), "缺少根目录 NOTICE")

        lic_lines = lic_path.read_text(encoding="utf-8").splitlines()
        lic_text = lic_path.read_text(encoding="utf-8")
        self.assertEqual(len(lic_lines), 202, f"Apache-2.0 官方标准文本应为 202 行，实际: {len(lic_lines)}")
        self.assertIn("Apache License", lic_text)
        self.assertIn("Version 2.0, January 2004", lic_text)
        self.assertIn("APPENDIX: How to apply the Apache License to your work.", lic_text)
        self.assertNotIn("Xerj " + "CN Hub", lic_text)
        self.assertNotIn("install " + "patent", lic_text)
        self.assertNotIn("indirect, " + "indirect", lic_text)

        notice_text = notice_path.read_text(encoding="utf-8")
        self.assertIn("VeriCorpus", notice_text)
        self.assertIn("Copyright 2026 wasabihu", notice_text)
        self.assertIn("Not affiliated with, sponsored by, or endorsed by The XERJ Authors", notice_text)

    def test_pyproject_zero_core_dependencies_and_optional_pdf_extra(self):
        pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
        proj = pyproject["project"]
        self.assertEqual(proj["name"], "vericorpus")
        self.assertEqual(proj["license"], {"file": "LICENSE"})
        self.assertEqual(proj["dependencies"], [], "核心包必须保持 100% 标准库零依赖，不得硬绑 AGPL 库")
        opt = proj.get("optional-dependencies") or {}
        self.assertIn("pdf", opt)
        self.assertTrue(any(dep.startswith("pymupdf") for dep in opt["pdf"]))
        self.assertFalse((SRC_DIR / "xerj_cn").exists(), "公开仓不应保留旧版 src/xerj_cn 目录")

    def test_stdlib_lazy_import_works_when_pymupdf_is_blocked(self):
        probe = (
            "import sys\n"
            "sys.modules['pymupdf'] = None\n"
            "import vericorpus\n"
            "from vericorpus import compliance, query_cn, pdf_table_fix\n"
            "assert vericorpus.__version__ == '0.1.0'\n"
            "assert vericorpus.audit_corpora_dir is compliance.audit_corpora_dir\n"
            "assert vericorpus.normalize_cell is pdf_table_fix.normalize_cell\n"
            "assert vericorpus.search_index is query_cn.search_index\n"
            "assert pdf_table_fix.normalize_cell('39.\\n9 亿美元') == '39.9 亿美元'\n"
            "assert pdf_table_fix.repair_hkex_cmap('本尸检报告') == '本尸检报告'\n"
            "try:\n"
            "    pdf_table_fix.extract_pdf_to_markdown('dummy.pdf')\n"
            "except ImportError as exc:\n"
            "    assert \"vericorpus[pdf]\" in str(exc)\n"
            "else:\n"
            "    raise AssertionError('Expected helpful ImportError when pymupdf is absent')\n"
        )
        env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=f"无 pymupdf 纯净导入失败:\n{proc.stderr}\n{proc.stdout}")

    def test_sec_user_agent_requires_email_at_sign_and_is_not_locked_at_import(self):
        from vericorpus import fetchers, financial_10y

        self.assertFalse(hasattr(financial_10y, "SEC_USER_AGENT"), "不应在 import 期静态锁定 SEC_USER_AGENT")
        self.assertFalse(hasattr(fetchers, "USER_AGENT"), "不应在 import 期静态锁定 USER_AGENT")

        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": "AcmeResearch sec-ops@example.org"}, clear=False):
            self.assertEqual(financial_10y.get_sec_user_agent(), "AcmeResearch sec-ops@example.org")
            self.assertEqual(
                fetchers.get_user_agent("https://data.sec.gov/submissions/CIK0001045810.json"),
                "AcmeResearch sec-ops@example.org",
            )

        for bad_ua in ("", "VeriCorpus/0.1 (+https://github.com/wasabihu/vericorpus)", "NoDomain@", "bot@fake." + "local"):
            with mock.patch.dict(os.environ, {"SEC_USER_AGENT": bad_ua}, clear=False):
                if not bad_ua:
                    os.environ.pop("SEC_USER_AGENT", None)
                with self.assertRaises(RuntimeError, msg=f"SEC 请求应拦截缺失有效邮箱的 UA: {bad_ua!r}"):
                    financial_10y.get_sec_user_agent()
                with self.assertRaises(RuntimeError, msg=f"SEC URL 应拦截无效 UA: {bad_ua!r}"):
                    fetchers.get_user_agent("https://www.sec.gov/files/company_tickers.json")

        # 非 SEC 站点无需强制 SEC_USER_AGENT
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            os.environ.pop("VERICORPUS_USER_AGENT", None)
            self.assertIn("VeriCorpus", fetchers.get_user_agent("https://api.openalex.org/works"))

    def test_readme_charter_links_ci_workflow_and_publicly_reproducible_evals(self):
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "> **Trademark & Non-Affiliation Notice**: VeriCorpus is an independent community project built for XERJ and Elasticsearch-compatible engines. It is not affiliated with, sponsored by, or endorsed by The XERJ Authors.",
            readme,
        )
        self.assertIn("Not Legal, Investment, or Medical Advice", readme)
        self.assertIn("docs/ENGINEERING_PHILOSOPHY.md", readme)
        self.assertIn("AGENTS.md", readme)
        self.assertIn("vericorpus[pdf]", readme)
        self.assertIn("AGPL-3.0", readme)

        self.assertTrue((ROOT_DIR / "AGENTS.md").is_file())
        self.assertTrue((ROOT_DIR / ".github" / "AI_CONTRIBUTIONS.md").is_file())
        self.assertTrue((ROOT_DIR / "docs" / "ENGINEERING_PHILOSOPHY.md").is_file())
        self.assertTrue((ROOT_DIR / ".github" / "workflows" / "ci.yml").is_file())
        self.assertFalse((ROOT_DIR / "docs" / ("OPEN_CORE_" + "FUNNEL_GUIDE.md")).exists())
        self.assertFalse((ROOT_DIR / "docs" / ("XERJ_PARTNERSHIP_" + "AND_PR_KIT.md")).exists())

        ci_txt = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", ci_txt)
        self.assertIn("timeout-minutes: 10", ci_txt)
        self.assertNotIn("pip install", ci_txt)
        self.assertRegex(ci_txt, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(ci_txt, r"actions/setup-python@[0-9a-f]{40}")

        # 确认公开评测集与清单已彻底移除不可复现私有 RWA 样本与 All Rights Reserved 周刊绑定
        for rel in (
            "corpora/cn-hkus-disclosures/manifest.json",
            "evals/cn_benchmark_24.json",
            "evals/primary_market_and_weekly_eval_32.json",
        ):
            blob = (ROOT_DIR / rel).read_text(encoding="utf-8")
            self.assertNotIn("Local-Private-Sample", blob)
            self.assertNotIn("rwa_energy_report_sample", blob)
            self.assertNotIn("全球RWA市场趋势", blob)
            self.assertNotIn("wklocal", blob)
            self.assertNotIn("ruanyf", blob)

        b24 = json.loads((ROOT_DIR / "evals" / "cn_benchmark_24.json").read_text(encoding="utf-8"))
        b32 = json.loads((ROOT_DIR / "evals" / "primary_market_and_weekly_eval_32.json").read_text(encoding="utf-8"))
        self.assertEqual(len(b24), 24)
        self.assertEqual(len(b32), 32)


if __name__ == "__main__":
    unittest.main()
