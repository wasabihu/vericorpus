# VeriCorpus Architecture & Engineering Philosophy Charter

> [!IMPORTANT]
> **MANDATORY FIRST-PRINCIPLES GATE**: ALL future feature design, refactoring, corpus onboarding, benchmark construction, CI pipeline work, and public releases across `wasabihu/vericorpus` and its companion `corpus-*` repositories **MUST** first check against this Charter and the four first-principles methodologies distilled from [`xerj-org`](https://github.com/xerj-org/xerj)'s production search and Corpus Hub engineering (`main` + `corpus-hub`). No architectural change, dependency addition, manifest update, or public release may proceed if it violates any boundary below.

> **Independent Project Notice**: VeriCorpus (`wasabihu/vericorpus`) is an independent Apache-2.0 open-source toolkit and benchmark suite built for XERJ and Elasticsearch-compatible retrieval engines. It is not affiliated with, sponsored by, or endorsed by The XERJ Authors.

---

## Why This Charter Exists

High-velocity retrieval and corpus engineering fails silently when code, mutable data, copyleft dependencies, unverified machine patches, and restricted texts share a single trust boundary. Left unchecked:

1. Build scripts inside data repositories get indexed alongside domain prose, polluting symbol tables (`defs.jsonl`) and skewing lexical rankings.
2. High-churn manifest updates and automated backfill logs drown `git blame` on `main` and starve heavy CI runners.
3. A single top-level `AGPL-3.0` PDF parser (`pymupdf`) infects downstream `Apache-2.0` callers that only needed pure-Python query expansion or license validation.
4. Network timeouts or unmounted search indices get silently folded into factual `"ABSENT"` verdicts, turning operational outages into false claims.
5. Plausible-looking AI patches land without watched-fail regression tests, or leak restricted raw disclosures into public evaluation JSONs.

VeriCorpus prevents all five failure modes structurally through **four non-negotiable engineering pillars**.

---

## Pillar 1 — Repository Taxonomy & Dual-Branch Topology

### 1.1 Converged Toolkit Monorepo vs. Domain-Sharded Pure-Text `corpus-*` Repositories

Our public ecosystem strictly separates **executable tooling** from **immutable pure-text reference corpora**:

| Repository Tier | Canonical Examples | GitHub `language` | License Boundary | Strict Architectural Role |
|---|---|---|---|---|
| **Converged Engine & Toolkit Repo** | `wasabihu/vericorpus` | `Python` | `Apache-2.0` (unmodified 202-line SPDX text + `NOTICE`) | Houses all retrieval adapters (`query_cn.py`), compliance gates (`compliance.py`), optional PDF geometry repair (`pdf_table_fix.py`), corpus splitters/builders (`scripts/`), and reproducible evaluation harnesses (`eval_*.py`). Never splits adapters, schemas, or evaluators into fragmented micro-repos. |
| **Domain-Sharded Pure-Text Corpora** | `wasabihu/corpus-cn-statutes`, `wasabihu/corpus-clinical-trials` | `None` (**zero code**) | Pure statutory public domain (`CC0-1.0`) or audited open-access (`CC-BY-4.0` + `LICENSES/`) | Contains **only** domain-sharded `.md` documents, `MANIFEST.tsv` (path, metadata, byte size, `sha256`), `LICENSE`, and `README.md`. **Zero `.py`, `.sh`, or build scripts** may live inside `corpus-*` trees so `xerj autoindex` and `xerj corpus index` never ingest build code into sidecar `code` indices or pollute `defs.jsonl`. |
| **Detached Release Artifacts** | GitHub Immutable Releases (`pack-<slug>-<pin8>`) | Non-Git binary assets | Declared in embedded `pack.json` + `LICENSES_AUDIT.md` | Pre-indexed `.hubpack.tar.zst` / `.zip` bundles and large snapshots live **exclusively** in GitHub Releases — never committed to Git history. |

#### Domain-First Sharding, Immutable `-v2` Evolution & Byte Conservation
1. **Group by Problem Domain, Never by Language or File Format**: A corpus that mixes unrelated domains retrieves like a search engine with no query. Split corpora by concrete problem domain and legal authority (e.g., PRC civil/commercial & capital-market statutes in `corpus-cn-statutes`; quantitative clinical trial outcomes in `corpus-clinical-trials`), intentionally omitting noisy boilerplate annexes that dilute BM25 precision. If referencing an external mixed repository, declare explicit sparse `"paths"` (`<= 32` entries) so only pure domain text is indexed.
2. **Immutable `-v2` / `-v3` Evolution (Never Rewrite Pinned History)**: Once a `corpus-*` commit SHA is referenced by an upstream Hub manifest, release pack, or benchmark report, **never `force-push` or rewrite its history** when re-chunking. When retrieval testing reveals chunk-granularity defects (e.g., long documents burying operative clauses), derive a new immutable `-v2` repository from the pinned v1 SHA.
3. **100% Byte-Conservation Invariant on Structural Splitting**: Every splitter (such as statutory provision splitting across `第X条`, `第X条之一`, numbered accounting rules, and supplementary provisions) must inject a deterministic single-line provenance breadcrumb header per chunk and assert in automated tests that **stripping the provenance header and concatenating all emitted chunks reproduces 100% of the source text (`reconstructed == original`)** with zero dropped clauses or altered numerals.
4. **Tombstone Contract for Retired Sources (`withdrawn` Manifests)**: When an upstream source goes `HTTP 404` or fails re-audit, never silently delete `corpora/<slug>/manifest.json`. Retain the manifest file as a tombstone with `"withdrawn": "<reason and migration target>"` and empty `"sources": []`, validated bidirectionally against the registry ledger so downstream `--from` callers receive actionable migration guidance.

### 1.2 Dual-Branch Physical Separation (`main` vs. `corpus-registry`)

To protect engineering history and CI throughput as corpus coverage scales:

- **`main` (Engine, Adapters & Strict Harnesses)**: Holds `src/vericorpus/`, `scripts/`, `tests/`, `docs/`, and core bootstrap manifests. Every push to `main` runs the full unit, negative-control, and release-audit suite with `cancel-in-progress: false`. Commit bodies on `main` form the permanent engineering log (`git blame` must explain root causes, invariants, and before/after measurements — never automated data churn).
- **`corpus-registry` (High-Churn Manifests, Catalogues & Backfill Reports)**: High-frequency SEC/exchange filing catalogues, automated `pin8` repin PRs, candidate license ledgers, and append-only backfill `REPORT.md` / `rows.jsonl` artifacts belong on `corpus-registry`. Pull requests targeting `corpus-registry` run a `<2s` pure-stdlib schema/compliance gate plus a `>5 MiB` binary and private-key blocker — never burning multi-platform test matrices on metadata updates while sharing repository-scoped Release permissions and signing secrets.

### 1.3 GitHub Immutable Releases & Verify-Before-Extract Detached Signatures

- **Content-Addressed Release Naming**: Pre-built corpus packs publish under `pack-<slug>-<pin8>` (where `pin8` is the first 8 hex chars of the 40-hex source commit SHA or canonical sorted-record SHA-256).
- **Protect `/releases/latest`**: Every data pack release **must** pass `--prerelease --latest=false` so high-frequency corpus updates never hijack the repository's latest software release pointer.
- **Detached `.sig` Outside the Archive (Verify-Before-Extract)**: Archive parsers (`tar`, `zstd`, `zip`) are complex untrusted-input attack surfaces. `scripts/build_hubpacks.py` must emit `<slug>-<pin8>.hubpack.tar.zst` (or `.zip`) alongside **external, detached `<slug>-SHA256SUMS` and `<slug>-SHA256SUMS.sig`** files outside the archive. Clients verify SHA-256 and Ed25519 signatures *before* passing a single byte to any decompressor; tampered downloads abort with zero extracted bytes on disk.
- **Signing Key Domain Isolation & Secret Hygiene**: Separate global catalogue signing keys from per-pack signing seeds. Write signing seeds only to `umask 077` temporary files with `trap rm EXIT` and immediately `unset` secret environment variables before invoking any parser over external corpus files; scrub secret-shaped patterns (`ghp_*`, `github_pat_*`, 64-hex seeds) from all backfill logs.

---

## Pillar 2 — Zero-Dependency Stdlib Control Plane, State-Driven Self-Healing CI & Defense-in-Depth

### 2.1 `dependencies = []` Pure-Stdlib Control Plane & Strict Copyleft Isolation

1. **Zero-Dependency Core (`pyproject.toml`)**: Core `vericorpus` (`compliance`, `query_cn`, `fetchers`, `eval_*`, `scripts/audit_public_release.py`, `scripts/build_hubpacks.py`) runs exclusively on the **Python 3.12+ standard library** (`json`, `pathlib`, `re`, `hashlib`, `urllib.request`, `tomllib`, `unittest`) plus native Runner tools (`openssl pkeyutl -rawin` with RFC 8410 fixed PKCS#8/SPKI prefixes for Ed25519). `dependencies = []` eliminates PyPI outage fragility and transitive supply-chain poisoning on the control plane.
2. **Optional `[pdf]` Isolation for `AGPL-3.0` (`PyMuPDF`)**: `pymupdf>=1.24.0` (`AGPL-3.0`) is strictly isolated under `[project.optional-dependencies] pdf = ["pymupdf>=1.24.0"]`. `src/vericorpus/__init__.py` enforces PEP 562 lazy `def __getattr__(name: str)` and `src/vericorpus/pdf_table_fix.py` lazy-imports `pymupdf` only inside PDF-opening functions (keeping pure-stdlib `normalize_cell` and `repair_hkex_cmap` 100% dependency-free). Every CI run proves core imports succeed with `sys.modules["pymupdf"] = None`.
3. **Hard CI Timeouts, Read-Only Permissions & Parser `_self_check()`**: Every GitHub Actions job declares `permissions: contents: read`, pins third-party Actions to **40-hex commit SHAs**, and sets an explicit `timeout-minutes` ceiling (never leaving GitHub's 360-minute default to wedge serial concurrency groups). Every custom stdlib validator or release auditor (`scripts/audit_public_release.py`) runs an embedded `_self_check()` on startup so regex or parser regressions fail closed immediately rather than silently passing bad inputs.

### 2.2 State-Driven Idempotent Reconciliation & Operational vs. Factual State Separation

1. **Reconcile `plan()` Over `git diff`**: Never trigger pack publication from push diffs, which permanently drop work when CI jobs time out, cancel, or get superseded. `plan(desired_corpora, live_releases)` compares desired `pin8` pins against live non-Draft GitHub Releases on every run:
   - Upload artifacts to a `--draft` Release first;
   - Re-download exact bytes from the Draft Release (`cmp` byte-identity check) into a clean node and clean temporary directory for end-to-end retrieval verification;
   - Promote via `gh release edit --draft=false` (automatically falling back to `-r2`, `-r3` tags if a prior deleted release burned an immutable tag).
2. **Anti-Delisting Guard (`live` / `none` / `unknown` 3-State Check)**: Before publishing an updated `catalogue.json`, compare against the currently live catalogue: no active `live` corpus may disappear. Strictly distinguish `live` (HTTP 200 + valid JSON + verified signature), `none` (genuine HTTP 404 on initial bootstrap), and `unknown` (HTTP 200 HTML fallback page, 5xx, timeout, or bad signature). Encountering `unknown` fails closed and aborts deployment.
3. **Blue/Green Index Mounting & 3-State Count Safety**: When mounting or refreshing search indices on `:9200`, index into a fresh timestamped generation prefix (`<slug>-b<YYYYMMDD>-*`), verify `_count > 0` and probe-query hits, atomically swap the routing state file via `os.replace`, and only then delete retired prefixes by explicit name (never wildcard `DELETE *` or `_all`). Node document counts have **three states** — `integer >= 0`, `404 (true zero)`, and `Unknown (timeout / 5xx / malformed JSON)`. **`Unknown` is NEVER `0`** and never authorizes deleting an existing index or advancing a durable pointer.
4. **`/_facts`-Style Dual-State Verification & Explicit Operational Error Codes**: Structured verification pipelines must separate unchecked extractor/model output (`raw_status`, `raw_answer`) from deterministically verified output (`final_status`, `final_answer`). When the search node is unreachable, times out, or has `0` live target indices mounted, return an **explicit operational error** (`HTTP 503 INDEX_NOT_MOUNTED` / `504 ASK_DEADLINE` / CLI exit code `3`) — **never fold operational unavailability into factual `"ABSENT"`, `"NOT_FOUND"`, or `"UNKNOWN"`**.

### 2.3 `pathgate` Defense-in-Depth on Untrusted Inputs

Treat every manifest field, corpus slug, relative file path, URL, and CLI argument as attacker-controlled input:

| Threat Vector | Mandatory `pathgate` Control (`compliance.py`, `fetchers.py`, `scripts/`) |
|---|---|
| **Path traversal & workspace clobbering** | Enforce `valid_slug` (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`; reject `_` which autoindex rewrites to `-`, causing silent empty queries) and `valid_rel_path`: reject `..`, `.`, leading `/` or `\`, Windows drive prefixes (`C:`), control chars, NUL bytes, path lengths `> 240B`, and symlinks resolving outside the corpus root. Error out on leading `/` rather than stripping it. |
| **CLI flag & Git pathspec injection** | Reject any path component starting with `-` (prevents flag injection into `git` / archive subprocesses), containing `:` (prevents `:(magic)` or `<sha>:<path>` injection), or containing `* ? [ ] ! #` globs. Cap sparse `"paths"` lists at `<= 32` entries. |
| **SSRF & `ext::` protocol RCE** | `_safe_urlopen()` permits **only** `https://` URLs with validated hostnames (blocking `file://`, `ftp://`, `gopher://`, custom schemes, and loopback/link-local metadata targets unless explicitly injected in isolated local unit tests). All `git` subprocesses set `GIT_ALLOW_PROTOCOL=https` and `GIT_TERMINAL_PROMPT=0`. |
| **Mutable short-SHA drift** | Require **40-character lowercase hex Commit SHAs** (`^[0-9a-f]{40}$`) on all pinned Git sources; reject 7/12-char short SHAs that fail shallow fetches or silently drift. |

### 2.4 Operational Negative Controls, Durable State & Honest Benchmarks

1. **Dual-Composition Negative Controls for Runnable Docs & Scripts**: Every documented command sequence, build script, and release gate is treated as executable code. Artifact verification and consumption must happen inside the **same atomic execution block** (never hand off "verified" status via a mutable staging path). Every negative control (bad SHA-256, missing `.sig`, restricted disclosure frontmatter, or attacker-precreated digest directory) must fail closed (`exit != 0`, zero bytes extracted/published/served) under **two mandatory compositions**:
   - **(a)** Discarding the failing block's exit status; and
   - **(b)** Appending and executing the next documented command block.
2. **Durable State vs. Invocation State**: Committed manifests, `MANIFEST.tsv` digests, and sealed snapshots are durable authority; in-memory counters, wall clocks, and per-run processed counts are invocation state. A **zero-work resume** (rerunning an interrupted or unchanged job) must never overwrite durable historical totals or timestamps with `0` or current wall time.
3. **Watched-Fail Regression Gate & `link-the-harness-or-drop-the-number`**: Every bug fix requires a deterministic test watched failing *before* the fix and passing *after* (`0 failed` hard gate — never add known-failure allowlists or weaken assertions to match broken behavior). All retrieval benchmarks (`eval_hub.py`, `eval_primary_weekly.py`, `eval_e2e_rag.py`) must run against a clean node with `XERJ_DISABLE_QUERY_CACHE=1` (verifying `xerj_query_cache_hits == 0`), report exact environment + commit SHA + honest failure breakdowns (`R / W / N`, `Net = R - 2W`, paired bootstrap 95% CI), and obey **`link-the-harness-or-drop-the-number`**: any metric without a one-command reproducible harness in the repository is deleted from documentation.

---

## Pillar 3 — De-SaaSed CLA, Dual-Layer Licensing & AI-Era Contribution Protocol

### 3.1 `.contributors` 1-Line PR CLA & Safe `pull_request_target` Exemptions

1. **Zero-SaaS Cryptographic Accountability**: Contributors retain copyright and grant an Apache-ICLA-v2.0-equivalent license by opening a pull request from their own GitHub account appending their ASCII GitHub username to `.contributors`. The authenticated GitHub PR history is the permanent legal audit trail — zero third-party CLA SaaS dependencies or external privacy databases.
2. **Deadlock-Free Self-CLA & `<= 25`-Line Field-Report Exemption**: Any `pull_request_target` workflow verifying CLA status **must checkout `pull_request.base.sha` only — never untrusted PR head code** — and inspect changed paths via the GitHub Compare API (`base_sha...head_sha`, failing closed if changed files `>= 300` or if renames disguise modifications, and enforcing strict ASCII login matching to block Unicode homoglyphs such as `U+212A` `K`). Two narrow diffs auto-pass without prior `.contributors` listing:
   - **Self-CLA PR**: Modifies only `.contributors`, preserves all existing entries as a multiset, and appends solely the PR author's own ASCII login.
   - **Agent Field Report PR**: Adds a single new Markdown file `field-reports/YYYY-MM-DD-<short-slug>.md` (`<= 25` lines ceiling, excluding `README.md` or subdirectories, zero code/doc edits in the diff) so external AI agents can report retrieval friction in 30 seconds without ceremony.
3. **Co-Author CLA Enforcement**: Automated checks inspect every commit message trailer in a PR; unverified or unsigned human co-authors fail the gate.

### 3.2 Strict AI Provenance, Human Accountability & Anti-DoS Discipline

Full operational rules for coding agents live in [`.github/AI_CONTRIBUTIONS.md`](../.github/AI_CONTRIBUTIONS.md):

- **ZERO `Co-Authored-By` AI Trailers**: Never attach AI model `Co-Authored-By` trailers to commits or pull requests. Commit authorship and PR accounts exist to record **which human can answer for a line of code in `git blame` months later**; a language model is not a legal entity and cannot answer. Disclose AI assistance in line 1 of the PR body and in commit prose instead.
- **GitHub Privacy Noreply Email Mandate**: All maintainer and automated commits must use GitHub's canonical noreply address (`<id>+<login>@users.noreply.github.com`, e.g., `973168+wasabihu@users.noreply.github.com`) — never personal email addresses or synthetic `.local` domains.
- **Mandatory Line-1 `Provenance` Split (`Verified` / `Assumed` / `Not run`)**: Machine-authored patches fail differently from human ones (more likely locally plausible yet globally wrong). Every AI-assisted PR must state the agent/model on line 1 and partition every claim into `Verified` (exact commands run + observed output), `Assumed` (untested assumptions + falsification criteria), and `Not run` (skipped suites + reason).
- **Three-Way Decision Tree & Anti-Bulk-Lint-DoS Rule**:
  1. *Reproducible defect, unfixed* -> file **1** issue with wire-level reproduction;
  2. *Reproducible defect, patched and watched fail-then-pass locally* -> open **1** PR;
  3. *Unrun suspicion, style-only churn, prose rewording, or 40 static/LLM sweep findings* -> **send nothing** (a batch of unverified findings is a denial-of-service attack on maintainer attention; if a sweep uncovers systemic candidates, open at most **1** summary issue asking whether maintainers want the list).

### 3.3 Dual-Layer License Gate, Zero-Restricted-Text Eval Schema, G7 Blind Suite & Rightsholder Lock

1. **Dual-Layer License Gate (`license` + Human `review` Block)**: Automated SPDX detection fails on multi-licensed repos, custom statutory notices, and mixed trees. Every `corpora/<slug>/manifest.json` must pair machine metadata with a human-signed `review` object (`{spdx, use, by, at, note}`) where `use` is strictly one of:
   - `adapt-with-attribution`: Public domain (`Public-Domain-CN-Law`, `SEC-Public-Filing`, `CC0-1.0`) or permissive (`Apache-2.0`, `MIT`, `BSD`, `CC-BY-4.0`) — eligible for `mode: "pack"` redistribution with full attribution;
   - `approach-only`: Copyleft, source-available, or exchange-restricted disclosures (`CNINFO`, `HKEX`, `KRX`, `All Rights Reserved`) — restricted strictly to `mode: "recipe"` (local fetch into `.gitignore`-isolated `data/` only; never redistributed in packs);
   - `mixed`: Permissive core with restricted paths — requires explicit sparse `"paths"` filtering and per-file header audit.
   Synthetic `author_grant` fields are banned, and external manifests cannot set `"own": true` to suppress license warnings.
2. **`CC-BY-4.0` Section 3(a) & Zero-Restricted-Text JSON Schema Gate**:
   - Every `CC-BY-4.0` document and evaluation item (`evals/*.json`) must carry resolved real author names (**zero** `"See original publication"` placeholders), canonical license URI (`https://creativecommons.org/licenses/by/4.0/`), an explicit `Adaptation Notice` documenting XML/HTML-to-Markdown table conversion, and `100%` verified character-slice invariants (`oracle_document[start:end] == quote`).
   - **Zero-Restricted-Text Public Eval Gate**: `scripts/audit_public_release.py` enforces at the JSON schema level that public `evals/*.json` files contain **zero** verbatim snippets or `oracle_document` bodies from `All Rights Reserved` or `CNINFO/HKEX/KRX-Public-Disclosure` sources. Evaluations over restricted `recipe` filings publish only `{source_url, sha256, char_span, numeric_assertion}` for local hydration via `fetchers.py`.
3. **PROGRAM-100 Gates (G1–G7) & Pre-Registered 5-Question G7 Blind Suite**: Every new `pack` corpus must pass:
   - **G1** (Domain utility statement) -> **G2** (Chunk granularity matched to query unit) -> **G3** (Anti-memorization check: no Retrieval Theatre over basic facts LLMs already memorize) -> **G4** (Human `review` block) -> **G5** (40-hex SHA pin) -> **G6** (`compliance.py` + `audit_public_release.py` zero violations) -> **G7** (**Pre-registered 5-question blind retrieval suite** `evals/g7-<slug>-YYYY-MM.json`, written from raw corpus files *before* running any search query; requires Top-5 relevant hit median `>= 3`; failed G7 rounds are preserved verbatim in JSON and fixed by re-chunking the corpus, never by softening the questions).
4. **`corpora/do-not-contact.json` & Non-Bypassable Branch Protection**: Rightsholder opt-out requests (`"no-contact"` or `"no-include"`, normalized across lowercase owner, login, and repo aliases) are recorded permanently in `corpora/do-not-contact.json` and enforced by `compliance.py`. Repository Branch Protection marks the stdlib compliance workflow as a **Required Status Check (including for administrators)** so automated `GITHUB_TOKEN` PRs (which do not trigger `pull_request` workflows by default) can never merge unvalidated state.

---

## Pillar 4 — Mandatory 10-Item Pre-Design & Pre-Release Checklist

Every developer and AI Agent **MUST** verify all 10 items below before proposing a design, opening a pull request, onboarding a corpus, or cutting a public release:

- [ ] **1. Taxonomy & Pure-Text Separation**: Does code stay in `vericorpus` while companion `corpus-*` repos remain `language=None` (`0` `.py`/`.sh` files) with `100%` `reconstructed == original` byte conservation and `MANIFEST.tsv` SHA-256 parity?
- [ ] **2. Dual-Branch & Release Hygiene**: Are high-churn catalogues/backfill logs routed to `corpus-registry` (keeping `main` history clean), and are binary archives published exclusively to GitHub Releases with `--prerelease --latest=false` and **detached `.sig` + `SHA256SUMS` outside the archive**?
- [ ] **3. Zero-Dependency Stdlib & `AGPL-3.0` Isolation**: Does `pyproject.toml` keep `dependencies = []` with `pymupdf` isolated under `[pdf]`, and does `PYTHONPATH=src python3 -c 'import sys; sys.modules["pymupdf"]=None; import vericorpus; from vericorpus import compliance, query_cn, pdf_table_fix'` exit `0`?
- [ ] **4. `pathgate`, HTTPS-Only & 40-Hex SHA Enforcement**: Are all slugs, relative paths, URLs, and Git pins validated against `..`, leading `/` or `-`, `:`, globs, symlinks, non-`https://` schemes (`file://` blocked), and short `<40`-hex SHAs?
- [ ] **5. State-Driven Idempotency & Operational Error Separation**: Do pipelines reconcile desired `pin8` against live state (never `git diff`), treat `:9200` timeouts/5xx as `Unknown` (never `0` count or factual `"ABSENT"`), and preserve durable state on zero-work resume?
- [ ] **6. Watched-Fail Regression Test & Dual Negative Controls**: Did you watch a deterministic test fail before your change and pass after (`0 failed`), and do runnable scripts/docs fail closed with zero side effects both when exit status is discarded and when the next block is appended?
- [ ] **7. Honest Uncached Benchmarks**: Were all reported metrics produced with `XERJ_DISABLE_QUERY_CACHE=1` (`xerj_query_cache_hits == 0`), paired with honest failure breakdowns and a one-command repository harness (`link-the-harness-or-drop-the-number`)?
- [ ] **8. Dual-Layer License, `CC-BY-4.0` Sec. 3(a) & Zero-Restricted-Text Gate**: Does every manifest carry a human `review` block, every `CC-BY-4.0` item carry real authors + license URI + `Adaptation Notice` + verified `[start:end]` offsets, and every `evals/*.json` contain zero `All Rights Reserved` or `CNINFO/HKEX/KRX` restricted prose?
- [ ] **9. G7 Blind Suite & Rightsholder Sovereignty**: For any new or re-chunked `pack` corpus, is there a pre-registered 5-question G7 blind retrieval file achieving Top-5 median `>= 3`, and does `corpora/do-not-contact.json` pass with zero regression?
- [ ] **10. Public Hygiene & AI Provenance Audit**: Does `python3 scripts/audit_public_release.py` report `Violations: 0` (zero workstation home paths, zero API keys, zero private index names, zero closed-source identifiers), are commits authored under `<id>+<login>@users.noreply.github.com` with **zero `Co-Authored-By` AI trailers**, and does the PR open with the `Provenance` (`Verified` / `Assumed` / `Not run`) block?

---

**Related Documents**: [AGENTS.md](../AGENTS.md) · [.github/AI_CONTRIBUTIONS.md](../.github/AI_CONTRIBUTIONS.md) · [LICENSES_AUDIT.md](../LICENSES_AUDIT.md) · [LICENSE](../LICENSE)
