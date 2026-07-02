# 数据目录说明

本目录用于存放研究数据。默认情况下，真实数据和中间结果不提交到 Git。

```text
raw/          原始下载或拷贝的数据
external/     外部工具或第三方处理结果
interim/      清洗、对齐、标注过程中的中间文件
processed/    实验用统一格式数据
```

推荐统一样本格式为 JSONL，每行一个样本，例如：

```json
{
  "sample_id": "demo_001",
  "dataset": "aci_bench",
  "split": "dev",
  "clean_transcript": "...",
  "noisy_transcript": "...",
  "repaired_transcript": "...",
  "error_tags": ["speaker_confusion", "medical_term_error"],
  "notes": "示例，不含真实患者隐私。"
}
```
