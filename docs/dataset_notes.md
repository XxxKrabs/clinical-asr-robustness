# 公开/候选数据集字段记录

更新时间：2026-06-30

本文档记录候选数据集的可见字段、可映射到本项目数据切片方案的方式，以及对后续子任务选数的影响。不要在这里粘贴真实患者隐私、受限数据正文或本地下载路径。

## 总体结论

5 个候选 benchmark 的原始结构差异很大，因此近期不建议先做覆盖所有数据集和子任务的大一统 schema。更合适的方式是：每个子任务单独选择数据集切片，并为该子任务维护最小字段约定。`clean_transcript / noisy_transcript / repaired_transcript` 可以作为实验对照概念保留，但不必强行要求所有数据都整理成同一张表。

如果未来确实需要统一 JSONL，中长期可以预留：

- `source` / `source_record`：保存原始数据集名称、许可、URL、split、原始字段名、文件 ID；
- `audio_files`：支持一个样本对应多个音频文件，尤其是 doctor/patient 分轨、MedDialog-Audio 的 speaker 片段、不同噪声强度版本；
- `speaker_turns`：支持带时间戳和说话人角色的 utterance/turn；
- `transcript_versions` 或 `variant_metadata`：记录 clean/noisy/repaired 的来源、ASR 系统、噪声条件、repair 方法；
- `reference_outputs`：保存数据集自带的 clinical note、summary、topic、highlight、plan 等参考输出；
- `error_annotations`：保存术语、药名/剂量、否定词、说话人、重叠/中断、代码混合等错误标签，最好支持 span 级记录；
- `downstream_outputs`：保存症状抽取、病例摘要、诊疗计划整理等模型/规则输出与评价结果。

如果未来恢复统一 schema，再考虑“两层 schema”：

1. **通用样本层**：稳定字段，跨数据集一致，供评估脚本直接读取。
2. **数据源保真层**：`source_record` / `raw_fields` 保存原始字段，避免过早丢失数据集特有信息。

## 数据集字段调研

### 1. DISPLACE-M 2026

来源：

- 论文：<https://arxiv.org/abs/2603.02813>
- 公开信息：挑战论文和 leaderboard 信息；真实数据包需要挑战注册/条款确认。

已知特征：

- 医疗场景：基层/前线健康工作者（NPHW）与 healthcare seeker（HS）的真实目标导向医疗对话；
- 语言：以 Hindi 为主，含 Indian English 代码混合和 Haryanvi、Bhojpuri、Magahi 等方言；
- 声学：真实场景、自然环境声、嘈杂、重叠说话；
- 时长：公开论文描述约 55 小时标注数据；开发/评估集按任务拆分；
- 任务：speaker diarization、ASR、topic identification、dialogue summarization。

字段/标注形态（公开论文可确认到任务级，具体数据包字段需注册后核对）：

| 类型 | 可能字段/格式 | 对本项目的意义 |
|---|---|---|
| audio | 录音文件、时长、会话 ID | `audio_files` |
| diarization reference | 类 RTTM 的 `start_time/end_time/speaker_id` | `speaker_turns` 与 speaker repair 评估 |
| ASR reference | time-marked word-level transcription，speaker-aware | `clean_transcript`、`speaker_turns`、WER/CER/tcpWER |
| topic reference | 医疗主题/关键词 | `reference_outputs.topics` |
| summary reference | 医疗对话摘要 | `reference_outputs.summary` |
| metadata | 地区、角色、语言/方言、split 等，待数据包确认 | `source_record.raw_fields` |

T001 判断：

- 不应把 DISPLACE-M 字段设为必填，因为目前无法直接看到数据包 schema；
- 必须预留 diarization/word-level ASR/summary/topic 的位置；
- 若后续接入，应先写 `importers/displace_m.py`，把挑战格式转换到统一 schema。

### 2. AfriSpeech-Dialog

来源：

- HuggingFace：<https://huggingface.co/datasets/intronhealth/afrispeech-dialog>
- 论文/数据卡：AfriSpeech-Dialog v1

数据卡可见字段：

| 原始字段 | 类型 | 说明 | 建议映射 |
|---|---|---|---|
| `audio` / `file_name` | Audio / path | `.wav` 对话音频 | `audio_files[].path` |
| `transcript` | string | 全对话转写，含时间戳与 `[Speaker 1]` / `[Speaker 2]` 标签 | `clean_transcript`；解析后进 `speaker_turns` |
| `domain` | string | `medical` 或 `general` | `domain` / `source_record.raw_fields.domain` |
| `duration` | float | 音频秒数 | `audio_files[].duration_s` |
| `age_group` | string | 年龄组 | `source_record.raw_fields.age_group` |
| `accent` | string | 口音，例如 Yoruba、Isoko 等 | `source_record.raw_fields.accent` |
| `country` | string | 国家，例如 NG、ZA | `source_record.raw_fields.country` |

T001 判断：

- 该数据集非常适合验证 `audio_files + speaker_turns + accent/country/domain metadata`；
- 自带 transcript 应视为 clean/reference，不是 noisy；
- noisy 应通过音频跑 ASR 得到，或额外做文本扰动；
- 医疗对话只是一部分，导入脚本应允许 `domain == "medical"` 过滤。

