# VeriCorpus 一级市场硬科技招股书与开源工程文档实测报告 (`PRIMARY_EVAL_REPORT.md`)

> Not Legal, Investment, or Medical Advice — strictly for retrieval benchmarking and document verification research.
>
> 全部评测数据均在同一隔离本地 `xerj` 进程（`XERJ_DISABLE_QUERY_CACHE=1`）实测产生，未触碰线上个人索引。

## 1. 隔离建索与合规资产总览

- **仓库 Manifest 合规通过数**：`11` 个语料目录全部通过 `compliance.audit_corpora_dir` 校验

| 索引前缀 | 语料轨道 | 版权模式 | 收录文件数 | XERJ 分块数 | 建索耗时 (ms) |
|---|---|---|---:|---:|---:|
| `secipo` | SEC 5 家硬科技招股书+年报 (`ALAB/CRDO/CRWV/ARM/SPCX`) | `pack` (`SEC-Public-Filing`) | 19 | 6290 | 3626.2 |
| `hkipo` | 港股 18C 4 家 (`02533/09660/ZHIPU/02432`) | `recipe` (`HKEX-Public-Disclosure`) | 16 | 5469 | 2560.2 |
| `cnipo` | 科创板 3 家含问询回复 (`688041/688498/688295`) | `recipe` (`CNINFO-Public-Disclosure`) | 7 | 3244 | 2476.2 |
| `cngh` | 5 座高星中文 AI 工程仓库文档 (`ragflow/PaddleOCR/LLaMA-Factory/Chatchat/self-llm`) | `pack` (`Apache-2.0`) | 22 | 191 | 2188.0 |

## 2. 32 题隔离 XERJ 对比结果（Native Baseline vs `vericorpus.query_cn`）

| 指标 | XERJ 原生基线 | `vericorpus` 中文+繁简+双语增强 |
|---|---:|---:|
| 域内真值题 Top-1 准确率 (28 题) | 20/28 (71.4%) | **25/28 (89.3%)** |
| 域内真值题 Top-3 召回率 (28 题) | 23/28 (82.1%) | **28/28 (100.0%)** |
| 严格缺失证据拒答率 (0 命中 / 4 题) | 0/4 (0.0%) | **4/4 (100.0%)** |

## 3. 越疆机器人 (`02432.HK`) 纯文本导出 vs `pdf_table_fix` 坐标重建对比

| 指标 | 纯文本导出 (`pypdfium2`) | 几何坐标重建 Markdown (`pdf_table_fix`) |
|---|---:|---:|
| 文档份数 | 0 | 7 |
| 提取总字符数 | 0 | 422,908 |
| 结构化 Markdown 管道表格行 (`| ... |`) | 0 | **699** |
| 顺序页码锚点 (`<!-- page: p/N -->`) | 0 (非结构化页号) | **486** |
| Unicode 乱码替换符 `\ufffd` / CMap 异常 `尸` 日期 | 0 / - | **0 / 0** |

## 4. 逐题实测明细

