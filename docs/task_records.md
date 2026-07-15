# 项目任务记录归档

更新时间：2026-07-09

本文档用于存放从 `docs/todo.md` 迁出的历史记录、较完整任务流水和早期路线演化。新对话默认只读 `docs/todo.md`；只有需要追溯某个决策来源、历史产出或失败原因时，才阅读本文件。

## 维护规则

- `docs/todo.md` 只保留当前焦点、下一步和少量最近历史。
- 本文件追加较完整的任务记录，包括完成内容、修改文件、验证、遗留问题和建议下一步。
- 完成较完整任务后，两个文件都要更新：`todo.md` 更新当前状态，本文件追加历史记录。
- 不记录真实患者隐私、未脱敏病例正文、本地密钥或受限数据细节。

## 路线演化摘要

### 2026-06-29 / 2026-06-30：早期规划

- 初始目标是评估临床 ASR noisy transcript 对病例信息整理任务的影响。
- 早期曾考虑 clean/noisy/repaired 三版本对照、文本 repair、下游任务、错误分析、可视化等较宽范围。
- 当时的合理收束建议是先跑通一个小闭环，再扩展 benchmark、repair 方法和错误类型。
- 5 个 benchmark 不应第一阶段同时接入；优先选一个文本友好数据集或一个含音频数据集。

### 2026-06-30：文本 repair 阶段

- 用户一度确认第一阶段先从 ACI-Bench 文本 repair 入手，不优先推进音频 ASR 闭环。
- 因此接入 ACI-Bench，建立 paired manifest、V0 note generation processed JSONL、错误分析和 repair schema。
- 该阶段产出仍有价值：可作为文本侧历史资产、界面假数据、下游评估参考和 repair 辅助模块。

### 2026-07-01 起：ASR 置信度主线

- 用户提出关键调整：置信度主要放在 ASR 输出层，而不是 noisy transcript → repair 的文本修复层。
- 当前主线变为：音频 → ASR → noisy transcript + ASR 置信度 → 医生实时交互确认 → confirmed transcript → 下游鲁棒性评估。
- 文本 repair、规则/词表增强、LLM 候选和反馈微调暂时降级为辅助扩展。

## 任务索引归档

| 任务编号 | 状态 | 历史说明 |
|---|---|---|
| T000 | 已完成 | 建立 `docs/todo.md` 与项目交接机制。 |
| T001 | 暂缓 | 全局 clean/noisy/repaired schema 暂缓；后续按子任务维护轻量切片约定。 |
| T002 | 已完成 | 历史任务：选择 2026-06-30 文本 repair 最小闭环路线；7.1 后不再是近期主线。 |
| T003 | 已完成 | 生成 ACI-Bench paired manifest 与种子切片。 |
| T004 | 已完成 | 跑通 manifest 基础读取与校验脚本。 |
| T005 | 已完成 | 完成 ACI-Bench noisy 来源与错误类型分析，指标为 WER + MC-WER。 |
| T006 | 暂缓 | 第一版文本 repair baseline；等 ASR 置信度闭环跑通后再考虑。 |
| T007/T008 | 未开始 | 下游任务与鲁棒性/交互指标实现，下一阶段接入。 |
| T009/T010/T012 | 未开始 | 文献调研、实验记录模板、错误分析/消融/可视化，排在 ASR 输出层之后。 |
| T013 | 已完成 | 梳理 ACI-Bench 子任务-数据集切片矩阵。 |
| T014 | 已完成 | 接入 ACI-Bench 第一阶段本地数据文件。 |
| T015 | 已完成 | 生成 V0 note generation processed JSONL。 |
| T016 | 已完成 | 历史任务：按文本 repair 方向重构项目定位文档；已被 7.1 主线取代。 |
| T017 | 已完成 | 设计交互式 repair 数据结构，后续作为辅助模块保留。 |
| T018 | 暂缓 | 文本 repair 候选生成与置信度 baseline；仅作为 ASR top-k 不足时的扩展。 |
| T019 | 未开始 | 医生实时审阅与前端原型流程。 |
| T020 | 已完成 | 记录 2026-07-01 ASR 置信度主线调整。 |
| T021 | 未开始 | 设计 ASR confidence / interaction 数据结构。 |
| T022 | 进行中 | 选择第一批音频样本与 ASR 输出方案；PriMock57 路线已确认并由 T025/T026 推进。 |
| T023 | 未开始 | 设计 ASR 置信度校准与交互指标。 |
| T024 | 已完成 | 梳理 NeMo entropy confidence 代码与适配风险。 |
| T025 | 已完成 | 核验 PriMock57 ASR 输入 manifest 与 reference 对齐方案。 |
| T026 | 已完成 | 确定 WSL/NeMo ASR 环境并完成 1 路 PriMock57 音频 smoke test。 |
| T027 | 已完成 | 设计项目侧 ASR confidence JSONL/schema，包含 Pydantic schema、JSONL 读写、文档和测试。 |
| T028 | 已完成 | 实现 NeMo entropy confidence 导出适配脚本；已实跑 2 路 PriMock57 音频并生成项目 schema JSONL。 |
| T029 | 已完成 | 实现 ASR n-best/top-k 候选抽取策略；支持 sequence-level n-best 与 uncertain span 对齐。 |
| T030 | 已完成 | 生成绿/黄/红可审阅样本包，包含 JSONL、span CSV 和 HTML 预览。 |
| T031 | 已完成初评 | 已实现并运行 ASR noisy / confidence / top-k 初评；后续可扩样本和做阈值/候选消融。 |
| T032 | 已完成 | 已整理 ASR 输出层最小闭环实验记录，补齐模拟 T035 回放和不依赖外部 `Speech-main` 证据。 |
| T033 | 已完成 | 迁移 `Speech-main` 必要文件与权重到 project。 |
| T034 | 已完成 | 精简 `docs/todo.md`、新增 `docs/task_records.md`，并记录 WSL 沙箱申请方式。 |
| T035 | 已完成 | 医生/模拟审阅者反馈日志与 `confirmed_transcript` 回放生成。 |
| T036 | 已完成 | 静态/轻量医生审阅 HTML demo，支持高亮、候选选择和反馈 JSONL 下载。 |
| T037 | 已完成 | 生成/接入真实 NeMo sequence-level n-best 候选，并重跑 T029/T030/T036 审阅 demo。 |
| T038 | 已完成 | 医学实体优先 ASR 审阅范围 gating：LLM 抽取医学实体，只让医学实体保留颜色并进入候选/反馈流程。 |

## 完整任务记录

### 2026-07-07：完成 T032 ASR 输出层最小闭环实验记录

- 背景：`docs/todo.md` 中 T032 仍要求把 ASR 输出层最小闭环整理成正式实验记录，并补齐 T035 反馈回放与“不依赖外部 Speech-main”证据。
- 完成：
  - 新增 `docs/t032_asr_output_min_loop.md`，记录 `T028 → T037 → T038 → T029 → T030/T036 → T035 → T031` 的输入、输出、命令、指标、局限和下一步；
  - 汇总 3 条 PriMock57 channel-level record 的 T028/T037/T038/T029/T036/T031/T035 run summary；
  - 明确 noisy ASR 质量解释：micro WER 0.3405、micro MC-WER 0.2526，deletion 453 高于 substitution 317 与 insertion 38；
  - 明确 confidence 现状：yellow 错误率 0.4785 高于 green 0.1543，但 green 仍有错误、当前无 red，阈值不能视作临床级校准；
  - 明确医学实体 gating 和 top-k 的不足：医学概念错误 token 覆盖 2/9，uncertain-span 覆盖 0/9，span-level top-k exact coverage 0/3；
  - 使用 3 条模拟 `accept_asr` feedback 跑通 T035 回放，生成 `outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.simulated_accept_asr.jsonl` 和对应 run summary；
  - 记录该 T035 只是模拟审阅者接受 ASR 原文，证明回放机制可运行，不代表真实医生确认或质量改善；
  - 补充不依赖外部 `Speech-main` 的证据：T028/T037 summary 中 `nemo_paths_inside_project=true` 且 `external_speech_main_paths=[]`，模型权重来自 `data/external/asr_models/nemo/`。
- 同步修复：
  - T035 读取 Windows 手工保存的反馈 JSONL 时遇到 UTF-8 BOM 会解析失败；
  - 已将 `read_feedback_entries_jsonl()` 读取编码改为 `utf-8-sig`，保持写出仍为纯 UTF-8；
  - 新增 `test_feedback_jsonl_accepts_utf8_bom()`。
- 修改文件：
  - `docs/t032_asr_output_min_loop.md`
  - `docs/todo.md`
  - `docs/task_records.md`
  - `src/clinical_asr_robustness/review_workflow.py`
  - `tests/test_review_workflow.py`
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/apply_asr_review_feedback.py ...`：T035 `status=ok`，`feedback_entries_read=3`，`confirmed_records=3`，`missing_feedback_spans=0`，`unresolved_spans=0`；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_review_workflow.py --basetemp=.pytest_tmp`：6 passed；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/review_workflow.py tests/test_review_workflow.py`：All checks passed。
- 遗留问题：
  - 尚无真实医生反馈，T035 confirmed transcript 只是模拟 `accept_asr`；
  - span-level candidate 覆盖不足，后续需改进候选生成；
  - 下一步建议推进 T019/T023 医生审阅成本指标，或 T007/T008 下游病例信息整理鲁棒性评估。

### 2026-07-07：完成 T031 ASR noisy / confidence / top-k 初评

- 背景：用户指出当前已经跑通初步完整流程，但不知道生成的 noisy transcript 相对 ground truth / clean transcript 效果如何；检查 `docs/todo.md` 后确认下一步正是 P0 的 T031 评估层。
- 完成：
  - 新增 `src/clinical_asr_robustness/asr_quality_evaluation.py`：
    - 从 PriMock57 TextGrid reference 中抽取 clean transcript；
    - 清理 `<UNIN/>`，保留 `<UNSURE>...</UNSURE>` 中的可读内容；
    - 复用 `error_analysis.analyze_transcript_pair()` 计算 WER / MC-WER / substitution / deletion / insertion；
    - 将 ASR hypothesis token 映射回 `asr_words`，统计 green/yellow/red/unknown 分桶错误率；
    - 计算 token correctness probability 的 ECE、NCE、Brier score；
    - 统计医学概念错误被 T038 医学实体 gating 和 uncertain span 覆盖的比例；
    - 评估 span-level top-k 是否精确覆盖 reference span，并评估 sequence-level n-best oracle WER 改善。
  - 新增 `scripts/evaluate_asr_quality.py`：
    - 默认读取 `outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl`；
    - 输出 annotation JSONL、summary JSON 和 run config 到 `outputs/primock57/t031_asr_quality_evaluation/`；
    - summary 不写入完整 transcript 正文；annotation JSONL 含局部 edit span / candidate span，默认仅本地研究排错。
  - 新增 `tests/test_asr_quality_evaluation.py`，覆盖 TextGrid reference 抽取、单条 record 的 WER/MC-WER/confidence/top-k 评估和 summary 聚合。
  - 新增文档 `docs/t031_asr_quality_evaluation.md`，并更新 `scripts/README.md`、`docs/todo.md`、`docs/task_records.md`。
- 本地初评结果：
  - 默认输入共 3 条 channel-level record：`day1_consultation01` doctor/patient 和 `day1_consultation02` doctor；
  - micro WER：0.3405；macro WER：0.3334；
  - micro MC-WER：0.2526；macro MC-WER：0.2562；
  - error counts：substitution 317、deletion 453、insertion 38，deletion 偏多；
  - confidence 分桶：green 1795 tokens、错误率 0.1543；yellow 163 tokens、错误率 0.4785；red/unknown 为 0；
  - macro ECE：0.0651；macro NCE：0.0580；macro Brier score：0.1358；
  - 医学概念错误 token 共 9 个，其中 2 个被标为医学实体，0 个进入 uncertain span；
  - span-level top-k：3 个 uncertain span，0 个有 span-level candidate，reference exact coverage 为 0/3；
  - sequence-level n-best：15 个候选，1 条 record 的 oracle WER 有改善，但 mean oracle WER improvement 仅 0.00068。
- 结论：
  - 当前 noisy transcript 质量已可量化，小样本整体 WER 约 34%、MC-WER 约 25%，足以影响下游病例整理；
  - ASR confidence 有预警信号：yellow 错误率显著高于 green；
  - 但 green 中仍有错误，不能把当前阈值当作临床级“无需审阅”标准；
  - 当前医学实体 gating 对真实医学概念错误覆盖不足，span-level top-k 候选也不足；
  - 后续 T032 应把 T031 结果纳入 ASR 输出层最小闭环实验记录，并优先改进医学实体 false negative 与候选生成。
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_asr_quality_evaluation.py --basetemp=.pytest_tmp`：3 passed；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_asr_quality.py`：成功生成 T031 outputs；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：45 passed；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`：All checks passed。

### 2026-07-02：完成 T037 真实 NeMo n-best 候选接入并重跑审阅 demo

- 完成：新增项目侧真实 ASR n-best 导出链路，使用 project 内 NeMo FastConformer CTC 模型对 PriMock57 音频做 `beam_batch` 解码，输出 sequence-level beams JSONL；随后调用 T029 把 n-best 对齐到 uncertain spans，并重跑 T030/T036，使 HTML demo 中真正出现可选 ASR 候选。
- 修改文件：`src/clinical_asr_robustness/nemo_nbest_export.py`、`scripts/export_nemo_asr_nbest.py`、`docs/t037_nemo_asr_nbest_demo.md`、`tests/test_nemo_nbest_export.py`、`src/clinical_asr_robustness/asr_nbest_candidates.py`、`tests/test_asr_nbest_candidates.py`、`docs/todo.md`、`docs/task_records.md`。
- 关键实现：T037 CLI 默认使用 `beam_strategy=beam_batch`、`beam_size=5`、`max_beams=5`、`ngram_lm_model=None`，避免 NeMo 普通 `strategy=beam` 默认依赖 KenLM 的问题；beam 输出只用于 candidates，不混入 T028 greedy entropy confidence。
- NeMo 适配细节：首次尝试 `TranscribeConfig(return_hypotheses=True)` 时触发 NeMo `ctc_models._transcribe_output_processing` 对 n-best list 的 shape 假设，报 `AttributeError("'list' object has no attribute 'y_sequence'")`；已改为 `TranscribeConfig(return_hypotheses=False)`，同时底层 decoder 保持 `beam.return_best_hypothesis=False`，可稳定返回 n-best 文本和分数。
- 同步修复：T029 二次规整 `SequenceNBestItem` 时原先会把 source 覆盖为默认 `nemo_beam`；已补充对 `SequenceNBestItem` 的保源处理，并加测试确认 T037 的 `nemo_beam_batch` 来源能保留下来。
- 本地运行产出：
  - T037 n-best：`outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl` 与 `t037_nemo_asr_nbest_limit2_run.json`；
  - T029 候选：`outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates_limit2.jsonl` 与 `t029_asr_nbest_candidates_limit2_run.json`；
  - T030 审阅样本：`outputs/primock57/t030_review_samples/`；
  - T036 HTML：`outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`。
- 验收结果：T037 `records_written=2`、`total_beams=10`、`records_with_unique_beam_variants=2`、`external_speech_main_paths=[]`；T029 `sequence_alternatives=10`、`span_alternatives=6`、`spans_with_alternatives=2`；T030/T036 均为 `spans_with_candidates=2`。
- 主干检查：截至 T037，用户第一周目标中的“音频数据 → ASR → noisy transcript + 置信度 → 医生交互选择 + 交互界面设计”已形成可运行闭环：T025/T028 负责音频与 ASR confidence，T037/T029 负责真实 n-best 候选，T030/T036 负责审阅样本和 HTML 交互，T035 负责反馈回放到 `confirmed_transcript`。未完成的是评估层：confidence 校准、top-k 覆盖率、医生确认成本和下游鲁棒性评估。
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`，结果 `33 passed`；
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`，结果 `All checks passed!`。
- 遗留问题：当前 T028 `limit2` 的 word confidence 全部落入红色，因此每一路音频被合并为一个长 uncertain span，T037 候选在 HTML 中可选但粒度偏长。T031/T032 应优先做 confidence 校准、span 拆分或聚合方式比较，再扩到 3-5 条 consultation。
- 建议下一步：推进 T031/T032，先用 reference 对齐报告 confidence 分桶错误率、top-k 覆盖率和失败案例，再把 T028→T037→T029→T030→T036→T035 串成第一批可复现实验记录。

### 2026-07-02：完成 T030/T035/T036 ASR 审阅样本、反馈回放与 HTML demo

