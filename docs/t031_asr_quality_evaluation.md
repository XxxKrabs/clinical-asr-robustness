# T031 ASR noisy / confidence / top-k 初评

本文记录第一版 ASR 输出层评估：用 PriMock57 clean/reference TextGrid 对比当前 ASR noisy transcript，并评估 confidence 与 top-k 候选是否能帮助医生审阅。

## 目标

回答三个问题：

1. 当前 noisy transcript 跟 clean/reference 差多少？
2. ASR confidence 的绿/黄分层是否真的能预警错误？
3. 当前 n-best/top-k 候选是否覆盖 reference，能否帮助医生快速确认？

## 实现文件

- 模块：`src/clinical_asr_robustness/asr_quality_evaluation.py`
- 脚本：`scripts/evaluate_asr_quality.py`
- 测试：`tests/test_asr_quality_evaluation.py`

脚本会从 `ASRConfidenceRecord.reference_textgrid_path` / `reference_transcript_path` 读取 reference。PriMock57 TextGrid 中的 `<UNSURE>...</UNSURE>` 内容会保留，`<UNIN/>` 等标签会移除；summary 不写入完整 transcript 正文。

## 运行命令

默认评估当前医学实体 gating + 候选输出：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_asr_quality.py
```

默认输入：

```text
outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl
```

默认输出：

```text
outputs/primock57/t031_asr_quality_evaluation/primock57_t031_asr_quality_annotations.jsonl
outputs/primock57/t031_asr_quality_evaluation/primock57_t031_asr_quality_summary.json
outputs/primock57/t031_asr_quality_evaluation/t031_asr_quality_evaluation_run.json
```

其中 annotation JSONL 含局部 edit span / candidate span，仅用于本地研究排错；summary 是聚合指标，不含完整 reference/noisy transcript 正文。

## 本次初评结果

评估时间：2026-07-07。默认输入中共 3 条 channel-level record：

- `primock57:day1_consultation01:doctor`
- `primock57:day1_consultation01:patient`
- `primock57:day1_consultation02:doctor`

聚合结果：

| 指标 | 数值 | 解读 |
|---|---:|---|
| record 数 | 3 | 当前仍是小样本 smoke/evaluation。 |
| reference tokens | 2373 | TextGrid reference 清洗后 token 数。 |
| noisy ASR tokens | 1958 | ASR 输出明显短于 reference。 |
| micro WER | 0.3405 | 当前 noisy transcript 约三分之一 token 级编辑距离。 |
| macro WER | 0.3334 | 各 record 平均后接近 micro WER。 |
| micro MC-WER | 0.2526 | 轻量医学概念 token 上错误率约 25%。 |
| substitution / deletion / insertion | 317 / 453 / 38 | deletion 偏多，说明漏识别/省略是主要误差来源之一。 |
| macro ECE | 0.0651 | confidence 有一定校准误差，但不算完全失控。 |
| macro NCE | 0.0580 | confidence 比只用总体正确率略有信息量，但提升有限。 |
| Brier score | 0.1358 | token correctness 概率预测的均方误差。 |

confidence 分层结果：

| level | token 数 | error 数 | error rate | medical concept tokens | medical concept error rate |
|---|---:|---:|---:|---:|---:|
| green | 1795 | 277 | 0.1543 | 80 | 0.1125 |
| yellow | 163 | 78 | 0.4785 | 2 | 0.0000 |
| red | 0 | 0 | NA | 0 | NA |
| unknown | 0 | 0 | NA | 0 | NA |

这说明当前 confidence 仍有用：yellow 的错误率约 47.9%，明显高于 green 的 15.4%。但也有大量错误落在 green 中，不能把 green 直接视为“无需审阅”的临床级可靠判断。

top-k / n-best 结果：

| 指标 | 数值 |
|---|---:|
| uncertain spans | 3 |
| spans with span-level candidates | 0 |
| exact reference covered spans | 0 |
| sequence-level candidates | 15 |
| records where sequence candidate improves WER | 1 |
| mean sequence oracle WER improvement | 0.00068 |

当前 top-k 对本轮医学实体 span 的帮助很弱：T029 没有为 3 个 uncertain span 生成 span-level candidate；sequence-level n-best 即使有 15 个候选，oracle WER 改善也几乎为 0。

医学实体 gating 覆盖：

| 指标 | 数值 |
|---|---:|
| medical concept error tokens | 9 |
| marked as medical entity error tokens | 2 |
| covered by uncertain span medical error tokens | 0 |
| medical entity marking coverage | 0.2222 |
| uncertain-span coverage | 0.0000 |

这批样本里，医学概念错误被 T038 医学实体 gating 捕捉到的比例偏低；而且没有进入最终 uncertain span。它提醒我们：当前 LLM/关键词实体识别和 confidence 阈值还不能充分覆盖真正的医学关键错误。

## 初步结论

1. noisy transcript 的质量不能只看整体流畅度。当前小样本 micro WER 约 34%，MC-WER 约 25%，已经足以影响下游病例整理。
2. confidence 分层有信号：yellow 错误率显著高于 green，适合作为医生审阅排序依据。
3. 但 green 中仍有不少错误，尤其当前没有 red，说明阈值和置信度尺度仍需校准。

## 2026-07-13 三档阈值复核

上表是旧阈值 `green >= 0.80`、`yellow >= 0.50` 的历史结果。使用同一批 3 条
reference 对齐记录离线比较后，当前选择 `green >= 0.90`、`yellow >= 0.80`：

| level | token count | error count | error rate |
|---|---:|---:|---:|
| green | 990 | 77 | 0.0778 |
| yellow | 805 | 200 | 0.2484 |
| red | 163 | 78 | 0.4785 |

三档错误率单调上升，且全量分布预计为 51,710 / 19,859 / 4,028 个词，三种颜色
都有实际作用。这里只完成操作阈值选择；正式 calibration 仍需扩大人工/reference
对齐样本，并报告 ECE/NCE、风险覆盖率与医生审阅成本。
4. 当前 top-k 候选覆盖不足，不能指望医生只靠候选点击完成修正；必须保留手动编辑/拒绝/无法判断。
5. 医学实体 gating 的方向正确，但当前实体识别与 uncertain span 触发规则还需要用 T031 annotation 的 false negative/false positive 继续调。

## 限制

- 当前只是 3 条 channel-level record，不是完整 PriMock57 评估。
- MC-WER 仍是 V0 轻量医学关键词定义，不等同于标准医学实体归一化评估。
- TextGrid reference 与 ASR transcript 采用 token 级自动对齐，局部错误 span 需要人工抽样复核。
- 评估还没有合并 doctor/patient 双路成 consultation-level transcript，也没有进入下游病例摘要/诊疗计划任务。

## 建议下一步

1. 用 annotation JSONL 抽样看 false negative：哪些医学关键错误被标成 green 或未进入实体 gating。
2. 调整医学实体关键词/LLM prompt 和 uncertain span 触发规则，优先提高医学错误覆盖率。
3. 改进 T029 span-level candidate 生成：sequence n-best 不足时，引入医学词表、规则或 LLM 辅助候选。
4. 扩到更多 PriMock57 consultation，并输出按 doctor/patient/consultation 的分层统计。
5. 在 T032 中整理 ASR 输出层最小闭环实验记录，再进入 T035 反馈回放和下游鲁棒性评估。
