# T041 noisy ASR → 病例摘要生成下游任务

更新时间：2026-07-08

本文记录第一版“noisy transcript → 病例摘要”的下游任务接入。所有生成内容仅用于研究评估，不构成临床建议；聚合 summary 不包含完整 transcript 或 prompt 正文。

## 目标

T040 已经能比较 raw ASR / confirmed transcript / reference 在 WER、MC-WER 和轻量医学概念 token 抽取上的差异。T041 进一步把当前 ASR noisy transcript 接到更贴近论文目标的病例信息整理任务：

```text
ASR noisy transcript
  → consultation-level 输入构造
  → 病例摘要 prompt
  → 可选 LLM 生成结构化病例摘要
```

V0 先解决“接口打通”“可复跑输入产物”和第一版 LLM 摘要生成：

- 默认按 `consultation_id` 合并 doctor/patient 分声道 ASR record；
- 在 prompt 中保留 `[doctor]` / `[patient]` 声道标签；
- 输出结构化 `case_summary` JSON schema；
- 默认 dry-run，只生成 `prompt_ready` JSONL，不调用外部 LLM；
- 加 `--run-llm` 可调用 OpenAI-compatible Chat Completions API，并已生成第一版 noisy ASR 病例摘要。

## 实现文件

- 模块：`src/clinical_asr_robustness/case_summary_generation.py`
- 脚本：`scripts/generate_case_summaries.py`
- 测试：`tests/test_case_summary_generation.py`

结构化病例摘要字段包括：

- `summary_text`
- `chief_complaint`
- `history_of_present_illness`
- `symptoms`
- `negated_or_absent_symptoms`
- `relevant_history`
- `medications`
- `tests_or_exam_mentioned`
- `assessment_mentioned`
- `plan_mentioned`
- `uncertainty_notes`

提示词要求模型严格基于 noisy ASR transcript，不新增事实，不给出新的诊疗建议；如果 ASR 噪声明显或信息不确定，应写入 `uncertainty_notes`。

## 运行命令

默认只生成 prompt-ready JSONL：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py
```

默认输入：

```text
outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl
```

默认输出：

```text
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_records.jsonl
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_summary.json
outputs/primock57/t041_case_summary_generation/t041_case_summary_generation_run.json
```

如果要实际生成病例摘要，可在确认 `.env` 已配置 `API_KEY` / `BASE_URL` / `MODEL_ID` 后运行：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py --run-llm
```

如需逐条 ASR record 生成而不是按问诊合并：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py --group-by record
```

## 本次 `--run-llm` 结果

评估时间：2026-07-08。已调用 OpenAI-compatible API，对当前 2 个 consultation-level 输入生成第一版结构化病例摘要：

| 指标 | 数值 |
|---|---:|
| input units | 2 |
| source ASR records | 3 |
| group_by | consultation |
| status | generated: 2 |
| source channels | doctor: 2, patient: 1 |
| transcript word count | total 1967, min 816, max 1151 |
| uncertain span count | 3 |
| model | Qwen3-Coder-Plus |

输出位置：

```text
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_records.jsonl
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_summary.json
outputs/primock57/t041_case_summary_generation/t041_case_summary_generation_run.json
```

本轮只生成 noisy ASR 输入对应的病例摘要；尚未生成 confirmed/reference 对照摘要，也尚未做结构化字段级质量评估。

## 本次 dry-run 结果

评估时间：2026-07-08。默认 dry-run 未调用外部 LLM，仅生成 prompt-ready 输入：

| 指标 | 数值 |
|---|---:|
| input units | 2 |
| source ASR records | 3 |
| group_by | consultation |
| status | prompt_ready: 2 |
| source channels | doctor: 2, patient: 1 |
| transcript word count | total 1967, min 816, max 1151 |
| uncertain span count | 3 |

隐私与安全：

- `records.jsonl` 包含完整 noisy ASR transcript 和 prompt，默认位于 `outputs/`，不应提交 Git；
- `summary.json` 不包含完整 transcript 或 prompt；
- 文档和 TODO 不记录病例正文、真实患者信息或 API key。

## 当前局限

1. V0 合并粒度是 consultation-level，但 doctor/patient 仍是声道级拼接，不是精确 turn-level 对齐。
2. 当前第一版摘要只基于 noisy ASR 生成，尚未与 confirmed transcript 或 reference transcript 的摘要进行对照。
3. 第一版 LLM 摘要仍需要人工检查结构化字段，再设计与 reference note 或 reference transcript 的信息保持指标。
4. 生成病例摘要是研究输出，不得视作临床建议。

## 下一步

1. 新增病例摘要质量评估：
   - noisy ASR / confirmed / reference 三类输入分别生成病例摘要；
   - 比较症状、否定症状、药物、检查、assessment、plan 等字段的信息保持；
   - 记录 hallucination、遗漏、ASR 噪声导致的错误。
2. 在真实研究者反馈后，复跑 T035/T040/T041，观察 confirmed transcript 是否改善病例摘要质量。

## 验证

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：5 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_generation.py scripts/generate_case_summaries.py tests/test_case_summary_generation.py`：All checks passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py`：成功生成 T041 prompt-ready summary；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py --run-llm`：成功生成 2 条 consultation-level 结构化病例摘要，summary 中 `status_counts={"generated": 2}`。

