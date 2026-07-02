"""生成 PriMock57 第一批 ASR 输入 manifest。

本脚本只写入音频、TextGrid reference 和 notes 的文件指针及结构化元数据，
不把人工转录、病例 note 或 presenting complaint 正文写入 manifest。

默认输出：
- data/interim/primock57/manifests/primock57_consultation_seed_manifest.jsonl
- data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl
- data/interim/primock57/manifests/primock57_asr_manifest_summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATASET = "primock57"
MANIFEST_VERSION = "primock57_asr_input_manifest/v0"
DEFAULT_SPLIT = "seed_asr_v0"
CHANNELS = ("doctor", "patient")
LICENSE_NAME = "Creative Commons Attribution 4.0 International"
LICENSE_SPDX = "CC-BY-4.0"

CONSULTATION_ID_PATTERN = re.compile(r"^day(?P<day>\d+)_consultation(?P<consultation>\d+)$")
AUDIO_NAME_PATTERN = re.compile(
    r"^(?P<consultation_id>day\d+_consultation\d+)_(?P<channel>doctor|patient)\.wav$",
    flags=re.IGNORECASE,
)
TEXTGRID_VALUE_PATTERN = re.compile(r"^\s*(?P<key>xmin|xmax|text)\s*=\s*(?P<value>.*)\s*$")


@dataclass(frozen=True)
class ConsultationKey:
    """PriMock57 consultation 编号。"""

    consultation_id: str
    day: int
    consultation: int

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.day, self.consultation)


def parse_consultation_id(consultation_id: str) -> ConsultationKey:
    """解析形如 day1_consultation01 的 consultation id。"""

    match = CONSULTATION_ID_PATTERN.match(consultation_id)
    if match is None:
        raise ValueError(f"无法解析 PriMock57 consultation id：{consultation_id}")
    return ConsultationKey(
        consultation_id=consultation_id,
        day=int(match.group("day")),
        consultation=int(match.group("consultation")),
    )


def path_for_manifest(path: Path, project_root: Path = PROJECT_ROOT) -> str:
    """将路径写成相对 project root 的 POSIX 风格字符串；无法相对化时保留绝对路径。"""

    resolved_path = path.resolve()
    resolved_root = project_root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return str(resolved_path)


def audio_info(path: Path) -> dict[str, Any]:
    """读取 wav 音频头信息，不读取或写出音频内容。"""

    with wave.open(str(path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        duration_sec = frame_count / frame_rate if frame_rate else 0.0
        return {
            "duration_sec": round(duration_sec, 3),
            "sample_rate_hz": frame_rate,
            "channels": wav_file.getnchannels(),
            "sample_width_bytes": wav_file.getsampwidth(),
            "frame_count": frame_count,
        }


def _unquote_textgrid_text(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.replace('""', '"')


def textgrid_reference_info(path: Path) -> dict[str, Any]:
    """读取 TextGrid 的时间边界与 utterance 计数，但不返回转录正文。"""

    xmin_values: list[float] = []
    xmax_values: list[float] = []
    text_interval_count = 0
    non_empty_text_interval_count = 0
    unsure_tag_count = 0
    unintelligible_tag_count = 0

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            match = TEXTGRID_VALUE_PATTERN.match(line)
            if match is None:
                continue

            key = match.group("key")
            raw_value = match.group("value")
            if key in {"xmin", "xmax"}:
                try:
                    value = float(raw_value.strip())
                except ValueError:
                    continue
                if key == "xmin":
                    xmin_values.append(value)
                else:
                    xmax_values.append(value)
                continue

            text = _unquote_textgrid_text(raw_value)
            text_interval_count += 1
            if text.strip():
                non_empty_text_interval_count += 1
            unsure_tag_count += text.count("<UNSURE>")
            unintelligible_tag_count += text.count("<UNIN/>")

    return {
        "format": "TextGrid",
        "duration_sec": round(max(xmax_values), 3) if xmax_values else None,
        "min_start_sec": round(min(xmin_values), 3) if xmin_values else None,
        "utterance_intervals": text_interval_count,
        "non_empty_utterance_intervals": non_empty_text_interval_count,
        "tag_counts": {
            "unsure": unsure_tag_count,
            "unintelligible": unintelligible_tag_count,
        },
        "text_fields_included": False,
    }


def discover_consultations(data_root: Path) -> list[ConsultationKey]:
    """从 audio 目录发现 doctor/patient 双路都存在的 consultation。"""

    audio_dir = data_root / "audio"
    by_consultation: dict[str, set[str]] = {}
    for audio_path in audio_dir.glob("*.wav"):
        match = AUDIO_NAME_PATTERN.match(audio_path.name)
        if match is None:
            continue
        consultation_id = match.group("consultation_id")
        channel = match.group("channel").lower()
        by_consultation.setdefault(consultation_id, set()).add(channel)

    complete = [
        parse_consultation_id(consultation_id)
        for consultation_id, channels in by_consultation.items()
        if all(channel in channels for channel in CHANNELS)
    ]
    return sorted(complete, key=lambda item: item.sort_key)


def select_consultations(
    available: list[ConsultationKey],
    *,
    limit: int,
    sample_ids: list[str] | None,
) -> list[ConsultationKey]:
    """按显式 sample_ids 或稳定排序选择 consultation。"""

    if sample_ids:
        by_id = {item.consultation_id: item for item in available}
        missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
        if missing:
            raise ValueError(f"指定的 consultation 不存在或不完整：{missing}")
        return [by_id[sample_id] for sample_id in sample_ids]

    if limit <= 0:
        raise ValueError("--limit 必须大于 0")
    return available[:limit]


def build_channel_record(
    *,
    data_root: Path,
    consultation: ConsultationKey,
    channel: str,
    project_root: Path,
) -> dict[str, Any]:
    """构造单个 doctor/patient channel 的文件指针与检查信息。"""

    audio_path = data_root / "audio" / f"{consultation.consultation_id}_{channel}.wav"
    textgrid_path = data_root / "transcripts" / f"{consultation.consultation_id}_{channel}.TextGrid"
    if not audio_path.exists():
        raise FileNotFoundError(f"缺少音频文件：{audio_path}")
    if not textgrid_path.exists():
        raise FileNotFoundError(f"缺少 TextGrid reference：{textgrid_path}")

    audio = audio_info(audio_path)
    reference = textgrid_reference_info(textgrid_path)
    textgrid_duration = reference["duration_sec"]
    duration_delta = None
    if textgrid_duration is not None:
        duration_delta = round(abs(audio["duration_sec"] - textgrid_duration), 3)

    return {
        "source_channel": channel,
        "audio_path": path_for_manifest(audio_path, project_root),
        "reference_textgrid_path": path_for_manifest(textgrid_path, project_root),
        "audio": audio,
        "reference": reference,
        "checks": {
            "audio_exists": True,
            "reference_textgrid_exists": True,
            "audio_textgrid_duration_delta_sec": duration_delta,
            "reference_text_included": False,
        },
    }


def build_consultation_record(
    *,
    data_root: Path,
    consultation: ConsultationKey,
    split: str,
    project_root: Path,
) -> dict[str, Any]:
    """构造 consultation 级 manifest 记录。"""

    notes_path = data_root / "notes" / f"{consultation.consultation_id}.json"
    if not notes_path.exists():
        raise FileNotFoundError(f"缺少 notes JSON：{notes_path}")

    channels = {
        channel: build_channel_record(
            data_root=data_root,
            consultation=consultation,
            channel=channel,
            project_root=project_root,
        )
        for channel in CHANNELS
    }

    return {
        "manifest_version": MANIFEST_VERSION,
        "sample_id": f"{DATASET}:{consultation.consultation_id}",
        "dataset": DATASET,
        "split": split,
        "consultation_id": consultation.consultation_id,
        "day": consultation.day,
        "consultation": consultation.consultation,
        "channels": channels,
        "notes_pointer": {
            "source_file": path_for_manifest(notes_path, project_root),
            "format": "json",
            "fields": ["day", "consultation", "presenting_complaint", "note", "highlights"],
            "text_fields_included": False,
        },
        "license": {
            "name": LICENSE_NAME,
            "spdx": LICENSE_SPDX,
            "license_file": path_for_manifest(data_root / "LICENSE.md", project_root),
            "attribution_required": True,
            "citation_source": path_for_manifest(data_root / "README.md", project_root),
        },
        "reference_alignment_plan": {
            "input_mode": "doctor_patient_separate_channels",
            "asr_step": "分别对 doctor/patient wav 运行 ASR，保留 source_channel。",
            "reference_step": "分别读取同名 doctor/patient TextGrid 作为 clean/reference 指针。",
            "merge_step": (
                "ASR 与 reference 均按 channel-local start_sec 排序合并；"
                "若两路时间轴存在细小偏差，先保留 source_channel 再做容差对齐。"
            ),
            "reference_is_noisy": False,
        },
        "privacy_and_safety": {
            "mock_consultation": True,
            "contains_real_patient_data": False,
            "no_inline_audio_or_text": True,
            "do_not_commit_source_data": True,
        },
        "checks": {
            "doctor_audio_exists": channels["doctor"]["checks"]["audio_exists"],
            "patient_audio_exists": channels["patient"]["checks"]["audio_exists"],
            "doctor_textgrid_exists": channels["doctor"]["checks"]["reference_textgrid_exists"],
            "patient_textgrid_exists": channels["patient"]["checks"]["reference_textgrid_exists"],
            "notes_exists": True,
            "reference_text_included": False,
            "notes_text_included": False,
        },
    }


def build_nemo_audio_records(consultation_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 consultation manifest 派生 NeMo 可读取的 channel-level ASR 输入 manifest。"""

    audio_records: list[dict[str, Any]] = []
    for consultation_record in consultation_records:
        for channel in CHANNELS:
            channel_record = consultation_record["channels"][channel]
            audio_records.append(
                {
                    "audio_filepath": channel_record["audio_path"],
                    "duration": channel_record["audio"]["duration_sec"],
                    "text": "",
                    "text_is_placeholder": True,
                    "sample_id": f"{consultation_record['sample_id']}:{channel}",
                    "consultation_sample_id": consultation_record["sample_id"],
                    "dataset": DATASET,
                    "split": consultation_record["split"],
                    "consultation_id": consultation_record["consultation_id"],
                    "source_channel": channel,
                    "reference_textgrid_path": channel_record["reference_textgrid_path"],
                    "notes_path": consultation_record["notes_pointer"]["source_file"],
                    "reference_text_included": False,
                }
            )
    return audio_records


