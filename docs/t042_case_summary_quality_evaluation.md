# T042 病例摘要质量评估：gold key facts 与 source-aware factuality

更新时间：2026-07-09

本文记录 T042 的方案 B 实现入口。T042 的主判据不是摘要表面流畅度，而是病例关键信息是否被保留、是否被输入 transcript 支持、以及错误能否回连到 ASR 置信度和医生审阅成本。

当前已完成：

- T042a：定义并实现 `gold_key_facts.jsonl` schema、校验工具和不含事实正文的聚合 summary。
- T042b：复用 T041 病例摘要生成链路，对 noisy ASR / confirmed transcript / reference oracle 三类输入生成同一 schema 的 consultation-level 病例摘要任务记录。
- T042c：接入轻量 ROUGE-L 辅助指标，用于横向看板，不作为主判据。
- T042d：接入 source-aware factuality B-lite，输出 supported / unsupported / contradicted / unverifiable、fact precision / recall / F1、critical fact recall 和 omission count。
- T042e：接入高风险错误类型统计和 `uncertainty_notes` 覆盖评估，检查 noisy ASR 低置信/证据不足/极性冲突/遗漏高风险事实是否被摘要不确定性说明覆盖。
- T042f：可选读取 ASR confidence JSONL 和 T035 confirmed transcript JSONL，把 summary fact / omitted gold fact 回连到 evidence pointer 对应的 ASR 词级颜色、待审 span 和审阅动作成本，并给出 noisy→confirmed 摘要质量收益。

当前仍需真实或人工生成的 `case_summary` 才能得到有效质量分数；如果 T041/T042b records 仍是 dry-run `prompt_ready`，T042c/T042d/T042e/T042f 会将其标为 skipped 或只输出成本/归因占位。

## 核心原则

- gold facts 来自 clean/reference transcript 或经人工确认的 reference note，不来自 noisy ASR 摘要本身。
- `canonical_fact` 只写短的规范化事实标签，例如“患者主诉腹痛”“否认便血”；不要粘贴完整问诊原文。
- `evidence_pointer` 只保存 sample/record、word index、time range、turn index 和短 cue；不要保存完整 transcript 句子。
- 聚合 summary 不包含 `canonical_fact`、完整 transcript、prompt 或未脱敏病例正文。
- 所有摘要和评估输出均为研究用途，不构成临床建议。

## `gold_key_facts.jsonl` 字段

每行一个 `GoldKeyFact`。必填/核心字段如下：

| 字段 | 说明 |
|---|---|
| `schema_version` | 固定为 `gold_key_fact/v1`。 |
| `fact_id` | 全局唯一事实 ID，建议格式：`<consultation_id>__<field>__NNN`。 |
| `bundle_id` | T042 gold bundle ID，建议用 `primock57:<consultation_id>:gold_key_facts:consultation`。 |
| `dataset` / `split` / `consultation_id` | 数据集与问诊定位信息。 |
| `field` | 对应 T041 摘要字段，如 `symptoms`、`medications`、`plan_mentioned`。 |
| `canonical_fact` | 短的规范化事实标签，不写完整 transcript。 |
| `polarity` | `present` / `absent` / `historical` / `planned` / `uncertain`。 |
| `severity` | `minor` / `major` / `safety_critical`。 |
| `source_channel` | `doctor` / `patient` / `mixed` / `unknown`。 |
| `evidence_pointer` | 证据指针；只写位置和短 cue，不写原文长句。 |
| `error_tags` | 可选高风险标签，如 `drug_name`、`negation_or_polarity`、`plan_or_follow_up`。 |

允许的 `field` 值与 T041 摘要 schema 对齐：

- `chief_complaint`
- `history_of_present_illness`
- `symptoms`
- `negated_or_absent_symptoms`
- `relevant_history`
- `medications`
- `tests_or_exam_mentioned`
- `assessment_mentioned`
- `plan_mentioned`

`negated_or_absent_symptoms` 必须使用 `polarity="absent"`；`plan_mentioned` 不应使用 `polarity="absent"`。

## `evidence_pointer` 规范

推荐字段：

```json
{
  "source_type": "reference_transcript",
  "sample_id": "demo_patient",
  "record_id": "record_demo_patient",
  "source_channel": "patient",
  "turn_index": 3,
  "word_start_index": 42,
  "word_end_index": 44,
  "start_sec": 12.4,
  "end_sec": 13.1,
  "cue": "symptom mention",
  "contains_full_transcript_text": false
}
```

