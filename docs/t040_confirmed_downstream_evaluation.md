# T040 confirmed transcript 与下游鲁棒性评估

更新时间：2026-07-08

本文记录第一版“全流程效果看板”：比较 **raw ASR / confirmed transcript / clean reference** 在转写质量和轻量下游医学信息抽取任务上的差异。

所有输出仅用于研究评估，不构成临床建议；summary 不包含完整 reference、raw ASR 或 confirmed transcript 正文。

## 目标

T031 已能回答 ASR noisy transcript、confidence 和 top-k 候选本身效果如何；T040 进一步回答：

1. confirmed transcript 是否比 raw ASR 更接近 reference？
2. 医生/研究者确认成本是多少？
3. 下游医学信息整理代理任务是否从 confirmed transcript 中受益？

## 实现文件

- 模块：`src/clinical_asr_robustness/confirmed_downstream_evaluation.py`
- 脚本：`scripts/evaluate_confirmed_downstream.py`
- 测试：`tests/test_confirmed_downstream_evaluation.py`

T040 V0 的下游任务采用轻量医学/临床概念 token 抽取：

- 复用 `error_analysis.tokenize_for_alignment()` 的医学概念 token 标记；
- 把 reference 与 hypothesis 中抽取到的医学概念 token 作为 multiset 比较；
- 输出 precision / recall / F1。

该指标不是最终医学实体归一化模型，但有三个优点：无需联网、可复跑、能快速显示 confirmed 是否比 raw ASR 更接近 reference。

## 运行命令

默认评估当前 PriMock57 小样本和 T035 simulated accept_asr confirmed transcript：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_confirmed_downstream.py
```

默认输入：

```text
outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl
outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.simulated_accept_asr.jsonl
```

默认输出：

```text
outputs/primock57/t040_confirmed_downstream_evaluation/primock57_t040_confirmed_downstream_annotations.jsonl
outputs/primock57/t040_confirmed_downstream_evaluation/primock57_t040_confirmed_downstream_summary.json
outputs/primock57/t040_confirmed_downstream_evaluation/t040_confirmed_downstream_evaluation_run.json
```

如果后续从 HTML demo 导出真实医生或研究者反馈，应先用 T035 回放生成新的 confirmed transcript JSONL，再替换 `--confirmed-input-jsonl`：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_confirmed_downstream.py `
  --confirmed-input-jsonl outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.real_or_research_review.jsonl
```

## 指标定义

| 指标 | 方向 | 解释 |
|---|---:|---|
| WER | 越低越好 | raw/confirmed/reference 与 clean reference 的 token 级编辑距离。 |
| MC-WER | 越低越好 | 医学/临床关键 token 上的 WER；V0 使用轻量词表、医学后缀、否定词和数字 token。 |
| medical concept precision | 越高越好 | hypothesis 抽取出的医学概念 token 中有多少也出现在 reference。 |
| medical concept recall | 越高越好 | reference 中的医学概念 token 有多少被 hypothesis 保留。 |
| medical concept F1 | 越高越好 | precision/recall 的调和平均。 |
| review span count | 越低越省力 | 每条样本需要医生/研究者处理的 span 数。 |
| changed span count | 视任务而定 | confirmed 与 ASR span 文本不同的数量；真实审阅中可反映修正量。 |
| unresolved span count | 越低越好 | reject / unable_to_judge / missing feedback 后仍未解决的 span。 |

T040 的 `confirmed_vs_raw` 中：

- WER / MC-WER improvement = `raw - confirmed`，正数表示 confirmed 更好；
- precision / recall / F1 improvement = `confirmed - raw`，正数表示 confirmed 更好。

## 本次基线结果

评估时间：2026-07-08。默认输入中共 3 条 channel-level record：

- `primock57:day1_consultation01:doctor`
- `primock57:day1_consultation01:patient`
- `primock57:day1_consultation02:doctor`

注意：本次 confirmed transcript 来自 T032/T035 的 **模拟 `accept_asr` 反馈**，即 3 个待审 span 全部“保留 ASR 原文并确认”。因此它只能验证 T040 评估链路和输出格式，不能代表真实医生确认效果。

聚合结果：

| variant | micro WER | micro MC-WER | medical concept precision | medical concept recall | medical concept F1 |
|---|---:|---:|---:|---:|---:|
| raw ASR | 0.3405 | 0.2526 | 0.9868 | 0.7895 | 0.8772 |
| confirmed transcript | 0.3405 | 0.2526 | 0.9868 | 0.7895 | 0.8772 |
| reference oracle | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |

confirmed vs raw：

| 指标 | 数值 |
|---|---:|
| mean WER improvement | 0.0000 |
| mean MC-WER improvement | 0.0000 |
| mean medical concept F1 improvement | 0.0000 |
| total error count reduction | 0 |
| total MC error count reduction | 0 |
| records by WER change | unchanged: 3 |
| records by medical concept F1 change | unchanged: 3 |

审阅成本：

| 指标 | 数值 |
|---|---:|
| review span count | 3 |
| applied span count | 3 |
| resolved span count | 3 |
| missing feedback span count | 0 |
| unresolved span count | 0 |
| changed span count | 0 |
| records with text changes | 0 |
| action summary | accept_asr: 3 |

## 解读

当前 T040 结果不是“医生确认没有用”，而是“当前没有真实修正动作”。因为 simulated feedback 全部是 `accept_asr`，confirmed transcript 与 raw ASR 在待审 span 上保持一致，所以 WER、MC-WER 和下游 F1 都没有变化。

这份基线的价值在于：

1. 评估链路已经跑通：T029/T035 输出可以被 T040 直接消费；
2. summary 同时显示 raw ASR、confirmed 和 reference oracle，后续改善空间一眼可见；
3. 审阅成本指标已经有位置：真实反馈接入后可以直接统计 manual_edit、select_alternative、reject、unable_to_judge 等动作；
4. 下游代理指标已接入：后续可替换成更强的症状抽取、医学实体识别或 sectioned note 信息保持评估。

## 下一步

1. 从 HTML demo 导出一份真实研究者反馈，不再全部 `accept_asr`；至少覆盖当前 3 个 span。
2. 用 T035 回放生成新的 confirmed transcript。
3. 复跑 T040，观察：
   - WER / MC-WER 是否下降；
   - medical concept recall/F1 是否上升；
   - changed span 与 manual_edit 成本是否合理；
   - 是否引入新错误。
4. 扩大到更多 PriMock57 consultation，并从 channel-level 过渡到 consultation-level。
5. 将 V0 医学概念 token 抽取替换或补充为更接近论文目标的症状/药物/检查实体抽取和病例摘要信息保持评估。

## 验证

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_confirmed_downstream_evaluation.py --basetemp=.pytest_tmp`：3 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/confirmed_downstream_evaluation.py scripts/evaluate_confirmed_downstream.py tests/test_confirmed_downstream_evaluation.py`：All checks passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_confirmed_downstream.py`：成功生成 T040 summary。