## 2026-07-09 T042b 三类输入对齐更新

T041 入口现已支持通过 `--input-variants` 对 noisy ASR、confirmed transcript 和 reference oracle 生成同一 schema 的 consultation-level 病例摘要任务记录。逐条 records 会记录 `input_variant`、`prompt_version`、`model`（dry-run 为 `null`，`--run-llm` 后记录模型元数据）、`research_use_only` 和 `clinical_use_warning`。

T042b dry-run 命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --input-variants noisy_asr confirmed_transcript reference_oracle `
  --output-dir outputs/primock57/t042_case_summary_variant_generation `
  --records-name primock57_t042_case_summary_variant_records.jsonl `
  --summary-name primock57_t042_case_summary_variant_summary.json `
  --run-config-name t042_case_summary_variant_generation_run.json
```

本轮 dry-run 生成 6 条 prompt-ready consultation-level 任务记录：三类 `input_variant` 各 2 条，合计复用 9 条 source record，`records_skipped=0`。聚合 summary 不包含 transcript 或 prompt 正文；records JSONL 含完整 transcript 和 prompt，默认只放在 `outputs/`，不提交 Git。

## 2026-07-13 字段条件化说话人软权重

病例摘要 prompt 升级为 `case_summary_prompt/v3_input_variant_role_field_weighting`。默认使用 `field_conditioned_v1`，将医生/患者角色作为不同摘要字段的相对证据优先级；也可使用 `role_blind` 生成不区分角色权重的消融基线。

| 字段 | doctor | patient | 设计意图 |
|---|---:|---:|---|
| `chief_complaint` / `history_of_present_illness` | 0.9 | 1.2 | 主诉与病程优先患者自述 |
| `symptoms` / `negated_or_absent_symptoms` | 0.9 | 1.2 | 症状及否定症状优先患者证据 |
| `relevant_history` | 1.0 | 1.2 | 病史优先患者自述，保留医生复述 |
| `medications` | 1.2 | 1.0 | 患者当前/既往用药仍保留；医生新开药、剂量调整优先 |
| `tests_or_exam_mentioned` | 1.3 | 0.9 | 检查结果与解释优先医生证据 |
| `assessment_mentioned` / `plan_mentioned` | 1.5 | 0.8 | 评估和计划优先医生陈述 |

这些数值只是 prompt 中的相对证据排序先验，不是事实真实性概率。硬性约束包括：

- 医生提问不算事实陈述；
- 患者主诉、症状、否定症状和病史不能仅因来自患者而被省略；
- 医患在否定、时间、剂量、检查结果或计划上冲突时，不得用高权重一方静默覆盖另一方，应保留归因并写入 `uncertainty_notes`；
- 证据权重不参与 gold key facts 构造，避免评测标签偏置。

默认字段条件化生成：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --evidence-weighting-profile field_conditioned_v1
```

角色盲消融：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --evidence-weighting-profile role_blind
```

逐条 generation record、聚合 summary 和 run config 均记录 `evidence_weighting_profile`/完整字段权重，但聚合文件不包含 transcript 正文。后续正式实验应在同一模型、同一 input variants、同一解码参数下对比两种 profile，并复用 T042 的事实级指标。

验证结果：目标测试 `8 passed`，全量测试 `80 passed`，目标 ruff 检查通过；两个 profile 均完成 1 条 noisy ASR 的 dry-run，summary 分别记录 `soft_prompt_role_field_prior` 与 `role_blind_ablation`，且 `summary_contains_full_transcript_text=false`。

## 2026-07-13 T046 全量消融结果

已在同一批 57 条 noisy ASR consultation、同一 `Qwen3-Coder-Plus`、`temperature=0`、同一英文 schema 和同一 516 条自动 gold facts 下完成 `role_blind` / `field_conditioned_v1` 正式对照。英文输出用于对齐英文 transcript 与英文 gold facts；首次中文批次因语言错配未纳入结论。

`field_conditioned_v1` 相对 `role_blind`：micro F1 0.1903 → 0.1763（-0.0140），Critical recall 0.2778 → 0.2556，Unsupported +85，Omission +6。本轮没有观察到质量提升。详细设计、配对分析与展示图见 `docs/t046_speaker_weight_ablation.md`。

为支持全量调用，生成入口新增 `--workers` 和 `--max-attempts`；默认值均为 1，旧运行方式不变。
