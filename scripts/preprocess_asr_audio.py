"""把 ASR manifest 音频确定性转成 16 kHz mono PCM/WAV 短窗（T053）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_MANIFEST = Path(
    "data/interim/remote_programming_40/manifests/"
    "remote_programming_40_asr_manifest.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/interim/remote_programming_40/audio_16k")
DEFAULT_OUTPUT_MANIFEST = Path(
    "data/interim/remote_programming_40/manifests/"
    "remote_programming_40_asr_16k_windows.jsonl"
)
DEFAULT_QC_JSON = Path(
    "data/interim/remote_programming_40/manifests/"
    "remote_programming_40_audio_preprocessing_qc.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_INPUT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-manifest", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--qc-json", type=Path, default=DEFAULT_QC_JSON)
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--target-sample-rate", type=int, default=16_000)
    parser.add_argument(
        "--window-sec",
        type=float,
        default=30.0,
        help="连续无重叠短窗长度；传 0 表示每条输入保留为单个完整窗口。",
    )
    parser.add_argument("--clip-start-sec", type=float, default=0.0)
    parser.add_argument(
        "--clip-duration-sec",
        type=float,
        default=None,
        help="只处理每条输入从 clip-start 开始的前 N 秒；smoke test 推荐 15–30 秒。",
    )
    parser.add_argument(
        "--max-windows-per-record",
        type=int,
        default=None,
        help="限制每条原音频导出的短窗数；用于 smoke test。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若某条源音频的全部预期窗口已存在且参数一致，则跳过解码并重建 manifest。",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"第 {line_number} 行不是 JSON object：{path}")
            records.append(payload)
    return records


def select_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = list(records)
    if args.sample_ids:
        wanted = set(args.sample_ids)
        selected = [record for record in selected if record.get("sample_id") in wanted]
        missing = wanted - {str(record.get("sample_id")) for record in selected}
        if missing:
            raise ValueError(f"未找到 sample_id：{sorted(missing)}")
    if args.record_index:
        invalid = [index for index in args.record_index if index < 0 or index >= len(records)]
        if invalid:
            raise ValueError(f"record-index 越界：{invalid}")
        selected_by_index = [records[index] for index in args.record_index]
        if args.sample_ids:
            allowed = {str(record.get("sample_id")) for record in selected}
            selected_by_index = [
                record
                for record in selected_by_index
                if str(record.get("sample_id")) in allowed
            ]
        selected = selected_by_index
    if args.limit is not None:
        if args.limit < 0:
            raise ValueError("--limit 不能为负数")
        selected = selected[: args.limit]
    if not selected:
        raise ValueError("没有选中任何输入记录")
    return selected


def window_ranges(
    *,
    source_duration_sec: float,
    clip_start_sec: float,
    clip_duration_sec: float | None,
    window_sec: float,
    max_windows: int | None,
) -> list[tuple[float, float]]:
    if clip_start_sec < 0 or clip_start_sec >= source_duration_sec:
        raise ValueError("clip-start-sec 必须位于原音频时长内")
    clip_end = source_duration_sec
    if clip_duration_sec is not None:
        if clip_duration_sec <= 0:
            raise ValueError("clip-duration-sec 必须大于 0")
        clip_end = min(clip_end, clip_start_sec + clip_duration_sec)
    active_window = clip_end - clip_start_sec if window_sec == 0 else window_sec
    if active_window <= 0:
        raise ValueError("window-sec 不能为负数")
    ranges: list[tuple[float, float]] = []
    cursor = clip_start_sec
    while cursor < clip_end - 1e-9:
        if max_windows is not None and len(ranges) >= max_windows:
            break
        end = min(cursor + active_window, clip_end)
        ranges.append((cursor, end))
        cursor = end
    return ranges


def read_mono_window(
    path: Path,
    *,
    source_start_sec: float,
    source_end_sec: float,
    target_sample_rate: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        import soundfile as sf
        from scipy.signal import resample_poly
    except ImportError as exc:  # pragma: no cover - 由项目环境检查覆盖
        raise RuntimeError("需要 soundfile 与 scipy；请使用 WSL clinical-asr 环境。") from exc

    info = sf.info(str(path))
    source_rate = int(info.samplerate)
    start_frame = int(round(source_start_sec * source_rate))
    end_frame = min(int(info.frames), int(round(source_end_sec * source_rate)))
    if end_frame <= start_frame:
        raise ValueError(f"音频窗口为空：{source_start_sec}–{source_end_sec}")
    with sf.SoundFile(str(path), mode="r") as file:
        file.seek(start_frame)
        audio = file.read(end_frame - start_frame, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1, dtype=np.float64).astype(np.float32)
    if source_rate != target_sample_rate:
        divisor = math.gcd(source_rate, target_sample_rate)
        mono = resample_poly(
            mono,
            target_sample_rate // divisor,
            source_rate // divisor,
        ).astype(np.float32, copy=False)
    return mono, {
        "source_sample_rate_hz": source_rate,
        "source_channels": int(info.channels),
        "source_start_frame": start_frame,
        "source_end_frame": end_frame,
    }


def slice_resampled_audio(
    audio: np.ndarray,
    *,
    decoded_start_sec: float,
    window_start_sec: float,
    window_end_sec: float,
    sample_rate: int,
) -> np.ndarray:
    """从一次解码/重采样的连续音频中切出一个绝对时间窗。"""

    start_sample = int(round((window_start_sec - decoded_start_sec) * sample_rate))
    end_sample = int(round((window_end_sec - decoded_start_sec) * sample_rate))
    start_sample = max(0, min(start_sample, len(audio)))
    end_sample = max(start_sample, min(end_sample, len(audio)))
    if end_sample <= start_sample:
        raise ValueError(f"重采样后的音频窗口为空：{window_start_sec}–{window_end_sec}")
    return audio[start_sample:end_sample]


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate, format="WAV", subtype="PCM_16")


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.target_sample_rate <= 0:
        raise ValueError("target-sample-rate 必须大于 0")
    input_manifest = resolve_project_path(args.input_manifest)
    output_dir = resolve_project_path(args.output_dir)
    output_manifest = resolve_project_path(args.output_manifest)
    qc_path = resolve_project_path(args.qc_json)
    records = select_records(load_jsonl(input_manifest), args)

    output_records: list[dict[str, Any]] = []
    resumed_source_records = 0
    processed_source_records = 0
    for record in records:
        audio_value = record.get("audio_filepath") or record.get("audio_path")
        if not audio_value:
            raise ValueError(f"输入记录缺少 audio_filepath：{record.get('sample_id')}")
        source_path = resolve_project_path(Path(str(audio_value)))
        if not source_path.exists():
            raise FileNotFoundError(f"输入音频不存在：{source_path}")
        source_duration = float(record.get("duration_sec") or record.get("duration"))
        ranges = window_ranges(
            source_duration_sec=source_duration,
            clip_start_sec=args.clip_start_sec,
            clip_duration_sec=args.clip_duration_sec,
            window_sec=args.window_sec,
            max_windows=args.max_windows_per_record,
        )
        case_id = str(record.get("consultation_id") or record.get("sample_id") or "sample")
        output_paths = [
            output_dir / case_id / f"window_{window_index:04d}.wav"
            for window_index in range(len(ranges))
        ]
        if args.resume and all(path.exists() for path in output_paths):
            try:
                import soundfile as sf
            except ImportError as exc:  # pragma: no cover - 由环境检查覆盖
                raise RuntimeError("需要 soundfile；请使用 WSL clinical-asr 环境。") from exc
            source_info = sf.info(str(source_path))
            source_rate = int(source_info.samplerate)
            valid_existing = True
            existing_info = []
            for output_path in output_paths:
                info = sf.info(str(output_path))
                existing_info.append(info)
                if (
                    int(info.samplerate) != args.target_sample_rate
                    or int(info.channels) != 1
                    or str(info.subtype) != "PCM_16"
                ):
                    valid_existing = False
                    break
            if valid_existing:
                for window_index, ((start_sec, end_sec), output_path, info) in enumerate(
                    zip(ranges, output_paths, existing_info, strict=True)
                ):
                    output_duration = int(info.frames) / args.target_sample_rate
                    unit_id = f"{case_id}:window_{window_index:04d}"
                    output_records.append(
                        {
                            **record,
                            "sample_id": f"{record.get('sample_id')}:{window_index:04d}",
                            "parent_sample_id": record.get("sample_id"),
                            "unit_id": unit_id,
                            "text_unit_mode": record.get("text_unit_mode") or "auto",
                            "audio_filepath": project_relative(output_path),
                            "duration": output_duration,
                            "duration_sec": output_duration,
                            "sample_rate_hz": args.target_sample_rate,
                            "channels": 1,
                            "audio_format": "WAV",
                            "audio_subtype": "PCM_16",
                            "audio_sha256": sha256_file(output_path),
                            "source_audio_filepath": project_relative(source_path),
                            "source_audio_sha256": record.get("audio_sha256"),
                            "source_duration_sec": source_duration,
                            "source_start_sec": start_sec,
                            "source_end_sec": end_sec,
                            "preprocessing": {
                                "version": "deterministic_pcm16_window/v1",
                                "channel_mix": "arithmetic_mean",
                                "resampling": "scipy.signal.resample_poly",
                                "windowing": "contiguous_non_overlapping",
                                "source_sample_rate_hz": source_rate,
                                "source_channels": int(source_info.channels),
                                "source_start_frame": int(round(start_sec * source_rate)),
                                "source_end_frame": int(round(end_sec * source_rate)),
                                "decoded_once_per_source_record": True,
                                "decoded_source_start_sec": ranges[0][0],
                                "decoded_source_end_sec": ranges[-1][1],
                                "resumed_existing_window": True,
                            },
                        }
                    )
                resumed_source_records += 1
                continue
        # MP3 按窗反复 seek 会重复解码并随音频长度近似二次增长。每例只解码和
        # 重采样一次，再按绝对时间连续切窗；这也是 5/40 例可扩量的关键。
        decoded_start_sec = ranges[0][0]
        decoded_end_sec = ranges[-1][1]
        decoded_audio, decoded_source_metadata = read_mono_window(
            source_path,
            source_start_sec=decoded_start_sec,
            source_end_sec=decoded_end_sec,
            target_sample_rate=args.target_sample_rate,
        )
        source_rate = int(decoded_source_metadata["source_sample_rate_hz"])
        processed_source_records += 1
        for window_index, (start_sec, end_sec) in enumerate(ranges):
            audio = slice_resampled_audio(
                decoded_audio,
                decoded_start_sec=decoded_start_sec,
                window_start_sec=start_sec,
                window_end_sec=end_sec,
                sample_rate=args.target_sample_rate,
            )
            source_metadata = {
                "source_sample_rate_hz": source_rate,
                "source_channels": decoded_source_metadata["source_channels"],
                "source_start_frame": int(round(start_sec * source_rate)),
                "source_end_frame": int(round(end_sec * source_rate)),
                "decoded_once_per_source_record": True,
                "decoded_source_start_sec": decoded_start_sec,
                "decoded_source_end_sec": decoded_end_sec,
            }
            output_path = output_dir / case_id / f"window_{window_index:04d}.wav"
            write_wav(output_path, audio, args.target_sample_rate)
            output_duration = len(audio) / args.target_sample_rate
            unit_id = f"{case_id}:window_{window_index:04d}"
            output_records.append(
                {
                    **record,
                    "sample_id": f"{record.get('sample_id')}:{window_index:04d}",
                    "parent_sample_id": record.get("sample_id"),
                    "unit_id": unit_id,
                    "text_unit_mode": record.get("text_unit_mode") or "auto",
                    "audio_filepath": project_relative(output_path),
                    "duration": output_duration,
                    "duration_sec": output_duration,
                    "sample_rate_hz": args.target_sample_rate,
                    "channels": 1,
                    "audio_format": "WAV",
                    "audio_subtype": "PCM_16",
                    "audio_sha256": sha256_file(output_path),
                    "source_audio_filepath": project_relative(source_path),
                    "source_audio_sha256": record.get("audio_sha256"),
                    "source_duration_sec": source_duration,
                    "source_start_sec": start_sec,
                    "source_end_sec": end_sec,
                    "preprocessing": {
                        "version": "deterministic_pcm16_window/v1",
                        "channel_mix": "arithmetic_mean",
                        "resampling": "scipy.signal.resample_poly",
                        "windowing": "contiguous_non_overlapping",
                        **source_metadata,
                    },
                }
            )

    write_jsonl(output_records, output_manifest)
    monotonic = all(
        float(row["source_end_sec"]) > float(row["source_start_sec"])
        for row in output_records
    )
    summary = {
        "task_id": "T053",
        "status": "ok" if monotonic else "failed_qc",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_manifest": project_relative(input_manifest),
        "output_manifest": project_relative(output_manifest),
        "input_record_count": len(records),
        "output_window_count": len(output_records),
        "target_sample_rate_hz": args.target_sample_rate,
        "target_channels": 1,
        "target_format": "WAV/PCM_16",
        "window_sec": args.window_sec,
        "clip_start_sec": args.clip_start_sec,
        "clip_duration_sec": args.clip_duration_sec,
        "max_windows_per_record": args.max_windows_per_record,
        "resume": bool(args.resume),
        "resumed_source_record_count": resumed_source_records,
        "processed_source_record_count": processed_source_records,
        "source_offsets_monotonic": monotonic,
        "source_start_min_sec": min(
            (float(row["source_start_sec"]) for row in output_records), default=None
        ),
        "source_end_max_sec": max(
            (float(row["source_end_sec"]) for row in output_records), default=None
        ),
        "safety": {
            "transcript_body_written": False,
            "research_data_only": True,
        },
    }
    qc_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