def build_manifests(
    *,
    data_root: Path,
    limit: int,
    sample_ids: list[str] | None = None,
    split: str = DEFAULT_SPLIT,
    project_root: Path = PROJECT_ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """构建 consultation-level manifest、NeMo audio manifest 和 summary。"""

    available = discover_consultations(data_root)
    selected = select_consultations(available, limit=limit, sample_ids=sample_ids)
    consultation_records = [
        build_consultation_record(
            data_root=data_root,
            consultation=consultation,
            split=split,
            project_root=project_root,
        )
        for consultation in selected
    ]
    nemo_audio_records = build_nemo_audio_records(consultation_records)

    total_channel_duration = round(
        sum(record["duration"] for record in nemo_audio_records),
        3,
    )
    total_reference_intervals = sum(
        channel_record["reference"]["utterance_intervals"]
        for consultation_record in consultation_records
        for channel_record in consultation_record["channels"].values()
    )
    max_duration_delta = max(
        (
            channel_record["checks"]["audio_textgrid_duration_delta_sec"] or 0.0
            for consultation_record in consultation_records
            for channel_record in consultation_record["channels"].values()
        ),
        default=0.0,
    )

    summary = {
        "dataset": DATASET,
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_root": path_for_manifest(data_root, project_root),
        "available_complete_consultations": len(available),
        "selected_consultations": [item.consultation_id for item in selected],
        "consultation_records": len(consultation_records),
        "channel_audio_records": len(nemo_audio_records),
        "total_channel_duration_sec": total_channel_duration,
        "total_reference_utterance_intervals": total_reference_intervals,
        "max_audio_textgrid_duration_delta_sec": round(max_duration_delta, 3),
        "license": {
            "name": LICENSE_NAME,
            "spdx": LICENSE_SPDX,
            "license_file": path_for_manifest(data_root / "LICENSE.md", project_root),
            "attribution_required": True,
        },
        "validation": {
            "sample_count_within_t025_target": 3 <= len(consultation_records) <= 5,
            "all_selected_files_exist": True,
            "no_inline_reference_text": True,
            "no_inline_notes_text": True,
            "nemo_manifest_text_is_empty_placeholder": True,
        },
        "next_step": "T026：使用 project 内 NeMo 权重对 1 条 channel 音频做 smoke test。",
    }
    return consultation_records, nemo_audio_records, summary


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """写入 JSONL。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: Path) -> None:
    """写入 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/external/primock57"),
        help="PriMock57 本地数据根目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/interim/primock57/manifests"),
        help="manifest 输出目录。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="未显式指定 sample ids 时，按稳定排序选取的 consultation 数量。",
    )
    parser.add_argument(
        "--sample-ids",
        nargs="*",
        default=None,
        help="可选，显式指定 consultation id，例如 day1_consultation01。",
    )
    parser.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="写入 manifest 的 split 名称。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    consultation_manifest_path = args.output_dir / "primock57_consultation_seed_manifest.jsonl"
    nemo_manifest_path = args.output_dir / "primock57_nemo_asr_input_manifest.jsonl"
    summary_path = args.output_dir / "primock57_asr_manifest_summary.json"

    consultation_records, nemo_audio_records, summary = build_manifests(
        data_root=args.data_root,
        limit=args.limit,
        sample_ids=args.sample_ids,
        split=args.split,
    )
    summary["outputs"] = {
        "consultation_manifest": path_for_manifest(consultation_manifest_path),
        "nemo_audio_manifest": path_for_manifest(nemo_manifest_path),
        "summary": path_for_manifest(summary_path),
    }

    write_jsonl(consultation_records, consultation_manifest_path)
    write_jsonl(nemo_audio_records, nemo_manifest_path)
    write_json(summary, summary_path)

    print("PriMock57 ASR 输入 manifest 生成完成。")
    print(f"- consultation records: {len(consultation_records)}")
    print(f"- channel audio records: {len(nemo_audio_records)}")
    print(f"- selected: {', '.join(summary['selected_consultations'])}")
    print(f"- consultation manifest: {consultation_manifest_path}")
    print(f"- NeMo audio manifest: {nemo_manifest_path}")
    print(f"- summary: {summary_path}")


if __name__ == "__main__":
    main()
