# T046 医生/患者说话人字段权重消融评测

更新时间：2026-07-13

## 目的

评估病例摘要 prompt 加入 `field_conditioned_v1` 医生/患者字段条件软权重后，是否优于不区分角色初始优先级的 `role_blind` 原始基线。

所有病例摘要均为研究输出，不构成临床建议。本记录只报告聚合指标，不包含 transcript、病例正文、prompt、API key 或可识别信息。

## 对照设计

- 数据：PriMock57 全量 57 条 consultation / 114 路 noisy ASR；
- 生成模型：两组均为 `Qwen3-Coder-Plus`；
- 解码：`temperature=0`，同一结构化 schema；
- 摘要语言：英文，与英文 transcript 和英文自动 gold facts 对齐；
- gold facts：固定复用 T045 的 516 条自动 gold facts，不受权重配置影响；
- 唯一实验变量：`evidence_weighting_profile=role_blind|field_conditioned_v1`；
- 评测：T042 source-aware B-lite 事实级 Precision / Recall / F1、Critical recall、ROUGE-L 辅助指标、错误与遗漏计数；
- 配对分析：consultation 级指标差值、bootstrap 95% CI 和双侧 sign test。

首次按默认中文生成的两组摘要与英文 gold facts 存在语言错配，B-lite micro F1 接近 0；该批次仅作为失败诊断保留，不纳入正式结果或图表。

## 正式结果

| 配置 | Precision | Recall | F1 | Critical recall | ROUGE-L F1 | Supported | Unsupported | Contradicted | Omission |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `role_blind` | 0.1477 | 0.2674 | 0.1903 | 0.2778 | 0.0897 | 235 | 1268 | 69 | 378 |
| `field_conditioned_v1` | 0.1345 | 0.2558 | 0.1763 | 0.2556 | 0.0835 | 223 | 1353 | 63 | 384 |
| 加权组减基线 | -0.0132 | -0.0116 | -0.0140 | -0.0222 | -0.0062 | -12 | +85 | -6 | +6 |

本轮字段条件软权重没有优于 `role_blind`：micro F1 下降 0.0140（1.40 个百分点），Precision、Recall、Critical recall 和 ROUGE-L F1 均下降；虽然 contradicted facts 减少 6 条，但 supported facts 减少 12 条、unsupported facts 增加 85 条、omission 增加 6 条。

57 条 consultation 中 56 条可计算 record-level F1：14 条改善、10 条持平、32 条下降；平均 F1 差值为 -0.0135，bootstrap 95% CI 为 [-0.0250, -0.0023]，双侧 sign-test `p=0.0114`。这支持“本次运行中权重配置更差”，但不能替代多随机重复和人工临床事实核查。

## 产物

- 展示图：`outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_figure.png`
- 矢量图：`outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_figure.svg`
- 结果表：`outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_results.csv`
- 聚合报告：`outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_report.md`
- 机器可读 summary：`outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_summary.json`
- 汇总脚本：`scripts/build_t046_speaker_weight_ablation_report.py`

正式生成 records 与质量记录位于 `role_blind_en/`、`field_conditioned_v1_en/` 子目录；其中 generation records 包含完整 noisy transcript 和模型输出，属于本地受控研究产物，默认不提交 Git。

## 解释与下一步

- 当前权重通过 prompt 文本表达，模型可能把数字权重理解为“扩写高权重字段”，造成摘要事实数增加 67 条并带来更多 unsupported facts；需要抽样复核该机制。
- doctor/patient 当前是声道级拼接，不是精确 turn-level 对齐；说话人权重无法解决时间顺序信息缺失。
- B-lite 依赖词面/术语启发式匹配，且 gold facts 为自动构建；建议抽样人工核验 supported / unsupported / omission。
- 下一轮优先尝试去掉显式数值、只保留简短字段归因规则，或先做“医生提问过滤 + 说话人归因”再生成摘要；应保持相同模型与数据并至少重复多次。
