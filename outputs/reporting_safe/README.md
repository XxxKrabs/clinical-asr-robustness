# 脱敏汇报输出包

本目录是 `outputs/` 中唯一允许提交 Git 的子目录，只保存聚合指标、匿名病例编号、静态图表和
不含病例正文的汇总页面。所有材料均为研究输出，不构成临床建议。

## 当前内容

- `chinese_pilot5/`：固定中文 5 例代理参考 pilot 的逐例指标 CSV、汇总 Markdown/HTML 和
  5 张 SVG 图表。代理参考不是人工 reference，相关指标不得表述为正式临床质量结论。
- `chinese_all40_status/`：40 例源样本的工程状态总览。当前实际 ASR、n-best 和 diarization
  只覆盖 5/40；该目录不能作为“40 例已完成”的证据。
- `week1/`：早期 ASR confidence review 流程总览图，不含转写正文或患者身份。

## 明确排除

以下内容继续留在 Git 忽略目录，不得加入本目录：

- 原始音频、模型权重、frame distribution 和大体积中间产物；
- ASR/noisy/reference/confirmed transcript、病例摘要正文和交互审阅 HTML；
- LLM prompt/response、医学实体逐例记录、反馈 JSONL、RTTM 和运行日志；
- 真实姓名、联系方式、身份证号、原始文件名或其他可识别信息。

## 来源

- 中文 5 例：`outputs/remote_programming_40/t058_pilot5/report/`
- 40 例工程状态：`outputs/remote_programming_40/t061_all40/report_qa/`
- Week 1 总览：`outputs/reports/week1_asr_confidence_review_summary.png`

同步日期：2026-07-15。
