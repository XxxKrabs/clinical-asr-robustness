# ASR 置信度主线决策清单

更新时间：2026-07-02

本文记录“音频原始数据 → ASR → top-k 候选 + 置信度”主线在真正实现前的用户决策。2026-07-02 已完成 D001-D010 拍板，后续实现和实验应以本文为准，并同步维护 `docs/todo.md`。

## 已确认结论摘要

| 决策编号 | 结论 |
|---|---|
| D001 | 使用本地 NeMo 模型；权重已迁移到 project 内 `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`，默认不提交 Git。 |
| D002 | 第一版采用离线批处理。 |
| D003 | 分别跑 doctor / patient 两路 ASR，再按时间合并。 |
| D004 | V0 采用 sequence-level beam n-best hypotheses，对齐到低/中置信度 span 生成候选；不做每个词独立 top-k。 |
| D005 | entropy confidence 当前默认 `tsallis + alpha=0.33 + lin`；`exp` 和 `max_prob` 保留为消融/校准对照。 |
| D006 | V0 先用启发式阈值生成可审阅样本。 |
| D007 | 同时保存 word 和 segment：底层精细，界面友好。 |
| D008 | 外部 `Speech-main` 仅作为一次性迁移来源；必要源码、示例、配置和许可说明已迁移到 `third_party/speech_main/`，后续脚本不得依赖外部仓库路径。 |
| D009 | 第一批样本规模为 3-5 条 consultation。 |
| D010 | 本轮只验收 ASR 输出层，不强行接入下游任务。 |

## D001：第一版 ASR 模型与运行方式

可选方案：

1. **本地 NeMo 模型/预训练模型**：最符合已选论文方法，能直接使用 entropy confidence；但需要环境依赖、模型权重和算力。
2. **外部 ASR API**：启动快，但通常拿不到完整 log-prob/entropy confidence，和论文方法不完全一致。
3. **数据集自带 ASR 或已有转写**：实现最轻，但不能验证“音频 → ASR 置信度”主线。

建议：第一版使用本地 NeMo 路线。若 GPU/模型下载受限，可先选较小英文模型做 smoke test，再换到 Parakeet/FastConformer 等更强模型。

已确认：第一版坚持本地 NeMo。原始权重来自外部 `Speech-main\weights\stt_en_fastconformer_ctc_large.nemo`，2026-07-02 已迁移到 project 内 `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`；后续优先使用该 project 内权重，不把联网下载或外部仓库路径作为默认路径。运行环境可根据适配度选择 Windows 或 WSL。

## D002：离线批处理还是流式脚本

可选方案：

1. **离线批处理**：先处理 PriMock57 小批量音频，适合研究闭环和可复现评估。
2. **RNNT 流式/长音频脚本**：更接近实时系统，但初期复杂度更高，且偏 RNNT。

建议：第一阶段先离线批处理；前端实时/流式 demo 放到 ASR 输出 JSONL 稳定之后。

已确认：先做离线批处理，不立即追求实时流式。

## D003：PriMock57 双路音频怎么使用

PriMock57 的 `audio/` 下是 doctor / patient 分开的 wav，`transcripts/` 下是对应 TextGrid。

可选方案：

1. **分别跑 doctor/patient 两路 ASR，再按时间合并**：说话人标签最干净，适合第一版；但不完全模拟单麦克风真实对话。
2. **先混音成单路对话音频再跑 ASR**：更接近真实录音，但第一版说话人归属和重叠会更难。
3. **只选单一路音频做 smoke test**：最快，但不能覆盖医患交互主线。

建议：第一版先分别跑两路并合并；后续再做混音/远场版本作为鲁棒性扩展。

已确认：第一版采用“doctor/patient 分路 ASR + 时间合并”。

## D004：top-k 候选的定义

NeMo 的 n-best 更自然是整句/整段 beam hypotheses，不是天然的“某个词/span 的 top-k 候选”。

可选方案：

1. **sequence-level n-best 对齐到低置信度 span**：第一版最现实；可把不同 beam 里对应位置的差异作为候选。
2. **自定义 token/frame-level top-k 提取**：更贴近点击某词调候选，但需要更深改造解码输出。
3. **ASR n-best 不足时补充文本 repair/词表候选**：可用，但应标注为辅助候选，不混同于 ASR 原生置信度。

建议：V0 先做 sequence-level n-best 对齐到低/中置信度 span；把真正 token-level top-k 作为 V1。

