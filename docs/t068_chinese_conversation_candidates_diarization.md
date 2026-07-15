# T068 中文完整对话审阅、LLM 候选与 NVIDIA 说话人分离调研

更新时间：2026-07-14

## 1. 本轮结论

三项调整应按下面的层级实现：

1. **ASR 推理单位仍可切成 30 秒窗口，但审阅单位必须是一整例对话。** 窗口只服务显存、失败重试、时间戳和反馈回放；医生、研究者或候选生成 LLM 看到的是同一 `consultation_id` 下按绝对时间排序的完整对话。
2. **中文候选以 LLM 辅助候选为当前必选分支，同时保留来源隔离。** ASR n-best、LLM 候选、词表候选必须分别标记，任何候选都不是答案，最终仍由回听确认。
3. **当前 Parakeet ASR checkpoint 不自带说话人分离输出。** NVIDIA 的 Mandarin-English Parakeet collection 另含 Sortformer diarization artifact；需要独立下载、独立推理，再按时间映射到 ASR 字词。

因此推荐主流程为：

> 整例 16 kHz mono 音频 → 独立 diarization → speaker 时间段
> 同一音频 → 分窗 Parakeet ASR → 字词/片段时间戳与置信度
> 时间重叠映射 → 病例级 speaker turns → 完整对话 LLM 候选 → 医生审阅

## 2. 为什么当前页面会出现“一例十段、某段只有一句或两个字”

当前最短整例 smoke test 的原始音频约 280.7 秒，为控制 0.6B ASR 的显存和失败恢复，被预处理为 10 个连续窗口。T030 过去把每条 ASR record 直接变成一个 review sample，于是内部推理窗口被错误提升成了页面一级样本；两个静音或弱语音窗口只输出两个 ASR 单元，也被单独显示。

正确的数据层级是：

```text
ReviewConversation（1 行 = 1 个 consultation/case）
  ├─ speaker_turns（按 speaker/time 组织，供完整阅读与 LLM 上下文）
  └─ review_samples（原 ASR 窗口，供 span 点击、音频定位和反馈回放）
```

本轮新增 `asr_review_conversation/v1`，并保留原 `asr_review_sample/v1`，避免破坏 T035 的确定性反馈回放。没有 diarization 时使用 `speaker_unknown`，界面显示“说话人待分离”，不得伪造 doctor/patient。

## 3. 中文 LLM 候选适配

### 3.1 现状与修正

旧 T044 能生成 LLM word candidate，但此前中文运行只输出 prompt JSONL，没有传 `--run-llm-candidates`；同时 prompt 是英文、只含局部窗口，并继续使用 PriMock57 英文词表。

本轮增加：

- prompt profile：`zh_dbs_remote_programming_v1`；
- context scope：`complete_consultation`；
- 中文 DBS 词表：`configs/medical_candidate_lexicon.remote_programming_40.json`；
- 数据集路由默认：`remote_programming_40` 启用 LLM candidate，仍可用 `--no-run-llm-candidates` 显式关闭；
- 完整上下文只由 noisy ASR、自动 speaker label 和时间戳构成，`reference_used=false`；
- prompt 明确模型没有听到音频、不得声称候选来自听辨、允许返回空数组。

### 3.2 候选生成约束

每个黄/红医学 ASR 单元最多返回 3 个短候选，重点关注：

- DBS/神经调控术语、靶点、电极、触点和程控状态；
- 症状、药名、否定词、左右侧；
- 电压、电流、脉宽、频率、数字和单位；
- 中英混说缩写，如 `DBS`、`STN`、`GPi`、`Vim`。

LLM 只负责扩大候选覆盖，不负责自动修复。候选 metadata 必须保留：

- `source=llm_word_candidate`；
- `prompt_profile=zh_dbs_remote_programming_v1`；
- `context_scope=complete_consultation`；
- `reference_used=false`；
- LLM model、base URL、cache hit 与调用时间等运行信息。

## 4. NVIDIA 模型是否天然支持说话人分离

### 4.1 准确答案

**整套 NVIDIA collection 支持；当前这个 Parakeet ASR `.nemo` 本身不支持。**

NVIDIA 官方 collection 将声学模型、语言模型、ITN、VAD 和 Sortformer 列为独立组件。Sortformer 负责“谁在什么时候说话”，官方说明支持流式处理和最多 4 个 speaker 输出。当前项目恢复出的 Parakeet checkpoint 类是 `EncDecHybridRNNTCTCBPEModel`，其职责仍然只有 ASR；说话人分离必须加载另一个模型对象。2026-07-15 已把独立 `diar_streaming_sortformer_4spk-v2.1.nemo` 放入 `data/external/asr_models/nemo/` 并跑通 1 例整段 RTTM→ASR word 映射；VAD/TitaNet 回退 artifact 仍未准备。当前实现和结果见 `docs/t070_sortformer_diarization_pilot.md`。

