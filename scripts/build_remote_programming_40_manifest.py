"""冻结真实中文远程程控 40 例快照并生成不含病例正文的 ASR manifest（T051）。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = "remote_programming_40"
DEFAULT_RAW_ROOT = Path(
    "data/raw/remote_programming_40/"
    "远程程控人工复核资料_精选40例_无病历版_20260713"
)
DEFAULT_QWEN_ROOT = Path(
    "data/external/remote_programming_40/"
    "远程程控精选40例_Qwen病历_20260714_加密"
)
DEFAULT_OUTPUT_DIR = Path("data/interim/remote_programming_40/manifests")
CASE_PATTERN = re.compile(r"病例_(\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--qwen-root", type=Path, default=DEFAULT_QWEN_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--expected-case-count",
        type=int,
        default=40,
        help="数量不符时失败；传 0 可关闭数量断言。",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def case_id_from_path(path: Path) -> str | None:
    for part in reversed(path.parts):
        match = CASE_PATTERN.search(part)
        if match:
            return f"case_{int(match.group(1)):04d}"
    return None


def probe_mp3_header(path: Path) -> dict[str, Any]:
    """从首个 MPEG Layer III frame header 快速读取采样率和声道。"""

    with path.open("rb") as file:
        data = file.read(1024 * 1024)
    sample_rates = [44_100, 48_000, 32_000]
    for index in range(len(data) - 4):
        header = int.from_bytes(data[index : index + 4], "big")
        if header >> 21 != 0x7FF:
            continue
        version_id = (header >> 19) & 0b11
        layer_id = (header >> 17) & 0b11
        sample_rate_index = (header >> 10) & 0b11
        bitrate_index = (header >> 12) & 0b1111
        if version_id == 0b01 or layer_id != 0b01:
            continue
        if sample_rate_index == 0b11 or bitrate_index in {0, 0b1111}:
            continue
        sample_rate = sample_rates[sample_rate_index]
        if version_id == 0b10:
            sample_rate //= 2
        elif version_id == 0b00:
            sample_rate //= 4
        channel_mode = (header >> 6) & 0b11
        return {
            "sample_rate_hz": sample_rate,
            "channels": 1 if channel_mode == 0b11 else 2,
            "format": "MPEG-1/2 Audio",
            "subtype": "MPEG Layer III",
        }
    raise ValueError(f"未找到有效 MPEG Layer III frame header：{path}")


def duration_by_case_from_root_csv(raw_root: Path) -> dict[str, float]:
    csv_paths = sorted(raw_root.glob("*.csv"))
    if len(csv_paths) != 1:
        raise ValueError(f"raw root 应恰好包含 1 个根级 CSV，实际 {len(csv_paths)}")
    result: dict[str, float] = {}
    with csv_paths[0].open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            case_value = str(row.get("病例编号") or "")
            match = re.search(r"(\d+)", case_value)
            if not match:
                raise ValueError("根级 CSV 存在无法解析的匿名病例编号")
            case_id = f"case_{int(match.group(1)):04d}"
            result[case_id] = float(row["音频时长_秒"])
    return result


def audio_metadata(
    path: Path,
    *,
    case_id: str,
    duration_by_case: dict[str, float],
) -> dict[str, Any]:
    if case_id not in duration_by_case:
        raise ValueError(f"根级 CSV 缺少音频时长：{case_id}")
    info = probe_mp3_header(path)
    return {
        "duration_sec": duration_by_case[case_id],
        **info,
        "duration_source": "package_root_csv",
        "format_source": "mpeg_frame_header",
    }


def iter_snapshot_files(roots: Iterable[tuple[str, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset_group, root in roots:
        if not root.exists():
            raise FileNotFoundError(f"资产目录不存在：{root}")
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            rows.append(
                {
                    "asset_group": asset_group,
                    "relative_path": project_relative(path),
                    "case_id": case_id_from_path(path),
                    "extension": path.suffix.casefold(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return rows


def snapshot_digest(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: (item["asset_group"], item["relative_path"])):
        canonical = "\t".join(
            [
                str(row["asset_group"]),
                str(row["relative_path"]),
                str(row["size_bytes"]),
                str(row["sha256"]),
            ]
        )
        digest.update(canonical.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def qwen_paths_by_case(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(root.rglob("*.md")):
        case_id = case_id_from_path(path)
        if case_id is None:
            continue
        if case_id in result:
            raise ValueError(f"同一病例存在多个 Qwen 病历文件：{case_id}")
        result[case_id] = path
    return result


def build_manifest_records(
    raw_root: Path,
    qwen_root: Path,
    *,
    snapshot_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    audio_paths = sorted(raw_root.rglob("*.mp3"))
    qwen_by_case = qwen_paths_by_case(qwen_root)
    duration_by_case = duration_by_case_from_root_csv(raw_root)
    snapshot_by_path = {row["relative_path"]: row for row in snapshot_rows}
    records: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for audio_path in audio_paths:
        case_id = case_id_from_path(audio_path)
        if case_id is None:
            raise ValueError(f"无法从音频路径解析匿名病例编号：{audio_path}")
        if case_id in seen_case_ids:
            raise ValueError(f"同一病例存在多个 MP3：{case_id}")
        seen_case_ids.add(case_id)
        audio = audio_metadata(
            audio_path,
            case_id=case_id,
            duration_by_case=duration_by_case,
        )
        case_dir = next(
            parent for parent in audio_path.parents if CASE_PATTERN.fullmatch(parent.name)
        )
        case_files = [path for path in case_dir.rglob("*") if path.is_file()]
        qwen_path = qwen_by_case.get(case_id)
        records.append(
            {
                "sample_id": f"{DATASET}:{case_id}:mixed",
                "dataset": DATASET,
                "split": "approved_internal_20260714",
                "consultation_id": case_id,
                "source_channel": "mixed",
                "language": "zh-CN",
                "text_unit_mode": "auto",
                "audio_filepath": project_relative(audio_path),
                "duration": audio["duration_sec"],
                "duration_sec": audio["duration_sec"],
                "sample_rate_hz": audio["sample_rate_hz"],
                "channels": audio["channels"],
                "audio_format": audio["format"],
                "audio_subtype": audio["subtype"],
                "audio_sha256": snapshot_by_path[project_relative(audio_path)]["sha256"],
                "case_file_count": len(case_files),
                "case_size_bytes": sum(path.stat().st_size for path in case_files),
                "qwen_auto_case_summary_path": (
                    project_relative(qwen_path) if qwen_path is not None else None
                ),
                "text": "",
                "text_is_placeholder": True,
                "reference_text_included": False,
                "reference_transcript_path": None,
                "confirmed_transcript_path": None,
                "data_classification": "approved_protected_clinical_research_data",
                "metadata": {
                    "asr_input": "original_mp3_requires_deterministic_preprocessing",
                    "existing_transcripts": "automatic_auxiliary_only_not_reference",
                    "qwen_case_summary": "automatic_baseline_not_gold",
                },
            }
        )
    return records


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = resolve_project_path(args.raw_root).resolve()
    qwen_root = resolve_project_path(args.qwen_root).resolve()
    output_dir = resolve_project_path(args.output_dir)
    snapshot_rows = iter_snapshot_files(
        [("raw_review_package", raw_root), ("qwen_auto_case_summary", qwen_root)]
    )
    records = build_manifest_records(
        raw_root,
        qwen_root,
        snapshot_rows=snapshot_rows,
    )
    if args.expected_case_count and len(records) != args.expected_case_count:
        raise ValueError(
            f"病例数不符合预期：实际 {len(records)}，预期 {args.expected_case_count}"
        )
    manifest_path = output_dir / "remote_programming_40_asr_manifest.jsonl"
    snapshot_path = output_dir / "remote_programming_40_snapshot_files.jsonl"
    summary_path = output_dir / "remote_programming_40_snapshot_summary.json"
    write_jsonl(records, manifest_path)
    write_jsonl(snapshot_rows, snapshot_path)

    extension_counts = Counter(row["extension"] or "<none>" for row in snapshot_rows)
    duration_values = sorted(float(record["duration_sec"]) for record in records)
    summary = {
        "task_id": "T051",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": DATASET,
        "case_count": len(records),
        "audio_count": len(records),
        "audio_total_duration_sec": sum(duration_values),
        "audio_min_duration_sec": duration_values[0] if duration_values else None,
        "audio_median_duration_sec": statistics.median(duration_values)
        if duration_values
        else None,
        "audio_max_duration_sec": duration_values[-1] if duration_values else None,
        "snapshot_file_count": len(snapshot_rows),
        "snapshot_size_bytes": sum(row["size_bytes"] for row in snapshot_rows),
        "snapshot_sha256": snapshot_digest(snapshot_rows),
        "extension_counts": dict(sorted(extension_counts.items())),
        "paths": {
            "raw_root": project_relative(raw_root),
            "qwen_root": project_relative(qwen_root),
            "asr_manifest": project_relative(manifest_path),
            "snapshot_files": project_relative(snapshot_path),
        },
        "approval": {
            "confirmed_by_user_on": "2026-07-14",
            "approved_scope": ["external_llm", "external_asr", "original_audio_processing"],
        },
        "safety": {
            "contains_transcript_or_case_body": False,
            "automatic_transcripts_are_reference": False,
            "qwen_case_summaries_are_gold": False,
            "git_policy": "data/raw data/external data/interim remain ignored",
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
