# T070：中文整例 Streaming Sortformer 说话人分离 pilot

更新时间：2026-07-15

## 1. 目标与边界

本轮只验证中文真实对话的工程闭环：

> 整例 16 kHz mono 音频 → 独立 Streaming Sortformer → RTTM/JSONL 说话人区间
> → 按时间重叠映射 ASR 字词 → 同人短空洞桥接 → 可选 LLM 语义补全
> → 病例级 speaker turns → 交互审阅包

Sortformer 输出的是 `speaker_0` 等声学身份，不是医生、患者、家属或工作人员等语义角色。
本轮没有使用人工 RTTM/reference，也没有把包内自动角色当作 speaker gold，因此不报告 DER/JER，
不声称说话人分离准确率或临床质量得到提升。

## 2. 模型与许可

- 模型：`nvidia/diar_streaming_sortformer_4spk-v2.1`；
- 文件：`data/external/asr_models/nemo/diar_streaming_sortformer_4spk-v2.1.nemo`；
- 大小：471,367,680 bytes（449.531 MiB）；
- SHA-256：`8abd32832159c6ac1148c926b7276f35ba34582c444e559dce1f1253fea42ef8`；
- 恢复类：`nemo.collections.asr.models.SortformerEncLabelModel`；
- 许可：NVIDIA Open Model License Agreement；
- 官方模型卡：<https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1>。

模型最多输出 4 个 speaker。模型卡同时提示其训练数据仍以英语为主，非英语和域外噪声场景可能
退化；因此中文远程程控对话必须以本项目 1→5 例 pilot 和后续独立人工 RTTM 为准。

## 3. 输入构造与运行环境

从已批准内部使用的 40 例中选择工程阶段最短整例 `case_0068`。选择依据仅是降低首次接入成本，
不是质量抽样。原始音频和正文均位于 Git 忽略目录，本文不记录正文或可识别信息。

使用 `scripts/preprocess_asr_audio.py --window-sec 0` 将整例确定性转换为：

- 16,000 Hz；
- 单声道；
- PCM16 WAV；
- 280.704 秒；
- 保留相对原始 MP3 的 0 秒绝对起点。

运行环境：WSL Ubuntu 22.04、Conda `clinical-asr`、NeMo 3.1.0 项目快照、
PyTorch 2.11.0+cu126、RTX 4060 Laptop 8 GB。ASR 与 diarization 顺序运行，不同时常驻 GPU。

最终固定的 Streaming Sortformer 配置以 80 ms 帧为单位：

| 参数 | 值 |
|---|---:|
| `chunk_len` | 340 |
| `chunk_right_context` | 40 |
| `fifo_len` | 40 |
| `spkcache_update_period` | 340 |
| `spkcache_len` | 188 |
| `batch_size` | 1 |

首次尝试沿用模型卡示例的 `spkcache_update_period=300` 时，当前 NeMo 明确提示其小于
`chunk_len=340`，实际会按 340 生效。最终脚本和正式运行记录均显式写为 340，避免配置记录与
实际行为不一致。后处理使用 checkpoint/NeMo 默认值，尚未针对中文数据调参。

## 4. 新增实现

- `src/clinical_asr_robustness/speaker_diarization.py`
  - `speaker_diarization_record/v1` schema；
  - Sortformer 三列输出解析；
  - RTTM 导出；
  - ASR 字词最大时间重叠映射；
  - 同一 speaker 的 1.5 秒内短空洞桥接，并保留原始声学证据；
  - JSONL 读写与可审计映射证据。
- `scripts/run_sortformer_diarization.py`
  - 整例 GPU 推理；
  - 逐例 JSONL/RTTM 落盘；
  - `--resume` / `--overwrite`；
  - 运行时间、RTF、显存和失败记录；
  - 可选直接映射 ASR confidence JSONL。
- `scripts/map_speaker_diarization_to_asr.py`
  - 不重复跑 GPU，把已有 diarization 应用到候选增强后的 ASR JSONL；
  - 区分原始声学覆盖和短空洞桥接后的展示覆盖。
- `tests/test_speaker_diarization.py`
  - 输出解析、RTTM、重叠说话保守决策、字词映射和 JSONL 往返。
