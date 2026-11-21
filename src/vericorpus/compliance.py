"""合规清单校验器与不可信输入安全门禁（pathgate + HTTPS/SSRF 防护 + 40 位 SHA 校验）。"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

PACK_ALLOWED_LICENSES = frozenset(
    {
        "Public-Domain-CN-Law",
        "Apache-2.0",
        "MIT",
        "BSD-3-Clause",
        "BSD-2-Clause",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC0-1.0",
        "SEC-Public-Filing",
    }
)

RECIPE_ALLOWED_LICENSES = PACK_ALLOWED_LICENSES | frozenset(
    {
        "HKEX-Public-Disclosure",
        "CNINFO-Public-Disclosure",
        "KRX-Public-Disclosure",
        "Multi-Exchange-Public-Disclosure",
    }
)

FORBIDDEN_LICENSE_PREFIXES = (
    "NOASSERTION",
    "NONE",
    "UNKNOWN",
    "PROPRIETARY",
    "ALL-RIGHTS-RESERVED",
    "GPL",
    "AGPL",
    "LGPL",
    "SSPL",
    "BUSL",
)

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_BAD_PATH_CHARS_RE = re.compile(r"[\x00-\x1f\x7f:*?\[\]!#\\]")


class ComplianceError(ValueError):
    """语料清单、路径或外部 URL 未通过开源许可与安全边界检查。"""


def validate_slug(slug: str) -> str:
    """Validate corpus slug against path traversal, underscore drift, and CLI flag injection."""
    s = str(slug or "").strip()
    if not _SLUG_RE.fullmatch(s):
        raise ComplianceError(
            f"非法语料 slug {slug!r}：仅允许小写字母、数字与内部连字符 [a-z0-9-]（禁止 ..、/、_ 或前导 -）"
        )
    return s


def validate_commit_sha(commit: str, field: str = "commit") -> str:
    """Require full 40-hex lowercase Git commit SHA to prevent shallow-fetch failure or branch drift."""
    c = str(commit or "").strip()
    if not _SHA40_RE.fullmatch(c):
        raise ComplianceError(f"{field} 必须是 40 位小写十六进制完整 Commit SHA，拒绝短哈希或分支名: {commit!r}")
    return c


def validate_rel_path(rel_path: str, base_dir: str | Path | None = None) -> Path:
    """Enforce XERJ pathgate rules on relative paths and verify symlink-free containment under base_dir."""
    raw = str(rel_path or "")
    if not raw or len(raw.encode("utf-8")) > 240:
        raise ComplianceError(f"非法相对路径（为空或超长 >240B）: {rel_path!r}")
    if raw.startswith(("/", "\\")) or _BAD_PATH_CHARS_RE.search(raw):
        raise ComplianceError(f"拒绝绝对路径、控制字符、冒号或通配符: {rel_path!r}")

    parts = raw.split("/")
    for part in parts:
        if not part or part in (".", ".."):
            raise ComplianceError(f"拒绝包含空段或上级目录穿越 '..' 的路径: {rel_path!r}")
        if part.startswith("-"):
            raise ComplianceError(f"拒绝以 '-' 开头的路径组件（防命令行选项注入）: {rel_path!r}")

    rel_obj = Path(*parts)
    if base_dir is None:
        return rel_obj

    base_resolved = Path(base_dir).resolve()
    cur = Path(base_dir)
    if cur.is_symlink():
        raise ComplianceError(f"拒绝符号链接根目录: {cur}")
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            raise ComplianceError(f"拒绝符号链接逃逸路径: {cur}")

    resolved = (base_resolved / rel_obj).resolve()
    if not resolved.is_relative_to(base_resolved):
        raise ComplianceError(f"路径越界逃逸出基准目录 {base_resolved}: {rel_path!r}")
    return resolved


def _is_forbidden_host(hostname: str, *, allow_localhost: bool = False) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return True
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localhost")):
        return not (allow_localhost and host == "localhost")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if allow_localhost and ip.is_loopback:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_https_url(url: str, *, allow_localhost_http: bool = False) -> str:
    """Allow strictly https:// public URLs (or explicit localhost http:// only for isolated local node calls)."""
    raw = str(url or "").strip()
    if not raw:
        raise ComplianceError("URL 不能为空")
    parsed = urllib.parse.urlsplit(raw)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""

    if parsed.username or parsed.password:
        raise ComplianceError(f"禁止在 URL 中内嵌账号密码凭证: {raw!r}")

    if allow_localhost_http and scheme == "http" and host in ("127.0.0.1", "::1", "localhost"):
        return raw

    if scheme != "https":
        raise ComplianceError(f"外部请求仅允许 https:// 协议，拒绝 {scheme or 'missing'}:// ({raw!r})")

    if _is_forbidden_host(host, allow_localhost=False):
        raise ComplianceError(f"禁止访问本地回环、链路本地或私有内网地址: {host!r}")
    return raw


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_localhost_http: bool = False) -> None:
        super().__init__()
        self._allow_localhost_http = allow_localhost_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        abs_target = urllib.parse.urljoin(req.full_url, newurl)
        validate_https_url(abs_target, allow_localhost_http=self._allow_localhost_http)
        return super().redirect_request(req, fp, code, msg, headers, abs_target)


