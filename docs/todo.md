# 项目 TODO 与当前交接板

更新时间：2026-07-02

本文档是新对话/新任务的首要入口，只保留“现在该做什么”和少量必要背景。历史任务、长变更记录和早期路线演化已迁入 `docs/task_records.md`；除非需要追溯历史决策，后续 Codex 不要默认完整阅读历史归档。

## 维护规则

- 开始工作时优先阅读本文件；再按当前任务需要阅读 README、研究计划、配置或专项文档。
- 完成较完整的任务后，同步更新：
  - `docs/todo.md`：当前焦点、下一步、阻塞/待确认、最近完成；
  - `docs/task_records.md`：追加一条更完整的任务记录。
- 本文件只保留最近少量已完成任务用于定位上下文；太久远的修改记录放入 `docs/task_records.md`。
- 不要记录真实患者隐私、未脱敏病例正文、本地密钥或受限数据细节。
- 推荐任务编号格式：`T001`、`T002`；推荐状态：`未开始`、`进行中`、`已完成`、`阻塞`、`暂缓`。

## WSL/clinical-asr 快速调用

以后在本项目运行 Python、pytest、ruff、NeMo、ASR 或实验脚本时，默认使用 WSL 中的 Conda 环境 `clinical-asr`，直接调用解释器：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python --version
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/check_wsl_asr_env.py --restore-model
```

Codex 沙箱注意：如果直接运行 WSL Python 出现权限/沙箱相关失败，或出现“发行版不存在”但 `wsl.exe -l -v` 能看到 `Ubuntu-22.04`，不要反复探索；应立即申请提升权限，建议申请可复用前缀：

```text
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python
```

2026-07-02 已验证并获本会话前缀授权：该命令返回 `Python 3.10.20`，`pytest 9.1.1` 可用。WSL 启动时可能打印 localhost 代理警告；只要命令退出码为 0，可先视为不影响当前 ASR/pytest 调用。更多环境细节见 `docs/wsl_environment.md`。

## 当前项目快照

项目当前主线是：

**音频 → ASR → noisy transcript + ASR token/span/segment 置信度 → 绿/黄/红风险高亮 → 医生点击 top-k/n-best 候选并确认 → confirmed transcript → 下游病例信息整理鲁棒性评估。**

2026-07-01 起，置信度主要放在 ASR 输出层，不再把 noisy transcript → repair 的文本修复置信度作为近期主线。文本 repair、LLM/规则候选和反馈微调只作为后续辅助扩展。

本周目标调整为产出最小 demo：先把 PriMock57 音频跑出 transcript、word/segment confidence、timestamps、uncertain spans 和 n-best/top-k 候选，再生成绿/黄/红审阅样本，并加入医生反馈记录、`confirmed_transcript` 生成和静态/轻量 HTML 交互界面。T037 已接入真实 NeMo beam/n-best，并重跑 T029/T030/T036，使审阅 HTML 中黄/红 span 能看到可选 ASR 候选。下一步优先进入 T031/T032：做 confidence/top-k 初评，并把第一批 ASR 输出层最小闭环整理成可复现实验记录。

截至 T037，用户第一周要实现的主干设计 **“音频数据 → ASR → noisy transcript + 置信度 → 医生交互选择 + 交互界面设计”** 已形成可运行闭环：T025/T028 负责音频输入与 ASR confidence，T037/T029 负责真实 n-best/top-k 候选接入，T030/T036 负责绿/黄/红审阅样本与 HTML 交互界面，T035 负责反馈回放生成 `confirmed_transcript`。尚未完成的是下一阶段评估层：confidence 校准、top-k 覆盖率、医生确认成本和下游鲁棒性评估。

## 当前焦点

| 任务编号 | 状态 | 任务 | 当前说明 |
|---|---|---|---|
| T025 | 已完成 | PriMock57 ASR 输入 manifest | 已生成 5 条 consultation / 10 路 doctor/patient 音频 manifest；不含正文。 |
| T033 | 已完成 | 迁移 `Speech-main` 必要资产到 project | 权重在 `data/external/asr_models/nemo/`，NeMo 快照在 `third_party/speech_main/`；后续不能依赖外部 `Speech-main`。 |
| T026 | 已完成 | WSL/NeMo 环境与 1 路音频 smoke test | 已在 WSL `clinical-asr` 中跑通 PriMock57 patient 音频，输出 transcript、timestamps、`word_confidence`。 |
| T034 | 已完成 | 精简 TODO 并建立历史归档 | 本文件变为短入口；历史流水迁入 `docs/task_records.md`；WSL 沙箱申请方式写入文档。 |
| T027 | 已完成 | 设计项目侧 ASR confidence JSONL/schema | 已新增 Pydantic schema、JSONL 读写工具、文档和测试；明确 timestamp/confidence 数量不一致时以 ASR 输出词为锚点。 |
| T028 | 已完成 | 实现 NeMo entropy confidence 导出适配脚本 | 已新增批量导出脚本、Hypothesis→schema 适配模块、文档和测试；实跑 `--limit 2` 生成 doctor/patient 两路 ASR confidence JSONL。 |
| T029 | 已完成 | 实现 ASR n-best/top-k 候选抽取策略 | 已新增策略模块、CLI、文档和测试；支持 sequence-level n-best 写入，并用词级 diff 映射到 uncertain span。 |
| T030 | 已完成 | 生成绿/黄/红可审阅样本包 | 已新增 review sample JSONL、span CSV 和 HTML 生成链路，见 `docs/t030_t035_t036_review_workflow.md`。 |
| T035 | 已完成 | 医生反馈与 confirmed transcript 生成 | 已支持 `accept_asr`、选择候选、手动编辑、拒绝、无法判断，并可回放生成 `confirmed_transcript`。 |
| T036 | 已完成 | 静态/轻量医生审阅小界面 | 已生成单文件 HTML demo：高亮 transcript、点击 span 查看候选、导出反馈 JSONL。 |
| T037 | 已完成 | 生成/接入真实 ASR n-best 候选并重跑审阅 demo | 已用 NeMo `beam_batch` 导出 2 路 PriMock57 sequence-level n-best；confidence 修正后重跑 T029/T030/T036，当前为 10 个 sequence alternatives、2 个 span alternatives、74 个黄色待审阅 span，其中 2 个带候选。 |
| T031 | 未开始 | 评估 confidence 校准与 top-k 覆盖 | ASR 输出层稳定后，用 reference 对齐统计分桶错误率、ECE/NCE、top-k 覆盖。 |
| T032 | 未开始 | 跑通 ASR 输出层最小闭环 | 第一批 PriMock57 样本形成可复现实验记录；最终需证明外部 `Speech-main` 删除/重命名后仍可运行。 |

## ASR 输出层已确认路线

| 阶段 | 子任务 | 状态/验收重点 |
|---|---|---|
| 代码理解 | T024 | 已完成；NeMo 支持 entropy confidence，但 top-k/span 候选和标准脚本输出需要项目侧适配。 |
| 决策确认 | D001-D010 | 已完成；本地 NeMo、离线批处理、双路 ASR 后合并、sequence-level n-best 对齐 uncertain span、默认 confidence 参数、启发式阈值、word+segment 输出。 |
| 数据入口 | T025 | 已完成；PriMock57 5 条 consultation / 10 路音频 manifest。 |
| 外部资产迁移 | T033 | 已完成；后续运行不依赖外部 `Speech-main`。 |
| 环境与模型 | T026 | 已完成；WSL `clinical-asr`、project 内权重、1 路音频 smoke test 均通过。 |
| Schema | T027 | 已完成；定义 ASR confidence JSONL/Pydantic schema，见 `docs/asr_confidence_schema.md`。 |
| ASR 导出 | T028 | 已完成；项目侧 adapter 输出 transcript、timestamps、word/segment confidence 和 alignment 诊断。 |
| 候选抽取 | T029 | 已完成；V0 支持 sequence-level n-best 与 uncertain span 对齐，见 `docs/t029_asr_nbest_candidates.md`。 |
| 真实候选接入 | T037 | 已完成；生成 NeMo beam/n-best JSONL，跑 T029 输出真实 span candidates，并重跑 T030/T036 demo。 |
| 审阅样本 | T030 | 已完成；生成绿/黄/红 JSONL/CSV/HTML。 |
| 反馈生成 | T035 | 已完成；记录医生选择/编辑/拒绝/无法判断，并生成 confirmed transcript。 |
| Demo 界面 | T036 | 已完成；静态/轻量 HTML 展示高亮、候选面板和反馈 JSONL 下载。 |
| ASR 层评估 | T031 | 待做；报告 confidence/top-k 初步质量。 |
| 最小闭环 | T032 | 待做；形成第一批 ASR 输出层实验记录。 |

## 下一步优先任务

| 优先级 | 任务编号 | 任务 | 验收标准 |
|---|---|---|---|
| P0 | T031 | confidence/top-k 初评 | 用 reference 统计高/中/低分桶错误率、医学概念错误率、top-k 覆盖率。 |
| P0 | T032 | ASR 输出层最小闭环记录 | 第一批样本可复现；记录失败案例与外部路径独立性，并串起 T028→T029→T030→T036→T035。 |
| P2 | T019/T023 | 医生审阅流程与交互指标 | 在 demo 跑通后，细化真实医生审阅流程、反馈日志字段和人工成本指标。 |
| P2 | T007/T008 | 下游鲁棒性评估 | 下一阶段接入症状/医学实体抽取或 sectioned note 信息保持评估。 |
| P3 | T006/T018 | 文本 repair 扩展 | 暂缓；仅在 ASR top-k 不足时作为辅助候选生成。 |

## 阻塞/待确认

- 当前无方案级阻塞；T037/T029/T030/T035/T036 已把 ASR 候选与审阅 demo 串通，下一步默认推进 T031/T032。
- 已修正 T028 `entropy_norm=exp` 导致 word confidence 全部贴近 0、界面全红的问题：当前 demo 默认改为论文同样支持的 `entropy + tsallis + alpha=0.33 + entropy_norm=lin + aggregation=mean`。`limit2` 重跑后 1145 个词中 1031 个 green、114 个 yellow、0 个 red；T030/T036 已重建为 74 个黄色待审阅 span，其中 2 个带 n-best 候选。后续 T031 仍需结合 reference 正式校准阈值和分桶错误率。
- T035/T036 的第一版可由研究者或模拟审阅者操作，不要求真实医生参与；界面输出已标注为研究 demo，不构成临床建议。
- WSL 命令在 Codex 沙箱中可能需要提升权限；见上方“WSL/clinical-asr 快速调用”，不要重复探索。
- T028 已按 T027 schema 处理 T026 发现的细节：`word timestamp` 数量可能比 `word_confidence` 多 1；规则是以 `asr_transcript.split()` 的 ASR 输出词为锚点，额外 timestamp/confidence 写入 `alignment.dropped_extra_*`，缺失项保留词并标记 `alignment_status`。
- 后续脚本不得依赖外部 `D:\...\Speech-main`；只能使用 project 内 `third_party/speech_main/` 和 `data/external/asr_models/nemo/`。
- PriMock57 本地数据、processed 输出和 ASR 结果默认不提交 Git；不要写入未脱敏正文或隐私信息。
- DISPLACE-M 仍是后续扩展数据集，接入前需确认许可、注册要求和字段结构。
- 尚未确认下游评估使用规则抽取器、本地模型、外部 API 还是人工标注；这不阻塞 ASR 输出层任务。

## 最近完成

| 日期 | 任务 | 产出/位置 |
|---|---|---|
| 2026-07-02 | 修正 T028 entropy confidence 默认归一化与 demo 全红问题 | `scripts/export_nemo_asr_confidence.py` 新增 `--confidence-method`、`--entropy-type`、`--entropy-norm`、`--confidence-alpha`，默认改为 `entropy_norm=lin`；`src/clinical_asr_robustness/nemo_confidence_export.py` 增加可配置 confidence 方法与分布统计；已重跑 `outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl`、T029/T030/T036，新的 HTML 位于 `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`。 |
| 2026-07-02 | T037 真实 NeMo n-best 候选接入并重跑审阅 demo | `src/clinical_asr_robustness/nemo_nbest_export.py`、`scripts/export_nemo_asr_nbest.py`、`docs/t037_nemo_asr_nbest_demo.md`、`tests/test_nemo_nbest_export.py`；本地输出位于 `outputs/primock57/t037_nemo_asr_nbest/`、`outputs/primock57/t029_asr_nbest_candidates/`、`outputs/primock57/t030_review_samples/`、`outputs/primock57/t036_doctor_review_demo/`；初次 T037 接入验证通过，后续 confidence 修正已重跑当前 demo。 |
| 2026-07-02 | T030/T035/T036 ASR 审阅样本、反馈回放与 HTML demo | `src/clinical_asr_robustness/review_workflow.py`、`scripts/build_asr_review_samples.py`、`scripts/apply_asr_review_feedback.py`、`scripts/build_doctor_review_demo_html.py`、`docs/t030_t035_t036_review_workflow.md`、`tests/test_review_workflow.py`；第一版先跑通无候选界面，T037 完成后已重跑为带真实 ASR 候选版本。 |
| 2026-07-02 | T029 ASR n-best/top-k 候选抽取策略 | `src/clinical_asr_robustness/asr_nbest_candidates.py`、`scripts/extract_asr_nbest_candidates.py`、`docs/t029_asr_nbest_candidates.md`、`tests/test_asr_nbest_candidates.py`。 |
| 2026-07-02 | T028 NeMo entropy confidence 导出适配脚本 | `scripts/export_nemo_asr_confidence.py`、`src/clinical_asr_robustness/nemo_confidence_export.py`、`docs/t028_nemo_confidence_export.md`、`tests/test_nemo_confidence_export.py`；本地实跑输出位于 `outputs/primock57/t028_nemo_asr_confidence/`。 |
| 2026-07-02 | T027 ASR confidence JSONL/schema | `src/clinical_asr_robustness/asr_confidence.py`、`docs/asr_confidence_schema.md`、`tests/test_asr_confidence_schema.py`。 |
| 2026-07-02 | T034 精简 TODO 与历史归档 | `docs/todo.md`、`docs/task_records.md`、`docs/wsl_environment.md`、`AGENTS.md`、`README.md`。 |
| 2026-07-02 | 验证 Codex 中 WSL `clinical-asr` 调用 | 已验证 `Python 3.10.20` 与 `pytest 9.1.1`；建议授权前缀见本文 WSL 小节。 |
| 2026-07-02 | T026 NeMo 音频 smoke test | `scripts/run_nemo_asr_smoke_test.py`、`docs/t026_nemo_smoke_test.md`；输出位于 `outputs/primock57/t026_nemo_smoke_test/`。 |
| 2026-07-02 | T025 PriMock57 ASR manifest | `scripts/build_primock57_asr_manifest.py`、`docs/primock57_asr_manifest.md`；本地 manifest 位于 `data/interim/primock57/manifests/`。 |
| 2026-07-02 | T033 `Speech-main` 资产迁移 | 权重、NeMo 快照和来源说明迁入 project；见 `third_party/speech_main/README.md`。 |
| 2026-07-01 | 主线调整为 ASR 置信度交互审阅 | README、研究计划、TODO、AGENTS 均已体现 ASR confidence 优先。 |

更多历史记录见 `docs/task_records.md`。

## 建议工作流

1. 先读本文件，确认当前焦点与下一步任务。
2. 需要背景时再读专项文档：
   - ASR 决策：`docs/asr_confidence_decisions.md`
   - NeMo 代码理解：`docs/asr_confidence_nemo_code_notes.md`
   - WSL 环境：`docs/wsl_environment.md`
   - T026 smoke test：`docs/t026_nemo_smoke_test.md`
   - T028 NeMo 导出：`docs/t028_nemo_confidence_export.md`
   - T029 候选抽取：`docs/t029_asr_nbest_candidates.md`
   - T030/T035/T036 审阅 demo：`docs/t030_t035_t036_review_workflow.md`
   - PriMock57 manifest：`docs/primock57_asr_manifest.md`
3. 涉及 Python/pytest/ruff/NeMo/ASR 时，默认用 WSL `clinical-asr`。
4. 涉及数据时，只记录文件指针、许可和统计摘要；不要提交正文、真实隐私或受限数据。
5. 结束时更新本文件，并在 `docs/task_records.md` 追加较完整记录。

## 交接记录模板

```markdown
### YYYY-MM-DD：简短标题

- 完成：
- 修改文件：
- 验证：
- 遗留问题：
- 建议下一步：
```
