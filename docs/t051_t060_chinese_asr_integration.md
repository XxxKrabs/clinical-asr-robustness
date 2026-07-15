# T051–T060 中文真实数据 ASR 增量集成与 1 例整例验证

日期：2026-07-14

本记录只保存匿名 ID、聚合统计、模型/运行配置和本地相对路径，不写原始对话、逐例转录、
病例正文或可识别信息。所有输出仅用于研究评估，不构成临床建议。

## 1. 交付边界

本轮不是新建一套中文孤立系统，而是在原有 PriMock57 主线上增加轻量数据集 profile：

| 项目 | PriMock57 | `remote_programming_40` |
|---|---|---|
| 语言/文本单元 | 英文、whitespace word | 中文/中英混说、timestamp/character/auto unit |
| checkpoint | `stt_en_fastconformer_ctc_large.nemo` | `Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo` |
| 模型分支 | 原有纯 CTC | Hybrid RNNT 主头 + auxiliary CTC |
| 词级信号 | NeMo word confidence | auxiliary CTC frame distribution 聚合 |
| 风险策略 | 历史固定阈值 | `demo_quantile_v0`，`calibrated=false` |
| 输出根目录 | `outputs/primock57/` | `outputs/remote_programming_40/` |

T028 置信度、T037 n-best、T038 医学实体、T029 候选、T030/T036 页面和 T035 反馈回放仍
共用原模块。`--dataset auto` 优先读取 manifest 的 `dataset`；无数据集提示时保持历史英文
默认，不会把中文 checkpoint 或阈值静默应用到 PriMock57。

## 2. 本地资产与 T051 快照

资产已归位到项目的 Git 忽略目录：

- 原始 40 例包：`data/raw/remote_programming_40/远程程控人工复核资料_精选40例_无病历版_20260713/`；
- Qwen 自动病历 baseline：`data/external/remote_programming_40/远程程控精选40例_Qwen病历_20260714_加密/`；
- 中文 checkpoint：`data/external/asr_models/nemo/Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo`；
- 英文 checkpoint 继续保留：`data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`。

`build_remote_programming_40_manifest.py` 生成不含正文的匿名清单与逐文件 SHA-256：

- 40 个病例、40 个 MP3；
- raw + Qwen 快照共 683 个文件、686,834,687 bytes；
- 音频总时长 42,626.664 秒（约 11.84 小时）；
- 最短 280.704 秒，中位数 735.960 秒，最长 3,789.096 秒；
- 快照 digest：`5d219620861b9dd4ad34296dec4caeff2de5aeeff2ac743c069fe19c01572994`。

主要产物：

- `data/interim/remote_programming_40/manifests/remote_programming_40_asr_manifest.jsonl`；
- `data/interim/remote_programming_40/manifests/remote_programming_40_snapshot_files.jsonl`；
- `data/interim/remote_programming_40/manifests/remote_programming_40_snapshot_summary.json`。

本地 checkpoint 来自用户提供的已下载 artifact；本轮已记录精确 digest 和恢复配置，但其原始
下载页面/许可证凭据没有嵌入 artifact，公开发布或重新分发前仍需单独补齐来源证明。

## 3. T052 checkpoint 恢复结果

`check_wsl_asr_env.py --model-path ... --restore-model` 在 WSL Conda `clinical-asr` 中成功：

- 文件大小：2,338,476,221 bytes；
- SHA-256：`0ac223ddf6ed7366d5c662abcc8d6a827767c44b93937e0f8f04ae05dba45e6a`；
- 实际模型类：`EncDecHybridRNNTCTCBPEModel`；
- tokenizer：SentencePiece BPE，词表 7,000；
- 采样率：16 kHz；auxiliary CTC blank id：7,000；
- 默认主解码：RNNT `greedy_batch`；项目置信度/n-best 走 auxiliary CTC；
- NeMo 3.1.0、PyTorch/torchaudio 2.11.0+cu126；
- GPU：RTX 4060 Laptop，CUDA 可用。

结果位于
`outputs/remote_programming_40/t052_checkpoint_validation/checkpoint_restore_summary.json`。

## 4. T053 音频与绝对时间轴

`preprocess_asr_audio.py` 使用 `soundfile` 解码、算术平均混声道、
`scipy.signal.resample_poly` 重采样，输出 16 kHz mono PCM16 WAV 连续短窗。每个窗口保存：

- 稳定 `unit_id` / `parent_sample_id`；
- 输入窗口路径和 SHA-256；
- `source_audio_filepath` / `source_audio_sha256`；
- `source_start_sec` / `source_end_sec` / `source_duration_sec`。

