"""从 T028 ASR confidence JSONL 整理 PriMock57 noisy transcript 新集。

输入是 `scripts/export_nemo_asr_confidence.py` 生成的 channel-level ASR
JSONL；输出两个便于后续评测/审阅衔接的数据集：

- channel 级：每行对应 doctor 或 patient 一路音频；
- consultation 级：每行合并同一 consultation 的 doctor/patient ASR segment，
  按时间排序形成 speaker_turns 和带说话人标签的 noisy_transcript。

本脚本会写出 ASR noisy transcript 正文，因此默认输出到 `data/processed/`
（项目约定不提交 Git）。summary 文件只包含计数、路径和质量检查，不包含 transcript、
TextGrid reference 或 notes 正文。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/processed/primock57/asr_noisy_transcripts_full"
DEFAULT_CHANNEL_JSONL = DEFAULT_OUTPUT_DIR / "primock57_noisy_transcripts_channel.jsonl"
DEFAULT_CONSULTATION_JSONL = DEFAULT_OUTPUT_DIR / "primock57_noisy_transcripts_consultation.jsonl"
DEFAULT_SUMMARY_JSON = DEFAULT_OUTPUT_DIR / "primock57_noisy_transcripts_summary.json"

CHANNEL_SCHEMA_VERSION = "primock57_noisy_transcript_channel/v0"
CONSULTATION_SCHEMA_VERSION = "primock57_noisy_transcript_consultation/v0"
SUMMARY_SCHEMA_VERSION = "primock57_noisy_transcript_dataset_summary/v0"
DATASET_VERSION = "primock57_asr_noisy_transcripts_full_v0"
CHANNEL_ORDER = {"doctor": 0, "patient": 1}


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def path_for_record(path_value: str | Path, project_root: Path = PROJECT_ROOT) -> str:
    path = resolve_project_path(path_value)
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"输入 ASR JSONL 不存在：{path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是合法 JSON：{path}") from exc
            records.append(record)

    if not records:
        raise ValueError(f"输入 ASR JSONL 为空：{path}")
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def confidence_level_from_value(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 0.90:
        return "green"
    if value >= 0.80:
        return "yellow"
    return "red"


def safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def word_confidence_summary(words: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        float(word["confidence"])
        for word in words
        if isinstance(word.get("confidence"), int | float)
    ]
    level_counts = Counter(
        str(word.get("confidence_level"))
        for word in words
        if word.get("confidence_level") is not None
    )
    summary: dict[str, Any] = {
        "word_count": len(words),
        "word_confidence_count": len(values),
        "confidence_level_counts": dict(sorted(level_counts.items())),
    }
    if values:
        sorted_values = sorted(values)
        summary.update(
            {
                "mean": round(sum(values) / len(values), 6),
                "min": round(sorted_values[0], 6),
                "max": round(sorted_values[-1], 6),
                "p50": round(percentile(sorted_values, 0.50), 6),
                "p10": round(percentile(sorted_values, 0.10), 6),
            }
        )
    else:
        summary.update({"mean": None, "min": None, "max": None, "p50": None, "p10": None})
    return summary


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("percentile 需要非空列表")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def compact_channel_pointer(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": record.get("sample_id"),
        "source_channel": record.get("source_channel"),
        "audio_filepath": record.get("audio_filepath"),
        "duration_sec": record.get("duration_sec"),
        "reference_textgrid_path": record.get("reference_textgrid_path"),
        "reference_text_included": bool(record.get("reference_text_included", False)),
        "asr_confidence": record.get("asr_confidence"),
        "confidence_level": record.get("confidence_level"),
        "asr_word_count": len(record.get("asr_words") or []),
        "asr_segment_count": len(record.get("asr_segments") or []),
        "uncertain_span_count": len(record.get("uncertain_spans") or []),
    }


def build_channel_dataset_record(
    record: dict[str, Any],
    *,
    source_asr_jsonl: Path,
    dataset_version: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    source_channel = record.get("source_channel")
    words = list(record.get("asr_words") or [])
    segments = list(record.get("asr_segments") or [])

    speaker_turns = [
        {
            "turn_index": index,
            "source_channel": source_channel,
            "speaker_label": segment.get("speaker_label") or source_channel,
            "start_sec": segment.get("start_sec"),
            "end_sec": segment.get("end_sec"),
            "text": segment.get("text") or "",
            "confidence": segment.get("confidence"),
            "confidence_level": segment.get("confidence_level"),
            "source_segment_id": segment.get("segment_id"),
        }
        for index, segment in enumerate(segments)
    ]

    return {
        "schema_version": CHANNEL_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "record_type": "channel_noisy_transcript",
        "sample_id": record.get("sample_id"),
        "consultation_sample_id": f"{record.get('dataset')}:{record.get('consultation_id')}",
        "dataset": record.get("dataset"),
        "split": record.get("split"),
        "consultation_id": record.get("consultation_id"),
        "source_channel": source_channel,
        "audio_filepath": record.get("audio_filepath"),
        "duration_sec": record.get("duration_sec"),
        "clean_transcript": None,
        "clean_reference": {
            "reference_textgrid_path": record.get("reference_textgrid_path"),
            "reference_transcript_path": record.get("reference_transcript_path"),
            "reference_text_included": bool(record.get("reference_text_included", False)),
            "reference_is_noisy": False,
        },
        "noisy_transcript": record.get("asr_transcript") or "",
        "asr_confidence": record.get("asr_confidence"),
        "confidence_level": record.get("confidence_level"),
        "asr_confidence_summary": word_confidence_summary(words),
        "asr_words": words,
        "asr_segments": segments,
        "uncertain_spans": list(record.get("uncertain_spans") or []),
        "asr_alternatives": list(record.get("asr_alternatives") or []),
        "confirmed_transcript": None,
        "speaker_turns": speaker_turns,
        "error_tags": [],
        "notes": {
            "source": "ASR noisy transcript generated from audio; not a clinical note.",
            "reference_text_not_included": True,
            "confirmed_transcript_pending": True,
            "research_use_only": True,
        },
        "source_asr": {
            "record_id": record.get("record_id"),
            "schema_version": record.get("schema_version"),
            "source_jsonl": path_for_record(source_asr_jsonl),
            "model": record.get("model"),
            "decoding": record.get("decoding"),
            "confidence": record.get("confidence"),
            "generated_at_utc": record.get("generated_at_utc"),
        },
        "generated_at_utc": generated_at_utc,
        "research_use_only": True,
        "clinical_use_warning": "研究用途 ASR noisy transcript，不得作为临床建议或病历依据。",
    }


def segment_sort_key(turn: dict[str, Any]) -> tuple[float, float, int, int]:
    start = turn.get("start_sec")
    end = turn.get("end_sec")
    channel = str(turn.get("source_channel") or "")
    source_index = turn.get("_source_index")
    return (
        float(start) if isinstance(start, int | float) else float("inf"),
        float(end) if isinstance(end, int | float) else float("inf"),
        CHANNEL_ORDER.get(channel, 99),
        int(source_index) if isinstance(source_index, int) else 0,
    )


def build_consultation_dataset_records(
    channel_records: list[dict[str, Any]],
    *,
    source_asr_jsonl: Path,
    dataset_version: str,
    generated_at_utc: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in channel_records:
        consultation_id = str(record.get("consultation_id") or "")
        if not consultation_id:
            raise ValueError(f"ASR record 缺少 consultation_id：{record.get('sample_id')}")
        grouped[consultation_id].append(record)

    consultation_records: list[dict[str, Any]] = []
    for consultation_id in sorted(grouped):
        records = sorted(
            grouped[consultation_id],
            key=lambda item: CHANNEL_ORDER.get(str(item.get("source_channel")), 99),
        )
        dataset = records[0].get("dataset")
        split_values = sorted({str(record.get("split")) for record in records})
        split = split_values[0] if len(split_values) == 1 else "mixed"

        all_words: list[dict[str, Any]] = []
        all_turns: list[dict[str, Any]] = []
        channels: dict[str, dict[str, Any]] = {}
        confidence_values: list[float] = []
        uncertain_span_count = 0
        segment_count = 0

        for record in records:
            channel = str(record.get("source_channel") or "unknown")
            words = list(record.get("asr_words") or [])
            segments = list(record.get("asr_segments") or [])
            all_words.extend(words)
            segment_count += len(segments)
            uncertain_span_count += len(record.get("uncertain_spans") or [])
            if isinstance(record.get("asr_confidence"), int | float):
                confidence_values.append(float(record["asr_confidence"]))

            channels[channel] = {
                **compact_channel_pointer(record),
                "noisy_transcript": (
                    record.get("noisy_transcript") or record.get("asr_transcript") or ""
                ),
            }

            for source_index, segment in enumerate(segments):
                text = segment.get("text") or ""
                all_turns.append(
                    {
                        "_source_index": source_index,
                        "source_channel": channel,
                        "speaker_label": segment.get("speaker_label") or channel,
                        "start_sec": segment.get("start_sec"),
                        "end_sec": segment.get("end_sec"),
                        "text": text,
                        "confidence": segment.get("confidence"),
                        "confidence_level": segment.get("confidence_level"),
                        "source_segment_id": segment.get("segment_id"),
                    }
                )

        sorted_turns = sorted(all_turns, key=segment_sort_key)
        speaker_turns = [
            {
                key: value
                for key, value in {"turn_index": index, **turn}.items()
                if key != "_source_index"
            }
            for index, turn in enumerate(sorted_turns)
        ]
        noisy_transcript = "\n".join(
            (
                f"{str(turn.get('speaker_label') or turn.get('source_channel')).upper()}: "
                f"{turn.get('text') or ''}"
            )
            for turn in speaker_turns
            if (turn.get("text") or "").strip()
        )
        consultation_confidence = safe_mean(confidence_values)

        consultation_records.append(
            {
                "schema_version": CONSULTATION_SCHEMA_VERSION,
                "dataset_version": dataset_version,
                "record_type": "consultation_noisy_transcript",
                "sample_id": f"{dataset}:{consultation_id}",
                "dataset": dataset,
                "split": split,
                "consultation_id": consultation_id,
                "channels": channels,
                "clean_transcript": None,
                "clean_reference": {
                    "reference_text_included": False,
                    "reference_is_noisy": False,
                    "channel_textgrid_paths": {
                        channel: channel_record.get("reference_textgrid_path")
                        for channel, channel_record in channels.items()
                    },
                },
                "noisy_transcript": noisy_transcript,
                "asr_confidence": consultation_confidence,
                "confidence_level": confidence_level_from_value(consultation_confidence),
                "asr_confidence_summary": word_confidence_summary(all_words),
                "asr_alternatives": [],
                "confirmed_transcript": None,
                "speaker_turns": speaker_turns,
                "error_tags": [],
                "notes": {
                    "source": (
                        "Merged doctor/patient channel ASR segments sorted by "
                        "channel-local timestamps."
                    ),
                    "reference_text_not_included": True,
                    "confirmed_transcript_pending": True,
                    "research_use_only": True,
                },
                "source_asr": {
                    "source_jsonl": path_for_record(source_asr_jsonl),
                    "channel_sample_ids": [record.get("sample_id") for record in records],
                    "channel_count": len(records),
                },
                "quality_checks": {
                    "has_doctor_channel": "doctor" in channels,
                    "has_patient_channel": "patient" in channels,
                    "speaker_turn_count": len(speaker_turns),
                    "asr_segment_count": segment_count,
                    "uncertain_span_count": uncertain_span_count,
                    "reference_text_included": False,
                },
                "generated_at_utc": generated_at_utc,
                "research_use_only": True,
                "clinical_use_warning": (
                    "研究用途 ASR noisy transcript，不得作为临床建议或病历依据。"
                ),
            }
        )
    return consultation_records


def build_summary(
    *,
    source_asr_jsonl: Path,
    channel_output_jsonl: Path,
    consultation_output_jsonl: Path,
    channel_records: list[dict[str, Any]],
    consultation_records: list[dict[str, Any]],
    generated_at_utc: str,
    dataset_version: str,
) -> dict[str, Any]:
    all_words = [
        word
        for record in channel_records
        for word in record.get("asr_words", [])
        if isinstance(word, dict)
    ]
    split_counts = Counter(str(record.get("split")) for record in channel_records)
    channel_counts = Counter(str(record.get("source_channel")) for record in channel_records)
    consultation_channel_counts = Counter(
        len(record.get("channels") or {}) for record in consultation_records
    )
    missing_channel_consultations = [
        record.get("consultation_id")
        for record in consultation_records
        if not record.get("quality_checks", {}).get("has_doctor_channel")
        or not record.get("quality_checks", {}).get("has_patient_channel")
    ]

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "source_asr_jsonl": path_for_record(source_asr_jsonl),
        "outputs": {
            "channel_jsonl": path_for_record(channel_output_jsonl),
            "consultation_jsonl": path_for_record(consultation_output_jsonl),
        },
        "counts": {
            "channel_records": len(channel_records),
            "consultation_records": len(consultation_records),
            "split_counts": dict(sorted(split_counts.items())),
            "channel_counts": dict(sorted(channel_counts.items())),
            "consultation_channel_count_distribution": {
                str(key): value for key, value in sorted(consultation_channel_counts.items())
            },
            "asr_word_count": len(all_words),
            "asr_segment_count": sum(
                len(record.get("asr_segments") or []) for record in channel_records
            ),
            "uncertain_span_count": sum(
                len(record.get("uncertain_spans") or []) for record in channel_records
            ),
        },
        "confidence_summary": word_confidence_summary(all_words),
        "validation": {
            "no_inline_reference_text": all(
                not record.get("clean_reference", {}).get("reference_text_included")
                for record in channel_records + consultation_records
            ),
            "no_confirmed_transcript_yet": all(
                record.get("confirmed_transcript") is None
                for record in channel_records + consultation_records
            ),
            "all_consultations_have_doctor_and_patient": not missing_channel_consultations,
            "missing_channel_consultations": missing_channel_consultations,
            "summary_contains_no_transcript_text": True,
        },
        "next_step": (
            "后续可读取 consultation_jsonl 作为 noisy_asr 输入，或用 source_asr_jsonl "
            "继续生成医学实体审阅 span、confirmed transcript 与下游评测。"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--channel-output-jsonl", type=Path, default=DEFAULT_CHANNEL_JSONL)
    parser.add_argument(
        "--consultation-output-jsonl",
        type=Path,
        default=DEFAULT_CONSULTATION_JSONL,
    )
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--dataset-version", default=DATASET_VERSION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_jsonl = resolve_project_path(args.input_jsonl)
    channel_output_jsonl = resolve_project_path(args.channel_output_jsonl)
    consultation_output_jsonl = resolve_project_path(args.consultation_output_jsonl)
    summary_json = resolve_project_path(args.summary_json)
    generated_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    asr_records = load_jsonl(input_jsonl)
    channel_records = [
        build_channel_dataset_record(
            record,
            source_asr_jsonl=input_jsonl,
            dataset_version=args.dataset_version,
            generated_at_utc=generated_at_utc,
        )
        for record in asr_records
    ]
    consultation_records = build_consultation_dataset_records(
        channel_records,
        source_asr_jsonl=input_jsonl,
        dataset_version=args.dataset_version,
        generated_at_utc=generated_at_utc,
    )
    summary = build_summary(
        source_asr_jsonl=input_jsonl,
        channel_output_jsonl=channel_output_jsonl,
        consultation_output_jsonl=consultation_output_jsonl,
        channel_records=channel_records,
        consultation_records=consultation_records,
        generated_at_utc=generated_at_utc,
        dataset_version=args.dataset_version,
    )

    write_jsonl(channel_records, channel_output_jsonl)
    write_jsonl(consultation_records, consultation_output_jsonl)
    write_json(summary, summary_json)

    print("PriMock57 noisy transcript 新集整理完成。")
    print(f"- channel records: {len(channel_records)}")
    print(f"- consultation records: {len(consultation_records)}")
    print(f"- channel JSONL: {channel_output_jsonl}")
    print(f"- consultation JSONL: {consultation_output_jsonl}")
    print(f"- summary: {summary_json}")


if __name__ == "__main__":
    main()
