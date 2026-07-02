# 项目任务记录归档

更新时间：2026-07-02

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
| T031 | 未开始 | 评估 confidence 校准与 top-k 覆盖。 |
| T032 | 未开始 | 跑通 ASR 输出层最小闭环并记录实验。 |
| T033 | 已完成 | 迁移 `Speech-main` 必要文件与权重到 project。 |
| T034 | 已完成 | 精简 `docs/todo.md`、新增 `docs/task_records.md`，并记录 WSL 沙箱申请方式。 |
| T035 | 已完成 | 医生/模拟审阅者反馈日志与 `confirmed_transcript` 回放生成。 |
| T036 | 已完成 | 静态/轻量医生审阅 HTML demo，支持高亮、候选选择和反馈 JSONL 下载。 |
| T037 | 已完成 | 生成/接入真实 NeMo sequence-level n-best 候选，并重跑 T029/T030/T036 审阅 demo。 |

## 完整任务记录

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
