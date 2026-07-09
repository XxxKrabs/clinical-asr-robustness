"""T031：评估 ASR noisy transcript、confidence 校准与 top-k 覆盖。

输入通常是 T029 之后的 ASR confidence JSONL（可包含 T038 医学实体 gating 和
n-best/top-k 候选）。脚本会读取每条 record 的 reference transcript 指针，
输出：

- `primock57_t031_asr_quality_annotations.jsonl`：含局部 edit span / candidate span；
- `primock57_t031_asr_quality_summary.json`：不含完整 transcript 正文的聚合摘要。

注意：annotation JSONL 包含局部 transcript span，仅用于本地研究评估；默认写入
`.gitignore` 已忽略的 `outputs/`。
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

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl  # noqa: E402
from clinical_asr_robustness.asr_quality_evaluation import (  # noqa: E402
    build_annotation_record,
    build_summary,
    load_medical_terms,
    read_reference_transcript,
    resolve_project_path,
    write_json,
    write_jsonl,
)

DEFAULT_INPUT_JSONL = Path(
    "outputs/primock57/t029_asr_nbest_candidates/"
    "primock57_asr_confidence_medical_entity_candidates.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("outputs/primock57/t031_asr_quality_evaluation")
DEFAULT_ANNOTATIONS_NAME = "primock57_t031_asr_quality_annotations.jsonl"
DEFAULT_SUMMARY_NAME = "primock57_t031_asr_quality_summary.json"
DEFAULT_RUN_CONFIG_NAME = "t031_asr_quality_evaluation_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=DEFAULT_INPUT_JSONL,
        help="ASR confidence JSONL，建议使用 T029 医学实体候选输出。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="T031 输出目录；默认位于 outputs/ 下。",
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


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    """执行 T031 评估并写出结果。"""

    input_jsonl = resolve_project_path(args.input_jsonl, PROJECT_ROOT)
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    annotations_path = output_dir / args.annotations_name
    summary_path = output_dir / args.summary_name
    run_config_path = output_dir / args.run_config_name
    medical_terms_path = (
        resolve_project_path(args.medical_terms, PROJECT_ROOT)
        if args.medical_terms is not None
        else None
    )

    records = read_asr_confidence_jsonl(input_jsonl)
    if args.limit is not None:
        records = records[: args.limit]
    medical_terms = load_medical_terms(medical_terms_path)

    annotation_records: list[dict[str, Any]] = []
    reference_missing_records: list[dict[str, Any]] = []
    for record in records:
        reference_pointer = record.reference_textgrid_path or record.reference_transcript_path
        if reference_pointer is None:
            reference_missing_records.append(
                {"sample_id": record.sample_id, "reason": "missing_reference_pointer"}
            )
            continue
        reference_path = resolve_project_path(reference_pointer, PROJECT_ROOT)
        if not reference_path.exists():
            reference_missing_records.append(
                {
                    "sample_id": record.sample_id,
                    "reference_path": str(reference_path),
                    "reason": "reference_file_not_found",
                }
            )
            continue

        reference_text = read_reference_transcript(reference_path)
        annotation = build_annotation_record(
            record,
            reference_text=reference_text,
            reference_path=reference_path,
            project_root=PROJECT_ROOT,
            medical_terms=medical_terms,
        )
        annotation["comparison"]["asr_confidence_source_file"] = _path_for_record(
            input_jsonl,
            PROJECT_ROOT,
        )
        annotation_records.append(annotation)

    write_jsonl(annotation_records, annotations_path)
    summary = build_summary(
        annotation_records=annotation_records,
        input_jsonl=input_jsonl,
        annotations_path=annotations_path,
        project_root=PROJECT_ROOT,
    )
    summary["records_skipped"] = len(reference_missing_records)
    summary["skipped_reference_records"] = reference_missing_records
    write_json(summary, summary_path)

    run_summary = {
        "task_id": "T031",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "input_jsonl": _path_for_record(input_jsonl, PROJECT_ROOT),
            "records_read": len(records),
            "records_evaluated": len(annotation_records),
            "medical_terms": _path_for_record(medical_terms_path, PROJECT_ROOT)
            if medical_terms_path is not None
            else None,
        },
        "outputs": {
            "annotations_jsonl": _path_for_record(annotations_path, PROJECT_ROOT),
            "summary_json": _path_for_record(summary_path, PROJECT_ROOT),
            "run_config_json": _path_for_record(run_config_path, PROJECT_ROOT),
        },
        "validation": {
            "reference_missing_records": reference_missing_records,
            "summary_contains_full_reference_text": False,
            "annotation_contains_local_error_spans": True,
        },
    }
    write_json(run_summary, run_config_path)
    return summary


def _path_for_record(path: Path | None, project_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    run_config_path = output_dir / args.run_config_name
    try:
        summary = run_evaluation(args)
        print("T031 ASR noisy / confidence / top-k 评估完成。")
        print(f"- records evaluated: {summary['record_count']}")
        print(f"- micro WER: {_format_metric(summary['micro_wer'])}")
        if summary["micro_mc_wer"] is not None:
            print(f"- micro MC-WER: {_format_metric(summary['micro_mc_wer'])}")
        calibration = summary["calibration"]
        if calibration["macro_ece"] is not None:
            print(f"- macro ECE: {_format_metric(calibration['macro_ece'])}")
        if calibration["macro_nce"] is not None:
            print(f"- macro NCE: {_format_metric(calibration['macro_nce'])}")
        span_topk = summary["topk"]["span_level"]
        print(
            "- span top-k exact coverage: "
            f"{span_topk['exact_reference_covered_spans']}/"
            f"{span_topk['total_uncertain_spans']}"
        )
        print(
            f"- summary: {resolve_project_path(args.output_dir, PROJECT_ROOT) / args.summary_name}"
        )
    except Exception as exc:
        failed_summary = {
            "task_id": "T031",
            "status": "failed",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(failed_summary, run_config_path)
        print("T031 ASR 质量评估失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


def _format_metric(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    main()
