"""T040：评估 confirmed transcript 与轻量下游医学信息抽取效果。

该脚本比较三类输入：

- raw ASR transcript；
- T035 生成的 confirmed transcript；
- clean/reference transcript 作为 oracle 上限。

默认使用当前 PriMock57 小样本产物。若 confirmed transcript 来自 simulated
`accept_asr`，指标通常不会改善；这时结果只代表“评估链路已跑通”，不代表真实医生确认效果。
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
from clinical_asr_robustness.confirmed_downstream_evaluation import (  # noqa: E402
    run_confirmed_downstream_evaluation,
    write_json,
)

DEFAULT_ASR_INPUT_JSONL = Path(
    "outputs/primock57/t029_asr_nbest_candidates/"
    "primock57_asr_confidence_medical_entity_candidates.jsonl"
)
DEFAULT_CONFIRMED_INPUT_JSONL = Path(
    "outputs/primock57/t035_confirmed_transcripts/"
    "primock57_confirmed_transcripts.simulated_accept_asr.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("outputs/primock57/t040_confirmed_downstream_evaluation")
DEFAULT_ANNOTATIONS_NAME = "primock57_t040_confirmed_downstream_annotations.jsonl"
DEFAULT_SUMMARY_NAME = "primock57_t040_confirmed_downstream_summary.json"
DEFAULT_RUN_CONFIG_NAME = "t040_confirmed_downstream_evaluation_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asr-input-jsonl",
        type=Path,
        default=DEFAULT_ASR_INPUT_JSONL,
        help="ASR confidence JSONL，通常使用 T029 医学实体候选输出。",
    )
    parser.add_argument(
        "--confirmed-input-jsonl",
        type=Path,
        default=DEFAULT_CONFIRMED_INPUT_JSONL,
        help="T035 confirmed transcript JSONL。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="T040 输出目录；默认位于 outputs/ 下。",
    )
    parser.add_argument(
        "--annotations-name",
        default=DEFAULT_ANNOTATIONS_NAME,
        help="annotation JSONL 文件名。",
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help="聚合 summary JSON 文件名。",
    )
    parser.add_argument(
        "--run-config-name",
        default=DEFAULT_RUN_CONFIG_NAME,
        help="运行摘要 JSON 文件名。",
    )
    parser.add_argument(
        "--medical-terms",
        type=Path,
        default=None,
        help="可选医学术语文本文件，每行一个 term；会与内置轻量词表合并。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="可选，只评估前 N 条 record，便于快速调试。",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    annotations_path = output_dir / args.annotations_name
    summary_path = output_dir / args.summary_name
    return run_confirmed_downstream_evaluation(
        asr_input_jsonl=args.asr_input_jsonl,
        confirmed_input_jsonl=args.confirmed_input_jsonl,
        output_annotations_jsonl=annotations_path,
        output_summary_json=summary_path,
        project_root=PROJECT_ROOT,
        medical_terms_path=args.medical_terms,
        limit=args.limit,
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
        "task_id": "T040",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_input_jsonl": _path_for_record(
                resolve_project_path(args.asr_input_jsonl, PROJECT_ROOT),
            ),
            "confirmed_input_jsonl": _path_for_record(
                resolve_project_path(args.confirmed_input_jsonl, PROJECT_ROOT),
            ),
            "medical_terms": _path_for_record(
                resolve_project_path(args.medical_terms, PROJECT_ROOT),
            )
            if args.medical_terms is not None
            else None,
            "limit": args.limit,
        },
        "outputs": {
            "annotations_jsonl": _path_for_record(output_dir / args.annotations_name),
            "summary_json": _path_for_record(output_dir / args.summary_name),
            "run_config_json": _path_for_record(output_dir / args.run_config_name),
        },
        "validation": {
            "records_evaluated": summary.get("record_count", 0),
            "records_skipped": summary.get("records_skipped", 0),
            "summary_contains_full_reference_text": False,
            "annotation_contains_full_transcript_text": False,
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


def _format_metric(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


def main() -> None:
    args = parse_args()
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    run_config_path = output_dir / args.run_config_name
    try:
        summary = run(args)
        run_config = build_run_config(args, summary, status="ok")
        write_json(run_config, run_config_path)
        raw = summary["variant_metrics"]["raw_asr"]
        confirmed = summary["variant_metrics"]["confirmed_transcript"]
        deltas = summary["confirmed_vs_raw"]
        print("T040 confirmed transcript / 下游鲁棒性评估完成。")
        print(f"- records evaluated: {summary['record_count']}")
        print(
            "- WER raw → confirmed: "
            f"{_format_metric(raw['micro_wer'])} → {_format_metric(confirmed['micro_wer'])}"
        )
        print(
            "- MC-WER raw → confirmed: "
            f"{_format_metric(raw['micro_mc_wer'])} → "
            f"{_format_metric(confirmed['micro_mc_wer'])}"
        )
        print(
            "- concept F1 raw → confirmed: "
            f"{_format_metric(raw['downstream']['micro_f1'])} → "
            f"{_format_metric(confirmed['downstream']['micro_f1'])}"
        )
        print(
            "- mean WER improvement: "
            f"{_format_metric(deltas['mean_wer_improvement'])}"
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
        print("T040 confirmed transcript / 下游鲁棒性评估失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
