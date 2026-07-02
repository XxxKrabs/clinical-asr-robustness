# T005 ACI-Bench noisy 来源与错误类型分析说明

本说明记录 T005 的最小落地版本，供后续 T018/T006/T008 复用。

## 已确认选择

- 错误类型：`substitution` / `deletion` / `insertion`
- 评价指标：`WER` + `MC-WER`

## V0 定义

`WER` 使用 token 级编辑距离：

```text
WER = (substitution + deletion + insertion) / reference_token_count
```

`MC-WER` 暂定义为 medical/clinical concept WER，即只统计命中医学/临床关键 token 的编辑错误：

```text
MC-WER = (MC-substitution + MC-deletion + MC-insertion) / MC-reference_token_count
```

V0 的 medical/clinical concept token 由轻量启发式识别：

- 内置医学/临床关键词；
- 常见医学后缀，如 `-itis`、`-emia`、`-oscopy`、`-ectomy`；
- 否定和极性词，如 `no`、`not`、`denies`、`without`；
- 数字 token，用于覆盖剂量、年龄、日期、频次等临床关键信息。

该定义是第一阶段可解释基线，后续可替换为医学词表、实体识别器或任务特定 clinical concept 标注。

## 输入与输出

输入：

- `data/processed/aci_bench/v0_note_generation/v0_note_generation_pairs.jsonl`

脚本：

- `scripts/analyze_aci_bench_noisy_errors.py`

默认输出：

- `outputs/aci_bench/t005_noisy_error_analysis/aci_bench_t005_error_annotations.jsonl`
- `outputs/aci_bench/t005_noisy_error_analysis/aci_bench_t005_error_summary.json`

其中 annotation JSONL 含局部 transcript span，仅用于本地研究实验，默认不提交 Git；summary JSON 不含 transcript 正文，可用于汇报聚合结果。

## 轨道解释

- `noise_harm`：比较 VirtScribe `clean` / `humantrans` 与 `noisy` / `asr`，用于估计 ASR noisy transcript 的伤害。
- `repair_gain`：比较 ACI `oracle_repaired` / `asrcorr` 与 `noisy` / `asr`，用于记录数据集自带 oracle 修复痕迹。

## 本次运行摘要

2026-06-30 默认参数运行结果：

- paired records：105
- `noise_harm`：28
- `repair_gain`：77
- edit spans：3360
- medical concept edit spans：325
- overall micro WER：0.0321
- overall micro MC-WER：0.0626
- `noise_harm` micro WER：0.1220
- `noise_harm` micro MC-WER：0.2124
- `repair_gain` micro WER：0.0003
- `repair_gain` micro MC-WER：0.0012

解释：第一阶段真正体现 noisy 差异的主要是 VirtScribe `noise_harm` 轨道；ACI `repair_gain` 轨道中的 `asr` 与 `asrcorr` 在当前本地切片上差异很小，更适合作为 oracle repaired 对照结构，而不是丰富错误类型来源。

## 后续使用建议

- T018 候选生成 baseline 可优先读取 annotation JSONL 中 `medical_concept_hit = true` 的 span。
- T006 生成 repaired transcript 时，可先用 reference alignment span 模拟 oracle repair，再替换为真实规则/词表/LLM 候选。
- T008 可复用 `src/clinical_asr_robustness/error_analysis.py` 计算 WER、MC-WER 和错误类型统计。
- 若后续需要更丰富的医学术语错误、药名错误或否定遗漏案例，建议在 T018/T006 前补充轻量合成扰动；但应保留 ACI-Bench 自带 noisy/asr 作为真实噪声基础。
