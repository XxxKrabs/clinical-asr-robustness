# NeMo ASR 置信度代码理解记录

更新时间：2026-07-01

本文记录本次为“音频 → ASR → top-k 候选 + 置信度”主线阅读本地 `Speech-main` 代码后的理解。目标不是替代正式实验记录，而是帮助后续实现时快速知道 NeMo 哪些模块能直接用、哪些地方需要项目侧适配。2026-07-02 已将后续会用到的外部仓库资产迁移到 project 内：源码/示例位于 `third_party/speech_main/`，权重位于 `data/external/asr_models/nemo/`。

## 阅读范围

- 原始阅读仓库：`D:\Chasingfordream\内地部分\文书合集\清华大学神经调控\Speech-main`
- project 内迁移快照：`third_party/speech_main/`
- 重点文件：
  - `nemo/collections/asr/parts/utils/asr_confidence_utils.py`
  - `nemo/collections/asr/parts/utils/confidence_metrics.py`
  - `nemo/collections/asr/parts/utils/asr_confidence_benchmarking_utils.py`
  - `nemo/collections/asr/parts/utils/rnnt_utils.py`
  - `nemo/collections/asr/parts/utils/transcribe_utils.py`
  - `nemo/collections/asr/parts/submodules/ctc_decoding.py`
  - `nemo/collections/asr/parts/submodules/rnnt_decoding.py`
  - `examples/asr/transcribe_speech.py`
  - `examples/asr/asr_chunked_inference/rnnt/speech_to_text_streaming_infer_rnnt.py`
  - `examples/asr/conf/asr_streaming_inference/*.yaml`
  - `nemo/collections/asr/inference/utils/bpe_decoder.py`
  - `nemo/collections/asr/inference/utils/text_segment.py`

## 总体结论

NeMo 已经实现了论文 *Fast Entropy-Based Methods of Word-Level Confidence Estimation for End-to-End Automatic Speech Recognition* 对应的 entropy confidence 路线。核心配置在 `ConfidenceMethodConfig` / `ConfidenceConfig`：

- 置信度方法支持 `max_prob` 和 `entropy`。
- `entropy` 支持 `gibbs`、`tsallis`、`renyi` 三类。
- 熵归一化支持 `lin` 和 `exp`。
- 当前 demo 默认使用 `entropy` + `tsallis` + `alpha=0.33` + `entropy_norm=lin`。
- frame/token 到 word 的聚合支持 `mean`、`min`、`max`、`prod`。

这和本项目 ASR 主线高度适配：可以把 NeMo 生成的 `word_confidence` 或 token/segment confidence 作为绿/黄/红风险高亮的主来源。

## 关键实现点

### 1. 置信度算法

`asr_confidence_utils.py` 中的核心类和函数：

- `ConfidenceMethodConfig`：定义 `name`、`entropy_type`、`alpha`、`entropy_norm`。
- `ConfidenceConfig`：定义是否保留 frame/token/word confidence、是否排除 blank、聚合方式等。
- `get_confidence_measure_bank()`：注册 `max_prob` 和各种 entropy measure。
- `get_confidence_aggregation_bank()`：注册 `mean/min/max/prod` 聚合。
- `ConfidenceMethodMixin` / `ConfidenceMixin`：在 CTC/RNNT 解码器中初始化和调用置信度计算。

对本项目而言，第一版建议先固定：

```yaml
confidence_cfg:
  preserve_frame_confidence: true
  preserve_token_confidence: true
  preserve_word_confidence: true
  exclude_blank: true
  aggregation: mean
  method_cfg:
    name: entropy
    entropy_type: tsallis
    alpha: 0.33
    entropy_norm: lin
```

T028 初版沿用 NeMo 默认 `entropy_norm=exp`，但在 PriMock57
`day1_consultation01:patient` 上得到最大约 0.075、全 red 的词级分数；改用论文同样
支持的 `lin` 归一化后均值约 0.912，适合作为当前绿/黄/红 demo 默认。后续仍应比较
`entropy_norm=exp`、`aggregation=min`、`alpha=0.5` 或 `max_prob` baseline。

### 2. Hypothesis 输出结构

`rnnt_utils.py` 的 `Hypothesis` 是统一承载对象，和本项目需要的字段直接相关：

- `text`：ASR 输出文本。
- `timestamp`：token/word/segment 时间戳，取决于解码设置。
- `frame_confidence`：frame 级置信度。
- `token_confidence`：token 级置信度。
- `word_confidence`：word 级置信度。
- `score`：beam 或 hypothesis 分数。
- `words` 属性：从 `text.split()` 得到 word list。

项目侧应把这些字段序列化为自己的 `asr_words` / `asr_segments` / `asr_alternatives`，不要直接依赖 NeMo 对象格式。

### 3. CTC 与 RNNT 解码

`ctc_decoding.py` 与 `rnnt_decoding.py` 都包含 `confidence_cfg`。解码时大致流程是：

1. 保留 frame confidence；
2. 聚合得到 token confidence；
3. 再聚合得到 word confidence；
4. 如开启 timestamps，则额外计算 token/word/segment 时间戳。

