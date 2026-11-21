# Sending Contributions Upstream — Protocol for AI Coding Agents & Maintainers

> [!IMPORTANT]
> **MANDATORY FIRST-PRINCIPLES GATE**: ALL future feature design, refactoring, corpus onboarding, CI pipeline work, and public releases in `wasabihu/vericorpus` and its companion `corpus-*` repositories **MUST** first check against [`docs/ENGINEERING_PHILOSOPHY.md`](../docs/ENGINEERING_PHILOSOPHY.md), [`AGENTS.md`](../AGENTS.md), and the four first-principles methodologies distilled from [`xerj-org`](https://github.com/xerj-org/xerj). Every contribution — human-written or AI-assisted — is held to the exact same engineering and compliance bar, plus explicit machine provenance and human accountability.

Most agents reading this file are working in a downstream project where `vericorpus` or one of its companion corpora (`wasabihu/corpus-cn-statutes`, `wasabihu/corpus-clinical-trials`) is a dependency. When an expansion rule misses a statutory alias, a table parser drops a decimal, or a manifest check fails unexpectedly, working around it locally lets the defect survive for the next user. This protocol defines **when to send a field report, an issue, a pull request — and when the right action is to send nothing**.

---

## 1. The Three-Way Contribution Decision Tree (Anti-DoS Mandate)

Maintainer review bandwidth is the scarcest resource in an open-source project. Before opening anything, verify the issue against the current `main` branch in a clean environment, search open and closed issues (`gh search issues --repo wasabihu/vericorpus "<terms>"`), and follow this deterministic decision rule:

1. **A reproducible defect you have NOT fixed -> Open 1 Issue**:
   - Include the exact copy-pasteable command (`python3 -c ...` or `curl` against a clean temporary node), full verbatim observed output, expected output with the invariant or statutory/accounting ground truth it violates, and Python / OS / `xerj --version` metadata.
   - **One defect per issue** so partial fixes never close live bugs.
2. **A reproducible defect you patched AND watched fail-then-pass locally -> Open 1 Pull Request**:
   - Requires a deterministic test you ran against the *unfixed* code (watching it fail for the exact defect) and ran again after the fix (`0 failed` across the suite).
   - Commit message body must explain **motivation, root cause, and measured evidence** — never paraphrase the diff.
3. **An unrun suspicion, style-only churn, prose polish, or bulk linter/LLM sweep -> Send Nothing**:
   - Compiling or syntax-checking is not running. Speculative fixes, import reordering, comment re-wrapping, synonym rewording, and unmotivated refactors pollute `git blame` and waste review cycles.
   - **Anti-Bulk-Sweep DoS Rule**: Filing 40 unverified findings from a static analyzer or an LLM pass over the repository is not 40 contributions — it is a denial-of-service attack on maintainer attention. If you ran a batch audit, open **at most one** summary issue naming the tool and high-level categories, and wait for a maintainer to request specifics.

### Low-Friction Baseline: `<= 25`-Line Agent Field Reports
If you used `vericorpus` or a companion corpus in a real retrieval task, you may submit a single-file experience report at `field-reports/YYYY-MM-DD-<short-slug>.md`:
- **Hard ceiling**: `25` lines maximum, one file per session, zero other files in the diff, and **zero raw user query text** (report query shapes such as `statutory penalty lookup <law> <article>` and corpus `pin8` only).
- Honest friction notes ("Chinese traditional/simplified accounting alias missed row X") are far more valuable than generic praise; two independent friction reports on the same pattern graduate directly into a regression test.

---

## 2. Provenance, Human Accountability & Privacy Email Rules

### 2.1 Mandatory Line-1 `Provenance` Block (`Verified` / `Assumed` / `Not run`)
Machine-authored patches fail differently from human patches: they are systematically more likely to look locally clean while violating a repository-wide invariant (such as lazy `AGPL-3.0` isolation, 3-state `:9200` error handling, or zero-restricted-text eval schemas). Every AI-assisted pull request **must** begin on line 1 of the PR body with:

```text
Provenance: Written by an AI coding agent (<model / harness>), run and reviewed by @<github-username>.

Verified — commands executed in this environment and exact output observed:
- PYTHONPATH=src python3 -m unittest discover -s tests -v -> Ran N tests, OK
- PYTHONPATH=src python3 scripts/audit_public_release.py -> PASS (Violations: 0)

Assumed — NOT tested in this environment:
- <explicit assumption, plus what concrete condition would falsify it>

Not run:
- <any benchmark or live-node gate skipped, and why>
```

### 2.2 ZERO `Co-Authored-By` AI Trailers
**Do not add `Co-Authored-By` trailers naming an AI model, bot, or coding assistant to any commit or pull request.**
Git commit authorship and the GitHub account opening a PR form the project's permanent accountability ledger — who signed the CLA and who can answer *"why does this code do that?"* when someone runs `git blame` next year. An AI model is not a legal person and cannot answer. Put AI disclosure in line 1 of the PR body and in commit prose instead.

### 2.3 GitHub Noreply Privacy Email Mandate
All commits must use GitHub's canonical privacy-preserving noreply address (`<id>+<login>@users.noreply.github.com`, e.g., `973168+wasabihu@users.noreply.github.com`) rather than personal email addresses or synthetic `.local` placeholders.

---

## 3. De-SaaSed `.contributors` CLA & Safe `pull_request_target` Architecture

1. **1-Line `.contributors` PR CLA**: Contributors retain copyright and grant an Apache-ICLA-v2.0 license (covering both human-written and AI-assisted contributions under human legal responsibility) by opening a pull request from their own GitHub account appending their ASCII GitHub username to `.contributors`. No external CLA SaaS is used.
2. **Safe `pull_request_target` Verification (Zero Untrusted Code Checkout)**:
   - Any workflow evaluating CLA exemptions under `pull_request_target` **must checkout `pull_request.base.sha` only** — never the untrusted PR head — and inspect changed filenames exclusively through the GitHub Compare API (`base_sha...head_sha`), failing closed if file count `>= 300` (API pagination truncation sentinel) or if file renames disguise edits.
   - **Self-CLA Deadlock Breaker**: A PR modifying *only* `.contributors` that preserves all prior entries as a multiset and adds solely the PR author's own strict-ASCII GitHub username (blocking Unicode case-folding homoglyphs such as `U+212A` `K`) automatically satisfies the CLA status check.
   - **Field-Report CLA Exemption**: A PR adding *only* a single `field-reports/YYYY-MM-DD-<short-slug>.md` file (`<= 25` lines, excluding `README.md` and subdirectories) is automatically CLA-exempt.
   - **Human Co-Author Check**: Every human `Co-authored-by` trailer in a multi-author PR is cross-checked against `.contributors`; unverified human co-authors block merge.

---

## 4. Architectural & Compliance Guardrails Every PR Must Respect

Every contribution is gated against all four project pillars (full specification in [`docs/ENGINEERING_PHILOSOPHY.md`](../docs/ENGINEERING_PHILOSOPHY.md)):

1. **Pillar 1 — Repository Taxonomy & Dual-Branch Topology**:
   - Keep all Python splitters/builders inside `vericorpus/scripts/`; companion `corpus-*` repos (`corpus-cn-statutes`, `corpus-clinical-trials`) stay `language=None` (`0` `.py`/`.sh` files), evolve immutably via `-v2` repos (never rewriting pinned SHAs), enforce `100%` `reconstructed == original` byte conservation on split chunks, and retain `"withdrawn"` manifest tombstones for retired sources.
   - Route core code to `main` and high-churn catalogues/repins/backfill reports to `corpus-registry` (`<2s` stdlib gate). Ship large binary packs exclusively via GitHub Immutable Releases (`pack-<slug>-<pin8>`, `--prerelease --latest=false`) with **detached `.sig` + `SHA256SUMS` outside the archive** for verify-before-extract.
2. **Pillar 2 — Zero-Dependency Stdlib Control Plane, Self-Healing CI & `pathgate`**:
   - Preserve `dependencies = []` in `pyproject.toml`; keep `pymupdf>=1.24.0` (`AGPL-3.0`) strictly optional behind `[pdf]` + PEP 562 lazy `__getattr__` + function-level imports. Pin CI Actions to 40-hex SHAs with `permissions: contents: read` and explicit `timeout-minutes`.
   - Reconcile packs via state-driven `plan()` (desired `pin8` vs. live Releases + Anti-Delisting 3-state guard), mount `:9200` indices blue/green with 3-state count safety (`Unknown` != `0`), and never collapse operational `503 INDEX_NOT_MOUNTED` errors into factual `"ABSENT"`.
   - Enforce `pathgate` across `compliance.py` and `fetchers.py` (reject `..`, leading `/` or `-`, `:`, globs, symlinks, `file://` SSRF; require `https://`, `GIT_ALLOW_PROTOCOL=https`, and 40-hex SHAs).
   - Prove runnable blocks pass dual negative controls (exit code discarded AND next block appended -> zero side effects), benchmark with `XERJ_DISABLE_QUERY_CACHE=1`, and obey **`link-the-harness-or-drop-the-number`**.
3. **Pillar 3 — Dual-Layer License Gate, Zero-Restricted-Text Evals & G7 Blind Suite**:
   - Every `corpora/<slug>/manifest.json` must include a human `review: {spdx, use: adapt-with-attribution | approach-only | mixed, by, at, note}` block (no synthetic `author_grant`, no external `"own": true`).
   - Every `CC-BY-4.0` record in packs or `evals/*.json` must carry real author names (**zero** `"See original publication"`), `https://creativecommons.org/licenses/by/4.0/`, an XML/HTML-to-Markdown `Adaptation Notice`, and verified `doc[start:end] == quote` offsets.
   - Public `evals/*.json` files must contain **zero verbatim prose** from `All Rights Reserved` or `CNINFO/HKEX/KRX-Public-Disclosure` sources (store URL + SHA-256 + char offsets + numeric assertions only).
   - Every new `pack` corpus must pass a **pre-registered 5-question G7 blind retrieval suite** (`Top-5 median >= 3`) and honor `corpora/do-not-contact.json`.

---

## 5. Pillar 4 — Mandatory 10-Item Pre-Submission Checklist

Paste or verify all 10 items before opening or merging any pull request:

- [ ] **1. Pure-Text Corpus Separation**: Zero `.py`/`.sh` files inside `corpus-*` trees (`language=None`); chunk splitters prove `reconstructed == original` byte identity.
- [ ] **2. Branch & Release Hygiene**: High-churn registry data stays on `corpus-registry`; large archives use GitHub Releases (`--prerelease --latest=false`) with **detached `.sig` outside the archive**.
- [ ] **3. Zero-Dependency Stdlib Core**: `dependencies = []` preserved; core imports pass with `sys.modules["pymupdf"] = None`; CI workflows set `timeout-minutes` and 40-hex Action SHAs.
- [ ] **4. `pathgate` & Transport Safety**: Slugs, paths, URLs, and commits reject `..`, leading `/` or `-`, `:`, globs, symlinks, non-`https://` URLs, and `<40`-hex short SHAs.
- [ ] **5. State Reconciliation & Error Fidelity**: Reconcile logic uses live state (not `git diff`); `:9200` timeouts/unmounted indices surface as operational `503` / Exit `3` (never factual `"ABSENT"`).
- [ ] **6. Watched-Fail Test & Negative Controls**: Regression test watched failing before fix and passing after (`0 failed`); operational recipes pass exit-discarded and next-block-appended negative controls.
- [ ] **7. Honest Uncached Numbers**: Every quoted benchmark ran with `XERJ_DISABLE_QUERY_CACHE=1` (`xerj_query_cache_hits == 0`), reports losses honestly, and links a reproducible harness.
- [ ] **8. Dual-Layer License & Eval Schema Gate**: Human `review` block present; `CC-BY-4.0` Section 3(a) authors + URI + `Adaptation Notice` + `[start:end]` spans verified; zero restricted text in `evals/*.json`.
- [ ] **9. G7 Blind Suite & Rightsholder Lock**: New `pack` corpora include a pre-registered 5-question G7 blind suite (`median >= 3`) and pass `corpora/do-not-contact.json`.
- [ ] **10. Public Release Audit & Provenance**: `PYTHONPATH=src python3 scripts/audit_public_release.py` reports `Violations: 0`; commit uses `<id>+<login>@users.noreply.github.com` with **zero `Co-Authored-By` AI trailers**; PR line 1 carries `Provenance` (`Verified` / `Assumed` / `Not run`).

---

## If You Are Sandboxed and Cannot Open a PR Directly

Hand your human operator a ready-to-file summary in your final message (do not leave untracked scratch files in their repo):
1. Exact reproduction commands from a clean temporary directory;
2. Python version, OS, and `xerj --version` (if applicable);
3. Verbatim observed output vs. expected invariant;
4. Unified diff (if patched) plus your `Verified` / `Assumed` split.

**Related**: [AGENTS.md](../AGENTS.md) · [docs/ENGINEERING_PHILOSOPHY.md](../docs/ENGINEERING_PHILOSOPHY.md) · [LICENSES_AUDIT.md](../LICENSES_AUDIT.md) · [LICENSE](../LICENSE)
