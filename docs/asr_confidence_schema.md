# T027 ASR confidence JSONL / Pydantic schema

更新时间：2026-07-02

本文定义项目侧 ASR confidence JSONL 记录。它服务于近期主线：

**音频 → ASR noisy transcript + 词/片段置信度 + 时间戳 + n-best 候选 → 绿/黄/红审阅样本 → confirmed transcript。**

对应 Pydantic schema 位于：

- `src/clinical_asr_robustness/asr_confidence.py`
- 主要入口：`ASRConfidenceRecord`
- JSONL 读写：`read_asr_confidence_jsonl()` / `write_asr_confidence_jsonl()`

## 记录粒度

第一版建议：

- 一行 JSONL = 一路音频 / 一个 channel 的 ASR 输出；
- PriMock57 第一批样本先分别保存 `source_channel="doctor"` 与 `source_channel="patient"`；
- 后续双路按时间合并后，可另存 `source_channel="mixed"` 的 consultation-level 记录。

不要在 ASR confidence JSONL 中内联人工 reference transcript 正文。只保存 `reference_textgrid_path`、`reference_transcript_path` 这类指针；schema 会拒绝 `reference_text_included=true`。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 当前为 `asr_confidence_record/v1`。 |
| `record_id` | string/null | 可选，ASR 输出记录 ID。 |
| `sample_id` | string | 与 manifest 对齐的样本 ID。 |
| `dataset` / `split` / `consultation_id` | string/null | 数据集和咨询会话信息。 |
| `source_channel` | enum | `doctor`、`patient`、`mixed` 或 `unknown`。 |
| `audio_filepath` / `duration_sec` | string/null, number/null | 音频指针与时长。 |
| `reference_textgrid_path` / `reference_transcript_path` | string/null | reference 指针，不保存正文。 |
| `reference_text_included` | bool | 必须为 `false`。 |
| `asr_transcript` | string | ASR noisy transcript。 |
| `asr_confidence` | number/null | 可选的整条转写平均或总体置信度。 |
| `confidence_level` | enum | 整条记录的绿/黄/红风险等级。 |
| `asr_words` | list | 词级 ASR 输出，见下文。 |
| `asr_segments` | list | 片段级输出，供界面展示。 |
| `uncertain_spans` | list | 连续中/低置信度词合并后的待审阅 span。 |
| `asr_alternatives` | list | ASR n-best / beam 候选。 |
| `model` | object | 模型和权重来源信息。 |
| `decoding` | object | 解码配置摘要。 |
| `confidence` | object | 置信度方法、聚合方式和阈值。 |
| `alignment` | object | timestamp/confidence 对齐诊断。 |
| `runtime` / `metadata` | object | 运行环境和额外信息。 |
| `research_use_only` / `clinical_use_warning` | bool, string | 标注为研究输出，不构成临床建议。 |

## 词级字段：`asr_words`

`asr_words` 是后续高亮、span 合并和医生点击的基础。每个元素使用：

| 字段 | 说明 |
|---|---|
| `word_index` | 0-based 词序，必须连续。 |
| `text` | ASR 输出词文本。 |
| `start_sec` / `end_sec` | 词级时间戳；缺失时为 `null`。 |
| `confidence` | 词级置信度；缺失时为 `null`。 |
| `confidence_level` | `green` / `yellow` / `red` / `unknown`。若未显式填写且有 `confidence`，schema 会按默认阈值补齐。 |
| `alignment_status` | `aligned`、`missing_timestamp`、`missing_confidence`、`missing_timestamp_and_confidence`。 |
| `timestamp_source` / `confidence_source` | 例如 `nemo.timestamp.word`、`nemo.word_confidence`。 |
| `char_start` / `char_end` | 可选，词在 `asr_transcript` 中的字符偏移。 |
| `speaker_label` / `metadata` | 可选扩展字段。 |

默认颜色阈值：

- 绿：`confidence >= 0.90`
- 黄：`0.80 <= confidence < 0.90`
- 红：`confidence < 0.80`

上述默认值自 2026-07-13 起用于当前 PriMock57 + NeMo 原生
`word_confidence` 主线。它是根据本地分数分布和 3 条 reference 对齐校准样本选择的
研究性操作点：校准样本中绿/黄/红错误率依次为 7.78% / 24.84% / 47.85%，
全量 75,597 词预计占比约 68.4% / 26.3% / 5.3%。这不是临床级校准结论，
更换 ASR 模型、confidence 方法或数据域后必须重新评估阈值。
- 缺失：`unknown`

