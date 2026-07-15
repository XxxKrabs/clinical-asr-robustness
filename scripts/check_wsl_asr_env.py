"""检查 WSL ASR 环境的关键依赖与本地权重状态。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = Path(
    "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
)


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def parse_args() -> object:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=(
            "待核验的 project 相对或绝对 .nemo 路径；默认保留历史英文模型，"
            "因此旧命令行为不变。"
        ),
    )
    parser.add_argument(
        "--restore-model",
        action="store_true",
        help="尝试从 project 内 .nemo 权重恢复 NeMo ASR 模型；不跑音频。",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="可选：把不含词表正文的环境/模型核验摘要写入 JSON。",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def vocabulary_size(model: Any) -> int | None:
    for candidate in (
        nested_value(model, "decoder", "vocabulary"),
        nested_value(model, "ctc_decoder", "vocabulary"),
        nested_value(model, "tokenizer", "vocab_size"),
    ):
        if candidate is None:
            continue
        try:
            return int(candidate) if isinstance(candidate, (int, float)) else len(candidate)
        except (TypeError, ValueError):
            continue
    return None


def model_metadata(model: Any) -> dict[str, Any]:
    cfg = getattr(model, "cfg", None)
    tokenizer = getattr(model, "tokenizer", None)
    decoder = getattr(model, "decoder", None)
    ctc_decoder = getattr(model, "ctc_decoder", None)
    blank_id = getattr(decoder, "blank_idx", None)
    if blank_id is None:
        blank_id = getattr(ctc_decoder, "blank_idx", None)
    return {
        "model_class": f"{model.__class__.__module__}.{model.__class__.__name__}",
        "sample_rate": nested_value(cfg, "preprocessor", "sample_rate"),
        "target": nested_value(cfg, "_target_"),
        "tokenizer_class": (
            f"{tokenizer.__class__.__module__}.{tokenizer.__class__.__name__}"
            if tokenizer is not None
            else None
        ),
        "tokenizer_type": nested_value(cfg, "tokenizer", "type"),
        "vocabulary_size": vocabulary_size(model),
        "blank_id": blank_id,
        "decoding_strategy": nested_value(cfg, "decoding", "strategy"),
        "has_primary_decoder": decoder is not None,
        "has_aux_ctc_decoder": ctc_decoder is not None or hasattr(model, "ctc_decoder"),
        "has_change_decoding_strategy": hasattr(model, "change_decoding_strategy"),
        "has_change_decoding_strategy_ctc": hasattr(model, "change_decoding_strategy_ctc"),
    }


def main() -> None:
    args = parse_args()
    model_path = resolve_project_path(args.model_path).resolve()

    result: dict[str, object] = {
        "project_root": str(PROJECT_ROOT),
        "model_path": str(model_path),
        "model_exists": model_path.exists(),
    }
    if model_path.exists():
        result["model_size_bytes"] = model_path.stat().st_size
        result["model_sha256"] = sha256_file(model_path)

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
    if result["nemo_available"]:
        import nemo

        result["nemo_version"] = getattr(nemo, "__version__", None)

    if args.restore_model:
        if not result["nemo_asr_available"]:
            result["model_restore"] = "skipped: nemo.collections.asr unavailable"
        elif not model_path.exists():
            result["model_restore"] = "skipped: model file missing"
        else:
            from nemo.collections.asr.models import ASRModel

            model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
            result["model_restore"] = "ok"
            result.update(model_metadata(model))

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json is not None:
        output_path = resolve_project_path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": repr(exc)}, ensure_ascii=False, indent=2))
        raise
