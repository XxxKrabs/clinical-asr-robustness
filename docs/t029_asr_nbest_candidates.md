# T029 ASR n-best/top-k 候选抽取策略

更新时间：2026-07-02

T029 已新增项目侧候选抽取入口：

- 模块：`src/clinical_asr_robustness/asr_nbest_candidates.py`
- 脚本：`scripts/extract_asr_nbest_candidates.py`
- 单元测试：`tests/test_asr_nbest_candidates.py`

## 目标

在 T028 生成的 ASR confidence JSONL 基础上，追加 n-best/top-k 候选：

1. 将 ASR beam / n-best 输出保存为 `scope="sequence"` 的整句候选；
2. 用词级 diff 将 sequence-level n-best 对齐到连续中/低置信度 `uncertain_spans`；
3. 生成 `scope="span"` 的候选，并把候选 ID 回写到 `uncertain_spans[].alternative_ids`。

本任务只处理 ASR 输出层候选，不读取或内联 reference transcript 正文，也不把候选内容视作临床建议。

## V0 策略

V0 沿用 D004 决策：不做每个词独立 top-k，而是使用 sequence-level beam n-best。

对每条 ASR confidence record：

1. 读取 `asr_transcript.split()` 作为 base word 序列；
2. 读取外部 n-best JSONL，或复用 record 内已有 `scope="sequence"` 候选；
3. 先把 n-best 候选写入 `asr_alternatives`：
   - `scope="sequence"`
   - `source="nemo_beam"` 或输入指定 source
   - `alignment_method="sequence_nbest"`
4. 对每个 `uncertain_span`，使用 `difflib.SequenceMatcher` 比较 base words 与候选 words；
5. 若 n-best 在 span 内或边界发生 replace / insert / delete，裁剪出候选局部文本；
6. 写入 `scope="span"` 候选：
   - `span_id`
   - `start_word_index` / `end_word_index` 使用原 ASR span 范围；
   - `alignment_method="sequence_nbest_diff"`
   - `metadata.sequence_alternative_id` 指回来源整句候选。

默认跳过与原 span 文本完全相同的 span 候选，但仍保留 sequence-level n-best。

## n-best JSONL 输入格式

推荐一行对应一条 ASR confidence record：

```json
{
  "sample_id": "primock57:demo:patient",
  "source": "nemo_beam",
  "beams": [
    ["patient reports cough now", -0.1],
    ["patient reports chest pain now", -0.3]
  ]
}
```

也支持：

- `record_id` 或 `sample_id` 匹配；
- `nbest` / `alternatives` / `beams` / `hypotheses` 作为候选列表字段；
- 一行一个候选：

```json
{"sample_id": "primock57:demo:patient", "rank": 1, "text": "patient reports cough now", "score": -0.1}
```

NeMo `transcribe_utils.write_transcription()` 在 `extract_nbest=True` 且 beam 返回多候选时，常见字段为 `beams`，形如：

```json
"beams": [["hypothesis text", -123.4], ["another hypothesis", -125.6]]
```

该格式可直接作为本脚本的 `--nbest-jsonl` 输入。

## 可复现命令

若已有 T028 ASR confidence JSONL 与外部 n-best JSONL：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py \
  --input-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence.jsonl \
  --nbest-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_sequence_nbest.jsonl \
  --output-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl
```

若输入 record 已经包含 `scope="sequence"` 候选，也可以省略 `--nbest-jsonl`：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py \
  --input-jsonl path/to/asr_confidence_with_sequence_alternatives.jsonl \
  --output-jsonl path/to/asr_confidence_with_span_candidates.jsonl
```

默认输出：

- `outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl`
- `outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_run.json`

`outputs/` 默认被 `.gitignore` 忽略；ASR transcript 和 n-best 属于本地研究输出，不应提交。

## 当前验证

已新增无需 NeMo/GPU 的单元测试，覆盖：

- sequence 候选对齐到 span 时保留局部候选窗口；
- insert / replace 情况的 span candidate 裁剪；
- sequence alternatives 写入；
- span alternatives 写入和 `uncertain_spans[].alternative_ids` 回写；
- n-best JSONL 的 record-level 与 item-level 两种格式解析。

验证命令：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_asr_nbest_candidates.py --basetemp=.pytest_tmp
```

本次运行结果：`3 passed`。

## 局限与后续

- T029 是候选抽取策略层；真实 NeMo beam 解码可作为上游生成 `beams` JSONL，再接入本脚本。
- 若某个 uncertain span 覆盖整条长音频，span 候选也可能变成长文本。后续 T030/T031 应结合阈值校准、最大 span 长度或 segment 边界拆分。
- 删除类差异如果在候选中没有可展示文本，V0 会跳过空候选；后续可在医生界面中单独表示“删除/空候选”动作。
- n-best 不等价于真实词级 top-k；后续若需要更精细的点击候选，可继续探索 token/frame-level top-k 或词表/规则辅助候选，并明确标注来源。
