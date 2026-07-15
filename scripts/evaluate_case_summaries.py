"""T042c/T042d/T042e/T042f：评估病例摘要质量。

本脚本读取 T041/T042b 生成的病例摘要 records 和 T042a gold key facts：

- T042c：计算轻量 ROUGE-L 辅助指标；
- T042d：执行 source-aware factuality B-lite 事实级评估；
- T042e：统计高风险错误类型，并检查 uncertainty_notes 覆盖情况。
- T042f：可选回连 ASR 置信度、待审阅 span 和 confirmed feedback 成本收益。

默认输出不在聚合 summary 或 fact-level JSONL 中写入事实正文；如需人工复核
生成摘要事实，可显式加 ``--include-fact-text``，并确保输出文件仍按受控研究数据
处理。所有结果仅用于研究评估，不构成临床建议。
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.asr_quality_evaluation import resolve_project_path  # noqa: E402
from clinical_asr_robustness.case_summary_evaluation import (  # noqa: E402
    CASE_SUMMARY_RECORDS_DEFAULT_INPUT,
    DEFAULT_FACT_CONTRADICTION_THRESHOLD,
    DEFAULT_FACT_SUPPORT_THRESHOLD,
    GOLD_KEY_FACTS_DEFAULT_INPUT,
    GOLD_KEY_FACTS_DEFAULT_OUTPUT_DIR,
    run_case_summary_quality_evaluation,
    write_json,
)

DEFAULT_QUALITY_RECORDS_NAME = "primock57_t042_case_summary_quality_records.jsonl"
DEFAULT_FACT_EVALUATIONS_NAME = "primock57_t042_case_summary_fact_evaluations.jsonl"
DEFAULT_SUMMARY_NAME = "primock57_t042_case_summary_quality_summary.json"
DEFAULT_RUN_CONFIG_NAME = "t042_case_summary_quality_evaluation_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary-records-jsonl",
        type=Path,
        default=CASE_SUMMARY_RECORDS_DEFAULT_INPUT,
        help="T041/T042b 病例摘要 records JSONL。",
    )
    parser.add_argument(
        "--gold-key-facts-jsonl",
        type=Path,
        default=GOLD_KEY_FACTS_DEFAULT_INPUT,
        help="T042a gold_key_facts.jsonl。",
    )
    parser.add_argument(
        "--asr-confidence-jsonl",
        type=Path,
        default=None,
        help=(
            "可选：ASR confidence JSONL；提供后启用 T042f evidence→ASR "
            "confidence/review span 归因。"
        ),
    )
    parser.add_argument(
        "--confirmed-transcripts-jsonl",
        type=Path,
        default=None,
        help=(
            "可选：T035 confirmed transcript JSONL；提供后统计 review action、"
            "manual edit 和 changed span 成本。"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=GOLD_KEY_FACTS_DEFAULT_OUTPUT_DIR,
        help="T042c/T042d/T042e 输出目录。",
    )
    parser.add_argument(
        "--quality-records-name",
        default=DEFAULT_QUALITY_RECORDS_NAME,
        help="record-level 指标 JSONL 文件名。",
    )
    parser.add_argument(
        "--fact-evaluations-name",
        default=DEFAULT_FACT_EVALUATIONS_NAME,
        help="fact-level B-lite 标签 JSONL 文件名。",
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help="聚合 summary JSON 文件名。",
    )
    parser.add_argument(
        "--run-config-name",
        default=DEFAULT_RUN_CONFIG_NAME,
        help="运行记录 JSON 文件名。",
    )
    parser.add_argument(
        "--support-threshold",
        type=float,
        default=DEFAULT_FACT_SUPPORT_THRESHOLD,
        help="summary fact 与 gold fact 判为 supported 的匹配阈值。",
    )
    parser.add_argument(
        "--contradiction-threshold",
        type=float,
        default=DEFAULT_FACT_CONTRADICTION_THRESHOLD,
        help="存在极性冲突时判为 contradicted 的最低匹配阈值。",
    )
    parser.add_argument(
        "--include-fact-text",
        action="store_true",
        help=(
            "在 fact-level JSONL 中写入生成摘要事实短标签，便于人工复核；"
            "默认不写入事实正文。"
        ),
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    return run_case_summary_quality_evaluation(
        summary_records_jsonl=args.summary_records_jsonl,
        gold_key_facts_jsonl=args.gold_key_facts_jsonl,
        asr_confidence_jsonl=args.asr_confidence_jsonl,
        confirmed_transcripts_jsonl=args.confirmed_transcripts_jsonl,
        output_records_jsonl=output_dir / args.quality_records_name,
        output_fact_evaluations_jsonl=output_dir / args.fact_evaluations_name,
        output_summary_json=output_dir / args.summary_name,
        project_root=PROJECT_ROOT,
        support_threshold=args.support_threshold,
        contradiction_threshold=args.contradiction_threshold,
        include_fact_text=args.include_fact_text,
    )


def build_run_config(
    args: argparse.Namespace,
    summary: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    record: dict[str, Any] = {
        "task_id": "T042",
        "t042_subtasks": [
            "T042c_rouge_l_auxiliary",
            "T042d_source_aware_factuality_b_lite",
            "T042e_high_risk_error_and_uncertainty_notes",
            "T042f_asr_confidence_and_review_cost_attribution",
        ],
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "summary_records_jsonl": _path_for_record(
                resolve_project_path(args.summary_records_jsonl, PROJECT_ROOT)
            ),
            "gold_key_facts_jsonl": _path_for_record(
                resolve_project_path(args.gold_key_facts_jsonl, PROJECT_ROOT)
            ),
            "asr_confidence_jsonl": _path_for_record(
                resolve_project_path(args.asr_confidence_jsonl, PROJECT_ROOT)
                if args.asr_confidence_jsonl is not None
                else None
            ),
            "confirmed_transcripts_jsonl": _path_for_record(
                resolve_project_path(args.confirmed_transcripts_jsonl, PROJECT_ROOT)
                if args.confirmed_transcripts_jsonl is not None
                else None
            ),
        },
        "outputs": {
            "quality_records_jsonl": _path_for_record(
                output_dir / args.quality_records_name
            ),
            "fact_evaluations_jsonl": _path_for_record(
                output_dir / args.fact_evaluations_name
            ),
            "summary_json": _path_for_record(output_dir / args.summary_name),
            "run_config_json": _path_for_record(output_dir / args.run_config_name),
        },
        "parameters": {
            "support_threshold": args.support_threshold,
            "contradiction_threshold": args.contradiction_threshold,
            "include_fact_text": args.include_fact_text,
        },
        "validation": {
            "summary_records": summary.get("summary_record_count", 0),
            "evaluated_records": summary.get("evaluated_record_count", 0),
            "skipped_records": summary.get("skipped_record_count", 0),
            "summary_fact_count": summary.get("summary_fact_count", 0),
            "gold_fact_count": summary.get("gold_fact_count", 0),
            "summary_contains_fact_text": False,
            "summary_contains_full_transcript_text": False,
            "fact_evaluations_contain_fact_text": args.include_fact_text,
            "confidence_attribution_status_counts": (
                summary.get("confidence_attribution_summary", {}).get(
                    "evaluation_status_counts",
                    {},
                )
            ),
            "review_benefit_status": summary.get("review_benefit_summary", {}).get(
                "evaluation_status"
            ),
            "research_use_only": True,
        },
    }
    if error is not None:
        record["error"] = error
    if traceback_text is not None:
        record["traceback"] = traceback_text
    return record


def _path_for_record(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    run_config_path = output_dir / args.run_config_name
    try:
        summary = run(args)
        run_config = build_run_config(args, summary, status="ok")
        write_json(run_config, run_config_path)
        print("T042 病例摘要质量评估完成。")
        print(f"- summary records: {summary['summary_record_count']}")
        print(f"- evaluated records: {summary['evaluated_record_count']}")
        print(f"- skipped records: {summary['skipped_record_count']}")
        print(f"- summary facts: {summary['summary_fact_count']}")
        print(f"- gold facts: {summary['gold_fact_count']}")
        print(f"- fact F1 micro: {summary['fact_f1_micro']}")
        print(f"- rouge-L F1 macro: {summary['rouge_l_f1_macro']}")
        confidence_summary = summary.get("confidence_attribution_summary") or {}
        print(
            "- confidence attribution statuses: "
            f"{confidence_summary.get('evaluation_status_counts', {})}"
        )
        review_benefit = summary.get("review_benefit_summary") or {}
        print(
            "- review benefit paired consultations: "
            f"{review_benefit.get('paired_consultation_count', 0)}"
        )
        uncertainty_summary = summary.get("uncertainty_note_summary") or {}
        print(
            "- uncertainty notes required/missing: "
            f"{uncertainty_summary.get('required_record_count', 0)}/"
            f"{uncertainty_summary.get('missing_record_count', 0)}"
        )
        print(f"- summary: {output_dir / args.summary_name}")
    except Exception as exc:
        failed_summary: dict[str, Any] = {}
        run_config = build_run_config(
            args,
            failed_summary,
            status="failed",
            error=repr(exc),
            traceback_text=traceback.format_exc(),
        )
        write_json(run_config, run_config_path)
        print("T042 病例摘要质量评估失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