def _safe_urlopen(
    req_or_url: str | urllib.request.Request,
    *,
    timeout: float = 15.0,
    allow_localhost_http: bool = False,
) -> Any:
    """Open URL safely using HTTPS-only handler (no file:// or ftp://) and SSRF-checked redirects."""
    target_url = req_or_url.full_url if isinstance(req_or_url, urllib.request.Request) else str(req_or_url)
    validate_https_url(target_url, allow_localhost_http=allow_localhost_http)

    handlers: list[urllib.request.BaseHandler] = [
        _SafeRedirectHandler(allow_localhost_http=allow_localhost_http),
        urllib.request.HTTPSHandler(),
    ]
    if allow_localhost_http:
        handlers.append(urllib.request.HTTPHandler())
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req_or_url, timeout=timeout)


def _check_license_token(lic: str, *, mode: str, context: str) -> None:
    upper = lic.upper()
    if (
        not lic
        or any(upper.startswith(p) for p in FORBIDDEN_LICENSE_PREFIXES)
        or "-NC" in upper
        or "-ND" in upper
    ):
        raise ComplianceError(f"{context} 许可证 {lic!r} 禁止纳入语料清单（含非商用、禁止演绎、传染性或无明确授权）")
    if mode == "pack" and lic not in PACK_ALLOWED_LICENSES:
        raise ComplianceError(f"pack 模式 {context} 仅允许白名单许可，拒绝 {lic!r}")
    if mode == "recipe" and lic not in RECIPE_ALLOWED_LICENSES:
        raise ComplianceError(f"recipe 模式 {context} 拒绝未核验许可 {lic!r}")


