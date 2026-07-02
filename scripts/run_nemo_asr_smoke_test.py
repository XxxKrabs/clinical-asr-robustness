"""运行 T026 NeMo ASR smoke test。

目标：
- 使用 project 内 `.nemo` 权重；
- 从 T025 生成的 PriMock57 channel manifest 中选择 1 路音频；
- 验证 NeMo `Hypothesis` 返回 transcript、timestamps 和 word confidence；
- 检查运行时没有从 project 外部 `Speech-main` 路径 import NeMo。

输出默认写入 `outputs/primock57/t026_nemo_smoke_test/`，该目录默认不纳入 Git。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl"
)
DEFAULT_MODEL = (
    PROJECT_ROOT / "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs/primock57/t026_nemo_smoke_test/t026_nemo_smoke_test_result.json"
)
INTERNAL_NEMO_ROOT = PROJECT_ROOT / "third_party/speech_main"


def is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path.is_relative_to。"""

    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def load_jsonl_record(path: Path, *, record_index: int, sample_id: str | None) -> dict[str, Any]:
    """读取 manifest 中的一条记录。"""

    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在：{path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))

    if not records:
        raise ValueError(f"manifest 为空：{path}")

    if sample_id is not None:
        for record in records:
            if record.get("sample_id") == sample_id:
                return record
        raise ValueError(f"manifest 中找不到 sample_id={sample_id!r}")

    if record_index < 0 or record_index >= len(records):
        raise IndexError(f"record_index 超出范围：{record_index}，manifest 共 {len(records)} 条")
    return records[record_index]


