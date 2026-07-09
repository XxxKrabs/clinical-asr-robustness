# 项目 TODO 与当前交接板

更新时间：2026-07-09

本文档是新对话/新任务的首要入口，只保留“现在该做什么”和必要操作提醒。历史任务流水、早期路线演化、详细产出和失败案例见 `docs/task_records.md`；除非需要追溯决策来源，不要默认完整阅读历史归档。

## 维护规则

- 工作语言优先使用中文。
- 开始较大的实现、实验或文档整理前，先读本文件；再按当前任务需要读取 README、专项文档或配置。
- 完成较完整任务后：
  - 更新本文件的当前状态、下一步、阻塞/待确认和最近完成；
  - 在 `docs/task_records.md` 追加较完整记录。
- 不要记录真实患者隐私、未脱敏病例正文、本地密钥或受限数据细节。
- Python、pytest、ruff、NeMo、ASR 或实验脚本默认使用 WSL Conda 环境 `clinical-asr`。

## 环境速记

推荐直接调用解释器：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python
```

常用验证：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
```

如果 Codex 沙箱中直接调用 WSL Python 出现权限/沙箱相关失败，或出现“发行版不存在”但 `wsl.exe -l -v` 能看到 `Ubuntu-22.04`，不要反复探索；应申请提升权限，建议可复用前缀：

```text
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python
```

更多环境细节见 `docs/wsl_environment.md`。

## 当前主线

项目近期主线：

**音频 → ASR → noisy transcript + ASR 词级置信度（可由 CTC frame posterior/log_probs entropy 聚合）+ span/segment 派生风险 → 医学实体优先绿/黄/红高亮 → 医生点击 top-k/n-best 候选并确认 → confirmed transcript → 下游病例信息整理鲁棒性评估。**

2026-07-01 起，置信度主要放在 ASR 输出层；文本 repair、LLM/规则候选和反馈微调只作为后续辅助扩展。

2026-07-07 起，审阅逻辑改为 **医学实体优先**：先用 LLM 从 ASR transcript 中识别疾病、症状、药物、检查等医学实体；只有医学实体词保留置信度颜色并进入候选/反馈流程，非医学词作为普通黑字上下文显示。详见 `docs/t038_medical_entity_review.md`。

当前可运行链路：

```text
T028/T043 ASR word confidence
  → T038 医学实体 gating
  → T029 n-best/top-k 候选
  → T030/T036 审阅样本与 HTML demo
  → T035 confirmed_transcript
  → T040 raw/confirmed/reference 下游指标看板
  → T041 noisy ASR → 病例摘要生成 V0
```

日常复跑入口已收敛为 `scripts/run_asr_review_pipeline.py`；默认复用已有 T028/T037 输出并自动生成 `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`。

截至 T041，第一周目标中的“音频数据 → ASR → noisy transcript + 置信度 → 医学实体优先医生交互选择 + 交互界面设计 + ASR 输出层初评/闭环记录 → confirmed/downstream 初评”已有可运行骨架。T040 已补上 raw ASR / confirmed / reference 的第一版全流程效果看板；T041 已把 noisy ASR 接到病例摘要下游任务，并已用 `--run-llm` 生成第一版 consultation-level 结构化病例摘要。当前 confirmed 仍来自 simulated accept_asr，尚不能代表真实医生确认质量。

2026-07-08 调研确认：当前候选覆盖极窄主要是方案/策略导致，而不是 n-best 文件没读到。T038 会先把待审阅范围从全部黄/红词收缩到“非 green 医学实体”，T029 又只在 sequence-level beam 与这些 span 局部发生差异时生成 span 候选；当前 3 条 record 中 T028 原始低/中置信 span 为 108 个，T038 后只剩 3 个医学实体待审 span，T037 虽有 15 个 sequence 候选，但 T029 span 候选为 0。T039 已完成第一版候选覆盖改进。2026-07-09 新增 T043：在不训练模型、不替换 NeMo FastConformer-CTC 主干的前提下，支持保存/读取 frame-level log_probs/posterior，并按 CTC entropy pipeline 聚合到 word-level confidence；下一步 P0 转向真实样本复跑、医生审阅流程/确认成本指标。