- `src/clinical_asr_robustness/speaker_semantic_resolution.py`
  - 按完整 consultation 聚合全部残余 gap；
  - 只允许从既有声学 speaker 标签中选择；
  - 严格 JSON 解析、置信度和来源审计；
  - 原始 acoustic label / mapping status 不改写。
- `scripts/resolve_speaker_gaps_with_llm.py`
  - 默认从项目 `.env` 读取 OpenAI-compatible API 配置；
  - 支持 prompt-only、响应缓存、置信度 gating 和显式 `--force-resolve-all`；
  - prompt/响应和带正文结果只写入 Git 忽略目录。

映射规则如下：

1. ASR 字词时间戳先确认是否已经是原音频绝对时间；窗口相对时间才加窗口 offset；
2. 按 speaker 聚合字词区间与 diarization 区间的重叠时长；
3. 最大重叠低于字词时长 10% 时留空；
4. 第二名重叠达到第一名的 90% 时标记 `ambiguous_overlap` 并留空，不强行指定 speaker；
5. 每个字词保存候选 speaker、重叠时长、覆盖比例、模型和映射来源；
6. 若未映射字词前后为同一 speaker、两侧间隔不超过 1.5 秒，且原状态仅为
   `no_overlap` / `insufficient_overlap`，则以 `same_speaker_short_gap_bridge/v1` 生成展示标签；
7. `ambiguous_overlap`、不同 speaker 交界、长静音和缺时间戳不桥接；原始
   `mapping_status` / acoustic `speaker_label` 不被改写；
8. ASR segment 内只有全部字词同 speaker 时才继承该 speaker，否则为 `mixed`。

## 5. 1 例工程结果

### 5.1 Sortformer 推理

固定配置复跑结果：

| 指标 | 结果 |
|---|---:|
| 成功病例 | 1/1 |
| 音频时长 | 280.704 s |
| 模型恢复 | 11.230 s |
| diarization 推理 | 2.180 s |
| RTF | 0.00777 |
| CUDA 峰值 allocated | 689.81 MiB |
| CUDA 峰值 reserved | 750.00 MiB |
| 声学区间数 | 97 |
| 输出声学 speaker | 4 |

各标签活动时长为 `speaker_0=112.24 s`、`speaker_1=27.04 s`、`speaker_2=24.88 s`、
`speaker_3=0.48 s`。不同 speaker 区间可重叠，活动时长不能直接相加为总语音时长。
`speaker_3` 极短且没有映射到候选增强 ASR 的任何字词，可能是真实短时第三方、重叠说话，
也可能是伪检出；没有人工回听/RTTM 前不作判断。

### 5.2 RTTM → ASR word 映射

候选增强后的 10 个 ASR 窗口共有 726 个可审阅单元：

| 映射状态 | 数量 |
|---|---:|
| `mapped_max_overlap` | 681 |
| `ambiguous_overlap` | 18 |
| `no_overlap` | 25 |
| `missing_timestamp` | 2 |

映射覆盖率为 681/726 = 93.80%。映射后的字词数为：`speaker_0=554`、`speaker_1=55`、
`speaker_2=72`。原始 45 个未映射字词形成 32 个连续空洞，其中 19 个空洞前后为同一
speaker；应用上述保守规则后桥接 14 个 `no_overlap` 字词，未桥接任何
`ambiguous_overlap`。因此展示层覆盖为 695/726 = 95.73%，剩余 31 个继续显示“说话人待确认”。
原始声学覆盖仍是 93.80%；这些数字都只表示工程映射/展示覆盖，不表示 speaker 标签正确率。

### 5.3 病例级审阅包

- 一级病例数：1；
- 内部 ASR 窗口：10；
- speaker turns：67（桥接前 89）；
- `diarization_status=partial`；
- `speaker_unknown` 22 turns / 31 个 ASR 单元（桥接前 33 turns / 45 单元）；
- 展示层 speaker 单元数：`speaker_0=563`、`speaker_1=59`、`speaker_2=73`；
- 声学原始 speaker 单元数仍为：`speaker_0=554`、`speaker_1=55`、`speaker_2=72`。

页面已成功生成，两个内联 JavaScript 块通过 Node 语法解析。当前会话的 Browser 列表为空，
因此没有进行真实页面点击、音频回听、刷新恢复或反馈下载验收；T060 仍保持进行中。

