# 面向临床 ASR 置信度交互审阅与病例信息整理鲁棒性评估

这是一个研究型 Python 项目，用于评估临床 ASR 转写噪声对病例信息整理任务的影响，并重点探索 **音频 → ASR → noisy transcript + 置信度 → 医生实时交互确认 → confirmed transcript** 的流程。

2026-07-01 起，项目主线调整为：置信度主要来自 ASR 输出层，而不是 noisy→repair 的文本修复层。系统应在生成 noisy transcript 的同时保留词级、span 级或片段级置信度与 top-k 候选，让医生通过颜色提示和点击选择快速确认转写。2026-07-07 起，审阅范围进一步调整为“医学实体优先”：先用 LLM 识别疾病、症状、药物、检查等医学实体，再只对这些实体显示绿/黄/红置信度和生成候选，其他上下文词显示为普通黑字。医生反馈可作为后续 ASR 微调或候选排序扩展，但暂不作为近期主线。

## 研究问题

远程随访和医患对话中的 ASR 转写常见问题包括医学术语识别错误、药名错误、否定词遗漏、说话人混淆、重叠说话和口音导致的误识别。本项目当前关注三个层次：

1. ASR 置信度主线：从音频生成 noisy transcript，同时输出词级/片段级置信度、时间戳和 top-k / n-best 候选；
2. 医生交互确认：优先对 LLM 识别出的医学实体按置信度用绿色/黄色/红色提示风险，医生点击中低置信度医学实体片段选择、编辑或拒绝候选；
3. 下游鲁棒性评估：比较 raw ASR / doctor-confirmed / reference 输入对病例整理任务的影响。

具体关注这些噪声如何影响：

- 症状、病史、用药、检查等结构化信息抽取；
- 病例摘要生成；
- 诊疗计划或随访计划整理；
- 医患双方信息归属判断。

在系统形态上，计划引入医生实时审阅：

- 高置信度医学实体：绿色显示，默认低优先级审阅；
- 中置信度医学实体：黄色显示，医生可按需点击检查 top-k 候选；
- 低置信度医学实体：红色显示，优先提示医生确认；
- 非医学实体上下文词：普通黑字显示，不进入候选生成和强制反馈；
- 反馈数据：医生选择、编辑、拒绝和最终 confirmed transcript 先作为研究日志保存，后续可用于置信度校准、主动学习或 ASR/候选排序微调。

## 计划使用的数据集

| 数据集 | 主要价值 | 注意事项 |
|---|---|---|
| DISPLACE-M 2026 | 真实基层医疗互动、多语种/代码混合、远场麦克风、重叠说话 | 需要挑战注册和数据使用条款 |
| AfriSpeech-Dialog | 长对话、非洲口音、多说话人，含医疗场景 | 适合分析口音与 ASR 错误 |
| ACI-Bench | 医患对话文本，部分含 doctor/patient tag swap | 已本地接入，可作为文本侧历史资产、界面假数据和下游评估参考 |
| PriMock57 / Fareez OSCE | 医患音频和人工转录 | 适合第一阶段 ASR 置信度闭环；人工转录可作 clean/reference，不能直接当 noisy |
| MedDialogue-Audio | 合成英语医疗对话音频，含噪声版本 | 可用于 ASR 置信度、声学噪声和医生审阅流程验证 |

## 项目结构

```text
configs/                         配置样例
data/                            数据目录，默认不提交真实数据
docs/                            研究计划与数据说明
notebooks/                       探索性分析
outputs/                         实验输出
scripts/                         命令行脚本
src/clinical_asr_robustness/     项目源码
tests/                           基础测试
AGENTS.md                        Codex 协作说明
```

## 快速开始

本项目当前实验默认使用 WSL Conda 环境 `clinical-asr`：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_asr_review_pipeline.py
Start-Process outputs\primock57\t036_doctor_review_demo\doctor_review_demo.html
```

这条命令默认复用已有 T028/T037 ASR 输出，并自动生成医学实体优先审阅样本和最终 HTML demo：

- `outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html`
- `outputs/primock57/asr_review_pipeline/asr_review_pipeline_run.json`

如果需要从音频重新跑 NeMo ASR 与 n-best，增加 `--run-asr`；全量重跑增加 `--asr-limit 0`。更多参数见 `scripts/README.md` 和 `scripts/run_asr_review_pipeline.py --help`。

常用验证：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
```

WSL/NeMo 详细环境与 Codex 沙箱申请方式见 `docs/wsl_environment.md`。如果只做非常轻量的本地代码浏览或临时开发，才考虑普通 Python venv：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

如果暂时不安装项目，也可以先阅读：

- `docs/research_plan.md`
- `docs/dataset_notes.md`
- `configs/datasets.example.yaml`
- `configs/eval_tasks.example.yaml`

涉及外部 LLM API 的 T038 医学实体抽取默认支持项目根目录 `.env`：

```dotenv
API_KEY="<your-api-key>"
BASE_URL="https://llmapi.paratera.com"
MODEL_ID="Qwen3-Next-80B-A3B-Instruct"
```

`.env` 已被 `.gitignore` 忽略；可从 `.env.example` 复制后填写，不要提交真实密钥。

## 当前状态

项目已完成初始骨架搭建，并已接入 ACI-Bench 文本侧数据切片与 paired manifest。2026-07-01 后，下一步主线是构建 ASR 置信度交互闭环：选择含音频样本，运行或接入 ASR，输出 noisy transcript + confidence + top-k alternatives，设计绿/黄/红医生审阅界面，形成 confirmed transcript，并在一个下游病例整理任务上比较 raw ASR / confirmed / reference 的差异。

已完成的文本 repair schema 和 ACI-Bench 错误分析保留为辅助资产；近期不要再把 repair 置信度自动采纳作为核心系统逻辑。

## TODO 与交接机制

项目当前状态、当前焦点和下一步任务记录在 `docs/todo.md`。它是新对话/新任务的首要入口，应保持短小；历史任务流水和较完整交接记录归档在 `docs/task_records.md`。

继续开发或实验前，Codex 应先阅读 `docs/todo.md`；完成较完整的任务后，应同步更新 `docs/todo.md`，并在 `docs/task_records.md` 追加记录，避免进展只留在聊天记录里。