## 当前焦点与下一步

| 优先级 | 任务编号 | 状态 | 下一步/验收标准 |
|---|---|---|---|
| P0 | T043 | 已完成/待实跑 | 已新增 CTC frame posterior/log_probs → frame entropy/max-prob confidence → token confidence → word confidence 的项目侧流水线；T028 可用 `--word-confidence-source ctc_frame_distribution --save-frame-distributions` 从 NeMo Hypothesis frame log_probs 重算 `asr_words[].confidence`，并保存 `.npz` artifact。下一步用真实 PriMock57 样本实跑，检查 `word_alignment_status_counts` 是否主要为 `aligned`，再复跑 T038/T029/T036/T031 对比医学 span 风险定位变化。详见 `docs/t043_ctc_word_confidence.md`。 |
| P0 | T039 | 已完成 | 已新增医学词表/模糊匹配辅助候选：ASR n-best 仍作为原生候选保留；无 ASR span candidate 的医学实体待审 span 会补充 `source="medical_lexicon_aux_candidate"` 的辅助候选，并在 metadata 中标注 `generated_by="T039"`、`reference_used=false`。本轮 T029/T030 显示 spans_with_candidates 从 0/3 提升到 3/3；T031 exact reference coverage 仍为 0/3，说明候选可用性改善但正确性仍需后续优化。详见 `docs/t039_candidate_coverage_improvement.md`。 |
| P0 | T044 | 已完成/待实跑 | 已新增黄/红词级 LLM 候选逻辑：词级置信度、颜色阈值和 T038 医学实体 gating 不变；T029 默认导出 prompt-ready JSONL，显式 `--run-llm-candidates` 时调用 OpenAI-compatible LLM。每个 prompt 包含目标词、局部上下文窗口和医学词表参考，返回约 3 个 `scope="word"` 候选，并在 metadata 标注 `generated_by="T044"`、`source="llm_word_candidate"`、`reference_used=false`。下一步需用真实 PriMock57 样本实跑，人工检查候选正确性、延迟和医生选择/编辑成本。 |
| P0 | T019/T023 | 进行中 | T040 已统计第一版 review cost；下一步需要导出真实研究者/医生反馈，区分真实医生、研究者和模拟审阅者反馈，并把候选来源、accept_asr/select_alternative/manual_edit/reject/unable_to_judge 的操作成本纳入报告。 |
| P1 | T041/T040/T007/T008 | 已生成 V0 摘要 | 已接入 V0 医学概念 token 抽取 precision/recall/F1，并用 `--run-llm` 基于 noisy ASR 生成 2 条 consultation-level 结构化病例摘要；下一步设计 noisy/confirmed/reference 的病例摘要信息保持评估，并人工审核字段遗漏、幻觉和 ASR 噪声导致的错误。 |
| P1 | T042 | 待实现 | 建立病例摘要质量评估：以 reference transcript/人工 key facts 为 gold，对 noisy/confirmed/reference 三类输入生成摘要，计算字段级信息保持、unsupported/contradicted facts、否定/药物/计划错误、结构合规和人工审核成本。 |
| P0 | T040 follow-up | 待办 | 从 HTML demo 导出一份真实研究者反馈，不再全部 accept_asr；用 T035 生成新的 confirmed transcript 后复跑 T040，观察 WER/MC-WER/F1 改善和 manual_edit 成本。 |
| P1 | T038 follow-up | 待优化 | 用 T031/T039/T040 结果回看医学实体误报与漏报；当前仍有疑似过宽/误报实体进入待审 span，需继续优化 entity postprocess 和高价值 green 医学实体点击检查策略。 |
| P3 | T006/T018 | 暂缓 | 文本 repair 扩展；仅在 ASR top-k 不足时作为辅助候选生成。 |

T039 本轮完成情况：

