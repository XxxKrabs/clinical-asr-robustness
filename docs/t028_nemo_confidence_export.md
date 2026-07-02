# T028 NeMo entropy confidence 导出适配脚本

更新时间：2026-07-02

T028 已新增项目侧批量导出入口：

- 脚本：`scripts/export_nemo_asr_confidence.py`
- 适配模块：`src/clinical_asr_robustness/nemo_confidence_export.py`
- 单元测试：`tests/test_nemo_confidence_export.py`

## 目标

从 T025 的 PriMock57 channel-level manifest 批量运行 project 内 NeMo 模型，导出符合 T027 schema 的 ASR confidence JSONL。每行对应一路音频，包含：

- ASR noisy transcript；
- word timestamp 与 `word_confidence`；
- 由 word 派生的 segment confidence；
- 连续黄/红/未知置信度词合并得到的 `uncertain_spans`；
- NeMo entropy confidence 配置、解码配置、模型路径和运行环境；
- timestamp/confidence 数量不一致时的 alignment 诊断。

脚本不读取、不 import、不引用 project 外部 `Speech-main`。运行前会优先把 `third_party/speech_main/` 放入 `sys.path`，并检查 `nemo` / `nemo.collections.asr` 模块路径是否位于 project 内。

## 可复现命令

在 WSL 中进入项目目录后运行：

```bash
cd /mnt/d/Chasingfordream/内地部分/文书合集/清华大学神经调控/project
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py --limit 1
```

默认输入：

- manifest：`data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl`
- 权重：`data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`

默认输出：

- `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence.jsonl`
- `outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_run.json`

`outputs/` 默认被 `.gitignore` 忽略；ASR transcript 属于本地研究输出，不应提交。

## 常用参数

```bash
# 只跑 manifest 第 1 条
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py --record-index 1

# 跑指定 sample_id
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --sample-id primock57:day1_consultation01:patient

# 使用 min 作为 NeMo frame/token -> word confidence 聚合消融
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 1 --confidence-aggregation min

# 使用论文 entropy 方法的线性归一化（当前 demo 默认）
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 1 --confidence-method entropy --entropy-type tsallis --entropy-norm lin --confidence-alpha 0.33

# sanity check：使用 max probability confidence baseline
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 1 --confidence-method max_prob --confidence-alpha 1.0
```

当前默认 confidence 配置为 `entropy + tsallis + alpha=0.33 + entropy_norm=lin + aggregation=mean`。
T028 初版曾沿用 NeMo 默认 `entropy_norm=exp`，但在 PriMock57
`day1_consultation01:patient` 上 word confidence 最大仅约 0.075、全 red；改用论文同样
支持的 `lin` 归一化后，词级均值约 0.912，适合当前交互 demo。`exp` 仍可通过
`--entropy-norm exp` 复现并作为消融。

默认颜色阈值沿用 T027：

- green：`confidence >= 0.80`
- yellow：`0.50 <= confidence < 0.80`
- red：`confidence < 0.50`

可用 `--green-min`、`--yellow-min` 调整。

## 对齐规则

导出脚本严格按 T027 的策略处理 NeMo 数组长度不一致：

1. 以 `asr_transcript.split()` 的 ASR 输出词作为主锚点；
2. `asr_words` 长度等于 ASR 输出词数；
3. 同 index 读取 `timestamp["word"]` 与 `word_confidence`；
4. 多出来的 timestamp/confidence 写入 `alignment.dropped_extra_*`；
5. 缺失 timestamp/confidence 的词仍保留，并在 `alignment_status` 与 `alignment.missing_*_word_indices` 中标记。

这能覆盖 T026 已观察到的情况：word timestamp 比 `word_confidence` 多 1。

## 当前验证

已新增无需 NeMo/GPU 的单元测试，覆盖：

- fake Hypothesis 到 `ASRConfidenceRecord` 的转换；
- timestamp 多余、confidence 缺失时的 alignment 诊断；
- word confidence 绿/黄/红分级；
- segment 派生与 uncertain span 合并；
- ASR confidence JSONL roundtrip。
- confidence distribution summary 与可切换 `entropy` / `max_prob` 配置。

推荐验证命令：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_nemo_confidence_export.py --basetemp=.pytest_tmp
```

如需完整回归：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
```

本次 T028 实跑验证还执行了：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/export_nemo_asr_confidence.py \
  --limit 2 \
  --output-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl \
  --run-config-json outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_limit2_run.json
```

结构化结果摘要：

- run summary：`status == "ok"`，`records_written == 2`，未内联 reference 正文，外部 `Speech-main` 路径为空；
- confidence distribution：1145 个 word confidence，1031 green、114 yellow、0 red；均值约 0.884，`low_scale_warning=false`；
- `primock57:day1_consultation01:doctor`：738 个 ASR words、19 个 derived segments、67 个 yellow uncertain spans，word timestamps/confidence 均为 738；
- `primock57:day1_consultation01:patient`：407 个 ASR words、11 个 derived segments、7 个 yellow uncertain spans，word timestamps 408、word confidence 407，记录 dropped extra timestamp 1。
