# WSL 项目环境配置

更新时间：2026-07-02

本文记录本项目在 Ubuntu 22.04 WSL2 中的推荐环境配置。目标是服务近期 T026：使用 project 内部 NeMo/FastConformer CTC 权重跑通 1 条 PriMock57 音频 smoke test，并验证 ASR 输出文本、时间戳和置信度。

## 当前推荐

- WSL 发行版：Ubuntu 22.04 LTS。
- Python：3.10。
- 项目环境：优先使用 Conda 环境 `clinical-asr`；如系统已安装 `python3.10-venv`，也可使用项目根目录下 `.venv-wsl/`。
- 基础依赖：安装 `pyproject.toml` 中的项目依赖与 `dev` 依赖。
- ASR 依赖：PyTorch CUDA 12.6、torchaudio 与 project 内迁移的 NeMo ASR 依赖。
- 权重路径：`data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo`，默认不提交 Git。

## 本机已完成配置

2026-07-02 已在现有 Ubuntu 22.04 WSL2 中完成以下配置：

- Conda 环境：`clinical-asr`。
- Python：3.10.20。
- 项目包：`clinical-asr-robustness` editable install。
- PyTorch：`torch==2.11.0+cu126`。
- Torchaudio：`torchaudio==2.11.0+cu126`。
- GPU：`NVIDIA GeForce RTX 4060 Laptop GPU`，`torch.cuda.is_available() == True`。
- NeMo：从 `third_party/speech_main[asr]` editable install，`nemo.collections.asr` 可导入。
- 模型恢复：project 内 `stt_en_fastconformer_ctc_large.nemo` 可恢复为 `EncDecCTCModelBPE`。

已通过验证：

```bash
python scripts/check_wsl_asr_env.py --restore-model
python -m pytest --basetemp=.pytest_tmp
python -m ruff check .
```

## Codex/PowerShell 中的直接调用与沙箱申请

在 Codex 或 Windows PowerShell 侧运行项目 Python 时，不要依赖交互式 `conda activate`，优先直接调用 WSL Conda 解释器：

```powershell
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python --version
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m pytest --basetemp=.pytest_tmp
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python -m ruff check .
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/check_wsl_asr_env.py --restore-model
```

如果 Codex 沙箱中直接运行 WSL Python 失败，或出现 `WSL_E_DISTRO_NOT_FOUND` 但 `wsl.exe -l -v` 能看到 `Ubuntu-22.04`，应直接申请提升权限，不要长时间反复探索。建议申请的可复用前缀是：

```text
wsl.exe -d Ubuntu-22.04 -e /home/krabs/miniforge3/envs/clinical-asr/bin/python
```

2026-07-02 已在 Codex 中验证：申请提升权限后，`--version` 返回 `Python 3.10.20`，`-m pytest --version` 返回 `pytest 9.1.1`。WSL 启动时可能打印 localhost 代理警告；如果命令退出码为 0，可先视为不影响当前 Python/pytest/ASR 调用。

## 一键配置

在 WSL 中进入项目目录后运行：

```bash
bash scripts/setup_wsl_env.sh --conda-env clinical-asr
```

如果确认系统已安装 `python3.10-venv`，也可以使用项目内 venv：

```bash
bash scripts/setup_wsl_env.sh
```

这会创建环境、安装基础依赖，并运行 `pytest` 与 `ruff`。

如果要同时准备 NeMo ASR smoke test 环境：

```bash
bash scripts/setup_wsl_env.sh --conda-env clinical-asr --with-asr
```

`--with-asr` 会安装已验证可用的 `torch==2.11.0+cu126`、`torchaudio==2.11.0+cu126`，以及 `third_party/speech_main` 中迁移的 NeMo ASR 依赖。该步骤体积较大，且需要网络可用。

如果后续需要系统级音频工具，可由用户在交互式 WSL 中运行：

```bash
bash scripts/setup_wsl_env.sh --conda-env clinical-asr --with-system-packages --with-asr
```

`--with-system-packages` 会使用 `sudo apt-get` 安装音频与构建相关系统包；当前 Codex 非交互执行时无法输入 sudo 密码，因此本次未执行该步骤。

## 常用命令

激活环境：

```bash
conda activate clinical-asr
```

运行测试：

```bash
python -m pytest --basetemp=.pytest_tmp
python -m ruff check .
```

运行 T026 音频 smoke test：

```bash
/home/krabs/miniforge3/envs/clinical-asr/bin/python scripts/run_nemo_asr_smoke_test.py
```

该命令默认读取 T025 生成的 `primock57_nemo_asr_input_manifest.jsonl` 第 0 条音频，使用 project 内 `stt_en_fastconformer_ctc_large.nemo`，并把结果写入 `outputs/primock57/t026_nemo_smoke_test/t026_nemo_smoke_test_result.json`。详细记录见 `docs/t026_nemo_smoke_test.md`。

2026-07-02 已验证：使用 `--record-index 1` 成功跑通 `primock57:day1_consultation01:patient`，输出 transcript、timestamps 和 `word_confidence`，且 `nemo` 模块路径来自 project 内 `third_party/speech_main/`。

检查 GPU：

```bash
nvidia-smi
python scripts/check_wsl_asr_env.py
python scripts/check_wsl_asr_env.py --restore-model
```

## 已知注意事项

- WSL 启动时如果出现 “localhost 代理配置未镜像到 WSL” 警告，说明 Windows 侧代理没有自动映射到 WSL NAT。若 `pip` 或 `apt` 下载失败，需要单独配置 WSL 可访问的代理，或临时关闭依赖本机 localhost 的代理。
- 用户当前 WSL 启动脚本中可能存在旧项目路径引用，例如缺失的 `setup_path.sh`。这通常不影响非交互命令，但如果每次打开 shell 都报错，后续可清理 `~/.bashrc` 中对应旧路径。
- 近期脚本不得读取、import 或引用外部 `Speech-main` 仓库路径；如需 NeMo 代码，应使用 `third_party/speech_main/` 中已迁移的快照。
