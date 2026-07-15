"""导出 NeMo ASR sequence-level n-best/beams JSONL（T037）。

本脚本默认读取 T025 的 PriMock57 channel-level manifest，使用 project 内
NeMo 权重执行 acoustic-only CTC beam_batch 解码，并写出可被 T029
`scripts/extract_asr_nbest_candidates.py --nbest-jsonl` 直接消费的 JSONL。

脚本只保存 ASR beam 文本、分数、配置和文件指针；不会读取或内联 reference
transcript 正文，也不生成临床建议。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.dataset_profiles import resolve_dataset_profile
from clinical_asr_robustness.nemo_confidence_export import to_jsonable
from clinical_asr_robustness.nemo_nbest_export import (
    DEFAULT_NBEST_SOURCE,
    DEFAULT_RECORD_ID_PREFIX,
    build_nbest_jsonl_record,
    configure_ctc_beam_nbest,
    flatten_nbest_transcription_results,
    write_nbest_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl"
)
DEFAULT_MODEL = (
    PROJECT_ROOT / "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t037_nemo_asr_nbest"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_sequence_nbest.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t037_nemo_asr_nbest_run.json"
INTERNAL_NEMO_ROOT = PROJECT_ROOT / "third_party/speech_main"


def is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path.is_relative_to。"""

    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def path_for_record(path: Path | None, project_root: Path = PROJECT_ROOT) -> str | None:
    """输出相对 project root 的 POSIX 风格路径；无法相对化时保留绝对路径。"""

    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path | None) -> Path | None:
    """将 manifest/CLI 中的相对路径解析到 project root。"""

    if path_value is None:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL manifest。"""

    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在：{path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"manifest 第 {line_number} 行不是合法 JSON：{path}") from exc
    if not records:
        raise ValueError(f"manifest 为空：{path}")
    return records


def select_manifest_records(
    records: list[dict[str, Any]],
    *,
    sample_ids: list[str] | None,
    record_indices: list[int] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """按 sample_id / index / limit 选择待转写记录。"""

    selected = records
    if sample_ids:
        wanted = set(sample_ids)
        selected = [record for record in selected if record.get("sample_id") in wanted]
        found = {record.get("sample_id") for record in selected}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(f"manifest 中找不到指定 sample_id：{missing}")

    if record_indices:
        indexed: list[dict[str, Any]] = []
        for index in record_indices:
            if index < 0 or index >= len(records):
                raise IndexError(f"record index 越界：{index}，manifest 共 {len(records)} 条")
            indexed.append(records[index])
        selected = indexed

    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit 必须大于 0")
        selected = selected[:limit]

    if not selected:
        raise ValueError("筛选后没有待转写记录")
    return selected


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


def ensure_project_nemo_on_path() -> None:
    """优先从 project 内 `third_party/speech_main` 导入 NeMo。"""

    if INTERNAL_NEMO_ROOT.exists():
        internal_path = str(INTERNAL_NEMO_ROOT)
        if internal_path not in sys.path:
            sys.path.insert(0, internal_path)


def validate_input_files(records: list[dict[str, Any]], model_path: Path) -> list[Path]:
    """检查模型和待处理音频文件存在。"""

    if not model_path.exists():
        raise FileNotFoundError(f"模型权重不存在：{model_path}")

    audio_paths: list[Path] = []
    for record in records:
        audio_value = record.get("audio_filepath") or record.get("audio_path")
        if not audio_value:
            raise ValueError(f"manifest 记录缺少 audio_filepath/audio_path：{record}")
        audio_path = resolve_project_path(audio_value)
        assert audio_path is not None
        if not audio_path.exists():
            raise FileNotFoundError(f"音频不存在：{audio_path}")
        audio_paths.append(audio_path)
    return audio_paths


def chunked(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """按固定大小切分列表。"""

    if chunk_size <= 0:
        raise ValueError("--transcribe-chunk-size 必须大于 0")
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="auto")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--run-config-json", type=Path, default=None)
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument(
        "--precision",
        choices=["auto", "fp32", "fp16", "bf16"],
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--transcribe-chunk-size", type=int, default=1)
    parser.add_argument(
        "--beam-strategy",
        choices=["beam_batch", "beam", "pyctcdecode", "flashlight"],
        default="beam_batch",
        help="默认 beam_batch 可在无 KenLM 时生成 acoustic-only n-best。",
    )
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--max-beams", type=int, default=5)
    parser.add_argument("--beam-beta", type=float, default=0.0)
    parser.add_argument("--beam-threshold", type=float, default=20.0)
    parser.add_argument("--ngram-lm-alpha", type=float, default=0.0)
    parser.add_argument("--ngram-lm-model", type=Path, default=None)
    parser.add_argument("--disable-cuda-graphs", action="store_true")
    parser.add_argument("--source", default=DEFAULT_NBEST_SOURCE)
    parser.add_argument("--record-id-prefix", default=DEFAULT_RECORD_ID_PREFIX)
    parser.add_argument(
        "--allow-nemo-outside-project",
        action="store_true",
        help="默认要求 nemo 来自 project/third_party/speech_main；仅调试时放宽。",
    )
    args = parser.parse_args()
    manifest_hint = resolve_project_path(args.manifest) if args.manifest else None
    profile = resolve_dataset_profile(dataset=args.dataset, manifest_path=manifest_hint)
    args.dataset = profile.dataset_id
    args.dataset_language = profile.language
    if args.manifest is None:
        args.manifest = profile.default_manifest
    if args.model_path is None:
        args.model_path = profile.default_model_path
    if args.output_jsonl is None:
        args.output_jsonl = profile.output_path(
            "t037_nemo_asr_nbest",
            f"{profile.dataset_id}_sequence_nbest.jsonl",
        )
    if args.run_config_json is None:
        args.run_config_json = profile.output_path(
            "t037_nemo_asr_nbest",
            "t037_nemo_asr_nbest_run.json",
        )
    return args


def run_export(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """执行 T037 n-best 导出。"""

    run_started = time.perf_counter()
    manifest_path = resolve_project_path(args.manifest)
    model_path = resolve_project_path(args.model_path)
    output_jsonl = resolve_project_path(args.output_jsonl)
    ngram_lm_model = resolve_project_path(args.ngram_lm_model)
    assert manifest_path is not None
    assert model_path is not None
    assert output_jsonl is not None

    manifest_records = load_jsonl_records(manifest_path)
    selected_records = select_manifest_records(
        manifest_records,
        sample_ids=args.sample_ids,
        record_indices=args.record_index,
        limit=args.limit,
    )
    record_datasets = {
        str(record.get("dataset")) for record in selected_records if record.get("dataset")
    }
    if record_datasets and record_datasets != {args.dataset}:
        raise ValueError(
            f"CLI/自动路由数据集 {args.dataset} 与 manifest 不一致：{sorted(record_datasets)}"
        )
    audio_paths = validate_input_files(selected_records, model_path)
    if ngram_lm_model is not None and not ngram_lm_model.exists():
        raise FileNotFoundError(f"ngram LM 文件不存在：{ngram_lm_model}")

    ensure_project_nemo_on_path()

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
    precision = args.precision
    if precision == "auto":
        precision = "fp16" if device == "cuda" else "fp32"
    if device != "cuda" and precision in {"fp16", "bf16"}:
        raise ValueError("CPU n-best 当前只支持 fp32 precision")

    restore_started = time.perf_counter()
    model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
    model.to(device)
    model.eval()
    restore_elapsed_sec = time.perf_counter() - restore_started
    decoding_config = configure_ctc_beam_nbest(
        model,
        strategy=args.beam_strategy,
        beam_size=args.beam_size,
        beam_beta=args.beam_beta,
        beam_threshold=args.beam_threshold,
        ngram_lm_alpha=args.ngram_lm_alpha,
        ngram_lm_model=str(ngram_lm_model) if ngram_lm_model is not None else None,
        allow_cuda_graphs=not args.disable_cuda_graphs,
    )

    runtime = {
        "device": device,
        "precision": precision,
        "restore_elapsed_sec": restore_elapsed_sec,
        "torch_version": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
        "nemo_path": nemo_module_paths[0],
        "nemo_asr_path": nemo_module_paths[1],
        "external_speech_main_paths": external_paths,
        "nemo_paths_inside_project": nemo_paths_inside_project,
    }
    model_info = {
        "provider": "nemo",
        "model_name": model_path.stem,
        "model_path": path_for_record(model_path),
        "model_class": f"{model.__class__.__module__}.{model.__class__.__name__}",
        "language": args.dataset_language,
        "decoder_type": decoding_config.get("project_decoder_type"),
    }
    decoding_summary = {
        "strategy": args.beam_strategy,
        "beam_size": args.beam_size,
        "n_best": args.max_beams,
        "batch_size": args.batch_size,
        "device": device,
        "timestamps_enabled": False,
        "transcribe_return_hypotheses": False,
        "return_best_hypothesis": False,
        "config": decoding_config,
        "metadata": {
            "num_workers": args.num_workers,
            "transcribe_chunk_size": args.transcribe_chunk_size,
            "beam_beta": args.beam_beta,
            "beam_threshold": args.beam_threshold,
            "ngram_lm_alpha": args.ngram_lm_alpha,
            "ngram_lm_model": path_for_record(ngram_lm_model),
            "allow_cuda_graphs": not args.disable_cuda_graphs,
        },
    }

    transcribe_config = TranscribeConfig(
        use_lhotse=False,
        batch_size=args.batch_size,
        # NeMo ctc_models._transcribe_output_processing assumes a single Hypothesis
        # when `return_hypotheses=True`; with n-best it receives a list and tries to
        # assign `.y_sequence` on that list. For T037 we only need text/score beams,
        # so keep the transcribe wrapper in non-hypothesis mode while the decoder
        # itself still returns all beams via `beam.return_best_hypothesis=False`.
        return_hypotheses=False,
        num_workers=args.num_workers,
        timestamps=False,
        verbose=False,
    )

    generated_at_utc = datetime.now(timezone.utc)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    transcribe_started = time.perf_counter()
    output_records: list[dict[str, Any]] = []
    processed = 0
    for record_chunk, audio_chunk in zip(
        chunked(selected_records, args.transcribe_chunk_size),
        chunked(audio_paths, args.transcribe_chunk_size),
        strict=True,
    ):
        with autocast_context(torch, device=device, precision=precision):
            transcription_result = model.transcribe(
                audio=[str(path) for path in audio_chunk],
                override_config=transcribe_config,
            )
        nbest_groups = flatten_nbest_transcription_results(transcription_result)
        if len(nbest_groups) != len(record_chunk):
            raise RuntimeError(
                "NeMo 返回 n-best 组数与输入音频数量不一致："
                f"{len(nbest_groups)} vs {len(record_chunk)}"
            )

        for manifest_record, hypothesis_group in zip(record_chunk, nbest_groups, strict=True):
            output_records.append(
                build_nbest_jsonl_record(
                    manifest_record=manifest_record,
                    hypothesis_group=hypothesis_group,
                    source=args.source,
                    max_beams=args.max_beams,
                    record_id_prefix=args.record_id_prefix,
                    model_info=model_info,
                    decoding_config=decoding_summary,
                    runtime=runtime,
                    generated_at_utc=generated_at_utc,
                )
            )
            processed += 1
            print(f"[{processed}/{len(selected_records)}] {manifest_record.get('sample_id')}")

    transcribe_elapsed_sec = time.perf_counter() - transcribe_started
    total_audio_duration_sec = sum(
        float(record.get("duration_sec") or record.get("duration") or 0.0)
        for record in selected_records
    )
    runtime.update(
        {
            "transcribe_elapsed_sec": transcribe_elapsed_sec,
            "total_elapsed_sec": time.perf_counter() - run_started,
            "total_audio_duration_sec": total_audio_duration_sec,
            "real_time_factor": (
                transcribe_elapsed_sec / total_audio_duration_sec
                if total_audio_duration_sec > 0
                else None
            ),
            "cuda_peak_memory_allocated_bytes": (
                int(torch.cuda.max_memory_allocated()) if device == "cuda" else None
            ),
            "cuda_peak_memory_reserved_bytes": (
                int(torch.cuda.max_memory_reserved()) if device == "cuda" else None
            ),
        }
    )
    for record in output_records:
        record["runtime"] = {**record.get("runtime", {}), **runtime}
    write_nbest_jsonl(output_records, output_jsonl)
    run_summary = build_run_summary(
        manifest_path=manifest_path,
        model_path=model_path,
        output_jsonl=output_jsonl,
        selected_records=selected_records,
        output_records=output_records,
        model_info=model_info,
        decoding_summary=decoding_summary,
        runtime=runtime,
        args=args,
    )
    return output_records, run_summary


def build_run_summary(
    *,
    manifest_path: Path,
    model_path: Path,
    output_jsonl: Path,
    selected_records: list[dict[str, Any]],
    output_records: list[dict[str, Any]],
    model_info: dict[str, Any],
    decoding_summary: dict[str, Any],
    runtime: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """构造 T037 运行摘要。"""

    beam_counts = [len(record.get("beams") or []) for record in output_records]
    unique_beam_text_counts = [
        len({" ".join(str(beam[0]).split()).casefold() for beam in record.get("beams") or []})
        for record in output_records
    ]
    return {
        "task_id": "T037",
        "status": "ok",
        "dataset": args.dataset,
        "language": args.dataset_language,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "manifest": path_for_record(manifest_path),
            "model_path": path_for_record(model_path),
            "selected_sample_ids": [record.get("sample_id") for record in selected_records],
            "selected_records": len(selected_records),
        },
        "outputs": {
            "sequence_nbest_jsonl": path_for_record(output_jsonl),
        },
        "model": model_info,
        "decoding": decoding_summary,
        "parameters": {
            "source": args.source,
            "record_id_prefix": args.record_id_prefix,
            "beam_strategy": args.beam_strategy,
            "beam_size": args.beam_size,
            "max_beams": args.max_beams,
        },
        "runtime": runtime,
        "validation": {
            "records_written": len(output_records),
            "total_beams": sum(beam_counts),
            "beam_counts": beam_counts,
            "records_with_multiple_beams": sum(count > 1 for count in beam_counts),
            "records_with_unique_beam_variants": sum(
                count > 1 for count in unique_beam_text_counts
            ),
            "no_inline_reference_text": all(
                not bool(record.get("reference_text_included", False))
                for record in selected_records
            ),
            "nemo_paths_inside_project": all(runtime["nemo_paths_inside_project"]),
            "external_speech_main_paths": runtime["external_speech_main_paths"],
            "research_use_only": all(record.get("research_use_only") for record in output_records),
        },
    }


def autocast_context(torch_module: Any, *, device: str, precision: str) -> Any:
    if device != "cuda" or precision == "fp32":
        return nullcontext()
    dtype = torch_module.float16 if precision == "fp16" else torch_module.bfloat16
    return torch_module.autocast(device_type="cuda", dtype=dtype)


def write_run_config(record: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(to_jsonable(record), file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    run_config_path = resolve_project_path(args.run_config_json)
    assert run_config_path is not None
    try:
        output_records, run_summary = run_export(args)
        write_run_config(run_summary, run_config_path)
        print("T037 NeMo ASR n-best 导出完成。")
        print(f"- records: {len(output_records)}")
        print(f"- output_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T037",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T037 NeMo ASR n-best 导出失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
