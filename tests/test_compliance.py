"""防止无许可证、非商用(NC)、路径穿越(pathgate)、非 HTTPS 协议(file:// SSRF)或短 SHA 清单混入语料库。"""
import tempfile
import unittest
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class ComplianceTests(unittest.TestCase):
    def test_allowlisted_pack_manifests_pass_validation(self):
        from vericorpus import compliance

        valid_sha = "8cb05f0dfd02c442b28e3fa1299014246aa7d3da"
        for lic, src in (
            ("Public-Domain-CN-Law", "https://github.com/LawRefBook/Laws"),
            ("Apache-2.0", "https://github.com/infiniflow/ragflow"),
            ("CC-BY-4.0", "https://api.openalex.org/works"),
            ("MIT", "https://github.com/example/open-repo"),
            ("SEC-Public-Filing", "https://www.sec.gov/Archives/edgar/data/1577552/000157755226000010"),
        ):
            manifest = {
                "slug": "valid-pack",
                "title": "测试合规语料",
                "mode": "pack",
                "license": lic,
                "source_url": src,
                "sources": [{"name": "docs/sample.md", "url": src, "commit": valid_sha}],
            }
            compliance.validate_manifest(manifest)

    def test_restricted_or_missing_licenses_are_rejected_for_pack_and_recipe_subsources(self):
        from vericorpus import compliance

        for bad_lic in ("NOASSERTION", "CC-BY-NC-SA-4.0", "GPL-3.0", "AGPL-3.0", "All-Rights-Reserved", ""):
            manifest = {
                "slug": "bad-pack",
                "title": "非法分发测试",
                "mode": "pack",
                "license": bad_lic,
                "source_url": "https://example.com/repo",
                "sources": [{"name": "bad.md", "url": "https://example.com/repo"}],
            }
            with self.assertRaises(compliance.ComplianceError, msg=f"应拦截 {bad_lic!r}"):
                compliance.validate_manifest(manifest)

        # recipe 模式同样必须拒绝 PROPRIETARY / AGPL-3.0 / CC-BY-ND-4.0 子来源
        for bad_sub in ("PROPRIETARY", "AGPL-3.0", "CC-BY-ND-4.0", "Local-Private-Sample"):
            bad_recipe_sub = {
                "slug": "bad-recipe-sub",
                "title": "混入未授权子源配方",
                "mode": "recipe",
                "license": "HKEX-Public-Disclosure",
                "source_url": "https://www1.hkexnews.hk/",
                "sources": [{"name": "x.pdf", "url": "https://www1.hkexnews.hk/a.pdf", "license": bad_sub}],
            }
            with self.assertRaises(compliance.ComplianceError, msg=f"recipe 应拦截子源许可 {bad_sub!r}"):
                compliance.validate_manifest(bad_recipe_sub)

    def test_hkex_disclosure_requires_recipe_mode_and_forbids_pack(self):
        from vericorpus import compliance

        bad_hkex = {
            "slug": "hkex-pack",
            "title": "港交所公开披露",
            "mode": "pack",
            "license": "HKEX-Public-Disclosure",
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/001.pdf",
            "sources": [{"name": "hkex.pdf", "url": "https://www1.hkexnews.hk/"}],
        }
        with self.assertRaises(compliance.ComplianceError):
            compliance.validate_manifest(bad_hkex)

        ok_recipe = dict(bad_hkex, mode="recipe")
        compliance.validate_manifest(ok_recipe)

    def test_pathgate_rejects_bad_slugs_traversal_flags_globs_and_symlinks(self):
        from vericorpus import compliance

        for bad_slug in ("", "../outside", "a/b", "-flag", "bad_underscore", "UPPER", "a:b", "a*b", "trailing-"):
            with self.assertRaises(compliance.ComplianceError, msg=f"应拒绝非法 slug: {bad_slug!r}"):
                compliance.validate_slug(bad_slug)
        self.assertEqual(compliance.validate_slug("cn-law-core"), "cn-law-core")

        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "sandbox"
            base.mkdir()
            outside = Path(td) / "secret.txt"
            outside.write_text("secret", encoding="utf-8")
            sym = base / "escape_link.md"
            sym.symlink_to(outside)

            for bad_rel in (
                "",
                "../../outside.md",
                "/etc/hosts",
                "sub\\win.md",
                "C:drive.md",
                "-git-flag.md",
                "dir/-flag.md",
                "magic:path.md",
                "glob/*.md",
                "escape_link.md",
            ):
                with self.assertRaises(compliance.ComplianceError, msg=f"应拒绝越界或危险路径: {bad_rel!r}"):
                    compliance.validate_rel_path(bad_rel, base)

            safe = compliance.validate_rel_path("sub/clean_doc.md", base)
            self.assertTrue(safe.resolve().is_relative_to(base.resolve()))

    def test_safe_urlopen_and_manifest_enforce_https_and_40hex_commit_sha(self):
        from vericorpus import compliance

        for bad_url in (
            "file:///etc/hosts",
            "http://www.cninfo.com.cn/new/data/szse_stock.json",
            "ftp://example.com/data.zip",
            "https://user:" + "pass@example.com/sec.md",
            "https://127.0.0.1/admin",
            "https://169.254.169.254/latest/meta-data/",
            "https://localhost:9200/_cat/indices",
        ):
            with self.assertRaises((compliance.ComplianceError, ValueError), msg=f"_safe_urlopen 应拦截 {bad_url!r}"):
                compliance._safe_urlopen(bad_url)

            bad_mf = {
                "slug": "ssrf-pack",
                "title": "SSRF Test",
                "mode": "pack",
                "license": "MIT",
                "source_url": "https://example.com/ok",
                "sources": [{"name": "out.md", "url": bad_url}],
            }
            with self.assertRaises(compliance.ComplianceError, msg=f"validate_manifest 应拦截 {bad_url!r}"):
                compliance.validate_manifest(bad_mf)

        short_sha_mf = {
            "slug": "short-sha",
            "title": "Short SHA Test",
            "mode": "pack",
            "license": "Apache-2.0",
            "source_url": "https://github.com/example/repo",
            "upstream_mirror": {"repo": "example/repo", "commit": "8cb05f0dfd02"},
            "sources": [{"name": "a.md", "url": "https://raw.githubusercontent.com/example/repo/main/a.md"}],
        }
        with self.assertRaises(compliance.ComplianceError):
            compliance.validate_manifest(short_sha_mf)


if __name__ == "__main__":
    unittest.main()
