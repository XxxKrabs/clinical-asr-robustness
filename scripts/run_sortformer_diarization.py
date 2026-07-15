from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.speaker_diarization import (
    SpeakerDiarizationModelInfo,
    SpeakerDiarizationRecord,
    diarization_segments_to_rttm,
    map_diarization_to_asr_records,
    parse_sortformer_output_lines,
    read_speaker_diarization_jsonl,
    write_speaker_diarization_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = Path(
    "data/external/asr_models/nemo/diar_streaming_sortformer_4spk-v2.1.nemo"
)
DEFAULT_OUTPUT_ROOT = Path("outputs/remote_programming_40/t070_sortformer_pilot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "用 NVIDIA Streaming Sortformer 跑整例说话人分离，导出 JSONL/RTTM，"
            "并可按时间重叠映射到 ASR words。"
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "sortformer_diarization.jsonl",
    )
    parser.add_argument(
        "--output-rttm-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "rttm",
    )
    parser.add_argument(
        "--run-summary-json",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "sortformer_diarization_run.json",
    )
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--chunk-len", type=int, default=340)
    parser.add_argument("--chunk-right-context", type=int, default=40)
    parser.add_argument("--fifo-len", type=int, default=40)
    parser.add_argument("--spkcache-update-period", type=int, default=340)
    parser.add_argument("--spkcache-len", type=int, default=188)
    parser.add_argument("--asr-confidence-jsonl", type=Path, default=None)
    parser.add_argument("--mapped-asr-output-jsonl", type=Path, default=None)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.10)
    parser.add_argument("--ambiguity-ratio", type=float, default=0.90)
    parser.add_argument("--max-same-speaker-bridge-gap-sec", type=float, default=1.5)
    parser.add_argument("--disable-same-speaker-gap-bridge", action="store_true")
    parser.add_argument("--overwrite-existing-speaker-labels", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"manifest 第 {line_number} 行不是合法 JSON：{path}") from exc
    return records


def select_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = records
    if args.record_index is not None:
        selected = []
        for index in args.record_index:
            if index < 0 or index >= len(records):
                raise IndexError(f"record-index 越界：{index}")
            selected.append(records[index])
    if args.sample_ids:
        wanted = set(args.sample_ids)
        selected = [record for record in selected if str(record.get("sample_id")) in wanted]
        missing = wanted - {str(record.get("sample_id")) for record in selected}
        if missing:
            raise ValueError(f"manifest 中找不到 sample_id：{sorted(missing)}")
    if args.limit is not None:
        if args.limit < 0:
            raise ValueError("limit 不能小于 0")
        selected = selected[: args.limit]
    if not selected:
        raise ValueError("没有选中任何 diarization 输入记录")
    return selected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def configure_streaming(model: Any, args: argparse.Namespace) -> dict[str, int]:
    values = {
        "chunk_len": args.chunk_len,
        "chunk_right_context": args.chunk_right_context,
        "fifo_len": args.fifo_len,
        "spkcache_update_period": args.spkcache_update_period,
        "spkcache_len": args.spkcache_len,
    }
    for name, value in values.items():
        setattr(model.sortformer_modules, name, value)
    model.sortformer_modules._check_streaming_parameters()
    return values