1. 保留 T029 sequence-level ASR n-best 与 span diff 逻辑，不改变 `nemo_beam` 等 ASR-native source 的含义。
2. 新增 T039 医学词表/模糊候选兜底，仅对“医学实体待审 span 且无 ASR-native span candidate”的情况生效。
3. 新增 `configs/medical_candidate_lexicon.example.json`；后续可按数据集扩展症状、药物、解剖部位、检查、否定相关短语等候选词表。
4. T029 run summary 新增 `span_alternatives_by_source`、`spans_with_alternatives_by_source`；T031 summary 新增 source-level exact coverage。
5. 本轮复跑结果：T029/T030 spans_with_candidates = 3/3；T031 exact reference coverage = 0/3，提示辅助候选不能替代医生编辑/拒绝/无法判断。


T044 本轮完成情况：

1. 保持 `asr_words[].confidence`、`confidence_level`、T038 医学实体 gating 和绿/黄/红显示逻辑不变。
2. 新增 T044 词级 LLM 候选：只为待审 span 内 `yellow`/`red` 的目标词构造 prompt；prompt 明确包含当前目标词、适量局部上下文和医学词表参考。
3. T029 默认导出 `primock57_llm_word_candidate_prompts.jsonl` 作为 prompt-ready 记录；只有显式传入 `--run-llm-candidates` 才实际访问外部 OpenAI-compatible API。
4. LLM 返回候选写入 `scope="word"` 的 `asr_alternatives`，并回填到所属 `uncertain_spans[].alternative_ids`；T035 回放已支持 word-level 候选只替换 span 内目标词。
5. 验证：`pytest --basetemp=.pytest_tmp` 62 passed；targeted `ruff check` 通过；T029 和一键 pipeline 的 `--help` 均正常。

已完成主干压缩索引：T025/T026/T027/T028/T029/T030/T031/T032/T035/T036/T037/T038/T039/T040/T041/T043/T044 均已完成或已启动 V0；详细产出、验证命令和历史细节见 docs/task_records.md。

## T042 病例摘要质量评估方案（待实现）

目标：判断 T041 生成摘要是否真的保留病例信息，而不是只看语言是否通顺。V0 评估以 reference transcript 或人工 key facts 为 gold，对 noisy ASR、confirmed transcript、reference transcript 三类输入分别生成摘要，比较质量差异和 confirmed transcript 带来的收益。

推荐指标：

- 结构合规：JSON 可解析率、必需字段存在率、字段类型正确率、是否只输出研究用摘要。
- 字段级信息保持：按 `chief_complaint`、`history_of_present_illness`、`symptoms`、`negated_or_absent_symptoms`、`relevant_history`、`medications`、`tests_or_exam_mentioned`、`assessment_mentioned`、`plan_mentioned` 建 gold key facts，计算 precision / recall / F1；重点单列症状、否定症状、药物、检查、assessment、plan。
- 事实一致性：把摘要拆成 atomic claims，标注 supported / unsupported / contradicted / unclear，报告 unsupported fact rate、contradiction rate、hallucination count per case。
- 临床高风险错误：单列否定词错误、药名/剂量/用法错误、诊疗计划越界、说话人归因错误、把不确定检查或诊断写实等；报告 safety-critical error count。
- 鲁棒性收益：比较 `score_confirmed - score_noisy`、`score_reference - score_noisy`，可用 gap closure = `(confirmed - noisy) / (reference - noisy)`；若当前 confirmed 仍是 simulated accept_asr，预期收益应接近 0。
- 不确定性质量：检查 `uncertainty_notes` 是否覆盖 ASR 噪声、低置信 span 和含糊医学术语；统计应标未标/误标不确定性。
- 人工审核成本：记录每条摘要需修改字段数、人工编辑字数、审核时间、严重错误数；用于评估医生/研究者确认后的下游收益是否值得。

V0 评测流程：

