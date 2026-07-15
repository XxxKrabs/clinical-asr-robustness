"""生成明确标记为自动工程 QA 的审阅反馈夹具。

该脚本只用于验证 T036 HTML 导出格式与 T035 确定性反馈回放链路。它默认对所选病例的
全部待审 span 执行 ``accept_asr``，不代表医生听音、人工确认或临床判断，也不能用于质量
提升结论。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
)
from clinical_asr_robustness.review_workflow import (
    DoctorFeedbackEntry,
    ReviewFeedbackAction,
    write_feedback_entries_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--run-summary-json", type=Path, required=True)
    parser.add_argument(
        "--consultation-id",
        action="append",
        dest="consultation_ids",
        required=True,
        help="可重复传入；只为指定匿名病例生成 QA 反馈。",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def record_consultation_id(record: ASRConfidenceRecord) -> str | None:
    if record.consultation_id:
        return record.consultation_id
    metadata_id = record.metadata.get("consultation_id")
    if metadata_id:
        return str(metadata_id)
    parts = record.sample_id.split(":")
    return parts[1] if len(parts) >= 2 and parts[1].startswith("case_") else None


def build_qa_feedback(
    records: list[ASRConfidenceRecord],
    consultation_ids: set[str],
) -> tuple[list[DoctorFeedbackEntry], Counter[str]]:
    """为所选病例的全部 uncertain span 建立 accept-ASR 工程夹具。"""

    entries: list[DoctorFeedbackEntry] = []
    selected_records: Counter[str] = Counter()
    generated_at = datetime.now(timezone.utc)
    for record in records:
        consultation_id = record_consultation_id(record)
        if consultation_id not in consultation_ids:
            continue
        selected_records[consultation_id] += 1
        for span in record.uncertain_spans:
            entries.append(
                DoctorFeedbackEntry(
                    feedback_id=f"automated_qa::{record.record_id}::{span.span_id}",
                    record_id=record.record_id,
                    sample_id=record.sample_id,
                    span_id=span.span_id,
                    action=ReviewFeedbackAction.ACCEPT_ASR,
                    original_text=span.text,
                    reviewer_id="automated_engineering_qa",
                    reviewer_role="automated_engineering_qa_not_human",
                    created_at_utc=generated_at,
                    source="build_review_feedback_qa_fixture/v1",
                    note="自动 accept_asr，仅验证反馈导出与回放，不代表听音或人工确认。",
                    metadata={
                        "consultation_id": consultation_id,
                        "automated_fixture": True,
                        "human_reviewed": False,
                        "doctor_confirmed": False,
                    },
                )
            )
    return entries, selected_records


def main() -> None:
    args = parse_args()
    input_path = resolve_project_path(args.input_jsonl)
    output_path = resolve_project_path(args.output_jsonl)
    run_path = resolve_project_path(args.run_summary_json)
    consultation_ids = set(args.consultation_ids)
    records = read_asr_confidence_jsonl(input_path)
    entries, selected_records = build_qa_feedback(records, consultation_ids)
    missing_cases = sorted(consultation_ids - set(selected_records))
    if missing_cases:
        raise ValueError(f"输入中缺少指定病例：{missing_cases}")
    if not entries:
        raise ValueError("所选病例没有 uncertain span，无法验证反馈回放")
    write_feedback_entries_jsonl(entries, output_path)
    action_counts = Counter(entry.action.value for entry in entries)
    summary = {
        "task_id": "T060_T035_AUTOMATED_QA_FIXTURE",
        "schema_version": "review_feedback_qa_fixture_run/v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {"asr_jsonl": project_relative(input_path)},
        "outputs": {"feedback_jsonl": project_relative(output_path)},
        "selected_consultation_ids": sorted(consultation_ids),
        "selected_record_counts": dict(sorted(selected_records.items())),
        "feedback_entry_count": len(entries),
        "action_counts": dict(sorted(action_counts.items())),
        "automated_fixture": True,
        "human_reviewed": False,
        "doctor_confirmed": False,
        "formal_quality_claim_allowed": False,
        "research_use_only": True,
        "note": "自动 accept_asr 夹具只验证反馈 schema 与 T035 回放，不代表医生确认。",
    }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