def run() -> dict[str, Any]:
    args = parse_args()
    if args.batch_size != 1:
        raise ValueError("当前 T070 pilot 固定 batch-size=1，以控制显存和逐例失败恢复")
    if args.overwrite and args.resume:
        raise ValueError("--overwrite 与 --resume 不能同时使用")
    if args.asr_confidence_jsonl and not args.mapped_asr_output_jsonl:
        raise ValueError("传入 --asr-confidence-jsonl 时必须同时指定 --mapped-asr-output-jsonl")

    input_manifest = resolve_project_path(args.input_manifest)
    model_path = resolve_project_path(args.model_path)
    output_jsonl = resolve_project_path(args.output_jsonl)
    output_rttm_dir = resolve_project_path(args.output_rttm_dir)
    run_summary_json = resolve_project_path(args.run_summary_json)
    if not model_path.exists():
        raise FileNotFoundError(f"Sortformer 模型不存在：{model_path}")

    manifest_records = select_records(load_jsonl(input_manifest), args)
    existing_records: list[SpeakerDiarizationRecord] = []
    if output_jsonl.exists():
        if args.overwrite:
            existing_records = []
        elif args.resume:
            existing_records = read_speaker_diarization_jsonl(output_jsonl)
        else:
            raise FileExistsError(
                f"输出已存在：{output_jsonl}；请显式使用 --overwrite 或 --resume"
            )
    completed_keys = {
        (record.dataset, record.consultation_id) for record in existing_records
    }
    pending_records = [
        record
        for record in manifest_records
        if (
            str(record.get("dataset") or "unknown"),
            str(record.get("consultation_id") or record.get("sample_id")),
        )
        not in completed_keys
    ]

    import soundfile as sf
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("请求了 CUDA，但当前 clinical-asr 环境中 CUDA 不可用")

    checkpoint_sha256 = sha256_file(model_path)
    restore_started = time.perf_counter()
    model = SortformerEncLabelModel.restore_from(
        restore_path=str(model_path),
        map_location="cpu",
        strict=False,
    )
    model = model.to(args.device)
    model.eval()
    streaming_config = configure_streaming(model, args)
    restore_elapsed_sec = time.perf_counter() - restore_started
    max_num_speakers = int(model.cfg.get("max_num_of_spks", 4))
    model_info = SpeakerDiarizationModelInfo(
        model_name=model_path.stem,
        model_path=project_relative(model_path),
        model_version="v2.1",
        checkpoint_sha256=checkpoint_sha256,
        license="NVIDIA Open Model License Agreement",
        max_num_speakers=max_num_speakers,
        metadata={
            "model_card": (
                "https://huggingface.co/nvidia/"
                "diar_streaming_sortformer_4spk-v2.1"
            ),
            "streaming_mode": bool(model.cfg.get("streaming_mode", False)),
        },
    )

    output_rttm_dir.mkdir(parents=True, exist_ok=True)
    diarization_records = list(existing_records)
    failures: list[dict[str, str]] = []
    for manifest_record in pending_records:
        dataset = str(manifest_record.get("dataset") or "unknown")
        consultation_id = str(
            manifest_record.get("consultation_id") or manifest_record.get("sample_id")
        )
        try:
            audio_value = manifest_record.get("audio_filepath") or manifest_record.get("audio_path")
            if not audio_value:
                raise ValueError("manifest 记录缺少 audio_filepath")
            audio_path = resolve_project_path(Path(str(audio_value)))
            if not audio_path.exists():
                raise FileNotFoundError(f"输入音频不存在：{audio_path}")
            audio_info = sf.info(str(audio_path))
            if int(audio_info.samplerate) != 16_000 or int(audio_info.channels) != 1:
                raise ValueError(
                    "Sortformer 输入必须是 16 kHz mono；"
                    f"实际为 {audio_info.samplerate} Hz/{audio_info.channels} channel"
                )
            duration_sec = float(audio_info.frames) / float(audio_info.samplerate)

            if args.device == "cuda":
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.synchronize()
            infer_started = time.perf_counter()
            with torch.inference_mode():
                outputs = model.diarize(audio=[str(audio_path)], batch_size=1)
            if args.device == "cuda":
                torch.cuda.synchronize()
            inference_elapsed_sec = time.perf_counter() - infer_started
            if len(outputs) != 1:
                raise RuntimeError(f"Sortformer 返回条数异常：{len(outputs)}")
            segments = parse_sortformer_output_lines(outputs[0])
            speaker_labels = sorted({segment.speaker_label for segment in segments})
            cuda_peak_allocated = (
                int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else None
            )
            cuda_peak_reserved = (
                int(torch.cuda.max_memory_reserved()) if args.device == "cuda" else None
            )
            diarization_record = SpeakerDiarizationRecord(
                record_id=f"sortformer_{dataset}_{consultation_id}",
                dataset=dataset,
                split=manifest_record.get("split"),
                consultation_id=consultation_id,
                audio_filepath=project_relative(audio_path),
                source_audio_filepath=manifest_record.get("source_audio_filepath"),
                duration_sec=duration_sec,
                generated_at_utc=datetime.now(timezone.utc),
                segments=segments,
                speaker_labels=speaker_labels,
                model=model_info,
                inference={
                    "device": args.device,
                    "batch_size": 1,
                    "sample_rate_hz": 16_000,
                    "streaming_config_frames_80ms": streaming_config,
                    "postprocessing_source": "checkpoint_default",
                },
                runtime={
                    "restore_elapsed_sec": restore_elapsed_sec,
                    "inference_elapsed_sec": inference_elapsed_sec,
                    "real_time_factor": inference_elapsed_sec / duration_sec,
                    "cuda_peak_memory_allocated_bytes": cuda_peak_allocated,
                    "cuda_peak_memory_reserved_bytes": cuda_peak_reserved,
                    "torch_version": torch.__version__,
                    "cuda_device": (
                        torch.cuda.get_device_name(0) if args.device == "cuda" else None
                    ),
                },
                metadata={
                    "task_id": "T070",
                    "acoustic_speaker_only": True,
                    "speaker_roles_assigned": False,
                    "reference_rttm_used": False,
                    "source_manifest": project_relative(input_manifest),
                    "source_sample_id": manifest_record.get("sample_id"),
                },
            )
            diarization_records.append(diarization_record)
            write_speaker_diarization_jsonl(diarization_records, output_jsonl)
            rttm_lines = diarization_segments_to_rttm(consultation_id, segments)
            (output_rttm_dir / f"{consultation_id}.rttm").write_text(
                "\n".join(rttm_lines) + ("\n" if rttm_lines else ""),
                encoding="utf-8",
            )
        except Exception as exc:
            failures.append(
                {
                    "dataset": dataset,
                    "consultation_id": consultation_id,
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            )
            if args.fail_fast:
                raise

    mapped_summary: dict[str, Any] | None = None
    if args.asr_confidence_jsonl:
        asr_input = resolve_project_path(args.asr_confidence_jsonl)
        mapped_output = resolve_project_path(args.mapped_asr_output_jsonl)
        asr_records = read_asr_confidence_jsonl(asr_input)
        mapped_records = map_diarization_to_asr_records(
            asr_records,
            diarization_records,
            min_overlap_ratio=args.min_overlap_ratio,
            ambiguity_ratio=args.ambiguity_ratio,
            overwrite_existing=args.overwrite_existing_speaker_labels,
            max_same_speaker_bridge_gap_sec=(
                None
                if args.disable_same_speaker_gap_bridge
                else args.max_same_speaker_bridge_gap_sec
            ),
        )
        write_asr_confidence_jsonl(mapped_records, mapped_output)
        resolved_word_count = sum(
            1 for record in mapped_records for word in record.asr_words if word.speaker_label
        )
        acoustic_mapped_word_count = sum(
            1
            for record in mapped_records
            for word in record.asr_words
            if isinstance(word.metadata.get("diarization"), dict)
            and word.metadata["diarization"].get("speaker_label")
        )
        smoothed_word_count = sum(
            1
            for record in mapped_records
            for word in record.asr_words
            if isinstance(word.metadata.get("diarization"), dict)
            and word.metadata["diarization"].get("smoothing_status")
        )
        total_word_count = sum(len(record.asr_words) for record in mapped_records)
        mapped_summary = {
            "input_jsonl": project_relative(asr_input),
            "output_jsonl": project_relative(mapped_output),
            "record_count": len(mapped_records),
            "mapped_word_count": acoustic_mapped_word_count,
            "total_word_count": total_word_count,
            "mapping_coverage": (
                acoustic_mapped_word_count / total_word_count
                if total_word_count
                else 0.0
            ),
            "resolved_word_count": resolved_word_count,
            "resolved_coverage": (
                resolved_word_count / total_word_count if total_word_count else 0.0
            ),
            "smoothed_word_count": smoothed_word_count,
            "same_speaker_gap_bridge_enabled": (
                not args.disable_same_speaker_gap_bridge
            ),
            "max_same_speaker_bridge_gap_sec": (
                args.max_same_speaker_bridge_gap_sec
            ),
            "ambiguous_overlap_bridged": False,
        }

    summary = {
        "task_id": "T070",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_manifest": project_relative(input_manifest),
        "model_path": project_relative(model_path),
        "model_sha256": checkpoint_sha256,
        "output_jsonl": project_relative(output_jsonl),
        "output_rttm_dir": project_relative(output_rttm_dir),
        "selected_record_count": len(manifest_records),
        "resumed_record_count": len(existing_records),
        "attempted_record_count": len(pending_records),
        "successful_record_count": len(diarization_records),
        "failure_count": len(failures),
        "failures": failures,
        "restore_elapsed_sec": restore_elapsed_sec,
        "streaming_config_frames_80ms": streaming_config,
        "mapped_asr": mapped_summary,
        "reference_rttm_used": False,
        "quality_claim_allowed": False,
        "note": (
            "当前只报告工程运行与时间映射覆盖；没有人工 RTTM 时不报告 DER/JER。"
        ),
    }
    write_json(summary, run_summary_json)
    return summary


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
