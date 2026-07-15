# 项目 TODO 与当前交接板

更新时间：2026-07-15

本文档只保留当前主线、可执行任务和验收口径。历史任务流水、旧路线、完整验证记录与
PriMock57 已完成结果见 `docs/task_records.md`；除非需要追溯决策，不要默认完整读取历史归档。

## 快速规则

- 当前主线：**音频 → ASR + 说话人分离 → 病例级 speaker turns + noisy transcript +
  ASR 词/片段级置信度 + n-best/LLM 候选 → 医学实体优先筛选 → 绿/黄/红审阅 →
  医生/研究者确认 → confirmed transcript →
  raw/confirmed/reference 下游鲁棒性评估**。
- 本批中文数据已通过相应审核，可按已批准范围用于外部 LLM、外部 ASR 和原音频处理；
  仍不得把原始音频、逐例转录、病例正文或可识别信息提交 Git。
- 包内现有转录和 Qwen 自动病历均是自动产物，不得标为人工 `reference`、真实
  `confirmed_transcript` 或下游 gold。
- 所有病例摘要、诊疗/随访计划整理结果必须标注“研究输出，不构成临床建议”。
- Python、pytest、ruff、NeMo、ASR 和实验脚本默认使用 WSL Conda 环境：
  `/home/krabs/miniforge3/envs/clinical-asr/bin/python`。
- 若 Codex 沙箱调用 WSL Python 失败，或误报发行版不存在但 `wsl.exe -l -v` 可见
  `Ubuntu-22.04`，立即申请提升权限，不反复探索。环境细节见 `docs/wsl_environment.md`。

## 当前焦点

T061 已完成中文 40/40 全量工程运行：710.44 分钟源音频切为 1,442 个窗口，confidence、
acoustic 5-best 和 Streaming Sortformer 均覆盖 40/40。共 75,228 个 ASR 审阅单元；
green/yellow/red=52,659/15,046/7,523；9 个 CTC 对齐失败窗口显式全红兜底，1 个空转写窗口和
21 个缺时间戳单元没有被静默丢弃。n-best 共 6,565 beams，1,440/1,442 窗有多个不同候选。

医学实体筛选完成 1,442/1,442，得到 447 个黄/红医学 span；85/447（19.0%）有 acoustic 局部
候选。Sortformer 40/40 成功，病例 macro 原始/短空洞桥接 speaker 映射为 88.9%/90.5%。审阅
包包含 40 个病例、10,138 turns 和 40 个独立交互页面；索引 40 个链接、80 个内联 JavaScript
块通过语法检查。全量 HTML/CSV/Markdown 和 5 张 SVG 见
`docs/t061_chinese_all40_engineering.md`。

固定 5 例 proxy 质量探索继续单独呈现：Proxy CER 21.2%、CIPS 88.0%、黄+红可检测错误召回
79.5%、审阅字符比例 28.8%，noisy↔proxy 病例摘要事实 F1 35.7%。proxy 没有听音频，不是
人工 gold。浏览器运行时仍不可用，自动 QA feedback 只验证回放链路，不是医生确认；因此
40 例工程目标已经完成，但“真实确认闭环/正式质量结论”门槛仍未通过。

当前最先执行：

1. 在可用浏览器中由医生/研究者完成 1 例真实点击、回听、下载和 T035 回放；
2. 为固定 5 例制作听音频的独立人工 reference，优先标注药物、否定、数字单位、侧别、DBS
   参数和说话人不确定区间；
3. 在人工 reference 上复算 CER、CIPS、ECE/Brier、risk-coverage 和 top-k/span 候选覆盖；
4. 为病例信息整理建立人工 gold facts，再评估 raw/confirmed/reference 下游鲁棒性与审阅收益；
5. 抽样评估 754 条完整对话 LLM 候选 prompt 的增量覆盖和人工可用率，不直接批量调用或把
   LLM 文本修复改成主线。

## 已整合的本地资产