官方来源：

- [Mandarin-English Parakeet 0.6B collection](https://catalog.ngc.nvidia.com/orgs/nvidia/collections/parakeet-ctc-0.6b-zh-cn)
- [Sortformer Speaker Diarization model card](https://catalog.ngc.nvidia.com/orgs/nvidia/riva/models/sortformer_diarizer)
- [NeMo speaker diarization overview](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/intro.html)
- [NeMo diarization configuration and ASR integration](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/configs.html)
- [NeMo diarization input manifest/RTTM format](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/datasets.html)

项目内 NeMo 快照已经包含：

- `SortformerEncLabelModel`；
- `ClusteringDiarizer`；
- `OfflineDiarWithASR`；
- `speaker_utils` / `diarization_utils`。

但快照没有完整迁入官方 `examples/speaker_tasks/diarization/` 配置与 notebook，当前只有一个 multitalker streaming 示例。因此还需要补一个项目侧离线推理脚本和固定配置，不能把“类可 import”当成“流程已可用”。

### 4.2 首选路线：单独运行 Sortformer

对 2–4 人 pilot，优先用 collection 对应的 Mandarin/English Sortformer：

1. 输入整例 16 kHz mono 音频，不对 diarization 使用独立 30 秒窗口，以免每窗 `spk_0` 含义重置；
2. 顺序运行 diarization 与 Parakeet ASR，不让两个模型同时常驻 RTX 4060 Laptop 8 GB；
3. diarization 输出统一保存为 RTTM 或等价 JSONL：`start_sec/end_sec/speaker_label/overlap`；
4. 用每个 ASR word 与 speaker 区间的最大时间重叠映射 speaker；无重叠时可用 word midpoint，但必须记录映射策略；
5. 相邻且 speaker 相同的字词合并为 turn；长静音、speaker 变化或 overlap 边界切段；
6. Sortformer 只输出 `spk_0` 等声学身份，不输出 doctor/patient/family/staff 角色。

### 4.3 多于 4 人或 Sortformer 域外失败时的回退

40 例说明中存在 2–6 名参与者。若实际有效 speaker 数超过 4，或远程录音声学条件使 Sortformer 不稳定，回退到 NeMo cascaded pipeline：

> multilingual VAD → TitaNet speaker embedding → clustering → 可选 MSDD

NeMo 官方 clustering 配置允许设置更大的 `max_num_speakers`；但 `diar_msdd_telephonic` 主要在电话语音上训练，不能假定对本数据天然最优。回退路线需要与 Sortformer 在同一小样本上比较。

## 5. speaker 与临床角色必须分开

建议保留两组字段：

```json
{
  "speaker_label": "spk_1",
  "speaker_label_source": "nvidia_sortformer_v1",
  "speaker_role": "doctor",
  "speaker_role_source": "human_mapping_v1",
  "speaker_role_confidence": 1.0
}
```

规则：

- `speaker_label` 回答“是不是同一个声音”；
- `speaker_role` 回答“这个声音在病例中是什么角色”；
- 自动角色模型无法判断时保留 `unknown`；
- 不得仅依据第一句话或语义强行把 `spk_0` 固定为医生；
- overlap 可保留多 speaker label，不能静默任选一人；
- 角色修订应进入 feedback log，而不是覆盖原 diarization 结果。

## 6. 最小 pilot 与验收

先用 1 例多说话人完整音频，再扩到 5 例：

1. 单独取得并记录 Sortformer artifact 的版本、digest、许可和来源；
2. 运行整例 diarization，记录 RTF、峰值显存、speaker 数和失败信息；
3. 生成 RTTM/JSONL，并映射到已有 ASR words；
4. 导出一行一例的 `ReviewConversation`，页面显示完整对话与 speaker turn；
5. 人工抽查 speaker change、短回应、静音、重叠、远端/近端音量差；
6. 对 2–3 分钟片段制作独立人工 RTTM 后再计算 DER/JER；没有人工 RTTM 前只报告工程覆盖率，不报告说话人准确率。

工程门槛：

- 100% 有时间戳的 ASR words 得到 speaker 或显式 `speaker_unknown/overlap`；
- 同一整例内 speaker ID 不因 ASR 窗口变化而重置；
- 完整对话只生成 1 个一级审阅样本；
- speaker turn 前有标签，黄/红 span 仍可点击、回听和回放；
- 5 例运行可恢复、无静默截断，显存和 RTF 可追溯。

## 7. 当前不做的事情

- 不把 Sortformer speaker label 直接当 doctor/patient role；
- 不用包内已有“推荐转录角色”冒充 diarization gold；
- 不把当前 ASR checkpoint 文件名或 collection 描述当作本地已安装 Sortformer 的证据；
- 不在没有人工 RTTM/reference 时宣称 speaker diarization 或转写质量提升；
- 不让病例摘要或诊疗计划反向参与候选生成。
