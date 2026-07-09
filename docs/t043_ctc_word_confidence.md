# T043 CTC posterior/entropy 词级置信度流水线

更新时间：2026-07-09

本任务把当前 ASR 置信度主线从“看起来偏段级/NeMo 已聚合结果”进一步明确为：

```text
NeMo FastConformer-CTC frame log_probs / posterior
  → frame-level entropy 或 max-prob confidence
  → CTC greedy collapse 后的 token confidence
  → SentencePiece/BPE token span 聚合到 word confidence
  → asr_words[].confidence
  → 低置信医学实体 span 风险定位
```

本任务只模仿论文 *Fast Entropy-Based Methods of Word-Level Confidence Estimation for E2E ASR* 中“从 CTC posterior / entropy 得到 word-level confidence”的 pipeline；不复现整篇论文、不训练置信度模型、不替换现有 NeMo FastConformer-CTC ASR 主干。

## 代码入口

- `src/clinical_asr_robustness/ctc_word_confidence.py`
  - 支持输入 `logits`、`log_probs` 或 `posterior`；
  - 支持 `entropy` / `max_prob` frame confidence；
  - `entropy` 支持 `gibbs`、`tsallis`、`renyi` 与 `lin` / `exp` 归一化；
  - CTC collapse 时排除 blank；
  - token/word 聚合支持 `mean`、`min`、`max`、`prod`；
  - 可保存/读取 `.npz` frame distribution artifact。
- `src/clinical_asr_robustness/nemo_confidence_export.py`
  - `build_asr_confidence_record()` 新增 `word_confidences_override`；
  - 当 T028 CLI 选择 CTC frame pipeline 时，`asr_words[].confidence_source` 会写成 `ctc_frame_distribution.word_confidence`；
  - `alignment.metadata.confidence_override_used=true` 用于区分 NeMo 原生 `word_confidence` 与项目侧 frame-derived word confidence。
- `scripts/export_nemo_asr_confidence.py`
  - 默认行为不变，仍可使用 NeMo `word_confidence`；
  - 新增 `--word-confidence-source ctc_frame_distribution` 后，从 Hypothesis 保存的 frame log_probs 重新计算词级置信度；
  - 新增 `--save-frame-distributions` 保存 frame-level `log_probs` 或 `posterior` artifact，便于离线复算和方法消融。

## 新增命令示例

默认旧链路：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py --limit 1
```

启用 CTC frame → word confidence，并保存 frame log_probs：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 1 \
  --word-confidence-source ctc_frame_distribution \
  --save-frame-distributions \
  --frame-distribution-kind log_probs
```

保存 posterior artifact：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 1 \
  --word-confidence-source ctc_frame_distribution \
  --save-frame-distributions \
  --frame-distribution-kind posterior
```

输出记录中应重点检查：

- `confidence.source_field == "ctc_frame_distribution.word_confidence"`；
- `asr_words[].confidence_source == "ctc_frame_distribution.word_confidence"`；
- `asr_words[].metadata.ctc_word_confidence.tokens` 是否包含 token frame 范围与 token confidence；
- `alignment.metadata.confidence_override_used == true`；
- run summary 中 `confidence_distribution.ctc_frame_distribution.word_alignment_status_counts` 是否主要为 `aligned`。

## 与医学实体低置信 span 的关系

T043 不改变 T038 的医学实体 gating 策略，也不改变 T029 的候选生成逻辑。它改变的是进入这些环节前的基础词级分数：

1. `asr_words[].confidence` 来自 CTC frame posterior/log_probs 的 entropy 聚合；
2. `build_uncertain_spans_from_words()` 仍按词级红/黄/未知连续合并；
3. T038 仍只保留医学实体覆盖范围内的非 green span；
4. 因此低置信医学 span 的风险定位会更清楚地追溯到帧级不确定性，而不是只依赖段级或黑盒聚合结果。

## 当前验证

已运行：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest \
  tests/test_ctc_word_confidence.py tests/test_nemo_confidence_export.py \
  --basetemp=.pytest_tmp

/home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check \
  src/clinical_asr_robustness/ctc_word_confidence.py \
  src/clinical_asr_robustness/nemo_confidence_export.py \
  scripts/export_nemo_asr_confidence.py \
  tests/test_ctc_word_confidence.py
```

结果：

- `9 passed`
- `ruff` 通过

## 后续建议

1. 用 `--limit 1 --word-confidence-source ctc_frame_distribution --save-frame-distributions` 跑一次真实 PriMock57 样本，检查 token→word 对齐是否为 `aligned`。
2. 对同一批样本比较：
   - NeMo 原生 `word_confidence`；
   - T043 `entropy + tsallis + lin + mean`；
   - `min` 聚合；
   - `max_prob` baseline。
3. 复跑 T038→T029→T036，观察医学实体待审 span 数量、黄/红分布和医生确认成本是否变化。
4. 在 T031 中单列 `confidence.source_field`，避免把不同来源的词级分数混在同一校准表里。