| 资产 | 项目内路径 | 定位 |
|---|---|---|
| 40 例原始音频与多路自动转录 | `data/raw/remote_programming_40/远程程控人工复核资料_精选40例_无病历版_20260713/` | 受保护 raw 快照；40 个 MP3、现有自动转录及说明，不提交 Git |
| 40 份 Qwen 自动病历 | `data/external/remote_programming_40/远程程控精选40例_Qwen病历_20260714_加密/` | `noisy_asr → case_summary` 外部基线/格式参考，不是 gold |
| 中文/中英混说 Parakeet artifact | `data/external/asr_models/nemo/Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo` | 已验证为 Hybrid RNNT + auxiliary CTC；约 2.34 GB，不提交 Git |
| Streaming Sortformer artifact | `data/external/asr_models/nemo/diar_streaming_sortformer_4spk-v2.1.nemo` | 471,367,680 bytes；SHA-256 已与官方值核对；最多 4 个声学 speaker；NVIDIA Open Model License；不提交 Git |
| 历史英文 NeMo artifact | `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo` | PriMock57 历史 baseline，不与中文阈值或结果静默混用 |

`data/raw/`、`data/external/`、`data/interim/`、`data/processed/` 和 `outputs/` 已被
`.gitignore` 忽略。路径、聚合统计和数据定位见
`docs/remote_programming_40_dataset_assessment.md`。

## 中文 40 例完整任务拆分

状态只使用：`待开始`、`进行中`、`已完成`、`阻塞`。一个任务只有在产物和验收项都满足后
才能标为已完成。

