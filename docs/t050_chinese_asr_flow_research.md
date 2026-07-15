# T050 中文真实音频全流程技术路线调研

更新时间：2026-07-14

## 1. 本轮决策

2026-07-14 实施状态补充：中文/中英混说 artifact 已整理到
`data/external/asr_models/nemo/Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo`。
由于本地文件名含 `Hybrid`，与前述 CTC artifact 命名不完全一致，下一步不再重复下载，
而是先记录 digest/来源/许可并 restore-only，依据实际模型类、tokenizer 和 decoding config
决定 CTC posterior、时间戳与 n-best 的导出实现。恢复前不得把文件名当成模型能力证明。

当前首要目标是让精选 40 例真实中文音频完整经过：

> MP3 → 中文 ASR → 时间戳 + 风险信号 + 候选 → 医学实体优先高亮 →
> 局部音频回听 → 选择/编辑/拒绝 → feedback log → confirmed transcript →
> 中文病例信息整理

本轮只验收工程闭环，不验收 ASR 或下游质量。因此以下内容不再作为 P0 前置条件：

- 人工 clean/reference；
- 人工 speaker role 真值；
- 下游 gold facts；
- CER/WER、校准误差、top-k 覆盖率和摘要 F1。

这些内容统一移到后续评估阶段。流程跑通时仍必须如实区分“自动转录”“自动角色”
“未校准风险信号”“研究输出”，但不需要先制作人工真值。

2026-07-14 补充决策：在确认 NVIDIA 已发布 Mandarin-English 统一版
Parakeet-CTC-XL-0.6B 后，P0 首选路线由 Google Chirp 2 调整为
**直接使用 Parakeet CTC 0.6B Mandarin-English 的可训练声学模型 artifact，经 NeMo
导出原始 CTC 帧分布、时间戳和候选**。Google Chirp 2 保留为云端回退和质量对照，
不再作为默认首选。这样中文、英文和中英混说可以共享 FastConformer-CTC 0.6B
适配层；如使用不同 checkpoint，研究记录中应称为“同一架构/模型家族、不同
checkpoint”，不能写成同一个已训练模型。

## 2. 核心判断：中文是当前迁移主问题，但不是中文模型缺失

真正阻塞 P0 的不是市场上没有中文 ASR，而是现有系统把英文实现假设写进了数据结构和
交互逻辑：

1. 当前本地 NeMo 模型是英文 `stt_en_fastconformer_ctc_large`；
2. 长音频分窗用 Python `wave`，不能直接读取这批 MP3；
3. schema、候选、审阅、反馈回放多处以 `transcript.split()` 为锚点；
4. 页面用空格拼接 token，会把中文 confirmed transcript 插入错误空格；
5. 当前医学实体兜底规则、doctor/patient 双通道和病例聚合仍带有 PriMock57 假设。

所以“适配中文”的正确含义是同时替换 ASR 后端和文本定位协议。只换一个中文模型、但继续
用空格 token 索引，仍然无法稳定高亮、回听、绑定候选或回放修改。

## 3. 官方能力调研与路线选择

### 3.1 首选：NVIDIA Parakeet CTC 0.6B Mandarin-English

官方 Mandarin-English collection 和声学模型卡确认：

- 声学模型为 Parakeet-CTC-XL / FastConformer-CTC，约 600M 参数，8 倍下采样；
- 训练数据超过 17,000 小时，覆盖 `zh-CN` 与 `en-US`，明确支持中英 code-switch；
- 模型版本为 `Parakeet-CTC-XL-unified-0.6b_spe7k_zh-CN_3.0`，CTC 每个时间步
  输出词表 token 的 log probability；
- collection 另含中英 code-switch 4-gram LM、中文 WFST ITN、Silero VAD 和
  Mandarin/English Sortformer；Sortformer 官方说明可给出 speaker label、支持流式和
  最多 4 人同时说话；