## 片段与待审阅 span

`asr_segments` 面向界面展示，可来自 ASR 原生 segment，也可从连续词合并得到。词范围统一使用半开区间：

```text
[start_word_index, end_word_index)
```

`uncertain_spans` 是后续医生点击和候选弹窗的核心输入，只应包含中/低置信度或规则触发的风险片段。schema 不允许将 uncertain span 标成 `green`；如果 `min_confidence` 或 `mean_confidence` 推出绿色，会自动降为 `yellow`，提醒后续阈值或合并逻辑需要复查。

## 候选：`asr_alternatives`

V0 的候选来源按 D004 决策：

- NeMo beam / n-best 首先作为 `scope="sequence"` 的整句候选保存；
- T029 再把 sequence-level n-best 与 `uncertain_spans` 对齐，得到 `scope="span"` 的候选；
- 若未来加入规则、词表或 LLM repair 候选，应在 `source` 中明确标注，不要混同为 ASR 原生置信度。

核心字段：

| 字段 | 说明 |
|---|---|
| `alternative_id` | 候选 ID，整条记录内唯一。 |
| `scope` | `sequence`、`segment`、`span` 或 `word`。 |
| `rank` | 候选排序，1 为最优。 |
| `text` | 候选文本。 |
| `span_id` | 对齐到 uncertain span 后填写。 |
| `start_word_index` / `end_word_index` | 可选词范围。 |
| `score` / `confidence` | ASR beam score 或候选置信度。 |
| `source` | 例如 `asr_nbest`、`nemo_beam`。 |
| `alignment_method` | 例如 `sequence_nbest_diff`。 |

非 `sequence` 候选必须填写 `span_id` 或词范围，避免候选无法回放到界面片段。

## 模型、解码和置信度配置

`model` 建议记录：

- `provider`：第一版为 `nemo`；
- `model_name`；
- `model_path`：project 内相对路径，例如 `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`；
- `model_class`；
- 可选 `checkpoint_sha256`。

`decoding` 建议记录：

- `strategy`：`greedy`、`beam` 等；
- `beam_size`、`n_best`；
- `batch_size`、`device`；
- `timestamps_enabled`、`return_hypotheses`；
- 原始 NeMo decoding config 可放入 `config`。

`confidence` 第一版默认对应 NeMo entropy confidence：

```yaml
method_name: entropy
entropy_type: tsallis
alpha: 0.33
entropy_norm: lin
aggregation: mean
preserve_token_confidence: true
preserve_word_confidence: true
exclude_blank: true
source_field: word_confidence
thresholds:
  green_min: 0.90
  yellow_min: 0.80
```

说明：T028 初版曾沿用 NeMo 默认 `entropy_norm=exp`，但在 PriMock57
`day1_consultation01:patient` 上实测 word confidence 最大仅约 0.075，导致全红；
同一配置改为论文同样支持的线性归一化 `entropy_norm=lin` 后，词级均值约 0.912，
可作为当前 demo 默认。`exp`、`max_prob` 和不同 `aggregation` 仍可作为消融或
sanity-check baseline，并应在 `confidence` 字段中准确记录。

## timestamp 与 confidence 数量不一致规则

T026 已观察到：

- `asr_transcript` word count = 407
- `word_confidence` count = 407
- `word timestamp` count = 408

因此 T027 明确采用以下导出策略：

```text
policy = word_text_anchored_trim_extras_keep_missing
```

具体规则：

1. 以 `asr_transcript.split()` 得到的 ASR 输出词序作为主锚点；
2. `asr_words` 长度应等于 ASR 输出词数，而不是 timestamp 数量；
3. 按 index 对齐 `word_confidence` 与 `word timestamp`；
4. 如果 timestamp 或 confidence 比 ASR 输出词多，不新增空词，额外项写入：
   - `alignment.dropped_extra_word_timestamps`
   - `alignment.dropped_extra_word_confidences`
5. 如果某个 ASR 输出词缺少 timestamp 或 confidence，仍保留该词，并设置：
   - `start_sec/end_sec = null` 或 `confidence = null`
   - `alignment_status = missing_timestamp` / `missing_confidence` / `missing_timestamp_and_confidence`
   - 对应 index 写入 `alignment.missing_timestamp_word_indices` 或 `alignment.missing_confidence_word_indices`
