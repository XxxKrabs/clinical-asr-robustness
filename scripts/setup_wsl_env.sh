#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
用法:
  bash scripts/setup_wsl_env.sh [选项]

默认行为:
  - 在项目根目录创建/更新 .venv-wsl，或使用 --conda-env 创建 Conda 环境
  - 安装项目基础依赖与 dev 依赖
  - 运行 pytest 与 ruff 验证

选项:
  --conda-env NAME         使用 Conda 环境而不是 venv，例如 clinical-asr
  --conda-bin PATH         指定 conda 可执行文件，默认 /home/krabs/miniforge3/bin/conda
  --with-asr               额外安装 PyTorch CUDA 与 project 内迁移的 NeMo ASR 依赖
  --with-system-packages   先用 apt 安装 ffmpeg、sox、libsndfile、build-essential 等系统依赖
  --no-tests               跳过 pytest/ruff 验证
  --venv-dir PATH          指定虚拟环境目录，默认 PROJECT_ROOT/.venv-wsl
  --python PATH            指定 Python 解释器，默认 python3
  --torch-index URL        指定 PyTorch wheel 源，默认 CUDA 12.6 wheel 源
  --torch-version VERSION  指定 torch 版本，默认 2.11.0+cu126
  --torchaudio-version VERSION
                           指定 torchaudio 版本，默认 2.11.0+cu126
  -h, --help               显示帮助

常用命令:
  bash scripts/setup_wsl_env.sh
  bash scripts/setup_wsl_env.sh --conda-env clinical-asr
  bash scripts/setup_wsl_env.sh --with-system-packages --with-asr
EOF
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-wsl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONDA_BIN="${CONDA_BIN:-/home/krabs/miniforge3/bin/conda}"
CONDA_ENV_NAME=""
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
TORCH_VERSION="${TORCH_VERSION:-2.11.0+cu126}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.11.0+cu126}"
WITH_ASR=0
WITH_SYSTEM_PACKAGES=0
RUN_TESTS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --conda-env)
      CONDA_ENV_NAME="$2"
      shift 2
      ;;
    --conda-bin)
      CONDA_BIN="$2"
      shift 2
      ;;
    --with-asr)
      WITH_ASR=1
      shift
      ;;
    --with-system-packages)
      WITH_SYSTEM_PACKAGES=1
      shift
      ;;
    --no-tests)
      RUN_TESTS=0
      shift
      ;;
    --venv-dir)
      VENV_DIR="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --torch-index)
      TORCH_INDEX="$2"
      shift 2
      ;;
    --torch-version)
      TORCH_VERSION="$2"
      shift 2
      ;;
    --torchaudio-version)
      TORCHAUDIO_VERSION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "[1/6] 项目目录: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

if [[ "$WITH_SYSTEM_PACKAGES" -eq 1 ]]; then
  echo "[2/6] 安装 WSL 系统依赖（需要 sudo）"
  sudo apt-get update
  sudo apt-get install -y \
    build-essential \
    ffmpeg \
    libsndfile1 \
    python3-pip \
    python3-venv \
    sox
else
  echo "[2/6] 跳过系统依赖安装（如需音频/NeMo 依赖，可加 --with-system-packages）"
fi

if [[ -n "$CONDA_ENV_NAME" ]]; then
  echo "[3/6] 创建/更新 Conda 环境: $CONDA_ENV_NAME"
  if [[ ! -x "$CONDA_BIN" ]]; then
    echo "找不到 conda: $CONDA_BIN" >&2
    exit 1
  fi
  if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -Fxq "$CONDA_ENV_NAME"; then
    "$CONDA_BIN" create -y -n "$CONDA_ENV_NAME" python=3.10 pip
  fi
  PY_RUN=("$CONDA_BIN" run -n "$CONDA_ENV_NAME" --no-capture-output python)
else
  echo "[3/6] 创建/更新虚拟环境: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  source "$VENV_DIR/bin/activate"
  PY_RUN=(python)
fi

echo "[4/6] 安装项目基础依赖"
"${PY_RUN[@]}" -m pip install --upgrade pip setuptools wheel
"${PY_RUN[@]}" -m pip install -e "$PROJECT_ROOT[dev]"

if [[ "$WITH_ASR" -eq 1 ]]; then
  echo "[5/6] 安装 ASR/NeMo 依赖"
  "${PY_RUN[@]}" -m pip install \
    --index-url "$TORCH_INDEX" \
    "torch==$TORCH_VERSION" \
    "torchaudio==$TORCHAUDIO_VERSION"
  "${PY_RUN[@]}" -m pip install -e "$PROJECT_ROOT/third_party/speech_main[asr]"
  "${PY_RUN[@]}" - <<'PY'
import torch

print(f"torch={torch.__version__}")
print(f"cuda_available={torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"cuda_device={torch.cuda.get_device_name(0)}")

import nemo.collections.asr as nemo_asr  # noqa: F401

print("nemo.collections.asr import OK")
PY
else
  echo "[5/6] 跳过 ASR/NeMo 依赖安装（如需 T026 smoke test，可加 --with-asr）"
fi

if [[ "$RUN_TESTS" -eq 1 ]]; then
  echo "[6/6] 运行项目验证"
  "${PY_RUN[@]}" -m pytest --basetemp=.pytest_tmp
  "${PY_RUN[@]}" -m ruff check .
else
  echo "[6/6] 跳过项目验证"
fi

echo "WSL 项目环境已就绪。激活命令："
if [[ -n "$CONDA_ENV_NAME" ]]; then
  echo "conda activate \"$CONDA_ENV_NAME\""
else
  echo "source \"$VENV_DIR/bin/activate\""
fi
