# 输出目录说明

本目录用于保存实验输出、图表和模型结果。默认不提交到 Git。

唯一例外是 `reporting_safe/`：该目录只保存经过筛选的脱敏汇报材料，可提交到远程仓库。
其中不得包含原始音频、逐例转写、病例正文、LLM prompt/response、医生反馈日志、
confirmed transcript 或可识别身份信息。

建议按日期或实验名组织，例如：

```text
outputs/
  reporting_safe/                 可提交的脱敏聚合汇报材料
  2026-06-29_smoke_eval/
  speaker_repair_ablation/
  term_correction_v1/
```