已确认：V0 接受“sequence-level beam n-best hypotheses 对齐到 uncertain span”的候选生成方式。系统只对连续低/中置信度词合并得到的 uncertain span 生成候选，并在 UI 中作为一个整体供医生选择；不做每个词的独立 top-k 候选。

## D005：entropy confidence 参数

可选方案：

1. 固定 NeMo/论文实现中的一组 entropy 参数：`entropy` + `tsallis` + `alpha=0.33`。
2. 使用 streaming 配置中常见的 `alpha=0.5`。
3. 做小网格搜索：`alpha`、`aggregation`、`entropy_type` 都比较。

建议：当前 demo 默认使用 `entropy_norm=lin` 与 `aggregation=mean`；同时保留
`entropy_norm=exp`、`aggregation=min` 和 `max_prob` 作为候选消融。

已修正：T028 初版沿用 NeMo 默认 `entropy_norm=exp` 时，PriMock57
`day1_consultation01:patient` 的 word confidence 最大仅约 0.075，导致全红；
同一音频改用论文同样支持的 `entropy_norm=lin` 后，均值约 0.912，分布更适合
绿/黄/红 demo。后续 T031 仍需用 reference 做正式校准。

## D006：绿/黄/红阈值

可选方案：

1. 先启发式阈值，例如绿 `>=0.80`、黄 `0.50-0.80`、红 `<0.50`。
2. 用 reference 校准后再定阈值，例如按高风险错误召回率选择黄/红分界。
3. 按人工审阅预算定阈值，例如每条样本最多提示 N 个片段。

建议：V0 先用启发式阈值生成可审阅样本；跑出 reference 对齐后再做校准阈值。

已确认：V0 先用启发式阈值生成可审阅样本；后续再基于 reference 对齐校准阈值。

## D007：第一版输出粒度

可选方案：

1. **word-level 为主**：最贴合论文和 NeMo `word_confidence`。
2. **segment/span-level 为主**：更适合医生交互，但需要从 word 合并。
3. 同时保存 word 和 segment：底层精细，界面友好。

建议：同时保存 word-level 原始输出和 span/segment-level 派生输出；医生界面优先展示 segment。

已确认：第一版同时保存 word 和 segment，底层保留精细 word 信息，界面优先使用更友好的 segment/span。

## D008：是否改外部 `Speech-main`

可选方案：

1. **不改外部仓库**：在本项目 `scripts/` 和 `src/` 中做适配层；最安全。
2. 在 `Speech-main` 里直接改官方脚本：短期方便，但后续同步和复现麻烦。

建议：不改外部仓库。只在本项目内记录依赖路径、调用 NeMo API、导出项目 JSONL。

已确认并更新：不修改外部 `Speech-main` 代码；外部仓库只作为一次性迁移来源，后续会删除。2026-07-02 已将必要 NeMo 源码、ASR 示例/配置、上游许可/来源文件迁入 `third_party/speech_main/`，并将模型权重迁入 `data/external/asr_models/nemo/`。项目侧 adapter、smoke test 和后续 ASR 输出层流程不得读取、import 或引用外部 `Speech-main` 路径。

## D009：第一批样本规模

可选方案：

1. 3-5 条 consultation：适合 smoke test 和调 schema。
2. 10-15 条 consultation：能初步看阈值和候选覆盖。
3. 全部 57 条：更完整，但容易被环境和格式问题拖住。

建议：第一轮 3-5 条；跑通后扩到 10-15 条，再考虑全量。

已确认：第一批样本规模选择 3-5 条 consultation。

## D010：下游任务是否立刻接入

可选方案：

1. 先只完成 ASR 输出 JSONL、confidence、n-best、颜色分层。
2. 同步接入一个下游任务。

建议：本轮先完成 ASR 主线输出；等你审核 ASR 输出字段后，再接症状/实体抽取或 note 信息保持评估。

已确认：本轮只验收 ASR 输出层，不强行接入下游任务。

## 当前不适配或需警惕之处

- NeMo entropy confidence 只对 ASR 已输出的 token/word 有置信度；漏识别的 reference 词没有直接置信度。
- NeMo n-best 是 sequence-level 候选，不天然是医生点击某个词后的 span-level top-k。
- 官方 `examples/asr/transcribe_speech.py` 支持 n-best 和 hypothesis，但默认写文件时不输出 `word_confidence`；需要项目侧适配。
- confidence 与 n-best 可能需要两次解码或两套配置，不能假设一个命令同时拿到所有字段。
- PriMock57 是 mock consultation，不是真实患者数据；伦理和隐私风险较低，但真实临床声学复杂度不足。
