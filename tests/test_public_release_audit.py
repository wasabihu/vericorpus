"""防止公开仓库发布前遗漏 Git 历史/对象泄漏、二进制/UTF-16 绕过、个人索引前缀、内部策略文档、闭源模型代号或 CC-BY-4.0 署名缺失。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for _p in (SRC_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _init_clean_git_repo(root: Path) -> None:
    """Create a minimal valid git repository with a compliant corpus and clean files."""
    (root / ".gitignore").write_text(
        ".venv/\ndata/\n.env*\n*.key\n*.pem\n*.sig\n*.safetensors\n*.hubpack\nhub.db*\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Clean Sample Repo\n\nApache-2.0 sample docs.\n", encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text("def ok() -> bool:\n    return True\n", encoding="utf-8")
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "GUIDE.md").write_text("# Guide\n\nUse relative paths only.\n", encoding="utf-8")

    corpus_dir = root / "corpora" / "demo-pack"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "slug": "demo-pack",
        "title": "Demo Compliant Pack",
        "mode": "pack",
        "license": "Apache-2.0",
        "source_url": "https://github.com/example/demo-pack",
        "sources": [{"name": "readme.md", "url": "https://example.com/readme.md", "license": "Apache-2.0"}],
    }
    (corpus_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    ignored_data = root / "data" / "raw"
    ignored_data.mkdir(parents=True, exist_ok=True)
    (ignored_data / "local.md").write_text("local only", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "add", "."], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class PublicReleaseAuditTests(unittest.TestCase):
    def test_self_check_and_home_paths_macos_and_linux(self):
        import audit_public_release

        audit_public_release._self_check()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            mac_leak = "/" + "Users/someone/private/data.md"
            linux_leak = "/" + "home/alice/secrets/config.json"
            (root / "docs" / "GUIDE.md").write_text(f"# Guide\n\n`{mac_leak}` and `{linux_leak}`\n", encoding="utf-8")
            result = audit_public_release.audit_repo(root)
            self.assertFalse(result["ok"])
            cats = [v["category"] for v in result["violations"]]
            self.assertGreaterEqual(cats.count("hardcoded_home_path"), 2)

    def test_catches_binary_null_byte_utf16_and_oversized_files(self):
        import audit_public_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            fake_sk = "sk" + "-proj-FakeToken1234567890abcdef"
            # UTF-16LE contains null bytes — must NOT be silently skipped!
            (root / "utf16_secret.txt").write_bytes(f"TOKEN={fake_sk}".encode("utf-16-le"))
            (root / "big_blob.txt").write_bytes(b"a" * (5 * 1024 * 1024 + 64))
            result = audit_public_release.audit_repo(root)
            self.assertFalse(result["ok"])
            paths = {v["path"] for v in result["violations"]}
            self.assertIn("utf16_secret.txt", paths)
            self.assertIn("big_blob.txt", paths)

    def test_catches_personal_indices_fine_grained_pat_strategy_docs_and_codenames(self):
        import audit_public_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            pat = "github_pat_" + "11ABCDEFG0123456789abcdef_XYZ"
            jiali_idx = "jia" + "li-notes-2026"
            bak_idx = "ba" + "k-archive-01"
            old_brand = "Xerj " + "CN Hub"
            codename = "CN-Reader-" + "1.7B-v3"
            (root / "src" / "app.py").write_text(
                f'PAT = "{pat}"\nI1 = "{jiali_idx}"\nI2 = "{bak_idx}"\nB = "{old_brand}"\nM = "{codename}"\n',
                encoding="utf-8",
            )
            (root / "docs" / ("OPEN_CORE_" + "FUNNEL_GUIDE.md")).write_text("# Funnel\n", encoding="utf-8")
            result = audit_public_release.audit_repo(root)
            self.assertFalse(result["ok"])
            details = "\n".join(v["detail"] for v in result["violations"])
            self.assertIn("github_pat", details)
            self.assertIn("personal_index_prefix", details)
            self.assertIn("legacy_brand_leak", details)
            self.assertIn("closed_source_model_codename", details)
            self.assertIn("internal_strategy_doc", details)

    def test_catches_git_log_identity_coauthor_and_deleted_historical_blob_leaks(self):
        import audit_public_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            # Commit 1: leak secret in a file and personal email + Co-Authored-By trailer
            leaked_tok = "sk" + "-ant-HistoricalSecret9876543210"
            (root / "temp_secret.py").write_text(f'SECRET = "{leaked_tok}"\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            bad_email = "wasabi.net@" + "gmail.com"
            coauthor = "Co-Authored-" + "By: Helper Bot <bot@example.com>"
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Wasabi",
                    "-c",
                    f"user.email={bad_email}",
                    "commit",
                    "-m",
                    f"init\n\n{coauthor}",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            # Commit 2: delete temp_secret.py from working tree with clean email — historical blob & log must STILL be caught!
            (root / "temp_secret.py").unlink()
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=wasabihu",
                    "-c",
                    "user.email=973168+wasabihu@users.noreply.github.com",
                    "commit",
                    "-m",
                    "remove secret from worktree",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            result = audit_public_release.audit_repo(root)
            self.assertFalse(result["ok"])
            cats = {v["category"] for v in result["violations"]}
            self.assertIn("git_history_leak", cats)
            details = "\n".join(v["detail"] for v in result["violations"])
            self.assertIn("personal_gmail_leak", details)
            self.assertIn("co_authored_by_trailer", details)
            self.assertIn("sk_token", details)

    def test_catches_eval_json_missing_ccby_attribution(self):
        import audit_public_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            evals_dir = root / "evals"
            evals_dir.mkdir(parents=True, exist_ok=True)
            bad_eval = [
                {
                    "id": "bad_ccby_1",
                    "question": "What is ORR?",
                    "oracle_document": "---\nlicense: CC-BY-4.0\n---\n\n# Study\n\n- **Authors**: See original publication\n- **License**: CC-BY-4.0\n",
                    "expected": {"status": "ABSENT", "value": None, "evidence": []},
                }
            ]
            (evals_dir / "sample_eval.json").write_text(json.dumps(bad_eval), encoding="utf-8")
            result = audit_public_release.audit_repo(root)
            self.assertFalse(result["ok"])
            cats = {v["category"] for v in result["violations"]}
            self.assertIn("eval_ccby_attribution", cats)

    def test_clean_synthetic_repo_with_clean_commit_passes(self):
        import audit_public_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_clean_git_repo(root)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=wasabihu",
                    "-c",
                    "user.email=973168+wasabihu@users.noreply.github.com",
                    "commit",
                    "-m",
                    "feat: clean initial commit",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            result = audit_public_release.audit_repo(root)
            self.assertTrue(result["ok"], msg=result)
            self.assertEqual(result["violations"], [])
            rc = audit_public_release.main(["--root", str(root)])
            self.assertEqual(rc, 0)

    def test_real_repo_passes_public_release_audit(self):
        import audit_public_release

        is_local_dev_parent = (ROOT_DIR / "builds" / "public_staging" / "vericorpus").is_dir()
        result = audit_public_release.audit_repo(ROOT_DIR, check_git_history=not is_local_dev_parent)
        self.assertTrue(result["ok"], msg=json.dumps(result["violations"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    unittest.main()