- 完成：建立 ASR 输出层医生审阅 demo 的第一版代码链路：T030 从 ASR confidence record 生成绿/黄/红 review samples；T035 读取反馈日志并回放生成 `confirmed_transcript`；T036 生成单文件 HTML 审阅界面。
- 修改文件：`src/clinical_asr_robustness/review_workflow.py`、`scripts/build_asr_review_samples.py`、`scripts/apply_asr_review_feedback.py`、`scripts/build_doctor_review_demo_html.py`、`docs/t030_t035_t036_review_workflow.md`、`tests/test_review_workflow.py`、`docs/todo.md`、`docs/task_records.md`。
- T030 产出：`asr_review_sample/v1` JSONL、span-level CSV 和可选 HTML；样本包含 `words[]`、`uncertain_spans[]`、颜色等级、时间戳、confidence、span alternatives 和 review policy。
- T035 产出：`doctor_feedback_entry/v1` 与 `confirmed_transcript_record/v1`；支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`。其中 `reject`/`unable_to_judge` 会保留 ASR 原文但标记 unresolved，不声称已确认。
- T036 产出：HTML 展示 ASR transcript 的 green/yellow/red/unknown 高亮；点击 span 后显示候选、编辑框和动作表单；提交后浏览器下载 `doctor_feedback_log.jsonl`，并用 localStorage 临时保存。
- 安全边界：所有 schema/HTML 均保留 `research_use_only` 与“本记录仅用于研究评估，不构成临床建议”提示；文档明确不要写入真实患者隐私或未脱敏病例内容。
- 验证：`wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`，结果 `30 passed`；针对新增文件运行 `ruff check`，结果 `All checks passed`；全仓 `ruff check .` 通过。
- 本地示例输出：使用 `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl` 生成 T030 样本包和 T036 HTML；2 条 records、2 个 review spans。由于当前未提供 T029 n-best 候选输出，示例 run summary 中 `spans_with_candidates=0`。
- 遗留问题：HTML 仍是无后端的静态 demo，反馈日志需下载后手动放回 `outputs/` 再由 T035 回放；span 替换当前按 `asr_transcript.split()` 词序完成，后续若需要保留复杂标点、双路时间线或说话人 turn，应扩展为 segment/turn 级回放。
- 建议下一步：推进 T031/T032，用第一批 PriMock57 ASR 输出串起 T028→T029→T030→T036→T035，并用 reference 做 confidence 分桶错误率和 top-k 覆盖率初评。

### 2026-07-02：完成 T029 ASR n-best/top-k 候选抽取策略

- 完成：新增项目侧 n-best/top-k 候选抽取策略层，输入 T028 ASR confidence JSONL 和可选 sequence-level n-best JSONL，输出带 `asr_alternatives` 和 `uncertain_spans[].alternative_ids` 的 ASR confidence JSONL。
- 修改文件：`src/clinical_asr_robustness/asr_nbest_candidates.py`、`scripts/extract_asr_nbest_candidates.py`、`docs/t029_asr_nbest_candidates.md`、`tests/test_asr_nbest_candidates.py`、`docs/todo.md`、`docs/task_records.md`。
- 关键实现：`asr_nbest_candidates.py` 不依赖 NeMo/torch，支持字符串、dict、NeMo `beams` 风格 tuple/list、Hypothesis 风格对象和 `NBestHypotheses.n_best_hypotheses` 规整为 `SequenceNBestItem`。
- 对齐策略：先保存 `scope="sequence"` 候选，`alignment_method="sequence_nbest"`；再用 `difflib.SequenceMatcher` 将 sequence n-best 与 `asr_transcript.split()` 做词级 diff，裁剪到连续中/低置信度 `uncertain_spans`，写出 `scope="span"`、`alignment_method="sequence_nbest_diff"` 的候选。
- JSONL 输入格式：支持一行一条 record 的 `nbest` / `alternatives` / `beams` / `hypotheses` 字段，也支持一行一个候选；优先按 `record_id` 匹配，随后按 `sample_id` 匹配。
- CLI：`scripts/extract_asr_nbest_candidates.py` 默认输出到 `outputs/primock57/t029_asr_nbest_candidates/`，并写运行摘要 JSON；若输入 record 已有 `scope="sequence"` 候选，可省略外部 `--nbest-jsonl`。
- 验证：在 WSL `clinical-asr` 中运行 `/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_asr_nbest_candidates.py --basetemp=.pytest_tmp`，结果 `3 passed`。
- 遗留问题：当前是候选抽取/映射策略层；真实 NeMo beam 解码仍需作为上游生成 `beams` JSONL。若 uncertain span 覆盖整条长音频，span 候选也会偏长，后续 T030/T031 应结合阈值、segment 边界或最大 span 长度做审阅友好化。
- 建议下一步：推进 T030，消费 `asr_words`、`uncertain_spans` 和 `asr_alternatives` 生成绿/黄/红审阅样本 JSONL/CSV/HTML。

### 2026-07-02：完成 T028 NeMo entropy confidence 导出适配脚本

- 完成：新增项目侧 NeMo ASR confidence 批量导出脚本，能从 T025 PriMock57 channel manifest 读取音频指针，调用 project 内 NeMo/FastConformer CTC 权重，导出符合 T027 `ASRConfidenceRecord` schema 的 JSONL。
- 修改文件：`scripts/export_nemo_asr_confidence.py`、`src/clinical_asr_robustness/nemo_confidence_export.py`、`docs/t028_nemo_confidence_export.md`、`tests/test_nemo_confidence_export.py`、`docs/todo.md`、`docs/task_records.md`。
- 关键实现：`nemo_confidence_export.py` 不在顶层 import NeMo/torch，便于普通测试；真实脚本运行前优先使用 `third_party/speech_main/`，并检查 `nemo` / `nemo.collections.asr` 模块路径不来自 project 外部 `Speech-main`。
- 输出内容：ASR transcript、word timestamps、`word_confidence`、派生 segment confidence、连续黄/红/未知词合并得到的 `uncertain_spans`、模型/解码/置信度配置、运行环境和 alignment 诊断。
- 对齐规则：以 `asr_transcript.split()` 为主锚点；多余 timestamp/confidence 写入 `alignment.dropped_extra_*`；缺失项保留 ASR 输出词并标记 `alignment_status` 与 `alignment.missing_*_word_indices`。
- 实跑验证：在 WSL `clinical-asr` 中运行 `scripts/export_nemo_asr_confidence.py --limit 2`，输出 `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl` 和 `t028_nemo_asr_confidence_limit2_run.json`。run summary 为 `status == "ok"`；写出 2 条记录；未内联 reference 正文；外部 `Speech-main` 路径为空。
- 实跑摘要：`primock57:day1_consultation01:doctor` 生成 738 个 ASR words、19 个 derived segments、1 个 uncertain span，word timestamps/confidence 均为 738；`primock57:day1_consultation01:patient` 生成 407 个 ASR words、11 个 derived segments、1 个 uncertain span，word timestamps 408、word confidence 407、dropped extra timestamp 1。
- 测试验证：`wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_nemo_confidence_export.py --basetemp=.pytest_tmp` 通过，2 passed；全量 `pytest --basetemp=.pytest_tmp` 通过，22 passed；`ruff check .` 通过。
- 遗留问题：T028 只导出 best/greedy transcript + confidence；sequence-level n-best/top-k 候选尚未接入，需要 T029 继续实现并写入 `asr_alternatives`。
- 建议下一步：推进 T029，使用 beam n-best 输出 sequence-level alternatives，并把候选对齐到 T028 JSONL 中的连续低/中置信度 `uncertain_spans`。

### 2026-07-02：完成 T027 ASR confidence JSONL/schema

- 完成：新增项目侧 ASR confidence JSONL/Pydantic schema，覆盖 `asr_words`、`asr_segments`、`uncertain_spans`、`asr_alternatives`、模型信息、解码配置、置信度配置和 timestamp/confidence 对齐诊断。
- 修改文件：`src/clinical_asr_robustness/asr_confidence.py`、`docs/asr_confidence_schema.md`、`tests/test_asr_confidence_schema.py`、`docs/todo.md`、`docs/task_records.md`。
- 核心规则：正式导出时以 `asr_transcript.split()` 得到的 ASR 输出词序为锚点；若 `word timestamp` 或 `word_confidence` 数量更多，不伪造额外词，而是写入 `alignment.dropped_extra_word_timestamps` / `alignment.dropped_extra_word_confidences`；若某个输出词缺少 timestamp 或 confidence，则保留该词并标记 `alignment_status`。
- 安全约束：ASR confidence JSONL 只保存 reference 文件指针，不内联人工 reference transcript 正文；schema 会拒绝 `reference_text_included=true`。
- 验证：`wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_asr_confidence_schema.py --basetemp=.pytest_tmp` 通过，4 passed；`wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/asr_confidence.py tests/test_asr_confidence_schema.py` 通过；全量 `pytest --basetemp=.pytest_tmp` 通过，20 passed。
- 遗留问题：T027 只定义 schema，不实际运行 NeMo 批量导出；T028 需要把 T026 smoke test 的 NeMo Hypothesis 适配成 `ASRConfidenceRecord` JSONL。
- 建议下一步：开始 T028，实现 NeMo entropy confidence 导出脚本，从 PriMock57 manifest 批量输出 ASR transcript、word/segment confidence、timestamps 和运行配置 JSONL。

### 2026-07-02：精简 TODO、建立历史归档并记录 WSL 沙箱调用

- 完成：将 `docs/todo.md` 从历史流水账改为短入口；新增 `docs/task_records.md` 存放历史记录；在 WSL 环境文档和项目说明中补充 Codex 沙箱授权建议。
- 修改文件：`docs/todo.md`、`docs/task_records.md`、`docs/wsl_environment.md`、`AGENTS.md`、`README.md`。
- 验证：在 Codex 中用提升权限成功运行 `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python --version`，返回 `Python 3.10.20`；随后验证 `pytest 9.1.1` 可用。
- 遗留问题：WSL 启动时仍会打印 localhost 代理警告；当前不影响退出码为 0 的 Python/pytest 调用。
- 建议下一步：继续 T027，设计 ASR confidence JSONL/schema。

### 2026-07-02：完成 T026 NeMo 音频 smoke test

- 新增 `scripts/run_nemo_asr_smoke_test.py`：读取 T025 的 `primock57_nemo_asr_input_manifest.jsonl`，使用 project 内 `.nemo` 权重，打开 CTC greedy timestamps 与 entropy word confidence，并写入 `outputs/primock57/t026_nemo_smoke_test/t026_nemo_smoke_test_result.json`。
- 脚本检查 `nemo` / `nemo.collections.asr` 是否来自 `project/third_party/speech_main/`，并检查 `sys.path` 中没有 project 外部 `Speech-main` 路径。
- 新增 `docs/t026_nemo_smoke_test.md`，记录运行命令、验收字段、通过结果和后续注意事项。
- 运行记录：在 WSL `clinical-asr` 中执行 `/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_nemo_asr_smoke_test.py --record-index 1`。
- 样本：`primock57:day1_consultation01:patient`，音频时长 457.86 秒。
- 验证结果：`status == "ok"`；模型类 `nemo.collections.asr.models.ctc_bpe_models.EncDecCTCModelBPE`；设备 `cuda`；transcript word count 407，word timestamp count 408，segment timestamp count 1，word confidence count 407。
- 后续注意：T027/T028 需要明确 word timestamp 与 word confidence 的对齐、裁剪或保留规则。

### 2026-07-02：完成项目专用 WSL/NeMo 环境配置

- 新增 `scripts/setup_wsl_env.sh`：支持在 WSL 中创建项目环境，默认可用 Conda 环境 `clinical-asr`，并可选安装 CUDA PyTorch、torchaudio 与 project 内迁移的 NeMo ASR 依赖。
- 新增 `scripts/check_wsl_asr_env.py`：检查 project 内权重、PyTorch/CUDA、torchaudio、NeMo ASR import，并支持 `--restore-model`。
- 新增 `docs/wsl_environment.md`：记录 WSL 环境配置、已安装版本、验证命令、WSL localhost 代理警告和非交互 sudo 限制。
- 实际环境：Ubuntu 22.04 WSL2，Conda 环境 `clinical-asr`，Python 3.10.20，`torch==2.11.0+cu126`，`torchaudio==2.11.0+cu126`，GPU 为 `NVIDIA GeForce RTX 4060 Laptop GPU`。
- NeMo 验证：`third_party/speech_main[asr]` 已安装；project 内 `.nemo` 权重可恢复为 `EncDecCTCModelBPE`。
- 验证：WSL 环境中 `python -m pytest --basetemp=.pytest_tmp` 通过，16 passed；`python -m ruff check .` 通过。

### 2026-07-02：完成 T025 PriMock57 ASR 输入 manifest

- 完成 PriMock57 数据入口核验：本地 `data/external/primock57/` 中可完整配对 57 条 consultation；第一批按稳定排序选取 5 条：`day1_consultation01` 至 `day1_consultation05`。
- 新增 `scripts/build_primock57_asr_manifest.py`：生成 consultation 级 rich manifest 与 NeMo channel 级 ASR 输入 manifest；只写文件指针、音频头信息、TextGrid 时间边界/计数、notes 指针、许可和对齐方案，不写入正文。
- 本地输出：`data/interim/primock57/manifests/primock57_consultation_seed_manifest.jsonl`、`primock57_nemo_asr_input_manifest.jsonl`、`primock57_asr_manifest_summary.json`。
- Summary：5 条 consultation / 10 路音频，总 channel 音频时长 5507.760 秒，TextGrid utterance interval 总数 1184，音频与 TextGrid 最大 duration delta 为 0.000 秒。
- 新增 `docs/primock57_asr_manifest.md` 和 `tests/test_primock57_asr_manifest.py`。

### 2026-07-02：完成 `Speech-main` 必要资产迁移

- 用户确认后续会删除外部 `Speech-main` 仓库，因此 project 不能将其作为长期运行依赖。
- 完成 T033：迁移后续 ASR 主线会用到的外部仓库资产到 project 内。
- 权重迁入 `data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`，默认不提交 Git；`.gitignore` 已补充 `*.nemo`。
- 代码与来源快照迁入 `third_party/speech_main/`，包括 `nemo/`、`examples/asr/`、`LICENSE`、`UPSTREAM_README.md`、`CITATION.cff`、`pyproject.toml`、`setup.py`、`nemo_dependencies.py` 和 `MANIFEST.in`。
- 迁移说明见 `third_party/speech_main/README.md`。
- T026/T028/T032 验收均要求不得读取、import 或引用外部 `Speech-main`。

### 2026-07-02：确认 ASR 输出层 D001-D010 决策

- 第一版使用本地 NeMo FastConformer CTC 模型；权重已迁入 project 内部。
- 运行方式为离线批处理，环境按适配度选择，当前 WSL `clinical-asr` 已验证。
- PriMock57 第一版采用 doctor/patient 双路分别 ASR，再按时间或 reference 规则合并。
- 第一批样本规模为 3-5 条 consultation，当前已准备 5 条。
- V0 候选生成使用 sequence-level beam n-best hypotheses，对齐到连续低/中置信度词合并得到的 uncertain span。
- entropy confidence 固定 NeMo 默认参数；绿/黄/红先用启发式阈值；输出同时保存 word 和 segment。
- 本轮只验收 ASR 输出层，不强行接入下游任务。

### 2026-07-01：拆解 NeMo entropy confidence ASR 输出层主线

- 阅读 NeMo confidence、CTC/RNNT decoding、transcribe、streaming、n-best 和 BPE 后处理相关代码。
- 新增 `docs/asr_confidence_nemo_code_notes.md`：记录 NeMo 支持 `entropy` confidence，但标准 `transcribe_speech.py` 不直接写出 `word_confidence`，n-best 也不是天然 span-level top-k。
- 新增 `docs/asr_confidence_decisions.md`：列出 D001-D010 待用户决策，后续已于 2026-07-02 确认。
- 在任务列表中新增 T024-T032。

### 2026-07-01：确认 PriMock57 / DISPLACE-M 数据集路线

- 用户确认第一阶段先用 PriMock57，DISPLACE-M 作为后续扩展。
- PriMock57 已下载到 `data/external/primock57/`，默认不提交 Git。
- DISPLACE-M 暂不作为第一阶段主线；接入前仍需确认许可、注册要求和具体字段结构。

### 2026-07-01：调整为 ASR 置信度驱动的医生实时审阅主线

- 将近期主线从“文本 repair + repair 置信度 + 医生确认”调整为“音频 → ASR → noisy transcript + ASR 置信度 → 医生实时交互确认”。
- 明确置信度主要附着在 ASR 输出 token/span/segment 上，用于绿/黄/红颜色分层。
- 医生点击中/低置信度词或短语，调出 ASR top-k/n-best 候选，选择、编辑或拒绝；操作结果保存为 feedback / interaction log。
- 医生反馈可作为后续 ASR 微调、候选排序或主动学习的数据来源，但不作为近期主线。
- T018/T006 文本 repair 相关任务暂缓为辅助扩展；新增 T021/T022/T023。

### 2026-06-30：建立 TODO 机制与单一维护入口

- 新增项目级 TODO 与交接板。
- 明确 `docs/todo.md` 是当时用户唯一需要主动维护与验收的 Markdown 文档。
- 2026-07-02 起，该机制调整为：`docs/todo.md` 仍是当前入口，历史长记录迁入 `docs/task_records.md`。

### 2026-06-30：早期规划收束与 T001 暂缓

- 曾将项目重点收束为两条主轴：音频转录层面降低 noisy、文本层面增强 repair。
- 在 `docs/dataset_notes.md` 中补充字段级调研：DISPLACE-M、AfriSpeech-Dialog、ACI-Bench、PriMock57、Fareez OSCE、MedDialog-Audio。
- 用户判断 T001 不需要近期推进，因为后续会针对不同子任务选择不同数据集的不同部分。
- T001 从“进行中”改为“暂缓”，不再编写全局 `schema_design.md` 或同步改 `schema.py`。

### 2026-06-30：确认从文本 repair 与 ACI-Bench 入手

- 用户当时确认第一阶段先做文本层面的 repair，不优先推进音频 ASR 闭环。
- 首选 ACI-Bench 构建小规模 clean/noisy 对照子集。
- 对齐任务边界：T003 准备 clean/reference 种子样本，T005 生成/核验 noisy，T006 生成 repaired。

### 2026-06-30：接入 ACI-Bench 第一阶段文件并完成 manifest 校验

- 将 ACI-Bench 第一阶段所需文件复制到 `data/external/aci_bench/`，包括 ACI `asr/asrcorr` 与 VirtScribe `humantrans/asr` 的 valid/test CSV 和 metadata。
- 预建 `data/interim/aci_bench/manifests/` 和 `data/processed/aci_bench/v0_note_generation/`。
- 新增 `src/clinical_asr_robustness/manifest.py`、`scripts/build_aci_bench_manifests.py`、`scripts/validate_paired_manifest.py`。
- 生成 VirtScribe `humantrans` vs `asr` 28 条 paired records、ACI `asr` vs `asrcorr` 77 条 paired records；gold note mismatch 为 0。
- 由于同一样本 `humantrans/asr/asrcorr` 三版本齐全数量为 0，后续实验拆成两条 paired 轨道。

### 2026-06-30：调整为交互式文本 repair 主线（历史，已被 7.1 取代）

- 当时根据用户设想，将近期主线收束为文本 repair + 置信度 + 医生交互 + 系统原型。
- 当时新增 repair 决策流程：高置信度修复自动采纳；低置信度修复展示 top-k 候选，供医生选择、编辑或拒绝。
- 7.1 后该流程保留为文本 repair 辅助扩展，不再是主线。

### 2026-06-30：完成 T015 V0 note generation processed JSONL

- 新增 `scripts/build_aci_bench_v0_note_generation.py`。
- 输出 `data/processed/aci_bench/v0_note_generation/v0_note_generation_inputs.jsonl`、`v0_note_generation_pairs.jsonl`、`v0_note_generation_summary.json`。
- 共 105 条 paired records、210 条 input records；其中 `noise_harm` 28 对 / 56 input，`repair_gain` 77 对 / 154 input。
- 新增 `tests/test_aci_bench_v0_note_generation.py`。

### 2026-06-30：完成 T017 交互式 repair 数据结构

- 新增 `src/clinical_asr_robustness/repair.py`，定义 `InteractiveRepairRecord`、`RepairSpan`、`RepairCandidate`、`RepairDecision`、`DoctorFeedback` 等 Pydantic schema。
- 新增 `read_repair_jsonl` / `write_repair_jsonl`。
- 新增 `docs/repair_schema.md` 和 `tests/test_repair_schema.py`。
- 7.1 后该结构保留为文本 repair 辅助模块，不再作为主线 confidence schema。

### 2026-06-30：完成 T005 ACI-Bench noisy 来源与错误类型分析

- 用户确认错误类型使用 `substitution` / `deletion` / `insertion`，评价指标使用 WER + MC-WER。
- 新增 `src/clinical_asr_robustness/error_analysis.py` 和 `scripts/analyze_aci_bench_noisy_errors.py`。
- 新增 `docs/t005_noisy_error_analysis.md`、`tests/test_error_analysis.py`、`tests/test_aci_bench_noisy_error_analysis.py`。
- 本地结果：105 条 paired records；overall micro WER 0.0321，overall micro MC-WER 0.0626；`noise_harm` 轨道 micro WER 0.1220、micro MC-WER 0.2124；`repair_gain` 轨道差异很小。
- 输出位置：`outputs/aci_bench/t005_noisy_error_analysis/`，annotation JSONL 含局部 transcript span，默认不提交 Git。

### 2026-07-02：修正 T028 entropy confidence 全红问题

- 背景：用户指出当前 word confidence 数值最大约 0.075、均值约 0.00186、`confidence_level` 全部为 red。复核旧 `record1` 输出后确认：`entropy + tsallis + alpha=0.33 + entropy_norm=exp` 在 PriMock57 `day1_consultation01:patient` 上 407 个词全 red，最大 0.0752。
- 对照：同一音频使用 `max_prob + alpha=1.0` sanity check 后，407 个词中 372 green、35 yellow，均值 0.943；使用论文同样支持的 `entropy_norm=lin` 后，398 green、9 yellow，均值 0.912。结论是字段对齐和 ASR 输出链路基本正常，问题主要是 `entropy_norm=exp` 在当前模型/数据上尺度过低，不适合直接配合 0.5/0.8 demo 阈值。
- 修改：
  - `src/clinical_asr_robustness/nemo_confidence_export.py`：`configure_ctc_greedy_confidence()` 支持 `method_name`、`entropy_type`、`entropy_norm`、`alpha`；新增 `summarize_confidence_values()`。
  - `scripts/export_nemo_asr_confidence.py`：新增 `--confidence-method`、`--entropy-type`、`--entropy-norm`、`--confidence-alpha`；默认改为 `entropy + tsallis + alpha=0.33 + entropy_norm=lin + aggregation=mean`；run summary 写入 `confidence_distribution` 和 `low_scale_warning`。
  - `src/clinical_asr_robustness/asr_confidence.py` 与 `scripts/run_nemo_asr_smoke_test.py` 同步默认 `entropy_norm=lin`。
  - 更新 `docs/asr_confidence_schema.md`、`docs/asr_confidence_nemo_code_notes.md`、`docs/asr_confidence_decisions.md`、`docs/t028_nemo_confidence_export.md`、`docs/todo.md`。
- 重跑：已用新默认重跑 T028 `limit2`、T029、T030、T036。新 `limit2` 总计 1145 个词：1031 green、114 yellow、0 red；T030/T036 为 74 个黄色待审阅 span，其中 2 个带真实 n-best 候选。
- 输出：
  - `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl`
  - `outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates_limit2.jsonl`
  - `outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl`
  - `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_nemo_confidence_export.py tests/test_asr_confidence_schema.py --basetemp=.pytest_tmp`：8 passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src scripts tests`：All checks passed。
- 遗留：当前阈值仍是 demo 启发式阈值。T031 应用 reference 做 confidence 校准、分桶错误率、ECE/NCE 和 top-k 覆盖评估；`entropy_norm=exp`、`max_prob`、不同 `alpha/aggregation` 可作为消融。

### 2026-07-02：生成第 1 周暑期实践周报与可视化资产

- 完成：
  - 按用户给定模板生成第 1 周周报 LaTeX，主题为“面向临床语音转写噪声的病例信息整理与鲁棒性评估”。
  - 周报重点说明本周已形成的 ASR 置信度交互审阅最小闭环、当前结果含义、问题判断和下周交付计划。
  - 新增周报图生成脚本，读取 T028/T029/T030/T036/T037 run summary，生成不含 transcript 正文和患者身份信息的 PNG 摘要图。
- 修改文件：
  - `docs/week1_practice_report.tex`
  - `scripts/generate_weekly_report_assets.py`
  - `outputs/reports/week1_asr_confidence_review_summary.png`
  - `docs/todo.md`
  - `docs/task_records.md`
- 周报采用的关键统计：
  - `limit2` 两路 PriMock57 音频；
  - 1145 个 ASR 词，其中 1031 green、114 yellow、0 red；
  - 74 个黄色待审阅 span，其中 2 个带 ASR 候选；
  - 10 个 sequence-level n-best，2 个 span alternatives；
  - HTML demo 支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`。
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_weekly_report_assets.py`：成功生成 `outputs/reports/week1_asr_confidence_review_summary.png`。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/generate_weekly_report_assets.py`：All checks passed。
- 遗留问题：
  - 未在本地编译 LaTeX PDF；用户要求只提供 LaTeX，自行生成 PDF。
  - 下周仍应优先推进 T031/T032，即 confidence/top-k 初评与 ASR 输出层最小闭环实验记录。

### 2026-07-07：完成 T038 医学实体优先 ASR 审阅范围 gating

- 背景：
  - 用户指出当前系统对每个低/中置信度词组都判断和高亮，但真实医生交互中更关心医学专有名词是否正确，例如疾病、症状、药物、检查等。
  - 新逻辑要求：先由大语言模型识别 ASR transcript 中的医学实体；只有这些医学实体词组显示绿/黄/红置信度并进入候选生成和医生反馈流程；其他词组显示普通黑字。
- 完成：
  - 新增 `src/clinical_asr_robustness/medical_entity_review.py`：
    - 支持 OpenAI-compatible Chat Completions API；
    - 默认 base URL 为 `https://llmapi.paratera.com`，默认模型为 `Qwen3-Next-80B-A3B-Instruct`；
    - API key 默认从项目根目录 `.env` 读取，也兼容环境变量；支持 `API_KEY`/`BASE_URL`/`MODEL_ID` 与 `PARATERA_*` 两套命名；不写入代码或运行摘要；
    - 提供 LLM JSON/fenced JSON 解析、医学实体 mention 规整、字符/文本/token 到 ASR word range 的对齐；
    - 将原全词低/中置信度 `uncertain_spans` 替换为“医学实体且非 green”的 review spans；
    - 给 `asr_words[].metadata.medical_entity_review` 写入显示策略：医学实体显示原置信度颜色，非医学词显示 `neutral` 黑字；
    - 保留 sequence-level alternatives，清除旧 span alternatives，便于 T029 只为医学实体 span 重新生成候选。
  - 新增 `scripts/extract_medical_entity_review_spans.py`：
    - 输入 T028 ASR confidence JSONL；
    - 调用或复用缓存的 LLM 医学实体抽取结果；
    - 输出 T038 医学实体限定版 ASR confidence JSONL；
    - 输出实体缓存 JSONL 和 run summary；
    - 支持 `--env-file`、`--force-refresh-entities`、`--limit`、`--model`、`--base-url`、`--api-key-env`。
  - 更新 `src/clinical_asr_robustness/review_workflow.py`：
    - T030/T036 HTML 渲染时读取 `medical_entity_review.display_confidence_level`；
    - 支持 `.word.neutral` 黑字显示和 `.word.medical-entity` 医学实体强调；
    - 医学实体 gating 开启时，非医学低置信词不再标记为 `review_required`；
    - review policy 增加 `target_scope=llm_identified_medical_entities_only`。
  - 新增 `tests/test_medical_entity_review.py`：
    - 覆盖非医学低置信词变黑且不进入审阅；
    - 医学低置信实体生成 `uncertain_spans`；
    - 医学高置信实体显示绿色但不生成候选 span；
    - T029 只为医学实体 span 生成候选；
    - HTML 包含 `neutral` 与 `medical-entity` 显示策略；
    - LLM fenced JSON 解析。
  - 新增 `.env.example`，提供项目级 LLM API 配置占位符；真实 `.env` 继续被 `.gitignore` 忽略。
  - 新增文档 `docs/t038_medical_entity_review.md`，并更新：
    - `README.md`
    - `docs/t029_asr_nbest_candidates.md`
    - `docs/t030_t035_t036_review_workflow.md`
    - `scripts/README.md`
    - `docs/todo.md`