### 3. ACI-Bench

来源：

- GitHub：<https://github.com/wyim/aci-bench>
- 数据集入口：<https://figshare.com/articles/dataset/aci-bench-corpus_zip/22494601>
- 论文：<https://www.nature.com/articles/s41597-023-02487-3>

公开 JSON 字段：

| 原始字段 | 类型 | 说明 | 建议映射 |
|---|---|---|---|
| `src` | string | doctor-patient conversation，含 `[doctor]` / `[patient]` 标签 | `clean_transcript` 或 `noisy_transcript`，取决于是否用于说话人错误实验 |
| `tgt` | string | 结构化 clinical note / visit note | `reference_outputs.clinical_note` 或 `reference_outputs.case_summary` |
| `file` | string | 样本 ID，如 `D2N001-virtassist` | `sample_id` / `source_record.record_id` |

数据卡/README 重要说明：

- 训练/验证/测试拆分包含完整医患对话和 clinical note；
- 部分子集保留 ASR 过程造成的 doctor/patient speaker tag swap；
- 这种 speaker tag swap 适合直接作为 `speaker_confusion` 错误研究对象。

T001 判断：

- ACI-Bench 是第一阶段文本闭环的最佳候选之一，因为字段简单、无需音频也能跑通；
- 但 `src` 是否视为 clean 要谨慎：如果研究说话人混淆，应把原始 `src` 保留为 source transcript，并将含 tag swap 的版本记录为 `noisy_transcript` 或在 `error_annotations` 标注 `speaker_confusion`；
- `tgt` 可作为摘要/病历 note 的参考输出，但第一阶段若只做症状抽取，可先不依赖它。

### 4. PriMock57

来源：

- GitHub：<https://github.com/babylonhealth/primock57>
- 论文：<https://arxiv.org/abs/2204.00333>

公开结构：

| 文件/字段 | 类型 | 说明 | 建议映射 |
|---|---|---|---|
| `audio/` | audio | 57 场 mock primary care consultations 的音频 | `audio_files` |
| `transcripts/*.TextGrid` | Praat TextGrid | utterance-level 人工转录 | `speaker_turns` 与 `clean_transcript` |
| `xmin` | float | utterance 起始时间 | `speaker_turns[].start_time` |
| `xmax` | float | utterance 结束时间 | `speaker_turns[].end_time` |
| `text` | string | utterance 文本 | `speaker_turns[].text` |
| TextGrid tier/file role | string | Doctor / Patient | `speaker_turns[].speaker_role` |
| `<UNSURE>` | tag | 转录员不确定 | `speaker_turns[].quality_tags` |
| `<UNIN/>` | tag | 不可理解片段 | `speaker_turns[].quality_tags`，也可映射为 `overlap_or_interruption` 候选 |
| `notes/*.json.day` | int | 咨询日期 | `source_record.raw_fields.day` |
| `notes/*.json.consultation` | int | 咨询编号 | `source_record.record_id` |
| `notes/*.json.presenting_complaint` | string | 主诉 | `reference_outputs.presenting_complaint` |
| `notes/*.json.note` | string | 医生写的 consultation note | `reference_outputs.clinical_note` |
| `notes/*.json.highlights` | list[string] | 医生高亮信息 | `reference_outputs.highlights` |

T001 判断：

- PriMock57 很适合验证“音频 → ASR → noisy”和“人工 TextGrid → clean”的链路；
- TextGrid 是 utterance-level，T001 必须支持 `speaker_turns`，不能只存拼接后的全文；
- `<UNSURE>` / `<UNIN/>` 不应直接丢掉，建议保存在 quality tags 中，后续可用于分析不可懂片段对下游任务的影响；
- 人工转录是 clean/reference，不应直接当 noisy。

### 5. Fareez OSCE 呼吸病例数据集

来源：

- 论文：<https://www.nature.com/articles/s41597-022-01423-1>
- 数据：Figshare，论文中说明为 272 个 mp3 音频和 272 个对应 transcript 文本文件。

公开论文可确认字段/文件形态：

| 原始字段/文件 | 类型 | 说明 | 建议映射 |
|---|---|---|---|
| `*.mp3` | audio | OSCE 模拟医患访谈音频 | `audio_files[].path` |
| `*.txt` | text | 对应人工校正 transcript | `clean_transcript` |
| filename prefix | string | `RES`、`MSK`、`CAR`、`GAS`、`DER` 分别代表呼吸、肌骨、心血管、胃肠、皮肤病例 | `source_record.raw_fields.case_category` |
| filename digits | string | 病例编号 | `sample_id` / `source_record.record_id` |
| speaker marker | string | 论文描述 transcript 用 `D` / `P` 区分 doctor/patient | `speaker_turns[].speaker_role` |

T001 判断：

- Fareez OSCE 与 PriMock57 类似，人工转录只能做 clean/reference，noisy 需自行 ASR；
- 它更适合症状抽取，因为 OSCE history-taking 会覆盖症状、发病时间、部位、严重程度、相关症状、既往史、用药史等；
- 论文未显示结构化 clinical note 字段，因此 T001 不应假设一定有 `reference_outputs.clinical_note`。

