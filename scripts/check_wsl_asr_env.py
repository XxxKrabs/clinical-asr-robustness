"""检查 WSL ASR 环境的关键依赖与本地权重状态。"""

from __future__ import annotations

import importlib.util
import json
from argparse import ArgumentParser
from pathlib import Path


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def parse_args() -> object:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restore-model",
        action="store_true",
        help="尝试从 project 内 .nemo 权重恢复 NeMo ASR 模型；不跑音频。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    model_path = project_root / "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"

    result: dict[str, object] = {
        "project_root": str(project_root),
        "model_path": str(model_path),
        "model_exists": model_path.exists(),
    }

    if module_available("torch"):
        import torch

        result.update(
            {
                "torch_version": torch.__version__,
                "cuda_available": torch.cuda.is_available(),
                "cuda_device": torch.cuda.get_device_name(0)
                if torch.cuda.is_available()
                else None,
            }
        )
    else:
        result["torch_available"] = False

    if module_available("torchaudio"):
        import torchaudio

        result["torchaudio_version"] = torchaudio.__version__
    else:
        result["torchaudio_available"] = False

    result["nemo_available"] = module_available("nemo")
    result["nemo_asr_available"] = module_available("nemo.collections.asr")

    if args.restore_model:
        if not result["nemo_asr_available"]:
            result["model_restore"] = "skipped: nemo.collections.asr unavailable"
        elif not model_path.exists():
            result["model_restore"] = "skipped: model file missing"
        else:
            from nemo.collections.asr.models import ASRModel

            model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
            result["model_restore"] = "ok"
            result["model_class"] = f"{model.__class__.__module__}.{model.__class__.__name__}"

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": repr(exc)}, ensure_ascii=False, indent=2))
        raise