- 推荐新主线：
  - `T028 ASR confidence → T038 医学实体 gating → T029 n-best/top-k 候选 → T030/T036 审阅界面 → T035 confirmed transcript`
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_medical_entity_review.py tests/test_review_workflow.py --basetemp=.pytest_tmp`：10 passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`：All checks passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：40 passed。
- 遗留问题：
  - 本轮未真实调用外部 LLM API；仅实现 API 客户端、项目 `.env` 读取、缓存机制和本地逻辑测试。真实运行前需在 `.env` 或环境变量中设置 API key，且不得提交密钥。
  - 当前 `UncertainSpan` schema 不允许 green，因此高置信医学实体只显示绿色，不进入候选/反馈面板；若后续希望所有医学实体都可点击，需要把“实体可点击 span”和“uncertain span”解耦。
  - 中文无空格 ASR、复杂标点或 LLM mention 与 ASR 原文不完全一致时，实体到 word range 的对齐仍需更强模糊匹配或词表辅助。

### 2026-07-07：再次精简 `docs/todo.md` 当前入口

- 完成：根据用户反馈，将 `docs/todo.md` 从任务索引/历史摘要混合文档压缩为当前行动导航，只保留环境速记、当前主线、P0/P2/P3 下一步、阻塞/待确认、最近完成和专项文档入口。
- 迁出/压缩内容：
  - T025-T038 已完成任务长表改为一行压缩索引；
  - “ASR 输出层已确认路线”长表不再放在 TODO 中，详细历史以 `docs/task_records.md` 为准；
  - 较久的最近完成记录、T028/T037/T030 等长产出描述从 TODO 中移除，保留在本归档；
  - WSL 调用说明保留最小必要命令，细节指向 `docs/wsl_environment.md`。
- 修改文件：`docs/todo.md`、`docs/task_records.md`。
- 验证：文档整理任务，未运行代码测试；已用 UTF-8 读取检查文档内容，避免中文乱码误改。
- 遗留问题：后续完成任务时继续让 `docs/todo.md` 保持短入口，只保留 1-3 条最近完成；完整记录追加到本文件。

### 2026-07-07：用可用模型重跑 T038→T036 医学实体优先审阅 demo

- 背景：
  - 用户将 `.env` 中的模型名改为可用模型后，要求重新把流程跑一遍并打开网页页面。
  - 诊断时发现 `.env` 中 `MODEL_ID` 一度被写成嵌套形式 `MODEL_ID="MODEL_ID="Qwen3-Coder-Plus""`；已修正为 `MODEL_ID="Qwen3-Coder-Plus"`，未读取或记录任何 API key 正文。
- 完成：
  - 使用 WSL Conda 环境 `clinical-asr`，从已有 T028 ASR confidence 和 T037 sequence n-best 产物开始，串起：
    - T038 医学实体 gating；
    - T029 医学实体 span 的 n-best/top-k 候选对齐；
    - T030 医学实体优先审阅样本与 HTML；
    - T036 医生审阅单文件 HTML demo。
  - 生成并用 Windows 默认浏览器打开：
    - `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`
- 关键运行结果：
  - T038：2 条 ASR record；实际 LLM 调用 2 次；输入实体 mention 43 个，匹配实体 mention 43 个；医学实体着色词 89 个；医学实体待审阅 span 8 个，均为 yellow；非医学词显示为 neutral black。
  - T029：2 条 record；sequence alternatives 10 个；医学实体 uncertain spans 8 个；本轮没有生成 span-level alternatives。
  - T036：2 个样本；交互 HTML 生成成功；待审阅 span 8 个；支持 `accept_asr`、`select_alternative`、`manual_edit`、`reject`、`unable_to_judge`；反馈导出为浏览器下载 JSONL 和 localStorage。
- 验证/命令摘要：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_medical_entity_review_spans.py ... --force-refresh-entities --timeout-sec 60`：成功。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py ...`：成功。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py ... --interactive-html`：成功。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_doctor_review_demo_html.py ...`：成功。
- 遗留问题：
  - 本轮医学实体 gating 后只有 8 个 yellow span，且 T029 未能对这些 span 生成 span-level alternatives；页面仍可手动编辑、保留 ASR、拒绝或标记无法判断，但候选覆盖率需要后续在 T031 中评估和改进。
  - Codex 内置浏览器后端本轮不可用，已改用 Windows 默认浏览器打开本地 HTML。

### 2026-07-07：优化 T038 医学实体后处理与关键词兜底

- 背景：
  - 用户反馈真实 LLM 医学实体抽取有两类误差：
    - 将普通问句词/上下文词误标为医学实体，例如 `do`、`you`、`mean`、`your`、`and`、`what`、`kind`、`not`、`talk`、`about`、`going`、`there's`、`noticed`、`any`、`other` 等；
    - 漏掉明显医学相关词，例如 `diarrhea/diarrheea/diarrhoea`、`pain`、`vomiting/vomit`、`feverish`、`temperature`、`blood`、`tummy pain`、`asthma`、`inhalers`、`medications`、`weak`、`shaky`、`loose stools`、`fluids`、`symptoms` 等。
- 完成：
  - 收紧 `src/clinical_asr_robustness/medical_entity_review.py` 中的 LLM system prompt：
    - 明确只抽取最小医学实体；
    - 禁止把代词、助动词、连词、介词、问句模板和上下文动词包进实体；
    - 加入 `your stools → stools`、`do you mean diarrhea → diarrhea`、`you mentioned the vomiting → vomiting`、`what kind of food → no entity` 等示例。
  - 在 `apply_medical_entity_review_gating()` 前新增 `postprocess_medical_entities_for_review()`：
    - 对 LLM 粗 span 先解析到 ASR word range；
    - 裁掉左右边界的普通词；
    - 对 `and/or` 连接的实体做轻量切分，避免连接词被染色；
    - 裁剪后只剩普通问句词/上下文词时丢弃；
    - 保持 `MedicalEntityMention`、`MedicalEntityExtractionRecord`、`ASRConfidenceRecord` schema 不变，只在 metadata 中记录后处理统计。
  - 新增关键词兜底：
    - 优先识别 `tummy pain`、`loose stools/loose stool` 等短语；
    - 再补充 `diarrhea`、`diarrheea`、`diarrhoea`、`pain`、`feverish`、`temperature`、`sweating`、`vomiting`、`vomit`、`blood`、`asthma`、`inhaler(s)`、`medication(s)`、`weak`、`shaky`、`stool(s)`、`fluid(s)`、`symptom(s)` 等单词；
    - 已被 LLM 清洗后实体覆盖的词不重复补充。
  - 新增测试：
    - LLM 误抽 `do you mean diarrhea` 时，只保留 `diarrhea` 染色和进入待审；
    - `what kind of food`、`noticed any other` 等误报被丢弃；
    - LLM 完全漏抽时，关键词兜底能补上 `diarrheea`、`tummy pain`、`loose stools`、`vomiting`。
- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_medical_entity_review.py tests/test_review_workflow.py --basetemp=.pytest_tmp`：12 passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`：All checks passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：42 passed。
- 遗留问题：
  - 关键词表仍是轻量兜底，不是完整医学术语词典；后续可在 T031/T032 的错误分析后按 false negative/false positive 增量扩展。
  - 当前仍未重新调用外部 LLM 或重生成 HTML demo；本轮是逻辑和测试层修复。若需要检查真实界面效果，可复跑 T038→T029→T030/T036。

### 2026-07-07：新增 ASR 审阅一键流水线入口

- 背景：
  - 用户希望不再每次手动询问/拼接分步命令，而是有一个专门的运行文件，一直跑到最终 HTML 浏览器页面。
  - 当前主线已经稳定为 `T028/T037 → T038 → T029 → T030 → T036`，但之前命令分散在多个专项文档中。
- 完成：
  - 新增总控脚本：`scripts/run_asr_review_pipeline.py`。
  - 默认行为：
    - 复用已有 `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl`；
    - 复用已有 `outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl`；
    - 自动串起 T038 医学实体 gating、T029 候选对齐、T030 审阅样本包、T036 最终医生审阅 HTML。
  - 支持后续扩展参数：
    - `--run-asr`：从 manifest/audio 重新跑 T028 和 T037；
    - `--asr-limit 0`：重新跑 ASR 时取消默认前 2 条限制，执行全量输入；
    - `--sample-id` / `--record-index`：重新跑 ASR 时选择指定样本；
    - `--force-refresh-entities`：忽略 T038 实体缓存，重新调用 LLM；
    - `--dry-run`：只打印完整分步命令；
    - `--open-html`：完成后尝试打开最终 HTML；
    - `--apply-feedback` / `--apply-feedback-if-exists`：HTML 下载反馈后继续跑 T035 confirmed transcript。
  - 更新文档：
    - `README.md`：快速开始改为一键命令；
    - `scripts/README.md`：新增“一键运行到 HTML demo”说明；
    - `docs/todo.md`：记录一键入口已完成，T032 进入“部分完成”。
- 推荐日常命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py
Start-Process outputs\primock57\t036_doctor_review_demo\doctor_review_demo.html
```

- 从音频重新跑小规模 demo：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py --run-asr
```

- 验证：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py --dry-run`：成功打印 T038→T029→T030→T036 命令。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py`：默认链路成功跑通，重新生成 `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html` 和 `outputs/primock57/asr_review_pipeline/asr_review_pipeline_run.json`。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/run_asr_review_pipeline.py`：All checks passed。
- 注意：
  - 本轮默认链路复用了已有实体缓存，没有在记录中写入 API key；`.env` 仍不得提交。
  - `--open-html` 会尝试调用本机浏览器；若在无 GUI/沙箱环境失败，可用 PowerShell 手动 `Start-Process` 打开 HTML。
  - T032 仍需补一份更正式的 ASR 输出层最小闭环实验记录，并在有反馈日志后跑 T035 生成 confirmed transcript。

### 2026-07-08：T039 候选覆盖问题调研与方案选定

- 背景：用户反馈当前生成的候选词覆盖面极窄，大部分词没有候选，需要调研原因并选定后续解决方案。
- 诊断结论：
  - 这不是 n-best 文件未读入。T037 当前 3 条 record 均有外部 n-best 输入，共 15 个 sequence-level beam；T029 `records_with_external_nbest_input=3`。
  - 覆盖窄主要来自两层策略叠加：T038 先清空 T028 原始 `uncertain_spans`，只保留“非 green 医学实体”作为候选/反馈目标；T029 再只把 sequence-level beam 中与这些 span 局部发生差异的片段裁成 span 候选。
  - 当前 T028 原始输出中有 1958 个词、163 个 yellow 词、0 个 red 词、108 个原始 uncertain span；T038 医学实体 gating 后有 133 个医学实体着色词，但只有 3 个非 green 医学实体 review span。
  - T029 在医学实体版本中读到 15 个 sequence alternatives，但生成 0 个 span alternatives；T031 评估中 span-level exact reference coverage 为 0/3，sequence-level oracle WER 改善均值也很低。
  - 因此“多数词没有候选”一部分是医学实体优先策略的预期结果：非医学词和 green 医学实体默认不进入候选面板；真正需要修复的是医学实体/重点审阅 span 的候选可用率太低。
- 选定方案：新增 T039“候选覆盖改进”。短期不追求普通上下文词全量候选，而是优先提高医学实体/重点审阅 span 的候选覆盖：
  1. 保留 ASR sequence n-best 作为原生候选来源；
  2. 对无 ASR span candidate 的医学实体 span，引入医学词表/规范化模糊匹配候选；
  3. 对词表仍无法覆盖的复杂误识别，可选启用 LLM 辅助候选，但必须缓存、标注来源，不得混同 ASR 原生 top-k；
  4. 后续如需绿色医学实体也可点击，再将“可点击实体 span”和 `uncertain_spans` 解耦。
- 已更新：`docs/todo.md` 中新增 T039 P0、拆分 T039a-T039e 子任务，并把候选覆盖不足写入阻塞/待确认和最近完成。
- 验证：本轮为文档/调研任务，未运行代码测试；读取聚合 run summary 和 JSONL 计数字段时未输出 transcript 正文或 reference 正文。

## 2026-07-08｜T039 医学实体辅助候选覆盖改进

### 背景

T031/T032 显示当前医学实体优先链路中，T038 后仅剩 3 个非 green 医学实体待审 span，但 T029 sequence-level n-best diff 未能生成任何 span-level candidate，导致医生点击候选面板为空。T039 的目标不是把普通上下文词全量纳入候选，而是优先让医学实体/重点审阅 span 有可用候选，并明确区分 ASR 原生候选和辅助候选。

### 实现

- 在 `src/clinical_asr_robustness/asr_nbest_candidates.py` 中新增 T039 医学词表/模糊候选兜底：
  - ASR sequence n-best 与 T029 span diff 逻辑保持不变；
  - 仅当 span 是 T038 医学实体待审 span，且没有 ASR-native span candidate 时，才补充辅助候选；
  - 辅助候选 `source="medical_lexicon_aux_candidate"`，metadata 标注 `generated_by="T039"`、`candidate_type="auxiliary_medical_lexicon"`、`asr_native_candidate=false`、`reference_used=false`。
- 在 `scripts/extract_asr_nbest_candidates.py` 中默认启用 T039：
  - 新增 `--disable-aux-medical-candidates`；
  - 新增 `--aux-medical-lexicon-json`；
  - 新增 `--max-auxiliary-span-alternatives`；
  - 新增 `--aux-min-similarity`；
  - run summary 新增按 source 的 span candidate 统计。
- 新增 `configs/medical_candidate_lexicon.example.json` 作为项目内轻量候选词表示例。
- 在 `src/clinical_asr_robustness/asr_quality_evaluation.py` 中为 T031 summary 增加 source-level coverage：
  - `candidate_count_by_source`；
  - `spans_with_candidates_by_source`；
  - `exact_reference_covered_spans_by_source`；
  - source-level exact coverage ratio。
- 新增/更新测试：
  - `tests/test_asr_nbest_candidates.py` 覆盖无 ASR span candidate 时的 T039 辅助候选；
  - `tests/test_asr_quality_evaluation.py` 覆盖按 source 的 top-k summary。
- 新增专项文档：`docs/t039_candidate_coverage_improvement.md`。

### 复跑结果

T029：

- records read：3；
- sequence alternatives：15；
- total uncertain spans：3；
- span alternatives：5；
- spans with alternatives：3/3；
- span alternatives by source：`medical_lexicon_aux_candidate`: 5；
- no inline reference text：true。

T031：

- micro WER：0.3405；
- micro MC-WER：0.2526；
- total uncertain spans：3；
- spans with candidates：3/3；
- exact reference covered spans：0/3；
- candidate count by source：`medical_lexicon_aux_candidate`: 5；
- exact reference coverage by source：`medical_lexicon_aux_candidate`: 0/3。

T030/T036：

- T030 review samples 生成成功；
- T030 `spans_with_candidates=3/3`；
- T036 HTML demo 重新生成成功。

### 解读

T039 已解决候选面板空白问题，但没有解决候选正确性问题。当前 exact reference coverage 仍为 0/3，且有待审 span 疑似来自 T038 医学实体误报或过宽实体范围。后续界面和实验必须继续保留手动编辑、拒绝、无法判断等动作，不得把辅助候选视为临床正确答案。

### 验证

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：47 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`：All checks passed。


## 2026-07-08｜T040 confirmed transcript 与下游鲁棒性评估

### 背景

用户提出“我怎么样才能知道我目前整个流程的效果怎么样”。根据当前主线，需要把效果拆成三层：ASR/置信度质量、医生/研究者确认成本、confirmed transcript 对下游病例信息整理的收益。T031/T032 已覆盖 ASR noisy、confidence 和 top-k 初评，但缺少 raw ASR / confirmed / reference 的统一对比看板。

### 实现

- 新增 `src/clinical_asr_robustness/confirmed_downstream_evaluation.py`：
  - 读取 T029 ASR confidence JSONL 与 T035 confirmed transcript JSONL；
  - 按 record_id / sample_id 匹配 confirmed transcript；
  - 从 ASR record 的 reference pointer 读取 clean/reference；
  - 对 raw ASR、confirmed transcript、reference oracle 三类 variant 计算 WER / MC-WER；
  - 新增 V0 下游代理任务：医学/临床概念 token multiset 抽取 precision / recall / F1；
  - 汇总 review cost：review span、resolved/missing/unresolved span、changed span、action summary、confirmation status；
  - summary 不包含完整 transcript 正文，annotation 也不写入完整 reference/raw/confirmed 正文。
- 新增 `scripts/evaluate_confirmed_downstream.py`：
  - 默认输入当前 T029 医学实体候选 JSONL；
  - 默认 confirmed 输入为 T035 simulated accept_asr 产物；
  - 输出 T040 annotation JSONL、summary JSON 和 run config。
- 新增 `tests/test_confirmed_downstream_evaluation.py`：
  - 覆盖 transcript variant WER/MC-WER 与 concept F1；
  - 覆盖 raw vs confirmed summary 聚合和不泄露完整正文；
  - 覆盖端到端写出 annotation/summary。
- 新增专项文档：`docs/t040_confirmed_downstream_evaluation.md`。
- 更新 `docs/todo.md`：
  - 当前主干索引加入 T040；
  - 将 T007/T008 标为 V0 已启动；
  - 增加 T040 follow-up：导出真实研究者反馈、T035 回放、复跑 T040；
  - 在阻塞/待确认中明确 simulated accept_asr 基线不能代表真实医生确认质量。

### 复跑结果

默认命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_confirmed_downstream.py
```

默认输入：

- `outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl`
- `outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.simulated_accept_asr.jsonl`

输出：

- `outputs/primock57/t040_confirmed_downstream_evaluation/primock57_t040_confirmed_downstream_annotations.jsonl`
- `outputs/primock57/t040_confirmed_downstream_evaluation/primock57_t040_confirmed_downstream_summary.json`
- `outputs/primock57/t040_confirmed_downstream_evaluation/t040_confirmed_downstream_evaluation_run.json`

本轮 3 条 channel-level record：

- raw ASR micro WER：0.3405；confirmed micro WER：0.3405；reference oracle：0.0000；
- raw ASR micro MC-WER：0.2526；confirmed micro MC-WER：0.2526；reference oracle：0.0000；
- raw ASR medical concept F1：0.8772；confirmed medical concept F1：0.8772；reference oracle：1.0000；
- mean WER improvement：0.0000；
- mean MC-WER improvement：0.0000；
- mean medical concept F1 improvement：0.0000；
- review span count：3；resolved span count：3；changed span count：0；action summary：`accept_asr: 3`。

### 解读

当前 T040 结果不是“医生确认没有用”，而是“当前没有真实修正动作”。本轮 confirmed transcript 来自 simulated `accept_asr` feedback，3 个待审 span 全部保留 ASR 原文，所以 raw ASR → confirmed 的 WER、MC-WER 和 V0 下游医学概念 F1 均无改善。该结果的意义是：全流程效果看板已经跑通，后续只要把 T035 confirmed 输入替换为真实研究者/医生反馈，就能直接量化质量收益和审阅成本。

### 后续建议

1. 从 T036 HTML demo 导出真实研究者反馈，不再全部 `accept_asr`；至少覆盖当前 3 个 span。
2. 用 T035 生成新的 confirmed transcript JSONL。
3. 复跑 T040，重点观察 WER/MC-WER 是否下降、medical concept recall/F1 是否提升、manual_edit/select_alternative 成本是否合理。
4. 将 V0 医学概念 token 抽取替换或补充为症状/药物/检查实体抽取、sectioned note 信息保持或病例摘要质量评估。
5. 扩大到更多 PriMock57 consultation，并从 channel-level 过渡到 consultation-level。

### 验证

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_confirmed_downstream_evaluation.py --basetemp=.pytest_tmp`：3 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/confirmed_downstream_evaluation.py scripts/evaluate_confirmed_downstream.py tests/test_confirmed_downstream_evaluation.py`：All checks passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_confirmed_downstream.py`：成功生成 T040 summary。

## 2026-07-08：T041 noisy ASR → 病例摘要生成下游任务

### 背景

用户希望先把下游任务接起来，选择一个病例摘要任务：把当前 ASR noisy transcript 写成病例摘要。T040 已有 raw ASR / confirmed / reference 的 WER、MC-WER 和医学概念 token F1 看板，但还没有真正接入病例摘要生成这一类更贴近论文目标的下游任务。

### 实现

