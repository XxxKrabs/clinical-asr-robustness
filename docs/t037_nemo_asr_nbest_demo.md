# T037 NeMo ASR n-best 候选接入与审阅 demo 重跑

更新时间：2026-07-02

T037 补齐 T029/T030/T036 之前缺失的真实 ASR n-best 上游：使用项目内
NeMo 模型对 PriMock57 音频做 sequence-level beam 解码，导出可被 T029
消费的 `beams` JSONL，再把候选对齐到低/中置信度 span，最后重跑绿/黄/红
审阅样本和医生审阅 HTML demo。

所有输出均为研究 demo，不构成临床建议；脚本只保存 ASR 输出、候选、配置和
文件指针，不读取或内联 reference transcript 正文。

## 新增文件

- 模块：`src/clinical_asr_robustness/nemo_nbest_export.py`
- T037 CLI：`scripts/export_nemo_asr_nbest.py`
- 测试：`tests/test_nemo_nbest_export.py`

## 设计选择

第一版沿用 D004：不做词级 top-k，而是导出 sequence-level beam n-best，
再用 T029 的词级 diff 把不同 beam 中对应位置的变化裁剪成 span alternatives。

默认解码策略是：

- `beam_strategy=beam_batch`
- `beam_size=5`
- `max_beams=5`
- `ngram_lm_model=None`
- `ngram_lm_alpha=0.0`
- `beam_beta=0.0`
- `timestamps=False`

选择 `beam_batch` 的原因是它可以在没有 KenLM 的情况下生成 acoustic-only
n-best；普通 `strategy=beam` 在 NeMo 中默认依赖 KenLM，未配置 LM 文件时会失败。
T037 的 beam 只用于候选，不混入 T028 的 greedy entropy confidence。

## 可复现命令

### 1. 导出真实 NeMo n-best/beams JSONL

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_nbest.py `
  --limit 2 `
  --output-jsonl outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl `
  --run-config-json outputs/primock57/t037_nemo_asr_nbest/t037_nemo_asr_nbest_limit2_run.json
```

输出 JSONL 一行对应一路音频，核心字段：

- `record_id` / `sample_id`：供 T029 匹配；
- `source="nemo_beam_batch"`；
- `beams`：`[["候选文本", score], ...]`；
- `nbest`：带 rank/source/metadata 的候选列表；
- `metadata.model` / `metadata.decoding` / `metadata.runtime`：运行配置与环境。

### 2. 用 T029 写入 span alternatives

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py `
  --input-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl `
  --nbest-jsonl outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl `
  --output-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates_limit2.jsonl `
  --run-config-json outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_limit2_run.json
```

### 3. 重跑 T030 审阅样本

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates_limit2.jsonl `
  --output-jsonl outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl `
  --output-csv outputs/primock57/t030_review_samples/primock57_asr_review_spans.csv `
  --output-html outputs/primock57/t030_review_samples/primock57_asr_review_samples.html `
  --run-config-json outputs/primock57/t030_review_samples/t030_review_samples_run.json
```

### 4. 重跑 T036 医生审阅 HTML

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_doctor_review_demo_html.py `
  --review-jsonl outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates_limit2.jsonl `
  --output-html outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html `
  --embedded-review-jsonl outputs/primock57/t036_doctor_review_demo/doctor_review_samples.embedded.jsonl `
  --run-config-json outputs/primock57/t036_doctor_review_demo/t036_doctor_review_demo_run.json
```

## 验收标准

T037 完成时应满足：

- `outputs/primock57/t037_nemo_asr_nbest/` 中存在真实 NeMo beam JSONL 和 run summary；
- `outputs/primock57/t029_asr_nbest_candidates/` 中存在带候选的 ASR confidence JSONL；
- T029/T030/T036 的 run summary 中 `spans_with_alternatives` 或
  `spans_with_candidates > 0`；
- HTML 点击黄/红 span 后能看到可选 ASR 候选；
- run summary 中 `external_speech_main_paths == []` 且 NeMo 路径来自
  `third_party/speech_main/`。

## 本次运行结果

2026-07-02 已在 WSL `clinical-asr` 中完成 `limit2` 实跑：

- T037：`records_written=2`、`total_beams=10`、`beam_counts=[5, 5]`、`records_with_unique_beam_variants=2`；
- T037 环境：`device=cuda`，GPU 为 `NVIDIA GeForce RTX 4060 Laptop GPU`，`external_speech_main_paths=[]`，NeMo 路径均来自 `third_party/speech_main/`；
- T029：`sequence_alternatives=10`、`span_alternatives=6`、`spans_with_alternatives=2`；
- T030：`total_uncertain_spans=2`、`spans_with_candidates=2`；
- T036：`interactive_html=true`、`spans_with_candidates=2`，支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`。

同日后续修正 T028 confidence 默认归一化后，已用 `entropy_norm=lin` 重跑 T028→T029→T030→T036：

- T028：`word_confidence` 共 1145 个，1031 green、114 yellow、0 red，`low_scale_warning=false`；
- T029：`sequence_alternatives=10`、`span_alternatives=2`、`spans_with_alternatives=2`；
- T030：`total_uncertain_spans=74`、`spans_with_candidates=2`，span 均为 yellow；
- T036：`interactive_html=true`、`total_uncertain_spans=74`、`spans_with_candidates=2`。

验证命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
```

T037 首次结果：`33 passed`；`All checks passed!`。confidence 修正后追加验证：
`tests/test_nemo_confidence_export.py tests/test_asr_confidence_schema.py` 共 `8 passed`，
`ruff check src scripts tests` 为 `All checks passed!`。

## 当前局限

- T028 初版 `entropy_norm=exp` 会把当前 PriMock57 word confidence 压到 0 附近并导致全红；当前 demo 已改用论文同样支持的 `entropy_norm=lin`。后续 T031/T032 仍应做 reference 校准、阈值修正或按 segment 最大长度拆分 span。
- `beam_batch` 输出是 acoustic-only n-best；若后续接入 KenLM、医学词表或上下文 bias，应把来源明确标注为新的 ASR 解码配置，不和当前 T037 结果混用。
- n-best 仍不是词级 top-k；医生界面里的 span 候选来自 sequence-level diff，是 V0 折中方案。
