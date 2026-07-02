# T030/T035/T036 ASR 置信度审阅样本、反馈回放与 HTML demo

更新时间：2026-07-02

本文记录 ASR 输出层最小医生审阅 demo 的三个相邻任务：

- T030：生成绿/黄/红可审阅样本包；
- T035：记录医生/模拟审阅者反馈，并回放生成 `confirmed_transcript`；
- T036：生成静态/轻量 HTML 审阅界面。

所有产出均为研究 demo，不构成临床建议；不要在反馈备注或手动编辑框中写入真实患者隐私或未脱敏病例内容。

## 新增文件

- 逻辑模块：`src/clinical_asr_robustness/review_workflow.py`
- T030 CLI：`scripts/build_asr_review_samples.py`
- T035 CLI：`scripts/apply_asr_review_feedback.py`
- T036 CLI：`scripts/build_doctor_review_demo_html.py`
- 测试：`tests/test_review_workflow.py`

## T030：生成审阅样本包

输入建议使用 T029 后的 ASR confidence JSONL，即包含：

- `asr_words`：词级文本、时间戳、confidence、颜色等级；
- `uncertain_spans`：连续黄/红/unknown 待审阅片段；
- `asr_alternatives`：span-level 候选。

示例命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl `
  --output-jsonl outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl `
  --output-csv outputs/primock57/t030_review_samples/primock57_asr_review_spans.csv `
  --output-html outputs/primock57/t030_review_samples/primock57_asr_review_samples.html
```

默认输出：

- `outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl`
- `outputs/primock57/t030_review_samples/primock57_asr_review_spans.csv`
- `outputs/primock57/t030_review_samples/primock57_asr_review_samples.html`
- `outputs/primock57/t030_review_samples/t030_review_samples_run.json`

JSONL 一行一个 `asr_review_sample/v1`，核心字段包括：

- `sample_id` / `record_id` / `source_channel`
- `asr_transcript`
- `words[]`：`text`、`start_sec`、`end_sec`、`confidence`、`confidence_level`
- `uncertain_spans[]`：`span_id`、词范围、时间戳、`confidence_level`、`alternatives[]`
- `review_policy`：颜色阈值和支持的反馈动作

CSV 为 span-level 摘要，便于研究者快速浏览候选覆盖情况。

## T035：反馈日志与 confirmed transcript

反馈日志使用一行一个 `doctor_feedback_entry/v1` 的 JSONL。T036 HTML 会按此格式导出，也可以手动构造。

支持动作：

| action | 含义 | 回放规则 |
|---|---|---|
| `accept_asr` | 保留 ASR 原 span 文本并确认 | 原文写入 confirmed，span 视为 resolved |
| `select_alternative` | 选择某个 ASR span 候选 | 用候选文本替换原 span，span 视为 resolved |
| `manual_edit` | 手动编辑 span 文本 | 用 `manual_text` 替换原 span，span 视为 resolved |
| `reject` | 拒绝候选，但当前无法给出确认文本 | 暂保留 ASR 原文，span 标记 unresolved |
| `unable_to_judge` | 无法判断 | 暂保留 ASR 原文，span 标记 unresolved |

最小反馈示例：

```json
{"schema_version":"doctor_feedback_entry/v1","record_id":"nemo_entropy_demo","sample_id":"primock57:demo:patient","span_id":"span_001","action":"select_alternative","selected_alternative_id":"alt_span_001_rank_001","original_text":"reports cough","research_use_only":true,"clinical_use_warning":"本记录仅用于研究评估，不构成临床建议。"}
```

回放命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/apply_asr_review_feedback.py `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl `
  --feedback-jsonl outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.jsonl `
  --output-jsonl outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.jsonl
```

输出 `confirmed_transcript_record/v1`，包含：

- `asr_transcript`
- `confirmed_transcript`
- `confirmation_status`：`confirmed` 或 `needs_review`
- `applied_spans[]`：每个 span 的原文、确认文本、动作和 resolved 状态
- `missing_feedback_span_ids`
- `unresolved_span_ids`
- `action_summary`

默认策略允许反馈不完整：缺失反馈的 span 会保留 ASR 原文并标记为 `needs_review`。若希望严格要求每个 uncertain span 都有反馈，可加：

```powershell
--require-feedback-for-all-spans
```

## T036：静态/轻量 HTML 医生审阅界面

生成命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_doctor_review_demo_html.py `
  --review-jsonl outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl `
  --output-html outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html
```

如果 `--review-jsonl` 不存在，脚本会回退读取 `--input-jsonl` 的 ASR confidence JSONL 并现场构建 review samples。

页面能力：

- 展示 ASR transcript 绿/黄/红/灰色高亮；
- 点击 uncertain span 后显示置信度、候选列表和反馈表单；
- 支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`；
- 点击“提交并下载反馈 JSONL”后下载 `doctor_feedback_log.jsonl`；
- 同时把 JSONL 写入浏览器 localStorage，便于本地 demo 临时恢复。

静态 HTML 没有后端服务，不能直接写入项目目录；下载后的反馈 JSONL 需要手动放到 `outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.jsonl`，再用 T035 脚本回放。

## 当前验证

已新增无需 NeMo/GPU 的单元测试，覆盖：

- T030 review sample JSONL/CSV 生成；
- span 候选嵌入审阅样本；
- `select_alternative` / `manual_edit` / `reject` 的回放策略；
- feedback entry 与 wrapper log 的 JSONL 读取；
- T036 HTML 包含候选选择和反馈导出逻辑。

验证命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_review_workflow.py --basetemp=.pytest_tmp
```

本次运行结果：`5 passed`。

## 局限与后续

- HTML 是单文件 demo，不包含后端鉴权、真实保存服务或审阅者身份管理。
- `confirmed_transcript` 当前按 ASR `split()` 后的词序替换 span，适合第一版最小闭环；若后续需要保留复杂标点、说话人轮次或双路时间线，应扩展到 turn/segment 级回放。
- `reject` 与 `unable_to_judge` 不会删除文本，也不会声称已确认；它们只保留 ASR 原文并标记 unresolved，供后续复审。
- 真实医生审阅成本、点击次数、停留时长等指标尚未细化，可在 T019/T023 中继续扩展。
