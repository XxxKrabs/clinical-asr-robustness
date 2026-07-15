# 数据目录说明

本目录用于存放研究数据。默认情况下，真实数据和中间结果不提交到 Git。

```text
raw/          原始下载或拷贝的数据
external/     外部工具或第三方处理结果
interim/      清洗、对齐、标注过程中的中间文件
processed/    实验用统一格式数据
```

当前中文 40 例的本地归档约定：

```text
raw/remote_programming_40/          原始音频、多路自动转录和数据包说明
external/remote_programming_40/     外部模型生成的 Qwen 自动病历等派生 baseline
external/asr_models/nemo/           NeMo/Parakeet 本地模型 artifact
interim/remote_programming_40/      音频转换、VAD、manifest、对齐和标注中间结果
processed/remote_programming_40/    统一 JSONL、ASR/confirmed/reference 对齐数据
```

以上目录中的真实数据、派生文本和模型大文件均不提交 Git。现有自动转录/自动病历不得改名
或解释为人工 reference、真实 confirmed transcript 或下游 gold。

当前已冻结的匿名技术清单位于
`interim/remote_programming_40/manifests/remote_programming_40_asr_manifest.jsonl`；只含匿名
ID、相对路径、格式、时长和校验信息，不含转写/病例正文。中文模型统一存放在
`external/asr_models/nemo/Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo`；历史英文
PriMock57 模型继续保留在同目录的 `stt_en_fastconformer_ctc_large.nemo`，两者由数据集路由
选择，不覆盖彼此。

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