1. 从 T041 records 抽取 `case_summary`，不把完整 transcript 写入公开文档。
2. 基于 clean/reference transcript 人工建立每个 consultation 的 gold key facts 表；字段包括症状、否定症状、药物/治疗、检查、诊断倾向、计划、相关病史/社会史。
3. 将生成摘要拆成 atomic claims，人工或 LLM-assisted 初标后人工复核：supported / unsupported / contradicted / unclear，并标严重程度 minor/major/safety-critical。
4. 先对当前 2 条 noisy ASR 摘要做人工 pilot，重点核查已发现的疑点：`止泻药` 是否为计划越界，`皮肤检查显示皮疹` 是否把不确定检查写实。
5. 生成 confirmed/reference 两套摘要后复跑同一评测，输出 summary JSON/CSV：字段级 P/R/F1、unsupported/contradicted facts、关键错误类型、审核成本和 robustness gain。
6. 扩展到更多 PriMock57 样本后，至少双人标注一小批，报告一致性；最终论文中同时报告自动指标和人工 error taxonomy。

阶段验收标准：先完成 2 条样本的 gold key facts 与人工审核表；实现 `scripts/evaluate_case_summaries.py` 后输出可复跑的 `outputs/primock57/t042_case_summary_evaluation/` 报告。V0 不把 ROUGE/BLEU 作为主指标，只可作为附录参考。

## 阻塞/待确认

- 当前无 ASR/n-best 读写层阻塞；T039 已完成医学实体辅助候选兜底。T043 已实现 CTC frame-derived word confidence，但尚未对真实 PriMock57 音频复跑，下一步需检查 token→word 对齐状态、artifact 体积和医学实体待审 span 分布。新的主要风险是：辅助候选可用性已提升，但 exact reference coverage 仍为 0/3，且 T038 仍有疑似实体误报/过宽 span，需要后续优化实体 gating 与医生操作成本指标。
- T044 LLM 候选真实调用仍需项目 `.env` 或环境变量提供 API 配置；不得把 API key 写入代码、文档、运行记录或 Git。LLM 候选是 ASR 审阅辅助，不是 ASR 原生 n-best/top-k，也不代表医学正确答案。
- T040 本轮使用 T035 simulated `accept_asr` confirmed transcript 作为基线：raw ASR → confirmed 的 WER/MC-WER/医学概念 F1 改善均为 0，只代表评估链路可运行，不代表真实医生确认或质量改善。
- T041 已实际调用 LLM 生成第一版病例摘要，`status_counts={"generated": 2}`；`records.jsonl` 仍包含完整 noisy ASR transcript、prompt 和模型输出，默认只放在 `outputs/`，不要提交 Git 或写入公开文档。当前摘要仅来自 noisy ASR，尚未完成 noisy/confirmed/reference 对照评估。
- T038 真实 LLM 抽取需要项目根目录 `.env` 或环境变量提供 `API_KEY`/`BASE_URL`/`MODEL_ID` 或 `PARATERA_*`；不要把 API key 写入代码、文档正文、运行记录或 Git。
- T031 初评显示 yellow 错误率明显高于 green，但 green 仍有错误；当前阈值仍不能视作临床级校准结果。
- T039/T044 后候选可用性已提升：T039 提供 span-level 词表/模糊兜底，T044 提供 yellow/red word-level LLM 候选；但这些辅助候选仍不能视作正确答案，必须保留 manual_edit/reject/unable_to_judge 并做真实样本质量评估。
- T035/T036 第一版可由研究者或模拟审阅者操作，不要求真实医生参与；界面输出是研究 demo，不构成临床建议。
- PriMock57 本地数据、processed 输出和 ASR 结果默认不提交 Git；不要写入未脱敏正文或隐私信息。
- 后续脚本不得依赖外部 `D:\...\Speech-main`；只能使用 project 内 `third_party/speech_main/` 和 `data/external/asr_models/nemo/`。
- DISPLACE-M 仍是后续扩展数据集，接入前需确认许可、注册要求和字段结构。
- T040 已接入 V0 医学概念 token 抽取 F1；它是可复跑代理指标，不等同于最终症状/药物/检查实体抽取或病例摘要质量评估。

## 最近完成