| ID | 优先级 | 状态 | 任务 | 关键产物与验收 |
|---|---|---|---|---|
| T051 | P0 | 已完成 | 数据归位与快照冻结 | 40 例匿名 manifest、相对路径、音频格式/时长、683 文件的 SHA-256 清单和聚合 digest 已生成；不含病例正文，产物位于 Git 忽略目录。 |
| T052 | P0 | 进行中 | checkpoint 与环境核验 | restore-only 已完成：真实类为 `EncDecHybridRNNTCTCBPEModel`，16 kHz、7,000 BPE、aux CTC blank=7000，NeMo/PyTorch/CUDA/GPU 与 digest 已记录；公开发布前仍需补原始下载页/许可证凭据。 |
| T053 | P0 | 已完成 | 确定性音频预处理 | 已实现 MP3 → 16 kHz mono PCM16 连续短窗、SHA-256、稳定 unit 和原 MP3 绝对时间；最短/典型/最长首窗及最短整例 10 窗 QC 通过。VAD 可在 5 例阶段作为可选优化加入。 |
| T054 | P0 | 进行中 | 1 例 Parakeet ASR smoke test | 30 秒与最短整例均成功；10/10 窗、726 单元、字符/绝对时间错误 0，confidence RTF 0.0491、峰值 2.465 GiB，5-best RTF 0.0105。待补独立 `am_raw`/margin/稀疏 frame top-k 视图后再关闭。 |
| T055 | P0 | 进行中 | 中文 ASR adapter 与稳定 schema | 数据集/checkpoint、Hybrid auxiliary CTC、`unit_id`、字符偏移、原分隔符、绝对时间和右向左反馈回放已接入共用 schema；待补 `am_raw/decoded_with_lm/display_itn` 三层及 transform log。 |
| T056 | P0 | 已完成 | ASR 词/片段置信度与三档风险 | auxiliary CTC frame distribution 已聚合到中文审阅单元；`demo_quantile_v0` 已实现并明确 `calibrated=false`，最短整例 green/yellow/red=507/146/73。 |
| T057 | P0 | 进行中 | n-best/top-k 局部候选 | acoustic auxiliary-CTC 5-best 和字符区间 span 对齐已贯通，整例每窗 3–5 个去重 beam，医学待审 span 获得 1 个局部差异候选；待接 4-gram LM 和稀疏 frame top-k 证据。 |
| T058 | P0 | 已完成 | 1 → 5 例 ASR pilot | 固定 5 例覆盖 4.7–37.9 分钟、K=2/4/5/6 与中英混说信号；152/152 窗完成 confidence 和多 beam 5-best，5/5 完成整例 diarization。ASR confidence RTF 0.01896、峰值 allocated 2.465 GiB；运行表、CSV、Markdown 和 5 张 SVG 已生成。 |
| T059 | P0 | 进行中 | 医学实体优先筛选 | 40 例 1,442/1,442 窗完成 LLM 实体筛选和缓存恢复：1,233 个输入 mention、1,036 个对齐、2,438 个医学 word、447 个黄/红医学 span；解析器可恢复多 JSON 响应。仍待人工 reference 核验 recall/precision。 |
| T060 | P0 | 进行中 | 中文审阅界面与反馈回放 | 40 个独立页面已生成：10,138 turns、447 个待审 span，支持接受、候选选择、手工编辑、拒绝、无法判断、本地恢复和 JSONL 导出；40 个索引链接和 80 个内联 JS 块通过静态验收。in-app browser 初始化超时；自动 QA fixture 已验证 T035 回放但不是医生确认，仍缺真实点击/回听/下载验收。 |
| T061 | P0 | 已完成 | 40 例全量 ASR 与可展示运行总览 | 40/40、710.44 分钟、1,442 窗完成 confidence、6,565 n-best beams、40/40 Sortformer、医学筛选、候选和审阅包；输出 40 行 CSV、Markdown、HTML、5 张 SVG、失败兜底统计和 40 页交互入口。ASR RTF 0.0164、CUDA peak allocated 2.46 GiB；详见 `docs/t061_chinese_all40_engineering.md`。 |
| T062 | P0 | 待开始 | 医生/研究者确认与 confirmed transcript | 先 1 例、再 5 例试审，修订操作说明后扩量；保存每次选择、编辑、拒绝、无法判断、回听次数、耗时、候选来源和最终文本。输出审阅成本表、动作分布图、修改类型图；明确区分真实人工确认与 LLM 模拟审阅。 |
| T063 | P1 | 进行中 | 人工 reference 与标注协议 | 已生成 5 例 `llm_multi_asr_consensus_proxy` 用于探索链路，记录明确为未听音频、非人工、非 gold、不可正式声称质量；它不完成本任务。下一步仍需制定并执行逐字/时间戳、speaker role、听不清、否定、药名、数字单位、DBS 参数及双人仲裁规范。 |
| T064 | P1 | 进行中 | ASR、置信度与候选评估 | 已在 5 例代理参考上跑通 CER、CIPS、代理事实召回、ECE/Brier、AURC/risk-coverage 和三档错误率；Proxy CER 21.2%，CIPS 88.0%，yellow+red 可检测错误召回 79.5%。正式 reference、top-k oracle、配对 CI 和失败案例人工复核仍缺。 |
| T065 | P1 | 待开始 | 下游统一输入与 gold facts | 对同一病例对齐 `raw_asr`、真实 `confirmed_transcript`、`clean_reference`；由独立标注流程建立症状抽取、病例摘要和诊疗/随访计划 gold facts。Qwen 自动病历只作外部 baseline，不参与 gold 构造。 |
| T066 | P1 | 进行中 | raw/confirmed/reference 下游鲁棒性评估 | 5 例 noisy/proxy 使用同一 LLM、prompt、schema 与解码参数完成 10/10 病例摘要；同字段事实 F1 35.7%、critical fact recall 33.9%，显示下游噪声敏感性。尚无真实 confirmed、人工 reference/gold、unsupported/contradicted 与配对 CI，不能作正式质量结论。 |
| T067 | P1 | 进行中 | 最终图表、演示与报告 | 已形成 40 例无参考工程报告（40 行表、HTML、5 张 SVG）和 5 例 proxy 质量报告（CSV/HTML、5 张 SVG）；脱敏副本已同步。最终正式质量版仍需真实 confirmed/reference、审阅成本收益、错误类型和人工失败案例。 |
| T068 | P0 | 已完成 | 病例级完整对话审阅协议 | 新增 `asr_review_conversation/v1`、speaker turn/slice schema 和 JSONL；HTML 按 `consultation_id` 聚合，内部 30 秒窗口不再作为一级对话导航；无 diarization 时显式 `speaker_unknown`。 |
| T069 | P0 | 进行中 | 中文完整对话 LLM 候选 | 首例完整对话 LLM 候选路径已验证。5 例 acoustic 5-best 共 692 个 beam，但只为 11/73 个医学 span 提供局部差异候选；本轮未发起 125 次全上下文候选 API 请求。待评估 LLM 候选的增量覆盖、重复/过度推断和人工可用率。 |
| T070 | P0 | 已完成 | NVIDIA 说话人分离工程接入 | 40/40 整例 Streaming Sortformer 成功、失败 0；全量 acoustic/桥接后 micro 映射 89.53%/91.18%，病例 macro 88.9%/90.5%。工程接入已完成；无人工 RTTM 不报告 DER/JER，模型最多 4 speaker，超过上限病例仍待人工回听与聚类回退。 |

## 阶段门槛与扩量规则

- `1 例门槛`：checkpoint 可恢复；15–30 秒和整例能转写；绝对时间可回放；中文往返无空格
  损坏；能导出风险信号和至少 sequence-level n-best（候选允许无局部差异）。
- `5 例工程门槛`：无静默截断；失败可重跑；显存/RTF 可接受；实体、候选、页面和确定性
  feedback 回放链路可验证。已通过；自动 QA 回放不等于真实 confirmed transcript。