def resolve_project_path(path_value: str) -> Path:
    """将 manifest 中的相对路径解析到 project root。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def path_to_posix(path: Path) -> str:
    """输出稳定的 POSIX 风格路径。"""

    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def find_external_speech_main_paths(paths: list[str | None]) -> list[str]:
    """找出疑似 project 外部 Speech-main 路径。"""

    external_paths: list[str] = []
    for value in paths:
        if not value:
            continue
        normalized = str(value).replace("\\", "/")
        lower = normalized.lower()
        if "speech-main" not in lower and "speech_main" not in lower:
            continue
        path = Path(value)
        if is_relative_to(path, PROJECT_ROOT):
            continue
        external_paths.append(value)
    return sorted(set(external_paths))


def configure_ctc_greedy_confidence(model: Any) -> dict[str, Any]:
    """打开 CTC greedy timestamps 与 word confidence。"""

    from omegaconf import OmegaConf, open_dict

    decoding_cfg = copy.deepcopy(model.cfg.decoding)
    with open_dict(decoding_cfg):
        decoding_cfg.strategy = "greedy"
        decoding_cfg.compute_timestamps = True
        decoding_cfg.ctc_timestamp_type = "all"
        decoding_cfg.confidence_cfg = OmegaConf.merge(
            decoding_cfg.get("confidence_cfg", {}),
            {
                "preserve_frame_confidence": True,
                "preserve_token_confidence": True,
                "preserve_word_confidence": True,
                "exclude_blank": True,
                "aggregation": "min",
                "method_cfg": {
                    "name": "entropy",
                    "entropy_type": "tsallis",
                    "alpha": 0.33,
                    "entropy_norm": "lin",
                },
            },
        )

    model.change_decoding_strategy(decoding_cfg, verbose=False)
    return json.loads(json.dumps(OmegaConf.to_container(decoding_cfg, resolve=True)))


def first_hypothesis(transcription_result: Any) -> Any:
    """从 NeMo transcribe 返回值中取第一条 Hypothesis。"""

    result = transcription_result
    if isinstance(result, tuple):
        result = result[0]
    if not isinstance(result, list) or not result:
        raise TypeError(f"无法从 transcribe 返回值提取 Hypothesis：{type(transcription_result)!r}")

    first = result[0]
    if isinstance(first, list):
        if not first:
            raise TypeError("第一条 transcribe 结果为空 list")
        return first[0]
    return first


def len_or_zero(value: Any) -> int:
    """安全读取长度。"""

    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def to_jsonable(value: Any) -> Any:
    """递归转换 numpy / torch 标量和张量，确保可写 JSON。"""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return to_jsonable(value.tolist())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def summarize_hypothesis(hypothesis: Any) -> dict[str, Any]:
    """把 Hypothesis 摘要为可写入 JSON 的结构。"""

    text = getattr(hypothesis, "text", "") or ""
    timestamp = getattr(hypothesis, "timestamp", None)
    timestamp_keys = sorted(timestamp.keys()) if isinstance(timestamp, dict) else []
    word_timestamps = timestamp.get("word", []) if isinstance(timestamp, dict) else []
    segment_timestamps = timestamp.get("segment", []) if isinstance(timestamp, dict) else []
    char_timestamps = timestamp.get("char", []) if isinstance(timestamp, dict) else []
    word_confidence = getattr(hypothesis, "word_confidence", None) or []
    token_confidence = getattr(hypothesis, "token_confidence", None) or []
    frame_confidence = getattr(hypothesis, "frame_confidence", None) or []

    return {
        "hypothesis_class": f"{hypothesis.__class__.__module__}.{hypothesis.__class__.__name__}",
        "asr_transcript": text,
        "asr_transcript_char_count": len(text),
        "asr_transcript_word_count": len(text.split()),
        "timestamp_keys": timestamp_keys,
        "word_timestamp_count": len_or_zero(word_timestamps),
        "segment_timestamp_count": len_or_zero(segment_timestamps),
        "char_timestamp_count": len_or_zero(char_timestamps),
        "word_confidence_count": len_or_zero(word_confidence),
        "token_confidence_count": len_or_zero(token_confidence),
        "frame_confidence_count": len_or_zero(frame_confidence),
        "word_confidence_preview": word_confidence[:10],
        "word_timestamp_preview": word_timestamps[:10],
        "segment_timestamp_preview": segment_timestamps[:5],
    }


def summarize_validation(hypothesis_summary: dict[str, Any]) -> dict[str, bool]:
    """生成 T026 验收布尔值。"""

    has_text = hypothesis_summary["asr_transcript_char_count"] > 0
    has_timestamps = (
        hypothesis_summary["word_timestamp_count"] > 0
        or hypothesis_summary["segment_timestamp_count"] > 0
        or hypothesis_summary["char_timestamp_count"] > 0
    )
    has_word_confidence = hypothesis_summary["word_confidence_count"] > 0
    word_confidence_matches_words = (
        hypothesis_summary["word_confidence_count"]
        == hypothesis_summary["asr_transcript_word_count"]
    )
    word_confidence_matches_timestamps = (
        hypothesis_summary["word_confidence_count"] == hypothesis_summary["word_timestamp_count"]
    )
    return {
        "has_transcript_text": has_text,
        "has_timestamps": has_timestamps,
        "has_word_confidence": has_word_confidence,
        "word_confidence_matches_asr_words": word_confidence_matches_words,
        "word_confidence_matches_word_timestamps": word_confidence_matches_timestamps,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--record-index", type=int, default=0)
    parser.add_argument("--sample-id", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument(
        "--allow-nemo-outside-project",
        action="store_true",
        help="默认要求 nemo 来自 project/third_party/speech_main；仅调试时放宽。",
    )
    return parser.parse_args()


def run_smoke_test(args: argparse.Namespace) -> dict[str, Any]:
    """执行 smoke test 并返回 JSON 记录。"""

    record = load_jsonl_record(
        args.manifest,
        record_index=args.record_index,
        sample_id=args.sample_id,
    )
    audio_path = resolve_project_path(record["audio_filepath"])
    model_path = (
        args.model_path if args.model_path.is_absolute() else PROJECT_ROOT / args.model_path
    )

    if not audio_path.exists():
        raise FileNotFoundError(f"音频不存在：{audio_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"模型权重不存在：{model_path}")

    import nemo
    import nemo.collections.asr as nemo_asr
    import torch
    from nemo.collections.asr.models import ASRModel
    from nemo.collections.asr.parts.mixins.transcription import TranscribeConfig

    nemo_module_paths = [
        getattr(nemo, "__file__", None),
        getattr(nemo_asr, "__file__", None),
    ]
    external_paths = find_external_speech_main_paths(sys.path + nemo_module_paths)
    nemo_paths_inside_project = [
        path is not None and is_relative_to(Path(path), INTERNAL_NEMO_ROOT)
        for path in nemo_module_paths
    ]
    if external_paths:
        raise RuntimeError(f"检测到 project 外部 Speech-main 路径：{external_paths}")
    if not args.allow_nemo_outside_project and not all(nemo_paths_inside_project):
        raise RuntimeError(
            "nemo 未从 project/third_party/speech_main 导入；"
            f"当前模块路径：{nemo_module_paths}"
        )

    cuda_available = torch.cuda.is_available()
    if args.device == "auto":
        device = "cuda" if cuda_available else "cpu"
    else:
        device = args.device
    if device == "cuda" and not cuda_available:
        raise RuntimeError("指定 --device cuda，但 torch.cuda.is_available() 为 False")

    model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
    model.to(device)
    model.eval()
    decoding_config = configure_ctc_greedy_confidence(model)

    transcribe_config = TranscribeConfig(
        use_lhotse=False,
        batch_size=args.batch_size,
        return_hypotheses=True,
        num_workers=args.num_workers,
        timestamps=True,
        verbose=False,
    )
    transcription_result = model.transcribe(
        audio=[str(audio_path)],
        override_config=transcribe_config,
    )
    hypothesis = first_hypothesis(transcription_result)
    hypothesis_summary = summarize_hypothesis(hypothesis)
    validation = summarize_validation(hypothesis_summary)

    if not validation["has_transcript_text"]:
        raise RuntimeError("Hypothesis 未返回非空 transcript")
    if not validation["has_timestamps"]:
        raise RuntimeError("Hypothesis 未返回 timestamp")
    if not validation["has_word_confidence"]:
        raise RuntimeError("Hypothesis 未返回 word_confidence")

    return {
        "task_id": "T026",
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "manifest_path": path_to_posix(args.manifest),
        "manifest_record_index": args.record_index,
        "sample": {
            "sample_id": record.get("sample_id"),
            "dataset": record.get("dataset"),
            "split": record.get("split"),
            "consultation_id": record.get("consultation_id"),
            "source_channel": record.get("source_channel"),
            "audio_path": path_to_posix(audio_path),
            "duration_sec": record.get("duration"),
            "reference_textgrid_path": record.get("reference_textgrid_path"),
            "reference_text_included": record.get("reference_text_included"),
        },
        "runtime": {
            "device": device,
            "torch_version": torch.__version__,
            "cuda_available": cuda_available,
            "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
            "nemo_path": nemo_module_paths[0],
            "nemo_asr_path": nemo_module_paths[1],
            "external_speech_main_paths": external_paths,
            "nemo_paths_inside_project": nemo_paths_inside_project,
        },
        "model": {
            "model_path": path_to_posix(model_path),
            "model_class": f"{model.__class__.__module__}.{model.__class__.__name__}",
        },
        "decode_config": {
            "batch_size": args.batch_size,
            "num_workers": args.num_workers,
            "use_lhotse": False,
            "return_hypotheses": True,
            "timestamps": True,
            "decoding": decoding_config,
        },
        "hypothesis": hypothesis_summary,
        "validation": validation,
        "privacy_and_safety": {
            "reference_text_included": False,
            "source_audio_or_text_committed": False,
            "output_directory_gitignored": True,
            "asr_transcript_is_research_output": True,
        },
    }


def write_result(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(to_jsonable(result), file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    try:
        result = run_smoke_test(args)
        write_result(result, output_path)
        print("T026 NeMo ASR smoke test 通过。")
        print(f"- sample_id: {result['sample']['sample_id']}")
        print(f"- source_channel: {result['sample']['source_channel']}")
        print(f"- transcript words: {result['hypothesis']['asr_transcript_word_count']}")
        print(f"- word timestamps: {result['hypothesis']['word_timestamp_count']}")
        print(f"- word confidence: {result['hypothesis']['word_confidence_count']}")
        print(f"- output: {output_path}")
    except Exception as exc:
        result = {
            "task_id": "T026",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_result(result, output_path)
        print("T026 NeMo ASR smoke test 失败。")
        print(f"- error: {exc!r}")
        print(f"- output: {output_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
