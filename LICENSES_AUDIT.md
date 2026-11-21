# VeriCorpus 语料与依赖合规准入审计清单（Licence & Provenance Audit）

> **Trademark & Non-Affiliation Notice**: VeriCorpus is an independent community project built for XERJ and Elasticsearch-compatible engines. It is not affiliated with, sponsored by, or endorsed by The XERJ Authors.
>
> **Legal, Financial & Medical Disclaimer**: Not Legal, Investment, or Medical Advice — strictly for retrieval benchmarking and document verification research.

本项目坚持**版权零纠纷与协议物理隔离**原则。每个纳入 `corpora/<slug>/manifest.json` 的语料包均须通过 `src/vericorpus/compliance.py` 的硬性白名单、40 位完整 Commit SHA 锁定与 HTTPS 来源校验，并在发版前通过 `scripts/audit_public_release.py` 全仓与全 Git 历史审查。

## 零、运行库许可证隔离说明（Core `Apache-2.0` Stdlib vs. Optional `[pdf]` `AGPL-3.0`）

- **核心控制面与检索适配器（`pip install vericorpus` / `dependencies = []`）**：100% 纯 Python 标准库实现（`Apache-2.0`），**零第三方运行时依赖**。导入 `vericorpus`、`vericorpus.compliance`、`vericorpus.query_cn`、`vericorpus.fetchers` 以及调用 `pdf_table_fix.normalize_cell` / `repair_hkex_cmap` 均不会触发任何外部库加载。
- **可选 PDF 几何坐标重建扩展（`pip install 'vericorpus[pdf]'`）**：通过 `[project.optional-dependencies] pdf = ["pymupdf>=1.24.0"]` 按需安装 `PyMuPDF`。请注意：**PyMuPDF 默认遵循 GNU Affero General Public License v3.0（`AGPL-3.0`，Artifex Software, Inc.）**（除非另行取得商业授权）；仅在本地调用 `extract_pdf_to_markdown` / `extract_page_to_markdown` 解析原始 PDF 时惰性导入，绝不传染纯标准库检索与合规模块。

---

## 一、语料准入标准（Allowlist）

| 分发模式（`mode`） | 允许的许可标识（`license`） | 适用范围与交付要求 |
|---|---|---|
| **`pack`**（可公开生成签名 `.hubpack`） | `Public-Domain-CN-Law` | 依据《中华人民共和国著作权法》第五条第一项，中国法律、法规、国家机关的决议、决定、命令等不适用著作权法，属于公有领域；须标明官方来源与版本日期。 |
| **`pack`** | `Apache-2.0` / `MIT` / `BSD-3-Clause` / `BSD-2-Clause` | 经 GitHub API 或上游仓库 `LICENSE` 实核确认 SPDX 标识的开源软件文档；须保留仓库名、锁定 **40 位完整 Commit SHA** 与版权声明。 |
| **`pack`** | `CC-BY-4.0` / `CC-BY-3.0` / `CC0-1.0` | 经 OpenAlex / Europe PMC / ClinicalTrials.gov OA 接口实核 `cc-by` 或 `cc0` 的开放获取科学论文与临床试验结果；`CC-BY-4.0` 条目须完整保留真实作者署名、DOI/PMCID、标准许可 URI（`https://creativecommons.org/licenses/by/4.0/`）及第 3(a) 条 XML/HTML→Markdown 表格转换说明（`Adaptation Notice`）。 |
| **`pack`** | `SEC-Public-Filing` | 美国 SEC EDGAR 法定公开披露文件（`10-K`、`20-F`、`10-Q`、`6-K`、`424B4` / `S-1` IPO 招股书及 CompanyFacts XBRL 审计数据）；实时抓取须配置含联系邮箱的 `SEC_USER_AGENT`。 |
| **`recipe`**（仅公开采集/清洗配方，不二次分发原文件） | `HKEX-Public-Disclosure` / `CNINFO-Public-Disclosure` / `KRX-Public-Disclosure` / `Multi-Exchange-Public-Disclosure` | 港交所（HKEXnews）、深上交所/巨潮资讯（CNINFO）、韩国 DART（KRX）及多交易所组合配方；子源同样受白名单约束，原始 PDF 与重建 Markdown 均置于 `.gitignore` 忽略的 `data/` 下本地隔离自用，不随公共仓库或评测 JSON 二次分发。 |

---

## 二、已审计通过清单（共 11 个语料目录：8 个 `pack` + 3 个 `recipe`）

