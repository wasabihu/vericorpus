#!/usr/bin/env python3
"""Package audited allowlist (`mode=pack`) corpora into XERJ-ready packs with detached SHA256SUMS and Ed25519 sig."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vericorpus import compliance  # noqa: E402

DEFAULT_FLAGSHIP_SLUGS = (
    "biomed-clinical-ccby",
    "ai-papers-ccby",
    "cn-github-stars",
    "sec-ipo-prospectus-pack",
)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_file_frontmatter_license(md_path: Path, fallback_manifest_lic: str) -> str:
    """Verify every packaged Markdown file declares an allowlisted pack license in YAML frontmatter."""
    text = md_path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise compliance.ComplianceError(f"拒绝无溯源 YAML frontmatter 的文件进入公开包：{md_path}")
    lic = ""
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip().lower() == "license":
                lic = v.strip()
                break
    if not lic:
        raise compliance.ComplianceError(f"文件 frontmatter 缺少 license 字段：{md_path}")
    if lic not in compliance.PACK_ALLOWED_LICENSES:
        raise compliance.ComplianceError(
            f"禁止将受限或未核验许可 ({lic!r}) 的文件打包发布：{md_path}（manifest={fallback_manifest_lic!r}）"
        )
    return lic


def _write_deterministic_zip(pack_dir: Path, archive_path: Path) -> None:
    """Create a deterministic ZIP archive containing pack files without embedding detached .sig files."""
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pack_dir.rglob("*")):
            if not f.is_file() or f.is_symlink() or f.name.endswith(".sig"):
                continue
            rel = f.relative_to(pack_dir).as_posix()
            info = zipfile.ZipInfo(filename=rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, f.read_bytes())


def build_hubpack(
    slug: str,
    *,
    corpora_dir: Path | None = None,
    raw_root: Path | None = None,
    out_root: Path | None = None,
    sign_key: Path | None = None,
    xerj_bin: str | None = None,
) -> dict[str, Any]:
    """Assemble one allowlist pack corpus into `<out_root>/<slug>/` + `<slug>-pack.zip` + detached `<slug>-SHA256SUMS(.sig)`."""
    clean_slug = compliance.validate_slug(slug)
    c_dir = (Path(corpora_dir) if corpora_dir is not None else (ROOT / "corpora")).resolve()
    r_root = (Path(raw_root) if raw_root is not None else (ROOT / "data" / "raw")).resolve()
    o_root = (Path(out_root) if out_root is not None else (ROOT / "builds" / "hubpacks")).resolve()

    manifest_path = compliance.validate_rel_path(f"{clean_slug}/manifest.json", c_dir)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"未找到语料清单：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compliance.validate_manifest(manifest)
    mode = str(manifest.get("mode") or "").strip()
    if mode != "pack":
        raise ValueError(f"禁止将 recipe 语料 {clean_slug!r} 打包为对外 .hubpack")

    src_dir = compliance.validate_rel_path(clean_slug, r_root)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"语料原始数据目录不存在（请先运行 fetchers.py）：{src_dir}")

    # Pre-validate ALL source Markdown files BEFORE touching out_root so failing runs emit zero bytes!
    md_files = sorted(p for p in src_dir.rglob("*.md") if p.is_file() and not p.is_symlink())
    if not md_files:
        raise ValueError(f"语料目录 {src_dir} 内没有可打包的 .md 文件")

    verified_items: list[tuple[Path, str]] = []
    manifest_lic = str(manifest["license"])
    for src_f in md_files:
        rel_posix = src_f.relative_to(src_dir).as_posix()
        compliance.validate_rel_path(rel_posix)
        _verify_file_frontmatter_license(src_f, manifest_lic)
        verified_items.append((src_f, rel_posix))

    o_root.mkdir(parents=True, exist_ok=True)
    pack_dir = compliance.validate_rel_path(clean_slug, o_root)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    docs_dir = pack_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_f, rel_posix in verified_items:
        dst_f = compliance.validate_rel_path(rel_posix, docs_dir)
        dst_f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_f, dst_f)
        copied += 1

    pack_meta = {
        "slug": manifest["slug"],
        "title": manifest.get("title"),
        "description": manifest.get("description"),
        "domain": manifest.get("domain"),
        "region": manifest.get("region"),
        "mode": "pack",
        "license": manifest.get("license"),
        "source_url": manifest.get("source_url"),
        "files_count": copied,
    }
    (pack_dir / "pack_manifest.json").write_text(json.dumps(pack_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sums_lines: list[str] = []
    for f in sorted(pack_dir.rglob("*")):
        if not f.is_file() or f.name in ("SHA256SUMS", "SHA256SUMS.sig"):
            continue
        rel = f.relative_to(pack_dir).as_posix()
        sums_lines.append(f"{_sha256_file(f)}  {rel}")
    (pack_dir / "SHA256SUMS").write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

    archive_path = compliance.validate_rel_path(f"{clean_slug}-pack.zip", o_root)
    _write_deterministic_zip(pack_dir, archive_path)
    outer_sums_path = compliance.validate_rel_path(f"{clean_slug}-SHA256SUMS", o_root)
    outer_sums_lines = [
        f"{_sha256_file(archive_path)}  {archive_path.name}",
        f"{_sha256_file(pack_dir / 'SHA256SUMS')}  {clean_slug}/SHA256SUMS",
    ]
    outer_sums_path.write_text("\n".join(outer_sums_lines) + "\n", encoding="utf-8")

    signed = False
    sig_size = 0
    detached_sig_path = compliance.validate_rel_path(f"{clean_slug}-SHA256SUMS.sig", o_root)
    if sign_key is not None:
        key_p = Path(sign_key)
        if not key_p.is_file():
            raise FileNotFoundError(f"签名私钥文件不存在：{key_p}")
        bin_path = xerj_bin or shutil.which("xerj")
        if not bin_path:
            raise RuntimeError("未找到 xerj 可执行文件，无法执行 Ed25519 签名")

        clean_env = {
            k: v
            for k, v in os.environ.items()
            if not any(tok in k.upper() for tok in ("SECRET", "SIGNING_SEED", "API_KEY", "TOKEN"))
        }
        clean_env["XERJ_DISABLE_FEEDBACK"] = "true"

        subprocess.run([bin_path, "corpus", "sign", str(pack_dir), "--key", str(key_p)], check=True, capture_output=True, env=clean_env)
        sig_p = pack_dir / "SHA256SUMS.sig"
        if not sig_p.is_file():
            raise RuntimeError("xerj corpus sign 执行后未生成 SHA256SUMS.sig")

        # Sign the detached outer <slug>-SHA256SUMS in a private temp dir so verify-before-extract works on the archive!
        with tempfile.TemporaryDirectory(prefix="vericorpus-detached-sig-") as sig_td:
            tmp_sig_dir = Path(sig_td)
            shutil.copy2(outer_sums_path, tmp_sig_dir / "SHA256SUMS")
            subprocess.run([bin_path, "corpus", "sign", str(tmp_sig_dir), "--key", str(key_p)], check=True, capture_output=True, env=clean_env)
            shutil.copy2(tmp_sig_dir / "SHA256SUMS.sig", detached_sig_path)

        signed = True
        sig_size = detached_sig_path.stat().st_size

    return {
        "slug": clean_slug,
        "license": manifest.get("license"),
        "pack_dir": str(pack_dir),
        "archive_path": str(archive_path),
        "outer_sha256sums": str(outer_sums_path),
        "detached_sig": str(detached_sig_path) if signed else None,
        "files_count": copied,
        "sha256_entries": len(sums_lines),
        "signed": signed,
        "sig_bytes": sig_size,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slugs", nargs="+", default=list(DEFAULT_FLAGSHIP_SLUGS), help="Allowlist pack slugs to bundle")
    ap.add_argument("--out-root", default=str(ROOT / "builds" / "hubpacks"))
    ap.add_argument("--sign-key", default=None, help="Optional external Ed25519 .key file for `xerj corpus sign`")
    args = ap.parse_args(argv)

    results = [
        build_hubpack(
            slug,
            out_root=Path(args.out_root),
            sign_key=Path(args.sign_key) if args.sign_key else None,
        )
        for slug in args.slugs
    ]
    print(json.dumps({"ok": True, "packs": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