### 6. MedDialog-Audio / MedDialogue-Audio

来源：

- HuggingFace 主数据集：<https://huggingface.co/datasets/aline-gassenn/MedDialog-Audio>
- 可加载变体：<https://huggingface.co/datasets/aline-gassenn/MedDialog-Audio_v2>
- 另一个镜像/派生：<https://huggingface.co/datasets/Chandanmanvi/MedDialog-Audio>

命名注意：

- 项目文档中写作 `MedDialogue-Audio`；
- HuggingFace 可检索到的主要名称是 `MedDialog-Audio`，README 标题也写作 `MedDialogue-Audio`；
- 后续配置建议使用稳定 key：`meddialog_audio`，并在 `source.name` 里保留原始仓库 ID。

主数据集 README 与 metadata 可见字段：

| 原始字段/文件 | 类型 | 说明 | 建议映射 |
|---|---|---|---|
| `metadata.csv.filename` | string | 音频文件名 | `audio_files[].file_name` |
| `duration_s` | float | 音频秒数 | `audio_files[].duration_s` |
| `mean_rms_energy` | float | 平均 RMS 能量 | `audio_files[].audio_features.mean_rms_energy` |
| `mean_f0_hz` | float | 平均基频 | `audio_files[].audio_features.mean_f0_hz` |
| `mean_spectral_centroid_hz` | float | 平均频谱质心 | `audio_files[].audio_features.mean_spectral_centroid_hz` |
| `hnr_db` | float | 谐噪比 | `audio_files[].audio_features.hnr_db` |
| `transcription` | string | 音频对应文本 | `clean_transcript` 或片段级 `speaker_turns[].text` |
| directory | string | `noise-free_audio`、`white_noise/noise_2%/6%/10%`、`background_noise/noise_20%/40%/60%` | `audio_files[].noise_condition` |
| filename pattern | string | `[DIALOGUE_ID]_[SPEAKER][AUDIO_TYPE][NOISE_LEVEL].wav` | `source_record.record_id`、`speaker_role`、`noise_condition` |

文件名含义：

- `SPEAKER=1`：patient；
- `SPEAKER=2`：doctor；
- `AUDIO_TYPE=o/w/b`：original / white noise / background noise；
- `NOISE_LEVEL=00/02/06/10/20/40/60`：噪声强度。

T001 判断：

- 该数据集天然适合做信噪比/医院背景噪声鲁棒性实验；
- 但它按 speaker 片段/音频文件组织，不一定是完整对话级 transcript，因此 schema 必须能把多个 `audio_files` 聚合到同一个 `dialogue_id`；
- `MedDialog-Audio_v2` 的 dataset-server 当前只暴露 `audio` 字段，不适合作为字段完整性首选；优先用带 `metadata.csv` 的主数据集/镜像。

## 近期落地方式：子任务-数据集切片矩阵

用户已确认近期不做 T001 式全局统一 schema。更轻的做法是先为每个子任务明确：

| 子任务 | 首选数据集/子集 | 使用字段 | clean 来源 | noisy 来源 | repaired 来源 | 主要指标 |
|---|---|---|---|---|---|---|
| 症状/医学实体抽取 | 待定，可优先 Fareez OSCE、PriMock57、AfriSpeech-Dialog medical 子集 | transcript / speaker turns / note highlights | 人工转录或数据集文本 | ASR 输出或规则扰动 | repair baseline | 实体 F1、否定一致性 |
| 病例摘要 | ACI-Bench、PriMock57 notes、DISPLACE-M summary subset | conversation + clinical note/summary | 原始对话文本 | speaker tag swap、ASR 输出或扰动文本 | repair 后文本 | ROUGE/LLM judge/临床相关错误数 |
| 诊疗计划整理 | ACI-Bench、PriMock57 notes | assessment/plan 相关文本 | 原始对话与 note | speaker 混淆或 ASR 输出 | repair 后文本 | plan item F1、说话人归属准确率 |
| ASR 噪声分析 | PriMock57、Fareez OSCE、AfriSpeech-Dialog、MedDialog-Audio | audio + transcript | 人工转录 | 本地/云端 ASR | ASR 改进或文本 repair | WER/CER、术语错误率 |
| 说话人修复 | ACI-Bench、AfriSpeech-Dialog、DISPLACE-M | speaker labels / diarization | 正确或参考 speaker turns | tag swap / diarization-aware ASR | speaker repair 输出 | speaker attribution accuracy |

这张矩阵应作为 T013 的产出。每个子任务只需要定义该任务所需的最小字段，不再要求所有数据集先进入同一个 JSONL schema。

## 数据使用记录模板

每接入一个数据集，建议补充：

```text
数据集名称：
访问日期：
下载位置：
许可/条款：
是否包含音频：
是否包含人工转录：
是否包含 ASR 转写：
是否包含说话人标签：
可用于 clean/noisy/repaired 的字段：
主要风险：
处理脚本：
```
