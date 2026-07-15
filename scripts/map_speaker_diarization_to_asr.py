from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from clinical_asr_robustness.asr_confidence import (
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.speaker_diarization import (
    map_diarization_to_asr_records,
    read_speaker_diarization_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把独立 speaker diarization 结果按时间重叠映射到 ASR words。"
    )
    parser.add_argument("--asr-jsonl", type=Path, required=True)
    parser.add_argument("--diarization-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--run-summary-json", type=Path, default=None)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.10)
    parser.add_argument("--ambiguity-ratio", type=float, default=0.90)
    parser.add_argument("--max-same-speaker-bridge-gap-sec", type=float, default=1.5)
    parser.add_argument("--disable-same-speaker-gap-bridge", action="store_true")
    parser.add_argument("--overwrite-existing-speaker-labels", action="store_true")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def run() -> dict[str, object]:
    args = parse_args()
    asr_path = resolve_project_path(args.asr_jsonl)
    diarization_path = resolve_project_path(args.diarization_jsonl)
    output_path = resolve_project_path(args.output_jsonl)
    asr_records = read_asr_confidence_jsonl(asr_path)
    diarization_records = read_speaker_diarization_jsonl(diarization_path)
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
    write_asr_confidence_jsonl(mapped_records, output_path)

    status_counts: Counter[str] = Counter()
    speaker_counts: Counter[str] = Counter()
    acoustic_speaker_counts: Counter[str] = Counter()
    smoothing_status_counts: Counter[str] = Counter()
    total_word_count = 0
    for record in mapped_records:
        total_word_count += len(record.asr_words)
        for word in record.asr_words:
            evidence = word.metadata.get("diarization")
            if isinstance(evidence, dict):
                status_counts[str(evidence.get("mapping_status") or "unknown")] += 1
                acoustic_label = str(evidence.get("speaker_label") or "").strip()
                if acoustic_label:
                    acoustic_speaker_counts[acoustic_label] += 1
                smoothing_status = str(evidence.get("smoothing_status") or "").strip()
                if smoothing_status:
                    smoothing_status_counts[smoothing_status] += 1
            if word.speaker_label:
                speaker_counts[word.speaker_label] += 1
    acoustic_mapped_word_count = sum(acoustic_speaker_counts.values())
    resolved_word_count = sum(speaker_counts.values())
    summary: dict[str, object] = {
        "task_id": "T070",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asr_jsonl": project_relative(asr_path),
        "diarization_jsonl": project_relative(diarization_path),
        "output_jsonl": project_relative(output_path),
        "record_count": len(mapped_records),
        "total_word_count": total_word_count,
        "mapped_word_count": acoustic_mapped_word_count,
        "mapping_coverage": (
            acoustic_mapped_word_count / total_word_count if total_word_count else 0.0
        ),
        "acoustic_mapped_word_count": acoustic_mapped_word_count,
        "acoustic_mapping_coverage": (
            acoustic_mapped_word_count / total_word_count if total_word_count else 0.0
        ),
        "resolved_word_count": resolved_word_count,
        "resolved_coverage": (
            resolved_word_count / total_word_count if total_word_count else 0.0
        ),
        "smoothed_word_count": sum(smoothing_status_counts.values()),
        "mapping_status_counts": dict(sorted(status_counts.items())),
        "smoothing_status_counts": dict(sorted(smoothing_status_counts.items())),
        "speaker_word_counts": dict(sorted(acoustic_speaker_counts.items())),
        "acoustic_speaker_word_counts": dict(sorted(acoustic_speaker_counts.items())),
        "resolved_speaker_word_counts": dict(sorted(speaker_counts.items())),
        "min_overlap_ratio": args.min_overlap_ratio,
        "ambiguity_ratio": args.ambiguity_ratio,
        "same_speaker_gap_bridge_enabled": (
            not args.disable_same_speaker_gap_bridge
        ),
        "max_same_speaker_bridge_gap_sec": args.max_same_speaker_bridge_gap_sec,
        "ambiguous_overlap_bridged": False,
        "acoustic_speaker_only": True,
        "speaker_roles_assigned": False,
        "reference_used": False,
    }
    if args.run_summary_json:
        summary_path = resolve_project_path(args.run_summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