| ID | 轨道 | 类别 | 查询语句 | 基线 Top-1 | `vericorpus` Top-1 | 判定 |
|---|---|---|---|---|---|---|
| SEC-IPO-01 | `secipo` | 美股招股书·高速互联产品 | ALAB Astera Labs Aries retimer CXL | ✅ `ALAB/2024_424B4_2024-03-21.md` | ✅ `ALAB/2024_424B4_2024-03-21.md` | PASS |
| SEC-IPO-02 | `secipo` | 美股年报·中文跨语业绩 | Astera Labs ALAB 2025 营业收入 研发费用 | ❌ `CRWV/CRWV_xbrl_summary.md` | ✅ `ALAB/ALAB_xbrl_summary.md` | PASS |
| SEC-IPO-03 | `secipo` | 美股招股书·AEC集群协议 | CRDO Credo HiWire Switch AEC 424B4 IPO prospectus | ✅ `CRDO/2022_424B4_2022-01-27.md` | ❌ `CRDO/2025_10-K_2025-07-02.md` | TOP3 |
| SEC-IPO-04 | `secipo` | 美股年报·上市后爆发验证 | Credo CRDO 2026 营业收入 净利润 | ❌ `CRWV/CRWV_xbrl_summary.md` | ✅ `CRDO/CRDO_xbrl_summary.md` | PASS |
| SEC-IPO-05 | `secipo` | 美股招股书·AI算力云生态 | CoreWeave CRWV NVIDIA Microsoft OpenAI | ✅ `CRWV/2025_424B4_2025-03-31.md` | ✅ `CRWV/2025_424B4_2025-03-31.md` | PASS |
| SEC-IPO-06 | `secipo` | 美股年报·算力云资本开支 | CoreWeave CRWV 2025 资本开支 总资产 营业收入 | ✅ `CRWV/CRWV_xbrl_summary.md` | ✅ `CRWV/CRWV_xbrl_summary.md` | PASS |
| SEC-IPO-07 | `secipo` | 美股招股书·股权结构 | ARM SoftBank Group 90.6% ordinary shares | ✅ `ARM/2023_424B4_2023-09-14.md` | ✅ `ARM/2023_424B4_2023-09-14.md` | PASS |
| SEC-IPO-08 | `secipo` | 美股招股书·航天星链 | SpaceX SPCX Starlink V2 Mini V3 | ✅ `SPCX/2026_424B4_2026-06-12.md` | ✅ `SPCX/2026_424B4_2026-06-12.md` | PASS |
| HK-IPO-01 | `hkipo` | 港股18C招股书·简搜繁芯片 | 黑芝麻智能 华山系列 武当系列 车规级 SoC | ✅ `02533/2024_PROSPECTUS.md` | ✅ `02533/2024_PROSPECTUS.md` | PASS |
| HK-IPO-02 | `hkipo` | 港股18C年报·营收验证 | 黑芝麻智能 2025年报 收入 822,328 毛利 | ❌ `02533/2024_PROSPECTUS.md` | ✅ `02533/2025_ANNUAL_REPORT.md` | PASS |
| HK-IPO-03 | `hkipo` | 港股招股书·智驾软硬件 | 地平线 征程3 Horizon Pilot NOA | ✅ `09660/2024_PROSPECTUS.md` | ✅ `09660/2024_PROSPECTUS.md` | PASS |
| HK-IPO-04 | `hkipo` | 港股年报·客户合同收入 | 地平线 2025年报 来自客户合同的收入 3,758,268 | ❌ `09660/2024_PROSPECTUS.md` | ✅ `09660/2025_ANNUAL_REPORT.md` | PASS |
| HK-IPO-05 | `hkipo` | 港股招股书·大模型MaaS | 智谱 GLM-130B MaaS 预训练大模型框架 | ✅ `ZHIPU/2025_PROSPECTUS.md` | ✅ `ZHIPU/2025_PROSPECTUS.md` | PASS |
| HK-IPO-06 | `hkipo` | 港股年报·大模型营收毛利 | 智谱 2025年度报告 724,334 毛利 296,656 | ❌ `ZHIPU/2025_PROSPECTUS.md` | ✅ `ZHIPU/2025_ANNUAL_REPORT.md` | PASS |
| HK-IPO-07 | `hkipo` | 港股基准对照·越疆概要 | 越疆 协作机器人 灼识咨询 全球前二 | ✅ `02432/02-聆讯后资料集-业务.md` | ✅ `02432/02-聆讯后资料集-业务.md` | PASS |
| HK-IPO-08 | `hkipo` | 港股基准对照·越疆2025年报 | 越疆机器人 2025年12月31日 营业收入 492.209 | ❌ `02432/02-聆讯后资料集-业务.md` | ✅ `02432/06-2025年度报告.md` | PASS |
| CN-IPO-01 | `cnipo` | 科创板招股书·国产算力DCU | 海光信息 DCU 海光一号 深算一号 营业收入 | ✅ `688041/2022_PROSPECTUS.md` | ✅ `688041/2022_PROSPECTUS.md` | PASS |
| CN-IPO-02 | `cnipo` | 科创板年报·营收净利跃升 | 海光信息 2025年报 归母净利润 14,376,889,476.95 | ✅ `688041/2025_ANNUAL_REPORT.md` | ✅ `688041/2025_ANNUAL_REPORT.md` | PASS |
| CN-IPO-03 | `cnipo` | 科创板招股书·高速光芯片 | 源杰科技 招股说明书 2.5G 1490nm 10G 1270nm DFB EML | ❌ `688498/2025_ANNUAL_REPORT.md` | ❌ `688498/2025_ANNUAL_REPORT.md` | TOP3 |
| CN-IPO-04 | `cnipo` | 科创板问询回复·监管追问 | 源杰科技 审核问询函 应收账款 1.14亿元 坏账减值 | ✅ `688498/2023_INQUIRY_REPLY.md` | ✅ `688498/2023_INQUIRY_REPLY.md` | PASS |
| CN-IPO-05 | `cnipo` | 科创板招股书·高性能碳纤维 | 中复神鹰 SYT49S SYM40 碳纤维 航空航天 | ✅ `688295/2022_PROSPECTUS.md` | ✅ `688295/2022_PROSPECTUS.md` | PASS |
| CN-IPO-06 | `cnipo` | 科创板年报·碳纤维复苏 | 中复神鹰 2025年报 营业收入 2,193,737,675.52 | ✅ `688295/2025_ANNUAL_REPORT.md` | ✅ `688295/2025_ANNUAL_REPORT.md` | PASS |
| GH-OSS-01 | `cngh` | 开源工程·知识切片管理 | RAGFlow Chunk Parsing Results Knowledge Fragment | ✅ `ragflow/docs_chunk_parsing.md` | ✅ `ragflow/docs_chunk_parsing.md` | PASS |
| GH-OSS-02 | `cngh` | 开源工程·昇腾NPU容器 | LlamaFactory 昇腾 Atlas NPU TorchNPU CANN 镜像 | ✅ `llamafactory/npu_OVERVIEW.zh.md` | ✅ `llamafactory/npu_OVERVIEW.zh.md` | PASS |
| GH-OSS-03 | `cngh` | 开源工程·QLoRA单卡训练 | llamafactory-cli qwen3_lora_sft_bnb_npu QLoRA | ❌ `llamafactory/README_zh.md` | ❌ `llamafactory/README_zh.md` | TOP3 |
| GH-OSS-04 | `cngh` | 开源工程·ONNX模型转换 | Paddle2ONNX PaddleOCR ONNXRuntime 模型转化 | ✅ `paddleocr/paddle2onnx_ch.md` | ✅ `paddleocr/paddle2onnx_ch.md` | PASS |
| GH-OSS-05 | `cngh` | 开源工程·显存与注意力优化 | PagedAttention FlashAttention MQA/GQA 显存优化 | ✅ `chatchat/大模型推理优化策略.md` | ✅ `chatchat/大模型推理优化策略.md` | PASS |
| GH-OSS-06 | `cngh` | 开源工程·代码模型微调 | DeepSeek-Coder-V2-Lite-Instruct Lora 微调 3090 | ✅ `selfllm/DeepSeek-Coder-V2-LoRA.md` | ✅ `selfllm/DeepSeek-Coder-V2-LoRA.md` | PASS |
| ABS-IPO-01 | `secipo` | 拒答·缺失私有条款 | SpaceX B轮优先股 对赌回购利率 条款 | hits=1541 | hits=0 | PASS (0-hit) |
| ABS-IPO-02 | `hkipo` | 拒答·虚构未上市标 | 幻方量子计算 港股18C 招股书 第八章 | hits=3319 | hits=0 | PASS (0-hit) |
| ABS-IPO-03 | `cnipo` | 拒答·虚构监管函 | 寒武纪 2026年科创板问询回复 退市风险警示 | hits=3067 | hits=0 | PASS (0-hit) |
| ABS-IPO-04 | `cngh` | 拒答·虚构量子算子 | PaddleOCR 室温超导量子引力波晶圆光刻第999章 | hits=78 | hits=0 | PASS (0-hit) |
