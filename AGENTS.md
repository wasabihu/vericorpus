# VeriCorpus — Operational Guide & Charter for AI Agents

> [!IMPORTANT]
> **MANDATORY FIRST-PRINCIPLES GATE**: ALL future feature design, refactoring, corpus onboarding, CI pipeline work, and public releases in `wasabihu/vericorpus` and its companion `corpus-*` repositories **MUST** first check against [`docs/ENGINEERING_PHILOSOPHY.md`](./docs/ENGINEERING_PHILOSOPHY.md), [`.github/AI_CONTRIBUTIONS.md`](./.github/AI_CONTRIBUTIONS.md), and the four first-principles methodologies distilled from [`xerj-org`](https://github.com/xerj-org/xerj) (`main` + `corpus-hub`). Read those rules before editing code, manifests, evaluation suites, or workflows.

**What this project is**: An independent, `Apache-2.0` open-source corpus compliance gate, pure-stdlib Chinese/English retrieval query adapter (`vericorpus.query_cn`), optional geometry-aware PDF table reconstructor (`vericorpus.pdf_table_fix`), and zero-leakage retrieval benchmark suite built for XERJ and Elasticsearch-compatible engines.

**What this project is NOT**: A search engine fork, a scraper for redistributing copyright-restricted filings, or an affiliate of The XERJ Authors (see [`NOTICE`](./NOTICE)). Restricted exchange disclosures (`CNINFO`, `HKEX`, `KRX`) and `All Rights Reserved` web pages are supported strictly as local-only `recipe` workflows inside `.gitignore`-isolated `data/` and are **never** committed or shipped in packs or evaluation JSONs.

---

## The Four Architectural Pillars (Binding Summary)

Full rationale and verification contracts live in [`docs/ENGINEERING_PHILOSOPHY.md`](./docs/ENGINEERING_PHILOSOPHY.md). Every agent working in or against this repository is bound by these four pillars:

### Pillar 1 — Repository Taxonomy & Dual-Branch Topology
- **Converged Toolkit vs. Pure-Text `corpus-*` Shards**: Executable Python code (`src/vericorpus/`, `scripts/`, `tests/`) lives exclusively in `wasabihu/vericorpus`. Companion domain-sharded repositories (`wasabihu/corpus-cn-statutes`, `wasabihu/corpus-clinical-trials`) must remain **100% pure text (`language=None`, zero `.py`/`.sh` build scripts)** so `xerj autoindex` / `xerj corpus index` never pollutes `code` indices or `defs.jsonl`.
- **Immutable `-v2` Evolution, Byte Conservation & Tombstones**: Group corpora by problem domain, never by programming language. Never `force-push` over a downstream-referenced `corpus-*` commit SHA; derive `-v2` when changing chunking. Every statutory or structural splitter must assert `strip_breadcrumb(chunks) == original_source` (100% byte/character conservation) in unit tests. Retired sources become `"withdrawn"` tombstones in `corpora/<slug>/manifest.json` rather than silent deletions.
- **Dual-Branch Split (`main` vs. `corpus-registry`)**: `main` holds core code and strict tests with root-cause commit bodies protecting `git blame`. High-churn filing catalogues, automated `pin8` repins, and backfill `REPORT.md` logs belong on `corpus-registry` behind `<2s` stdlib validation so metadata churn never starves heavy CI.
- **Immutable Releases & Detached `.sig` Outside Archives**: Distribute large pre-indexed bundles exclusively via GitHub Immutable Releases (`pack-<slug>-<pin8>`, always with `--prerelease --latest=false`), emitting **detached `<slug>-SHA256SUMS` and `<slug>-SHA256SUMS.sig` outside the archive** for zero-trust **verify-before-extract**.

### Pillar 2 — Zero-Dependency Stdlib Control Plane, State-Driven CI & Defense-in-Depth
- **`dependencies = []` & `AGPL-3.0` Lazy Isolation**: Core `vericorpus` uses **zero third-party runtime dependencies** (pure Python 3.12+ stdlib + native `openssl` Ed25519). `pymupdf>=1.24.0` (`AGPL-3.0`) stays strictly optional under `[project.optional-dependencies] pdf` behind PEP 562 lazy `__getattr__` in `src/vericorpus/__init__.py` and function-scoped imports in `src/vericorpus/pdf_table_fix.py`. Every CI job sets `permissions: contents: read`, an explicit `timeout-minutes` ceiling, and 40-hex SHA-pinned Actions; `scripts/audit_public_release.py` runs `_self_check()` at startup.
- **State-Driven Reconciliation & Operational Error Separation**: Pack publishing reconciles desired `pin8` pins against live GitHub Releases (`plan()` -> `--draft` upload -> re-download byte `cmp` + clean-node Consumer E2E -> promote, guarded by a 3-state `live`/`none`/`unknown` Anti-Delisting check) — never `git diff`. When mounting or querying `:9200`, use blue/green timestamped prefixes (`<slug>-b<YYYYMMDD>-*`) + atomic `os.replace`, treat timeouts/5xx as `Unknown` (never `0` count), emit both `raw_status` and verified `final_status`, and surface missing/unreachable indices as explicit operational errors (`HTTP 503 INDEX_NOT_MOUNTED` / CLI Exit `3`) — **never** as factual `"ABSENT"`.
- **`pathgate` Untrusted-Input Defense**: Validate all slugs (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`, rejecting `_`), relative paths (reject `..`, leading `/` or `\`, drive letters, leading `-` CLI flag injection, `:` pathspec magic, `* ? [ ] ! #` globs, symlinks, control chars), URLs (`https://` allowlist only in `fetchers._safe_urlopen`, blocking `file://` SSRF; `GIT_ALLOW_PROTOCOL=https`), and Git pins (**40-hex full Commit SHAs** only).
- **Operational Negative Controls & Honest Uncached Benchmarks**: Keep artifact verification and consumption inside one atomic block (zero filesystem TOCTOU handoff) and verify negative controls fail closed both when exit status is discarded and when the next block is appended. Run all benchmarks with `XERJ_DISABLE_QUERY_CACHE=1` (`xerj_query_cache_hits == 0`), preserve durable state on zero-work resume, publish honest loss breakdowns, and obey **`link-the-harness-or-drop-the-number`**.

### Pillar 3 — De-SaaSed CLA, Dual-Layer Licensing & AI-Era Contribution Protocol
- **`.contributors` 1-Line PR CLA & Safe Exemptions**: Sign the CLA via a 1-line PR adding your ASCII GitHub username to `.contributors`. Any `pull_request_target` check must checkout **`pull_request.base.sha` only** (Compare API `base...head` with `>= 300` file sentinel + ASCII homoglyph guard), auto-exempting self-CLA PRs and single-file `<= 25`-line `field-reports/YYYY-MM-DD-<slug>.md` PRs.
- **Strict AI Provenance & Accountability**: **Do not add `Co-Authored-By` AI trailers** to commits or PRs — the human GitHub account is the sole accountable author. Use GitHub noreply privacy emails (`<id>+<login>@users.noreply.github.com`), place `Provenance` (`Verified` / `Assumed` / `Not run`) on line 1 of every PR body, and **send nothing** for unrun suspicions, style churn, or bulk linter/LLM sweeps (anti-DoS rule; see [`.github/AI_CONTRIBUTIONS.md`](./.github/AI_CONTRIBUTIONS.md)).
- **Dual-Layer License Gate, Zero-Restricted-Text Evals & G7 Blind Suite**: Every `corpora/<slug>/manifest.json` requires a human `review: {spdx, use: adapt-with-attribution | approach-only | mixed, by, at, note}` block (no synthetic `author_grant`, no external `"own": true`). All `CC-BY-4.0` items require resolved real authors (zero `"See original publication"`), canonical license URI, `Adaptation Notice`, and `100%` valid `doc[start:end] == quote` spans. Public `evals/*.json` files are schema-gated for **zero verbatim restricted prose**. New `pack` corpora require a pre-registered 5-question G7 blind retrieval suite (`Top-5 median >= 3`) and honor `corpora/do-not-contact.json`.

---

## Local Search Node Safety Rules (Shared `:9200` Guardrails)

When running evaluations or indexing against a local XERJ or Elasticsearch node:

1. **Prefer an isolated temporary node** for tests and benchmarks:
   ```sh
   xerj --insecure --data-dir "$(mktemp -d)" &
   ```
2. **Never read, query, or delete non-corpus indices on a shared machine**: Only interact with indices you explicitly created in this session under a dedicated prefix (e.g., `vc-bench-*`). Never issue wildcard `DELETE *` / `_all` or probe unrelated local indices on a user's workstation.
3. **Verify uncached state before quoting retrieval latency or scores**: Export `XERJ_DISABLE_QUERY_CACHE=1` on the node and confirm `xerj_query_cache_hits == 0` on `/v1/metrics`.

---

## Key Verification Commands (Run Before Proposing Any Change)

```sh
# 1. Verify zero-dependency stdlib import isolation (with PyMuPDF blocked)
PYTHONPATH=src python3 -c '
import sys
sys.modules["pymupdf"] = None
import vericorpus
from vericorpus import compliance, query_cn, pdf_table_fix
assert pdf_table_fix.normalize_cell("39.\n9 亿美元") == "39.9 亿美元"
assert pdf_table_fix.repair_hkex_cmap("本尸检报告") == "本尸检报告"
'

# 2. Run full deterministic unit & negative-control test suite
PYTHONPATH=src python3 -m unittest discover -s tests -v

# 3. Run pre-push public release & leak gate (must report Violations: 0)
PYTHONPATH=src python3 scripts/audit_public_release.py
```

---

## Pillar 4 — Mandatory 10-Item Pre-Design & Pre-Release Checklist

Tick off all 10 items before proposing designs, opening a PR, or cutting a release:

1. [ ] **Pure-Text Corpus Boundary**: Companion `corpus-*` repos stay `language=None` (`0` `.py`/`.sh` files) with `reconstructed == original` byte conservation and `MANIFEST.tsv` SHA-256 parity.
2. [ ] **Dual-Branch & Release Topology**: High-churn catalogues/reports target `corpus-registry`; large packs ship only via GitHub Releases (`--prerelease --latest=false`) with **detached `.sig` outside the archive**.
3. [ ] **Stdlib Control Plane**: `pyproject.toml` keeps `dependencies = []`; `pymupdf` (`AGPL-3.0`) remains strictly lazy/optional under `[pdf]`; all CI jobs set `timeout-minutes`, `permissions: contents: read`, and 40-hex Action SHAs.
4. [ ] **`pathgate` & HTTPS Allowlist**: Slugs, paths, URLs, and Git pins reject `..`, leading `/` or `-`, `:`, globs, symlinks, `file://` SSRF, and `<40`-hex short SHAs.
5. [ ] **Idempotent Reconcile & 3-State Safety**: Pipelines reconcile desired `pin8` vs. live Releases; `:9200` timeouts/5xx map to `Unknown` / `503 INDEX_NOT_MOUNTED` (never `0` count or factual `"ABSENT"`).
6. [ ] **Watched-Fail Test & Negative Controls**: Every fix has a test watched failing before and passing after (`0 failed`); runnable blocks keep verify+act atomic and pass both exit-discarded and next-block-appended negative controls.
7. [ ] **Honest Uncached Benchmarks**: Benchmarks run under `XERJ_DISABLE_QUERY_CACHE=1` with honest failure breakdowns and a linked one-command harness (`link-the-harness-or-drop-the-number`).
8. [ ] **Dual-Layer License & Eval Schema Gate**: Every manifest has human `review`; `CC-BY-4.0` items carry real authors + URI + `Adaptation Notice` + valid `[start:end]` spans; `evals/*.json` hold zero restricted verbatim text.
9. [ ] **G7 Pre-Registered Blind Suite & Opt-Out Lock**: New `pack` corpora pass a pre-registered 5-question G7 blind suite (`median >= 3`) and honor `corpora/do-not-contact.json`.
10. [ ] **Public Audit & AI Provenance**: `scripts/audit_public_release.py` reports `Violations: 0`; commits use `<id>+<login>@users.noreply.github.com` with **zero `Co-Authored-By` AI trailers**; PR body starts with `Provenance` (`Verified` / `Assumed` / `Not run`).
