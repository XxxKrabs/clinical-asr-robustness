# Scripts

本目录用于放置可复现实验脚本。建议脚本具备以下特点：

- 支持命令行参数；
- 支持读取 `configs/` 中的配置文件；
- 不写死本地绝对路径；
- 输出到 `outputs/` 或 `data/interim/`、`data/processed/`。

后续可添加：

- 数据转换脚本；
- ASR 批量转写脚本；
- 错误类型统计脚本；
- 下游任务评估脚本。

## 当前 ASR 审阅主线脚本

近期主线建议按下面顺序运行：

1. `export_nemo_asr_confidence.py`：导出 ASR transcript、词级置信度、时间戳和初始风险 span。
2. `extract_medical_entity_review_spans.py`：调用 LLM 抽取医学实体，只保留医学实体的置信度高亮和待审阅 span。
3. `extract_asr_nbest_candidates.py`：把 sequence-level n-best 对齐到医学实体待审阅 span，生成候选。
4. `build_asr_review_samples.py` / `build_doctor_review_demo_html.py`：生成 JSONL/CSV/HTML 审阅包。
5. `apply_asr_review_feedback.py`：回放医生或模拟审阅者反馈，生成 `confirmed_transcript`。
6. `evaluate_asr_quality.py`：用 clean/reference 评估 ASR noisy、confidence 校准和 top-k 覆盖。
7. `generate_case_summaries.py` / `evaluate_case_summaries.py`：生成 noisy/confirmed/reference 三类病例摘要任务记录，并用 gold key facts 做 T042 ROUGE-L 辅助指标、source-aware B-lite 事实级评估、高风险错误统计、uncertainty notes 覆盖检查、ASR 置信度归因和审阅成本收益分析。

外部 LLM API key 推荐写入项目根目录 `.env`，以便和其他项目隔离；`.env` 已被 `.gitignore` 忽略。也兼容环境变量。不要把真实 key 写入脚本、文档、输出摘要或 Git。

## 一键运行到 HTML demo

### 中文真实数据：先预处理，再复用同一流水线

中文 40 例的原始 MP3 manifest 与 ASR-ready manifest 分开。先冻结匿名清单，再把所选音频
确定性转换为 16 kHz mono PCM16 短窗：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_remote_programming_40_manifest.py

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/preprocess_asr_audio.py `
  --sample-id remote_programming_40:case_0068:mixed `
  --window-sec 30
```

然后把预处理 manifest 交给共用总控脚本：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py `
  --dataset auto `
  --manifest data/interim/remote_programming_40/manifests/remote_programming_40_asr_16k_windows.jsonl `
  --run-asr `
  --asr-limit 0
```

`dataset=remote_programming_40` 会选择项目内中文 Hybrid checkpoint、辅助 CTC frame
distribution、`demo_quantile_v0`、中文字符区间、DBS 中文候选词表和
`zh_dbs_remote_programming_v1` prompt。中文 profile 默认实际调用 LLM 候选，并把同一
`consultation_id` 的完整 speaker-labeled noisy ASR 对话放进候选上下文；如只想生成 prompt
而不调用 API，显式加 `--no-run-llm-candidates`。`dataset=primock57` 仍选择历史英文
checkpoint、局部候选上下文和固定阈值。

T030 同时输出两种粒度：`review_samples.jsonl` 保留 ASR 推理窗口以支持回听和反馈回放，
`review_conversations.jsonl` 一行一例并按 speaker turn 组织；HTML 也按完整病例对话显示。
没有 diarization 时 speaker 必须显示为“待分离”，不得猜测 doctor/patient。说话人分离调研
和 NVIDIA Sortformer 接入边界见 `docs/t068_chinese_conversation_candidates_diarization.md`。

中文整例 Streaming Sortformer pilot 使用独立的 `.nemo` 权重：
`data/external/asr_models/nemo/diar_streaming_sortformer_4spk-v2.1.nemo`。先用预处理器的
`--window-sec 0` 生成整例 16 kHz mono WAV，再运行：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_sortformer_diarization.py `
  --input-manifest data/interim/remote_programming_40/manifests/remote_programming_40_t070_sortformer_pilot_manifest.jsonl `
  --asr-confidence-jsonl outputs/remote_programming_40/t054_shortest_full/remote_programming_40_shortest_full_asr_confidence.jsonl `
  --mapped-asr-output-jsonl outputs/remote_programming_40/t070_sortformer_pilot/asr_confidence_diarized.jsonl `
  --overwrite --fail-fast