其中 `cue` 只能是短标签，帮助人工复核快速定位；不要把原始问诊句子放进 `cue`。如果确实需要复核原文，应通过 `sample_id`、`word_start_index` / `word_end_index` 或时间戳回到本地受控数据文件查看。T042f 当前把 `word_start_index` / `word_end_index` 作为半开区间 `[start, end)` 连接到 ASR `asr_words`；若索引不可用或越界，会尝试用 `start_sec` / `end_sec` 做时间重叠回连。

## 示例 JSONL 行

下面是合成示例，不对应真实患者：

```json
{"schema_version":"gold_key_fact/v1","fact_id":"demo__symptoms__001","bundle_id":"primock57:demo:gold_key_facts:consultation","dataset":"primock57","split":"seed_asr_v0","consultation_id":"demo","field":"symptoms","canonical_fact":"患者报告腹痛","polarity":"present","severity":"major","source_channel":"patient","evidence_pointer":{"source_type":"reference_transcript","sample_id":"demo_patient","source_channel":"patient","word_start_index":12,"word_end_index":14,"cue":"symptom mention","contains_full_transcript_text":false},"error_tags":["medical_term","asr_noise_sensitive"],"normalized_terms":["腹痛"],"annotator_role":"researcher","reviewed":true,"research_use_only":true}
```

真实标注文件建议放在：

```text
data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl
```

该目录默认不纳入 Git。若需要提交示例，只能提交合成样例，不能包含真实未脱敏病例内容。

## 校验命令

默认路径：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/validate_gold_key_facts.py
```

指定输入：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/validate_gold_key_facts.py `
  --input-jsonl data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl
```

默认输出：

```text
outputs/primock57/t042_case_summary_evaluation/primock57_t042_gold_key_facts_summary.json
outputs/primock57/t042_case_summary_evaluation/t042_gold_key_facts_validation_run.json
```

summary 只包含字段、极性、严重程度、声道和高风险标签计数，不包含 `canonical_fact` 正文。

## 后续接法

T042b 已让 T041 对三类输入生成同一 schema 的 consultation-level 摘要：

- `input_variant="noisy_asr"`
- `input_variant="confirmed_transcript"`
- `input_variant="reference_oracle"`

默认 dry-run 只导出 prompt-ready JSONL，不调用外部 LLM：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --input-variants noisy_asr confirmed_transcript reference_oracle `
  --output-dir outputs/primock57/t042_case_summary_variant_generation `
  --records-name primock57_t042_case_summary_variant_records.jsonl `
  --summary-name primock57_t042_case_summary_variant_summary.json `
  --run-config-name t042_case_summary_variant_generation_run.json
```

输出包括：

```text
outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl
outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_summary.json
outputs/primock57/t042_case_summary_variant_generation/t042_case_summary_variant_generation_run.json
```

本轮 dry-run 结果：2 个 consultation × 3 个 `input_variant` = 6 条 prompt-ready 任务记录；三类输入各覆盖 2 个 consultation、3 条 source ASR record；`records_skipped=0`。聚合 summary 不包含 transcript 或 prompt 正文。

逐条 records 会记录：

- `input_variant`
- `prompt_version="case_summary_prompt/v2_input_variant_aware"`
- `model`（dry-run 为 `null`，`--run-llm` 后记录模型元数据）
- `research_use_only=true`
- `clinical_use_warning`

## T042c/T042d/T042e/T042f 摘要质量评估入口

评估脚本：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_case_summaries.py `
  --summary-records-jsonl outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl `
  --gold-key-facts-jsonl data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl
```

若要启用 T042f ASR 置信度归因与审阅成本收益，再提供 ASR confidence 和 T035 confirmed transcript：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_case_summaries.py `
  --summary-records-jsonl outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl `
  --gold-key-facts-jsonl data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl `
  --asr-confidence-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl `
  --confirmed-transcripts-jsonl outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.jsonl
```

默认输出：

```text
outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_quality_records.jsonl
outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_fact_evaluations.jsonl
outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_quality_summary.json
outputs/primock57/t042_case_summary_evaluation/t042_case_summary_quality_evaluation_run.json
```

评估逻辑：