- 新增 `src/clinical_asr_robustness/case_summary_generation.py`：读取 ASR confidence JSONL，默认按 `consultation_id` 合并 doctor/patient 分声道 ASR record，在输入中保留声道标签，并构造 noisy ASR → structured case summary 的 Chat Completions prompt。
- 默认 dry-run 生成 `prompt_ready` JSONL，不调用外部 LLM；可选 `run_llm=True` 或脚本 `--run-llm` 调用 OpenAI-compatible Chat Completions API。
- 结构化病例摘要 schema 包含 `summary_text`、`chief_complaint`、`history_of_present_illness`、`symptoms`、`negated_or_absent_symptoms`、`relevant_history`、`medications`、`tests_or_exam_mentioned`、`assessment_mentioned`、`plan_mentioned`、`uncertainty_notes`。
- 新增 `scripts/generate_case_summaries.py`：默认输入当前 T029 医学实体候选输出，默认输出到 `outputs/primock57/t041_case_summary_generation/`，支持 `--group-by consultation|record`、`--run-llm`、`--summary-language zh|en`、`--limit`、`--exclude-prompts`。
- 新增 `tests/test_case_summary_generation.py`，覆盖 consultation-level 合并、prompt 约束、fenced JSON 解析、dry-run 写出和 stub LLM 生成路径。
- 新增专项文档 `docs/t041_case_summary_generation.md`，并更新 `docs/todo.md`。

### dry-run 结果

默认命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py
```

默认输出：

```text
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_records.jsonl
outputs/primock57/t041_case_summary_generation/primock57_t041_case_summary_summary.json
outputs/primock57/t041_case_summary_generation/t041_case_summary_generation_run.json
```

本轮未调用外部 LLM，只生成 prompt-ready 输入：input units 2，source ASR records 3，group_by consultation，status `prompt_ready: 2`，source channels doctor 2 / patient 1，transcript word count total 1967 / min 816 / max 1151，uncertain span count 3。

### 注意与局限

- `records.jsonl` 包含完整 noisy ASR transcript 和 prompt，默认位于 `outputs/`，不应提交 Git 或写入公开文档。
- `summary.json` 不包含完整 transcript 或 prompt。
- 当前 consultation-level 合并只是分声道拼接，不是精确 turn-level 对齐。
- 本轮 dry-run 只证明病例摘要下游接口已接好；真实病例摘要质量还需要 `--run-llm` 生成后再评估。
- 病例摘要输出是研究结果，不构成临床建议。

### 后续建议

1. 使用 `--run-llm` 对当前 2 个 consultation-level 输入生成第一版病例摘要。
2. 设计病例摘要质量评估：对 noisy ASR / confirmed / reference 三类输入分别生成摘要，比较症状、否定症状、药物、检查、assessment、plan 等字段的信息保持、遗漏和幻觉。
3. 等真实研究者/医生反馈接入后，复跑 T035/T040/T041，观察 confirmed transcript 是否改善病例摘要质量。

### 验证

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：5 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_generation.py scripts/generate_case_summaries.py tests/test_case_summary_generation.py`：All checks passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py`：成功生成 T041 prompt-ready summary。

## 2026-07-08：T041 `--run-llm` 生成第一版病例摘要

用户要求将 T041 从 prompt-ready 阶段推进到实际病例摘要生成。运行命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py --run-llm
```

本轮使用项目根目录 `.env` 中的 OpenAI-compatible API 配置；运行记录只保留环境变量名和模型名，不记录 API key。

结果：2 个 consultation-level input units 均生成成功，覆盖 3 条 ASR record；`status_counts={"generated": 2}`，模型记录为 `Qwen3-Coder-Plus`。输出位于 `outputs/primock57/t041_case_summary_generation/`：

- `primock57_t041_case_summary_records.jsonl`
- `primock57_t041_case_summary_summary.json`
- `t041_case_summary_generation_run.json`

局限：本轮只生成 noisy ASR 输入对应的病例摘要，尚未生成 confirmed/reference 对照摘要，也尚未做结构化字段级质量评估。`records.jsonl` 包含完整 noisy ASR transcript、prompt 和模型输出，默认不提交 Git 或写入公开文档。生成摘要为研究输出，不构成临床建议。

后续建议：人工审核当前 2 条 `case_summary`；设计 noisy/confirmed/reference 的摘要质量对照评估；在真实研究者/医生反馈接入后复跑 T035/T040/T041。


## 2026-07-09：T043 CTC posterior/entropy 词级置信度流水线

新增 CTC frame logits/log_probs/posterior 到 word-level confidence 的项目侧流水线：src/clinical_asr_robustness/ctc_word_confidence.py 支持 entropy/max-prob frame confidence、CTC token collapse、BPE word 聚合和 .npz frame artifact 读写；T028 导出脚本新增 --word-confidence-source ctc_frame_distribution、--save-frame-distributions、--frame-distribution-kind log_probs|posterior，可把 `asr_words[].confidence` 改为 frame-derived word confidence，并在 metadata 中标明来源。新增 tests/test_ctc_word_confidence.py 和 docs/t043_ctc_word_confidence.md；验证目标 pytest 9 passed、targeted ruff 通过。局限：尚未对真实 PriMock57 音频复跑，下一步检查 token→word 对齐、artifact 体积和医学实体待审 span 变化。

## 2026-07-09：T044 黄/红词级 LLM 候选逻辑

背景：用户明确要求“词级置信度不变，只修改候选词逻辑”：候选只面向黄/红色词；对每个需要候选的词，把当前目标词、适量上下文和医学词表作为参考交给大语言模型，生成约 3 个候选词。

本轮实现：

- 在 `src/clinical_asr_robustness/asr_nbest_candidates.py` 中新增 T044：
  - `LLMWordCandidatePrompt`、prompt 构造、医学词表参考裁剪、OpenAI-compatible Chat Completions 调用、LLM JSON 解析与去重；
  - 只枚举待审 span 内 `ConfidenceLevel.YELLOW` / `ConfidenceLevel.RED` 的词，忽略 green 和 unknown；
  - LLM 候选写入 `AlternativeScope.WORD`，`source="llm_word_candidate"`，`alignment_method="llm_target_word_context_lexicon"`，metadata 标注 `generated_by="T044"`、目标词、上下文、词表片段、`reference_used=false`、`asr_native_candidate=false`；
  - 重跑时会清理旧 T029/T039/T044 自动候选，避免重复叠加。
- 在 `scripts/extract_asr_nbest_candidates.py` 中接入 T044：
  - 默认导出 prompt-ready JSONL：`primock57_llm_word_candidate_prompts.jsonl`；
  - 仅显式传入 `--run-llm-candidates` 时调用外部 LLM；
  - 支持 `--max-llm-word-candidates`、`--llm-word-context-window`、`--max-llm-lexicon-terms`、`--env-file`、`--llm-base-url`、`--llm-model` 等参数；
  - run summary 新增 word-level candidate 与 prompt 统计。
- 在 `scripts/run_asr_review_pipeline.py` 中透传 T044 参数，便于一键流水线使用。
- 在 `src/clinical_asr_robustness/review_workflow.py` 中修正 confirmed transcript 回放：如果医生选择 `scope="word"` 候选，只替换对应 span 内的目标词；旧的 span-level 候选仍替换整个 span。
- 新增/更新测试：
  - T044 只对黄/红词构造 prompt，并使用目标词、上下文和医学词表生成 word-level 候选；
  - 选择 word-level 候选时 confirmed transcript 只替换目标词。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：62 passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/asr_nbest_candidates.py src/clinical_asr_robustness/review_workflow.py scripts/extract_asr_nbest_candidates.py scripts/run_asr_review_pipeline.py tests/test_asr_nbest_candidates.py tests/test_review_workflow.py`：All checks passed。
- `scripts/extract_asr_nbest_candidates.py --help` 和 `scripts/run_asr_review_pipeline.py --help` 均正常展示 T044 参数。

遗留与风险：

- 本轮没有真实调用外部 LLM 生成大样本候选；真实调用仍需项目 `.env` 或环境变量提供 API 配置，且不得把 key 写入代码、文档或输出摘要。
- LLM 候选是 ASR 审阅辅助，不是 ASR 原生 n-best/top-k，也不代表医学正确答案；后续仍需人工检查候选正确性、延迟、医生选择/编辑/拒绝成本，并继续保留 `manual_edit`、`reject`、`unable_to_judge`。
- T038 医学实体 gating 的误报/过宽 span 仍会影响哪些词进入 T044 候选生成，后续需要和实体后处理一起评估。

## 2026-07-09：T042 病例摘要质量评估方案归档

背景：原 `docs/todo.md` 中保留了较长的 T042 方案，导致 TODO 入口过长。本轮将方案归档到任务记录，TODO 中只保留一行下一步。

目标：判断 T041 生成摘要是否真正保留病例信息，而不是只看语言是否通顺。V0 评估以 reference transcript 或人工 key facts 为 gold，对 noisy ASR、confirmed transcript、reference transcript 三类输入分别生成摘要，比较质量差异和 confirmed transcript 带来的收益。

推荐指标：

- 结构合规：JSON 可解析率、必需字段存在率、字段类型正确率、是否只输出研究用摘要。
- 字段级信息保持：按 `chief_complaint`、`history_of_present_illness`、`symptoms`、`negated_or_absent_symptoms`、`relevant_history`、`medications`、`tests_or_exam_mentioned`、`assessment_mentioned`、`plan_mentioned` 建 gold key facts，计算 precision / recall / F1；重点单列症状、否定症状、药物、检查、assessment、plan。
- 事实一致性：把摘要拆成 atomic claims，标注 supported / unsupported / contradicted / unclear，报告 unsupported fact rate、contradiction rate、hallucination count per case。
- 临床高风险错误：单列否定词错误、药名/剂量/用法错误、诊疗计划越界、说话人归因错误、把不确定检查或诊断写实等；报告 safety-critical error count。
- 鲁棒性收益：比较 `score_confirmed - score_noisy`、`score_reference - score_noisy`，可用 gap closure = `(confirmed - noisy) / (reference - noisy)`；若当前 confirmed 仍是 simulated accept_asr，预期收益应接近 0。
- 不确定性质量：检查 `uncertainty_notes` 是否覆盖 ASR 噪声、低置信 span 和含糊医学术语；统计应标未标/误标不确定性。
- 人工审核成本：记录每条摘要需修改字段数、人工编辑字数、审核时间、严重错误数；用于评估医生/研究者确认后的下游收益是否值得。

V0 评测流程：

1. 从 T041 records 抽取 `case_summary`，不把完整 transcript 写入公开文档。
2. 基于 clean/reference transcript 人工建立每个 consultation 的 gold key facts 表；字段包括症状、否定症状、药物/治疗、检查、诊断倾向、计划、相关病史/社会史。
3. 将生成摘要拆成 atomic claims，人工或 LLM-assisted 初标后人工复核：supported / unsupported / contradicted / unclear，并标严重程度 minor/major/safety-critical。
4. 先对当前 2 条 noisy ASR 摘要做人工 pilot，重点核查已发现的疑点：`止泻药` 是否为计划越界，`皮肤检查显示皮疹` 是否把不确定检查写实。
5. 生成 confirmed/reference 两套摘要后复跑同一评测，输出 summary JSON/CSV：字段级 P/R/F1、unsupported/contradicted facts、关键错误类型、审核成本和 robustness gain。
6. 扩展到更多 PriMock57 样本后，至少双人标注一小批，报告一致性；最终论文中同时报告自动指标和人工 error taxonomy。

阶段验收标准：先完成 2 条样本的 gold key facts 与人工审核表；实现 `scripts/evaluate_case_summaries.py` 后输出可复跑的 `outputs/primock57/t042_case_summary_evaluation/` 报告。V0 不把 ROUGE/BLEU 作为主指标，只可作为附录参考。

## 2026-07-09：再次精简 `docs/todo.md`

背景：`docs/todo.md` 再次累积了较多历史说明、任务展开和完成记录，已经不适合作为新对话的快速入口。

本轮整理：

- 保留快速规则、环境速记、当前主线、当前焦点、阻塞/风险、最近完成和专项文档入口。
- 将 T039/T043/T044 的展开说明从 TODO 中移除，详细实现继续以专项文档和 `docs/task_records.md` 为准。
- 将 T042 病例摘要质量评估方案归档到本文件，TODO 中只保留下一步验收口径。
- 最近完成只保留 5 条；更早记录统一指向 `docs/task_records.md`。

## 2026-07-09：T042a gold key facts schema 与校验入口

背景：T042 已选择方案 B，即以 gold key facts + source-aware factuality 为主评估层，常规 ROUGE-L / BERTScore 只作为辅助。`docs/todo.md` 中 T042 的下一步是先定义 `gold_key_facts.jsonl`，为后续 raw ASR / confirmed / reference 三类摘要对齐评估提供稳定 gold 层。

本轮实现：

- 新增 `src/clinical_asr_robustness/case_summary_evaluation.py`：
  - 定义 `GoldKeyFact`、`EvidencePointer`、`CaseSummaryFactField`、`GoldFactPolarity`、`GoldFactSeverity` 和 `SummaryHighRiskTag`；
  - `gold_key_facts.jsonl` 核心字段包括 `fact_id`、`bundle_id`、`field`、`canonical_fact`、`polarity`、`severity`、`source_channel`、`evidence_pointer`、`error_tags`；
  - `evidence_pointer` 禁止 `contains_full_transcript_text=true`，并只允许短 `cue`、word/time index、sample/record 等定位信息；
  - `negated_or_absent_symptoms` 强制 `polarity="absent"`，避免否定事实后续评估混乱；
  - 提供 JSONL 读写、重复 `fact_id` 检查、variant-neutral `build_gold_bundle_id()` 和不含 `canonical_fact` 正文的聚合 summary。
- 新增 `scripts/validate_gold_key_facts.py`：
  - 默认读取 `data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl`；
  - 输出 `outputs/primock57/t042_case_summary_evaluation/primock57_t042_gold_key_facts_summary.json`；
  - run config 记录输入输出、fact/bundle 数和隐私约束，不记录完整 transcript。
- 新增 `configs/gold_key_facts.example.jsonl` 合成示例；真实标注仍应放在 `data/processed/`，不提交 Git。
- 新增 `docs/t042_case_summary_quality_evaluation.md`，说明 schema 字段、允许值、证据指针规范、校验命令和后续 T042b/T042d 接法。
- 新增 `tests/test_case_summary_evaluation.py`，覆盖合法 round-trip、summary 不泄露 fact 正文、重复 `fact_id` 拒绝、证据指针隐私检查、否定症状 polarity 约束和高风险标签计数。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py --basetemp=.pytest_tmp`：6 passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_evaluation.py scripts/validate_gold_key_facts.py tests/test_case_summary_evaluation.py`：All checks passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/validate_gold_key_facts.py --input-jsonl configs/gold_key_facts.example.jsonl --output-dir outputs/primock57/t042_case_summary_evaluation_example`：成功生成合成示例 summary，`summary_contains_canonical_fact_text=false`。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`：68 passed。

隐私与边界：

- `gold_key_facts.jsonl` 会包含短的 `canonical_fact` 标签，真实标注文件仍应视作研究数据，默认不提交 Git。
- 聚合 summary、run config 和文档示例不得包含真实未脱敏病例正文、完整 transcript、prompt 或 API key。
- 当前只完成 T042a schema/校验，不等于已经评估 T041 摘要质量。

下一步：

- T042b：扩展/复用 T041，为 raw ASR / confirmed transcript / reference oracle 生成同一 schema 的 consultation-level 病例摘要，并记录 `input_variant`、模型、prompt 版本和研究用途声明。
- T042d：在 gold facts 基础上实现 source-aware 事实级评估 B-lite，计算 fact precision / recall / F1、critical fact recall、unsupported / contradicted / unverifiable 和 omission count。

## 2026-07-09：T042b 三类输入摘要生成对齐

背景：T042a 已定义 gold key facts schema；`docs/todo.md` 中 T042 的下一步是复用 T041，为 noisy/raw ASR、confirmed transcript 和 reference oracle 生成同一 schema 的 consultation-level 病例摘要任务记录，作为后续 source-aware factuality 评估输入。

本轮实现：

- 扩展 `src/clinical_asr_robustness/case_summary_generation.py`：
  - 新增 `input_variant` 支持：`noisy_asr`、`confirmed_transcript`、`reference_oracle`，并兼容 `raw_asr` 作为 `noisy_asr` alias；
  - confirmed variant 读取 T035 `confirmed_transcript_record/v1`，reference variant 通过 ASR record 的 reference 指针读取 clean/reference transcript；
  - 三类输入复用同一 `CaseSummary` schema、同一 consultation-level bundle 逻辑和同一 LLM 调用路径；
  - prompt 升级为 `case_summary_prompt/v2_input_variant_aware`，在 prompt metadata 中记录 `input_variant` 和 `prompt_version`；
  - records 中记录 `input_variant`、`prompt_version`、`model`、`research_use_only` 和 `clinical_use_warning`；
  - 聚合 summary 新增 `input_variant_counts`、`status_counts_by_input_variant`、`source_record_counts_by_input_variant` 和 `skipped_records`，仍不写入 transcript/prompt 正文。
- 扩展 `scripts/generate_case_summaries.py`：
  - 新增 `--input-variants` 和 `--confirmed-input-jsonl`；
  - 默认仍只生成 noisy ASR，T042b 可显式指定三类输入；
  - run config 记录 input variants、confirmed 输入路径和隐私校验信息。
- 扩展 `tests/test_case_summary_generation.py`：
  - 覆盖 input-variant-aware prompt；
  - 覆盖 noisy ASR / confirmed / reference 三类输入 dry-run 对齐、summary 不泄露 reference 正文。
- 更新 `docs/t041_case_summary_generation.md`、`docs/t042_case_summary_quality_evaluation.md` 和 `docs/todo.md`。

T042b dry-run 命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/generate_case_summaries.py `
  --input-variants noisy_asr confirmed_transcript reference_oracle `
  --output-dir outputs/primock57/t042_case_summary_variant_generation `
  --records-name primock57_t042_case_summary_variant_records.jsonl `
  --summary-name primock57_t042_case_summary_variant_summary.json `
  --run-config-name t042_case_summary_variant_generation_run.json
```

输出：

- `outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl`
- `outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_summary.json`
- `outputs/primock57/t042_case_summary_variant_generation/t042_case_summary_variant_generation_run.json`

dry-run 结果：

- input units：6；
- group_by：`consultation`；
- input variants：`noisy_asr: 2`、`confirmed_transcript: 2`、`reference_oracle: 2`；
- source records：每个 variant 3 条，合计 9 条；
- status：`prompt_ready: 6`；
- records_skipped：0；
- prompt_version：`case_summary_prompt/v2_input_variant_aware`；
- `summary_contains_full_transcript_text=false`。

注意：当前 confirmed 输入仍是 simulated `accept_asr`，仅用于验证链路，不代表真实医生确认收益。`records.jsonl` 包含完整 transcript 和 prompt，默认只保存在 `outputs/`，不提交 Git；summary/run config 不含完整 transcript、prompt 或 API key。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：7 passed；
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_generation.py scripts/generate_case_summaries.py tests/test_case_summary_generation.py`：All checks passed；
- 上述 T042b dry-run 命令成功生成 6 条 prompt-ready 任务记录。

下一步：

- T042c：接入 ROUGE-L 辅助指标，只作为横向看板，不替代事实级评价。
- T042d：在 T042a gold facts 基础上实现 source-aware 事实级评估 B-lite，计算 fact precision / recall / F1、critical fact recall、unsupported / contradicted / unverifiable 和 omission count。

## 2026-07-09：T042c/T042d ROUGE-L 辅助层与 source-aware B-lite 事实评估

背景：T042a 已提供 `gold_key_facts.jsonl` schema，T042b 已生成 noisy ASR / confirmed transcript / reference oracle 三类 input_variant 的 consultation-level 摘要任务 records。当前缺口是：在真实或人工生成的 `case_summary` 存在后，能够复跑一个不泄露完整 transcript 的摘要质量评估入口。

本轮实现：

- 扩展 `src/clinical_asr_robustness/case_summary_evaluation.py`：
  - 新增轻量 `rouge_l_score()`，不依赖外部 ROUGE 包；英文/数字按词，中文按 CJK 字符 token，用于 T042c 辅助指标；
  - 新增 `ExtractedSummaryFact`、`SummaryFactFactuality`、`SummaryFactPolarity`；
  - 从 T041 `case_summary` 的结构化字段抽取短 summary facts，不读取或输出完整 transcript；
  - 对每条 summary fact 做 source-aware B-lite 匹配：ROUGE-L / normalized term coverage + 极性启发式，标注 `supported` / `unsupported` / `contradicted` / `unverifiable`；
  - 按 record 计算 fact precision / recall / F1、critical fact recall、omission count、ROUGE-L against gold facts 和 high-risk error tag counts；
  - 聚合 summary 按 input_variant 汇总 micro/macro 指标，默认不包含 `canonical_fact`、summary fact 文本、完整 transcript 或 prompt。
- 新增 `scripts/evaluate_case_summaries.py`：
  - 默认读取 T042b records：`outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl`；
  - 默认读取真实 gold：`data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl`；
  - 默认输出：
    - `outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_quality_records.jsonl`
    - `outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_fact_evaluations.jsonl`
    - `outputs/primock57/t042_case_summary_evaluation/primock57_t042_case_summary_quality_summary.json`
    - `outputs/primock57/t042_case_summary_evaluation/t042_case_summary_quality_evaluation_run.json`
  - 默认 `fact_evaluations.jsonl` 不写 `summary_fact_text`；如需人工复核可显式加 `--include-fact-text`，但该输出应按受控研究数据处理。
- 扩展 `tests/test_case_summary_evaluation.py`：
  - 覆盖 mixed Chinese/English ROUGE-L；
  - 覆盖 supported + unsupported + critical recall + omission 的 happy path；
  - 覆盖否定极性冲突判为 `contradicted`；
  - 覆盖 dry-run `prompt_ready` / missing `case_summary` 时跳过评估。
- 更新 `docs/t042_case_summary_quality_evaluation.md`、`scripts/README.md` 和 `docs/todo.md`。

评估命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_case_summaries.py `
  --summary-records-jsonl outputs/primock57/t042_case_summary_variant_generation/primock57_t042_case_summary_variant_records.jsonl `
  --gold-key-facts-jsonl data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl
```

当前没有强行运行默认真实评估，因为 `data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl` 尚未存在；用合成 gold 去评估真实 T042b records 会产生误导性 skipped/unverifiable 输出。`scripts/evaluate_case_summaries.py --help` 已确认入口可加载。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py --basetemp=.pytest_tmp`：10 passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：17 passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_evaluation.py scripts/evaluate_case_summaries.py tests/test_case_summary_evaluation.py`：All checks passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/evaluate_case_summaries.py --help`：成功加载 CLI。

