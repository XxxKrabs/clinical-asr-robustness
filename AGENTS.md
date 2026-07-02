# Codex 项目说明

本项目的工作语言优先使用中文。所有面向用户的说明、阶段汇报、研究记录和项目文档默认使用中文；代码标识符可使用英文，注释可中英混合，但应以清晰为先。

## 项目名称

面向临床 ASR 置信度交互审阅与病例信息整理鲁棒性评估

## 项目目标

本课题面向远程随访、基层医疗互动和医患对话中的 ASR noisy transcript，重点研究 **音频 → ASR → noisy transcript + 置信度 → 医生实时交互确认 → confirmed transcript** 的流程，并评估医生确认后的转写是否能提升症状抽取、病例摘要和诊疗计划整理质量。

2026-07-01 起，当前阶段的核心调整为：置信度主要放在 ASR 输出层，而不是 noisy transcript → repair 的文本修复层。近期工作应优先围绕 ASR 词级/片段级置信度、绿/黄/红风险高亮、医生点击 top-k 候选选择、confirmed transcript 和下游鲁棒性评估展开。文本 repair、LLM/规则候选和模型微调作为后续辅助扩展，暂不作为主线。

核心产出应包括：

- audio / clean reference / ASR noisy / doctor-confirmed transcript 对照数据；
- ASR token/span/segment 置信度、颜色等级、top-k/n-best 候选、阈值规则和医生反馈记录；
- 医学术语错误、药名错误、否定词遗漏、说话人混淆等错误类型分析；
- 症状抽取、病例摘要、诊疗计划整理等下游任务的鲁棒性评估；
- ASR 置信度校准、top-k 候选覆盖率、医生确认成本和 confirmed transcript 质量评估；
- 可演示的交互式系统原型设想或前端流程，包括绿/黄/红高亮、点击中低置信度片段调出候选、医生选择/编辑/拒绝和反馈日志；
- 术语纠错、说话人修复、LLM/规则/词表增强、多版本转写融合等辅助方法的扩展实验结果。

## 工作边界与安全要求

- 不要提交任何真实患者隐私信息、身份信息或未脱敏临床数据。
- `data/raw/`、`data/external/`、`data/interim/`、`data/processed/` 默认不纳入 Git 版本控制。
- 使用受限数据集前，先确认许可、挑战注册要求和数据使用条款。
- 不能把人工转录文本直接当作 noisy transcript；人工转录通常应视作 clean/reference。
- 对所有自动生成或修复后的病例摘要、诊疗计划，应明确标注为研究输出，不得视作临床建议。

## 推荐目录约定

```text
configs/                         配置样例与实验配置
data/
  raw/                            原始数据，不提交
  external/                       外部下载数据，不提交
  interim/                        中间处理结果，不提交
  processed/                      可复现实验数据，不提交
docs/                             研究计划、数据集记录、实验设计
notebooks/                        探索性分析
outputs/                          图表、评估结果、模型输出，不提交
scripts/                          命令行脚本
src/clinical_asr_robustness/      项目 Python 包
tests/                            基础测试
```

## 代码规范

- Python 版本建议为 3.10 或更高。
- 文本数据优先使用 UTF-8 编码。
- 数据样本建议使用 JSONL 保存，每行一个样本。
- 字段命名尽量稳定，例如：
  - `sample_id`
  - `dataset`
  - `split`
  - `clean_transcript`
  - `noisy_transcript`
  - `asr_confidence`
  - `confidence_level`
  - `asr_alternatives`
  - `confirmed_transcript`
  - `speaker_turns`
  - `error_tags`
  - `notes`
- 新增实验脚本时，优先支持命令行参数和配置文件，不要把本地绝对路径写死。

## 运行环境约定

- 以后在本项目运行 Python、pytest、ruff、NeMo、ASR 或实验脚本时，默认使用 WSL 中的 Conda 环境 `clinical-asr`，不要使用 Windows 侧 Python、WSL system Python 或 Conda `base` 环境，除非用户明确要求。
- 推荐直接调用解释器路径，避免 shell 激活状态不一致：
  `/home/krabs/miniforge3/envs/clinical-asr/bin/python`。
- 在 Codex/Windows PowerShell 中推荐直接使用：
  `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python ...`
- 如果 Codex 沙箱中直接调用 WSL Python 失败，或出现 `WSL_E_DISTRO_NOT_FOUND` 但 `wsl.exe -l -v` 能看到 `Ubuntu-22.04`，应立即申请提升权限，不要反复探索；建议申请前缀：
  `wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python`
- 常用验证命令：
  - `/home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp`
  - `/home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .`
  - `/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/check_wsl_asr_env.py --restore-model`
- WSL/NeMo 环境配置细节记录在 `docs/wsl_environment.md`；T026 当前状态和后续任务记录在 `docs/todo.md`。

## 实验记录要求

每次较完整的实验应记录：

- 数据来源、版本和许可状态；
- audio / clean reference / ASR noisy / confirmed transcript 的构造方式；
- ASR 系统、解码设置、置信度来源、时间戳、top-k/n-best 候选或 noisy transcript 来源；
- 颜色阈值设置、医生交互规则、反馈记录方式和 confirmed transcript 生成方式；
- 如使用文本 repair 辅助候选，应记录 repair 方法、候选生成方式和其与 ASR 原生置信度的区别；
- 错误类型标注规则；
- 下游任务提示词、模型或抽取器版本；
- 评价指标；
- 主要结论和失败案例。

## 推荐优先级

1. 先建立小规模 ASR 置信度闭环：少量音频样本、ASR noisy transcript、词级/片段级置信度、top-k 候选和 reference 对照。
2. 再加入医生交互流程：高置信度绿色、中置信度黄色、低置信度红色；医生点击黄/红片段选择、编辑或拒绝候选，并记录反馈。
3. 再扩展下游评估与系统原型：症状抽取、病例摘要、诊疗计划整理、前端高亮/候选选择界面。
4. 最后补充文本 repair、反馈微调和多版本融合：医生反馈可作为后续 ASR 微调或候选排序数据，但暂不作为近期主线。

## TODO 与交接机制

- 当前状态、当前焦点和下一步任务记录在 `docs/todo.md`；历史任务流水和较完整记录归档在 `docs/task_records.md`。
- `docs/todo.md` 是新对话/新任务的首要入口，应保持短小；除非需要追溯历史决策，不要默认完整阅读 `docs/task_records.md`。
- 开始较大的实现、实验或文档整理前，先阅读 `docs/todo.md`，再按任务需要阅读 README、研究计划、相关配置或专项文档。
- 完成较完整的任务后，应同步更新 `docs/todo.md` 的“当前焦点 / 下一步优先任务 / 阻塞 / 最近完成”，并在 `docs/task_records.md` 追加较完整记录。
- 不要在 TODO 中记录真实患者隐私、未脱敏病例内容、本地密钥或受限数据细节。

## 给后续 Codex 的提示

- 开始任何实现前，先阅读 `docs/todo.md`；再根据当前任务需要阅读 `README.md`、`docs/research_plan.md`、专项文档和相关配置文件。
- 如果用户要求“继续做实验”或“跑评估”，先检查音频数据、reference transcript、ASR 输出能力和许可状态是否存在；近期默认优先推进 ASR 置信度交互闭环，而不是文本 repair。
- 如需联网下载数据或安装依赖，应先说明原因并遵守当前环境权限。
- 遇到医学判断相关内容时，只做信息整理和研究评估，不提供诊疗建议。
