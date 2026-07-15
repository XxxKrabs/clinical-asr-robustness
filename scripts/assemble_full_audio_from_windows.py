"""把已预处理的连续 16 kHz 短窗无损拼成整例 WAV 与 manifest。

该入口复用 T053 的 PCM16 窗口，避免为 Sortformer 再次解码和重采样原始 MP3。拼接前会检查
同一病例的源时间轴连续、采样率/声道一致；输出只含音频与文件指针，不写 transcript 正文。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-window-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--qc-json", type=Path, required=True)
    parser.add_argument("--continuity-tolerance-sec", type=float, default=0.002)
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def group_windows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent_id = str(
            row.get("parent_sample_id")
            or row.get("consultation_id")
            or row.get("sample_id")
            or ""
        )
        if not parent_id:
            raise ValueError("窗口记录缺少 parent_sample_id/consultation_id/sample_id")
        groups[parent_id].append(row)
    for windows in groups.values():
        windows.sort(key=lambda item: float(item.get("source_start_sec") or 0.0))
    return dict(groups)


def validate_windows(
    parent_id: str,
    windows: list[dict[str, Any]],
    *,
    tolerance_sec: float,
) -> tuple[int, int, float, float]:
    sample_rates = {int(row.get("sample_rate_hz") or 0) for row in windows}
    channels = {int(row.get("channels") or 0) for row in windows}
    if len(sample_rates) != 1 or 0 in sample_rates:
        raise ValueError(f"{parent_id} 窗口采样率不一致：{sorted(sample_rates)}")
    if channels != {1}:
        raise ValueError(f"{parent_id} 不是单声道窗口：{sorted(channels)}")
    for previous, current in zip(windows, windows[1:], strict=False):
        gap = float(current["source_start_sec"]) - float(previous["source_end_sec"])
        if abs(gap) > tolerance_sec:
            raise ValueError(f"{parent_id} 窗口时间轴不连续：gap={gap:.6f}s")
    return (
        sample_rates.pop(),
        channels.pop(),
        float(windows[0]["source_start_sec"]),
        float(windows[-1]["source_end_sec"]),
    )


def assemble_case(
    parent_id: str,
    windows: list[dict[str, Any]],
    *,
    output_dir: Path,
    tolerance_sec: float,
) -> dict[str, Any]:
    try:
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - 由环境检查覆盖
        raise RuntimeError("需要 soundfile；请使用 WSL clinical-asr 环境。") from exc

    sample_rate, channels, source_start, source_end = validate_windows(
        parent_id,
        windows,
        tolerance_sec=tolerance_sec,
    )
    case_id = str(windows[0].get("consultation_id") or parent_id.split(":")[-2])
    output_path = output_dir / case_id / "full.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = 0
    with sf.SoundFile(
        str(output_path),
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        format="WAV",
        subtype="PCM_16",
    ) as output_file:
        for window in windows:
            window_path = resolve_project_path(Path(str(window["audio_filepath"])))
            audio, window_rate = sf.read(str(window_path), dtype="float32", always_2d=True)
            if int(window_rate) != sample_rate or audio.shape[1] != channels:
                raise ValueError(f"窗口音频参数与 manifest 不一致：{window_path}")
            output_file.write(audio)
            total_frames += int(audio.shape[0])
    first = windows[0]
    duration_sec = total_frames / sample_rate
    return {
        **first,
        "sample_id": parent_id,
        "parent_sample_id": None,
        "unit_id": f"{case_id}:full",
        "audio_filepath": project_relative(output_path),
        "duration": duration_sec,
        "duration_sec": duration_sec,
        "audio_sha256": sha256_file(output_path),
        "source_start_sec": source_start,
        "source_end_sec": source_end,
        "preprocessing": {
            "version": "assemble_pcm16_windows/v1",
            "source_window_count": len(windows),
            "source_window_manifest": True,
            "continuity_tolerance_sec": tolerance_sec,
            "transcript_body_written": False,
        },
    }


def main() -> None:
    args = parse_args()
    if args.continuity_tolerance_sec < 0:
        raise ValueError("continuity-tolerance-sec 不能为负数")
    input_path = resolve_project_path(args.input_window_manifest)
    output_dir = resolve_project_path(args.output_dir)
    output_manifest = resolve_project_path(args.output_manifest)
    qc_path = resolve_project_path(args.qc_json)
    rows = read_jsonl(input_path)
    groups = group_windows(rows)
    output_rows = [
        assemble_case(
            parent_id,
            windows,
            output_dir=output_dir,
            tolerance_sec=args.continuity_tolerance_sec,
        )
        for parent_id, windows in sorted(groups.items())
    ]
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with output_manifest.open("w", encoding="utf-8", newline="\n") as file:
        for row in output_rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    summary = {
        "task_id": "T061_FULL_AUDIO_ASSEMBLY",
        "schema_version": "full_audio_assembly_run/v1",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_window_manifest": project_relative(input_path),
        "output_manifest": project_relative(output_manifest),
        "input_window_count": len(rows),
        "output_case_count": len(output_rows),
        "total_duration_sec": sum(float(row["duration_sec"]) for row in output_rows),
        "continuity_tolerance_sec": args.continuity_tolerance_sec,
        "transcript_body_written": False,
        "research_use_only": True,
    }
    qc_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
