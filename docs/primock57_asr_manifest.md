# PriMock57 ASR 输入 manifest 说明

更新时间：2026-07-02

本文记录 T025 的产出：为第一批 PriMock57 样本生成 ASR 输入 manifest 与 reference 对齐方案。该 manifest 只保存文件指针、音频头信息、TextGrid 结构统计和许可信息，不保存人工转录、医生 note、presenting complaint 或音频正文。

## 本地数据与许可

- 数据根目录：`data/external/primock57/`
- 音频目录：`data/external/primock57/audio/`
- reference TextGrid：`data/external/primock57/transcripts/`
- 医生 notes：`data/external/primock57/notes/`
- 许可：Creative Commons Attribution 4.0 International，SPDX 记作 `CC-BY-4.0`
- 许可文件：`data/external/primock57/LICENSE.md`
- 引用信息：`data/external/primock57/README.md`

PriMock57 是模拟初级保健问诊，不是真实患者数据；但项目仍按受限研究数据处理，默认不提交源音频、TextGrid、notes 正文或派生正文。

## 生成命令

```powershell
python scripts\build_primock57_asr_manifest.py
```

默认选择稳定排序前 5 条 consultation：

- `day1_consultation01`
- `day1_consultation02`
- `day1_consultation03`
- `day1_consultation04`
- `day1_consultation05`

默认输出位于 `data/interim/primock57/manifests/`，该目录被 `.gitignore` 忽略：

- `primock57_consultation_seed_manifest.jsonl`：5 行 consultation 级 manifest；
- `primock57_nemo_asr_input_manifest.jsonl`：10 行 channel 级 ASR 输入 manifest，每条 consultation 包含 doctor/patient 两路；
- `primock57_asr_manifest_summary.json`：不含正文的聚合摘要。

## 字段约定

consultation 级 manifest 每行包含：

- `sample_id`、`consultation_id`、`day`、`consultation`；
- `channels.doctor` / `channels.patient`：
  - `audio_path`；
  - `reference_textgrid_path`；
  - wav 头信息：duration、sample rate、channel count、sample width、frame count；
  - TextGrid 结构统计：duration、utterance interval 数、非空 interval 数、`<UNSURE>` / `<UNIN/>` 标签计数；
- `notes_pointer`：仅记录 JSON 文件路径和字段名，不写入字段值；
- `license`：CC BY 4.0 信息和许可文件指针；
- `reference_alignment_plan`：双路 ASR 与 TextGrid reference 的对齐方案；
- `checks`：源文件存在性、是否误写入正文等检查结果。

NeMo channel 级 manifest 每行包含：

- `audio_filepath`
- `duration`
- `text`: 空字符串，仅作 NeMo manifest 占位
- `text_is_placeholder`: `true`
- `sample_id`
- `consultation_sample_id`
- `source_channel`
- `reference_textgrid_path`
- `notes_path`
- `reference_text_included`: `false`

## Reference 对齐方案

T025 不运行 ASR，只固定输入与对齐规则：

1. 对同一 consultation 的 doctor/patient 两个 wav 分别运行 ASR；
2. ASR 输出必须保留 `source_channel`，后续 word/segment 时间戳先在各自通道内解释；
3. doctor/patient 的 TextGrid 作为 clean/reference 指针，不当作 noisy transcript；
4. reference 对齐时先在各通道内按时间戳对齐 ASR 与 TextGrid interval，再把双路结果按 `start_sec` 合并为 conversation 视图；
5. 如果两路音频或 TextGrid 时间轴存在细小偏差，优先保留通道标签并在后续评估脚本中设置容差，不在 manifest 阶段强行修改源时间戳。

当前生成的 summary 显示：

- 可完整配对的 consultation：57 条；
- 当前选取：5 条 consultation / 10 路音频；
- 总 channel 音频时长：5507.760 秒；
- TextGrid utterance interval 总数：1184；
- 当前样本音频与 TextGrid 最大 duration delta：0.000 秒；
- `no_inline_reference_text`、`no_inline_notes_text` 均为 `true`。

## 验证

已新增测试：

```powershell
python -m pytest tests\test_primock57_asr_manifest.py --basetemp=.pytest_tmp
```

测试覆盖：

- fake PriMock57 数据可生成 consultation/channel 两级 manifest；
- manifest 不包含 TextGrid reference 正文、presenting complaint、note 或 highlights 正文；
- NeMo manifest 的 `text` 为空占位；
- 5 条以内样本满足 T025 的 3-5 条 consultation 验收范围。

## 后续衔接

下一步进入 T026：使用 project 内部权重 `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`，从 `primock57_nemo_asr_input_manifest.jsonl` 中选 1 路音频做 NeMo smoke test，验证能返回文本、时间戳和 confidence，并确认不读取外部 `Speech-main` 路径。
