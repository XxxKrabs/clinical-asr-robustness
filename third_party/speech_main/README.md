# Speech-main 迁移说明

本目录保存从外部 `Speech-main` 仓库迁入 project 的 NeMo/ASR 相关源码、示例和上游元数据。迁移目的：后续即使删除外部 `Speech-main` 仓库，project 仍保留实现 ASR confidence 适配所需的本地代码参考和 import 来源。

## 迁移来源

- 原始本地仓库：`D:\Chasingfordream\内地部分\文书合集\清华大学神经调控\Speech-main`
- 迁移日期：2026-07-02
- 上游许可文件：`LICENSE`
- 上游说明文件：`UPSTREAM_README.md`
- 上游引用文件：`CITATION.cff`

## 已迁移内容

- `nemo/`：NeMo 源码包，用于后续 project 侧 adapter import 或参考。
- `examples/asr/`：ASR 示例脚本和配置，尤其是 transcribe、confidence、CTC/RNNT、streaming、n-best 相关示例。
- `pyproject.toml`、`setup.py`、`nemo_dependencies.py`、`MANIFEST.in`：保留上游依赖和打包信息，便于后续复现环境。
- `LICENSE`、`UPSTREAM_README.md`、`CITATION.cff`：保留来源、许可和引用信息。

## 权重位置

模型权重未放在本目录，而是放在 project 的数据目录中：

```text
data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo
```

该目录默认被 `.gitignore` 忽略，不应提交到 Git。

## 使用约束

- 后续脚本不得再读取、import 或引用外部 `..\Speech-main` 路径。
- 如需复用这里的 NeMo 源码，优先在 project 侧 adapter 中显式加入本目录到 Python path，或在环境配置中使用本目录作为本地源码来源。
- 如后续只依赖正式安装的 NeMo 包，也应保留本目录作为已审阅代码和配置的迁移快照，直到确认不再需要。
