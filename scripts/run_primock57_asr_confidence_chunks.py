"""分块运行 PriMock57 全量 T028 ASR confidence 导出。

背景：长时间在同一个 NeMo/PyTorch 进程里连续转写 100+ 路音频时，CUDA cache
或底层 workspace 可能累积导致 OOM。本脚本把全量 channel manifest 拆成小 chunk，
每个 chunk 独立启动 `scripts/export_nemo_asr_confidence.py`，再把 chunk JSONL
合并成一个全量 ASR confidence JSONL。

输出 JSONL 的每条记录仍由 T028 脚本生成；本脚本只负责编排、续跑和合并。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data/interim/primock57/manifests_full/primock57_nemo_asr_input_manifest.jsonl"
)
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT / "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
)
DEFAULT_OUTPUT_JSONL = (
    PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl"
)
DEFAULT_RUN_SUMMARY_JSON = (
    PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence/"
    "t028_nemo_asr_confidence_full_chunked_run.json"
)
DEFAULT_CHUNKS_DIR = PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence/full_chunks"


@dataclass(frozen=True)
class ChunkSpec:
    chunk_index: int
    record_indices: list[int]

    @property
    def name(self) -> str:
        return f"chunk_{self.chunk_index:04d}"


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def path_for_summary(path_value: str | Path) -> str:
    path = resolve_project_path(path_value)
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL 不存在：{path}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON") from exc
    return records


def write_json(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def build_chunks(record_count: int, chunk_size: int) -> list[ChunkSpec]:
    if chunk_size <= 0:
        raise ValueError("--chunk-size 必须大于 0")
    chunks: list[ChunkSpec] = []
    for start in range(0, record_count, chunk_size):
        stop = min(start + chunk_size, record_count)
        chunks.append(ChunkSpec(len(chunks), list(range(start, stop))))
    return chunks


def chunk_paths(chunks_dir: Path, chunk: ChunkSpec) -> tuple[Path, Path]:
    chunk_jsonl = chunks_dir / f"primock57_asr_confidence_full_{chunk.name}.jsonl"
    chunk_run_json = chunks_dir / f"t028_nemo_asr_confidence_full_{chunk.name}_run.json"
    return chunk_jsonl, chunk_run_json


def validate_chunk_output(
    *,
    chunk_jsonl: Path,
    manifest_records: list[dict[str, Any]],
    record_indices: list[int],
) -> tuple[bool, str]:
    if not chunk_jsonl.exists():
        return False, "missing"
    try:
        output_records = load_jsonl(chunk_jsonl)
    except Exception as exc:  # noqa: BLE001 - 用于续跑诊断
        return False, f"unreadable: {exc!r}"
    if len(output_records) != len(record_indices):
        return False, f"record_count_mismatch:{len(output_records)}!={len(record_indices)}"
    expected_sample_ids = [manifest_records[index].get("sample_id") for index in record_indices]
    actual_sample_ids = [record.get("sample_id") for record in output_records]
    if actual_sample_ids != expected_sample_ids:
        return False, "sample_id_mismatch"
    return True, "ok"


def export_command(
    args: argparse.Namespace,
    chunk: ChunkSpec,
    chunk_jsonl: Path,
    chunk_run_json: Path,
) -> list[str]:
    command = [
        args.python_executable,
        "scripts/export_nemo_asr_confidence.py",
        "--manifest",
        str(args.manifest),
        "--model-path",
        str(args.model_path),
        "--output-jsonl",
        str(chunk_jsonl),
        "--run-config-json",
        str(chunk_run_json),
        "--device",
        args.device,
        "--batch-size",
        str(args.batch_size),
        "--num-workers",
        str(args.num_workers),
        "--transcribe-chunk-size",
        str(args.transcribe_chunk_size),
        "--confidence-aggregation",
        args.confidence_aggregation,
        "--confidence-method",
        args.confidence_method,
        "--entropy-type",
        args.entropy_type,
        "--entropy-norm",
        args.entropy_norm,
        "--confidence-alpha",
        str(args.confidence_alpha),
        "--word-confidence-source",
        args.word_confidence_source,
        "--green-min",
        str(args.green_min),
        "--yellow-min",
        str(args.yellow_min),
        "--segment-max-words",
        str(args.segment_max_words),
        "--segment-max-gap-sec",
        str(args.segment_max_gap_sec),
    ]
    if args.save_frame_distributions:
        command.append("--save-frame-distributions")
        command.extend(["--frame-artifact-dir", str(args.frame_artifact_dir)])
    if args.audio_window_sec is not None:
        command.extend(["--audio-window-sec", str(args.audio_window_sec)])
        if args.audio_window_temp_dir is not None:
            command.extend(["--audio-window-temp-dir", str(args.audio_window_temp_dir)])
    if args.allow_nemo_outside_project:
        command.append("--allow-nemo-outside-project")
    for record_index in chunk.record_indices:
        command.extend(["--record-index", str(record_index)])
    return command


def run_chunk(
    *,
    args: argparse.Namespace,
    chunk: ChunkSpec,
    manifest_records: list[dict[str, Any]],
) -> dict[str, Any]:
    chunk_jsonl, chunk_run_json = chunk_paths(resolve_project_path(args.chunks_dir), chunk)
    valid, reason = validate_chunk_output(
        chunk_jsonl=chunk_jsonl,
        manifest_records=manifest_records,
        record_indices=chunk.record_indices,
    )
    sample_ids = [manifest_records[index].get("sample_id") for index in chunk.record_indices]
    if args.resume and valid:
        print(f"[{chunk.name}] skip existing ok: {sample_ids[0]} ... {sample_ids[-1]}", flush=True)
        return {
            "chunk": chunk.name,
            "status": "skipped",
            "reason": reason,
            "record_indices": chunk.record_indices,
            "sample_ids": sample_ids,
            "output_jsonl": path_for_summary(chunk_jsonl),
            "run_config_json": path_for_summary(chunk_run_json),
            "elapsed_sec": 0.0,
        }

    chunk_jsonl.parent.mkdir(parents=True, exist_ok=True)
    command = export_command(args, chunk, chunk_jsonl, chunk_run_json)
    env = os.environ.copy()
    if args.cuda_alloc_conf:
        env["PYTORCH_CUDA_ALLOC_CONF"] = args.cuda_alloc_conf

    print(
        f"[{chunk.name}] run {len(chunk.record_indices)} records: "
        f"{sample_ids[0]} ... {sample_ids[-1]}",
        flush=True,
    )
    started = time.perf_counter()
    if args.dry_run:
        return {
            "chunk": chunk.name,
            "status": "dry_run",
            "record_indices": chunk.record_indices,
            "sample_ids": sample_ids,
            "output_jsonl": path_for_summary(chunk_jsonl),
            "run_config_json": path_for_summary(chunk_run_json),
            "command": command,
            "elapsed_sec": 0.0,
        }

    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, env=env)
    elapsed_sec = round(time.perf_counter() - started, 3)
    valid_after, reason_after = validate_chunk_output(
        chunk_jsonl=chunk_jsonl,
        manifest_records=manifest_records,
        record_indices=chunk.record_indices,
    )
    status = "ok" if completed.returncode == 0 and valid_after else "failed"
    return {
        "chunk": chunk.name,
        "status": status,
        "returncode": completed.returncode,
        "validation": reason_after,
        "record_indices": chunk.record_indices,
        "sample_ids": sample_ids,
        "output_jsonl": path_for_summary(chunk_jsonl),
        "run_config_json": path_for_summary(chunk_run_json),
        "command": command,
        "elapsed_sec": elapsed_sec,
    }


def merge_chunks(
    *,
    chunks: list[ChunkSpec],
    chunks_dir: Path,
    output_jsonl: Path,
    manifest_records: list[dict[str, Any]],
) -> dict[str, Any]:
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    sample_ids: list[str] = []
    with output_jsonl.open("w", encoding="utf-8", newline="\n") as output_file:
        for chunk in chunks:
            chunk_jsonl, _ = chunk_paths(chunks_dir, chunk)
            valid, reason = validate_chunk_output(
                chunk_jsonl=chunk_jsonl,
                manifest_records=manifest_records,
                record_indices=chunk.record_indices,
            )
            if not valid:
                raise RuntimeError(f"{chunk.name} 无法合并：{reason}")
            for record in load_jsonl(chunk_jsonl):
                output_file.write(json.dumps(record, ensure_ascii=False))
                output_file.write("\n")
                sample_ids.append(str(record.get("sample_id")))
                written += 1
    expected_sample_ids = [str(record.get("sample_id")) for record in manifest_records]
    return {
        "records_written": written,
        "sample_ids_match_manifest_order": sample_ids == expected_sample_ids,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--run-summary-json", type=Path, default=DEFAULT_RUN_SUMMARY_JSON)
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--chunk-size", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--transcribe-chunk-size", type=int, default=1)
    parser.add_argument(
        "--confidence-aggregation",
        choices=["mean", "min", "max", "prod"],
        default="mean",
    )
    parser.add_argument("--confidence-method", choices=["entropy", "max_prob"], default="entropy")
    parser.add_argument("--entropy-type", choices=["gibbs", "tsallis", "renyi"], default="tsallis")
    parser.add_argument("--entropy-norm", choices=["lin", "exp"], default="lin")
    parser.add_argument("--confidence-alpha", type=float, default=0.33)
    parser.add_argument(
        "--word-confidence-source",
        choices=["nemo_word_confidence", "ctc_frame_distribution"],
        default="nemo_word_confidence",
    )
    parser.add_argument("--save-frame-distributions", action="store_true")
    parser.add_argument("--audio-window-sec", type=float, default=None)
    parser.add_argument("--audio-window-temp-dir", type=Path, default=None)
    parser.add_argument(
        "--frame-artifact-dir",
        type=Path,
        default=DEFAULT_CHUNKS_DIR / "ctc_frame_distributions",
    )
    parser.add_argument("--green-min", type=float, default=0.90)
    parser.add_argument("--yellow-min", type=float, default=0.80)
    parser.add_argument("--segment-max-words", type=int, default=40)
    parser.add_argument("--segment-max-gap-sec", type=float, default=1.5)
    parser.add_argument("--allow-nemo-outside-project", action="store_true")
    parser.add_argument("--cuda-alloc-conf", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = resolve_project_path(args.manifest)
    chunks_dir = resolve_project_path(args.chunks_dir)
    output_jsonl = resolve_project_path(args.output_jsonl)
    run_summary_json = resolve_project_path(args.run_summary_json)
    manifest_records = load_jsonl(manifest_path)
    chunks = build_chunks(len(manifest_records), args.chunk_size)
    generated_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(
        f"PriMock57 chunked T028 ASR start: {len(manifest_records)} records, "
        f"{len(chunks)} chunks, chunk_size={args.chunk_size}",
        flush=True,
    )
    chunk_results: list[dict[str, Any]] = []
    success = True
    for chunk in chunks:
        result = run_chunk(args=args, chunk=chunk, manifest_records=manifest_records)
        chunk_results.append(result)
        if result["status"] == "failed":
            success = False
            print(f"[{chunk.name}] failed, stop before merge.", flush=True)
            break

    merge_summary = None
    if success and not args.dry_run:
        merge_summary = merge_chunks(
            chunks=chunks,
            chunks_dir=chunks_dir,
            output_jsonl=output_jsonl,
            manifest_records=manifest_records,
        )
        success = bool(merge_summary["sample_ids_match_manifest_order"])

    summary = {
        "task_id": "T028_CHUNKED_FULL",
        "status": "ok" if success else "failed",
        "generated_at_utc": generated_at_utc,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "manifest": path_for_summary(manifest_path),
            "model_path": path_for_summary(args.model_path),
            "record_count": len(manifest_records),
        },
        "parameters": {
            "chunk_size": args.chunk_size,
            "chunk_count": len(chunks),
            "resume": args.resume,
            "device": args.device,
            "batch_size": args.batch_size,
            "transcribe_chunk_size": args.transcribe_chunk_size,
            "word_confidence_source": args.word_confidence_source,
            "audio_window_sec": args.audio_window_sec,
            "cuda_alloc_conf": args.cuda_alloc_conf,
            "dry_run": args.dry_run,
        },
        "outputs": {
            "merged_asr_confidence_jsonl": path_for_summary(output_jsonl),
            "chunks_dir": path_for_summary(chunks_dir),
            "run_summary_json": path_for_summary(run_summary_json),
        },
        "chunks": chunk_results,
        "merge_summary": merge_summary,
    }
    if not args.dry_run:
        write_json(summary, run_summary_json)

    if success:
        print("PriMock57 chunked T028 ASR finished.", flush=True)
        print(f"- merged JSONL: {output_jsonl}", flush=True)
        print(f"- run summary: {run_summary_json}", flush=True)
    else:
        print("PriMock57 chunked T028 ASR failed.", flush=True)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
