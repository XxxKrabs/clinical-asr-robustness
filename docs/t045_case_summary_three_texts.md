# T045 全量三文本病例摘要评测

更新时间：2026-07-10

本文记录 T045 主线：同一批 PriMock57 57 条 consultation，在同一病例摘要 prompt/schema 和同一病例生成模型下，分别使用 `noisy_asr`、`clean_reference`、`doctor_llm_repair` 三种输入文本生成病例摘要，并完成事实级质量评测。

所有 transcript 正文、prompt 正文、repair 正文和模型输出正文默认只保存在 `data/processed/` 或 `outputs/`，不提交 Git；本文只记录路径、计数和校验结果。

## 三种输入文本定义

| 输入变体 | 当前状态 | 来源 |
|---|---|---|
| `noisy_asr` | 已有全量 57 条 consultation | `data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_consultation.jsonl` |
| `clean_reference` | 已构建全量 consultation-level JSONL | `data/external/primock57/transcripts/*_{doctor,patient}.TextGrid` |
| `doctor_llm_repair` | 已生成 real doctor LLM selector repair；仍是模拟医生/LLM 审阅，不等于真实医生确认 | 独立 selector LLM 基于 noisy ASR、候选、局部上下文和置信度生成 feedback log，再回放为 repair transcript |

硬性边界：

- `doctor_llm_repair` 是模拟医生选择，不等于真实医生确认；
- doctor selector 不得读取 `clean_reference`、gold facts、医生 notes、病例摘要或评测结果；
- 病例摘要生成模型只接收当前 input variant 的 transcript，不应知道该文本来自 noisy、clean 还是 repair。

## 第 2–8 步：real selector 全量验收结果

实现文件：

- 脚本：`scripts/run_t045_case_summary_final_evaluation.py`
- selector / repair 脚本：`scripts/run_t045_doctor_llm_selector.py`

默认命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_doctor_llm_selector.py

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_case_summary_final_evaluation.py `
  --repair-jsonl data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
```

本轮使用独立 selector LLM `Qwen3-Coder-Plus` 扮演模拟临床转写审阅者，审阅全量 2861 个风险 span，生成 feedback log 和 real `doctor_llm_repair`。selector 只读取 noisy ASR、局部上下文、置信度和候选，不读取 clean/reference、gold facts、病例摘要或评测结果。病例摘要生成仍使用同一个离线 deterministic keyword case-summary baseline，因此 selector LLM 和病例摘要生成模型不是同一个模型。

默认输出：

```text
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_clean_reference_consultation.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_decisions.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_feedback.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_confirmed_channel_transcripts.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_gold_key_facts.keyword_baseline.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_generation_records.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_quality_summary.json
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.csv
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.md
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.svg
outputs/primock57/t045_case_summary_three_texts/t045_case_summary_final_evaluation_run.json
```

运行日期：2026-07-10。

| 指标 | 数值 |
|---|---:|
| consultation records | 57 |
| clean reference records | 57 |
| real repair consultation records | 57 |
| case summary records | 171 |
| 自动 gold key facts | 516 |
| evaluated quality records | 171 |
| skipped quality records | 0 |
| selector-reviewed risk spans | 2861 |
| selector manual_edit / keep_asr | 980 / 1881 |
| actually changed spans | 833 |

最终评测表：

| 输入变体 | 样本数 | Precision | Recall | F1 | Critical recall | ROUGE-L F1 | Omission | Unsupported | Contradicted | Uncertainty 缺失 | F1 Δ vs noisy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `noisy_asr` | 57 | 0.939 | 0.834 | 0.876 | 0.833 | 0.804 | 87 | 20 | 10 | 57 | 0.000 |
| real `doctor_llm_repair` | 57 | 0.868 | 0.877 | 0.866 | 0.881 | 0.788 | 62 | 58 | 20 | 46 | -0.010 |
| `clean_reference` oracle | 57 | 1.000 | 1.000 | 1.000 | 1.000 | 0.932 | 0 | 0 | 0 | 0 | 0.124 |

读数说明：

- `clean_reference` 使用同一 deterministic generator 和由 clean/reference 自动抽取的 gold facts，因此代表本轮离线验收 oracle 上限，不是人工临床事实 adjudication。
- real `doctor_llm_repair` 相对 `noisy_asr`：Recall +0.043、Critical recall +0.048、Omission -25；但 Precision 从 0.939 降到 0.868，Unsupported 和 Contradicted 增加，导致 F1 从 0.876 小幅降到 0.866。
- 当前全量 T029 候选补齐后 `spans_with_candidates=0`，因为未先全量 T038 医学实体 gating；selector 大多在无候选条件下 `keep_asr` 或 `manual_edit`。后续应优先补全 ASR n-best / 医学词表 / T044 候选覆盖，再复跑 selector。
- 表和图只含聚合指标，不含完整 transcript、prompt、病例原文或 gold fact 正文。

## 第 1 步：三文本样本对齐

实现文件：

- 脚本：`scripts/build_t045_three_text_alignment.py`
- 测试：`tests/test_t045_three_text_alignment.py`

默认命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_t045_three_text_alignment.py
```

默认输出：

```text
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment_summary.json
```

alignment JSONL 每条记录对应 1 条 consultation，只保存：

- `consultation_id`、`sample_id`、`split`；
- `noisy_asr` 的来源 JSONL、声道列表、turn 数、置信度摘要字段；
- `clean_reference` 的 doctor/patient TextGrid 路径、utterance 计数、`<UNSURE>` / `<UNIN/>` 标签计数；
- `doctor_llm_repair` 的 available / pending 状态；
- 对齐检查与安全标记。

它不保存 noisy ASR、clean TextGrid 或 repair transcript 正文。

## 第 1 步全量运行结果

运行日期：2026-07-10。

| 指标 | 数值 |
|---|---:|
| alignment records | 57 |
| split | `primock57_full_asr_v0`: 57 |
| noisy ASR available | 57 |
| noisy doctor/patient 双声道完整 | 57 |
| clean TextGrid doctor/patient 成对完整 | 57 |
| doctor_llm_repair available | 0 |
| doctor_llm_repair pending | 57 |
| ready for clean/reference build | 57 |
| ready for three-text summary generation | 0 |
| TextGrid non-empty utterance intervals | 7108 |
| `<UNSURE>` 标签计数 | 1132 |
| `<UNIN/>` 标签计数 | 1359 |

校验结果：

- `all_noisy_consultations_have_doctor_patient_channels=true`
- `all_noisy_consultations_have_clean_textgrid_pair=true`
- `missing_clean_reference_consultation_ids=[]`
- `manifest_contains_full_transcript_text=false`
- `summary_contains_full_transcript_text=false`
- `reference_text_included=false`

## 验证

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_t045_three_text_alignment.py --basetemp=.pytest_tmp
```

结果：`2 passed`。

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/build_t045_three_text_alignment.py tests/test_t045_three_text_alignment.py
```

结果：`All checks passed!`

## 下一步

- 补全全量 T038 医学实体 gating、ASR n-best / T039 / T044 候选覆盖，减少 selector 在无候选条件下直接 manual edit 的比例。
- 如有可用 API/模型，使用真实病例摘要生成 LLM 替换 deterministic keyword baseline，并用人工/研究者复核的 gold key facts 复跑 T042。
- 对自动 gold facts 与 B-lite 评测抽样人工复核，记录 disagreement 和失败模式。
