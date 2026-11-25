"""防止公开的 30 天 SEC Form D Ed25519 签名示例包被篡改、破坏验签脚本或漏检单字节改动。"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PACK_DIR = ROOT_DIR / "examples" / "formd-sample-30d"


class FormDSamplePackTests(unittest.TestCase):
    def test_committed_formd_sample_pack_verifies_cleanly(self):
        verifier = PACK_DIR / "verify_pack.py"
        self.assertTrue(verifier.is_file(), "Missing examples/formd-sample-30d/verify_pack.py")
        proc = subprocess.run(
            [sys.executable, str(verifier), "--json"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, msg=f"verify_pack.py failed:\n{proc.stderr}\n{proc.stdout}")
        self.assertIn('"ok": true', proc.stdout)
        self.assertIn('"record_count": 3685', proc.stdout)
        self.assertIn('"date_range": "2026-10-06..2026-11-04"', proc.stdout)

    def test_formd_sample_pack_rejects_one_byte_tamper_on_data_manifest_and_sig(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # 1. 1-byte tamper in filings_30d.jsonl (without SHA256SUMS.txt)
            t1 = tmp / "tamper_data"
            shutil.copytree(PACK_DIR, t1)
            (t1 / "SHA256SUMS.txt").unlink()
            data = bytearray((t1 / "filings_30d.jsonl").read_bytes())
            data[10] ^= 0x01
            (t1 / "filings_30d.jsonl").write_bytes(bytes(data))
            p1 = subprocess.run([sys.executable, str(t1 / "verify_pack.py")], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(p1.returncode, 0, "Expected non-zero exit when filings_30d.jsonl is tampered")

            # 2. 1-byte tamper in manifest.json (without SHA256SUMS.txt)
            t2 = tmp / "tamper_manifest"
            shutil.copytree(PACK_DIR, t2)
            (t2 / "SHA256SUMS.txt").unlink()
            mdata = bytearray((t2 / "manifest.json").read_bytes())
            idx = mdata.index(b"3685")
            mdata[idx] = ord("4")
            (t2 / "manifest.json").write_bytes(bytes(mdata))
            p2 = subprocess.run([sys.executable, str(t2 / "verify_pack.py")], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(p2.returncode, 0, "Expected non-zero exit when manifest.json is tampered")

            # 3. 1-byte tamper in manifest.sig.b64 (without SHA256SUMS.txt)
            t3 = tmp / "tamper_sig"
            shutil.copytree(PACK_DIR, t3)
            (t3 / "SHA256SUMS.txt").unlink()
            raw_sig = bytearray(base64.b64decode((t3 / "manifest.sig.b64").read_text(encoding="ascii").strip()))
            raw_sig[0] ^= 0x01
            (t3 / "manifest.sig.b64").write_text(base64.b64encode(bytes(raw_sig)).decode("ascii") + "\n", encoding="ascii")
            p3 = subprocess.run([sys.executable, str(t3 / "verify_pack.py")], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(p3.returncode, 0, "Expected non-zero exit when manifest.sig.b64 is tampered")


if __name__ == "__main__":
    unittest.main()
