# T032 ASR 输出层最小闭环实验记录

更新时间：2026-07-07

本文记录当前第一版可复查闭环：

```text
PriMock57 audio
  → T028 NeMo ASR noisy transcript + word confidence
  → T037 NeMo sequence-level n-best
  → T038 医学实体优先 gating
  → T029 医学实体 span top-k/n-best 候选对齐
  → T030/T036 医生审阅样本与 HTML demo
  → T035 模拟反馈回放生成 confirmed_transcript
  → T031 noisy / confidence / top-k 质量评估
```

所有输出均为研究用途，不构成临床建议。本文不写入完整 transcript 正文、真实患者隐私、本地密钥或受限数据细节。

## 实验范围

本轮使用 PriMock57 本地数据中的 3 条 channel-level record：

- `primock57:day1_consultation01:doctor`
- `primock57:day1_consultation01:patient`
- `primock57:day1_consultation02:doctor`

ASR 使用 project 内部模型路径：

```text
data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo
```

clean/reference 从 record 中记录的 PriMock57 TextGrid reference 路径读取，仅用于本地评估；summary 不内联完整 reference/noisy transcript。

## 复现实验入口

本轮流水线摘要来自：

```text
outputs/primock57/asr_review_pipeline/asr_review_pipeline_run.json
```

等价顶层命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py --run-asr --asr-limit 3
```

评估命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_asr_quality.py
```

T035 本轮使用模拟审阅者反馈验证回放链路。反馈文件共 3 条 `doctor_feedback_entry/v1`，均为 `accept_asr`，仅表示“模拟审阅者接受当前 ASR span 文本”，不代表真实医生确认，也不代表转写质量提升：

```text
outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.simulated_accept_asr.jsonl
```

回放命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/apply_asr_review_feedback.py `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl `
  --feedback-jsonl outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.simulated_accept_asr.jsonl `
  --output-jsonl outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.simulated_accept_asr.jsonl `
  --run-config-json outputs/primock57/t035_confirmed_transcripts/t035_confirmed_transcripts_simulated_accept_asr_run.json
```

## 主要产物

| 阶段 | 产物 |
|---|---|
| T028 | `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl` |
| T037 | `outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl` |
| T038 | `outputs/primock57/t038_medical_entity_review/primock57_asr_confidence_medical_entities.jsonl` |
| T029 | `outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl` |
| T030 | `outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.jsonl` |
| T036 | `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html` |
| T035 | `outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.simulated_accept_asr.jsonl` |
| T031 | `outputs/primock57/t031_asr_quality_evaluation/primock57_t031_asr_quality_summary.json` |

`outputs/` 下产物默认不提交 Git。需要追查局部错误 span 时，可看 T031 annotation JSONL，但它含局部 reference/noisy 片段，只应留在本地研究排错。

## 各阶段运行结果

| 阶段 | 关键结果 |
|---|---|
| T028 ASR confidence（历史旧阈值） | 3 条 record；1958 个 ASR word；1795 green、163 yellow、0 red；word confidence mean 0.8874；当时阈值为 green ≥ 0.8、yellow ≥ 0.5；2026-07-13 起默认改为 0.9/0.8。 |
| T037 n-best | 3 条 record；每条 5 个 beam；共 15 个 sequence-level candidate；3 条均有多个 beam 且有唯一变体。 |
| T038 医学实体 gating | 3 条 record；医学实体着色词 133 个；医学实体待审阅 span 3 个，均为 yellow；非医学词显示为 neutral black。 |
| T029 候选对齐 | sequence alternatives 15 个；医学实体 uncertain spans 3 个；span alternatives 0 个；3 个 span 均无 span-level candidate。 |
| T030/T036 HTML | 3 个样本；3 个待审阅 span；支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`；反馈通过浏览器下载 JSONL/localStorage 导出。 |
| T035 反馈回放 | 读取 3 条模拟反馈；生成 3 条 confirmed transcript record；3 条均为 `confirmed`；`action_summary={"accept_asr": 3}`；missing/unresolved span 均为 0。 |
| T031 质量评估 | micro WER 0.3405；micro MC-WER 0.2526；macro ECE 0.0651；macro NCE 0.0580；span-level top-k exact coverage 0/3。 |

## noisy transcript 质量解释

当前 noisy ASR 不能只看界面是否流畅。本轮小样本 reference tokens 为 2373，ASR noisy tokens 为 1958，ASR 明显短于 reference。编辑错误中 deletion 为 453，高于 substitution 317 和 insertion 38，说明漏识别/省略是主要误差来源之一。

核心指标：