隐私与边界：

- 聚合 `quality_summary.json` 不包含 fact 正文、完整 transcript 或 prompt。
- `quality_records.jsonl` 只记录指标、计数、omitted gold fact id，不包含 fact 正文。
- `fact_evaluations.jsonl` 默认只写 summary fact hash、字段、匹配分数和 best gold fact id；显式 `--include-fact-text` 后才写生成摘要事实短标签。
- B-lite 是确定性词面/术语匹配和极性启发式，不替代人工临床事实核查；论文或报告结论应以人工抽样复核后的事实级评价为准。

下一步：

- 准备真实/人工 `gold_key_facts.jsonl`，并对 T041/T042b records 加 `--run-llm` 或人工写入 `case_summary` 后复跑 T042c/T042d。
- T042e：统计否定词/极性翻转、药名/剂量、检查/计划、说话人归属等 high-risk errors，并检查 `uncertainty_notes` 是否覆盖低置信或证据不足事实。
- T042f：把错误或被修复的 summary facts 回连到 ASR `green/yellow/red` span 和审阅反馈成本，区分 ASR-induced 与 model hallucination。

## 2026-07-09：T042e 高风险错误类型与不确定性说明覆盖评估

背景：T042c/T042d 已能对生成病例摘要做 ROUGE-L 辅助指标和 source-aware B-lite 事实级评估，但 `docs/todo.md` 中 T042e 仍缺少两类关键输出：一是把 unsupported / contradicted / unverifiable / omission 进一步归入否定极性、药名剂量、检查计划、说话人归属等高风险错误族；二是检查 noisy ASR 输入下模型是否在 `uncertainty_notes` 中说明低置信或证据不足风险。

本轮实现：

- 扩展 `src/clinical_asr_robustness/case_summary_evaluation.py`：
  - 新增 `CASE_SUMMARY_QUALITY_SUBTASKS`，将评估入口标记为 T042c/T042d/T042e；
  - 在 fact-level evaluation 中新增 `is_high_risk_error` 和 `high_risk_error_types`，默认仍不写 summary fact 正文；
  - 在 record-level quality record 中新增 `high_risk_error_type_counts`，按 summary field、gold fact tag/severity 和 omitted gold fact 统计风险族；
  - 新增 `uncertainty_note_evaluation`，对 `case_summary.uncertainty_notes` 只输出 note 数量、类别计数、覆盖状态和缺失原因，不输出 note 正文；
  - 支持 `coverage_status`：`not_required`、`missing`、`generic_note_present`、`covered_by_category`；
  - 聚合 summary 新增 `uncertainty_note_summary`，统计 required/missing record count、loose/category 覆盖率、expected/missing reason counts 和 note category counts。
- 扩展 `scripts/evaluate_case_summaries.py`：
  - 运行记录 `t042_subtasks` 加入 `T042e_high_risk_error_and_uncertainty_notes`；
  - CLI 成功输出中新增 uncertainty notes required/missing 摘要。
- 扩展 `tests/test_case_summary_evaluation.py`：
  - 覆盖药名/剂量、否定极性冲突和 noisy ASR 低置信风险均被 `uncertainty_notes` 类别覆盖；
  - 覆盖 noisy ASR 有 `uncertain_span_count` 但无 `uncertainty_notes` 时标记 missing；
  - 继续验证 fact/summary 聚合输出不泄露 summary fact 正文或 uncertainty note 正文。
- 更新 `docs/t042_case_summary_quality_evaluation.md`、`scripts/README.md` 和 `docs/todo.md`。

当前 T042e 输出重点：

- `high_risk_error_type_counts`：包括 `negation_or_polarity`、`drug_name`、`medication_dose_or_route`、`test_or_exam`、`plan_or_follow_up`、`speaker_attribution`、`assessment_or_diagnosis`、`medical_term`、`safety_critical_fact` 及其 omitted 前缀计数；
- `uncertainty_note_summary`：包括是否需要 notes、缺失记录数、宽松覆盖率、类别覆盖率、预期原因计数和缺失原因计数；
- `uncertainty_note_evaluation.expected_uncertainty_reasons`：记录低置信 ASR span、unsupported/contradicted/unverifiable fact、omitted safety-critical/high-risk gold fact 等原因。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py --basetemp=.pytest_tmp`：12 passed。

隐私与边界：

- 聚合 summary 和 quality records 不包含完整 transcript、prompt、summary fact 正文或 uncertainty note 正文。
- 当前 T042e 是确定性启发式风险分类和 notes 覆盖检查；它能用于自动看板和抽样优先级，不替代人工临床事实核查。
- 真实质量结论仍需等待真实/人工 `case_summary` 与真实 `gold_key_facts.jsonl` 复跑。

下一步：

- 复跑完整测试与 ruff；
- T042f：将错误或被修复的 summary facts 回连到 ASR evidence span / green-yellow-red confidence / review feedback 成本，区分 ASR-induced 与 model hallucination。

## 2026-07-09：T042f ASR 置信度归因与审阅成本收益

背景：T042a–T042e 已建立 gold key facts、三类 input_variant 摘要生成、ROUGE-L 辅助指标、source-aware B-lite 事实级评估、高风险错误统计和 uncertainty notes 覆盖检查。剩余缺口是：把摘要事实错误或遗漏回连到 ASR 输出层证据，观察错误是否与低置信词、待审阅医学实体 span、manual edit / select alternative 等审阅动作相关，并比较 confirmed transcript 摘要相对 noisy ASR 摘要的质量收益。

本轮实现：

- 扩展 `src/clinical_asr_robustness/case_summary_evaluation.py`：
  - `run_case_summary_quality_evaluation()` 新增可选 `asr_confidence_jsonl` 与 `confirmed_transcripts_jsonl`；
  - 读取 ASR confidence records 后，按 `source_record_ids` / `source_sample_ids` / `dataset + consultation_id` 回连 T041/T042b summary record；
  - 使用 gold fact 的 `evidence_pointer` 回连 ASR record，优先按 `record_id` / `sample_id` / `source_channel` 匹配；词范围按 `[word_start_index, word_end_index)` 连接到 `asr_words`，越界或缺失时尝试时间重叠；
  - fact-level `confidence_attribution` 输出 evidence 所在 ASR 词颜色计数、dominant risk level、重叠 `uncertain_spans`、T035 review action counts、changed/manual/select span 计数；
  - fact-level `summary_error_attribution` 启发式区分 `asr_induced_possible`、`review_modified_evidence_span`、`summary_generation_polarity_error_possible`、`model_hallucination_possible` 等；
  - record-level 新增 `confidence_attribution` 和 `review_cost_attribution`；
  - summary-level 新增 `confidence_attribution_summary`、`review_cost_attribution_summary`、`review_benefit_summary`；
  - review cost 聚合按 source record 去重，避免同一 ASR source 因 noisy/confirmed/reference 多个 variant 被重复计费。
- 扩展 `scripts/evaluate_case_summaries.py`：
  - 新增 `--asr-confidence-jsonl` 和 `--confirmed-transcripts-jsonl`；
  - 运行记录和 CLI 摘要输出 T042f 状态、confidence attribution status 和 paired consultation count。
- 扩展 `tests/test_case_summary_evaluation.py`：
  - 构造合成 ASR 低置信红色 span：`pain` 被识别为 `pian`；
  - 构造 T035 `manual_edit` confirmed transcript；
  - 验证 noisy 摘要 fact F1 从 0 提升到 confirmed 摘要 1，review benefit 可按 manual edit 归因；
  - 验证 fact evidence 被回连到 red review span 和 `manual_edit` 成本；
  - 继续验证 summary 不包含完整 transcript、summary fact 正文或 confirmed span 正文。
- 更新 `docs/t042_case_summary_quality_evaluation.md`、`scripts/README.md` 和 `docs/todo.md`。

当前 T042f 输出重点：

- `fact_evaluations.jsonl[].confidence_attribution`：record/sample/span id、颜色计数、cue hash、review action counts；
- `fact_evaluations.jsonl[].summary_error_attribution`：ASR-induced / hallucination / polarity 等启发式来源；
- `quality_records.jsonl[].confidence_attribution`：本 record 的 evidence 颜色分布、omission attribution 和 overlap review span 计数；
- `quality_records.jsonl[].review_cost_attribution`：source record、review span、applied/resolved/changed span、action summary；
- `quality_summary.json.review_benefit_summary`：noisy ASR vs confirmed transcript 摘要 fact F1 / recall / critical recall 改善、omission reduction、fact error reduction，以及 per review span / changed span / manual edit 收益。

验证：

- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py --basetemp=.pytest_tmp`：13 passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check src/clinical_asr_robustness/case_summary_evaluation.py scripts/evaluate_case_summaries.py tests/test_case_summary_evaluation.py`：All checks passed。
- `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_case_summary_evaluation.py tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：20 passed。

隐私与边界：

- 默认 fact-level 输出仍不写 `summary_fact_text`；T042f 只新增 fact hash、best gold id、evidence pointer 位置、cue hash、record/sample/span id 和计数。
- 聚合 summary 不包含完整 transcript、prompt、gold canonical fact 正文、summary fact 正文、uncertainty note 正文或 confirmed span 正文。
- ASR-induced / model hallucination 是启发式自动归因，不替代人工复核；低置信或待审 span 只能说明“可能由 ASR 噪声传播”，不能单独作为最终错误来源结论。

下一步：

- 在真实/人工 `case_summary` 与真实 `gold_key_facts.jsonl` 上复跑 T042c–T042f；
- 用真实研究者/医生反馈替换 simulated `accept_asr` confirmed transcript，再比较 review benefit；
- 推进 T042g：对自动事实评估与 ASR 归因结果抽样人工复核，记录 disagreement、失败案例和典型 ASR 噪声传播链，并生成不含完整 transcript 正文的报告。

## 2026-07-10：PriMock57 全量 ASR noisy transcript 新集

背景：此前 PriMock57 只对少量 2–3 路音频跑过 ASR noisy transcript。为了后续医学实体审阅、confirmed transcript 与下游评测，需要对 `data/external/primock57/` 的 57 条 consultation / 114 路 doctor-patient channel 全量生成 ASR noisy transcript、词级时间戳和置信度，并整理为可直接作为后续输入的新集。

本轮实现：

- 生成全量 PriMock57 manifest：
  - 输入数据根目录：`data/external/primock57/`
  - 输出目录：`data/interim/primock57/manifests_full/`
  - split：`primock57_full_asr_v0`
  - 结果：57 条 consultation / 114 路 channel，总 channel 音频时长 62171.46 秒，reference / notes 正文未写入 manifest。
- 扩展 `scripts/export_nemo_asr_confidence.py`：
  - 新增 `--audio-window-sec` 与 `--audio-window-temp-dir`；
  - 长音频按固定长度临时切窗后逐窗转写，再把词级 `start_sec` / `end_sec` 平移回原始音频时间轴；
  - 合并窗口级 words 后重建 `asr_segments`、`uncertain_spans`、alignment diagnostics 和 windowing metadata；
  - 每次 transcribe 后主动 `torch.cuda.empty_cache()` / `gc.collect()`，降低长任务显存累积风险；
  - 当前 windowed 路径只支持 NeMo 原生 `word_confidence`，暂不与 T043 `ctc_frame_distribution` / frame artifact 同时运行。
- 新增 `scripts/run_primock57_asr_confidence_chunks.py`：
  - 将 114 路 channel manifest 切成 chunk，逐 chunk 调用 T028；
  - 支持 `--resume`、chunk 输出校验、最终按 manifest 顺序合并；
  - 本轮使用 chunk size 8，共 15 个 chunk。
- 新增 `scripts/build_primock57_noisy_transcript_dataset.py`：
  - 从 T028 channel-level ASR confidence JSONL 整理 channel 级 noisy transcript 新集；
  - 合并同一 consultation 的 doctor/patient ASR segments，按时间排序生成 consultation 级 `speaker_turns` 与带说话人标签的 `noisy_transcript`；
  - summary 只写路径、计数、置信度分布和校验结果，不写 transcript、reference 或 notes 正文。

关键运行命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_primock57_asr_manifest.py `
  --limit 57 `
  --split primock57_full_asr_v0 `
  --output-dir data/interim/primock57/manifests_full

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_primock57_asr_confidence_chunks.py `
  --chunk-size 8 `
  --resume `
  --audio-window-sec 120 `
  --chunks-dir outputs/primock57/t028_nemo_asr_confidence/full_window120_chunks `
  --run-summary-json outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_full_window120_chunked_run.json

wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_primock57_noisy_transcript_dataset.py `
  --input-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl `
  --channel-output-jsonl data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_channel.jsonl `
  --consultation-output-jsonl data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_consultation.jsonl `
  --summary-json data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_summary.json `
  --dataset-version primock57_asr_noisy_transcripts_full_window120_v0
```

主要产物：

- 全量 ASR confidence：
  - `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl`
  - 114 条 channel record，约 42.8 MB；
  - run summary：`outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_full_window120_chunked_run.json`
  - chunk 输出：`outputs/primock57/t028_nemo_asr_confidence/full_window120_chunks/`
- noisy transcript 新集：
  - channel 级：`data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_channel.jsonl`
  - consultation 级：`data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_consultation.jsonl`
  - summary：`data/processed/primock57/asr_noisy_transcripts_full/primock57_noisy_transcripts_summary.json`

关键计数：

- ASR confidence JSONL：114 records；57 consultations；doctor/patient 各 57；所有 records 均有 words；`reference_text_included=false`。
- noisy transcript 新集：114 channel records；57 consultation records；所有 consultation 均有 doctor + patient 双通道。
- 新集 summary：75597 ASR words，2095 ASR segments，2861 uncertain spans。
- 词级置信度分布：green 71569，yellow 4028，当前阈值下 red 0；mean 0.912602，min 0.52682，p10 0.833451。

验证：

- T028 ASR schema 读取校验：
  - 114 records；
  - `all_have_words=True`；
  - `no_inline_reference=True`；
  - 57 consultations；
  - channels：doctor / patient。
- chunk runner 摘要：
  - status：`ok`；
  - chunk count：15；
  - records written：114；
  - sample order 与 manifest 一致。
- noisy transcript summary：
  - `no_inline_reference_text=true`；
  - `no_confirmed_transcript_yet=true`；
  - `all_consultations_have_doctor_and_patient=true`；
  - `summary_contains_no_transcript_text=true`。
- 测试：
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/export_nemo_asr_confidence.py scripts/run_primock57_asr_confidence_chunks.py scripts/build_primock57_noisy_transcript_dataset.py`：All checks passed。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m py_compile scripts/export_nemo_asr_confidence.py scripts/run_primock57_asr_confidence_chunks.py scripts/build_primock57_noisy_transcript_dataset.py`：通过。
  - `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_asr_confidence_schema.py tests/test_nemo_confidence_export.py tests/test_primock57_asr_manifest.py --basetemp=.pytest_tmp`：10 passed。

失败与修正记录：

- 直接对 114 路整段音频连续运行 T028，在第 10/114 路附近触发 CUDA OOM；
- chunk size 4 仍会因同一 Python/NeMo 进程内多条长音频显存累积而 OOM；
- 最长单条 858 秒音频整段前向也会 OOM；
- 采用 120 秒无重叠 audio windows 后，最长单条音频可成功转写并合并；全量 15 chunks 均成功。

隐私与边界：

- PriMock57 是模拟问诊数据，但本项目仍按研究数据处理；`data/processed/`、`outputs/` 和本地 PriMock57 派生 transcript 默认不提交 Git。
- 本轮记录和 summary 不写完整 transcript、reference TextGrid 正文、notes 正文或 confirmed transcript 正文。
- 当前全量基线使用 NeMo 原生 `word_confidence`，不是 T043 CTC posterior/entropy 全量结果。
- 120 秒 windowed ASR 会在窗口边界损失跨窗口上下文；它是为规避 8GB GPU 长音频 OOM 的工程基线，后续报告应标注 `audio_window_sec=120`。

下一步：

- 以 `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl` 为输入复跑 T038 医学实体 gating、T029 候选对齐、T030/T036 审阅样本与 HTML demo。
- 用全量 noisy transcript 新集复跑 T031 ASR noisy/置信度初评，以及后续 T040 raw/confirmed/reference 下游评估。
- 若需要 T043 CTC posterior 全量结果，应先为 windowed 长音频路径补齐/验证 `ctc_frame_distribution` 聚合与 artifact 保存策略，避免整段长音频 OOM 和 `.npz` 体积失控。

## 2026-07-10：TODO 精简与 T045 全量三文本病例摘要评测拆解

任务来源：用户提出下一阶段要用全量 `noisy transcript`、PriMock57 自带 `clean transcript`、以及“医生选择候选词后修正的 repair transcript”三种文本进入病例生成下游任务，并以三种文本的病例摘要评测结果作为验收。

本轮处理：

- 将 `docs/todo.md` 从较长的历史交接板精简为当前任务入口，只保留快速规则、当前目标、已确认资产、T045 分步 TODO、模型分工约束、风险和专项文档入口。
- 将下一阶段主线命名为 `T045 全量三文本病例摘要评测`，拆为 9 个步骤：
  1. 三文本样本对齐；
  2. clean/reference 构建；
  3. 全量候选生成；
  4. 选择 LLM 扮演医生；
  5. repair transcript 回放；
  6. 三文本病例摘要生成；
  7. 病例摘要评测；
  8. 三组结果验收表；
  9. 抽样人工复核。
- 明确最终验收标准：同一批 57 条 consultation、同一病例摘要 prompt/schema、同一病例生成模型下，输出 `noisy_asr` / `clean_reference` / `doctor_llm_repair` 三组病例摘要评测结果和聚合对比表。
- 明确模型隔离要求：选择 LLM（doctor selector）必须不同于病例摘要生成 LLM（case summary generator）；选择 LLM 不得读取 clean/reference、医生 notes、gold key facts、病例摘要输出或评测结果。
- 在 TODO 中加入选择 LLM 的结构化提示词草案和输出 JSON schema，支持 `select_candidate`、`keep_asr`、`manual_edit`、`reject`、`unable_to_judge` 等动作。

PriMock57 clean/reference 核对：

- 本地存在 `data/external/primock57/transcripts/*.TextGrid`，共 114 个 doctor/patient TextGrid，对应 57 条 consultation。
- `data/external/primock57/transcripts/README.md` 说明该目录包含每条音频的 manual utterance-level transcriptions，格式为 TextGrid。
- 因此 PriMock57 自带 clean/reference transcript；项目中应将其作为 `clean_reference`，不能当作 noisy transcript。

隐私与边界：

- 本轮记录不写入任何完整 transcript、TextGrid 正文、notes 正文或病例摘要正文。
- `doctor_llm_repair` 只能称为模拟医生选择结果，不等于真实医生确认。

## 2026-07-10：T045 第 1 步三文本样本对齐

任务来源：用户要求“完成 T045 的下一步”。根据 `docs/todo.md`，当前下一步是 P0-1“三文本样本对齐”。

本轮处理：

- 新增 `scripts/build_t045_three_text_alignment.py`，读取全量 consultation-level noisy ASR JSONL，核对 PriMock57 doctor/patient TextGrid clean/reference 文件，并可选读取后续的 `doctor_llm_repair` JSONL。
- 新增 `tests/test_t045_three_text_alignment.py`，覆盖：
  - repair JSONL 不存在时按 consultation 标记 `pending_generation`；
  - 可选 repair JSONL 存在时只记录 ID、声道和记录数，不把 repair transcript 正文写入 manifest；
  - alignment/summary 不写 noisy ASR 或 TextGrid reference 正文。
- 新增专项文档 `docs/t045_case_summary_three_texts.md`，记录三文本定义、对齐产物、全量计数和下一步。
- 更新 `docs/todo.md`：T045 当前下一步推进到 P0-2 `clean/reference` 构建。

全量运行命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_t045_three_text_alignment.py
```

输出：

```text
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_three_text_alignment_summary.json
```

关键结果：

- alignment records：57；
- split：`primock57_full_asr_v0` 共 57；
- noisy ASR available：57；
- noisy doctor/patient 双声道完整：57；
- clean TextGrid doctor/patient 成对完整：57；
- `doctor_llm_repair` available：0；
- `doctor_llm_repair` pending：57；
- ready for clean/reference build：57；
- ready for three-text summary generation：0；
- TextGrid non-empty utterance intervals：7108；
- `<UNSURE>` 标签计数：1132；
- `<UNIN/>` 标签计数：1359。

校验：

- `all_noisy_consultations_have_doctor_patient_channels=true`；
- `all_noisy_consultations_have_clean_textgrid_pair=true`；
- `missing_clean_reference_consultation_ids=[]`；
- `manifest_contains_full_transcript_text=false`；
- `summary_contains_full_transcript_text=false`；
- `reference_text_included=false`。

验证命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_t045_three_text_alignment.py --basetemp=.pytest_tmp
```

结果：`2 passed`。

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/build_t045_three_text_alignment.py tests/test_t045_three_text_alignment.py
```

结果：`All checks passed!`

隐私与边界：

- alignment JSONL 和 summary 只写路径、ID、声道、计数、状态和校验结果，不写完整 transcript 正文。
- `doctor_llm_repair` 当前只是待生成的模拟医生选择产物；不能写成真实医生确认。
- 下一步是 T045 P0-2：解析 TextGrid，按时间戳合并为 consultation-level `clean_reference` JSONL，并记录 `<UNSURE>` / `<UNIN/>` 的保留或归一化策略。

## 2026-07-10：T045 全量三文本病例摘要离线验收

任务来源：用户要求完成 T045，验收要求是得到最终病例摘要生成任务的评测结果表，有条件画成图。

本轮处理：

- 新增 `scripts/run_t045_case_summary_final_evaluation.py`，在没有外部 LLM/API、且全量 doctor selector 尚未完成时，先跑通 T045 的可复现离线验收闭环：
  - 从 PriMock57 doctor/patient TextGrid 构建 57 条 consultation-level `clean_reference` JSONL；
  - 明确 TextGrid 标签策略：`<UNSURE>` 去标签但保留内部文本，`<UNIN/>` 和其他 angle tag 移除；
  - 生成 `doctor_llm_repair` no-change simulated baseline，明确不读取 clean/reference、不代表真实医生或 doctor selector 审阅；
  - 使用同一 deterministic keyword case-summary baseline 为 `noisy_asr`、`doctor_llm_repair`、`clean_reference` 生成结构化病例摘要记录；
  - 从 clean/reference 自动抽取短 gold key facts，并调用既有 T042 source-aware B-lite 评测链路；
  - 输出最终 CSV/Markdown 结果表和 SVG 图。
- 更新 `docs/t045_case_summary_three_texts.md`、`docs/todo.md`、`scripts/README.md`，记录运行命令、产物路径、指标和限制。

运行命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_case_summary_final_evaluation.py
```

