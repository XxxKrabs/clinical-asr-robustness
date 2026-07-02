"""为 ASR confidence JSONL 追加 n-best/top-k 候选（T029）。

输入通常是 T028 生成的 ASR confidence JSONL；可额外提供 sequence-level
n-best JSONL。脚本会：

1. 把 n-best 保存为 `scope="sequence"` 的 `asr_alternatives`；
2. 将 sequence n-best 与 `uncertain_spans` 做词级 diff 对齐；
3. 为每个 uncertain span 生成 `scope="span"` 候选，并回写
   `uncertain_spans[].alternative_ids`。

本脚本不读取 reference 正文，也不把候选视为临床建议。
"""

from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    AlternativeScope,
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_nbest_candidates import (
    DEFAULT_NBEST_SOURCE,
    SEQUENCE_ALIGNMENT_METHOD,
    SPAN_ALIGNMENT_METHOD,
    attach_nbest_candidates_to_record,
    load_nbest_jsonl,
    nbest_items_for_record,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t029_asr_nbest_candidates"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_asr_confidence_with_candidates.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t029_asr_nbest_candidates_run.json"


def path_for_record(path: Path, project_root: Path = PROJECT_ROOT) -> str:
    """输出相对 project root 的 POSIX 风格路径；无法相对化时保留绝对路径。"""

    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path) -> Path:
    """将 CLI 中的相对路径解析到 project root。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument(
        "--nbest-jsonl",
        type=Path,
        default=None,
        help=(
            "sequence-level n-best JSONL；支持字段 nbest/alternatives/beams/hypotheses。"
            "若省略，则尝试复用输入 record 内已有 scope=sequence 候选。"
        ),
    )
    parser.add_argument("--default-source", default=DEFAULT_NBEST_SOURCE)
    parser.add_argument("--max-sequence-alternatives", type=int, default=5)
    parser.add_argument("--max-span-alternatives", type=int, default=3)
    parser.add_argument(
        "--include-unchanged-span-candidates",
        action="store_true",
        help="默认跳过与原 uncertain span 文本完全相同的 span 候选。",
    )
    return parser.parse_args()


def run_extraction(args: argparse.Namespace) -> tuple[list[ASRConfidenceRecord], dict[str, Any]]:
    """执行 T029 候选追加。"""

    input_jsonl = resolve_project_path(args.input_jsonl)
    output_jsonl = resolve_project_path(args.output_jsonl)
    nbest_jsonl = resolve_project_path(args.nbest_jsonl) if args.nbest_jsonl else None

    records = read_asr_confidence_jsonl(input_jsonl)
    nbest_by_key = (
        load_nbest_jsonl(nbest_jsonl, default_source=args.default_source)
        if nbest_jsonl is not None
        else {}
    )

    output_records: list[ASRConfidenceRecord] = []
    records_with_nbest_input = 0
    for record in records:
        nbest_items = nbest_items_for_record(record, nbest_by_key)
        if nbest_items:
            records_with_nbest_input += 1
        output_records.append(
            attach_nbest_candidates_to_record(
                record,
                nbest_items,
                max_sequence_alternatives=args.max_sequence_alternatives,
                max_span_alternatives=args.max_span_alternatives,
                default_source=args.default_source,
                include_unchanged_span_candidates=args.include_unchanged_span_candidates,
            )
        )

    write_asr_confidence_jsonl(output_records, output_jsonl)
    run_summary = build_run_summary(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        nbest_jsonl=nbest_jsonl,
        records=output_records,
        records_with_nbest_input=records_with_nbest_input,
        args=args,
    )
    return output_records, run_summary


def build_run_summary(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    nbest_jsonl: Path | None,
    records: list[ASRConfidenceRecord],
    records_with_nbest_input: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """构造 T029 运行摘要。"""

    sequence_alternative_count = sum(
        1
        for record in records
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    )
    span_alternative_count = sum(
        1
        for record in records
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.SPAN
    )
    spans_with_alternatives = sum(
        1
        for record in records
        for span in record.uncertain_spans
        if span.alternative_ids
    )
    total_uncertain_spans = sum(len(record.uncertain_spans) for record in records)
    records_with_sequence_alternatives = sum(
        any(
            alternative.scope == AlternativeScope.SEQUENCE
            for alternative in record.asr_alternatives
        )
        for record in records
    )
    records_with_span_alternatives = sum(
        any(alternative.scope == AlternativeScope.SPAN for alternative in record.asr_alternatives)
        for record in records
    )

    return {
        "task_id": "T029",
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_confidence_jsonl": path_for_record(input_jsonl),
            "nbest_jsonl": path_for_record(nbest_jsonl) if nbest_jsonl else None,
            "records_read": len(records),
            "records_with_external_nbest_input": records_with_nbest_input,
        },
        "outputs": {
            "asr_confidence_with_candidates_jsonl": path_for_record(output_jsonl),
        },
        "parameters": {
            "default_source": args.default_source,
            "max_sequence_alternatives": args.max_sequence_alternatives,
            "max_span_alternatives": args.max_span_alternatives,
            "include_unchanged_span_candidates": args.include_unchanged_span_candidates,
            "sequence_alignment_method": SEQUENCE_ALIGNMENT_METHOD,
            "span_alignment_method": SPAN_ALIGNMENT_METHOD,
        },
        "validation": {
            "sequence_alternatives": sequence_alternative_count,
            "span_alternatives": span_alternative_count,
            "total_uncertain_spans": total_uncertain_spans,
            "spans_with_alternatives": spans_with_alternatives,
            "records_with_sequence_alternatives": records_with_sequence_alternatives,
            "records_with_span_alternatives": records_with_span_alternatives,
            "no_inline_reference_text": all(
                not record.reference_text_included for record in records
            ),
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
        output_records, run_summary = run_extraction(args)
        write_run_config(run_summary, run_config_path)
        print("T029 ASR n-best/top-k 候选抽取完成。")
        print(f"- records: {len(output_records)}")
        print(f"- output_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T029",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T029 ASR n-best/top-k 候选抽取失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
