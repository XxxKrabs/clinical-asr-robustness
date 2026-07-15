# 中文 5 例 ASR 置信度与病例信息鲁棒性 pilot

日期：2026-07-15
涉及任务：T058、T059、T060、T063、T064、T066、T067、T070

## 结论摘要

中文主线已从 1 例扩展到固定 5 例 pilot。5/5 例完成确定性音频预处理、Parakeet auxiliary-CTC
置信度、acoustic 5-best、Streaming Sortformer、医学实体筛选、病例级交互审阅包和 noisy/proxy
两路病例摘要。总计 74.60 分钟、152 个 30 秒窗口、9,458 个 ASR 审阅单元；所有 ASR 窗口均有
词级置信度和多个去重 beam，5 个整例均完成说话人分离。

为在没有人工 clean transcript 时先检验鲁棒性分析链路，本轮另建 5 份
`llm_multi_asr_consensus_proxy`：强 LLM 只根据三路自动转录做保守融合与修复，没有听原音频，
也没有人工转录或医生确认。所有记录均显式保存 `audio_used=false`、
`human_transcriber_used=false`、`doctor_confirmed=false`、`is_gold=false` 和
`formal_quality_claim_allowed=false`。因此本文的 CER、校准和事实保持指标均为探索性代理结果，
不能替代人工 reference 上的正式结论。

代理评估显示：macro Proxy CER 为 21.2%，病例关键信息保持分数 CIPS 为 88.0%，代理事实文本
召回为 75.1%；把黄/红字符送审可覆盖 79.5% 的可着色错误，审阅字符比例为 28.8%。同一摘要
模型在 noisy 与 proxy 输入上的事实 F1 只有 35.7%，说明即使关键术语总体保持尚可，下游病例
整理仍对转写噪声敏感，适合作为本课题的鲁棒性展示结果。

## 固定病例与覆盖

| case | 时长（分钟） | 预期参与人数 K | 选择理由 |
|---|---:|---:|---|
| `case_0068` | 4.7 | 2 | 最短病例、双人基线 |
| `case_0057` | 5.0 | 6 | 短音频、多参与者，超过 Sortformer 4-speaker 上限 |
| `case_0040` | 12.7 | 6 | 中等时长、多参与者与较高噪声 |
| `case_0008` | 14.3 | 4 | 中等时长、普通话/中英混说信号 |
| `case_0021` | 37.9 | 5 | 长音频、恢复性与批量稳定性压力测试 |

预处理器已改为每个源 MP3 只解码和重采样一次，再从内存切出连续窗口，避免旧实现对每个
30 秒窗口重复打开并 seek MP3。输出 152 个 16 kHz mono PCM16 窗口和 5 个整例 WAV；窗口
覆盖原始时间轴，实际总时长为 4,475.627 秒。

## 工程运行结果

| 环节 | 结果 | 关键工程指标 |
|---|---|---|
| ASR confidence | 152/152 成功 | 转写 84.87 秒，RTF 0.01896，峰值 allocated 2.465 GiB |
| acoustic 5-best | 152/152 成功 | 692 个 beam；152/152 均有多个且去重候选；RTF 0.00904 |
| Streaming Sortformer | 5/5 成功 | 原始 ASR word 映射 8,637/9,458（91.32%） |
| 同人短空洞桥接 | 193 个 word | 展示层映射 8,830/9,458（93.36%）；未桥接重叠歧义 |
| 医学实体筛选 | 152/152 完成 | 181 个输入 mention，147 个对齐；形成 73 个黄/红医学 span |
| 病例级审阅包 | 5 例、1,059 turns | 9,458 word；green/yellow/red=6,620/1,892/946 |
| 交互 HTML | 已生成 | 73 个 span，11 个有 acoustic span 候选；支持五类审阅动作和 JSONL 导出 |
| 病例摘要 | 10/10 完成 | 5 个 noisy + 5 个 proxy，同模型、同 schema、同解码条件 |

confidence 首次从 Windows 挂载的 `.nemo` 冷恢复耗时 1,221.44 秒，是明显瓶颈。随后把同一
SHA-256 的 checkpoint 复制到 WSL 持久缓存，5-best 恢复降至 35.43 秒；这不改变模型内容，
但说明全量 40 例应复用 WSL 缓存，避免把文件系统恢复开销误写成 ASR 推理成本。

本轮没有对 152 个窗口逐一调用完整对话 LLM 候选生成器。acoustic beam 只为 11/73 个医学
span 提供局部差异候选；其余 span 仍可接受 ASR、手工编辑、拒绝或标记无法判断。首例已经验证
完整对话 LLM 候选路径，本轮结果不能声称 5 例 top-k span 覆盖已经充分。

## 代理参考与自定义指标

### 代理参考构造

每例输入三路自动文本：当前推荐 speaker/source 转录、带医学先验的 Qwen3-ASR 转录和带医学
先验的 Paraformer 转录。LLM 被要求优先保留多路一致内容，对药名、否定、数字、单位、侧别、
DBS 参数和说话人归属不确定项保守标记，并同时给出带 `evidence_terms` 的代理关键事实。

代理参考的用途仅为：

- 验证 CER、置信度风险覆盖和病例信息指标的代码链路；
- 选择后续人工精转与复核的高价值病例/片段；
- 形成可展示但明确标为 proxy 的 pilot 图表。

它不用于声称 ASR 准确率、医生确认收益或临床摘要正确性。

### 指标

