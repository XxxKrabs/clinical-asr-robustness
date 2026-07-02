# 交互式文本 repair 数据结构 v1

> 2026-07-01 更新：项目近期主线已调整为“音频 → ASR → noisy transcript + ASR 置信度 → 医生实时交互确认”。本文档保留为 2026-06-30 文本 repair 方案的辅助 schema，可用于 ASR top-k 候选不足时补充文本候选；不要再把这里的 repair 置信度视为第一阶段主线置信度来源。后续应新增 ASR confidence / interaction schema。

本文档对应 T017，定义第一阶段 `noisy transcript → repaired transcript` 闭环中最小可用的数据结构。它不是全局统一样本 schema，而是服务于 repair 候选、置信度、阈值决策和医生反馈记录的轻量约定。

实现位置：`src/clinical_asr_robustness/repair.py`

## 设计目标

- 保留每个可疑片段的 top-k `repair_candidates`；
- 为候选和阈值决策记录 `confidence`；
- 用 `decision_type` 区分高置信度自动采纳、低置信度转人工、医生选择/编辑/拒绝；
- 用 `doctor_feedback` 保存结构化人工反馈，便于后续阈值校准和候选排序；
- 用 `final_repaired_transcript` 保存合并自动采纳和人工确认结果后的最终文本；
- 所有临床相关文本输出均标记为研究用途，不构成临床建议。

## 顶层记录：`InteractiveRepairRecord`

建议一行 JSONL 对应一个 noisy transcript 样本。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 固定为 `interactive_repair_record/v1`。 |
| `repair_id` | string | 本次 repair 运行内唯一 ID。 |
| `sample_id` | string | 对应 manifest 或 processed JSONL 的样本 ID。 |
| `dataset` / `split` / `track` | string | 数据集、切分和实验轨道，例如 `aci_bench`、`valid`、`repair_gain`。 |
| `source_variant` | string | repair 输入版本，默认 `noisy`。 |
| `noisy_transcript` | string | 输入的 noisy transcript。包含正文的输出文件应只放在本地 ignored 目录。 |
| `spans` | list | 可疑待修复片段列表。 |
| `repair_candidates` | list | 所有候选修复方案，按 `span_id` 关联到片段。 |
| `decisions` | list | 每个片段的阈值决策或医生反馈后最终决策。 |
| `final_repaired_transcript` | string | 最终 repaired transcript。 |
| `confidence_threshold` | number | 本次运行使用的自动采纳阈值。 |
| `method_name` / `method_version` | string | 候选生成或 repair baseline 名称与版本。 |
| `interaction_mode` | string | 可填 `offline_simulation`、`review_sheet`、`prototype_ui` 等。 |
| `research_use_only` | bool | 默认 `true`。 |
| `clinical_use_warning` | string | 默认声明“本记录仅用于研究评估，不构成临床建议”。 |

## 片段与候选

`RepairSpan` 描述一个可疑片段：

- `span_id`
- `original_text`
- `start_char` / `end_char`：相对于 `noisy_transcript` 的字符偏移；若第一版无法稳定对齐，可以留空。
- `error_tags`：复用 `ErrorTag`，例如 `negation_omission`、`drug_name_error`、`speaker_confusion`。

`RepairCandidate` 描述一个候选：

- `candidate_id`
- `span_id`
- `rank`
- `original_text`
- `replacement_text`
- `confidence`：0 到 1；
- `method_source` / `method_version`
- `rationale` / `evidence`
- `error_tags`

## 阈值决策与医生反馈

`RepairDecision.decision_type` 支持：

| 值 | 含义 |
|---|---|
| `auto_accepted` | 最高候选置信度达到阈值，自动采纳。 |
| `needs_doctor_review` | 低于阈值，等待医生或人工核验。 |
| `doctor_selected` | 医生从 top-k 中选择某个候选。 |
| `doctor_edited` | 医生基于候选或原文进行了编辑。 |
| `doctor_rejected` | 医生拒绝候选。 |
| `no_change` | 不修改该片段。 |

`DoctorFeedback.action` 支持：

- `select_candidate`
- `edit_text`
- `reject_all`
- `accept_original`
- `mark_unsure`

第一阶段如果没有真实医生参与，可以把 `feedback_source` 设置为 `researcher_simulation` 或 `clinical_reviewer`，并在实验记录里说明模拟规则。真实医生参与前，应先明确伦理、隐私和数据使用边界。

## 最小 JSON 示例

以下为合成示例，不含真实患者信息：

```json
{
  "schema_version": "interactive_repair_record/v1",
  "repair_id": "repair_demo_001",
  "sample_id": "demo_001",
  "dataset": "synthetic_demo",
  "source_variant": "noisy",
  "noisy_transcript": "Patient chest pain.",
  "spans": [
    {
      "span_id": "span_001",
      "original_text": "Patient chest pain",
      "start_char": 0,
      "end_char": 18,
      "error_tags": ["negation_omission"]
    }
  ],
  "repair_candidates": [
    {
      "candidate_id": "cand_001",
      "span_id": "span_001",
      "rank": 1,
      "original_text": "Patient chest pain",
      "replacement_text": "Patient denies chest pain",
      "confidence": 0.93,
      "method_source": "rule_negation_demo",
      "rationale": "根据否定表达规则恢复 denies。",
      "error_tags": ["negation_omission"]
    }
  ],
  "decisions": [
    {
      "span_id": "span_001",
      "decision_type": "auto_accepted",
      "selected_candidate_id": "cand_001",
      "final_text": "Patient denies chest pain",
      "confidence": 0.93,
      "threshold": 0.9
    }
  ],
  "final_repaired_transcript": "Patient denies chest pain.",
  "confidence_threshold": 0.9,
  "method_name": "rule_demo",
  "research_use_only": true,
  "clinical_use_warning": "本记录仅用于研究评估，不构成临床建议。"
}
```

## 后续与 T018/T006 的衔接

- T018 的候选生成 baseline 应输出 `RepairCandidate`，并按阈值生成初始 `RepairDecision`。
- T006 的完整 repair baseline 应把多个 span 的决策合并为 `final_repaired_transcript`。
- T008 的指标可以直接统计 `decision_type` 分布、自动采纳比例、低置信度转人工比例、top-k 命中和医生反馈动作分布。