```

如果 GPU diarization 已完成，只需把同一结果映射到候选增强 ASR，可运行
`scripts/map_speaker_diarization_to_asr.py`，不必再次加载 Sortformer。两条脚本都只产生
声学 `speaker_0...speaker_3`；doctor/patient/family/staff 角色必须另行映射。详细结果与
配置见 `docs/t070_sortformer_diarization_pilot.md`。

映射器默认桥接前后同一 speaker、间隔不超过 1.5 秒的 `no_overlap` /
`insufficient_overlap` 短空洞，以减少界面中的“待分离”碎片；重叠歧义和不同 speaker 交界
不会桥接，原始声学标签与状态仍保留在 metadata。可用
`--max-same-speaker-bridge-gap-sec` 调整阈值，或用 `--disable-same-speaker-gap-bridge`
关闭并生成原始对照。

残余“待分离”可用完整病例语义作独立补全层。脚本默认从项目 `.env` 读取 `API_KEY`、
`BASE_URL`、`MODEL_ID`，只生成 prompt 时不联网；实际运行示例：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/resolve_speaker_gaps_with_llm.py `
  --run-llm --force-resolve-all
```

`--force-resolve-all` 会为每个残余 gap 强制选择最可能的既有 speaker，只适合实验展示；默认不加
该参数时按 `--min-confidence 0.80` 应用，低置信项仍保持未知。两种模式都保留原始声学空值、
重叠状态、LLM confidence 和 reason code；界面中的“含语义补全”不代表声纹真值。

两类数据复用 T028/T037/T038/T029/T030/T036/T035，输出目录按数据集隔离。中文置信度颜色
明确是 `calibrated=false` 的研究 demo，不代表临床可靠性。

### 中文 5 例代理参考鲁棒性报告

没有人工 clean transcript 时，可以先用固定 5 例、多路自动转录和强 LLM 生成明确标源的
探索性 proxy。该 proxy 没有听音频、不是人工 reference、不是医生 confirmed transcript，
不得用于正式质量声称：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_chinese_proxy_references.py `
  --run-llm --overwrite
```

完成 confidence、diarization 与 noisy/proxy 病例摘要后，生成逐例 CSV、聚合 Markdown/JSON、
单页 HTML 报告和五张 SVG：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_chinese_pilot_robustness.py `
  --asr-run-json outputs/remote_programming_40/t058_pilot5/asr_confidence_run.json `
  --nbest-run-json outputs/remote_programming_40/t058_pilot5/asr_nbest_run.json `
  --diarization-jsonl outputs/remote_programming_40/t058_pilot5/sortformer_diarization.jsonl `
  --diarized-asr-jsonl outputs/remote_programming_40/t058_pilot5/asr_confidence_diarized.jsonl `
  --case-summary-records-jsonl outputs/remote_programming_40/t058_pilot5/case_summaries/case_summary_records.jsonl
```

报告同时给出 Proxy CER、CIPS、代理事实召回、ECE/Brier、risk-coverage、黄/红错误捕获与
审阅成本代理，以及 noisy↔proxy 病例摘要事实稳定性。完整口径与本轮 5 例结果见
`docs/t058_t066_chinese_pilot5_robustness.md`；1 例底层接入细节见
`docs/t051_t060_chinese_asr_integration.md`。

### 中文 40 例全量工程报告与拆分页

全量运行使用 `preprocess_asr_audio.py --resume` 复用已经通过格式校验的 30 秒窗口；
`assemble_full_audio_from_windows.py` 从连续窗口流式重组每例完整 WAV，避免再次解码 MP3。
confidence 遇到无法对齐的 CTC 单元时使用显式
`--unaligned-confidence-policy all_red`，保留转写并强制全红人工复核，不能静默设成高置信。

完成 confidence、5-best、Sortformer、医学实体和候选后，先生成不带超大单页 HTML 的审阅
JSONL，再按病例拆页：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py `
  --input-jsonl outputs/remote_programming_40/t061_all40/asr_candidates_diarized.jsonl `
  --output-jsonl outputs/remote_programming_40/t061_all40/review_samples.jsonl `
  --conversation-jsonl outputs/remote_programming_40/t061_all40/review_conversations.jsonl `
  --output-csv outputs/remote_programming_40/t061_all40/review_spans.csv `
  --run-config-json outputs/remote_programming_40/t061_all40/review_run.json `
  --no-html

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_split_doctor_review_pages.py `
  --review-jsonl outputs/remote_programming_40/t061_all40/review_samples.jsonl `
  --output-dir outputs/remote_programming_40/t061_all40/review_pages/pages `
  --index-html outputs/remote_programming_40/t061_all40/review_pages/index.html `
  --run-summary-json outputs/remote_programming_40/t061_all40/split_review_run.json `
  --title "中文 40 例 ASR 置信度交互审阅"
```

生成 40 行 CSV、Markdown、HTML 和五张无第三方依赖 SVG：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_chinese_all40_engineering.py
```

全量报告只描述覆盖、RTF/显存、风险、候选、speaker 映射和异常显式率；没有人工 reference
时不报告 CER/DER/JER。完整结果与口径见 `docs/t061_chinese_all40_engineering.md`。

