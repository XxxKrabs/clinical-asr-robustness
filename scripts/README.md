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

外部 LLM API key 推荐写入项目根目录 `.env`，以便和其他项目隔离；`.env` 已被 `.gitignore` 忽略。也兼容环境变量。不要把真实 key 写入脚本、文档、输出摘要或 Git。

## 一键运行到 HTML demo

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
