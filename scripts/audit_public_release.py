#!/usr/bin/env python3
"""Pre-push public release auditor for vericorpus.

Verifies corpus license allowlists, enforces binary/size/null-byte gates,
scans tracked + untracked files AND full Git commit/blob history for home paths,
API tokens, personal indices/emails, strategy docs, closed-source leaks, and
validates CC-BY-4.0 Section 3(a) attribution on evaluation datasets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SRC = _DEFAULT_ROOT / "src"
if str(_DEFAULT_SRC) not in sys.path:
    sys.path.insert(0, str(_DEFAULT_SRC))

from vericorpus import compliance  # noqa: E402

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MiB ceiling on all tracked/candidate repository files
FORBIDDEN_TOP_DIRS = frozenset({"data", ".venv"})
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".key",
        ".seed",
        ".pem",
        ".sig",
        ".safetensors",
        ".gguf",
        ".npz",
        ".pt",
        ".pth",
        ".onnx",
        ".bin",
        ".hubpack",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".zst",
        ".pkl",
        ".pickle",
        ".parquet",
    }
)
CLOSED_SOURCE_FILENAMES = frozenset(
    {
        "verifier" + ".py",
        "compiler_mlx" + ".py",
        "build_cn_cases" + ".py",
        "build_v2_corpus" + ".py",
        "build_v3_corpus" + ".py",
        "fuse_8bit" + ".py",
        "doc_auditor" + ".py",
        "pdf_router" + ".py",
        "demo_server" + ".py",
        "eval_v3_wild" + ".py",
        "eval_compare_count_40" + ".py",
        "run_benchmark" + ".py",
        "mount_public_packs" + ".py",
        "audit_article_cli" + ".py",
    }
)
INTERNAL_STRATEGY_FILENAMES = frozenset(
    {
        "open_core_" + "funnel_guide.md",
        "xerj_partnership_" + "and_pr_kit.md",
    }
)
RAW_DISCLOSURE_SUFFIXES = (
    "_ANNUAL_REPORT.md",
    "_PROSPECTUS.md",
    "_INTERIM_REPORT.md",
    "_INQUIRY_REPLY.md",
    "_rebuilt.md",
)

# Construct all detection regexes via split literals so this script never contains banned tokens verbatim.
_HOME_PATH_RE = re.compile(r"(?<![A-Za-z0-9_./:-])/(?:" + "Users|" + "home)/[A-Za-z0-9._-]+")
_DYNAMIC_PRIVATE_HOME_RE = re.compile(
    r"Path\.home\(\)\s*/\s*[\"'](?:" + "Documents|" + "Desktop|" + "Downloads)[\"']"
)
_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sk_token", re.compile(r"\b" + "sk" + r"-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{12,}\b")),
    ("github_token", re.compile(r"\b" + "gh" + r"[pousr]_[A-Za-z0-9_]{12,}\b")),
    ("github_pat", re.compile(r"\b" + "github_" + r"pat_[A-Za-z0-9_]{22,}\b")),
    ("google_api_key", re.compile(r"\b" + "AI" + r"za[0-9A-Za-z_-]{16,}\b")),
    ("aws_access_key", re.compile(r"\b(?:" + "AK" + "IA|" + "AS" + r"IA)[0-9A-Z]{16}\b")),
    ("hf_token", re.compile(r"\b" + "hf" + r"_[A-Za-z0-9]{16,}\b")),
    ("url_credentials", re.compile(r"https?://[^/\s:@\"']+:[^/\s:@\"']+@[^/\s\"']+")),
    (
        "env_api_key_assign",
        re.compile(
            r"\b(?:XERJ_API_"
            + r"KEY|OPENAI_API_"
            + r"KEY|ANTHROPIC_API_"
            + r"KEY|GEMINI_API_"
            + r"KEY|HF_"
            + r"TOKEN|GITHUB_"
            + r"TOKEN|DART_API_"
            + r"KEY)\s*[:=]\s*[\"']?(?!your_|YOUR_|example|EXAMPLE|changeme|placeholder|\$\{|<|\*\*\*)[A-Za-z0-9_.-]{8,}"
        ),
    ),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*" + r"PRIVATE KEY-----")),
)
_PERSONAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "personal_index_prefix",
        re.compile(
            r"\b(?:"
            + "we"
            + "chat|"
            + "in"
            + "box|"
            + "jia"
            + "li|"
            + "wx"
            + "arch|"
            + "x"
            + "arch|"
            + "ba"
            + r"k)-[A-Za-z0-9_.*-]+"
        ),
    ),
    ("wx_id_leak", re.compile(r"\b" + "wx" + r"id_[A-Za-z0-9_-]{6,}\b")),
    ("fake_local_email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\." + r"local\b")),
    ("personal_gmail_leak", re.compile(r"\bwasabi\.net@" + r"gmail\.com\b", re.IGNORECASE)),
    (
        "personal_watchlist_note",
        re.compile(
            r"(?:"
            + "洛克"
            + "西|"
            + "Watchlist "
            + "Biomed|"
            + "Watchlist "
            + "AI|"
            + "严格覆盖用户全部"
            + "点名|"
            + "越疆测试包"
            + r"README)"
        ),
    ),
)
_CLOSED_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("closed_source_workspace_ref", re.compile(r"\b03-cn-reader-" + r"mvp\b")),
    (
        "closed_source_impl",
        re.compile(r"\b(?:class\s+LocalMLX" + r"Compiler|def\s+execute_" + r"program|def\s+compile_and_" + r"verify)\b"),
    ),
    ("wide_table_focus", re.compile(r"\bfocus_wide_tables_for_" + r"prompt\b")),
    ("closed_source_sft_spec", re.compile(r"\b(?:to_sft_chat_" + r"record|Neuro-Symbolic Verification " + r"Compiler)\b")),
    (
        "closed_source_model_codename",
        re.compile(
            r"(?:\bCN-Reader-"
            + r"(?:1\.7B|0\.6B)(?:-v\d+)?\b|\bcn_reader_"
            + r"(?:1_7b|0_6b)[A-Za-z0-9_]*\b|(?<=[:/])"
            + r"9360\b|"
            + "商业"
            + r"微调)"
        ),
    ),
    ("legacy_brand_leak", re.compile(r"Xerj\s+" + r"CN\s+Hub", re.IGNORECASE)),
    (
        "internal_strategy_doc",
        re.compile(r"(?:OPEN_CORE_" + r"FUNNEL_GUIDE|XERJ_PARTNERSHIP_" + r"AND_PR_KIT)", re.IGNORECASE),
    ),
)
_COAUTHOR_TRAILER_RE = re.compile(r"(?im)^\s*Co-Authored-" + r"By\s*:\s*\S+")
_TRAIN_FILE_RE = re.compile(r"^train_(?:sft|grpo).*\.(?:py|jsonl)$", re.IGNORECASE)
_FUSED_DIR_RE = re.compile(r"(?:^|/)(?:cn-reader-[^/]*fused|[^/]*fused-8bit)(?:/|$)", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_RESTRICTED_FRONTMATTER_RE = re.compile(
    r"(?im)^license\s*:\s*(?:CNINFO|HKEX|KRX)-Public-Disclosure\b"
)
_PLACEHOLDER_AUTHORS = frozenset(
    {
        "see original publication",
        "see original paper",
        "n/a",
        "unknown",
        "none",
        "详见原刊",
    }
)


def _self_check() -> None:
    """Built-in self-test ensuring no detection regex was accidentally broken during refactoring."""
    probes: list[tuple[re.Pattern[str], str, str]] = [
        (_HOME_PATH_RE, "/" + "Users/alice/doc.md", "https://example.com/users/guide"),
        (_HOME_PATH_RE, "/" + "home/bob/key.pem", "relative/path/home_page.md"),
        (dict(_TOKEN_PATTERNS)["sk_token"], "sk" + "-proj-AbCdEfGhIjKlMnOpQr12", "skill_level = 1"),
        (dict(_TOKEN_PATTERNS)["github_pat"], "github_" + "pat_11ABCDEF0123456789abcdef_Z", "github_pat_*"),
        (dict(_PERSONAL_PATTERNS)["personal_index_prefix"], "jia" + "li-private-1", "public-corpus-1"),
        (dict(_PERSONAL_PATTERNS)["personal_index_prefix"], "ba" + "k-2026", "baker_hughes"),
        (dict(_PERSONAL_PATTERNS)["personal_gmail_leak"], "wasabi.net@" + "gmail.com", "973168+wasabihu@users.noreply.github.com"),
        (dict(_CLOSED_SOURCE_PATTERNS)["legacy_brand_leak"], "Xerj " + "CN Hub", "VeriCorpus"),
        (dict(_CLOSED_SOURCE_PATTERNS)["closed_source_model_codename"], "CN-Reader-" + "1.7B-v3", "Neuro-Symbolic Reader (1.7B)"),
        (dict(_CLOSED_SOURCE_PATTERNS)["internal_strategy_doc"], "OPEN_CORE_" + "FUNNEL_GUIDE", "ENGINEERING_PHILOSOPHY"),
        (_COAUTHOR_TRAILER_RE, "Co-Authored-" + "By: Bot <b@x.com>", "Zero `Co-Authored-" + "By` AI trailers allowed."),
    ]
    for pat, bad_input, good_input in probes:
        if not pat.search(bad_input):
            raise AssertionError(f"Auditor self-check failed to match positive probe: {pat.pattern!r}")
        if pat.search(good_input):
            raise AssertionError(f"Auditor self-check false-triggered on clean probe: {good_input!r}")


def _git_candidate_files(root: Path) -> tuple[list[str], bool]:
    """Enumerate git-tracked and untracked non-ignored files, falling back if not a git repo."""
    if (root / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--others", "--exclude-standard"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        items = {
            part.decode("utf-8", errors="replace")
            for blob in (tracked, untracked)
            for part in blob.split(b"\x00")
            if part
        }
        return sorted(items), True

    items = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    ]
    return sorted(items), False


def _add_violation(
    violations: list[dict[str, Any]],
    *,
    category: str,
    path: str,
    detail: str,
    line: int | None = None,
) -> None:
    violations.append(
        {
            "category": category,
            "path": path,
            "line": line,
            "detail": detail,
        }
    )


def _check_path_rules(rel: str, full_path: Path, violations: list[dict[str, Any]]) -> None:
    parts = rel.split("/")
    name = parts[-1]
    lower_name = name.lower()

    if parts[0] in FORBIDDEN_TOP_DIRS or ".venv" in parts:
        _add_violation(
            violations,
            category="forbidden_file",
            path=rel,
            detail="Tracked or unignored file under restricted directory (data/ or .venv/)",
        )
        return

    if full_path.is_file() and full_path.stat().st_size > MAX_FILE_BYTES:
        _add_violation(
            violations,
            category="binary_or_oversized_file",
            path=rel,
            detail=f"File exceeds {MAX_FILE_BYTES} bytes limit ({full_path.stat().st_size} bytes)",
        )

    if lower_name in INTERNAL_STRATEGY_FILENAMES:
        _add_violation(
            violations,
            category="closed_source_leak",
            path=rel,
            detail=f"Internal strategy document forbidden in public repository (internal_strategy_doc): {rel}",
        )

    if (
        lower_name.startswith(".env")
        or lower_name == "hub.db"
        or lower_name.startswith("hub.db-")
        or lower_name.endswith(".hubpack.tar.zst")
        or any(lower_name.endswith(sfx) for sfx in FORBIDDEN_SUFFIXES)
    ):
        _add_violation(
            violations,
            category="forbidden_file",
            path=rel,
            detail=f"Forbidden secret, weight, database, signature, or archive artifact: {name}",
        )

    if lower_name.endswith(".pdf"):
        _add_violation(
            violations,
            category="personal_data_leak",
            path=rel,
            detail="Raw PDF disclosure/document file tracked or unignored outside data/",
        )

    if (
        lower_name in CLOSED_SOURCE_FILENAMES
        or _TRAIN_FILE_RE.match(name)
        or _FUSED_DIR_RE.search(rel)
    ):
        _add_violation(
            violations,
            category="closed_source_leak",
            path=rel,
            detail=f"Closed-source training/verifier script or weight artifact: {rel}",
        )

    if any(name.endswith(sfx) for sfx in RAW_DISCLOSURE_SUFFIXES):
        _add_violation(
            violations,
            category="personal_data_leak",
            path=rel,
            detail="Raw CNINFO/HKEX rebuilt disclosure Markdown found outside .gitignored data/",
        )


def _scan_text_lines(
    rel: str,
    text: str,
    violations: list[dict[str, Any]],
    *,
    category_override: str | None = None,
) -> None:
    for line_no, line_text in enumerate(text.splitlines(), start=1):
        for home_match in _HOME_PATH_RE.finditer(line_text):
            _add_violation(
                violations,
                category=category_override or "hardcoded_home_path",
                path=rel,
                line=line_no,
                detail=f"Hardcoded local home path: {home_match.group(0)}",
            )
        for dyn_match in _DYNAMIC_PRIVATE_HOME_RE.finditer(line_text):
            _add_violation(
                violations,
                category=category_override or "hardcoded_home_path",
                path=rel,
                line=line_no,
                detail=f"Hardcoded local home path: {dyn_match.group(0)}",
            )

        for label, pat in _TOKEN_PATTERNS:
            if pat.search(line_text):
                _add_violation(
                    violations,
                    category=category_override or "api_token_leak",
                    path=rel,
                    line=line_no,
                    detail=f"Matched secret/API token pattern ({label})",
                )

        for label, pat in _PERSONAL_PATTERNS:
            m = pat.search(line_text)
            if m:
                _add_violation(
                    violations,
                    category=category_override or "personal_data_leak",
                    path=rel,
                    line=line_no,
                    detail=f"Matched personal data pattern ({label}): {m.group(0)}",
                )

        for label, pat in _CLOSED_SOURCE_PATTERNS:
            if pat.search(line_text):
                _add_violation(
                    violations,
                    category=category_override or "closed_source_leak",
                    path=rel,
                    line=line_no,
                    detail=f"Matched closed-source/strategy pattern ({label})",
                )


def _decode_for_scan(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (b"\x00" in raw and len(raw) >= 4):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                decoded = raw.decode(enc)
                if decoded.isprintable() or "\n" in decoded or "=" in decoded:
                    return decoded
            except UnicodeDecodeError:
                continue
    return raw.decode("utf-8", errors="replace")


def _audit_eval_json(rel: str, text: str, violations: list[dict[str, Any]]) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _add_violation(violations, category="eval_schema_error", path=rel, detail=f"Invalid JSON in eval file: {exc}")
        return

    if not isinstance(data, list):
        return

    for idx, case in enumerate(data):
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or f"row_{idx}")
        doc = str(case.get("oracle_document") or "")
        if not doc:
            continue

        if _RESTRICTED_FRONTMATTER_RE.search(doc) or "Local-Private-Sample" in doc or "All Rights Reserved" in doc:
            _add_violation(
                violations,
                category="personal_data_leak",
                path=rel,
                detail=f"{cid}: oracle_document embeds restricted or All-Rights-Reserved source text",
            )

        is_ccby = (
            str(case.get("license") or "") == "CC-BY-4.0"
            or "license: CC-BY-4.0" in doc
            or "- **License**: CC-BY-4.0" in doc
        )
        if is_ccby:
            if "https://creativecommons.org/licenses/by/4.0/" not in doc:
                _add_violation(
                    violations,
                    category="eval_ccby_attribution",
                    path=rel,
                    detail=f"{cid}: CC-BY-4.0 oracle_document missing canonical license URI",
                )
            if "Adaptation Notice" not in doc:
                _add_violation(
                    violations,
                    category="eval_ccby_attribution",
                    path=rel,
                    detail=f"{cid}: CC-BY-4.0 oracle_document missing Section 3(a) Adaptation Notice",
                )
            m_auth = re.search(r"(?m)^-\s*\*\*Authors\*\*\s*:\s*(.+)$", doc)
            authors_val = m_auth.group(1).strip() if m_auth else ""
            if not authors_val or authors_val.lower() in _PLACEHOLDER_AUTHORS:
                _add_violation(
                    violations,
                    category="eval_ccby_attribution",
                    path=rel,
                    detail=f"{cid}: CC-BY-4.0 oracle_document missing real author attribution ({authors_val!r})",
                )

        ev_list = (case.get("expected") or {}).get("evidence") or []
        if isinstance(ev_list, list):
            for span in ev_list:
                if not isinstance(span, dict):
                    continue
                st, ed, qt = span.get("start"), span.get("end"), span.get("quote")
                if not (isinstance(st, int) and isinstance(ed, int) and 0 <= st < ed <= len(doc) and doc[st:ed] == qt):
                    _add_violation(
                        violations,
                        category="eval_ccby_attribution",
                        path=rel,
                        detail=f"{cid}: invalid evidence character offset [{st}:{ed}]",
                    )


def _scan_text_file(rel: str, full_path: Path, violations: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if not full_path.is_file():
        return False, None
    raw = full_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    if b"\x00" in raw:
        _add_violation(
            violations,
            category="binary_or_oversized_file",
            path=rel,
            detail="Null byte detected (binary or UTF-16 file not permitted in pure-text/code repository)",
        )
        text = _decode_for_scan(raw)
        _scan_text_lines(rel, text, violations)
        return False, sha

    text = raw.decode("utf-8", errors="replace")

    if rel.endswith((".md", ".txt")):
        fm = _FRONTMATTER_RE.match(text)
        if fm and _RESTRICTED_FRONTMATTER_RE.search(fm.group(1)):
            _add_violation(
                violations,
                category="personal_data_leak",
                path=rel,
                line=1,
                detail="Materialized restricted CNINFO/HKEX/KRX disclosure found outside data/",
            )

    if rel.startswith("evals/") and rel.endswith(".json"):
        _audit_eval_json(rel, text, violations)

    _scan_text_lines(rel, text, violations)
    return True, sha


def _scan_git_history(root: Path, scanned_worktree_shas: set[str], violations: list[dict[str, Any]]) -> None:
    """Scan all Git commits (author/committer emails + Co-Authored-By trailers) and all historical Git blobs."""
    if not (root / ".git").exists():
        return
    has_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if has_head.returncode != 0:
        return

    log_raw = subprocess.run(
        ["git", "-C", str(root), "log", "--all", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x00"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.decode("utf-8", errors="replace")

    for rec in log_raw.split("\x00"):
        rec = rec.strip()
        if not rec:
            continue
        parts = rec.split("\x1f", 5)
        if len(parts) < 6:
            continue
        commit_sha, _an, ae, _cn, ce, msg = parts
        short_sha = commit_sha[:12]
        for role, email in (("author", ae.strip()), ("committer", ce.strip())):
            for label, pat in _PERSONAL_PATTERNS:
                if pat.search(email):
                    _add_violation(
                        violations,
                        category="git_history_leak",
                        path=f"git:{short_sha}",
                        detail=f"Commit {role} email matched {label}: {email}",
                    )
        if _COAUTHOR_TRAILER_RE.search(msg):
            _add_violation(
                violations,
                category="git_history_leak",
                path=f"git:{short_sha}",
                detail="Commit message contains forbidden co_authored_by_trailer",
            )
        _scan_text_lines(f"git-commit:{short_sha}", msg, violations, category_override="git_history_leak")

    rev_out = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--objects", "--all"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.decode("utf-8", errors="replace")

    obj_lines = [ln for ln in rev_out.splitlines() if " " in ln]
    if not obj_lines:
        return

    obj_map: dict[str, str] = {}
    for ln in obj_lines:
        oid, obj_path = ln.split(" ", 1)
        if oid and obj_path:
            obj_map.setdefault(oid, obj_path)

    batch_in = "".join(f"{oid}\n" for oid in obj_map).encode("utf-8")
    batch_raw = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=batch_in,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout

    pos = 0
    total_len = len(batch_raw)
    while pos < total_len:
        nl = batch_raw.find(b"\n", pos)
        if nl == -1:
            break
        hdr = batch_raw[pos:nl].decode("ascii", errors="replace")
        pos = nl + 1
        hdr_parts = hdr.split()
        if len(hdr_parts) < 3:
            continue
        oid, obj_type, sz_str = hdr_parts[0], hdr_parts[1], hdr_parts[2]
        size = int(sz_str)
        content = batch_raw[pos : pos + size]
        pos += size + 1  # trailing LF after object payload
        if obj_type != "blob":
            continue
        content_sha = hashlib.sha256(content).hexdigest()
        if content_sha in scanned_worktree_shas:
            continue
        hist_path = f"git-blob:{oid[:12]}:{obj_map.get(oid, '')}"
        if size > MAX_FILE_BYTES:
            _add_violation(
                violations,
                category="git_history_leak",
                path=hist_path,
                detail=f"Historical git blob exceeds {MAX_FILE_BYTES} bytes ({size} bytes)",
            )
            continue
        text = _decode_for_scan(content)
        _scan_text_lines(hist_path, text, violations, category_override="git_history_leak")


def audit_repo(repo_root: str | Path, *, check_git_history: bool = True) -> dict[str, Any]:
    """Run full pre-push release compliance, binary, eval attribution, and git history leak checks."""
    _self_check()
    root = Path(repo_root).resolve()
    violations: list[dict[str, Any]] = []
    corpora_audited = 0

    try:
        audited = compliance.audit_corpora_dir(root / "corpora")
        corpora_audited = len(audited)
    except Exception as exc:
        _add_violation(
            violations,
            category="compliance_audit",
            path="corpora",
            detail=str(exc),
        )

    candidates, git_mode = _git_candidate_files(root)
    text_files_scanned = 0
    scanned_shas: set[str] = set()
    for rel in candidates:
        full_p = root / rel
        _check_path_rules(rel, full_p, violations)
        pre_v_count = len(violations)
        is_text, file_sha = _scan_text_file(rel, full_p, violations)
        if is_text:
            text_files_scanned += 1
        if file_sha and len(violations) == pre_v_count:
            scanned_shas.add(file_sha)

    if git_mode and check_git_history:
        _scan_git_history(root, scanned_shas, violations)

    counts_by_category: dict[str, int] = {}
    for item in violations:
        cat = item["category"]
        counts_by_category[cat] = counts_by_category.get(cat, 0) + 1

    return {
        "ok": len(violations) == 0,
        "root": str(root),
        "git_enumerated": git_mode,
        "git_history_checked": bool(git_mode and check_git_history),
        "corpora_audited": corpora_audited,
        "files_enumerated": len(candidates),
        "text_files_scanned": text_files_scanned,
        "violation_count": len(violations),
        "counts_by_category": counts_by_category,
        "violations": violations,
    }


def format_report(result: dict[str, Any]) -> str:
    """Format a human-readable summary plus JSON block."""
    status = "PASS" if result["ok"] else "FAIL"
    lines = [
        f"Public Release Audit: {status}",
        f"Root: {result['root']}",
        (
            f"Corpora audited: {result['corpora_audited']} | "
            f"Files enumerated: {result['files_enumerated']} | "
            f"Text files scanned: {result['text_files_scanned']} | "
            f"Violations: {result['violation_count']}"
        ),
    ]
    if result["violations"]:
        lines.append("Violations:")
        for v in result["violations"]:
            loc = f"{v['path']}:{v['line']}" if v.get("line") else v["path"]
            lines.append(f"  - [{v['category']}] {loc} -> {v['detail']}")
    lines.append("")
    lines.append(json.dumps(result, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit vericorpus before public GitHub push.")
    parser.add_argument("--root", default=str(_DEFAULT_ROOT), help="Repository root path to audit.")
    parser.add_argument("--json-only", action="store_true", help="Print JSON summary only.")
    args = parser.parse_args(argv)

    result = audit_repo(args.root, check_git_history=True)
    if args.json_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