| Slug | 领域 | 许可标识 | 模式 | 核验来源与状态 |
|---|---|---|---|---|
| `cn-law-core` | 中国核心商法与合规法律 | `Public-Domain-CN-Law` | `pack` | 国家法律法规数据库整理版（`LawRefBook/Laws` 锁定 40 位 commit `8cb05f0dfd02c442b28e3fa1299014246aa7d3da`，共 9 部现行法律全文；单条拆分版见 [`wasabihu/corpus-cn-statutes`](https://github.com/wasabihu/corpus-cn-statutes)） |
| `cn-capital-market-law` | 中国资本市场、企业会计准则与财税审计核心法规 | `Public-Domain-CN-Law` | `pack` | 国家法律法规数据库及部委规章/司法解释整理版（`LawRefBook/Laws` 锁定 40 位 commit `8cb05f0dfd02c442b28e3fa1299014246aa7d3da`，共 20 部：会计法、注册会计师法、审计法及实施条例、企业所得税法、增值税法及实施条例、期货和衍生品法、证券投资基金法、企业破产法、财政部准则与会计处理规定 4 部、证监会信披/重组/收购/注册制办法 5 部、最高法虚假陈述民事赔偿规定） |
| `cn-github-stars` | 中文高星开源 AI 与工程文档 | `Apache-2.0` | `pack` | 全部 5 仓经 GitHub API 实核 SPDX = `Apache-2.0` 并锁定 40 位完整 Commit SHA：`infiniflow/ragflow`、`PaddlePaddle/PaddleOCR`、`hiyouga/LLaMA-Factory`、`chatchat-space/Langchain-Chatchat`、`datawhalechina/self-llm`（共 22 篇） |
| `cn-science-ccby` | 开放获取科学/临床中文与双语论文 | `CC-BY-4.0` | `pack` | OpenAlex `open_access.is_oa:true + primary_location.license:cc-by` 实核抓取并保留完整作者、DOI 与期刊署名（共 40 篇） |
| `ai-papers-ccby` | 高影响力开放获取 AI 论文与评测表 | `CC-BY-4.0` | `pack` | OpenAlex `open_access.is_oa:true + primary_location.license:cc-by`（辅以 Europe PMC 降级）跨越 5 大 AI 方向抓取，结合 arXiv HTML / Europe PMC 许可块实核拒绝 `-NC`/`-ND`/`-SA` 及默认非排他许可（共 50 篇，其中 40 篇提取结构化评测 Markdown 表，保留完整作者、DOI、许可 URI 与转换声明） |
| `biomed-clinical-ccby` | 开放获取临床医学全文与临床试验结果 | `CC-BY-4.0`（子源含 `CC0-1.0`） | `pack` | Europe PMC / NCBI PMC JATS XML 临床全文（`CC-BY-4.0`，完整保留真实作者、DOI/PMCID、许可 URI 与转换声明）与 ClinicalTrials.gov API v2 已完成并公布结果的干预性试验（US NIH Public Domain `CC0-1.0`），全部含结构化临床疗效/安全性 Markdown 表（独立纯文本配套仓见 [`wasabihu/corpus-clinical-trials`](https://github.com/wasabihu/corpus-clinical-trials)） |
| `sec-10y-core` | 美股与赴美中概近 10 年财报 | `SEC-Public-Filing` | `pack` | 覆盖 48 家美股核心科技/消费/金融/能源/医药龙头与中概 ADR（含 `SPCX`），共 442 份年报原文 Markdown + 48 份双语 XBRL 财务总表，可供公开检索基准与文档核验评测复用 |
| `sec-ipo-prospectus-pack` | 美股硬科技 IPO 招股书与上市后对照 | `SEC-Public-Filing` | `pack` | 覆盖 `ALAB`、`CRDO`、`CRWV`、`ARM`、`SPCX` 共 5 家硬科技 `424B4` 招股书、上市后 `10-K`/`20-F`/`10-Q` 及 XBRL 对照汇总（共 19 份） |
| `cn-hkus-disclosures` | 港美股公告与 PDF 表格清洗回归配方 | `HKEX-Public-Disclosure` | `recipe` | 阿里巴巴（SEC 6-K HTML + 港交所季报 PDF）与腾讯控股（`0700.HK` 2026Q3 季报 PDF）；仅分发采集与表格坐标重建脚本配方，不在公开仓分发交易所披露原文 |
| `cn-hk-financial-10y` | 中美港韩 92 家代表性公司近 10 年财报全市场配方 | `Multi-Exchange-Public-Disclosure` | `recipe` | 统一编目 92 家公司权威代码与披露索引；支持在本地隔离目录执行 A 股/A+H（巨潮资讯 HTTPS）与港股（港交所披露易 HTTPS）PDF 几何重建及韩股 Open DART 同步；原件均留在 `.gitignore` 忽略的 `data/` 下 |
| `cn-hk-ipo-prospectus-recipe` | 港股 18C 与科创板硬科技招股书、问询回复与年报配方 | `Multi-Exchange-Public-Disclosure` | `recipe` | 覆盖港股 18C 4 家（黑芝麻智能 `02533`、地平线 `09660`、智谱 `02513`、越疆机器人 `02432`）及科创板 3 家（海光信息 `688041`、源杰科技 `688498` 含上交所审核问询函回复、中复神鹰 `688295`），仅分发本地清洗配方，不二次分发原件 |

---

## 三、明确拒绝名单（已审计拦截，不纳入公开仓库、`pack` 或公开评测集）

以下高星中文项目与热门技术内容源虽热度较高，但在核验时因无开源协议、协议不明确或含非商用限制被明确拦截，防止版权风险：

1. **`krahets/hello-algo`**：文本教程使用 `CC-BY-NC-SA 4.0`（含 **NC 非商用**条款），GitHub SPDX 为 `NOASSERTION`，与 Apache-2.0 生态不兼容，**不收进公开 `pack`**。
2. **`datawhalechina/happy-llm`**：GitHub SPDX 为 `NOASSERTION`，暂不进公开 `pack`（待上游补齐标准许可证声明后再议）。
3. **`datawhalechina/hello-agents`**：GitHub SPDX 为 `NOASSERTION`，暂不进公开 `pack`。
4. **`QwenLM/Qwen2.5`**：仓库根目录 `spdx=None`，因部分权重/文档附带专有补充条款，不默认按纯 `Apache-2.0` 纳入公开文档包。
5. **`LawRefBook/Laws` 仓库本体代码**：虽然其收录的中国法律法规正文属于法定公有领域（适用 `Public-Domain-CN-Law`），但该仓库未带代码许可证（`license=None`），因此本项目**仅提取公有领域法律条文文本并自主封装校验清单，不搬运其任何代码或应用实现**。
6. **`ruanyf/weekly`（《科技爱好者周刊》）**：GitHub API 实核 `license: None`（默认保留全部权利 / All Rights Reserved），**严禁进入 `corpora/`、公开发行包或公开评测 JSON（`evals/*.json`）**。
