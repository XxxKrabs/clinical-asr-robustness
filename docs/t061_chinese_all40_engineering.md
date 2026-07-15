# T061 中文 40 例全量 ASR 工程运行与展示报告

更新时间：2026-07-15

## 结论

中文 40 例已经完成全量工程流水线：确定性音频预处理、Hybrid auxiliary-CTC ASR
置信度、acoustic 5-best、Streaming Sortformer、医学实体优先筛选、局部候选、病例级审阅包和
40 个独立交互页面均已生成。全量报告状态为 `completed`，包含 40 行病例级 CSV、Markdown、
HTML 和 5 张 SVG。

本轮 40 例没有独立人工 clean/reference，也没有真实医生 confirmed transcript。因此全量结果只
用于说明工程覆盖、风险信号、资源成本、候选可用性和审阅负载，不报告 CER、DER/JER 或病例
摘要准确率。正式质量指标仍只在明确标源的固定 5 例 LLM 多路 ASR 融合 proxy 上探索，proxy
不是人工 gold。

## 数据与运行覆盖

| 项目 | 全量结果 |
|---|---:|
| 匿名病例 | 40/40 |
| 源音频总时长 | 710.44 min（11.84 h） |
| 30 秒 ASR 窗口 | 1,442 |
| ASR 审阅单元 | 75,228 |
| confidence / n-best / diarization 病例覆盖 | 40/40 / 40/40 / 40/40 |
| 空 ASR 窗口 | 1 |
| 缺单元时间戳 | 21 |
| CTC 对齐失败后全红兜底窗口 | 9 |
| green / yellow / red | 52,659 / 15,046 / 7,523 |
| acoustic n-best beams | 6,565 |
| 有多个不同 beam 的窗口 | 1,440/1,442 |
| 原始 / 短空洞桥接后 speaker 映射（macro） | 88.9% / 90.5% |
| 医学实体 mention 输入 / 对齐 | 1,233 / 1,036 |
| 医学高亮单元 / 黄红医学 span | 2,438 / 447 |
| 有 acoustic 局部候选的医学 span | 85/447（19.0%） |
| 病例级审阅包 / speaker turns | 40 / 10,138 |

绿/黄/红采用 `demo_quantile_v0`，按当前批次约 70%/20%/10% 分档，`calibrated=false`。
9 个没有可用 CTC 对齐置信度的非空窗口被强制设为全红；空转写窗口也显式保留。该策略把
异常暴露给审阅者，不把缺失信号伪装成高置信。

## 运行成本

- confidence 推理覆盖 42,625.30 秒音频，转写 699.15 秒，RTF 0.0164；CUDA 峰值 allocated
  约 2.46 GiB；
- acoustic 5-best 转写 332.06 秒，RTF 0.00779，共得到 6,565 个 beam；
- Sortformer 40/40 成功、失败 0；全量声学映射为 67,348/75,228（89.53%），保守短空洞桥接
  后为 68,595/75,228（91.18%）。报告中的 88.9%/90.5% 是逐病例 macro 均值；
- 医学实体在线抽取使用逐条缓存和重试。一次读取超时与一次多 JSON 响应不会导致已完成记录
  丢失；解析器已支持提取首个完整 JSON，最终 1,442/1,442 完成；
- 完整病例 LLM 候选只生成 754 条 prompt，没有在 40 例上批量调用 API。当前候选来自 ASR
  原生 acoustic beams 和医学词表，避免把文本修复重新变成主线。

## 可展示产物

- 全量 HTML：`outputs/remote_programming_40/t061_all40/report/all40_report.html`；
- 40 行病例表：`outputs/remote_programming_40/t061_all40/report/all40_case_metrics.csv`；
- Markdown：`outputs/remote_programming_40/t061_all40/report/all40_results.md`；
- 图 1–5：病例时长、阶段覆盖、风险颜色分布、speaker 映射覆盖、n-best 可用性；
- 交互审阅入口：`outputs/remote_programming_40/t061_all40/review_pages/index.html`，链接 40 个
  独立页面；
- 固定 5 例代理质量报告：`outputs/remote_programming_40/t058_pilot5/report/pilot5_report.html`，
  包含 Proxy CER、CIPS、代理事实召回、风险分层、risk-coverage 和下游病例摘要稳定性图；
- 可提交的脱敏副本：`outputs/reporting_safe/chinese_all40_status/` 和
  `outputs/reporting_safe/chinese_pilot5/`。

40 个页面共有 447 个黄/红医学 span，其中 85 个有局部候选；每页支持接受 ASR、选择候选、
手工编辑、拒绝、无法判断、本地恢复和反馈 JSONL 导出。40 页共 80 个内联 JavaScript 块通过
Node 语法解析，索引包含 40 个病例链接。浏览器运行时仍不可用，因此本轮只完成静态/工程
验收；自动 QA feedback 只用于验证确定性回放，明确标记为非人工、非医生确认。

最终验证为整仓 `125 passed`、`ruff check .` 通过；5 张全量 SVG 均可作为 XML 解析，40 行
CSV、HTML、Markdown、40 个页面与索引均存在。临时本地 HTTP 服务在验收后已关闭。

## 鲁棒性指标口径

没有人工 reference 的 40 例采用过程鲁棒性指标，而不是伪造准确率：

- **异常显式率**：空转写、CTC 对齐失败、缺时间戳均进入全量统计；
- **风险分布与病例异质性**：逐例统计 green/yellow/red 和平均 confidence；
- **候选可用性**：多 beam 窗口覆盖、医学 span 局部候选覆盖；
- **可审阅性**：音频路径/绝对时间戳覆盖、病例页面覆盖、黄红医学审阅负载；
- **speaker 可用性**：声学映射覆盖与保守桥接后覆盖分开报告，不等同 speaker 准确率；
- **计算鲁棒性**：阶段成功率、RTF、峰值显存、失败/重试/缓存恢复。

固定 5 例 proxy 另外报告 CIPS（医学术语、否定、数字单位、侧别保持加权）、黄+红可检测错误
召回、审阅字符比例、ECE/Brier、risk-coverage/AURC，以及 noisy↔proxy 病例摘要事实稳定性。
两类证据严格分开：40 例回答“能否稳定运行与暴露风险”，5 例 proxy 只探索“风险信号是否与
代理误差、下游不稳定一致”。

## 仍待人工完成

1. 在可用浏览器中完成至少 1 例真实点击、回听和反馈下载；
2. 由医生/研究者生成真实 confirmed transcript，并记录操作、耗时和回听次数；
3. 固定 5 例制作听音频的独立人工 reference/gold；
4. 在人工 reference 上复算 CER、CIPS、ECE/Brier、risk-coverage、top-k/span 候选覆盖，并为
   病例整理建立人工 gold facts；
5. 没有人工 RTTM 前不报告 DER/JER；没有人工 reference/confirmed/gold 前不声称质量提升。
