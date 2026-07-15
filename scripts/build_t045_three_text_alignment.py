"""T045：建立 PriMock57 三文本病例摘要评测的 consultation 对齐清单。

本脚本完成 T045 第 1 步“三文本样本对齐”：

- 读取全量 consultation-level noisy ASR transcript JSONL；
- 核对 PriMock57 doctor/patient TextGrid clean/reference 文件是否成对存在；
- 可选读取后续生成的 doctor_llm_repair transcript JSONL；
- 输出 57 条 consultation 的统一 alignment manifest 和不含正文的 summary。

注意：alignment manifest 只保存路径、ID、计数和状态，不写入 noisy ASR、
TextGrid clean/reference 或 repair transcript 正文。完整 transcript 仍只保留在
`data/processed/` 或 `outputs/` 下游产物中，默认不提交 Git。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TASK_ID = "T045"
ALIGNMENT_SCHEMA_VERSION = "t045_three_text_alignment_record/v0"
SUMMARY_SCHEMA_VERSION = "t045_three_text_alignment_summary/v0"
DATASET = "primock57"
INPUT_UNIT = "consultation"
CHANNELS = ("doctor", "patient")
CONSULTATION_ID_PATTERN = re.compile(r"^day(?P<day>\d+)_consultation(?P<consultation>\d+)$")
TEXTGRID_FILENAME_PATTERN = re.compile(
    r"^(?P<consultation_id>day\d+_consultation\d+)_(?P<channel>doctor|patient)\.TextGrid$",
    flags=re.IGNORECASE,
)
TEXTGRID_VALUE_PATTERN = re.compile(r"^\s*(?P<key>xmin|xmax|text)\s*=\s*(?P<value>.*)\s*$")

DEFAULT_NOISY_CONSULTATION_JSONL = (
    PROJECT_ROOT
    / "data/processed/primock57/asr_noisy_transcripts_full/"
    "primock57_noisy_transcripts_consultation.jsonl"
)
DEFAULT_TEXTGRID_DIR = PROJECT_ROOT / "data/external/primock57/transcripts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t045_case_summary_three_texts"
DEFAULT_REPAIR_JSONL = DEFAULT_OUTPUT_DIR / "primock57_doctor_llm_repair_transcripts.jsonl"
DEFAULT_ALIGNMENT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_t045_three_text_alignment.jsonl"
DEFAULT_SUMMARY_JSON = DEFAULT_OUTPUT_DIR / "primock57_t045_three_text_alignment_summary.json"


def resolve_project_path(path_value: str | Path, project_root: Path = PROJECT_ROOT) -> Path:
    """把相对路径解析为 project root 下路径。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return project_root / path