6. `asr_segments` 和 `uncertain_spans` 只基于保留下来的 `asr_words` 词序计算；
7. segment/span 的时间戳可取覆盖词中第一个和最后一个非空时间戳；置信度可用 mean/min 等聚合，但必须记录 `confidence_aggregation`。

这条规则的核心是不因为 NeMo 原始数组长度不一致而丢失 ASR 已输出词，也不把额外 timestamp 伪造成一个新词。

## 最小 JSONL 示例

以下是合成示例，不对应真实患者或受限数据：

```json
{
  "schema_version": "asr_confidence_record/v1",
  "record_id": "asr_demo_001",
  "sample_id": "primock57:demo:patient",
  "dataset": "primock57",
  "source_channel": "patient",
  "audio_filepath": "data/raw/primock57/audio/demo_patient.wav",
  "reference_text_included": false,
  "asr_transcript": "patient reports cough",
  "asr_confidence": 0.7,
  "confidence_level": "yellow",
  "asr_words": [
    {"word_index": 0, "text": "patient", "start_sec": 0.0, "end_sec": 0.4, "confidence": 0.93},
    {"word_index": 1, "text": "reports", "start_sec": 0.4, "end_sec": 0.8, "confidence": 0.77},
    {"word_index": 2, "text": "cough", "start_sec": 0.8, "end_sec": 1.1, "confidence": 0.42}
  ],
  "asr_segments": [
    {
      "segment_id": "seg_001",
      "text": "patient reports cough",
      "start_word_index": 0,
      "end_word_index": 3,
      "start_sec": 0.0,
      "end_sec": 1.1,
      "confidence": 0.7,
      "confidence_aggregation": "mean"
    }
  ],
  "uncertain_spans": [
    {
      "span_id": "span_001",
      "text": "cough",
      "start_word_index": 2,
      "end_word_index": 3,
      "mean_confidence": 0.42,
      "min_confidence": 0.42,
      "alternative_ids": ["alt_span_001_rank_1"]
    }
  ],
  "asr_alternatives": [
    {
      "alternative_id": "alt_span_001_rank_1",
      "scope": "span",
      "rank": 1,
      "text": "mild cough",
      "span_id": "span_001",
      "source": "asr_nbest",
      "alignment_method": "sequence_nbest_diff"
    }
  ],
  "model": {
    "provider": "nemo",
    "model_name": "stt_en_fastconformer_ctc_large",
    "model_path": "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
  },
  "decoding": {
    "strategy": "greedy",
    "batch_size": 1,
    "device": "cuda",
    "timestamps_enabled": true,
    "return_hypotheses": true
  },
  "confidence": {
    "method_name": "entropy",
    "entropy_type": "tsallis",
    "alpha": 0.33,
    "entropy_norm": "lin",
    "aggregation": "min",
    "source_field": "word_confidence"
  },
  "alignment": {
    "policy": "word_text_anchored_trim_extras_keep_missing",
    "transcript_word_count": 3,
    "word_timestamp_count": 4,
    "word_confidence_count": 3,
    "asr_word_count": 3,
    "paired_word_count": 3,
    "dropped_extra_word_timestamps": [
      {
        "raw_index": 3,
        "raw_value": {"word": "", "start_offset": 1.1, "end_offset": 1.1},
        "reason": "timestamp_without_output_word"
      }
    ]
  },
  "research_use_only": true,
  "clinical_use_warning": "本记录仅用于研究评估，不构成临床建议。"
}
```

## 对后续任务的接口约定

- T028：NeMo 导出脚本应直接写 `ASRConfidenceRecord` JSONL，并填好 `alignment` 诊断。
- T029：n-best/top-k 抽取脚本应追加或生成 `asr_alternatives`，并把 span 候选 ID 写入 `uncertain_spans[].alternative_ids`。
- T030：绿/黄/红审阅样本包应优先消费 `asr_words`、`asr_segments`、`uncertain_spans` 和 `asr_alternatives`。
- T035/T036：医生反馈和 HTML demo 不应修改 ASR 原始输出；应在反馈日志和 confirmed transcript 记录中引用 `record_id`、`span_id`、`alternative_id`。