### 5.4 LLM 语义补全实验版

在短空洞桥接后仍有 31 个未映射字词，按完整病例顺序合并为 20 个连续 gap。本轮按用户要求
运行独立的“全部连接”实验版：使用项目 `.env` 中的 `Qwen3-Coder-Plus` /
`https://llmapi.paratera.com` 配置，把完整 speaker-labeled noisy ASR 对话和 20 个 gap 合并为
一次请求。提示词只允许从本例已有 `speaker_0/1/2` 中选择，不允许修改 ASR 文字或创建角色
标签；返回必须逐 gap 满足严格 JSON schema。

一次 API 请求成功覆盖 20/20 gaps、31/31 字词：

| 指标 | 结果 |
|---|---:|
| LLM gap 决策 | 20/20 |
| 高置信 gap（≥0.80） | 6 |
| 中置信 gap（0.50–0.80） | 14 |
| `uncertain_best_guess` | 3 |
| LLM 补全字词 | 31 |
| 最终未映射字词 | 0 |
| 最终病例级 turns | 43 |
| 审阅状态 | `semantic_complete` |

31 个语义补全字词中，22 个赋给 `speaker_0`、9 个赋给 `speaker_1`。最终来源构成为：681 个
Sortformer 直接时间映射、14 个同人短空洞桥接、31 个 LLM 语义补全。全部 LLM 字词仍保存
原始 acoustic `speaker_label=None` 以及 11 个 `no_overlap`、18 个 `ambiguous_overlap`、2 个
`missing_timestamp` 状态；界面显示“含语义补全”，运行记录明确
`semantic_labels_are_not_acoustic_ground_truth=true`。因此 43 turns 只是更连贯的实验展示，
不是声纹准确率提升，尤其 3 个 `uncertain_best_guess` 应优先人工回听。

## 6. 产物

以下产物均位于 Git 忽略目录：

- 整例 WAV manifest：
  `data/interim/remote_programming_40/manifests/remote_programming_40_t070_sortformer_pilot_manifest.jsonl`；
- diarization JSONL：
  `outputs/remote_programming_40/t070_sortformer_pilot/sortformer_diarization.jsonl`；
- RTTM：`outputs/remote_programming_40/t070_sortformer_pilot/rttm/case_0068.rttm`；
- 候选增强 + speaker ASR：
  `outputs/remote_programming_40/t070_sortformer_pilot/remote_programming_40_shortest_full_candidates_diarized_smoothed.jsonl`；
- 病例级审阅包：
  `outputs/remote_programming_40/t070_sortformer_pilot/remote_programming_40_shortest_full_review_conversation_diarized_smoothed.jsonl`；
- 交互 HTML：
  `outputs/remote_programming_40/t070_sortformer_pilot/remote_programming_40_shortest_full_doctor_review_diarized_smoothed.html`；
- LLM 语义补全 ASR / 病例级审阅包 / 交互 HTML：文件名分别带
  `_diarized_semantic.jsonl`、`_review_conversation_diarized_semantic.jsonl` 和
  `_doctor_review_diarized_semantic.html`；
- LLM prompt、响应和运行摘要：`semantic_speaker_prompts.jsonl`、
  `semantic_speaker_responses.jsonl`、`semantic_speaker_resolution_run.json`；
- 推理与映射摘要：`sortformer_diarization_run.json`、`speaker_mapping_smoothed_run.json`、
  `review_diarized_smoothed_run.json`。未平滑版本保留用于审计对照。

## 7. 验证与下一步

- 新增针对性测试：11 passed；
- 整仓测试：108 passed；
- `ruff check .`：通过；
- HTML 内联 JavaScript：2/2 语法解析通过；
- 浏览器人工交互：未验收，原因是当前没有可用浏览器实例。

下一步先扩到预先选定的 5 例，覆盖短/长、多参与者、普通话和中英混说，并汇总成功率、RTF、
显存、speaker 数、极短 speaker、映射覆盖、重叠歧义和空区间。对已知参与者超过 4 人或
Sortformer 明显失效的病例，准备 VAD + TitaNet + clustering 回退。5 例中至少选取代表性片段
人工回听 speaker 切换；在独立人工 RTTM 完成前仍不报告 DER/JER。