- 可训练声学模型 artifact 为
  `nvidia/riva/parakeet-ctc-riva-0-6b-unified-zh-cn:trainable_v3.0`，模型页要求
  Riva 2.19.0+，压缩体积约 2.18 GB，并要求 Linux/NVIDIA GPU；下载页需要 NGC
  登录及相应许可确认。

这条路线与当前项目已有 NeMo CTC 能力高度匹配：项目已经能够恢复
`EncDecCTCModelBPE`、保存 Hypothesis 中的帧级 log-probs、计算 entropy/max-prob
confidence、生成 beam n-best，并把反馈回放为 confirmed transcript。因此研究主路径应
优先下载 **trainable NeMo artifact 并直接恢复**，而不是先部署完整 Riva/NIM。完整
Riva/NIM 更适合后续流式演示和一体化 VAD/LM/ITN/diarization，但 Riva gRPC 标准接口
主要返回 transcript、sequence/word confidence、word timestamp、n-best 和 speaker tag，
不直接暴露完整 `[T,V]` CTC 分布；其 confidence 官方也说明不保证准确或始终存在，且
数值计算会随配置变化。

必须处理的迁移问题：

1. **当前英文模型并不是 Parakeet 0.6B**：项目现用
   `stt_en_fastconformer_ctc_large` 只有约 115M 参数；若要真正统一模型家族，英文侧应
   改为 `nvidia/parakeet-ctc-0.6b`，或更严格地让中英文都使用双语 unified checkpoint。
2. **同架构不等于同 checkpoint**：英文 Parakeet 0.6B 使用 1,024 词表，中文 unified
   版本名中的 `spe7k` 表示约 7,000 SentencePiece 词表。恢复时必须加载完整模型配置、
   tokenizer 和 decoder，不能只把中文 state dict 塞入英文模型；阈值、校准和 LM
   配置也不能跨 checkpoint 复用。
3. **本机显存是主要工程风险**：当前 RTX 4060 Laptop 只有 8 GB；官方 Riva collection
   推荐 H100/A100/L40。直接 NeMo、`batch_size=1`、FP16/BF16、VAD 后 15–30 秒短段可能
   可行，但现有 120 秒窗口不能先验认为仍可用。完整 Riva + Sortformer 同卡常驻大概率
   不适合作为第一步。
4. **MP3 仍需预处理**：声学模型卡输入为单声道 WAV，Riva proto 也不含 MP3 编码；40
   例 48 kHz MP3 应确定性解码为 PCM/FLAC，并保留原音频绝对时间偏移。不要把换模型
   误认为已经解决长音频和 MP3 迁移。
5. **中文 unit 不能再由空格恢复**：现有 `transcript.split()` 会把整段中文变成一个词。
   应直接保存 SentencePiece/CTC emitted token、合并后的汉字/英文 span、
   `char_start/char_end` 与绝对时间；中英混说的空格由 tokenizer/显示层决定。
6. **原始 CTC top-k 不是医生可点的候选**：逐帧 top-k 包含 blank、重复 token 和不完整
   子词。可点击候选应由 CTC prefix/beam + 4-gram LM 生成 sequence n-best，再与 top-1
   按字符区间对齐到局部 span；Riva `max_alternatives` 也只保证 sequence-level n-best，
   且服务端可以少返回。
7. **置信度不能直接跨语言/词表比较**：帧 log-prob 可用于 entropy、margin 或 max-prob，
   但不是校准后的正确率。中文、英文和 code-switch 片段的 token 粒度不同；P0 仍使用
   `demo_quantile_v0`，后续按 checkpoint + 语言/数据域分别校准。
8. **LM/ITN 会改变文本和偏移**：LM、标点和 ITN 可能把声学 token 改写为不同长度的
   书写形式，尤其是剂量、频率、电压和日期。应同时保存 `am_raw`、`decoded_with_lm`、
   `display_itn` 三层及其对齐/变换日志；不能把 raw token confidence 无映射地贴到 ITN
   后文本。
