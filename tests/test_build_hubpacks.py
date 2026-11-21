"""防止 .hubpack 打包脚本路径穿越、放行缺失/受限逐文件 frontmatter 许可、或遗漏外置分离签名(.sig)与 SHA256SUMS。"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for p in (SRC_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class BuildHubpacksTests(unittest.TestCase):
    def test_build_hubpack_rejects_traversal_bad_frontmatter_and_recipe_zero_side_effects(self):
        import build_hubpacks

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out_dir = tmp / "hubpacks"
            fake_raw = tmp / "raw"

            # 1. Path traversal / CLI flag slug must fail closed
            for bad_slug in ("../outside", "-flag", "bad_underscore"):
                with self.assertRaises(ValueError):
                    build_hubpacks.build_hubpack(
                        bad_slug,
                        corpora_dir=ROOT_DIR / "corpora",
                        raw_root=fake_raw,
                        out_root=out_dir,
                    )

            # 2. Must refuse recipe corpora
            with self.assertRaises(ValueError):
                build_hubpacks.build_hubpack(
                    "cn-hkus-disclosures",
                    corpora_dir=ROOT_DIR / "corpora",
                    raw_root=fake_raw,
                    out_root=out_dir,
                )

            # 3. Must refuse pack corpus if any .md file has restricted or missing frontmatter license (zero bytes emitted!)
            bad_src = fake_raw / "cn-github-stars"
            bad_src.mkdir(parents=True)
            (bad_src / "poisoned.md").write_text(
                "---\nlicense: HKEX-Public-Disclosure\n---\n\n# Restricted\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                build_hubpacks.build_hubpack(
                    "cn-github-stars",
                    corpora_dir=ROOT_DIR / "corpora",
                    raw_root=fake_raw,
                    out_root=out_dir,
                )
            self.assertFalse(out_dir.exists() and any(out_dir.iterdir()), "校验失败时严禁向输出目录遗留任何打包产物")

    def test_build_hubpack_emits_archive_outer_sha256sums_and_detached_sig(self):
        import build_hubpacks

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out_dir = tmp / "hubpacks"
            key_prefix = tmp / "ephemeral_key"
            fake_raw = tmp / "raw"
            pack_src = fake_raw / "cn-github-stars"
            pack_src.mkdir(parents=True)
            sample_md = pack_src / "sample.md"
            sample_md.write_text("---\nlicense: Apache-2.0\n---\n\n# Sample Pack Doc\n", encoding="utf-8")

            xerj_bin = shutil.which("xerj")
            if xerj_bin:
                subprocess.run([xerj_bin, "corpus", "keygen", "--out", str(key_prefix)], check=True, capture_output=True)
                sign_key = Path(f"{key_prefix}.key")
            else:
                sign_key = None

            summary = build_hubpacks.build_hubpack(
                "cn-github-stars",
                corpora_dir=ROOT_DIR / "corpora",
                raw_root=fake_raw,
                out_root=out_dir,
                sign_key=sign_key,
            )
            pack_dir = Path(summary["pack_dir"])
            self.assertTrue((pack_dir / "pack_manifest.json").is_file())
            self.assertTrue((pack_dir / "docs" / "sample.md").is_file())
            sums_path = pack_dir / "SHA256SUMS"
            self.assertTrue(sums_path.is_file())

            # Verify archive + external <slug>-SHA256SUMS alongside archive
            archive_path = out_dir / "cn-github-stars-pack.zip"
            outer_sums = out_dir / "cn-github-stars-SHA256SUMS"
            self.assertTrue(archive_path.is_file(), "缺少归档包 <slug>-pack.zip")
            self.assertTrue(outer_sums.is_file(), "缺少归档外置 <slug>-SHA256SUMS")
            expected_zip_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            self.assertIn(f"{expected_zip_hash}  cn-github-stars-pack.zip", outer_sums.read_text(encoding="utf-8"))

            sums_text = sums_path.read_text(encoding="utf-8")
            expected_hash = hashlib.sha256(sample_md.read_bytes()).hexdigest()
            self.assertIn(f"{expected_hash}  docs/sample.md", sums_text)
            manifest_data = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["slug"], "cn-github-stars")
            self.assertEqual(manifest_data["license"], "Apache-2.0")

            if xerj_bin:
                sig_path = pack_dir / "SHA256SUMS.sig"
                detached_sig = out_dir / "cn-github-stars-SHA256SUMS.sig"
                self.assertTrue(sig_path.is_file())
                self.assertEqual(len(sig_path.read_bytes()), 64)
                self.assertTrue(detached_sig.is_file(), "缺少归档外置分离签名 <slug>-SHA256SUMS.sig")
                self.assertEqual(len(detached_sig.read_bytes()), 64)


if __name__ == "__main__":
    unittest.main()