- 从 T041/T042b `case_summary` 的结构化字段抽取短事实标签，不评估完整 transcript。
- ROUGE-L：把结构化摘要事实拼接后，与同一 consultation 的 gold `canonical_fact` 标签拼接做轻量 ROUGE-L；该指标只作为辅助。
- B-lite factuality：对每条 summary fact 和 gold fact 做 ROUGE-L / normalized term coverage 匹配，并结合字段与极性启发式判定：
  - `supported`：匹配分数达到阈值且极性兼容；
  - `contradicted`：匹配到相似 gold fact，但否定/极性冲突；
  - `unsupported`：有 gold facts，但没有足够支持；
  - `unverifiable`：该 record 没有可用 gold facts。
- gold recall：同一 gold fact 只要被任一 summary fact 支持即视为 recovered，用于计算 recall、critical fact recall 和 omission count。
- 高风险错误：对 unsupported / contradicted / unverifiable summary facts 以及 omitted gold facts 统计风险族，包括 `negation_or_polarity`、`drug_name`、`medication_dose_or_route`、`test_or_exam`、`plan_or_follow_up`、`speaker_attribution`、`assessment_or_diagnosis`、`medical_term`、`safety_critical_fact` 等。
- 不确定性覆盖：对 `case_summary.uncertainty_notes` 只输出 note 数量和类别计数，不输出 note 正文；记录 `coverage_status`，区分 `missing`、`generic_note_present` 和 `covered_by_category`。noisy ASR 中有 `uncertain_span_count>0`、事实 unsupported/contradicted/unverifiable 或遗漏高风险 gold fact 时，会要求 uncertainty notes 覆盖。
- ASR 置信度归因：对 summary fact 的 best gold fact、以及 omitted gold fact，使用 `evidence_pointer` 回连到 ASR source record 的词级 `green/yellow/red/unknown`、重叠 `uncertain_spans`、T035 `manual_edit` / `select_alternative` / `accept_asr` 等动作计数。
- 错误来源粗分类：对 unsupported / contradicted / unverifiable facts 输出 `summary_error_attribution`，区分 `asr_induced_possible`、`review_modified_evidence_span`、`summary_generation_polarity_error_possible`、`model_hallucination_possible` 等启发式类别。
- 审阅收益：当同一 consultation 同时有 `noisy_asr` 与 `confirmed_transcript` 摘要质量记录时，输出 fact F1 / recall / critical recall 改善、omission reduction、fact error reduction，以及每个 review span / changed span / manual edit 对应的 fact F1 改善。

默认 `fact_evaluations.jsonl` 不写入 `summary_fact_text`，只写 hash、字段、匹配分数、best gold fact id 和标签，避免把病例短事实重复扩散到报告中。若需要人工复核可显式加：

```powershell
--include-fact-text
```

开启后 fact-level JSONL 会包含生成摘要事实短标签，应按受控研究数据处理，默认不提交 Git。

T042d/T042e/T042f 当前输出：

- fact precision / recall / F1；
- critical fact recall；
- unsupported / contradicted / unverifiable fact count；
- omission count；
- high-risk error tag counts（来自 matched/omitted gold fact 的标签）。
- high-risk error type counts（来自 summary field、gold fact tag/severity 和 omission 的风险族）；
- uncertainty note summary，包括 required/missing record count、loose/category 覆盖率、expected/missing reason counts 和 note category counts。
- fact-level `confidence_attribution`：只含 record/sample/span id、颜色计数、动作计数和 cue hash，不含事实正文或 transcript；
- record-level `confidence_attribution` / `review_cost_attribution`：统计 source record 数、fact evidence 风险颜色分布、overlapping review span、changed span、action summary；
- summary-level `confidence_attribution_summary`、`review_cost_attribution_summary` 和 `review_benefit_summary`：用于比较 raw/noisy 摘要与 confirmed 摘要的质量收益和审阅成本。

## 当前限制

- B-lite 是确定性词面/术语匹配和极性启发式，不替代人工临床事实核查。
- T042f 的 ASR-induced / model hallucination 分类是启发式归因：低置信/待审 span 与事实错误共现时标为可能 ASR-induced；没有 evidence match 或 gold 支持时标为可能 hallucination。最终错误来源仍需人工复核。
- ROUGE-L 使用 gold fact 标签而非人工 reference summary，只能辅助横向比较。
- 当前真实 `gold_key_facts.jsonl` 仍应放在 `data/processed/`；没有 gold 或没有生成摘要时，评估会输出 skipped / unverifiable，而不是伪造质量分数。