def path_for_record(path_value: str | Path | None, project_root: Path = PROJECT_ROOT) -> str | None:
    """将路径保存为相对 project root 的 POSIX 风格字符串。"""

    if path_value is None:
        return None
    path = resolve_project_path(path_value, project_root)
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def consultation_sort_key(consultation_id: str) -> tuple[int, int, str]:
    """稳定排序 PriMock57 consultation id。"""

    match = CONSULTATION_ID_PATTERN.match(consultation_id)
    if match is None:
        return (9999, 9999, consultation_id)
    return (
        int(match.group("day")),
        int(match.group("consultation")),
        consultation_id,
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL。"""

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
                raise ValueError(f"第 {line_number} 行不是合法 JSON：{path}") from exc
    if not records:
        raise ValueError(f"JSONL 为空：{path}")
    return records


def load_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取可选 JSONL；不存在时返回空列表。"""

    if not path.exists():
        return []
    return load_jsonl(path)


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


def unquote_textgrid_text(raw_value: str) -> str:
    """解析 TextGrid text 字段，但调用方只做计数，不保存正文。"""

    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.replace('""', '"')


def textgrid_reference_info(path: Path) -> dict[str, Any]:
    """读取 TextGrid 的时间边界、utterance 计数和特殊标签计数，不返回转录正文。"""

    xmin_values: list[float] = []
    xmax_values: list[float] = []
    interval_count = 0
    non_empty_interval_count = 0
    tag_counts: Counter[str] = Counter()

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

            text = unquote_textgrid_text(raw_value)
            interval_count += 1
            if text.strip():
                non_empty_interval_count += 1
            tag_counts["<UNSURE>"] += text.count("<UNSURE>")
            tag_counts["<UNIN/>"] += text.count("<UNIN/>")

    return {
        "format": "TextGrid",
        "duration_sec": round(max(xmax_values), 3) if xmax_values else None,
        "min_start_sec": round(min(xmin_values), 3) if xmin_values else None,
        "utterance_intervals": interval_count,
        "non_empty_utterance_intervals": non_empty_interval_count,
        "tag_counts": dict(sorted(tag_counts.items())),
        "text_fields_included": False,
    }


def discover_textgrid_pairs(textgrid_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """发现并汇总每条 consultation 的 doctor/patient TextGrid 文件。"""

    if not textgrid_dir.exists():
        raise FileNotFoundError(f"TextGrid 目录不存在：{textgrid_dir}")

    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for textgrid_path in sorted(textgrid_dir.glob("*.TextGrid")):
        match = TEXTGRID_FILENAME_PATTERN.match(textgrid_path.name)
        if match is None:
            continue
        consultation_id = match.group("consultation_id")
        channel = match.group("channel").lower()
        pairs[consultation_id][channel] = {
            "path": path_for_record(textgrid_path),
            "reference": textgrid_reference_info(textgrid_path),
        }
    return {key: dict(value) for key, value in pairs.items()}


def group_records_by_consultation(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 consultation_id 分组；兼容 sample_id 中携带 consultation_id 的记录。"""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        consultation_id = consultation_id_for_record(record)
        if consultation_id:
            grouped[consultation_id].append(record)
    return dict(grouped)


def consultation_id_for_record(record: dict[str, Any]) -> str | None:
    """从常见字段中提取 consultation_id。"""

    consultation_id = record.get("consultation_id")
    if isinstance(consultation_id, str) and consultation_id.strip():
        return consultation_id.strip()

    sample_id = record.get("sample_id") or record.get("bundle_id")
    if isinstance(sample_id, str):
        for part in re.split(r"[:/|]", sample_id):
            if CONSULTATION_ID_PATTERN.match(part):
                return part
    return None


def channels_for_noisy_record(record: dict[str, Any]) -> list[str]:
    """从 consultation-level noisy record 中读取声道列表。"""

    channels = record.get("channels")
    if isinstance(channels, dict):
        return sorted(channel for channel in channels if channel in CHANNELS)
    discovered = {
        str(turn.get("source_channel") or turn.get("speaker_label"))
        for turn in record.get("speaker_turns") or []
        if isinstance(turn, dict)
    }
    return sorted(channel for channel in discovered if channel in CHANNELS)


def channels_for_repair_records(records: list[dict[str, Any]]) -> list[str]:
    """从 repair/confirmed transcript 记录中读取声道列表。"""

    channels = {
        str(record.get("source_channel"))
        for record in records
        if record.get("source_channel") in CHANNELS
    }
    if not channels and records:
        return list(CHANNELS)
    return sorted(channels)


def compact_repair_status(
    consultation_id: str,
    repair_grouped: dict[str, list[dict[str, Any]]],
    *,
    repair_jsonl: Path,
) -> dict[str, Any]:
    """构造 repair variant 的对齐状态，不写入 repair 正文。"""

    records = repair_grouped.get(consultation_id, [])
    if not records:
        return {
            "status": "pending_generation",
            "source_jsonl": path_for_record(repair_jsonl) if repair_jsonl.exists() else None,
            "record_count": 0,
            "channels": [],
            "transcript_text_included": False,
            "feedback_log_required": True,
            "notes": (
                "doctor_llm_repair 尚未生成；后续需由独立 doctor selector "
                "基于 noisy ASR 与候选词生成 feedback log，再回放为 repair transcript。"
            ),
        }

    return {
        "status": "available",
        "source_jsonl": path_for_record(repair_jsonl),
        "record_count": len(records),
        "channels": channels_for_repair_records(records),
        "sample_ids": [record.get("sample_id") for record in records],
        "transcript_text_included": False,
        "feedback_log_required": True,
    }


def build_alignment_records(
    *,
    noisy_records: list[dict[str, Any]],
    textgrid_pairs: dict[str, dict[str, dict[str, Any]]],
    repair_records: list[dict[str, Any]],
    noisy_jsonl: Path,
    repair_jsonl: Path,
    generated_at_utc: str,
    textgrid_dir: Path = DEFAULT_TEXTGRID_DIR,
) -> list[dict[str, Any]]:
    """生成三文本 alignment manifest records。"""

    noisy_by_consultation = group_records_by_consultation(noisy_records)
    if len(noisy_by_consultation) != len(noisy_records):
        duplicate_ids = [
            consultation_id
            for consultation_id, group in noisy_by_consultation.items()
            if len(group) > 1
        ]
        raise ValueError(f"noisy consultation JSONL 中存在重复或缺失 ID：{duplicate_ids}")

    repair_grouped = group_records_by_consultation(repair_records)
    alignment_records: list[dict[str, Any]] = []
    for record_index, consultation_id in enumerate(
        sorted(noisy_by_consultation, key=consultation_sort_key)
    ):
        noisy_record = noisy_by_consultation[consultation_id][0]
        noisy_channels = channels_for_noisy_record(noisy_record)
        clean_channels = sorted(
            channel for channel in textgrid_pairs.get(consultation_id, {}) if channel in CHANNELS
        )
        clean_status = (
            "textgrid_pair_available"
            if all(channel in clean_channels for channel in CHANNELS)
            else "missing_textgrid_pair"
        )
        repair_status = compact_repair_status(
            consultation_id,
            repair_grouped,
            repair_jsonl=repair_jsonl,
        )
        has_repair = repair_status["status"] == "available"

        alignment_records.append(
            {
                "schema_version": ALIGNMENT_SCHEMA_VERSION,
                "task_id": TASK_ID,
                "record_type": "three_text_alignment",
                "dataset": noisy_record.get("dataset") or DATASET,
                "split": noisy_record.get("split"),
                "sample_id": noisy_record.get("sample_id") or f"{DATASET}:{consultation_id}",
                "consultation_id": consultation_id,
                "input_unit": INPUT_UNIT,
                "input_variants": {
                    "noisy_asr": {
                        "status": "available",
                        "source_jsonl": path_for_record(noisy_jsonl),
                        "source_record_index": record_index,
                        "sample_id": noisy_record.get("sample_id"),
                        "split": noisy_record.get("split"),
                        "channels": noisy_channels,
                        "speaker_turn_count": len(noisy_record.get("speaker_turns") or []),
                        "asr_confidence": noisy_record.get("asr_confidence"),
                        "confidence_level": noisy_record.get("confidence_level"),
                        "transcript_text_included": False,
                        "source_record_contains_transcript_text": True,
                    },
                    "clean_reference": {
                        "status": clean_status,
                        "source_textgrid_dir": path_for_record(textgrid_dir),
                        "channel_textgrid_paths": {
                            channel: textgrid_pairs.get(consultation_id, {})
                            .get(channel, {})
                            .get("path")
                            for channel in CHANNELS
                        },
                        "channels": clean_channels,
                        "textgrid_info": {
                            channel: textgrid_pairs.get(consultation_id, {})
                            .get(channel, {})
                            .get("reference")
                            for channel in CHANNELS
                        },
                        "transcript_text_included": False,
                        "clean_reference_jsonl_status": "pending_t045_step2",
                        "special_tag_policy": {
                            "<UNSURE>": "preserve_for_step2_then_record_normalization_policy",
                            "<UNIN/>": "preserve_for_step2_then_record_normalization_policy",
                        },
                    },
                    "doctor_llm_repair": repair_status,
                },
                "alignment_checks": {
                    "has_noisy_asr": True,
                    "has_clean_reference_textgrid_pair": clean_status
                    == "textgrid_pair_available",
                    "has_doctor_llm_repair": has_repair,
                    "noisy_channels_match_expected": all(
                        channel in noisy_channels for channel in CHANNELS
                    ),
                    "clean_channels_match_expected": all(
                        channel in clean_channels for channel in CHANNELS
                    ),
                    "repair_channels_match_expected": (
                        all(channel in repair_status["channels"] for channel in CHANNELS)
                        if has_repair
                        else None
                    ),
                    "ready_for_clean_reference_build": clean_status
                    == "textgrid_pair_available",
                    "ready_for_candidate_generation": True,
                    "ready_for_three_text_summary_generation": (
                        clean_status == "textgrid_pair_available" and has_repair
                    ),
                },
                "privacy_and_safety": {
                    "manifest_contains_full_transcript_text": False,
                    "summary_should_not_include_full_transcript_text": True,
                    "research_use_only": True,
                    "doctor_llm_repair_is_simulated_doctor_selection": True,
                },
                "generated_at_utc": generated_at_utc,
            }
        )
    return alignment_records


def aggregate_textgrid_tag_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """聚合 alignment records 中的 TextGrid 特殊标签计数。"""

    counter: Counter[str] = Counter()
    for record in records:
        info_by_channel = record["input_variants"]["clean_reference"]["textgrid_info"]
        for info in info_by_channel.values():
            if not isinstance(info, dict):
                continue
            counter.update(info.get("tag_counts") or {})
    return dict(sorted(counter.items()))


def build_summary(
    *,
    alignment_records: list[dict[str, Any]],
    noisy_jsonl: Path,
    textgrid_dir: Path,
    repair_jsonl: Path,
    alignment_jsonl: Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    """生成不含 transcript 正文的 T045 alignment summary。"""

    split_counts = Counter(record.get("split") for record in alignment_records)
    noisy_channel_count_distribution = Counter(
        len(record["input_variants"]["noisy_asr"]["channels"])
        for record in alignment_records
    )
    clean_channel_count_distribution = Counter(
        len(record["input_variants"]["clean_reference"]["channels"])
        for record in alignment_records
    )
    repair_status_counts = Counter(
        record["input_variants"]["doctor_llm_repair"]["status"]
        for record in alignment_records
    )
    missing_clean_ids = [
        record["consultation_id"]
        for record in alignment_records
        if not record["alignment_checks"]["has_clean_reference_textgrid_pair"]
    ]
    pending_repair_ids = [
        record["consultation_id"]
        for record in alignment_records
        if not record["alignment_checks"]["has_doctor_llm_repair"]
    ]
    ready_for_step2_ids = [
        record["consultation_id"]
        for record in alignment_records
        if record["alignment_checks"]["ready_for_clean_reference_build"]
    ]

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "step": "1_three_text_sample_alignment",
        "generated_at_utc": generated_at_utc,
        "dataset": DATASET,
        "input_files": {
            "noisy_consultation_jsonl": path_for_record(noisy_jsonl),
            "textgrid_dir": path_for_record(textgrid_dir),
            "doctor_llm_repair_jsonl": path_for_record(repair_jsonl)
            if repair_jsonl.exists()
            else None,
        },
        "output_files": {
            "alignment_jsonl": path_for_record(alignment_jsonl),
        },
        "counts": {
            "alignment_records": len(alignment_records),
            "split_counts": dict(sorted(split_counts.items())),
            "noisy_asr_available": sum(
                record["alignment_checks"]["has_noisy_asr"] for record in alignment_records
            ),
            "clean_reference_textgrid_pair_available": sum(
                record["alignment_checks"]["has_clean_reference_textgrid_pair"]
                for record in alignment_records
            ),
            "doctor_llm_repair_available": sum(
                record["alignment_checks"]["has_doctor_llm_repair"]
                for record in alignment_records
            ),
            "doctor_llm_repair_pending": len(pending_repair_ids),
            "ready_for_clean_reference_build": len(ready_for_step2_ids),
            "ready_for_three_text_summary_generation": sum(
                record["alignment_checks"]["ready_for_three_text_summary_generation"]
                for record in alignment_records
            ),
            "noisy_channel_count_distribution": {
                str(key): value for key, value in sorted(noisy_channel_count_distribution.items())
            },
            "clean_textgrid_channel_count_distribution": {
                str(key): value for key, value in sorted(clean_channel_count_distribution.items())
            },
            "doctor_llm_repair_status_counts": dict(sorted(repair_status_counts.items())),
            "textgrid_tag_counts": aggregate_textgrid_tag_counts(alignment_records),
            "textgrid_non_empty_utterance_intervals": sum(
                (info or {}).get("non_empty_utterance_intervals", 0)
                for record in alignment_records
                for info in record["input_variants"]["clean_reference"][
                    "textgrid_info"
                ].values()
            ),
        },
        "validation": {
            "all_noisy_consultations_have_doctor_patient_channels": all(
                record["alignment_checks"]["noisy_channels_match_expected"]
                for record in alignment_records
            ),
            "all_noisy_consultations_have_clean_textgrid_pair": not missing_clean_ids,
            "missing_clean_reference_consultation_ids": missing_clean_ids,
            "doctor_llm_repair_missing_or_pending_consultation_ids": pending_repair_ids,
            "manifest_contains_full_transcript_text": False,
            "summary_contains_full_transcript_text": False,
            "reference_text_included": False,
            "research_use_only": True,
        },
        "next_step": (
            "T045 第 2 步：解析 PriMock57 doctor/patient TextGrid，按时间戳合并为 "
            "consultation-level clean_reference JSONL，并记录 <UNSURE>/<UNIN/> 处理策略。"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--noisy-consultation-jsonl",
        type=Path,
        default=DEFAULT_NOISY_CONSULTATION_JSONL,
        help="全量 consultation-level noisy ASR JSONL。",
    )
    parser.add_argument(
        "--textgrid-dir",
        type=Path,
        default=DEFAULT_TEXTGRID_DIR,
        help="PriMock57 doctor/patient TextGrid 目录。",
    )
    parser.add_argument(
        "--repair-jsonl",
        type=Path,
        default=DEFAULT_REPAIR_JSONL,
        help="可选 doctor_llm_repair transcript JSONL；不存在时标记为 pending。",
    )
    parser.add_argument(
        "--alignment-jsonl",
        type=Path,
        default=DEFAULT_ALIGNMENT_JSONL,
        help="输出 alignment manifest JSONL。",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_SUMMARY_JSON,
        help="输出不含正文的 summary JSON。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    noisy_jsonl = resolve_project_path(args.noisy_consultation_jsonl)
    textgrid_dir = resolve_project_path(args.textgrid_dir)
    repair_jsonl = resolve_project_path(args.repair_jsonl)
    alignment_jsonl = resolve_project_path(args.alignment_jsonl)
    summary_json = resolve_project_path(args.summary_json)
    generated_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    noisy_records = load_jsonl(noisy_jsonl)
    textgrid_pairs = discover_textgrid_pairs(textgrid_dir)
    repair_records = load_optional_jsonl(repair_jsonl)
    alignment_records = build_alignment_records(
        noisy_records=noisy_records,
        textgrid_pairs=textgrid_pairs,
        repair_records=repair_records,
        noisy_jsonl=noisy_jsonl,
        textgrid_dir=textgrid_dir,
        repair_jsonl=repair_jsonl,
        generated_at_utc=generated_at_utc,
    )
    summary = build_summary(
        alignment_records=alignment_records,
        noisy_jsonl=noisy_jsonl,
        textgrid_dir=textgrid_dir,
        repair_jsonl=repair_jsonl,
        alignment_jsonl=alignment_jsonl,
        generated_at_utc=generated_at_utc,
    )

    write_jsonl(alignment_records, alignment_jsonl)
    write_json(summary, summary_json)

    print("T045 三文本样本对齐完成。")
    print(f"- alignment records: {len(alignment_records)}")
    print(
        "- clean TextGrid pairs: "
        f"{summary['counts']['clean_reference_textgrid_pair_available']}"
    )
    print(f"- doctor_llm_repair pending: {summary['counts']['doctor_llm_repair_pending']}")
    print(f"- alignment JSONL: {alignment_jsonl}")
    print(f"- summary JSON: {summary_json}")


if __name__ == "__main__":
    main()
