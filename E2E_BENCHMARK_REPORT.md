# VeriCorpus 端到端双语检索与验证闭环评测报告 (`E2E_BENCHMARK_REPORT.md`)

> Not Legal, Investment, or Medical Advice — strictly for retrieval benchmarking and document verification research.
>
> 全部检索均在隔离单进程 `xerj`（关闭查询缓存 `XERJ_DISABLE_QUERY_CACHE=1`，单命名空间 `e2e-*`）实测完成；验证阶段通过本地标准 `http://127.0.0.1:8000/api/verify` 接口（`Neuro-Symbolic Reader (1.7B)`）执行，未触碰线上个人索引。

## 一、合并索引规模（100% `pack` 合规子集）

- **总文件数**：`208` 份 Markdown（全部属于 `pack` 白名单合规语料）
- **XERJ 合并分块总数**：**`33,575` chunks**（建索耗时 `9214.5 ms`）
- **评测题集**：`60` 题严格零泄漏盲测（`20` SEC 财报 `10 extract + 10 arithmetic` 仅限 11 家保留标的 + `10` ARM IPO 招股书 + `15` 中国法规与资本市场新规 + `15` 硬拒答陷阱）
- **审计通过语料包总数**：`9` 个

## 二、端到端回答质量对比（XERJ `R / W / N` 与 `Net = R - 2W`，4,000 次配对 Bootstrap 95% CI）

| 评测分支 (Arm) | R / W / N | Net (`R - 2W`) | Net 95% CI | Score (`% Oracle`) | Score 95% CI | 严格准确率 | `ABSENT` 误答数 | 证据偏移 100% 合法 |
|---|---|---:|---|---:|---|---:|---:|---:|
| **Arm 1: Oracle Passage + Neuro-Symbolic Reader (1.7B)** | `52 / 7 / 1` | **38** | `[23.0, 51.0]` | `100.0` | `[100.0, 100.0]` | `86.7%` | `2` | `60/60` |
| **Arm 2: Native XERJ BM25 Top-3 + Neuro-Symbolic Reader (1.7B)** | `24 / 11 / 25` | **2** | `[-16.0, 18.0]` | `5.3` | `[-44.7, 48.5]` | `40.0%` | `0` | `60/60` |
| **Arm 3: `vericorpus` Enhanced Top-3 + Neuro-Symbolic Reader (1.7B)** | `49 / 6 / 5` | **37** | `[22.0, 50.0]` | `97.4` | `[64.1, 147.8]` | `81.7%` | `1` | `60/60` |

- **Arm 3 相对 Arm 2 的配对净分差 ΔNet (95% CI)**：`+35` (`[15.0, 55.0]`)
- **相比上代验证基线（`Neuro-Symbolic Reader (1.7B, Baseline)`）变化**：Arm 1 Net `46 → 38` (`-8`) · Arm 2 Net `4 → 2` (`-2`) · Arm 3 Net `38 → 37` (`-1`)

## 三、Top-3 证据块检索质量与拒答表现

| 检索器 | 证据块 `R@1` | 证据块 `R@3` | `nDCG@3` | 文档级 `R@1` | 文档级 `R@3` | `15` 题陷阱 0 命中拒答率 |
|---|---:|---:|---:|---:|---:|---:|
| Native XERJ BM25 (`multi_match`) | `0.1778` | `0.2222` | `0.2029` | `0.4000` | `0.4889` | `5/15 (33.3%)` |
| **`vericorpus` Enhanced BM25** | **`0.7778`** | **`0.9111`** | **`0.8561`** | **`0.9333`** | **`0.9778`** | **`9/15 (60.0%)`** |

## 四、分阶段延迟拆解（检索 ms vs 验证推理 ms，p50 / p95）

| 分支 | 检索 `p50 / p95` (ms) | 验证端 `p50 / p95` (ms) | 端到端合计 `p50 / p95` (ms) |
|---|---:|---:|---:|
| Arm 1 (Oracle) | `0.0 / 0.0` | `1891.25 / 3616.64` | `1891.25 / 3616.64` |
| Arm 2 (Native BM25) | `113.67 / 306.94` | `2461.85 / 6421.15` | `2630.87 / 6621.41` |
| Arm 3 (`vericorpus`) | `102.5 / 521.88` | `2502.2 / 5319.96` | `2745.84 / 5883.71` |

## 五、分赛道结果与错误归因

| 赛道 | Arm 1 (`R/W/N`) | Arm 2 (`R/W/N`) | Arm 3 (`R/W/N`) |
|---|---|---|---|
| SEC 财报与 XBRL (20 题) | `18/2/0` | `4/9/7` | `15/2/3` |
| ARM 硬科技 IPO 招股书 (10 题) | `9/1/0` | `1/1/8` | `7/1/2` |
| 中国法规与资本市场新规 (15 题) | `13/2/0` | `4/1/10` | `13/2/0` |
| 硬拒答陷阱 (15 题) | `12/2/1` | `15/0/0` | `14/1/0` |

### 失败原因归因统计

- **Arm 1 (Oracle)**：`false_answer_hallucinated`=3, `reader_miss`=5
- **Arm 2 (Native BM25)**：`reader_wrong_value_or_op`=1, `retrieval_wrong_chunk_in_doc`=12, `retrieval_wrong_doc`=18, `retrieval_zero_hits`=5
- **Arm 3 (`vericorpus`)**：`false_answer_hallucinated`=1, `reader_missed_evidence_present`=1, `reader_program_rejected`=1, `reader_wrong_value_or_op`=5, `retrieval_wrong_chunk_in_doc`=2, `retrieval_wrong_doc`=1

## Limits

- 本次评测仅索引了 100% `pack` 合规子集中的部分代表性年报/法典/论文（`>= 10,000` 分块），未包含受限于 `recipe` 分发模式的 A 股 CNINFO / 港股 HKEX 私有重建原文，也未索引 `sec-10y-core` 全量 48 家原始 10-K。
- `60` 题评测集为人工核验构造的零泄漏评测集，样本量有限，95% Bootstrap 置信区间基于题目重抽样而非跨更大机构文档池的集群抽样。
- Arm 2 与 Arm 3 仅测试纯词法 BM25（无 Dense Vector 向量索引与重排模型），跨英汉深层语义改写且未命中同义词表的问题仍可能因词法失配而退回 `ABSENT`。
- 当检索返回与 Oracle 完全一致或两分支召回相同组装上下文时，脚本对相同的 `(document, question)` 请求复用了 `http://127.0.0.1:8000/api/verify` 结果以节省本地推理时间，但延迟分位数仍按实际 `Neuro-Symbolic Reader (1.7B)` 推理耗时记录。