核心输出：

```text
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_clean_reference_consultation.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_no_change_baseline.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_gold_key_facts.keyword_baseline.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_generation_records.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_quality_records.jsonl
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_quality_summary.json
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.csv
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.md
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.svg
outputs/primock57/t045_case_summary_three_texts/t045_case_summary_final_evaluation_run.json
```

关键结果：

- consultation records：57；
- clean reference records：57；
- no-change repair baseline records：57；
- case summary records：171；
- 自动 gold key facts：516；
- T042 quality evaluated records：171；
- skipped records：0。

最终聚合表：

| 输入变体 | 样本数 | Precision | Recall | F1 | Critical recall | ROUGE-L F1 | Omission | Unsupported | Contradicted | Uncertainty 缺失 | F1 Δ vs noisy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `noisy_asr` | 57 | 0.939 | 0.834 | 0.876 | 0.833 | 0.804 | 87 | 20 | 10 | 57 | 0.000 |
| `doctor_llm_repair` no-change baseline | 57 | 0.939 | 0.834 | 0.876 | 0.833 | 0.804 | 87 | 20 | 10 | 47 | 0.000 |
| `clean_reference` oracle | 57 | 1.000 | 1.000 | 1.000 | 1.000 | 0.932 | 0 | 0 | 0 | 0 | 0.124 |

验证：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/run_t045_case_summary_final_evaluation.py
```

结果：`All checks passed!`

隐私与边界：

- 最终表、SVG 图、run summary 和聚合 summary 不包含完整 transcript、prompt 或病例原文。
- `data/processed/` 中的 clean/reference、repair baseline 和 gold facts JSONL 为本地研究数据，默认不提交 Git。
- 本轮病例摘要生成是 deterministic keyword baseline，不是外部 LLM 真实病例摘要生成；gold facts 也是自动抽取，适合管线验收和相对比较，不替代人工临床事实核查。
- 当前 `doctor_llm_repair` 是 no-change simulated baseline，因此相对 `noisy_asr` 的 F1 收益为 0；后续需用真实全量候选和独立 doctor selector feedback log 替换后复跑同一脚本。

## 2026-07-10：T045 real doctor LLM selector / repair 替换 no-change baseline

任务来源：用户要求实现真实 `doctor_llm_selector` / `doctor_llm_repair`，不能继续使用 no-change baseline；selector LLM 必须不同于病例摘要生成任务的 LLM；需要对每个风险 span 做选择、输出 repaired/confirmed transcript、保留每个 span 的审阅日志，并复跑 T045 `noisy_asr` vs real `doctor_llm_repair` vs `clean_reference` oracle 评测表和图。

本轮处理：

- 先用全量 T028 ASR confidence 复跑 T029 候选补齐：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py `
  --input-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl `
  --output-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_full_medical_entity_candidates.jsonl `
  --run-config-json outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_full_run.json `
  --llm-candidate-prompts-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_full_llm_word_candidate_prompts.jsonl
```

- 新增 `scripts/run_t045_doctor_llm_selector.py`：
  - 读取全量 ASR confidence / risk spans；
  - 组织 selector payload：`asr_span_text`、左右局部上下文、speaker、置信度、候选列表；
  - 使用 `.env` 中配置的 OpenAI-compatible API 调用独立 selector LLM；
  - 输出 `select_candidate` / `keep_asr` / `manual_edit` / `reject` / `unable_to_judge` 决策；
  - 将决策转为 T035 `DoctorFeedbackEntry` 并回放到 channel-level confirmed transcript；
  - 合并为 57 条 consultation-level real `doctor_llm_repair` JSONL；
  - 支持续跑：每个 batch append decisions，失败后可继续跳过已完成 span。
- 修改 `scripts/run_t045_case_summary_final_evaluation.py`：
  - 新增 `--repair-jsonl` 参数，可直接传入 real repair JSONL 替换 no-change baseline；
  - run summary、Markdown 表和 SVG 图记录 `doctor_llm_repair_mode=real_doctor_llm_selector`；
  - final CSV 中为 repair 行补入 selector review action / changed span 成本。
- 更新 `docs/todo.md`、`docs/t045_case_summary_three_texts.md`、`scripts/README.md`。

selector 运行命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_doctor_llm_selector.py
```

复跑 T045 评测命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_t045_case_summary_final_evaluation.py `
  --repair-jsonl data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
```

selector 核心输出：

```text
outputs/primock57/t045_doctor_llm_selector/t045_doctor_llm_selector_run.json
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_decisions.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_feedback.jsonl
outputs/primock57/t045_doctor_llm_selector/primock57_t045_doctor_llm_confirmed_channel_transcripts.jsonl
data/processed/primock57/t045_case_summary_three_texts/primock57_t045_doctor_llm_repair_real_selector.jsonl
```

selector 结果：

- selector model：`Qwen3-Coder-Plus`；
- 病例摘要生成模型：`deterministic_keyword_case_summary_baseline/v1`；
- 两者不是同一个模型；
- ASR records：114；
- total risk spans：2861；
- completed decisions：2861；
- remaining decisions：0；
- feedback entries：2861；
- confirmed channel records：114；
- consultation repair records：57；
- `manual_edit=980`；
- `keep_asr=1881`；
- actually changed spans：833；
- `selector_used_clean_reference=false`；
- `selector_used_gold_facts=false`；
- `selector_used_case_summary_outputs=false`。

注意：本轮全量 T029 补齐后 `spans_with_candidates=0`，因为输入尚未先经过全量 T038 医学实体 gating，T039 词表候选没有触发；因此 selector 主要在无候选场景下做 `keep_asr` 或 `manual_edit`。

最终评测输出：

```text
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.md
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.csv
outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.svg
outputs/primock57/t045_case_summary_three_texts/t045_case_summary_final_evaluation_run.json
```

最终聚合表：

| 输入变体 | 样本数 | Precision | Recall | F1 | Critical recall | ROUGE-L F1 | Omission | Unsupported | Contradicted | Uncertainty 缺失 | F1 Δ vs noisy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `noisy_asr` | 57 | 0.939 | 0.834 | 0.876 | 0.833 | 0.804 | 87 | 20 | 10 | 57 | 0.000 |
| real `doctor_llm_repair` | 57 | 0.868 | 0.877 | 0.866 | 0.881 | 0.788 | 62 | 58 | 20 | 46 | -0.010 |
| `clean_reference` oracle | 57 | 1.000 | 1.000 | 1.000 | 1.000 | 0.932 | 0 | 0 | 0 | 0 | 0.124 |

结论：

- real repair 相对 noisy：Recall +0.043、Critical recall +0.048、Omission -25；
- 但 Precision 从 0.939 降到 0.868，Unsupported 从 20 增到 58，Contradicted 从 10 增到 20；
- 因此 F1 从 0.876 小幅降到 0.866；
- 说明当前 selector 提高了事实覆盖，但也引入了更多不支持/冲突事实；后续应抽样复核 manual edit，并优先补全候选覆盖后复跑。

验证：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check scripts/run_t045_case_summary_final_evaluation.py scripts/run_t045_doctor_llm_selector.py
```

结果：`All checks passed!`

隐私与边界：

- selector feedback / decisions 不读取或记录 clean/reference、gold facts 或病例摘要输出；
- decisions/feedback 包含 span 级原词、候选、选择、理由、是否修改，属于本地研究输出，默认不提交 Git；
- real `doctor_llm_repair` 是模拟 LLM 审阅产物，不是真实医生确认；
- 病例摘要评测仍是 deterministic keyword baseline + 自动 gold facts，适合管线和相对变化观察，不替代人工临床事实核查。

## 2026-07-10：生成第二周暑期实践周报

任务来源：用户提供暑期实践周报模板和第一周示例，要求生成第二周周报 LaTeX；特别提醒第二周工作不止 T045，需要参考任务记录完整整理。

本轮处理：

- 新增 `docs/week2_practice_report.tex`。
- 周报按统一模板组织为：
  - 本周目标；
  - 本周完成内容；
  - 本周可展示成果；
  - 当前结果与初步结论；
  - 遇到的问题与当前判断；
  - 下周计划。
- 内容覆盖第二周主要工作，而不是只写 T045：
  - T031 ASR noisy / confidence / top-k 初评；
  - T038/T039 医学实体优先审阅和候选覆盖改进；
  - T040/T041/T042 confirmed transcript 与病例摘要下游评估链路；
  - T043/T044 置信度来源和黄/红词级 LLM 候选逻辑；
  - PriMock57 全量 57 条 consultation / 114 路 channel ASR noisy transcript 新集；
  - T045 三文本病例摘要评测和 real doctor LLM selector / repair 最终结果。
- 报告中的图位已按用户要求写入绝对路径：
  - PNG 占位：`D:/Chasingfordream/内地部分/文书合集/清华大学神经调控/project/outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.png`
  - 当前已有 SVG：`D:/Chasingfordream/内地部分/文书合集/清华大学神经调控/project/outputs/primock57/t045_case_summary_three_texts/primock57_t045_case_summary_final_results.svg`
- 报告只使用聚合指标、路径和结构化产物说明，不写完整 transcript、prompt、病例正文、API key 或真实患者隐私。

关键写入指标：

- 全量 noisy ASR：57 条 consultation、114 路 channel、75,597 个 ASR words、2,095 个 ASR segments、2,861 个风险 span。
- 小样本 ASR 初评：micro WER 0.3405，micro medical concept WER 0.2526，绿色词错误率 15.43%，黄色词错误率 47.85%。
- T045 最终评测：
  - `noisy_asr`：Precision 0.939，Recall 0.834，F1 0.876，Critical recall 0.833，Omission 87；
  - real `doctor_llm_repair`：Precision 0.868，Recall 0.877，F1 0.866，Critical recall 0.881，Omission 62；
  - `clean_reference` oracle：Precision/Recall/F1/Critical recall 均为 1.000。

验证：

- 已用 UTF-8 读取检查 `docs/week2_practice_report.tex` 头尾内容。
- 已检查 `\begin{...}` / `\end{...}` 环境基本配对。
- 当前本机未检测到 `xelatex` / `pdflatex` / `lualatex`，因此未进行 PDF 编译验证；LaTeX 中已加入图片缺失占位逻辑，便于后续上传或转换 PNG 后编译。

后续建议：

- 若要直接编译 PDF，建议将现有 SVG 转为同名 PNG 或 PDF，放到周报中预留的绝对路径。
- 下周周报可直接复用本文件结构，并让“下周计划”对齐为第三周“本周目标”。

## 2026-07-13：病例摘要字段条件化说话人软权重

背景：下游病例摘要需要利用医生语言在检查解释、临床评估和诊疗计划方面的信息密度，同时避免全局提高医生权重后遗漏患者主诉、症状、否定症状和病史。采用“摘要字段 × 说话人角色”的条件化软权重方案，并保留角色盲消融。

实现：

- `src/clinical_asr_robustness/case_summary_generation.py`
  - prompt 升级为 `case_summary_prompt/v3_input_variant_role_field_weighting`；
  - 新增 `field_conditioned_v1` 与 `role_blind` 两种 profile，默认启用前者；
  - 主诉/现病史/症状/否定症状/病史提高患者证据优先级，检查/评估/计划提高医生证据优先级，药物字段区分患者自述用药与医生新开药/剂量调整；
  - 明确权重是相对证据优先级而非事实概率，医生提问不算事实，医患冲突需保留归因或写入 `uncertainty_notes`；
  - generation records 与聚合 summary 记录 profile、字段权重和 `gold_facts_unchanged=true`。
- `scripts/generate_case_summaries.py`
  - 新增 `--evidence-weighting-profile field_conditioned_v1|role_blind`；
  - run config 记录实际使用的 profile。
- `tests/test_case_summary_generation.py`
  - 覆盖默认字段权重 prompt、安全冲突规则、角色盲消融和 records/summary 元数据。

边界：本轮只接入可复跑的 prompt 层软证据先验，没有修改 T042 gold facts 或事实评估逻辑，也没有声称权重已提升病例摘要质量。后续需使用同一独立病例摘要 LLM、同一三类 input variants 和同一解码参数，分别运行 `role_blind` 与 `field_conditioned_v1`，比较字段级 F1、critical recall、unsupported、contradicted 和 omission，并抽样人工复核。

验证：

- `python -m pytest tests/test_case_summary_generation.py --basetemp=.pytest_tmp`：8 passed；
- `python -m pytest --basetemp=.pytest_tmp`：80 passed；
- `python -m ruff check src/clinical_asr_robustness/case_summary_generation.py scripts/generate_case_summaries.py tests/test_case_summary_generation.py`：All checks passed；
- 两种 profile 各完成 1 条 noisy ASR dry-run，输出位于 `outputs/primock57/t041_role_weighting_smoke/`；聚合 summary 正确区分 `soft_prompt_role_field_prior` / `role_blind_ablation`，并确认不包含 transcript 正文。

## 2026-07-13：T046 说话人字段权重全量消融与展示图

任务：比较病例摘要加入医生/患者字段条件软权重后与原始 `role_blind` 基线的质量，验收产物为可展示图。

对照设计：

- 输入固定为 PriMock57 全量 57 条 consultation / 114 路 noisy ASR；
- 两组使用同一 `Qwen3-Coder-Plus`、`temperature=0`、同一 schema；
- 正式批次使用英文摘要，与英文 transcript 和 T045 的 516 条英文自动 gold facts 对齐；
- 唯一变量为 `evidence_weighting_profile=role_blind|field_conditioned_v1`；
- 使用 T042 B-lite 事实级评测，并补充 consultation 级配对 bootstrap CI 与 sign test。

运行改进：

- `scripts/generate_case_summaries.py` 新增 `--workers` 与 `--max-attempts`；
- `src/clinical_asr_robustness/case_summary_generation.py` 支持有限线程并发和单条失败重试；默认仍为 `workers=1`、`max_attempts=1`，保持向后兼容；
- 首轮全量遇到一条模型残缺 JSON，加入单条重试后两组均完成 57/57；
- 默认中文摘要与英文 gold facts 产生语言错配，micro F1 接近 0；该批次作为失败诊断保留，不纳入正式结论。

正式结果：

- `role_blind`：Precision 0.1477，Recall 0.2674，micro F1 0.1903，Critical recall 0.2778，Omission 378；
- `field_conditioned_v1`：Precision 0.1345，Recall 0.2558，micro F1 0.1763，Critical recall 0.2556，Omission 384；
- 差值（加权减基线）：micro F1 -0.0140，Precision -0.0132，Recall -0.0116，Critical recall -0.0222，Supported -12，Unsupported +85，Contradicted -6，Omission +6；
- 56 条可计算 record-level F1 中，改善 14、持平 10、下降 32；平均 Δ=-0.0135，bootstrap 95% CI [-0.0250, -0.0023]，双侧 sign-test `p=0.0114`。

结论：本轮字段条件软权重没有优于原始 `role_blind`。显式数字权重可能诱导模型扩写高权重字段：摘要事实总数增加 67，但 supported 减少、unsupported 明显增加。该解释仍需抽样人工复核。

产物：

- `scripts/build_t046_speaker_weight_ablation_report.py`；
- `docs/t046_speaker_weight_ablation.md`；
- `outputs/primock57/t046_speaker_weight_ablation/t046_speaker_weight_ablation_figure.png`；
- 同目录 SVG、CSV、Markdown 和 JSON summary。

隐私与边界：聚合图和报告不包含 transcript、病例正文或可识别信息；generation records 含完整 noisy transcript 和模型输出，仅保存在默认不提交的 `outputs/`。所有生成摘要为研究输出，不构成临床建议。

## 2026-07-13：T047 ASR 绿黄红阈值重分级

背景：T028 全量 NeMo 原生 `word_confidence` 共 75,597 个词，旧阈值
`green >= 0.80`、`yellow >= 0.50` 得到 green 71,569、yellow 4,028、red 0；
实际最小 confidence 为 0.52682，因此旧红色下界脱离当前分数尺度，交互界面中的
红色风险等级没有作用。

阈值选择：在 T031 的 3 条 reference 对齐记录上离线比较候选阈值，最终选择
`green >= 0.90`、`yellow >= 0.80`、`red < 0.80`。同一批 1,958 个对齐词中，
green 990 / error 77 / error rate 0.0778，yellow 805 / error 200 / error rate
0.2484，red 163 / error 78 / error rate 0.4785，形成单调风险梯度。该结果只支持
当前 PriMock57 + NeMo 原生 word confidence 的研究性操作点，不是临床级校准。

实现：

- `ConfidenceThresholds`、T028 导出 CLI 和全量 chunk runner 默认改为 0.90/0.80；
- 新增 `reclassify_confidence_record()`，同步重算 record、word、segment 和
  `uncertain_spans`；已有 `asr_alternatives` 时拒绝处理，避免候选绑定旧 span；
- 新增 `scripts/reclassify_asr_confidence_thresholds.py`，允许不重跑 ASR、且不读取
  reference 正文地离线重分级，并保留旧输入产物；
- 更新 schema、T028/T031/T032 文档和回归测试。

全量结果：114 路、75,597 词，green 51,710（68.40%）、yellow 19,859
（26.27%）、red 4,028（5.33%）；待审 `uncertain_spans` 从 2,861 增至 10,130。
新产物为
`outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full_three_level.jsonl`，
聚合记录为同目录 `t028_confidence_threshold_reclassification_summary.json`。

交互验收：基于新三档文件生成
`outputs/primock57/t047_three_level_review/primock57_t047_review.html`，共 114 条
review samples、75,597 个词、10,130 个待审 span；词级 green/yellow/red 数与重分级
summary 一致，span 级 yellow 7,688、red 2,442。该页面由 T028 原始记录直接构建，
目前 `spans_with_candidates=0`，可验证颜色、优先级和手工编辑/保留/拒绝流程，但
top-k 候选仍需从新三档输入重跑 T029/T038/T044 后再验收。

验证：目标 pytest 9 passed；目标 ruff 检查通过；重分级脚本逐行完成 Pydantic
解析和重建。后续 T029/T038/医生反馈实验应显式使用新三档文件重跑；既往 T045
结果仍绑定旧阈值文件，不能静默替换后继续比较。
## 2026-07-13：T048 医生审阅网页人性化改版

基于 T047 三档置信度审阅页完成单文件 HTML 交互改版。原页面一次罗列 114 路对话，长页面滚动后审阅控件远离当前词；新版改为顶部“当前对话”按钮展开可搜索列表，每次只渲染一段 doctor/patient 声道文本，并提供前后对话按钮。桌面端审阅面板使用视口内 sticky 定位，窄屏使用底部抽屉，解决跨段滚动后候选与操作控件停留在上一位置的问题。

视觉上采用深青绿色医疗机构风格，保留 green ≥ 0.90、yellow ≥ 0.80、red < 0.80 的研究阈值和颜色语义，并补充文字标签、虚线可点击提示、焦点样式和已确认勾选，避免只依赖颜色传达状态。交互新增局部语境、前后风险词跳转、保存并下一个、对话内与全局进度、反馈本地恢复、搜索、键盘 Enter/Space 激活、移动端关闭和反馈 JSONL 统一导出；没有候选时明确引导保留原文、手动编辑、拒绝或无法判断，不把辅助候选视为正确答案。

改动位于 `src/clinical_asr_robustness/review_workflow.py`，并重新生成 `outputs/primock57/t047_three_level_review/primock57_t047_review.html`。验证：`tests/test_review_workflow.py` 与 `tests/test_medical_entity_review.py` 合计 14 passed；目标 ruff 检查通过；生成页内嵌 JavaScript 语法检查通过。页面仍是研究原型，不构成临床建议；当前 T047 输入是全词三档置信度，后续接入 T038 医学实体 gating 后，同一界面会自动切换为“实体高亮、非实体黑字”的医学实体优先显示。

## 2026-07-13：T047 医学实体优先高亮与 LLM 候选闭环修复

针对 T047 页面“普通词也全部着色、绝大多数风险词没有候选”的问题，确认旧页面直接从全量 T028 三档文件构建，绕过了 T038 医学实体 gating；旧 T029 全量运行也只导出了 T044 prompt，未传 `--run-llm-candidates`，因此候选数为 0。本轮恢复完整 `T028 three-level → T038 → T029/T044 → T030` 链路。

T038 使用 `Qwen3-Coder-Plus` 的 114 路缓存实体结果重新 gating。全量运行时发现两类工程问题并修复：长 transcript 的 1,600 token 输出上限会截断实体 JSON，因此提高为 4,096；脚本新增单条重试、逐条缓存和有限并发，避免中途格式错误丢失已完成调用。进一步抽查唯一无候选 span 时发现，LLM 偶尔返回正确实体文本但错误字符偏移；旧逻辑盲目信任偏移，导致相邻普通词被误标。现在字符偏移只有在对应 transcript 子串与实体文本规整后一致时才采用，否则回退到实体文本匹配，并新增回归测试。

修正后的 T038 结果：114 路、75,597 词中有 3,025 个医学实体着色词，其他词写入 `display_confidence_level=neutral` 并在界面显示为黑色；得到 589 个黄/红医学实体审阅 span，其中 yellow 516、red 73。实体缓存复跑为 `cache_hits=114`、`llm_calls=0`，未再次调用实体模型。

T029/T044 新增基于完整 messages 的 SHA-256 响应缓存、API 重试和 record 级有限并发。只对 710 个黄/红医学实体目标词生成候选，复用 108 条缓存并新增 602 次调用，最终写入 1,732 个 `scope=word`、`source=llm_word_candidate` 候选；589/589 个审阅 span 均有候选。候选明确标注 `asr_native_candidate=false`、`reference_used=false`，不与 ASR 原生 n-best 混同。