| 日期 | 任务 | 摘要 |
|---|---|---|
| 2026-07-09 | T044 黄/红词级 LLM 候选逻辑 | 保持词级置信度与 T038 gating 不变，新增基于目标词、局部上下文和医学词表参考的 LLM 候选生成；T029 默认导出 prompt-ready JSONL，`--run-llm-candidates` 时调用 OpenAI-compatible API，写入 `scope="word"` 候选；T035 回放支持只替换目标词。验证：全量 `pytest --basetemp=.pytest_tmp` 62 passed，targeted `ruff check` 通过。 |
| 2026-07-09 | T043 CTC posterior/entropy 词级置信度流水线 | 新增 `src/clinical_asr_robustness/ctc_word_confidence.py`，支持从 CTC frame logits/log_probs/posterior 计算 entropy/max-prob frame confidence，经 CTC token collapse 与 BPE word span 聚合成 `asr_words[].confidence`；T028 新增 `--word-confidence-source ctc_frame_distribution` 与 `--save-frame-distributions`，可保存 `.npz` frame artifact；验证目标测试 9 passed、targeted `ruff check` 通过。 |
| 2026-07-08 | T042 病例摘要质量评估方案入 TODO | 明确摘要质量不以通顺度或 ROUGE/BLEU 为主，而以字段级信息保持、事实一致性、临床高风险错误、uncertainty notes、noisy/confirmed/reference 鲁棒性收益和人工审核成本为核心；下一步实现 gold key facts 表和 `scripts/evaluate_case_summaries.py`。 |
| 2026-07-08 | T041 `--run-llm` 生成第一版病例摘要 | 使用 `.env` 中 OpenAI-compatible API 配置运行 `scripts/generate_case_summaries.py --run-llm`，基于 noisy ASR 生成 2 条 consultation-level 结构化病例摘要，模型记录为 `Qwen3-Coder-Plus`，summary 中 `status_counts={"generated": 2}`。本轮仅生成 noisy ASR 摘要，尚未做 confirmed/reference 对照和质量评估。 |
| 2026-07-08 | T041 noisy ASR → 病例摘要生成下游任务 | 新增 `src/clinical_asr_robustness/case_summary_generation.py`、`scripts/generate_case_summaries.py` 和测试；默认按 `consultation_id` 合并 doctor/patient 分声道 noisy ASR，生成病例摘要 prompt-ready JSONL，支持后续 `--run-llm` 调用 OpenAI-compatible API。本轮 dry-run 生成 2 个 consultation-level input units、覆盖 3 条 ASR record；新增 `docs/t041_case_summary_generation.md`。 |
| 2026-07-08 | T040 confirmed transcript 与下游鲁棒性评估 | 新增 `src/clinical_asr_robustness/confirmed_downstream_evaluation.py`、`scripts/evaluate_confirmed_downstream.py` 和测试；比较 raw ASR / confirmed / reference 的 WER、MC-WER、V0 医学概念 token 抽取 precision/recall/F1，并统计 review cost。当前 simulated accept_asr 基线 raw→confirmed 改善为 0；新增 `docs/t040_confirmed_downstream_evaluation.md`。 |
| 2026-07-08 | T039 医学实体辅助候选覆盖改进 | 新增医学词表/模糊匹配辅助候选兜底；默认在 T029 中启用，且只对无 ASR-native span candidate 的医学实体待审 span 生效。复跑 T029/T030 后 spans_with_candidates 从 0/3 提升到 3/3；T031 exact reference coverage 仍为 0/3；新增 `docs/t039_candidate_coverage_improvement.md`，验证 `pytest` 47 passed、`ruff check .` 通过。 |
| 2026-07-08 | T039 候选覆盖问题调研与方案选定 | 诊断候选覆盖窄的主因：T038 医学实体 gating 将 T028 原始 108 个低/中置信 span 收缩为 3 个非 green 医学实体 span；T029 只把 sequence-level n-best 中与 span 局部发生差异的 beam 裁成 span 候选，因此 15 个 sequence 候选最终 0 个 span 候选。选定 T039：保留 ASR n-best 为原生候选，新增医学词表/模糊匹配/可选 LLM 辅助候选兜底，并明确标注来源。 |
| 2026-07-07 | T032 ASR 输出层最小闭环实验记录 | 新增 `docs/t032_asr_output_min_loop.md`；汇总 T028→T037→T038→T029→T030/T036→T035→T031 的输入、输出、指标和局限；用 3 条模拟 `accept_asr` 反馈跑通 T035，生成 confirmed transcript run summary；修复 T035 反馈 JSONL 读取 UTF-8 BOM 兼容，验证 `tests/test_review_workflow.py` 6 passed、targeted `ruff check` 通过。 |
| 2026-07-07 | T031 ASR noisy / confidence / top-k 初评 | 新增 `scripts/evaluate_asr_quality.py` 与 `src/clinical_asr_robustness/asr_quality_evaluation.py`；读取 PriMock57 TextGrid reference，对当前 ASR noisy 计算 WER/MC-WER、confidence 分桶错误率、ECE/NCE、医学错误覆盖和 top-k 覆盖；3 条 record 初评 micro WER 0.3405、micro MC-WER 0.2526、yellow 错误率 0.4785、green 错误率 0.1543、span top-k 覆盖 0/3；验证 `pytest` 45 passed、`ruff check .` 通过。 |
| 2026-07-07 | 新增 ASR 审阅一键流水线入口 | 新增 `scripts/run_asr_review_pipeline.py`，默认复用 T028/T037 并串起 T038→T029→T030→T036 生成最终 HTML；文档补充日常命令、`--run-asr`、`--dry-run`、`--apply-feedback` 等用法；验证默认链路跑通，`ruff check scripts/run_asr_review_pipeline.py` 通过。 |
| 2026-07-07 | 优化 T038 医学实体后处理与关键词兜底 | 收紧 LLM prompt；在 gating 前裁剪 do/you/mean/your/what/kind/of 等普通词、丢弃非医学误报；新增 diarrhea/pain/vomiting/feverish/temperature/blood/asthma/inhalers/medications/tummy/weak/shaky/stools/fluids/symptoms 等关键词补漏；验证 `ruff check .` 通过，`pytest` 42 passed。 |
| 2026-07-07 | 重跑 T038→T036 医学实体优先审阅 demo | 修正本地 `.env` 的 `MODEL_ID` 写法后，用 `Qwen3-Coder-Plus` 实际调用 LLM 抽取医学实体，并串起 T038→T029→T030→T036；生成并打开 `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`。 |
| 2026-07-07 | T038 医学实体优先 ASR 审阅范围 gating | 新增 LLM 医学实体抽取、实体到 ASR word 对齐、非医学词黑字显示、医学实体限定候选/反馈流程；验证 `ruff check .` 通过，`pytest` 40 passed。 |
| 2026-07-07 | 精简 `docs/todo.md` | 将早期冗余任务表、长路线说明和较久完成记录压缩到当前入口；详细记录继续放在 `docs/task_records.md`。 |

更早完成记录见 `docs/task_records.md`。

## 专项文档入口

- WSL 环境：`docs/wsl_environment.md`
- ASR confidence schema：`docs/asr_confidence_schema.md`
- NeMo confidence 导出：`docs/t028_nemo_confidence_export.md`
- 医学实体 gating：`docs/t038_medical_entity_review.md`
- ASR noisy / confidence / top-k 初评：`docs/t031_asr_quality_evaluation.md`
- ASR 输出层最小闭环实验记录：`docs/t032_asr_output_min_loop.md`。
- confirmed/downstream 全流程效果看板：`docs/t040_confirmed_downstream_evaluation.md`
- noisy ASR → 病例摘要生成：`docs/t041_case_summary_generation.md`
- 候选覆盖改进：`docs/t039_candidate_coverage_improvement.md`
- ASR n-best 候选：`docs/t029_asr_nbest_candidates.md`
- CTC posterior/entropy 词级置信度：`docs/t043_ctc_word_confidence.md`
- 审阅 demo / feedback / confirmed transcript：`docs/t030_t035_t036_review_workflow.md`
- PriMock57 manifest：`docs/primock57_asr_manifest.md`