日常复跑推荐直接使用总控脚本：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py
```

默认会复用已有 T028 ASR confidence 和 T037 n-best 输出，然后自动串起：

```text
T038 医学实体 gating
  → T029 n-best/top-k 候选
  → T030 审阅样本 JSONL/CSV/HTML
  → T036 最终医生审阅 HTML demo
```

最终页面默认生成到：

```text
outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html
```

在 PowerShell 中打开：

```powershell
Start-Process outputs\primock57\t036_doctor_review_demo\doctor_review_demo.html
```

如果需要从音频重新跑 ASR 和 n-best：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py --run-asr
```

`--run-asr` 默认只跑前 2 条样本，便于 demo 和快速验收；全量重跑用：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py --run-asr --asr-limit 0
```

常用参数：

- `--dry-run`：只打印将要执行的分步命令；
- `--force-refresh-entities`：忽略 T038 实体缓存，重新调用 LLM 抽取医学实体；
- `--open-html`：流程完成后尝试自动打开最终 HTML；
- `--apply-feedback`：将 HTML 下载的 `doctor_feedback_log.jsonl` 回放为 `confirmed_transcript`；
- `--sample-id ...` / `--record-index ...`：重新跑 ASR 时选择指定样本。

## 评估 noisy transcript / confidence / top-k

生成 HTML demo 之后，建议立即跑 T031 初评：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_asr_quality.py
```

默认输出：

```text
outputs/primock57/t031_asr_quality_evaluation/primock57_t031_asr_quality_summary.json
outputs/primock57/t031_asr_quality_evaluation/primock57_t031_asr_quality_annotations.jsonl
```

summary 不含完整 transcript 正文；annotation JSONL 含局部错误 span，默认只用于本地研究排错，不提交 Git。

## 评估病例摘要质量（T042）

先准备或生成三类输入的病例摘要 records：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --input-variants noisy_asr confirmed_transcript reference_oracle `
  --output-dir outputs/primock57/t042_case_summary_variant_generation `
  --records-name primock57_t042_case_summary_variant_records.jsonl `
  --summary-name primock57_t042_case_summary_variant_summary.json `
  --run-config-name t042_case_summary_variant_generation_run.json
```

再用 `gold_key_facts.jsonl` 评估摘要事实保持情况：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_case_summaries.py `
  --summary-records-jsonl outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl `
  --gold-key-facts-jsonl data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl
```

如需启用 T042f，把摘要事实错误/遗漏回连到 ASR 颜色和 T035 反馈成本，可加：

```powershell
  --asr-confidence-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl `
  --confirmed-transcripts-jsonl outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.jsonl
```

注意：如果 `generate_case_summaries.py` 只是 dry-run，records 中没有 `case_summary`，评估会将对应记录标为 skipped；需要 `--run-llm` 或人工写入结构化摘要后，才会产生有效 fact precision / recall / F1。T042e 会进一步输出 `high_risk_error_type_counts` 和 `uncertainty_note_summary`；T042f 会输出 `confidence_attribution_summary`、`review_cost_attribution_summary` 和 `review_benefit_summary`。这些聚合输出不写完整 transcript、summary fact 正文、confirmed span 正文或 uncertainty note 正文。

## T045 全量三文本病例摘要评测

T045 的第一步是建立 57 条 consultation 的三文本对齐清单：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_t045_three_text_alignment.py
```

默认输出：

```text
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment_summary.json
```

该脚本只写 ID、路径、声道、计数和 pending/available 状态，不写 noisy ASR、clean TextGrid 或 repair transcript 正文。对齐阶段全量结果为 57 条 alignment records，clean TextGrid doctor/patient 成对完整 57/57；后续已由 real doctor LLM selector 生成 `doctor_llm_repair`。

真实 doctor LLM selector / repair 已有一键脚本。先生成 selector feedback、channel confirmed transcript 和 consultation-level repair：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_doctor_llm_selector.py
```

再用 real repair 替换 no-change baseline，复跑 T045 最终病例摘要评测表和图：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_case_summary_final_evaluation.py `
  --repair-jsonl data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
```

默认输出：

```text
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.md
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.csv
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.svg
outputs/primock57/t045_case_summary_three_texts/t045_case_summary_final_evaluation_run.json
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_decisions.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_feedback.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
```

注意：病例摘要评测仍使用 deterministic keyword case-summary baseline；`doctor_llm_repair` 是模拟医生/LLM selector 输出，不代表真实医生审阅。当前 selector 已审阅 2861 个风险 span，`manual_edit=980`、`keep_asr=1881`，实际修改 833 个 span；复跑结果显示 repair 提升 Recall / Critical recall 并减少 Omission，但 Precision 下降、F1 小幅下降，需进一步抽样复核。