最终页面已重建为 `outputs/primock57/t047_three_level_review/primock57_t047_review.html`。验证包括：`tests/test_asr_nbest_candidates.py`、`tests/test_medical_entity_review.py`、`tests/test_review_workflow.py` 合计 20 passed；相关 ruff 检查通过；单文件 HTML 内嵌 JavaScript 语法检查通过。浏览器插件连接连续超时，未完成本轮点击式目视验收；应由用户在 IDE/本地浏览器中抽查候选内容与实体边界。

同时评估了“在黄/红医学实体旁播放邻近原始音频”的设想，暂未实现。现有 record 已有 `audio_filepath`，word/span 已有 `start_sec`/`end_sec`，因此原型技术难度不高：可使用共享 `<audio>` 元素，在点击 span 播放键时定位到 `start_sec - padding`，并在 `end_sec + padding` 自动暂停。主要工程点是本地 HTML 与音频相对路径/HTTP 服务、浏览器 seek 与预加载、长 WAV 的按需读取、doctor/patient 声道对应、时间戳边界及隐私日志。研究表达上应将贡献定位为“医学实体 gating + ASR 风险分级 + 局部声学证据 + 医生反馈闭环”，而不是把播放按钮本身视为独立算法创新。

## 2026-07-13：T049 黄/红词局部音频回听与确认单选状态修复

按后续需求实现了此前只评估、未落地的局部音频功能。`build_review_html()` 新增 `html_output_path` / `project_root` 参数，在 HTML 内嵌数据中为每条 review sample 生成相对于最终 HTML 的 `metadata.review_audio_url`；JSONL 中仍保留项目相对 `audio_filepath`，不写入新的本地绝对路径。T030/T036 两个生成脚本均传入最终 HTML 路径，因此直接以 `file://` 打开或从项目根目录启动静态服务时都能解析到 `data/external/primock57/audio/*.wav`。

页面使用一个共享、`preload=metadata` 的 HTML5 `<audio>` 元素，不复制或预切割音频。每个可审阅且显示为 yellow/red 的词旁加入圆形播放键，按该词 `start_sec` / `end_sec` 播放前后各 1.5 秒；侧栏另提供 span 级“播放附近原始音频”按钮。切换对话、切换 span 或按 Escape 时停止旧播放；再次点击当前播放键可暂停；到窗口结束时间自动暂停。加载/播放失败会在侧栏和 toast 中明确提示。反馈状态新增 `audio_play_count` 与 `last_audio_window`，导出 JSONL 的 metadata 同步记录播放次数、最近窗口及 padding，便于后续分析医生是否依赖声学证据和回听成本。

同时修复确认方式可重复勾选的问题。根因是候选使用 `name="candidate"`、保留 ASR/手动编辑/拒绝/无法判断使用 `name="action"`，浏览器将其视为两个 radio group。现在所有候选和动作统一使用 `name="decision"`，通过 `data-decision-action` 区分动作；选择候选会将 action 设为 `select_alternative`，选择任一其他动作会清空 `selected_alternative_id`，聚焦手动编辑框会选中 `manual_edit` 并取消候选。`getState()` 会规范化旧 `clinical_asr_review_state_v2` localStorage 状态，避免旧页面留下的“accept_asr + candidate id”矛盾重新出现。

正式 T047 页面已重新生成。全量验证：114/114 条 sample 有音频路径且对应 WAV 文件存在；589/589 个审阅 span 有时间戳；710/710 个 yellow/red 审阅词有词级时间戳。生成页只包含 `name="decision"`，不再包含旧 `name="candidate"` 或 `name="action"`；内嵌 JavaScript 语法检查通过。`tests/test_asr_nbest_candidates.py`、`tests/test_medical_entity_review.py`、`tests/test_review_workflow.py` 合计 20 passed，目标 ruff 检查通过。自动浏览器验收未执行：当前 Browser 插件目录缺少技能要求的 `scripts/browser-client.mjs`（仅有 `open-chrome-window.js`），按技能约束未改用其他浏览器自动化绕过；仍建议用户在本地页面抽查一次真实播放、自动停止和单选切换。

## 2026-07-14：T050 远程程控精选 40 例真实数据盘点与迁移评估

背景：用户计划把受保护目录 `远程程控人工复核资料_精选40例_无病历版_20260713`
接入现有 ASR 置信度交互审阅与病例信息整理系统，需要先形成可跨对话恢复的知识记录，
并确认从 PriMock57 迁移到真实中文远程程控数据还缺哪些条件。本轮仅做只读盘点和文档
记录，没有复制、修改或提交原音频、逐例转录和病例映射。

授权补充：用户于 2026-07-14 明确确认本批数据的外部 LLM、外部 ASR 和原音频处理均
已经获审。因此在线模型不是迁移阻塞，授权范围不再作为迁移问题；实验只按
复现要求记录 endpoint/服务商、模型、输入字段和运行配置。

数据快照：

- 40 例、642 个文件、686,806,868 bytes；每例固定为 1 个 MP3、14 个 TXT 和
  1 个说明 Markdown；根级另有隐私说明和 40 行清单；
- 音频合计约 11.84 小时，单例约 4.68–63.15 分钟；40/40 为 48 kHz 单声道 MP3；
- 每例包含供应商未核实的商业转录、4 个当前开源模型的有/无医疗先验两版、4 个旧版
  开源转录，以及 `Qwen结构化医学先验v3 + source-aware审计v2` 生成的说话人/信息来源
  推荐转录；所有文本均为自动结果，不是 clean/reference；
- 推荐转录共 5,942 个自动时间片段；说话人数 K=2–6，角色含医生、患者、家属/照护者、
  工作人员和未知，未知角色 993 段；发现 187 个零时长片段，5 例末段距音频结尾超过
  10 秒；
- 清单虽给出 889 个“高置信片段”和 1,629 个“待核医疗片段”，但没有逐片段分数、
  阈值、触发原因、ASR posterior 或运行配置，不能映射为当前 ASR 原生置信度；
- SenseVoice 的有/无先验结果 40/40 完全相同；Qwen3-ASR 和 Whisper-large-v3 存在
  明显长度异常与短输出，使用多模型文本作候选前必须做 QC；

迁移结论：

1. 本地 NeMo 只有英文 `stt_en_fastconformer_ctc_large`，不能用于中文数据；T028
   长音频分窗使用 Python `wave`，不能直接读取 MP3；
2. 当前数据没有人工 reference、真实 confirmed transcript、独立 gold facts、ASR 原生
   词级置信度、词时间戳或同解码器 n-best，暂不能做可靠 CER/校准/top-k/下游质量评估；
3. `nemo_confidence_export.py`、`review_workflow.py` 和反馈回放多处依赖
   `transcript.split()`，英文医学关键词/边界规则也依赖空格 token，必须改为中文字符/
   子词偏移后才能保证高亮、候选绑定和 confirmed transcript 不被错误加空格；
4. PriMock57 的 doctor/patient 双通道、0.90/0.80 置信度阈值和英文医学实体规则不能
   迁移到 K=2–6 的中文多参与者场景。需要区分声学 speaker 与语义 role，并扩展家属、
   工作人员、未知等角色；
5. 下游 summary 聚合仍写死 `dataset=primock57`，字段权重只考虑 doctor/patient；远程
   程控还需设备/侧别、触点、幅度/电压/电流、脉宽、频率、开关状态、调整前后、症状、
   不良反应和随访计划等 DBS 专用 gold schema。

建议按时长、K 和异常程度选 5 例建立 pilot：人工 reference + 角色映射 + 医学/DBS
gold；之后适配中文 manifest、MP3→WAV 或 MP3 解码、中文 ASR 原生 confidence/n-best、
字符级审阅回放、多角色 schema 和外部 LLM 调用审计。专项记录：
`docs/remote_programming_40_dataset_assessment.md`。

## 2026-07-14：T050 中文 ASR 全流程 deep research 与 P0 重排

用户进一步明确：人工 clean/reference、人工角色和下游 gold 都属于评估层，当前不先做；
首要目标是让精选 40 例从中文 MP3 完整经过 ASR 风险交互审阅、feedback、confirmed
transcript 和病例信息整理。本轮据此将这些人工真值任务从 P0 移到后续评估阶段。

现有实现核查确认，中文迁移不是只换模型：本地模型仍是英文
`stt_en_fastconformer_ctc_large`，T028 长音频分窗用 `wave.open()`；schema、候选、页面和
feedback 回放多处依赖 `transcript.split()`/空格 join，会把无空格中文当成单 token 或在
confirmed transcript 中错误插空格。因此 P0 数据协议改为 provider unit +
`char_start/char_end` + `display_joiner=""`，文本修改按字符区间从右向左确定性回放。

官方能力调研后的路线：

1. P0 首选 Google Cloud Speech-to-Text V2 `chirp_2 + cmn-Hans-CN +
   asia-southeast1 + BatchRecognize`。它支持中文、长音频、MP3 自动解码、字词时间戳、
   模型自适应和字词级数值，最容易接现有逐词回听页面；
2. Google 官方将字词 confidence 标为 Preview，Chirp 2 文档还说明返回值不是真正的
   confidence。因此统一记录为 `uncalibrated_provider_score`，允许缺失；P0 使用
   `demo_quantile_v0`（低 10% 红、后 20% 黄、其余绿）控制审阅预算，不声称校准；
3. Google alternatives 不保证返回；原生候选为空时可使用明确标源的包内多模型候选和
   已获审外部 LLM 候选；
4. Chirp 2 中文不含说话人区分，P0 先按时间重叠复用现有 source-aware 自动角色；
5. Azure Batch Transcription 是云端备选，能一次返回 phrase confidence/n-best、逐词
   时间戳和 speaker，但没有逐词 confidence，应按 segment 着色或标明 phrase score 传播；
6. FunASR Paraformer-zh 是后续本地可控路线，支持中文字符时间戳、VAD、标点、热词和
   说话人；其源码内部有 decoder scores/beam/n-best，但标准结果不导出逐 token posterior
   或 hypothesis score，需要定制 adapter，不作为最快 P0。

工程顺序改为 1 → 5 → 40 例：先建 manifest 和 1 例 Chirp 2 adapter smoke test，再改
中文 schema/页面/feedback，接 provider/LLM 候选和中文 DBS 实体，最后扩到 40 例并贯通
病例信息整理。当前 WSL `clinical-asr` 尚未安装 `google.cloud.speech_v2`、Azure SDK 或
FunASR；这是后续接入工作，不是数据问题。完整研究记录与官方来源：
`docs/t050_chinese_asr_flow_research.md`。

## 2026-07-14：T050 Qwen 27B 自动病历补充包识别与定位

新增受保护目录 `远程程控精选40例_Qwen病历_20260714_加密/远程程控精选40例_Qwen病历_20260714`。
只读盘点得到 40 份 `病例_XXXX_Qwen病历_v1.7.5.md` 和 1 个 `.DS_Store`；40 个匿名病例
编号与 20260713 无病历版完全一致。用户转述生成链为“带医学先验的 Qwen ASR 模型转录，
再由本地 Qwen 27B 生成病历”。

这批 Markdown 是下游 `noisy_asr → case_summary` 自动产物，不是新的音频/ASR 资产。
正文平均约 166 字符，栏目出现数为处置 38、现病史 29、随访计划 20、查体 8、主诉 6、
既往史/过敏史 4；20/40 含“需核实”，4 份只有一个栏目，最短记录只有 11 字符。因此其
定位是现成的 Qwen-ASR 输入下自动病历 baseline 和格式参考，不是人工病历、clean/reference、
confirmed transcript 或 gold facts，也不能倒灌为转录真值。

P0 流程可以保留这批结果作为“确认前病历输出”对照，但不需要把它作为流程输入。以后若
比较 confirmed transcript 带来的病例整理变化，应使用同一 Qwen 27B、同一 prompt/schema
和同一解码设置分别处理原始带医学先验 Qwen ASR 与 confirmed transcript。当前文件没有
提供精确 ASR/27B 模型标识、prompt 和运行配置，`v1.7.5` 暂仅记录为产物版本标签。

## 2026-07-14：T050 Parakeet CTC 0.6B Mandarin-English 迁移调研

用户希望实训项目尽量统一 ASR 模型，不再因为中文/英文直接切换到完全不同的服务或架构。
本轮只读核对 NVIDIA NGC collection、声学模型卡、英文 Hugging Face 模型卡、Riva protobuf
和 NVIDIA Riva/NeMo 教程，并检查本项目现有 checkpoint、NeMo 版本与 GPU；未下载新模型、
未处理受保护音频，也未修改 ASR 运行代码。

官方确认：

- `Parakeet-CTC-XL-unified-0.6b_spe7k_zh-CN_3.0` 为约 600M 参数的
  FastConformer-CTC，训练数据超过 17,000 小时，覆盖 `zh-CN`/`en-US` 并明确支持中英
  code-switch；声学模型每个时间步输出词表 token log probability；
- NGC collection 含中英 code-switch 4-gram LM、中文 WFST/Sparrowhawk ITN、Silero VAD
  和 Mandarin/English Sortformer；Sortformer 只给 acoustic speaker label，不给
  doctor/patient/family/staff 语义角色；
- 可训练声学 artifact 为
  `nvidia/riva/parakeet-ctc-riva-0-6b-unified-zh-cn:trainable_v3.0`，压缩体积约
  2.18 GB，模型卡要求 Riva 2.19.0+、Linux/NVIDIA GPU，并受 NVIDIA Community Model
  License 管理；
- Riva 标准 ASR proto 支持 `max_alternatives`、top hypothesis 的 word timestamp/
  confidence、speaker tag 和 language code，但 confidence 不保证准确或始终存在，标准
  服务接口也不提供完整 `[T,V]` CTC 分布；若研究需要 raw logits，应优先直接恢复 trainable
  NeMo artifact，而不是只调用 Riva/NIM 服务。

本地核查：

- 当前英文 `stt_en_fastconformer_ctc_large.nemo` 大小约 463 MB，官方模型卡为约 115M
  参数、1,024 SentencePiece 词表，并不是 Parakeet 0.6B；
- 若统一模型家族，英文应改为 `nvidia/parakeet-ctc-0.6b`，或让全部语言都使用 bilingual
  unified checkpoint。不同 checkpoint 只能称为“同一架构/模型家族”，不能写成同一个
  已训练模型；
- WSL `clinical-asr` 当前为 NeMo 3.1.0、PyTorch 2.11.0+cu126；GPU 为 RTX 4060 Laptop
  8 GB。官方完整 Riva collection 推荐 H100/A100/L40，因此首轮采用直接 NeMo、
  `batch_size=1`、FP16/BF16、15–30 秒 VAD 短段；现有 120 秒窗口不能先验复用。

关键迁移风险：

1. 中文 unified 的 `spe7k` tokenizer/decoder 与英文 1,024 词表不同，必须恢复完整
   checkpoint 配置，不能只换 state dict；置信度阈值和校准也必须按 checkpoint/语言重做；
2. 模型/Riva 不直接接收当前 48 kHz MP3；需确定性解码为 mono PCM/FLAC，并把 VAD/窗口
   内时间恢复为原音频绝对时间；
3. 现有 T043/T028 仍以 `transcript.split()` 为 word 锚点，中文会退化成整段单词；应改为
   CTC/SentencePiece emitted token + 合并字词 span + `char_start/char_end`；
4. 帧 top-k 含 blank、重复和不完整子词，不能直接作为医生候选；应由 acoustic/4-gram LM
   beam 生成 sequence n-best，再按字符区间对齐成局部 span 候选；
5. raw CTC entropy/max-prob 不等于校准正确率；中文、英文、code-switch 和不同词表不能
   共享阈值。P0 仍用 `demo_quantile_v0`，后续用人工 reference 分层校准；
6. LM、标点和 ITN 会改变文本长度，尤其会改写 DBS 参数、剂量、频率和日期。必须并存
   `am_raw`、`decoded_with_lm`、`display_itn` 及变换/对齐日志，不能把 raw confidence
   无映射地贴到 ITN 文本；
7. 40 例有 2–6 名参与者，Sortformer 仍需与 source-aware 自动 role 按时间重叠映射；
   官方只明确最多 4 人同时说话，超出范围或映射失败应保留 `unknown`；
8. 官方模型卡未给出本场景可直接引用的 CER/WER，因此普通话/英文/code-switch 支持成立
   不代表 DBS 临床术语和数字已达标，仍需 pilot 实测。

决策：P0 主线由 Google Chirp 2 调整为直接 NeMo 恢复 Parakeet Mandarin-English
`trainable_v3.0`；Google 保留为 8 GB 显存或 artifact 兼容失败时的回退。下一步先做 NGC
访问/许可确认和 checkpoint restore-only，再做 15–30 秒三类语言 smoke test，不先部署完整
Riva/NIM。详细路线、官方链接和 P0 完成定义已更新到
`docs/t050_chinese_asr_flow_research.md`。

## 2026-07-14：TODO 精简、中文 40 例完整拆解与本地资产归位

按用户决定，当前主线正式切换为真实中文医患对话的完整闭环：`audio → ASR → noisy
transcript + ASR confidence + n-best/top-k → 医学实体优先审阅 → 人工 confirmed transcript →
raw/confirmed/reference 下游鲁棒性评估`。

本轮将原 `docs/todo.md` 中已经完成的 PriMock57 T045–T049 产物清单、旧提示词全文、旧阈值
细节和长篇最近完成记录移出当前交接面；这些历史证据继续保存在本文件及对应专项文档。
新 TODO 改为 T051–T067 的可验收任务，覆盖数据快照、checkpoint restore、音频预处理、
1→5→40 例 ASR、中文字符区间 schema、未校准风险颜色、原生 n-best、医学实体筛选、审阅页、
真实人工确认、独立 reference/gold、ASR/置信度/候选评估、三输入下游评估，以及最终图表和
演示交付。只有独立 reference/gold 与真实人工确认齐备后才能宣称质量提升。

本地资产已按语义归位，且均受 `.gitignore` 保护：

- 原始 40 例包：`data/raw/remote_programming_40/远程程控人工复核资料_精选40例_无病历版_20260713/`；
- Qwen 自动病历 baseline：`data/external/remote_programming_40/远程程控精选40例_Qwen病历_20260714_加密/`；
- unified Parakeet artifact：`data/external/asr_models/nemo/Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo`。

迁移前聚合盘点保持不变：原始包 642 个文件、686,806,868 bytes，其中 40 个 MP3；Qwen 包
41 个文件；Parakeet artifact 2,338,476,221 bytes。文件名含 `Hybrid`，与先前调研的 CTC
artifact 命名不完全一致，故下一步必须 restore-only 核验真实模型类、tokenizer 和解码配置，
不能仅凭文件名假定可直接导出完整 CTC frame posterior。

## 2026-07-14：T051–T060 中文真实数据增量集成与最短整例闭环

按“保留 PriMock57 英文主线、只增加数据集差异逻辑”的约束完成第一阶段实现。数据和模型均
已归位到项目的 Git 忽略目录；未把真实对话、病例正文、模型权重或中间输出加入版本控制。

### 数据与 checkpoint

新增 `build_remote_programming_40_manifest.py`，生成 40 条匿名 ASR manifest 和逐文件
SHA-256 快照。raw + Qwen 共 683 个文件、686,834,687 bytes；40 个 MP3 总时长
42,626.664 秒，快照 digest 为
`5d219620861b9dd4ad34296dec4caeff2de5aeeff2ac743c069fe19c01572994`。

本地 Hybrid artifact 大小 2,338,476,221 bytes，SHA-256 为
`0ac223ddf6ed7366d5c662abcc8d6a827767c44b93937e0f8f04ae05dba45e6a`。WSL
`clinical-asr` restore-only 确认真实类是 `EncDecHybridRNNTCTCBPEModel`，16 kHz、
SentencePiece BPE 7,000、auxiliary CTC blank id 7,000；环境为 NeMo 3.1.0、PyTorch/
torchaudio 2.11.0+cu126、RTX 4060 Laptop。原始下载页面/许可证凭据没有嵌入本地 artifact，
公开发布或重新分发前仍需补齐。

### 共用代码路径

新增 `dataset_profiles.py`，当前只识别 `primock57` 与 `remote_programming_40`。无提示时
回退到历史英文；中文选择 Hybrid checkpoint、auxiliary CTC frame distribution、
`demo_quantile_v0` 和独立输出根目录；英文仍选择 FastConformer、NeMo word confidence、
历史固定阈值。T028、T037、T038、T029、T030、T036、T035 没有复制为第二套系统。

核心兼容改动：

- Hybrid 模型的 confidence 和 beam 解码走 auxiliary CTC，纯 CTC 分支保持不变；
- 中文 timestamp/字符单元保存 `char_start/char_end`、原始分隔符和 nullable 信号，不再以
  `.split()` 为真值；
- CTC emitted BPE 表面文本可聚合到中文字/词，segment/span 和页面不插入额外空格；
- T035 反馈按字符范围从右向左回放；
- 中文医学实体采用 Unicode NFKC 规范化，忽略 ASR 分词空格/标点后映射回原字符范围；
- 运行 RTF 从实际 ASR 输入窗口时长求和，不重复累计审阅侧整段时长。

### 音频、整例 ASR 与页面

`preprocess_asr_audio.py` 已实现 MP3 → 16 kHz mono PCM16 连续 30 秒窗，并保存原 MP3
绝对时间。最短/典型/最长首窗 QC 通过；最短整例为 10 窗，覆盖 0–280.704 秒。

最短整例运行结果：

- confidence：10/10 成功，实际输入 280.661375 秒，transcribe 13.776 秒，RTF 0.0491，
  峰值 allocated 2.465 GiB；
- n-best：10/10 成功，transcribe 2.953 秒，RTF 0.0105，峰值 allocated 2.470 GiB；
- 726 个审阅单元，字符偏移错误 0、绝对时间越界 0；
- `demo_quantile_v0` 为 green/yellow/red = 507/146/73，明确 `calibrated=false`；
- 每窗返回 3–5 个去重 acoustic beam，10/10 窗有多个不同序列候选。

