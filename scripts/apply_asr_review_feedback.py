"""回放医生反馈并生成 confirmed transcript（T035）。

输入：

- ASR confidence JSONL（建议已包含 T029 span alternatives）；
- 医生/模拟审阅者反馈 JSONL（可由 T036 HTML 导出）。

输出：

- confirmed transcript JSONL；
- 运行摘要 JSON。

注意：`reject` 和 `unable_to_judge` 会暂保留 ASR 原文，但标记为 unresolved；
只有 `accept_asr`、`select_alternative`、`manual_edit` 会把对应 span 视为 resolved。
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl
from clinical_asr_robustness.review_workflow import (
    T035_GENERATED_BY,
    apply_feedback_to_records,
    read_feedback_entries_jsonl,
    write_confirmed_transcripts_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl"
)
DEFAULT_FEEDBACK_JSONL = (
    PROJECT_ROOT / "outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t035_confirmed_transcripts"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_confirmed_transcripts.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t035_confirmed_transcripts_run.json"


def path_for_record(path: Path | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--feedback-jsonl", type=Path, default=DEFAULT_FEEDBACK_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument(
        "--require-feedback-for-all-spans",
        action="store_true",
        help="若任一 uncertain span 没有反馈，则失败；默认保留 ASR 原文并标记 needs_review。",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_jsonl = resolve_project_path(args.input_jsonl)
    feedback_jsonl = resolve_project_path(args.feedback_jsonl)
    output_jsonl = resolve_project_path(args.output_jsonl)

    records = read_asr_confidence_jsonl(input_jsonl)
    feedback_entries = read_feedback_entries_jsonl(feedback_jsonl)
    confirmed_records = apply_feedback_to_records(
        records,
        feedback_entries,
        require_feedback_for_all_spans=args.require_feedback_for_all_spans,
    )
    write_confirmed_transcripts_jsonl(confirmed_records, output_jsonl)

    return build_run_summary(
        input_jsonl=input_jsonl,
        feedback_jsonl=feedback_jsonl,
        output_jsonl=output_jsonl,
        asr_record_count=len(records),
        feedback_entry_count=len(feedback_entries),
        confirmed_records=confirmed_records,
        require_feedback_for_all_spans=args.require_feedback_for_all_spans,
    )


def build_run_summary(
    *,
    input_jsonl: Path,
    feedback_jsonl: Path,
    output_jsonl: Path,
    asr_record_count: int,
    feedback_entry_count: int,
    confirmed_records: list[Any],
    require_feedback_for_all_spans: bool,
) -> dict[str, Any]:
    status_counter = Counter(record.confirmation_status.value for record in confirmed_records)
    action_counter: Counter[str] = Counter()
    for record in confirmed_records:
        action_counter.update(record.action_summary)
    return {
        "task_id": "T035",
        "status": "ok",
        "generated_by": T035_GENERATED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_confidence_jsonl": path_for_record(input_jsonl),
            "feedback_jsonl": path_for_record(feedback_jsonl),
            "asr_records_read": asr_record_count,
            "feedback_entries_read": feedback_entry_count,
        },
        "outputs": {
            "confirmed_transcripts_jsonl": path_for_record(output_jsonl),
        },
        "parameters": {
            "require_feedback_for_all_spans": require_feedback_for_all_spans,
        },
        "validation": {
            "confirmed_records": len(confirmed_records),
            "confirmation_status": dict(status_counter),
            "action_summary": dict(action_counter),
            "missing_feedback_spans": sum(
                len(record.missing_feedback_span_ids) for record in confirmed_records
            ),
            "unresolved_spans": sum(
                len(record.unresolved_span_ids) for record in confirmed_records
            ),
            "research_use_only": all(record.research_use_only for record in confirmed_records),
        },
    }


def write_run_config(record: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    run_config_path = resolve_project_path(args.run_config_json)
    try:
        summary = run(args)
        write_run_config(summary, run_config_path)
        print("T035 confirmed transcript 生成完成。")
        print(f"- confirmed_transcripts_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T035",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T035 confirmed transcript 生成失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
