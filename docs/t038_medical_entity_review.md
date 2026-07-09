# T038 医学实体优先 ASR 审阅范围

更新时间：2026-07-07

本任务把原先“所有低/中置信度词组都高亮和生成候选”的逻辑，改为更贴近医生交互场景的版本：

**只有 LLM 判断为医学实体/医学专有术语的词组，才保留绿/黄/红颜色；非医学词只作为黑字上下文显示。**

## 目标

T038 位于 T028 和 T029 之间：

```text
T028 ASR confidence
  → T038 LLM 医学实体抽取与审阅范围 gating
  → T029 n-best/top-k 候选对齐
  → T030/T036 审阅样本与 HTML demo
  → T035 confirmed transcript
```

T038 不替代 ASR 置信度；它只决定哪些词值得医生重点确认。

## 新增文件

- 逻辑模块：`src/clinical_asr_robustness/medical_entity_review.py`
- CLI：`scripts/extract_medical_entity_review_spans.py`
- 测试：`tests/test_medical_entity_review.py`

## 处理规则

1. 对每条 `ASRConfidenceRecord.asr_transcript` 调用 OpenAI-compatible LLM API，抽取医学实体：
   - 疾病/诊断；
   - 症状体征；
   - 药物/剂量；
   - 检查检验、影像；
   - 操作/手术；
   - 解剖部位；
   - 医学缩写和重要临床属性。
2. 将 LLM 返回的实体 mention 对齐到 ASR word index，并做轻量后处理：
   - 裁掉实体 span 左右的普通问句词/上下文词，例如 `do`、`you`、`mean`、`your`、`what`、`kind`、`of`、`talk`、`about`；
   - 裁剪后只剩普通词时丢弃，避免普通词被染成绿/黄/红；
   - 对 `and/or` 连接的粗实体做轻量切分，减少连接词被误染色。
3. 用小型医学关键词表做兜底补漏：
   - 短语：`tummy pain`、`loose stools/loose stool`；
   - 单词/变体：`diarrhea/diarrheea/diarrhoea`、`pain`、`feverish`、`temperature`、`sweating`、`vomiting/vomit`、`blood`、`asthma`、`inhaler(s)`、`medication(s)`、`weak`、`shaky`、`stool(s)`、`fluid(s)`、`symptom(s)` 等。
4. 给 `asr_words[].metadata.medical_entity_review` 写入界面显示策略：
   - 医学实体词：按原 ASR 置信度显示 `green/yellow/red/unknown`；
   - 非医学词：显示 `neutral`，HTML 中渲染为普通黑字。
5. 清空原先按所有低/中置信度词得到的 `uncertain_spans`。
6. 只为“医学实体且非 green”的范围生成新的 `uncertain_spans`，供 T029 生成候选、T036 点击审阅、T035 回放反馈。
7. 高置信度医学实体会显示绿色，但不进入 `uncertain_spans`，因此默认不弹候选面板。

这样可避免医生被普通低置信度上下文词打扰，把交互成本集中到医学关键信息上。

## API 配置

推荐使用项目根目录 `.env` 保存本项目专用 key，避免和其他项目的 key 混在全局环境变量里。`.env` 已被 `.gitignore` 忽略；可以复制 `.env.example` 后填写：

```powershell
Copy-Item .env.example .env
```

`.env` 支持两套命名。通用命名：

```dotenv
API_KEY="<your-api-key>"
BASE_URL="https://llmapi.paratera.com"
MODEL_ID="Qwen3-Next-80B-A3B-Instruct"
```

也支持项目专用命名：

```dotenv
PARATERA_API_KEY="<your-api-key>"
PARATERA_BASE_URL="https://llmapi.paratera.com"
PARATERA_MODEL="Qwen3-Next-80B-A3B-Instruct"
```

解析优先级为：CLI 显式参数 → 项目 `.env` → 系统环境变量 → 默认值。

当前默认使用：

- `PARATERA_BASE_URL=https://llmapi.paratera.com`
- `PARATERA_MODEL=Qwen3-Next-80B-A3B-Instruct`
- API key 支持 `.env` 中的 `PARATERA_API_KEY` 或 `API_KEY`

不要把 API key 写入代码、运行记录或 Git。`.env` 可以用于本地隔离，但也不要提交。

如果模型选择需要调整，可通过 `--model` 或 `PARATERA_MODEL` 切换到同一服务支持的其他文本模型。

## 可复现命令

先从 T028 输出生成医学实体限定版 ASR confidence JSONL：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_medical_entity_review_spans.py `
  --input-jsonl outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl `
  --output-jsonl outputs/primock57/t038_medical_entity_review/primock57_asr_confidence_medical_entities.jsonl `
  --entity-cache-jsonl outputs/primock57/t038_medical_entity_review/primock57_medical_entities_llm.jsonl `
  --env-file .env
```

再把 T038 输出交给 T029，只对医学实体 review spans 生成候选：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/extract_asr_nbest_candidates.py `
  --input-jsonl outputs/primock57/t038_medical_entity_review/primock57_asr_confidence_medical_entities.jsonl `
  --nbest-jsonl outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl `
  --output-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl
```

随后按 T030/T036 生成审阅样本和 HTML：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/build_asr_review_samples.py `
  --input-jsonl outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_medical_entity_candidates.jsonl `
  --output-jsonl outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.jsonl `
  --output-csv outputs/primock57/t030_review_samples/primock57_medical_entity_review_spans.csv `
  --output-html outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.html `
  --interactive-html
```

## 缓存与复跑

`--entity-cache-jsonl` 会保存 LLM 抽取结果。缓存存在时，脚本默认复用缓存，避免重复调用外部 API；如果确实要重抽实体，加：

```powershell
--force-refresh-entities
```

缓存和输出都位于 `outputs/`，默认不提交 Git。

## 当前验证

已新增本地单元测试，覆盖：

- LLM JSON/fenced JSON 解析；
- 医学实体 mention 到 ASR word range 的对齐；
- LLM 粗 span 的普通词裁剪和非医学误报丢弃；
- 明显医学关键词兜底补漏；
- 非医学低置信词显示为 neutral 黑字且不进入审阅；
- 医学低置信实体生成 `uncertain_spans`；
- 医学高置信实体显示绿色但不生成候选 span；
- T029 只为医学实体 span 生成候选；
- T036 HTML 使用 `neutral` 和 `medical-entity` 显示策略。

验证命令：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest tests/test_medical_entity_review.py tests/test_review_workflow.py --basetemp=.pytest_tmp
```

本次运行结果：`12 passed`。全量 `pytest --basetemp=.pytest_tmp` 结果：`42 passed`。

## 局限与后续

- 医学实体识别仍依赖 LLM 输出质量；当前关键词表只是轻量兜底，不是完整医学术语词典。
- 当前 T038 只为非 green 医学实体生成候选；如果希望医生也能点击绿色医学实体查看候选，需要扩展 schema，使“可点击实体 span”和“uncertain span”解耦。
- 实体对齐主要依赖 LLM 返回字符偏移、原文字符串匹配和 token exact match；复杂标点、中文无空格 ASR 或 ASR 错词导致的 mention 不一致，后续需要更强的模糊对齐。
- LLM 只负责识别医学实体，不应把 LLM 输出的实体置信度混同于 ASR 词级置信度。
