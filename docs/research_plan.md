# 研究计划草案

## 1. 研究定位

远程随访、基层医疗互动和医患对话中的自动转写文本往往不是干净的人工转录，而是由 ASR 生成的 noisy transcript。错误可能来自口音、远场麦克风、重叠说话、医学术语/药名识别困难、否定词遗漏和说话人混淆。下游病例信息整理模型如果只在 clean transcript 上评估，可能高估真实可用性。

2026-07-01 起，本项目近期主线调整为：

**音频 → ASR → noisy transcript + ASR 置信度 → 医生实时交互确认 → confirmed transcript → 下游病例信息整理鲁棒性评估。**

关键变化是：置信度主要放在 ASR 输出层，而不是 noisy transcript → repair 的文本修复层。文本 repair、规则/词表增强和 LLM 候选可以作为辅助扩展，用于 ASR top-k 候选不足时补充建议，但不再是第一阶段的主轴。

本项目希望回答四个问题：

1. ASR 输出的词级、span 级或片段级置信度，能否有效提示医学转写错误风险？
2. 绿色/黄色/红色等置信度可视化，能否帮助医生更快定位需要确认的转写片段？
3. 医生点击中低置信度片段并选择/编辑 top-k 候选后，confirmed transcript 是否更接近 reference？
4. confirmed transcript 是否能提升症状抽取、病例摘要、诊疗计划整理等下游任务质量？

所有自动生成的病例摘要、诊疗计划和修正结果都只作为研究输出，不构成临床建议。

## 2. 数据与样本版本

第一阶段不追求全局统一 schema，但每条实验样本应尽量保留以下信息：

- `audio_id` / `audio_path`：音频来源、数据集、split、许可状态和本地路径指针；不要提交真实患者隐私或受限音频正文。
- `reference_transcript` / `clean_transcript`：人工转录、校正文本或高可信参考文本；人工转录通常不能直接当作 noisy transcript。
- `asr_transcript` / `noisy_transcript`：ASR 输出文本。
- `asr_tokens` / `asr_segments`：ASR token、时间戳、说话人标签、置信度、候选列表等结构化输出。
- `confidence` / `confidence_level`：连续置信度及其映射后的等级，例如 `high` / `medium` / `low`，或绿色/黄色/红色。
- `asr_alternatives`：ASR top-k / n-best 候选；如果当前 ASR 系统不能输出候选，应明确记录能力缺口。
- `interaction_log` / `doctor_feedback`：医生或人工核验者的点击、选择、编辑、拒绝、无法判断等动作。
- `confirmed_transcript`：医生确认后的 transcript，可作为下游任务输入。
- `downstream_outputs`：症状抽取、病例摘要、诊疗计划整理等任务输出及评价结果。

已有的 `repair_candidates` / `repaired_transcript` 字段保留为可选扩展：当 ASR 候选不足时，可由词表、规则或 LLM 生成额外文本候选，但应标注其来源，避免和 ASR 原生置信度混淆。

## 3. ASR 置信度与医生交互流程

计划中的最小闭环如下：

1. 输入音频样本；
2. 运行或接入 ASR，生成 noisy transcript；
3. 保留 ASR token/span/segment 的时间戳、置信度和 top-k / n-best 候选；
4. 将置信度映射为颜色等级，例如：
   - 高置信度：绿色，默认低优先级审阅；
   - 中置信度：黄色，医生可按需点击检查；
   - 低置信度：红色，优先提示医生确认；
5. 医生点击黄色或红色词/短语，系统展示 ASR top-k 候选、上下文和可编辑输入框；
6. 医生选择候选、手动编辑、拒绝候选或标记无法判断；
7. 系统记录 feedback，并生成 confirmed transcript；
8. 将 raw ASR / confirmed / reference 输入下游任务，评估质量差异和人工成本。

第一版可以先离线模拟医生交互：把低/中置信度片段导出为 JSONL、表格或静态 HTML，由人工选择候选并回填反馈。前端 demo 可以稍后再做，不必一开始就实现完整实时系统。

## 4. 系统原型设想

系统原型可分为三个部分：

- ASR 后端：负责音频输入、ASR 解码、词级/片段级置信度、top-k 候选、时间戳和说话人信息输出。
- 交互前端：按置信度颜色高亮文本，支持点击片段、展示候选、编辑文本、拒绝候选和记录医生反馈。
- 评估后端：比较 raw ASR、confirmed transcript 和 reference 在文本差异、置信度校准、交互成本和下游任务质量上的表现。