需要注意：高层 `compute_confidence()` 更自然地服务 greedy 解码路径。n-best/beam 分支可返回多个 hypothesis，但不是所有路径都会同时给每个 beam hypothesis 计算 word confidence。因此第一版可能需要“两次解码”：

- greedy 或 best hypothesis：用于主 transcript + word confidence + timestamps；
- beam/n-best：用于候选列表，再和低置信度 span 做对齐。

### 4. 通用离线转写脚本

`examples/asr/transcribe_speech.py` 支持：

- `dataset_manifest` 或 `audio_dir` 输入；
- `timestamps=True`；
- `return_hypotheses=True`；
- `extract_nbest=True`；
- CTC/RNNT/hybrid 解码配置；
- WER/CER 计算。

但有一个重要适配点：`transcribe_utils.write_transcription()` 本身支持 `confidence=True` 时写出 `word_confidence` 和 `words`，可是 `transcribe_speech.py` 当前调用它时没有传入 `confidence=True`。因此如果直接跑官方脚本，未必能得到项目需要的完整 word confidence JSONL。

建议第一版不要修改或依赖原始外部 `Speech-main`，而是在本项目内新增适配脚本，调用 project 内迁移快照或已安装 NeMo 的 API，拿到 `Hypothesis` 后按项目 schema 写 JSONL。

### 5. RNNT 流式/长音频脚本

`examples/asr/asr_chunked_inference/rnnt/speech_to_text_streaming_infer_rnnt.py` 有显式 `confidence: bool` 开关。开启后会：

- 设置 `preserve_frame_confidence=True`；
- 设置 `preserve_word_confidence=True`；
- 调用 `asr_model.decoding.compute_confidence()`；
- 调用 `write_transcription(..., confidence=cfg.confidence)`。

这条路径适合长音频或流式 demo，但第一阶段如果只是 PriMock57 小批量离线 ASR，可能比通用离线适配脚本更重。

### 6. 新 inference pipeline 与 BPE 后处理

`nemo/collections/asr/inference/utils/bpe_decoder.py` 可以把 BPE tokens + timestamps + confidences 聚合为：

- `Word(text, start, end, conf)`
- `TextSegment(text, start, end, conf)`

这非常贴合本项目 UI/交互数据结构：词级高亮可以用 `Word`，片段级高亮可以用 `TextSegment`。后续如果采用 NeMo 的 streaming pipeline，可优先复用这一路的输出思想。

### 7. 置信度评估工具

`asr_confidence_benchmarking_utils.py` 和 `confidence_metrics.py` 已有：

- `get_correct_marks()`：reference 与 hypothesis 对齐后标记预测 token/word 是否正确；
- token/word confidence benchmark；
- AUC-ROC、AUC-PR、AUC-NT、NCE、ECE、AUC-YC；
- 置信度直方图和曲线保存。

本项目可复用思想，但要补充医学任务所需指标，例如医学概念错误率、否定词错误、药名错误、top-k 覆盖率和交互成本。

## 与本项目的适配风险

1. **top-k 候选并不等于词级候选。** NeMo 的 `extract_nbest` 主要给 sequence-level beam hypotheses。医生点击某个黄/红词后展示的“候选”，需要项目侧把 n-best 序列与低置信度 span 对齐，或另做 CTC/RNNT token-level top-k 提取。
2. **confidence 与 n-best 可能需要分两次跑。** 标准 beam/n-best 路径未必同时保留每个候选的 word confidence。第一版可以用 greedy/best 输出 confidence，用 beam 输出 alternatives。
3. **标准 `transcribe_speech.py` 不直接写 confidence。** 需要项目侧导出适配脚本，或修改调用参数；建议不要改外部仓库。
4. **删除错误天然没有 ASR token confidence。** 置信度只附着在 ASR 发出的 token/word 上；reference 中被漏识别的医学词需要通过相邻低置信度片段、空缺对齐或事后错误分析补充评价。
5. **PriMock57 是模拟初级医疗问诊。** 许可友好、无真实患者隐私，更适合第一阶段；但真实临床远场、重叠说话和口音复杂度不足，后续仍需 DISPLACE-M 等扩展。
6. **PriMock57 音频是 doctor/patient 双路文件。** 第一版要决定是分别转写后合并，还是先混音成单路对话音频。

## 建议第一版技术路线

1. 先用 PriMock57 做 3-5 条咨询的 manifest：保留 doctor/patient 两路 audio path、TextGrid reference、notes 指针和许可说明。
2. 使用 NeMo 本地仓库或已安装 NeMo 环境，选择一个能跑通的 CTC/RNNT 英文模型。
3. 用 entropy confidence 配置跑出 best hypothesis 的 `text`、`word_confidence`、word timestamps。
4. 单独开启 beam/n-best，得到 sequence-level alternatives。
5. 将 n-best 对齐到低/中置信度 word/span，形成第一版点击候选；若对齐不稳定，先记录为 sequence-level alternatives。
6. 写入项目 JSONL：`audio_id`、`speaker_channel`、`asr_transcript`、`asr_words`、`asr_segments`、`asr_alternatives`、`confidence_config`、`asr_model`。
7. 根据阈值生成绿/黄/红 `confidence_level`，为医生交互模拟提供输入。