最短、典型、最长 3 例的 30 秒首窗 QC 均通过。最短整例被切成 10 个窗口，覆盖
0–280.704 秒。ASR record 对外指向原始 MP3，并把窗口内时间平移到原音频绝对时间；实际
推理 WAV 路径保留在 `metadata.source_manifest.asr_input_audio_filepath`。

## 5. 中文 adapter 与 schema

实现要点：

- Hybrid checkpoint 自动切换到 auxiliary CTC 解码，纯 CTC 英文分支不变；
- 中文单元优先采用可靠 timestamp unit，否则按 Unicode 字符回退；保留
  `char_start/char_end` 和原始分隔符；
- CTC emitted SentencePiece 表面文本按字符区间聚合到中英文可审阅单元；
- segment/span、上下文渲染和 confirmed transcript 不再假设 `.split()`；
- 反馈按字符区间从右向左应用，不向中文插入新空格；
- 分窗 record 的时间戳与页面音频统一使用原始 MP3 绝对时间；
- 中文医学实体匹配采用 Unicode NFKC/casefold，忽略 ASR 分词空格和标点后再回映射原字符。

## 6. T054/T056/T057 最短整例结果

运行条件：10 个连续窗口、总 ASR 输入 280.661375 秒、CUDA FP16、batch size 1。模型从
Windows 挂载盘恢复约需 5 分钟；以下 RTF 只计算实际 transcribe 时间，不把 restore I/O
计入。

| 输出 | 结果 |
|---|---|
| confidence | 10/10 成功；13.776 秒；RTF 0.0491；峰值 allocated 2.465 GiB |
| n-best | 10/10 成功；2.953 秒；RTF 0.0105；峰值 allocated 2.470 GiB |
| 审阅单元 | 726；字符偏移错误 0；绝对时间越界 0 |
| 风险颜色 | green 507、yellow 146、red 73 |
| 风险声明 | `demo_quantile_v0`；`calibrated=false`；当前运行内按秩分配 |
| n-best | 每窗 3–5 个去重 beam；10/10 窗均有多个不同序列候选 |

主要产物位于 `outputs/remote_programming_40/t054_shortest_full/`。完整 frame distribution
保存为本地 `.npz` 证据；逐帧 top-k 不直接展示为完整词。

## 7. T038–T060 共用审阅链

在同一最短整例上复用原流水线，最终状态为 `T038/T029/T030/T036 = ok`：

- T038：10 条实体抽取缓存命中；7/7 实体匹配；22 个医学单元着色；4 个黄/红 span
  （1 yellow、3 red）；
- T029：43 个 sequence alternatives；1 个可对齐的局部 span alternative；候选为空仍合法；
- T030：10 个需审阅医学单元全部有原始 MP3 绝对时间；
- T036：单文件 HTML 支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、
  `unable_to_judge` 和 JSONL 反馈导出；
- T035：中文字符区间反馈回放已有单元测试覆盖，但本轮没有伪造真实医生反馈或
  `confirmed_transcript`。

最终本地页面：
`outputs/remote_programming_40/t054_shortest_full/remote_programming_40_shortest_full_doctor_review.html`。
当前 Codex 会话没有可用浏览器实例，因此未完成截图/人工点击验收；流水线结构验证已通过，
T060 仍保持“进行中”。

## 8. 验证与已修问题

- WSL `clinical-asr`：`95 passed`；
- `ruff check .`：通过；
- PriMock57 英文 dry-run：仍选择英文 checkpoint、`nemo_word_confidence` 和
  `fixed_thresholds`；
- 中文 dry-run：选择 Hybrid checkpoint、`ctc_frame_distribution`、保存 frame artifact、
  `demo_quantile_v0`。

整例验证中发现并修复：

1. 中文无空格 transcript 被旧 CTC word 聚合当成单一词；现按 timestamp/字符表面文本对齐；
2. 审阅侧整段时长被运行统计按窗口重复累计；RTF 改为从实际输入 manifest 求和；
3. 旧医学实体规范化只保留 ASCII，中文实体 0/7 匹配；改为 Unicode 规范化后达到 7/7。

## 9. 尚未完成与下一步

- 尚未跑 5 例和 40 例，不声称全量迁移完成；
- 尚未保存独立的 `am_raw/decoded_with_lm/display_itn` 三层和 LM/ITN transform log；
- 当前只有 acoustic auxiliary-CTC beam，未接官方 4-gram LM；
- 未完成浏览器人工点击、真实医生反馈、人工 reference/gold 或正式置信度校准；
- 包内自动转录和 Qwen 自动病历仍不是 reference/confirmed/gold；
- 下一门槛是 T058 五例 pilot，再做 T060 人工页面验收和 T062 一例真实试审。
