"""离线重算 T028 ASR confidence 的绿/黄/红等级与待审 span。

该脚本只改变阈值派生字段，不重跑 ASR，也不读取 clean/reference 正文。为避免
候选与新 span 边界错位，输入必须是尚未附加 ``asr_alternatives`` 的 T028 原始记录。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    DEFAULT_GREEN_MIN,
    DEFAULT_YELLOW_MIN,
    ASRConfidenceRecord,
    ConfidenceThresholds,
)
from clinical_asr_robustness.nemo_confidence_export import reclassify_confidence_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full.jsonl"
)
DEFAULT_OUTPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_full_three_level.jsonl"
)
DEFAULT_SUMMARY_JSON = (
    PROJECT_ROOT
    / "outputs/primock57/t028_nemo_asr_confidence/"
    "t028_confidence_threshold_reclassification_summary.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--green-min", type=float, default=DEFAULT_GREEN_MIN)
    parser.add_argument("--yellow-min", type=float, default=DEFAULT_YELLOW_MIN)
    return parser.parse_args()


def level_counts(record: ASRConfidenceRecord) -> Counter[str]:
    return Counter(word.confidence_level.value for word in record.asr_words)


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    thresholds = ConfidenceThresholds(
        green_min=args.green_min,
        yellow_min=args.yellow_min,
    )
    input_path = args.input_jsonl.resolve()
    output_path = args.output_jsonl.resolve()
    if input_path == output_path:
        raise ValueError("output-jsonl 不能覆盖 input-jsonl；请保留旧阈值实验产物")
    if not input_path.exists():
        raise FileNotFoundError(f"输入不存在：{input_path}")

    before_counts: Counter[str] = Counter()
    after_counts: Counter[str] = Counter()
    record_count = 0
    before_span_count = 0
    after_span_count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = ASRConfidenceRecord.model_validate_json(line)
                updated = reclassify_confidence_record(record, thresholds)
            except Exception as exc:  # noqa: BLE001 - 保留输入行号便于定位
                raise ValueError(f"第 {line_number} 行重分级失败：{input_path}") from exc
            before_counts.update(level_counts(record))
            after_counts.update(level_counts(updated))
            before_span_count += len(record.uncertain_spans)
            after_span_count += len(updated.uncertain_spans)
            target.write(json.dumps(updated.model_dump(mode="json"), ensure_ascii=False))
            target.write("\n")
            record_count += 1

    total_words = sum(after_counts.values())
    summary = {
        "task_id": "T047_CONFIDENCE_THRESHOLD_RECLASSIFICATION",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {"asr_confidence_jsonl": relative_path(input_path)},
        "outputs": {"asr_confidence_jsonl": relative_path(output_path)},
        "thresholds": thresholds.model_dump(mode="json"),
        "calibration_scope": "PriMock57 + NeMo native word_confidence research operating point",
        "clinical_calibration": False,
        "record_count": record_count,
        "word_count": total_words,
        "word_level_counts_before": dict(sorted(before_counts.items())),
        "word_level_counts_after": dict(sorted(after_counts.items())),
        "word_level_ratios_after": {
            level: round(count / total_words, 6) if total_words else None
            for level, count in sorted(after_counts.items())
        },
        "uncertain_span_count_before": before_span_count,
        "uncertain_span_count_after": after_span_count,
        "asr_rerun": False,
        "reference_text_read": False,
    }
    write_json(summary, args.summary_json.resolve())
    print("ASR confidence 三档阈值重分级完成。")
    print(f"- records: {record_count}")
    print(f"- words: {total_words}")
    print(f"- levels: {summary['word_level_counts_after']}")
    print(f"- output: {relative_path(output_path)}")


if __name__ == "__main__":
    main()