- `40 例工程完成`：40/40 均有标准化 ASR 记录或明确的失败/回退记录，运行配置可追溯，
  页面可审阅并能确定性生成 confirmed transcript。
- `质量结论门槛`：只有独立人工 reference/gold、真实人工 confirmed transcript 和预先声明
  的评估子集齐备后，才可声称 ASR、确认流程或下游质量得到提升。

## 当前风险与阻塞

- checkpoint 已确认是 Hybrid RNNT + auxiliary CTC；当前置信度和 beam 明确走 auxiliary CTC，
  不能把结果写成 RNNT 原生 confidence，也不能把 acoustic beam 写成已接 4-gram LM。
- RTX 4060 Laptop 8 GB 可能无法让 0.6B 模型、LM、ITN、VAD、diarization 同卡常驻；首轮
  仅跑直接 NeMo + 短段，逐组件接入。
- LM、标点和 ITN 会改变文字与偏移；数字、剂量、频率、电压/电流等不得无映射继承 raw
  token confidence。
- 包内多路文本不是同一解码器的 top-k；现有“推荐转录”角色也不是 speaker/role gold。
- NVIDIA Sortformer 是独立 artifact，不在当前 Parakeet ASR `.nemo` 内；本地已取得并跑通
  Streaming Sortformer v2.1。模型最多 4 speaker 输出，首例还出现仅 0.48 秒且未映射到 ASR
  word 的 `speaker_3`，需人工回听判定真 speaker/重叠/伪检出；2–6 人病例仍需准备
  VAD+TitaNet+clustering 回退，并把 acoustic speaker 与 doctor/patient/family/staff role 分开。
- LLM speaker 语义补全只利用 noisy ASR 的轮次和语义，无法识别声纹或可靠处理重叠说话；
  强制全连接版必须保留 `semantic_complete`/confidence/reason code 标记，不得当作人工 speaker
  reference、DER/JER 输入或声学准确率结果。首例 20 gaps 中仅 6 个高置信、3 个明确为
  `uncertain_best_guess`，5 例阶段必须抽样回听。
- 当前没有独立人工 reference 与下游 gold；这不阻塞工程闭环，但阻塞正式质量结论。
- 5 例 LLM 多路转录代理参考没有听原音频，可能继承多路 ASR 的共同错误；Proxy CER、CIPS、
  ECE/Brier、risk-coverage 和病例摘要稳定性只用于探索性展示，不得替代人工 reference 结果。
- 40 例 acoustic beam 只覆盖 85/447（19.0%）个医学待审 span；其余 span 依赖手工编辑、拒绝
  或无法判断。完整对话 LLM 候选已生成 754 条 prompt 但没有批量调用，候选增量覆盖和人工
  可用率仍待抽样验证。

## 最近完成