| 指标 | 数值 | 解释 |
|---|---:|---|
| micro WER | 0.3405 | token 级编辑距离约三分之一。 |
| macro WER | 0.3334 | 各 record 平均后与 micro 接近。 |
| micro MC-WER | 0.2526 | V0 医学/临床概念 token 错误率约四分之一。 |
| macro ECE | 0.0651 | confidence 有校准误差，但仍有一定可用信号。 |
| macro NCE | 0.0580 | confidence 比只用总体正确率略有信息量，但提升有限。 |
| Brier score | 0.1358 | token correctness 概率预测仍需校准。 |

confidence 分层有信号但还不够安全：

| level | token 数 | error rate | 医学概念 token error rate |
|---|---:|---:|---:|
| green | 1795 | 0.1543 | 0.1125 |
| yellow | 163 | 0.4785 | 0.0000 |
| red | 0 | NA | NA |

yellow 错误率明显高于 green，适合作为审阅排序线索。但 green 仍有约 15% token 错误，不能视作临床级“无需审阅”；本轮也没有 red，说明阈值和 confidence 尺度仍需按数据校准。

## 医学实体 gating 与 top-k 解释

T038 医学实体优先方向能显著减少医生界面的非医学低置信噪声：非医学词显示为黑字上下文，只让医学实体词保留颜色和反馈入口。

但 T031 显示医学关键错误覆盖仍不足：

| 指标 | 数值 |
|---|---:|
| medical concept error tokens | 9 |
| marked as medical entity error tokens | 2 |
| covered by uncertain span medical error tokens | 0 |
| medical entity marking coverage | 0.2222 |
| uncertain-span coverage | 0.0000 |

top-k 候选也不足：

| 指标 | 数值 |
|---|---:|
| uncertain spans | 3 |
| spans with span-level candidates | 0 |
| exact reference covered spans | 0 |
| sequence-level candidates | 15 |
| records where sequence candidate improves WER | 1 |
| mean sequence oracle WER improvement | 0.00068 |

因此，当前界面必须保留手动编辑、拒绝、无法判断，不应假设医生总能从 top-k 中点选正确答案。后续可以引入医学词表、规则候选或 LLM 辅助候选，但主线仍应把 ASR 原生 confidence 作为风险排序依据。

## T035 反馈回放说明

本轮 T035 的作用是补齐“医生/模拟审阅者反馈 → confirmed_transcript”的机制证据：

- 输入：T029 医学实体候选版 ASR confidence JSONL；
- 反馈：3 条模拟 `accept_asr` entry；
- 输出：3 条 `confirmed_transcript_record/v1`；
- 结果：3 条 record 均 `confirmed`，无 missing/unresolved span。

因为反馈动作全部是 `accept_asr`，本轮 confirmed transcript 与 ASR transcript 在这些 span 上保持一致。它只能证明回放机制可运行，不能证明真实医生审阅质量，也不能证明 confirmed transcript 比 raw ASR 更好。

实现时发现并修复一个兼容性问题：如果反馈 JSONL 由 Windows 工具写成带 UTF-8 BOM 的文件，旧读取器会解析失败。当前 `read_feedback_entries_jsonl()` 已改为 `utf-8-sig` 读取，并新增测试覆盖。

## 不依赖外部 `Speech-main` 的证据

T028 与 T037 run summary 均显示 NeMo import 路径来自 project 内部：

```text
third_party/speech_main/nemo/__init__.py
third_party/speech_main/nemo/collections/asr/__init__.py
```

对应验证字段：

| 阶段 | `nemo_paths_inside_project` | `external_speech_main_paths` |
|---|---:|---|
| T028 | true | `[]` |
| T037 | true | `[]` |

模型权重也来自 project 内：

```text
data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo
```

因此，本轮 ASR confidence、n-best 和闭环记录不依赖 project 外部 `D:\...\Speech-main` 路径。

## 验证

本轮新增/复验：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/apply_asr_review_feedback.py ...
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_review_workflow.py --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/review_workflow.py tests/test_review_workflow.py
```

结果：

- T035：`status=ok`，`feedback_entries_read=3`，`confirmed_records=3`，`missing_feedback_spans=0`，`unresolved_spans=0`；
- targeted pytest：`6 passed`；
- targeted ruff：`All checks passed`。

## 局限与下一步

1. 样本仍很小：当前只是 3 条 channel-level record，不是完整 PriMock57 consultation-level 评估。
2. 目前没有真实医生反馈：T035 只是模拟 `accept_asr` 回放，下一步需要设计审阅成本、点击次数、编辑比例和 unresolved 比例等指标。
3. 医学实体错误覆盖不足：需要用 T031 annotation 抽样看 false negative，优化实体识别、关键词兜底和 uncertain span 触发规则。
4. span-level top-k 覆盖不足：当前 3 个医学实体待审 span 均无 span candidate，后续应改进候选生成或引入辅助候选。
5. 还未做下游鲁棒性评估：下一阶段应接入症状/医学实体抽取或 sectioned note 信息保持评估，对比 raw ASR / simulated confirmed / reference。