- `Proxy CER`：中文字符与混合语言 token 归一化后的编辑距离，仅对代理参考计算。
- `CIPS`（Critical Information Preservation Score）：医学术语、否定、数字+单位参数和侧别的
  召回加权，权重依次为 0.35、0.20、0.25、0.20；代理参考中缺失的分量从分母移除，其余权重
  重归一化。
- `代理事实文本召回`：LLM 代理事实的 `evidence_terms` 是否能在 raw ASR 中找到；它比全文
  CER 更直接反映病例信息可恢复性。
- `黄+红可检测错误召回`：序列对齐后，能归因到 hypothesis 字符的替换/插入错误中，被黄/红
  覆盖的比例。ASR 删除没有可着色字符，不能归因到颜色。
- `审阅字符比例`：黄/红字符占比，作为人工审阅成本代理。
- `Proxy word ECE/Brier`：把 proxy 对齐正确性当作临时标签的置信度校准误差。
- `risk-coverage/AURC`：按置信度从高到低保留字符时，选择性错误率随覆盖变化的曲线。
- `病例摘要事实 F1`：同一 LLM、相同 schema 下，noisy 与 proxy 输入的同字段事实模糊匹配稳定性；
  不是人工 gold factuality。

## 可展示结果

| 指标 | 5 例 macro/micro 结果 | 解释 |
|---|---:|---|
| Proxy CER | 21.2% | 代理全文转写差异，越低越好 |
| CIPS | 88.0% | 病例关键信息保持，越高越好 |
| 代理事实文本召回 | 75.1% | raw ASR 可直接找回的代理事实比例 |
| 黄+红可检测错误召回 | 79.5% | 风险高亮覆盖能力 |
| 审阅字符比例 | 28.8% | 成本代理，约审三成字符 |
| Proxy word ECE | 0.0510 | 未校准置信度的代理校准误差 |
| green/yellow/red 可检测错误率 | 3.3% / 19.3% / 50.2% | 风险颜色呈清晰单调分层 |
| 声学 speaker 映射覆盖 | 91.0% | 仅工程覆盖；无人工 RTTM，不是 DER/JER |
| noisy↔proxy 病例摘要事实 F1 | 35.7% | 下游整理对 ASR 噪声较敏感 |
| noisy↔proxy critical fact recall | 33.9% | 药物/否定/计划等关键字段稳定性较低 |

颜色分层是本轮最清晰的工程信号：yellow 的可检测错误率约为 green 的 5.9 倍，red 约为
green 的 15.3 倍。它支持“优先审阅黄/红片段”的交互设计，但仍需人工 reference 重新校准
阈值后才能形成正式结论。

逐例结果与完整口径见：

- `outputs/remote_programming_40/t058_pilot5/report/pilot5_results.md`
- `outputs/remote_programming_40/t058_pilot5/report/pilot5_case_metrics.csv`
- `outputs/remote_programming_40/t058_pilot5/report/pilot5_robustness_summary.json`
- `outputs/remote_programming_40/t058_pilot5/report/pilot5_report.html`：汇总指标卡、逐例表和 5 张图的
  单页展示入口。

已生成五张 900 px 宽的 SVG：

1. `figure_1_engineering_coverage.svg`：各病例窗口、ASR 与 speaker 工程覆盖；
2. `figure_2_proxy_robustness_metrics.svg`：CER、CIPS、事实召回、错误捕获与审阅成本；
3. `figure_3_risk_color_stratification.svg`：green/yellow/red 实际代理错误率；
4. `figure_4_risk_coverage.svg`：逐例 selective risk-coverage 曲线；
5. `figure_5_downstream_case_summary_robustness.svg`：逐例摘要事实 F1 与关键事实召回。

病例级交互页位于
`outputs/remote_programming_40/t058_pilot5/doctor_review_pilot5.html`。静态结构检查确认 5 个 case、
本地恢复、JSONL 导出、接受 ASR、候选选择、手工编辑、拒绝和无法判断动作均已嵌入。Codex
in-app browser runtime 本轮连续初始化超时，因此尚未完成真实鼠标点击、音频回听和下载文件
回放；这一项仍留在 T060/T062 的人工验收门槛内。

代码与产物验证结果：整仓 `pytest` 为 120 passed，`ruff check .` 通过；最终 HTML 的 2 个内联
JavaScript 块通过 Node 语法解析；5 张 SVG 均可作为 XML 解析，尺寸为 900×500 或 900×520，
并包含坐标、标签和数据文字。由于浏览器运行时不可用，本轮不声称完成视觉像素级或交互点击
验收。

## 验收边界与下一步

本轮通过的是“5 例工程运行 + 代理参考探索评估 + 可展示图表”门槛，不是完整的 5 例医生确认
门槛。继续扩 40 例前，建议按以下顺序补齐：

1. 在可用浏览器中对 1 例执行真实点击、回听、本地恢复和 JSONL 下载，并用 T035 生成真实
   `confirmed_transcript`；
2. 由研究者/医生完成至少 1 例真实试审，记录耗时、回听次数和动作分布；
3. 对这 5 例制作听音频的独立人工 reference，优先核对药物、否定、数字单位、侧别和 DBS 参数；
4. 在人工 reference 上复算 CER、CIPS、ECE/Brier、risk-coverage 和候选覆盖，再决定阈值；
5. 工程链路稳定后以可续跑方式扩到 40/40；若尚无全量 reference，仍只报告工程覆盖与明确标源的
   proxy 指标，不声称正式质量提升。

所有转写、代理参考、音频、交互页面和逐例结果均位于 Git 忽略目录。文档只记录匿名 case id
与聚合数字，不包含病例正文。所有病例摘要均为研究输出，不构成临床建议。
