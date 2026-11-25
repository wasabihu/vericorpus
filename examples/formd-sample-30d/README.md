# SEC EDGAR Form D 30-Day Signed Public Sample Pack (`2026-10-06` to `2026-11-04`)

> **Public Data & Non-Advice Notice**: All records are parsed exclusively from public U.S. SEC EDGAR Form D XML notices (`SEC-Public-Filing`, zero paid APIs). Provided strictly for verifiable corpus benchmarking, citation grounding, and research — **not investment, financial, or legal advice**.

## Overview

A deterministic, cryptographically signed 30-calendar-day snapshot of initial U.S. SEC Form D notices (`form_type: "D"`, excluding `D/A` amendments), anchored to exact SEC EDGAR source URLs and XML SHA-256 digests.

| Metric | Value |
|---|---|
| Pack ID | `sec-form-d-sample-30d-2026-10-06-to-2026-11-04` |
| Date Window | `2026-10-06` to `2026-11-04` (`30` calendar days, `21` SEC filing days) |
| Record Count | `3,685` unique Form D filings (`3,577` unique CIKs) |
| Equity / Pooled Fund | `1,744` equity filings · `2,230` pooled investment fund filings |
| Data Privacy Boundary | Entity-level public fields only (excludes `relatedPersonsList` and street addresses) |
| Signing Algorithm | `Ed25519` (detached signature over canonical `manifest.json`) |
| Public Key SPKI SHA-256 | `2c564b3b7f2b83156a7231a9b45aac40bede4a5b5adced63af310b5fff5d0189` |
| Public Key Raw (Hex) | `2266c0d5171621462e7009c80d84a7a323ee05fe8263e13aca05e85e9ba375e3` |
| `filings_30d.jsonl` SHA-256 | `6bcee99f0b4bb1566c7fe2acf29fd8bdfb73b5ac5dd74f8acaef393549f34d1a` |

### 简介（中文）

本数据包收录连续 **30 个自然日**（`2026-10-06` 至 `2026-11-04`，覆盖 21 个 SEC 交易申报日）内 **3,685 条**去重后的美国 SEC EDGAR 公开 Form D 首次申报记录（`3,577` 家唯一 CIK 发行主体，零付费 API）。每条记录仅保留实体级公开字段（排除个人高管名单 `relatedPersonsList` 与街道门牌），按规范键序输出为 JSONL，并附带官方 `sec_edgar_url` 与原始 `primary_doc.xml` 的 `source_xml_sha256` 摘要；清单 `manifest.json` 附带分离式 Ed25519 签名，任何单字节篡改均会被离线校验拦截。

---

## Verify in One Command

`verify_pack.py` uses **only the Python 3 standard library + `openssl`** (zero third-party Python dependencies). It verifies:
1. Detached Ed25519 signature over the exact bytes of `manifest.json` against the SPKI public key;
2. Public key SPKI/PEM/raw fingerprints recorded in `manifest.json`;
3. Exact byte length, SHA-256, record count, date bounds, unique `accession_number`, and `https://www.sec.gov/` provenance of `filings_30d.jsonl`;
4. `SHA256SUMS.txt` parity for all pack files.

```bash
python3 verify_pack.py
```

For machine-readable JSON output:

```bash
python3 verify_pack.py --json
```

### Direct `openssl` Verification (No Python Required)

When verifying the local distribution (`public_key.pem` + raw 64-byte `manifest.sig`):

```bash
openssl pkeyutl -verify -pubin -inkey public_key.pem -rawin -in manifest.json -sigfile manifest.sig
shasum -a 256 -c SHA256SUMS.txt
```

When verifying the pure-text Git mirror in `wasabihu/vericorpus` (`public_key.pub` + ASCII base64 `manifest.sig.b64` — byte-for-byte identical public key & signature, stored in pure-text extensions to obey VeriCorpus's unmodified pure-text `audit_public_release.py` gate):

```bash
openssl base64 -d -in manifest.sig.b64 -out /tmp/formd_manifest.sig && \
  openssl pkeyutl -verify -pubin -inkey public_key.pub -rawin -in manifest.json -sigfile /tmp/formd_manifest.sig && \
  rm -f /tmp/formd_manifest.sig
shasum -a 256 -c SHA256SUMS.txt
```

---

## Record Schema (`filings_30d.jsonl`)

Each line is a canonical sorted-key JSON object with strictly public entity-level Form D fields:

- `accession_number`, `cik`, `form_type` (`"D"`), `filing_date` (`YYYY-MM-DD`)
- `issuer_name`, `entity_type`, `jurisdiction_of_inc`, `year_of_inc`, `city`, `state_or_country`
- `industry_group`, `revenue_range`, `federal_exemptions`, `date_of_first_sale`
- `is_equity`, `is_pooled_investment_fund`, `is_indefinite_offering`, `offering_amount_usd`, `amount_sold_usd`, `total_investors`
- `sec_edgar_url`, `sec_index_url`, `source_xml_sha256`

---

## Composing with VeriCorpus & claimcite

1. **Cryptographic pre-ingest verification (`verify_pack.py`)**: Run `python3 verify_pack.py` before indexing or downstream analytics to guarantee zero payload or manifest tampering.
2. **Retrieval & compliance (`wasabihu/vericorpus`)**: Every record carries `SEC-Public-Filing` provenance (`sec_edgar_url` + `source_xml_sha256`), fitting directly into VeriCorpus's allowlisted public-filing pipelines and XERJ / Elasticsearch indexing workflows.
3. **Deterministic citation verification (`wasabihu/claimcite`)**: Downstream LLM summaries or funding claims citing offering amounts, filing dates, or exemptions can be verified deterministically against the immutable `filings_30d.jsonl` JSONL records and traced back to the exact `accession_number` and `source_xml_sha256` on SEC EDGAR.
