"""VeriCorpus: licence-audited Chinese/SEC/clinical reference corpora, coordinate PDF table reconstruction, and bilingual retrieval benchmarks for XERJ and Elasticsearch-compatible engines."""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "0.1.0"

_SUBMODULES = frozenset(
    {
        "cn_reader_pack",
        "compliance",
        "eval_e2e_rag",
        "eval_hub",
        "eval_primary_weekly",
        "fetchers",
        "financial_10y",
        "ipo_prospectus",
        "pdf_table_fix",
        "query_cn",
        "science_packs",
    }
)

_SYMBOL_TO_MODULE: dict[str, str] = {
    "PACK_ALLOWED_LICENSES": "compliance",
    "RECIPE_ALLOWED_LICENSES": "compliance",
    "ComplianceError": "compliance",
    "audit_corpora_dir": "compliance",
    "validate_manifest": "compliance",
    "DEFAULT_HELDOUT_TICKERS": "cn_reader_pack",
    "build_sec_benchmark_pack": "cn_reader_pack",
    "get_sec_user_agent": "financial_10y",
    "normalize_cell": "pdf_table_fix",
    "analyze_query": "query_cn",
    "build_search_body": "query_cn",
    "search_index": "query_cn",
}

__all__ = [
    "__version__",
    *_SYMBOL_TO_MODULE.keys(),
    *sorted(_SUBMODULES),
]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute loader so stdlib imports never trigger optional dependencies."""
    if name in _SUBMODULES:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod
    target_mod = _SYMBOL_TO_MODULE.get(name)
    if target_mod is not None:
        mod = importlib.import_module(f".{target_mod}", __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
