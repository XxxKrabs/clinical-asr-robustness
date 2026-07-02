# T026 NeMo ASR smoke test 记录

更新时间：2026-07-02

本文记录 T026 的 project 内 smoke test 入口。T026 的验收目标是：使用 project 内 FastConformer CTC `.nemo` 权重，对 T025 生成的 1 路 PriMock57 channel 音频运行 NeMo ASR，并验证返回的 `Hypothesis` 至少包含：

- 非空 transcript；
- word/segment/char timestamps 中至少一种；
- `word_confidence`；
- `nemo` 运行路径来自 `project/third_party/speech_main/`，且未引用 project 外部 `Speech-main`。

## 可复现命令

在 WSL 中进入项目目录后运行：

```bash
cd /mnt/d/Chasingfordream/内地部分/文书合集/清华大学神经调控/project
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_nemo_asr_smoke_test.py
```

默认输入：

- manifest：`data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl`
- 权重：`data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`
- 样本：manifest 第 0 条，即 `primock57:day1_consultation01:doctor`

默认输出：

- `outputs/primock57/t026_nemo_smoke_test/t026_nemo_smoke_test_result.json`

该输出目录默认被 `.gitignore` 忽略。JSON 结果中会保存 ASR transcript 和局部 timestamp/confidence preview，仅用于本地研究记录，不应提交。

## 当前执行状态

T026 已在 WSL `clinical-asr` 环境中通过。执行时使用 project 内路径：

- 权重：`data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`
- NeMo 代码：`third_party/speech_main/`
- 音频样本：`primock57:day1_consultation01:patient`
- 音频时长：457.86 秒
- 实际命令：`/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_nemo_asr_smoke_test.py --record-index 1`
- 输出：`outputs/primock57/t026_nemo_smoke_test/t026_nemo_smoke_test_result.json`

结果摘要：

| 字段 | 结果 |
|---|---|
| `status` | `ok` |
| ASR 模型类 | `nemo.collections.asr.models.ctc_bpe_models.EncDecCTCModelBPE` |
| 设备 | `cuda` |
| PyTorch | `2.11.0+cu126` |
| CUDA 可用 | `true` |
| transcript word count | 407 |
| word timestamp count | 408 |
| segment timestamp count | 1 |
| word confidence count | 407 |
| `validation.has_transcript_text` | `true` |
| `validation.has_timestamps` | `true` |
| `validation.has_word_confidence` | `true` |
| project 外部 `Speech-main` 路径 | 空 |
| `nemo` 路径来自 project 内 | `true, true` |

注意：本次 `word_timestamp_count` 比 `word_confidence_count` 多 1。T026 只要求验证 transcript、timestamp 与 word confidence 能返回，因此不阻塞；后续 T027/T028 设计正式 schema/导出脚本时，需要明确 word timestamp 与 word confidence 的对齐和裁剪规则。

## 脚本行为说明

`scripts/run_nemo_asr_smoke_test.py` 会：

1. 读取 T025 channel-level ASR manifest；
2. 检查音频与 project 内 `.nemo` 权重存在；
3. 检查 `nemo` / `nemo.collections.asr` 模块路径来自 `project/third_party/speech_main/`；
4. 打开 CTC greedy 解码的 `compute_timestamps` 与 entropy word confidence；
5. 使用 `TranscribeConfig(use_lhotse=False, return_hypotheses=True, timestamps=True)` 运行 1 路音频；
6. 将 transcript、timestamp 计数、confidence 计数、运行路径和验证布尔值写入本地 JSON。
