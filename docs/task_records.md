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

新增 CTC frame logits/log_probs/posterior 到 word-level confidence 的项目侧流水线：src/clinical_asr_robustness/ctc_word_confidence.py 支持 entropy/max-prob frame confidence、CTC token collapse、BPE word 聚合和 .npz frame artifact 读写；T028 导出脚本新增 --word-confidence-source ctc_frame_distribution、--save-frame-distributions、--frame-distribution-kind log_probs|posterior，可把 sr_words[].confidence 改为 frame-derived word confidence，并在 metadata 中标明来源。新增 	ests/test_ctc_word_confidence.py 和 docs/t043_ctc_word_confidence.md；验证目标 pytest 9 passed、targeted ruff 通过。局限：尚未对真实 PriMock57 音频复跑，下一步检查 token→word 对齐、artifact 体积和医学实体待审 span 变化。

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