# T039 候选覆盖改进记录

更新时间：2026-07-08

## 目标

T039 解决 T031/T032 暴露的一个具体问题：T038 医学实体 gating 后，待审阅 span 只剩少量医学实体，但 T029 的 sequence-level n-best diff 没能为这些 span 生成可点击候选。本任务不追求普通上下文词全量候选，而是优先让“医学实体/重点审阅 span”有可用候选。

关键边界：

- ASR 原生 n-best / beam 仍保留为 `source="nemo_beam"` 等 ASR-native 候选；
- 医学词表/模糊匹配只作为辅助候选，使用 `source="medical_lexicon_aux_candidate"`；
- 辅助候选 metadata 明确写入 `generated_by="T039"`、`candidate_type="auxiliary_medical_lexicon"`、`asr_native_candidate=false`、`reference_used=false`；
- 候选生成不读取 clean/reference transcript；reference 只在 T031 评估阶段使用。

## 实现文件

- `src/clinical_asr_robustness/asr_nbest_candidates.py`
  - 新增 T039 医学词表/模糊候选生成；
  - 只在医学实体待审 span 没有 ASR-native span 候选时添加辅助候选；
  - 保留 T029 sequence/span n-best 原有逻辑。
- `scripts/extract_asr_nbest_candidates.py`
  - 默认启用 T039 辅助候选；
  - 新增 `--disable-aux-medical-candidates`、`--aux-medical-lexicon-json`、`--max-auxiliary-span-alternatives`、`--aux-min-similarity`；
  - run summary 新增按候选来源统计。
- `configs/medical_candidate_lexicon.example.json`
  - 轻量医学候选词表示例，可后续按数据集扩展。
- `src/clinical_asr_robustness/asr_quality_evaluation.py`
  - T031 span top-k summary 新增按 `source` 的 candidate count、spans-with-candidates 和 exact reference coverage。
- `tests/test_asr_nbest_candidates.py`
  - 覆盖无 ASR span 候选时的医学词表辅助候选。
- `tests/test_asr_quality_evaluation.py`
  - 覆盖按候选来源统计的 summary 字段。

## 策略说明

T039 的执行顺序：

1. 先写入 sequence-level ASR n-best；
2. 再沿用 T029 diff 策略尝试生成 ASR-native span candidate；
3. 若某个 span 是 T038 医学实体待审 span，且没有任何 span-level candidate，则进入 T039 兜底；
4. T039 从内置词表与可选 JSON 词表中按实体类别和 `_global` 候选池取词；
5. 用轻量规整后的字符相似度、compact 字符相似度和 token overlap 取最大值排序；
6. 跳过与原 span 文本完全相同的候选，默认最多补足 `--max-span-alternatives` 个辅助候选。

本轮词表补充了 `back pain`、`back ache`、`feeling sick`、`feeling weak` 等通用短语，使当前 T038 产出的疑似医学实体误报也能进入“可选择/可拒绝/可编辑”的交互流程。它不是在断言这些候选正确，而是在降低“候选面板空白”的交互失败率。

## 可复现命令

复跑 T029：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py --input-jsonl outputs/primock57/t038_medical_entity_review/primock57_asr_confidence_medical_entities.jsonl --nbest-jsonl outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl --output-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl --run-config-json outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_run.json
```

复跑 T031：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_asr_quality.py --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl --output-dir outputs/primock57/t031_asr_quality_evaluation
```

复跑 T030/T036：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl --output-jsonl outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.jsonl --output-csv outputs/primock57/t030_review_samples/primock57_medical_entity_review_spans.csv --output-html outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.html --run-config-json outputs/primock57/t030_review_samples/t030_review_samples_run.json --interactive-html

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_doctor_review_demo_html.py --review-jsonl outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.jsonl --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl --output-html outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html --embedded-review-jsonl outputs/primock57/t036_doctor_review_demo/doctor_review_samples.embedded.jsonl --run-config-json outputs/primock57/t036_doctor_review_demo/t036_doctor_review_demo_run.json --title "T036 医学实体优先 ASR 医生审阅 demo"
```

## 本轮结果

T029 run summary：

| 指标 | 结果 |
|---|---:|
| records | 3 |
| sequence alternatives | 15 |
| total uncertain spans | 3 |
| span alternatives | 5 |
| spans with alternatives | 3/3 |
| span alternatives by source | `medical_lexicon_aux_candidate`: 5 |
| spans with alternatives by source | `medical_lexicon_aux_candidate`: 3 |
| no inline reference text | true |

T031 summary：

| 指标 | 结果 |
|---|---:|
| micro WER | 0.3405 |
| micro MC-WER | 0.2526 |
| total uncertain spans | 3 |
| spans with candidates | 3/3 |
| exact reference covered spans | 0/3 |
| candidate count by source | `medical_lexicon_aux_candidate`: 5 |
| exact coverage by source | `medical_lexicon_aux_candidate`: 0/3 |

T030 run summary：

| 指标 | 结果 |
|---|---:|
| records read | 3 |
| total uncertain spans | 3 |
| spans with candidates | 3/3 |
| span confidence levels | yellow: 3 |
| no inline reference text | true |

T036 已重新生成：

- `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`
- `outputs/primock57/t036_doctor_review_demo/doctor_review_samples.embedded.jsonl`

## 解读

T039 已把当前医学实体待审 span 的候选可用性从 0/3 提升到 3/3，但 exact reference coverage 仍为 0/3。这说明辅助候选解决的是“医生界面不要空白”的交互问题，不等于正确修复 ASR 错误。

本轮两个待审 span 似乎来自 T038 医学实体误报或过宽实体范围，因此后续仍需要继续优化 T038 entity postprocess 和绿色医学实体的点击检查策略。医生交互界面必须继续保留手动编辑、拒绝候选和无法判断，不应假设候选总能覆盖正确答案。

## 验证

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
```

本轮结果：

- `pytest`：47 passed；
- `ruff check .`：All checks passed。