| 日期 | 任务 | 摘要 |
|---|---|---|
| 2026-07-15 | T061 中文 40 例全量工程与展示报告 | 40/40、710.44 分钟、1,442 窗完成 confidence、6,565 n-best beams、40/40 Sortformer、1,442/1,442 医学实体、447 个医学待审 span、40 个交互页面。输出 40 行 CSV、Markdown/HTML 与 5 张 SVG；40 页 JS 语法和链接通过。9 个对齐失败窗口全红兜底、1 个空窗和 21 个缺时间戳单元均显式统计。没有人工 reference/confirmed，不作正式质量声称。 |
| 2026-07-15 | 脱敏汇报输出包 | 新增 `outputs/reporting_safe/`，纳入中文 5 例代理评估、40 例工程状态和 Week 1 流程总览共 17 个安全汇报产物；仅含匿名病例编号、聚合指标和静态图表，不含音频、转写正文、病例正文、prompt/response 或反馈日志。40 例状态页明确当前实际处理覆盖仍为 5/40。 |
| 2026-07-15 | T058/T064/T066/T070 中文 5 例代理鲁棒性 pilot | 固定 5 例 74.60 分钟完成 152/152 confidence 与 5-best、5/5 Sortformer、152/152 医学实体筛选、5 例交互页和 10/10 noisy/proxy 病例摘要。探索结果：Proxy CER 21.2%、CIPS 88.0%、黄+红错误召回 79.5%、审阅字符比例 28.8%、摘要事实 F1 35.7%；输出 CSV/Markdown/run JSON 与 5 张 SVG。代理参考非人工 gold，浏览器真实点击与 confirmed transcript 仍待完成。 |
| 2026-07-15 | T070 LLM speaker 语义全连接实验 | 新增完整病例级 `semantic_speaker_resolution/v1` 与 `.env` 驱动脚本；一次 `Qwen3-Coder-Plus` 请求严格覆盖首例剩余 20/20 gaps、31/31 字词，unknown 31→0、turns 67→43，状态单列为 `semantic_complete`。6 个高置信、14 个中置信、3 个 `uncertain_best_guess`；原 acoustic 空值/状态全部保留，页面标记“含语义补全”。108 tests/ruff 与 HTML JavaScript 语法通过。 |
| 2026-07-15 | T070 同一说话人短空洞桥接 | 新增可审计的 `same_speaker_short_gap_bridge/v1`：只桥接前后同 speaker、≤1.5 秒且原状态为 `no_overlap`/`insufficient_overlap` 的空洞，不桥接 `ambiguous_overlap` 或不同 speaker 边界；首例桥接 14 个单元，展示覆盖 95.73%，`speaker_unknown` 45→31，speaker turns 89→67；原始声学覆盖仍单列为 93.80%。105 tests/ruff 通过。 |
| 2026-07-15 | T070 Streaming Sortformer 1 例接入 | 核验 471,367,680-byte v2.1 `.nemo` 与官方 SHA-256；新增 diarization schema、GPU/恢复运行器、RTTM、独立 ASR 映射器和保守重叠规则；1 例 280.704 秒音频 RTF 0.00777、峰值 reserved 750 MiB，候选 ASR 映射覆盖 93.80%，形成 89 个病例级 turns。101 tests/ruff 与 HTML JavaScript 语法通过；浏览器实例仍不可用。详见 `docs/t070_sortformer_diarization_pilot.md`。 |
| 2026-07-14 | T068–T070 完整对话、中文候选与 diarization 调研 | 1 例由 10 个窗口聚合为 1 个病例级审阅包；中文完整对话 LLM 候选实际生成 25 个 alternatives，4/4 span 有候选；确认 Sortformer 为独立组件并形成 1→5 例接入方案。97 tests/ruff 通过；浏览器实例仍不可用。详细见 `docs/t068_chinese_conversation_candidates_diarization.md`。 |
| 2026-07-14 | T051–T060 中文 1 例增量闭环 | 冻结匿名快照、恢复 Hybrid checkpoint、完成确定性短窗与绝对时间、30 秒和最短整例 confidence/5-best、中文实体 gating、候选和医生 HTML；95 tests/ruff 通过。详细见 `docs/t051_t060_chinese_asr_integration.md`。 |
| 2026-07-14 | T051 本地资产归位 | 将 40 例原始包迁入 `data/raw/remote_programming_40/`，Qwen 自动病历迁入 `data/external/remote_programming_40/`，Parakeet 权重归入 `data/external/asr_models/nemo/`；目录均受 Git 忽略规则保护。 |
| 2026-07-14 | T050 中文路线与数据盘点 | 完成 40 例聚合盘点、中文 schema 风险分析和 Parakeet 主路线调研；详细记录见专项文档和 `docs/task_records.md`。 |

## 专项文档入口

- 40 例数据盘点与迁移：`docs/remote_programming_40_dataset_assessment.md`
- 中文 ASR 技术路线：`docs/t050_chinese_asr_flow_research.md`
- 中文增量实现与 1 例验证：`docs/t051_t060_chinese_asr_integration.md`
- 完整对话、中文 LLM 候选与说话人分离：`docs/t068_chinese_conversation_candidates_diarization.md`
- Streaming Sortformer 1 例接入：`docs/t070_sortformer_diarization_pilot.md`
- 中文 5 例代理鲁棒性 pilot：`docs/t058_t066_chinese_pilot5_robustness.md`
- 中文 40 例全量工程报告：`docs/t061_chinese_all40_engineering.md`
- WSL/NeMo 环境：`docs/wsl_environment.md`
- ASR confidence schema：`docs/asr_confidence_schema.md`
- n-best 候选：`docs/t029_asr_nbest_candidates.md`
- 医学实体审阅：`docs/t038_medical_entity_review.md`
- 审阅/feedback/confirmed transcript：`docs/t030_t035_t036_review_workflow.md`
- 病例信息整理与质量评估：`docs/t041_case_summary_generation.md`、
  `docs/t042_case_summary_quality_evaluation.md`
- PriMock57 历史结果与任务流水：`docs/task_records.md`