def validate_manifest(manifest: dict[str, Any]) -> None:
    """校验单个语料清单的必填字段、pathgate 路径安全、HTTPS 协议、40 位 SHA 及版权许可白名单。"""
    if not isinstance(manifest, dict):
        raise ComplianceError("manifest 必须是 JSON 对象")

    for req_key in ("slug", "title", "mode", "license"):
        if not str(manifest.get(req_key) or "").strip():
            raise ComplianceError(f"缺少必填字段: {req_key}")

    validate_slug(str(manifest["slug"]))

    mode = str(manifest["mode"]).strip()
    if mode not in ("pack", "recipe"):
        raise ComplianceError(f"不支持的分发模式 {mode!r}，仅允许 'pack' 或 'recipe'")

    lic = str(manifest["license"]).strip()
    _check_license_token(lic, mode=mode, context="顶层")

    source_url = str(manifest.get("source_url") or "").strip()
    if source_url:
        validate_https_url(source_url)

    sources = manifest.get("sources")
    if not source_url and not (isinstance(sources, list) and sources):
        raise ComplianceError("必须提供 source_url 或非空 sources 溯源清单")

    um = manifest.get("upstream_mirror")
    if isinstance(um, dict) and um.get("commit"):
        validate_commit_sha(str(um["commit"]), field="upstream_mirror.commit")

    repos = manifest.get("repos")
    if isinstance(repos, list):
        for r_idx, r_item in enumerate(repos):
            if isinstance(r_item, dict) and r_item.get("commit"):
                validate_commit_sha(str(r_item["commit"]), field=f"repos[{r_idx}].commit")

    if isinstance(sources, list):
        for idx, item in enumerate(sources):
            if not isinstance(item, dict) or not (item.get("url") or item.get("local_path")):
                raise ComplianceError(f"sources[{idx}] 缺少 url 或 local_path")
            if not str(item.get("name") or "").strip():
                raise ComplianceError(f"sources[{idx}] 缺少 name")
            validate_rel_path(str(item["name"]))
            if item.get("url"):
                validate_https_url(str(item["url"]))
            if item.get("local_path"):
                lp = str(item["local_path"])
                validate_rel_path(lp)
                if not lp.startswith("data/"):
                    raise ComplianceError(f"sources[{idx}].local_path 必须位于受隔离的 data/ 目录内: {lp!r}")
            if item.get("commit"):
                validate_commit_sha(str(item["commit"]), field=f"sources[{idx}].commit")
            item_lic = str(item.get("license") or lic).strip()
            _check_license_token(item_lic, mode=mode, context=f"sources[{idx}]")

    if "author_grant" in manifest or manifest.get("own") is True:
        raise ComplianceError("禁止使用合成 author_grant 或外部 own=true 绕过许可证门禁")

    review = manifest.get("review")
    if review is not None:
        if not isinstance(review, dict):
            raise ComplianceError("review 字段必须为对象")
        use = str(review.get("use") or "").strip()
        if use not in {"adapt-with-attribution", "approach-only", "mixed"}:
            raise ComplianceError(f"review.use 非法: {use!r}")
        if mode == "pack" and use == "approach-only":
            raise ComplianceError("mode=pack 不允许使用 review.use='approach-only'")
        if not str(review.get("by") or "").strip() or not str(review.get("at") or "").strip():
            raise ComplianceError("review 必须声明人工审核人 (by) 与日期 (at)")

    for q_field in ("query_filters", "clinicaltrials_queries"):
        q_list = manifest.get(q_field)
        if isinstance(q_list, list):
            for idx, q_item in enumerate(q_list):
                if isinstance(q_item, dict) and q_item.get("url"):
                    validate_https_url(str(q_item["url"]))


def _load_do_not_contact(corpora_root: Path) -> set[str]:
    dnc_path = corpora_root / "do-not-contact.json"
    if not dnc_path.is_file():
        return set()
    raw = json.loads(dnc_path.read_text(encoding="utf-8"))
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ComplianceError("do-not-contact.json 格式错误：entries 必须为数组")
    blocked: set[str] = set()
    for item in entries:
        if isinstance(item, str) and item.strip():
            blocked.add(item.strip().lower())
        elif isinstance(item, dict):
            for key in ("owner", "repo", "target", "domain"):
                val = str(item.get(key) or "").strip().lower()
                if val:
                    blocked.add(val)
    return blocked


def audit_corpora_dir(corpora_dir: str | Path) -> list[dict[str, Any]]:
    """扫描并校验 corpora/*/manifest.json，任一不合规则直接抛出 ComplianceError。"""
    root = Path(corpora_dir)
    if not root.is_dir():
        raise ComplianceError(f"语料目录不存在: {root}")

    blocked_targets = _load_do_not_contact(root)
    results: list[dict[str, Any]] = []
    manifests = sorted(root.glob("*/manifest.json"))
    if not manifests:
        raise ComplianceError(f"未在 {root} 下发现任何 manifest.json")

    for mf_path in manifests:
        raw_text = mf_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        if blocked_targets:
            lower_blob = raw_text.lower()
            for token in blocked_targets:
                if token and token in lower_blob:
                    raise ComplianceError(f"语料 {mf_path.parent.name!r} 命中权利人退出名单 (do-not-contact): {token!r}")
        validate_manifest(data)
        if data.get("slug") != mf_path.parent.name:
            raise ComplianceError(f"目录名 {mf_path.parent.name!r} 与 slug {data.get('slug')!r} 不一致")
        results.append(
            {
                "slug": data["slug"],
                "title": data["title"],
                "mode": data["mode"],
                "license": data["license"],
                "manifest_path": str(mf_path),
            }
        )
    return results