复用实体和页面链后，10 条实体缓存记录全部命中；7/7 LLM 实体映射成功，22 个医学单元
着色，形成 4 个黄/红 span，其中 1 个有局部 n-best 差异候选。最终 T036 单文件 HTML 支持
接受 ASR、选择候选、手工编辑、拒绝、无法判断和 JSONL 反馈导出；10 个需审阅单元全部有
原始 MP3 绝对时间。没有伪造真实医生反馈或 confirmed transcript。当前 Codex 会话无可用
浏览器实例，故浏览器人工点击/截图验收仍留在 T060。

### 验证与后续

整仓 `pytest` 为 95 passed，`ruff check .` 通过。PriMock57 dry-run 继续选择英文 checkpoint、
`nemo_word_confidence` 和固定阈值；中文 dry-run 选择 Hybrid checkpoint、
`ctc_frame_distribution`、frame artifact 和 `demo_quantile_v0`。

尚未完成 5 例/40 例、独立 `am_raw/decoded_with_lm/display_itn`、4-gram LM、浏览器人工验收、
真实人工确认、reference/gold 和正式校准。详细实现与不含正文的结果见
`docs/t051_t060_chinese_asr_integration.md`；`docs/todo.md` 已把当前焦点推进到 T058/T060。

## 2026-07-14：T068–T070 完整对话审阅、中文 LLM 候选与 NVIDIA diarization 调研

### 问题复核与设计决策

用户指出三项中文链路问题：审阅被 30 秒 ASR 窗口切碎、中文没有实际候选、页面要求按
说话人分段但尚未完成 diarization。检查最短整例产物确认：约 280.7 秒音频产生 10 条 ASR
record，过去 T030 也生成 10 条一级 review sample，其中两个窗口仅有 2 个 ASR 单元；T029
已具备 LLM candidate 代码，但当次运行没有 `--run-llm-candidates`，prompt 仍为英文局部上下文，
词表仍偏 PriMock57 英文；所有 ASR word 的 `speaker_label` 为空。

决定保留 30 秒窗口作为 ASR 内部推理、失败恢复、绝对时间和反馈回放单元，新增一行一例的
`asr_review_conversation/v1` 作为医生/研究者/候选上下文单元。conversation 内保存 speaker
turn、原 window slice 和完整 review sample，从而不破坏 T035 按 record/span 回放。页面按
`consultation_id` 导航并展示完整对话；speaker 不可用时明确写 `speaker_unknown/说话人待分离`。

### 代码与配置

- `review_workflow.py`：新增 `ReviewConversation`、`ReviewSpeakerTurn`、`ReviewTurnSlice`、
  conversation JSONL 读写和 speaker turn 聚合；HTML 从按窗口导航改为按病例导航，仍保留
  每个风险 span 的候选、回听和 feedback key。
- `build_asr_review_samples.py`：新增 `--conversation-jsonl`，同步输出 window-level 与
  consultation-level 两种审阅包；运行摘要记录 conversation/turn/diarization status。
- `dataset_profiles.py`：中文 profile 选择 `zh_dbs_remote_programming_v1`、
  `complete_consultation`、中文 DBS 词表，并在本批已批准数据范围内默认实际运行 LLM
  candidate；可用 `--no-run-llm-candidates` 关闭。
- `asr_nbest_candidates.py` / `extract_asr_nbest_candidates.py`：新增不含 reference 的完整
  speaker-labeled noisy ASR context、中文保守候选 prompt、独立 cache 路径和可审计 metadata；
  中文上下文使用字符偏移拼接，不给汉字插空格。
- `configs/medical_candidate_lexicon.remote_programming_40.json`：新增 DBS 设备、靶点、参数、
  症状、药名、侧别、数字单位和否定词提示；词表只作候选提示，不是答案或 gold。
- `run_asr_review_pipeline.py`：按数据集传递词表、prompt profile、context scope、cache 与
  conversation 输出路径；运行摘要增加上述参数。

### 1 例实际候选与页面结果

在 WSL `clinical-asr` 环境使用现有实体/5-best 产物，按中文完整对话 profile 实际调用外部
LLM。共 10 条 prompt，10 次 API 请求成功、cache hit 0，生成 25 个
`llm_word_candidate` word alternatives；4/4 个医学待审 span 均有候选。候选没有自动写回
confirmed transcript，也没有使用 reference、Qwen 病历或下游摘要。

随后重建审阅产物：window-level review JSONL 仍为 10 条；conversation JSONL 为 1 条，
内部含 10 个 review samples。由于尚未安装 diarization artifact，当前产生 10 个
`speaker_unknown` turn，`diarization_status=missing`，这是预期的诚实占位而不是分离结果。
最终 HTML 的 JavaScript 已通过 Node 语法解析；当前产品没有可用 in-app browser/Chrome
实例，故没有伪造点击、截图、本地恢复或下载验收，T060 仍为进行中。

上述病例正文、prompt/response、原始音频和候选文本全部留在 Git 忽略目录；项目记录只保存
聚合数量、配置和路径。

### NVIDIA diarization 结论

官方 Mandarin-English Parakeet 0.6B collection 确实列出独立 Sortformer 组件，支持
Mandarin/English、流式处理和最多 4 speaker 输出；但当前 2.34 GB Parakeet artifact 恢复类是
`EncDecHybridRNNTCTCBPEModel`，只负责 ASR，不能从该对象直接取得 speaker。项目本地模型
目录也没有 Sortformer/VAD/TitaNet 权重。NeMo 快照含 `SortformerEncLabelModel`、
`ClusteringDiarizer` 和 `OfflineDiarWithASR`，但没有完整迁入官方 speaker_tasks 离线示例和
配置。

首选 pilot：整例 16 kHz mono 音频单独跑 Sortformer，输出 RTTM/JSONL，再按最大时间重叠
映射 ASR words；ASR 与 diarization 顺序运行，避免 8 GB GPU 同时常驻。声学
`spk_0/spk_1` 与 doctor/patient/family/staff role 必须分开。对超过 4 个有效 speaker 或域外
失败，准备 multilingual VAD + TitaNet + clustering（可选 MSDD）回退。没有人工 RTTM 前只
报告 speaker 映射覆盖和运行工程指标，不报告 DER/JER 或准确率。

详细调研、官方链接、schema 和 1→5 例门槛见
`docs/t068_chinese_conversation_candidates_diarization.md`。

### 验证

- 针对性测试：19 passed；
- 整仓测试：97 passed；
- `ruff check .`：通过；
- 真实 1 例 LLM candidate：10/10 请求成功，25 个 word alternatives，4/4 span 有候选；
- conversation 聚合：1 个病例级记录，内部 10 个 window records；
- HTML JavaScript 语法解析：通过；
- 浏览器人工交互：未验收，原因是当前无可用浏览器实例。

下一步是先取得并核验 Sortformer artifact，在 1 例整段音频跑 RTTM→ASR word 映射；同时按
T058 扩 5 例，复核 LLM 候选的空候选、重复、过度推断和人工可用率，再进行真实医生/研究者
试审。未通过 5 例门槛前不跑 40 例。

## 2026-07-15：T070 Streaming Sortformer 1 例整段接入

### 模型取得与恢复

用户把 NVIDIA `diar_streaming_sortformer_4spk-v2.1.nemo` 放入
`data/external/asr_models/nemo/`。文件大小 471,367,680 bytes，SHA-256 为
`8abd32832159c6ac1148c926b7276f35ba34582c444e559dce1f1253fea42ef8`，与官方 Hugging Face
文件页一致；许可记录为 NVIDIA Open Model License Agreement。项目 WSL `clinical-asr` / NeMo
3.1.0 快照成功恢复为 `SortformerEncLabelModel`，采样率 16 kHz，最大 4 speaker。首次 CPU
冷恢复约 105 秒；实际 GPU pilot 在文件系统缓存后恢复为 11.230 秒。模型权重仍位于 Git 忽略
目录，不提交或重新分发。

### 实现

新增 `speaker_diarization_record/v1` 与以下入口：

- `src/clinical_asr_robustness/speaker_diarization.py`：解析 Sortformer
  `start end speaker`、导出 RTTM、保存模型/许可/运行元数据，并按 `dataset + consultation_id`
  映射 ASR 字词；
- `scripts/run_sortformer_diarization.py`：整例 16 kHz mono GPU 推理，逐例 JSONL/RTTM 落盘，
  支持 `--resume`、`--overwrite`、失败记录和可选 ASR 映射；
- `scripts/map_speaker_diarization_to_asr.py`：在不重复加载 GPU 模型的情况下，把已有
  diarization 应用到候选增强 ASR；
- `tests/test_speaker_diarization.py`：覆盖解析、RTTM、近似并列重叠保守留空、字词映射、
  segment mixed 传播和 JSONL 往返。

映射不使用 reference、自动病历或角色文本。普通字词按累计最大重叠 speaker 赋值；最大覆盖低于
10% 时留空，第二名重叠达到第一名的 90% 时标记 `ambiguous_overlap` 并留空。每个字词记录候选
speaker 重叠时长、覆盖比例、时间 offset 和模型来源。声学 speaker 与语义 role 保持分离。

### 1 例真实工程运行

用 `preprocess_asr_audio.py --window-sec 0` 把工程阶段最短整例确定性转换为 280.704 秒、
16 kHz mono PCM16 WAV。ASR 与 diarization 顺序运行。最终显式配置为：

- `chunk_len=340`；
- `chunk_right_context=40`；
- `fifo_len=40`；
- `spkcache_update_period=340`；
- `spkcache_len=188`；
- `batch_size=1`。

模型卡示例的 `spkcache_update_period=300` 在当前 NeMo 中会因小于 `chunk_len` 被自动提升为
340；正式复跑已显式改成 340，保证记录与实际一致。固定配置结果：1/1 成功，推理 2.180 秒，
RTF 0.00777，CUDA 峰值 allocated/reserved 为 689.81/750.00 MiB。输出 97 个声学区间和
`speaker_0...speaker_3` 四个标签；活动时长分别为 112.24、27.04、24.88、0.48 秒。不同
speaker 区间允许重叠，不能把活动时长直接相加。`speaker_3` 极短且没有映射到候选增强 ASR
字词，可能是真实短时第三方、重叠或伪检出，需人工回听/RTTM 判断。

候选增强后的 10 个 ASR 窗口共有 726 个字词单元：681 个 `mapped_max_overlap`、18 个
`ambiguous_overlap`、25 个 `no_overlap`、2 个 `missing_timestamp`，覆盖 93.80%。病例级审阅包
仍是一行一例，内部保留 10 个窗口，产生 89 个 speaker turns；681 个字词进入
`speaker_0/1/2`，45 个保留 `speaker_unknown`，故 `diarization_status=partial`。这只表示工程
映射覆盖，不是准确率。

主要产物位于 `outputs/remote_programming_40/t070_sortformer_pilot/`：diarization JSONL、
RTTM、候选增强 + speaker ASR、window/conversation 审阅 JSONL、CSV、交互 HTML 和三个运行
摘要。所有音频、转写和页面仍位于 Git 忽略目录。

### 验证与边界

- 新增测试：4 passed；
- 整仓测试：101 passed；
- `ruff check .`：通过；
- 交互 HTML 的 2 个内联 JavaScript 块通过 Node 语法解析；
- Browser runtime 可初始化，但浏览器列表为空，未进行真实点击、回听、本地恢复或反馈下载；
- 没有人工 RTTM/reference，不报告 DER/JER、speaker 准确率或质量提升。

详细配置、指标、产物和下一步见 `docs/t070_sortformer_diarization_pilot.md`。下一步扩到 5 例，
重点检查极短 speaker、超过 4 人、中文/中英混说、重叠歧义、失败恢复和人工可用性；必要时接
VAD + TitaNet + clustering 回退。未通过 5 例门槛前不跑 40 例。

## 2026-07-15：T070 同一说话人短空洞桥接与审阅分段收敛

用户反馈病例级页面仍出现“说话人待分离”把同一人的连续话语切成多段。对首例只统计标签、
时间戳和相邻关系，不读取或记录对话正文：45 个未映射字词组成 32 个连续空洞，其中 19 个
空洞前后是同一声学 speaker；14 个短空洞满足 1.5 秒阈值和安全状态约束。

`speaker_diarization.py` 新增 `same_speaker_short_gap_bridge/v1`。规则仅在未映射 run 前后标签
相同、两侧间隔不超过 1.5 秒，且 run 中所有原始状态均为 `no_overlap` 或
`insufficient_overlap` 时回填展示标签。`ambiguous_overlap`、不同 speaker 交界、长静音、
缺时间戳和时间倒序均不桥接。word metadata 中原始 acoustic `speaker_label`、
`mapping_status` 和候选重叠证据保持不变，另存 `resolved_speaker_label`、来源、观察间隔和
平滑状态；运行摘要分别报告 acoustic coverage 与 resolved coverage，避免把上下文推断伪装成
模型输出。规则跨 ASR window 生效，但只在同一 `dataset + consultation_id +
diarization_record_id` 内运行。

两个映射入口均新增 `--max-same-speaker-bridge-gap-sec` 和
`--disable-same-speaker-gap-bridge`。病例级审阅的 speaker label source 也会保留直接声学映射
或短空洞桥接来源。首例重新映射后：原始声学覆盖仍为 681/726（93.80%），安全桥接 14 个
`no_overlap` 单元，展示覆盖为 695/726（95.73%）；没有桥接 18 个重叠歧义。
`speaker_unknown` 从 33 turns / 45 单元降至 22 turns / 31 单元，完整对话从 89 turns 降至
67 turns，状态仍为 `partial`。剩余未知项必须人工回听或保留待确认，不能仅为减少碎片而猜测。

新增/更新产物位于 Git 忽略目录 `outputs/remote_programming_40/t070_sortformer_pilot/`，文件名
带 `_smoothed`，并保留原始未平滑版本作审计对照。针对性测试覆盖同人短空洞、重叠歧义、
不同 speaker 边界和跨 ASR window 桥接；整仓测试 105 passed，`ruff check .` 通过。

## 2026-07-15：T070 LLM speaker 语义全连接实验

用户进一步要求用大语言模型判断并连接全部残余“待分离”，并授权直接复用项目 `.env`。
新增 `speaker_semantic_resolution.py` 与 `resolve_speaker_gaps_with_llm.py`：先按完整 consultation
和 ASR 原顺序聚合未知 run，再把带 `speaker_0/1/2` 标签的完整 noisy ASR 对话与全部 gap
合并为一次提示。模型只能从本病例已有声学标签中选择，不得创建 doctor/patient 角色、修改
ASR 文字或输出诊疗解释；响应必须逐 gap 满足严格 JSON schema。脚本支持 prompt-only、缓存、
重试、默认 0.80 confidence gating，以及显式 `--force-resolve-all` 实验模式。

本轮读取 `.env` 的 `API_KEY` / `BASE_URL` / `MODEL_ID`，实际解析为
`Qwen3-Coder-Plus` 与 `https://llmapi.paratera.com`；密钥没有输出或写入运行记录。短空洞桥接后
的 31 个未知字词合并为 20 个连续 gap。一次 API 请求成功返回 20/20 决策：6 个高置信、14 个
中置信；reason code 为 12 个 `same_sentence_continuation`、4 个 `turn_taking`、1 个
`question_answer`、3 个 `uncertain_best_guess`。按用户要求的 forced 模式应用后，31/31 字词
全部有展示 speaker，22 个进入 `speaker_0`、9 个进入 `speaker_1`；完整病例由短空洞版 67
turns 降为 43 turns，unknown 31→0。

为避免“全连接”掩盖证据边界，31 个字词的原始 acoustic `speaker_label=None` 与 11 个
`no_overlap`、18 个 `ambiguous_overlap`、2 个 `missing_timestamp` 状态均未改写；最终来源严格
分成 681 个 `nvidia_sortformer_time_overlap/v1`、14 个
`same_speaker_short_gap_bridge/v1`、31 个 `llm_semantic_speaker_resolution/v1`。conversation
状态不是声学 `complete`，而是 `semantic_complete`；HTML speaker 标签显示“含语义补全”，并
提示这不是声纹真值。该版本仅用于实验展示和人工回听优先级，不得作为 speaker reference、
DER/JER 输入或声学质量结论。

主要新产物均在 Git 忽略目录 `outputs/remote_programming_40/t070_sortformer_pilot/`：semantic
ASR JSONL、window/conversation review JSONL、CSV、交互 HTML、prompt、响应缓存和运行摘要。
新增测试覆盖 prompt gap、强制回写保留声学证据和 confidence gating；整仓测试 108 passed，
`ruff check .` 通过，最终 HTML 的 2 个内联 JavaScript 块通过 Node 语法解析。下一步在 5 例
阶段同时保留 acoustic-only、short-gap 和 semantic 三版，并人工回听中低置信及重叠 gap。

## 2026-07-15：T058/T064/T066/T070 中文 5 例代理鲁棒性 pilot

用户要求把已经跑通的中文 1 例流水线继续扩展，并以可展示的图/表作为阶段验收；在暂时没有
clean transcript 的前提下，允许先选择 5–10 例并用强 LLM 修复 noisy transcript 形成代理
clean。为避免把自动修复伪装成人工金标准，本轮固定选择 `case_0068`、`case_0057`、
`case_0040`、`case_0008`、`case_0021` 五例，覆盖 4.7–37.9 分钟、预期 K=2/4/5/6、短长音频
与中英混说信号；所有 proxy 记录显式保存未听音频、非人工、非医生确认、非 gold 和不可正式
质量声称标志。

首先优化 `preprocess_asr_audio.py`：旧实现对每个 30 秒窗口重新打开并 seek MP3，批处理性能
很差；现在每个源音频只解码/重采样一次，再从内存确定性切窗。5 例共输出 152 个 16 kHz mono
PCM16 窗口和 5 个整例 WAV，总实际时长 4,475.627 秒。新增预处理测试覆盖内存切片边界。

Parakeet Hybrid auxiliary-CTC confidence 152/152 成功，产生 9,458 个词/字审阅单元，转写
84.87 秒、RTF 0.01896、CUDA 峰值 allocated 2.465 GiB。从 Windows 挂载 `.nemo` 的冷恢复
耗时 1,221.44 秒；复制同 SHA-256 checkpoint 到 WSL 持久缓存后，acoustic 5-best 恢复降为
35.43 秒，转写 40.45 秒、RTF 0.00904。152/152 窗均有多个去重 beam，共 692 个 beam。

Streaming Sortformer 对 5 个整例 5/5 成功。原始声学 ASR word 时间映射为 8,637/9,458
（91.32%）；可审计同人短空洞桥接 193 个 word 后，展示覆盖为 8,830/9,458（93.36%），没有
桥接重叠歧义。无人工 RTTM，因此不报告 DER/JER；其中 K=5/6 病例超过模型最多 4-speaker 输出
上限，映射率也不是 speaker 准确率。

医学实体 LLM 筛选完成 152/152 窗、152 次 API 请求，181 个输入 mention 中 147 个与 ASR
对齐，形成 340 个医学 word 和 73 个黄/红医学 span。病例级审阅包包含 5 例、1,059 turns、
green/yellow/red=6,620/1,892/946；交互 HTML 支持接受 ASR、选择候选、手工编辑、拒绝、无法
判断、本地恢复和 JSONL 下载。acoustic 5-best 只为 11/73 个 span 提供局部候选；本轮没有对
125 个不确定词逐一发起完整对话 LLM 候选请求，不能声称 5 例候选覆盖已经充分。Codex in-app
browser runtime 连续初始化超时，静态 HTML/SVG 结构与文件完整性已检查，但真实点击、回听和
下载回放仍未验收。

新增 `build_chinese_proxy_references.py`，每例融合推荐 speaker/source 转录、医学先验
Qwen3-ASR 与医学先验 Paraformer，由强 LLM 保守生成 5/5 代理参考、代理关键事实、证据词和
不确定项。新增 `attach_proxy_references_to_asr.py` 把病例级 proxy 指针附到 152 个窗口，并修复
病例摘要 reference bundle 对同一共享路径重复展开的问题。使用同一 LLM、prompt、schema 与
解码条件完成 5 个 noisy + 5 个 proxy 病例摘要，10/10 成功。病例摘要均标注为研究输出，不
构成临床建议。

为体现本课题的“病例信息整理与鲁棒性”，新增中文 pilot 评估模块和无第三方依赖的 SVG 图表
生成器。除 Proxy CER 外，加入：CIPS（医学术语/否定/数字单位/侧别保持加权）、代理事实文本
召回、黄+红可检测错误召回、审阅字符比例、proxy ECE/Brier、risk-coverage/AURC，以及同一
病例摘要模型在 noisy/proxy 输入上的事实稳定性。5 例 macro 结果为 Proxy CER 21.2%、CIPS
88.0%、代理事实文本召回 75.1%、黄+红可检测错误召回 79.5%、审阅字符比例 28.8%、Proxy
word ECE 0.0510、声学 speaker 映射覆盖 91.0%、病例摘要事实 F1 35.7%、critical fact recall
33.9%。micro 可检测错误率从 green 3.3% 增至 yellow 19.3% 和 red 50.2%，说明三档风险具有
清晰排序；摘要稳定性明显更低，显示下游病例整理对转写噪声敏感。

主要展示产物位于 Git 忽略目录
`outputs/remote_programming_40/t058_pilot5/report/`：逐例 CSV、聚合 JSON、Markdown、汇总
HTML，以及工程覆盖、代理鲁棒性、颜色错误分层、risk-coverage、下游病例摘要稳定性五张
SVG。交互页面位于
同级 `doctor_review_pilot5.html`。完整方法、边界、指标定义和下一步见
`docs/t058_t066_chinese_pilot5_robustness.md`。本轮通过“5 例工程运行 + 代理探索评估 + 可展示
图表”门槛，但没有真实人工 confirmed transcript 或人工 reference，不能声称正式质量提升；
最终整仓 120 tests 通过、`ruff check .` 通过，2 个内联 JavaScript 块通过 Node 语法解析，5 张
SVG 均通过 XML 结构检查。下一步优先完成 1 例真实浏览器试审和固定 5 例听音频 reference，
再决定是否扩到 40/40。