9. **Sortformer 只有 speaker，不给角色**：它可以提供“谁在何时说话”的标签，但不会
   判断 doctor/patient/family/staff。40 例又存在 2–6 名参与者，而 collection 只明确到
   最多 4 人同时说话；仍需和现有 source-aware 自动角色按时间重叠映射，并允许
   `unknown`。
10. **官方卡未给出可直接引用的 CER/WER 数值**：模型卡只描述了训练/评估数据构成，
    没有公开本项目场景可用的中文临床指标。中英混说与通用能力成立，不代表 DBS 术语、
    数字和药名质量已经满足要求；必须用 pilot 实测。

推荐的“统一模型”定义：

- 最强控制：中文、英文、中英混说全部使用 Mandarin-English unified checkpoint；
- 工程折中：英文使用 `nvidia/parakeet-ctc-0.6b`，中文/混说使用 unified zh-CN
  checkpoint，共享 `ParakeetCTCAdapter`，但把 `checkpoint_id` 作为实验变量；
- 现有 `stt_en_fastconformer_ctc_large` 只保留为历史 baseline。若与新中文结果做联合
  结论，必须先用新 Parakeet 路线重跑英文样本，不能静默拼接旧产物。

官方资料：

- [Mandarin-English Parakeet 0.6B collection](https://catalog.ngc.nvidia.com/orgs/nvidia/collections/parakeet-ctc-0.6b-zh-cn)
- [Parakeet-CTC-XL-0.6B Unified 声学模型](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/riva/models/parakeet-ctc-riva-0-6b-unified-zh-cn)
- [英文 Parakeet CTC 0.6B NeMo checkpoint](https://huggingface.co/nvidia/parakeet-ctc-0.6b)
- [当前 115M 英文 FastConformer checkpoint](https://huggingface.co/nvidia/stt_en_fastconformer_ctc_large)
- [Riva ASR protobuf：n-best、word time/confidence、speaker](https://github.com/nvidia-riva/common/blob/main/riva/proto/riva_asr.proto)
- [Riva 音频编码 protobuf](https://github.com/nvidia-riva/common/blob/main/riva/proto/riva_audio.proto)
- [NVIDIA Riva / NeMo 微调与转换教程](https://github.com/nvidia-riva/tutorials/blob/main/asr-finetune-parakeet-nemo.ipynb)

### 3.2 云端回退：Google Cloud Speech-to-Text V2 / Chirp 2

建议参数：

```text
location = asia-southeast1
model = chirp_2
language_code = cmn-Hans-CN
method = BatchRecognize
decoding = AutoDetectDecodingConfig
enable_word_time_offsets = true
enable_word_confidence = true
enable_automatic_punctuation = true
```

选择原因：

- 官方语言表明确列出 `cmn-Hans-CN + chirp_2` 支持自动标点、模型自适应和字词级
  置信度；
- `BatchRecognize` 支持超过 60 秒的长音频，单文件上限 480 分钟，本数据最长约 63 分钟；
- V2 自动解码明确支持 MP3，可直接上传现有 48 kHz 单声道 MP3，不必先改写本地 WAV
  分窗器；
- 返回字词时间偏移，最贴合现有逐词高亮和局部回听页面；
- 可以用 PhraseSet/模型自适应加入 DBS、程控、药名、参数和单位词表。

必须保留的限制：

- Google 将字词级置信度标为 Preview；Chirp 2 模型文档还明确说明“会返回一个值，但它
  不是真正的置信度分数”。因此 P0 字段应命名和记录为
  `provider_confidence_signal` / `uncalibrated_provider_score`，不能写成已经校准的错误概率；
- `confidence` 可能缺失，代码必须允许 `null`；缺失时显示为“未知/待核”，不能补 0 或 1；
- 请求多个 alternatives 不保证一定返回多个候选。候选列表必须允许为空；
- Chirp 2 的中文能力表没有讲话人区分，而 Chirp 3 有讲话人区分、却没有字词级置信度。
  P0 不建议为此多跑一遍 Chirp 3，先按时间重叠把现有 source-aware 推荐转录的自动角色
  映射到 Chirp 2 单元即可。

按数据总时长约 710.4 分钟粗算，如果 Chirp 2 按官方当前列出的标准/动态批处理档计费，
0.016 美元/分钟对应单次全量约 11.37 美元，0.003 美元/分钟对应约 2.13 美元；动态批处理
的代价是最长 24 小时延迟。不含 Cloud Storage 等少量附加费用，实际运行前仍应在目标
region 的账单页面确认 SKU。工程上应先跑 1 例，再跑 5 例，最后跑 40 例。

官方资料：

- [V2 支持语言与功能](https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages?hl=zh-cn)
- [Chirp 2 能力与限制](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2)
- [长音频 BatchRecognize](https://cloud.google.com/speech-to-text/docs/batch-recognize)
- [V2 自动解码支持的音频格式](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v2/projects.locations.recognizers)
- [字词级置信度说明](https://docs.cloud.google.com/speech-to-text/v2/docs/word-confidence)
- [候选与置信度返回注意事项](https://docs.cloud.google.com/speech-to-text/docs/overview)
- [价格](https://cloud.google.com/speech-to-text/pricing)

### 3.3 备选：Azure Speech Batch Transcription

Azure 适合在 Google Cloud 账号、区域或调用条件不便时快速替代。官方批量结果可以返回：

- phrase offset/duration；
- phrase-level `confidence`；
- phrase-level `nBest`；
- word/display-word 时间戳；
- 启用 diarization 后的 `speaker`。

它的一次调用更接近“时间戳 + 候选 + 说话人”全套结果，但官方示例没有逐词 confidence；
不能把 phrase confidence 伪装成每个中文字独立置信度。若采用 Azure，P0 应按 phrase/segment
整体着色，或者把同一个 phrase score 传播给内部字词并显式记录
`confidence_scope=phrase_propagated`。

官方资料：

- [批量转录结果结构](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-transcription-get)
- [创建批量转录与说话人区分](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-transcription-create)
- [语言支持](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support)

### 3.4 另一条本地路线：FunASR Paraformer-zh

FunASR 官方给出的中文生产组合是 `paraformer-zh + fsmn-vad + ct-punc + cam++`，支持中文、
VAD、标点、热词、说话人和字符级时间戳，适合作为后续本地可控路线。

但它不是当前最快的 P0 路线。官方 Paraformer 标准输出只有 `text` 和 `timestamp`；源码虽有
decoder `am_scores`、beam search、`nbest` 和 hypothesis score，标准结果没有把逐 token
posterior/entropy 或 hypothesis score 导出。若把它作为研究主后端，需要新增适配层：

1. 对 decoder logits 做 softmax，导出 top-1 posterior、entropy 或 margin；
2. 打开 CTC/LM beam search，导出 n-best 文本及归一化 hypothesis score；
3. 将字符级 CIF 时间戳与 token 分数严格对齐；
4. 保存模型、词表、VAD、标点、说话人和热词版本。

官方资料：

- [FunASR 项目与中文生产示例](https://github.com/modelscope/FunASR)
- [Paraformer 推理源码](https://github.com/modelscope/FunASR/blob/main/funasr/models/paraformer/model.py)

### 3.5 暂不选作 P0 主线

- 当前 115M 英文 NeMo checkpoint：保留历史 baseline，不作为新的统一模型主线；
- 完整 Riva/NIM：待直接 NeMo artifact smoke test 成功后再评估；首轮不同时常驻
  Parakeet、LM、ITN、VAD 和 Sortformer；
- Whisper：多语转写可用，但官方主实现没有直接提供本项目需要的逐词置信度和稳定 n-best
  接口；
- 包内 8 路开源纯文本：没有原生时间戳/分数，不能反推成真正的 ASR confidence。它们只
  适合标记为 `multi_model_alternative` 的辅助候选。

## 4. 中文数据协议：P0 必须改的部分

### 4.1 不再以空格分词为真值

每个 ASR 返回单元至少保存：

```json
{
  "unit_id": "...",
  "text": "程控",
  "char_start": 12,
  "char_end": 14,
  "start_sec": 31.20,
  "end_sec": 31.66,
  "confidence_signal": 0.73,
  "confidence_source": "parakeet_ctc_frame_entropy_v0",
  "confidence_scope": "ctc_subword_span",
  "speaker_label": "spk_2",
  "speaker_role": "doctor"
}
```

规则：

- `char_start/char_end` 是 confirmed transcript 回放的主锚点；
- CTC/tokenizer 返回的字/词/子词单元是显示和回听锚点，不再调用 `.split()` 重建；
- 中文 `display_joiner=""`，英文/空格语言才使用 `" "`；
- 标点可以先附着到前一个单元，或作为 `confidence=null` 的 neutral 单元；
- 修改回放按字符区间从右向左替换，避免前一次替换改变后续偏移；
- word index 仅作为页面稳定 ID/向后兼容字段，不能再承担文本重建职责。

### 4.2 风险颜色先用工程阈值，不声称校准

没有 reference 时无法验证固定阈值与错误率的关系。为了让页面一定出现有意义的绿/黄/红
分布，P0 使用全批或单例分位数：

- 最低 10%：红；
- 接下来 20%：黄；
- 其余：绿；
- `confidence=null`：未知；医学实体上的未知按待核处理。

策略名记录为 `demo_quantile_v0`，并明确 `calibrated=false`。这只是控制医生审阅预算的
工程操作点，不是模型可靠性结论。以后有人工 reference 后再替换成校准阈值。

### 4.3 候选分层

候选优先级和来源必须分开：

1. `asr_native_alternative`：同一 ASR 返回的 phrase/n-best；
2. `multi_model_alternative`：包内其他 ASR 经过时间/文本对齐后的候选；
3. `llm_word_candidate`：中文 LLM 基于局部上下文产生的辅助候选。

Parakeet 主线优先由 acoustic-only CTC beam 和官方 4-gram LM beam 生成第 1 层，再将
sequence n-best 按字符区间对齐成局部候选；逐帧 top-k 只保存为声学证据，不直接显示为
完整词。若 beam 对某个 span 没有差异候选，P0 仍允许第 1 层为空，并用已获审的外部 LLM
补第 3 层。页面继续显示来源，不把任何候选当作答案。

### 4.4 多参与者先复用现有自动角色

P0 将整例记录设为 `source_channel=mixed`，再把现有 source-aware 片段按最大时间重叠映射到
ASR unit/segment，保留：

- `acoustic_speaker_label`；
- `speaker_role`：doctor/patient/family_or_caregiver/staff/unknown/unrelated；
- `speaker_role_source=existing_source_aware_auto_v2`。

不要求人工确认角色。映射失败保留 `unknown`，不能根据上下文强行补齐。

## 5. 最小实现顺序

### P0-A：1 例工程 smoke test

1. 建 40 例 manifest，只保存匿名 ID、受保护本地路径和音频时长；
2. 核验已下载的本地 artifact，记录来源、NVIDIA Community Model License、digest、模型
   版本和实际恢复配置；仅在文件损坏或并非目标 artifact 时重新下载 `trainable_v3.0`；
3. 在 WSL `clinical-asr` / NeMo 3.1.0 中先做 `ASRModel.restore_from()`，检查实际模型类、
   tokenizer、`blank_id`、词表大小、采样率和 decoding config；若旧 artifact 无法恢复，
   单独建立 NVIDIA 推荐版本环境，不覆盖当前可复现环境；
4. 将 1 例 MP3 确定性解码为保留绝对 offset 的 16 kHz mono PCM/WAV，先选 15–30 秒
   片段，以 RTX 4060 8 GB、`batch_size=1`、FP16/BF16 运行；
5. 保存 `am_raw` transcript、CTC emitted token、token timestamp、frame entropy/margin、
   稀疏 frame top-k 和 sequence n-best；验证中文、英文和中英混说均能往返；
6. 再接 Silero VAD 处理整例，使用短段 + overlap，并把段内时间恢复为原 MP3 绝对时间。

首轮不部署完整 Riva/NIM，不同时加载 Sortformer。若直接 NeMo checkpoint 无法在 8 GB 显存
稳定运行，再把 Google Chirp 2 作为 P0 回退，或使用更大显存的 NVIDIA GPU。

### P0-B：中文审阅协议

1. 扩展 `ASRConfidenceRecord`，允许 CTC/subword units + char offsets + nullable confidence；
2. 移除中文路径上的 `.split()`/`join(" ")`；
3. 以 `display_joiner` 渲染上下文和 transcript；
4. 以 char range 回放选择、编辑、拒绝和无法判断；
5. 用时间重叠映射现有自动 speaker/role；
6. 加 `demo_quantile_v0` 风险分级，并记录 `checkpoint_id`、`confidence_source`、
   `calibration_id` 和 `calibrated=false`；
7. 同时保存 `am_raw`、`decoded_with_lm`、`display_itn`，任何 LM/ITN 改写都保留可审计
   alignment/transform log。

### P0-C：候选、实体和页面

1. 运行 acoustic-only beam 和 4-gram LM beam，把 sequence n-best 字符对齐为 span 候选；
   没有局部差异时允许空列表；
2. 使用中文外部 LLM 提取医学实体并生成辅助候选；
3. 加 DBS 热词/词表：脑深部电刺激、程控、电极、触点、幅度、电压、电流、脉宽、频率、
   左/右侧、开关状态、震颤、僵硬、异动、步态、药名和剂量单位；
4. 复用现有 HTML5 MP3 局部回听、单选确认、反馈日志和 confirmed transcript 导出；
5. confirmed transcript 送入现有中文病例信息整理 LLM，产物标注为研究输出。

### P0-D：扩量

按 1 → 5 → 40 例扩量。每一级只检查：

- 任务成功/失败与重试；
- 峰值显存、实时因子、VAD/窗口长度和 overlap；
- 所有文本能无空格损坏地往返；
- 时间戳可 seek；
- 页面有绿/黄/红/未知、候选和编辑操作；
- feedback 能确定性生成 confirmed transcript；
- 下游病例信息整理能接收 confirmed transcript 并输出结构化结果。

不在 P0 计算正确率或质量提升。

## 6. P0 完成定义

满足以下条件即可宣布“40 例迁移流程跑通”：

- 40/40 MP3 有 Parakeet Mandarin-English ASR 标准化记录，或明确标注的 Google 回退记录；
- 每例有可定位的 ASR unit/segment，且中文没有被错误插入空格；
- 置信度缺失和 alternatives 缺失不会使流程崩溃；
- 风险颜色明确标注为未校准工程信号；
- 医学实体风险片段能打开候选、播放局部音频并记录单选反馈；
- feedback 可重复回放为相同 confirmed transcript；
- confirmed transcript 能进入中文病例信息整理环节；
- provider/runtime、artifact/checkpoint、model、language、decoding、LM/ITN/VAD/diarization
  版本、运行时间、显存和失败重试可追溯。

## 7. 后续评估阶段再做

完成 P0 后，如果研究目标切回“证明质量提升”，再选代表性子集制作人工 reference、人工角色
和下游 gold，评估 CER、实体/数字错误、置信度校准、top-k 覆盖率、医生审阅成本以及
noisy/confirmed 下游差异。届时 Parakeet 原始 CTC entropy/max-prob、Riva confidence 或
Google Preview signal 都不能直接当作校准后的正确率；应基于人工 reference 按 checkpoint、
语言/混说状态和数据域做温度缩放、保序校准或训练独立风险模型，并单独评估 raw AM、
LM decoded 与 ITN display 三个层级。