第一版界面重点不是临床系统完整性，而是验证交互逻辑：医生是否能快速看到不确定位置，候选是否足够有用，反馈能否结构化保存。

## 5. 错误类型

重点关注以下错误：

- 医学术语识别错误；
- 药名、剂量、频次错误；
- 否定词遗漏或极性翻转；
- 医生/患者说话人标签混淆；
- 重要症状、检查、用药或计划项缺失；
- 口音、代码混合、远场麦克风、背景噪声和重叠说话导致的 ASR 错误；
- ASR 高置信度但实际错误的“危险自信”片段。

T005 已完成的 ACI-Bench 文本错误分析可作为医学概念错误和下游影响分析的参考；但 7.1 后还需要补充真实或模拟 ASR 置信度维度。

## 6. 下游任务

### 症状/医学实体抽取

抽取症状名称、是否存在、持续时间、严重程度、部位、诱因和缓解因素。尤其关注否定症状，例如“无胸痛”“否认发热”。第一阶段优先级较高，因为指标相对稳定。

### 病例摘要

生成结构化摘要，可包含主诉、现病史、既往史、用药史、检查结果、评估与计划。摘要结果必须标注为研究输出。

### 诊疗计划整理

抽取药物调整、检查安排、转诊、复诊时间和生活方式建议，并评估是否归属到正确说话人。该任务临床含义较强，必须持续声明“不构成诊疗建议”。

## 7. 方法路线

优先探索以下方法：

1. ASR 置信度输出：选择或接入能输出词级/片段级置信度、时间戳和候选的 ASR 系统；
2. 置信度分层与校准：将连续置信度映射为绿/黄/红，并用 reference transcript 分析分桶错误率、ECE 或 Brier score；
3. ASR top-k / n-best 候选：评估候选中是否包含正确医学词、药名、否定词或说话人标签；
4. 医生交互模拟：先用离线人工核验记录选择、编辑、拒绝，后续再做前端 demo；
5. 文本 repair 辅助候选：当 ASR 候选不足时，可用医学词表、规则、LLM 或 Seq2Seq 纠错模型补充候选；
6. 反馈学习扩展：医生选择结果后续可用于候选排序、置信度校准、主动学习或 ASR/纠错模型微调；该部分暂不作为近期主线。

## 8. 评价思路

建议同时评估四类指标：

### ASR 与置信度本身

- WER / CER；
- 医学概念 WER / MC-WER；
- 高/中/低置信度分桶错误率；
- 置信度校准情况，例如 ECE 或 Brier score；
- 高置信度错误比例，尤其是医学关键概念上的危险错误。

### 候选与交互质量

- ASR top-1 / top-k 命中率；
- top-k 是否覆盖正确医学术语、药名、否定表达；
- 每条样本需要医生确认的片段数；
- 医生选择、编辑、拒绝、无法判断的分布；
- 平均确认成本和质量收益。

### confirmed transcript 质量

- raw ASR vs reference；
- confirmed transcript vs reference；
- confirmed 相对 raw ASR 的恢复率；
- 错误类型层面的恢复情况。

### 下游任务收益

- raw ASR → 下游任务表现；
- confirmed transcript → 下游任务表现；
- clean/reference → 参考上限；
- confirmed 相对 raw ASR 的提升，以及相对 reference 上限的接近程度。

## 9. 推荐第一阶段里程碑

第一阶段不追求规模，追求闭环：

1. 选择一批可许可使用的含音频样本，并明确 reference transcript；
2. 选择 ASR 系统，确认是否支持 token/span 级置信度、时间戳和 top-k / n-best 候选；
3. 定义 `asr_confidence`、`confidence_level`、`asr_alternatives`、`interaction_log` 和 `confirmed_transcript` 的轻量字段约定；
4. 跑出第一批 raw ASR transcript + confidence；
5. 用绿/黄/红阈值生成可审阅样本；
6. 用离线人工核验或最小前端模拟医生点击、选择、编辑和拒绝；
7. 生成 confirmed transcript；
8. 在一个下游任务上比较 raw ASR / confirmed / reference；
9. 形成 ASR 置信度校准、交互成本和下游收益的初步报告。
