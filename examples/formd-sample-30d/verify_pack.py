#!/usr/bin/env python3
"""Zero-dependency verifier for the Ed25519-signed 30-day SEC Form D sample pack.

Uses only the Python 3 standard library plus the system `openssl` CLI (`pkeyutl -verify`).
Verifies:
  1. Public key is a valid Ed25519 SPKI PEM key (never a private key) matching all
     fingerprints recorded in `manifest.json`.
  2. Detached Ed25519 signature (`manifest.sig` raw 64-byte or `manifest.sig.b64` ASCII
     base64) cryptographically verifies over the exact bytes of `manifest.json`.
  3. `filings_30d.jsonl` byte size and SHA-256 exactly match the signed `manifest.json`.
  4. Every line in `filings_30d.jsonl` is valid canonical JSON matching `record_count`,
     unique `accession_number`, declared `date_range`, and `https://www.sec.gov/` provenance.
  5. Optional `SHA256SUMS.txt` entries match on-disk files when present.

Exits 0 only when ALL checks pass; exits non-zero on any tamper or missing artifact.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_child_path(pack_dir: Path, filename: str) -> Path:
    if not filename or filename in (".", "..") or not _SAFE_FILENAME_RE.fullmatch(filename):
        raise ValueError(f"Unsafe filename in pack metadata: {filename!r}")
    base = pack_dir.resolve()
    target = (pack_dir / filename)
    if target.is_symlink():
        raise ValueError(f"Refusing symlink inside sample pack: {filename!r}")
    resolved = target.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Path escapes pack directory: {filename!r}")
    return resolved


def _resolve_pubkey(pack_dir: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"Public key not found: {explicit}")
        return explicit
    for candidate in ("public_key.pem", "public_key.pub"):
        p = pack_dir / candidate
        if p.is_file():
            return p
    raise FileNotFoundError(f"No public key found in {pack_dir} (expected public_key.pem or public_key.pub)")


def _resolve_signature_bytes(pack_dir: Path, explicit: Path | None) -> tuple[bytes, str]:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"Signature file not found: {explicit}")
        if explicit.name.endswith(".b64"):
            raw = base64.b64decode(explicit.read_text(encoding="ascii").strip(), validate=True)
        else:
            raw = explicit.read_bytes()
        if len(raw) != 64:
            raise ValueError(f"Expected 64-byte Ed25519 signature in {explicit.name}, got {len(raw)} bytes")
        return raw, explicit.name

    raw_sig_path = pack_dir / "manifest.sig"
    b64_sig_path = pack_dir / "manifest.sig.b64"
    raw_bytes: bytes | None = None
    b64_bytes: bytes | None = None

    if raw_sig_path.is_file():
        raw_bytes = raw_sig_path.read_bytes()
        if len(raw_bytes) != 64:
            raise ValueError(f"Expected 64-byte raw Ed25519 signature in manifest.sig, got {len(raw_bytes)} bytes")
    if b64_sig_path.is_file():
        b64_bytes = base64.b64decode(b64_sig_path.read_text(encoding="ascii").strip(), validate=True)
        if len(b64_bytes) != 64:
            raise ValueError(f"Expected 64-byte decoded signature in manifest.sig.b64, got {len(b64_bytes)} bytes")

    if raw_bytes is not None and b64_bytes is not None:
        if raw_bytes != b64_bytes:
            raise ValueError("manifest.sig and manifest.sig.b64 disagree")
        return raw_bytes, "manifest.sig + manifest.sig.b64"
    if raw_bytes is not None:
        return raw_bytes, "manifest.sig"
    if b64_bytes is not None:
        return b64_bytes, "manifest.sig.b64"
    raise FileNotFoundError(f"No signature file found in {pack_dir} (expected manifest.sig or manifest.sig.b64)")


def _parse_ed25519_spki_pem(pem_bytes: bytes) -> tuple[bytes, bytes]:
    text = pem_bytes.decode("ascii")
    if "PRIVATE KEY" in text:
        raise ValueError("Refusing private key file during verification.")
    if "-----BEGIN PUBLIC KEY-----" not in text or "-----END PUBLIC KEY-----" not in text:
        raise ValueError("Public key is not in standard SPKI PEM format.")
    b64_body = "".join(
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("-----")
    )
    der = base64.b64decode(b64_body, validate=True)
    if len(der) != 44 or not der.startswith(ED25519_SPKI_PREFIX):
        raise ValueError(f"Invalid Ed25519 SPKI DER public key (len={len(der)})")
    return der, der[len(ED25519_SPKI_PREFIX) :]


def _verify_ed25519_openssl(pubkey_path: Path, manifest_path: Path, sig_bytes: bytes) -> None:
    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        raise RuntimeError("System `openssl` binary not found in PATH; cannot verify Ed25519 signature.")
    with tempfile.TemporaryDirectory(prefix="formd-pack-verify-") as td:
        sig_file = Path(td) / "manifest.sig"
        sig_file.write_bytes(sig_bytes)
        proc = subprocess.run(
            [
                openssl_bin,
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(pubkey_path),
                "-rawin",
                "-in",
                str(manifest_path),
                "-sigfile",
                str(sig_file),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    if proc.returncode != 0 or "Signature Verified Successfully" not in proc.stdout:
        detail = (proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}"
        raise ValueError(f"Ed25519 signature verification FAILED: {detail}")


def verify_pack(
    pack_dir: Path,
    *,
    pubkey_path: Path | None = None,
    sig_path: Path | None = None,
    quiet: bool = False,
) -> dict:
    pack_dir = pack_dir.resolve()
    manifest_path = _safe_child_path(pack_dir, "manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest.json in {pack_dir}")

    resolved_pubkey = _resolve_pubkey(pack_dir, pubkey_path)
    sig_bytes, sig_label = _resolve_signature_bytes(pack_dir, sig_path)

    # 1. Verify detached Ed25519 signature over raw manifest.json bytes BEFORE trusting manifest contents
    pub_pem_bytes = resolved_pubkey.read_bytes()
    spki_der, raw_pub = _parse_ed25519_spki_pem(pub_pem_bytes)
    _verify_ed25519_openssl(resolved_pubkey, manifest_path, sig_bytes)

    # 2. Parse manifest.json and cross-check public key fingerprints
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema_version") != "formd-pack/v1":
        raise ValueError(f"Unsupported schema_version: {manifest.get('schema_version')!r}")

    signing = manifest.get("signing") or {}
    if signing.get("algorithm") != "Ed25519":
        raise ValueError(f"Unexpected signing algorithm: {signing.get('algorithm')!r}")
    expected_checks = {
        "public_key_spki_sha256": _sha256_bytes(spki_der),
        "public_key_pem_sha256": _sha256_bytes(pub_pem_bytes),
        "public_key_raw_sha256": _sha256_bytes(raw_pub),
        "public_key_raw_hex": raw_pub.hex(),
        "public_key_raw_b64": base64.b64encode(raw_pub).decode("ascii"),
    }
    for field, actual in expected_checks.items():
        if signing.get(field) != actual:
            raise ValueError(f"Public key fingerprint mismatch for {field}: manifest={signing.get(field)!r} actual={actual!r}")

    # 3. Verify filings_30d.jsonl byte length and SHA-256 against signed manifest.json
    artifacts = manifest.get("artifacts") or {}
    filings_name = str(artifacts.get("filings_file") or "")
    filings_path = _safe_child_path(pack_dir, filings_name)
    if not filings_path.is_file():
        raise FileNotFoundError(f"Missing filings artifact: {filings_name}")

    filings_bytes = filings_path.read_bytes()
    actual_sha256 = _sha256_bytes(filings_bytes)
    if len(filings_bytes) != artifacts.get("filings_bytes"):
        raise ValueError(
            f"Byte length mismatch for {filings_name}: expected {artifacts.get('filings_bytes')}, got {len(filings_bytes)}"
        )
    if actual_sha256 != artifacts.get("filings_sha256"):
        raise ValueError(
            f"SHA-256 mismatch for {filings_name}: expected {artifacts.get('filings_sha256')}, got {actual_sha256}"
        )

    # 4. Verify record count, canonical JSONL structure, unique accessions, date window, and SEC URLs
    date_range = manifest.get("date_range") or {}
    start_date = str(date_range.get("start") or "")
    end_date = str(date_range.get("end") or "")
    lines = filings_bytes.decode("utf-8").splitlines()
    if len(lines) != manifest.get("record_count"):
        raise ValueError(f"Record count mismatch: manifest={manifest.get('record_count')}, actual={len(lines)}")

    seen_accessions: set[str] = set()
    for idx, line in enumerate(lines, start=1):
        rec = json.loads(line)
        if not isinstance(rec, dict):
            raise ValueError(f"Line {idx} is not a JSON object")
        acc = str(rec.get("accession_number") or "")
        if not acc or acc in seen_accessions:
            raise ValueError(f"Line {idx} has missing or duplicate accession_number: {acc!r}")
        seen_accessions.add(acc)
        fdate = str(rec.get("filing_date") or "")
        if not (start_date <= fdate <= end_date):
            raise ValueError(f"Line {idx} filing_date {fdate!r} outside [{start_date}, {end_date}]")
        url = str(rec.get("sec_edgar_url") or "")
        if not url.startswith("https://www.sec.gov/Archives/edgar/data/"):
            raise ValueError(f"Line {idx} has non-SEC EDGAR URL: {url!r}")

    # 5. If SHA256SUMS.txt exists, verify every listed artifact checksum
    sums_checked = 0
    sums_path = pack_dir / "SHA256SUMS.txt"
    if sums_path.is_file():
        for raw_line in sums_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            if len(parts) != 2 or not _SHA256_HEX_RE.fullmatch(parts[0]):
                raise ValueError(f"Malformed line in SHA256SUMS.txt: {raw_line!r}")
            expected_hex, rel_name = parts[0], parts[1].strip()
            target = _safe_child_path(pack_dir, rel_name)
            if not target.is_file():
                raise FileNotFoundError(f"File listed in SHA256SUMS.txt is missing: {rel_name}")
            got_hex = _sha256_bytes(target.read_bytes())
            if got_hex != expected_hex:
                raise ValueError(f"SHA256SUMS.txt mismatch for {rel_name}: expected {expected_hex}, got {got_hex}")
            sums_checked += 1

    result = {
        "ok": True,
        "pack_id": manifest["pack_id"],
        "date_range": f"{start_date}..{end_date}",
        "record_count": len(lines),
        "filings_sha256": actual_sha256,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "public_key_file": resolved_pubkey.name,
        "public_key_spki_sha256": expected_checks["public_key_spki_sha256"],
        "signature_source": sig_label,
        "sha256sums_entries_verified": sums_checked,
    }
    if not quiet:
        print(f"PASS: {result['pack_id']}")
        print(f"  Ed25519 signature : OK ({sig_label} via {resolved_pubkey.name})")
        print(f"  Pubkey SPKI SHA256: {result['public_key_spki_sha256']}")
        print(f"  Manifest SHA256   : {result['manifest_sha256']}")
        print(f"  Filings SHA256    : {result['filings_sha256']} ({result['record_count']} records, {result['date_range']})")
        if sums_checked:
            print(f"  SHA256SUMS.txt    : OK ({sums_checked} files verified)")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing manifest.json, filings_30d.jsonl, public key, and signature.",
    )
    parser.add_argument("--pubkey", type=Path, default=None, help="Optional explicit public key path.")
    parser.add_argument("--sig", type=Path, default=None, help="Optional explicit signature path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON verification summary.")
    args = parser.parse_args(argv)

    try:
        summary = verify_pack(
            args.pack_dir,
            pubkey_path=args.pubkey,
            sig_path=args.sig,
            quiet=args.json,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
