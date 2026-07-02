"""T005：核验并标注 ACI-Bench noisy 来源与错误类型。

输入为 T015 生成的 `v0_note_generation_pairs.jsonl`。脚本不会改动源数据；
它会在输出目录生成：

- `aci_bench_t005_error_annotations.jsonl`：每条 pair 的 WER、MC-WER 和编辑 span。
- `aci_bench_t005_error_summary.json`：不含正文的聚合统计摘要。

注意：annotation JSONL 中包含局部 transcript span，仅用于本地研究实验，默认应放在
`.gitignore` 已忽略的 `outputs/` 下。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.error_analysis import (  # noqa: E402
    DEFAULT_MEDICAL_CONCEPT_TERMS,
    EditType,
    analyze_transcript_pair,
)

ANNOTATION_SCHEMA_VERSION = "aci_bench_t005_noisy_error_annotation/v1"
SUMMARY_SCHEMA_VERSION = "aci_bench_t005_noisy_error_summary/v1"
DEFAULT_PAIRS_JSONL = Path(
    "data/processed/aci_bench/v0_note_generation/v0_note_generation_pairs.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("outputs/aci_bench/t005_noisy_error_analysis")
DEFAULT_ANNOTATIONS_NAME = "aci_bench_t005_error_annotations.jsonl"
DEFAULT_SUMMARY_NAME = "aci_bench_t005_error_summary.json"
SELECTED_ERROR_TYPES = [item.value for item in EditType]
SELECTED_METRICS = ["WER", "MC-WER"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 为 dict 列表。"""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"无法解析 JSONL 第 {line_number} 行：{path}") from exc
    return records


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> None:
    """写入 JSONL。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def load_medical_terms(path: Path | None) -> set[str]:
    """读取可选医学术语表；默认使用内置轻量词表。"""

    terms = set(DEFAULT_MEDICAL_CONCEPT_TERMS)
    if path is None:
        return terms

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            terms.add(line.lower())
    return terms


def select_reference_and_noisy_variants(pair_record: dict[str, Any]) -> tuple[str, str]:
    """根据 paired track 选择 reference variant 与 noisy variant。"""

    variants = pair_record.get("variants", {})
    if "noisy" not in variants:
        raise KeyError(f"pair 缺少 noisy variant：{pair_record.get('sample_id')}")

    track = pair_record.get("track")
    if track == "noise_harm" and "clean" in variants:
        return "clean", "noisy"
    if track == "repair_gain" and "oracle_repaired" in variants:
        return "oracle_repaired", "noisy"

    # 兜底：优先选 clean，其次选 oracle_repaired，便于未来新切片复用。
    for candidate in ("clean", "oracle_repaired"):
        if candidate in variants:
            return candidate, "noisy"

    raise KeyError(f"pair 缺少可用 reference variant：{pair_record.get('sample_id')}")


def build_annotation_record(
    pair_record: dict[str, Any],
    medical_terms: set[str],
) -> dict[str, Any]:
    """对单条 ACI-Bench pair 生成 T005 错误标注记录。"""

    reference_role, noisy_role = select_reference_and_noisy_variants(pair_record)
    reference_variant = pair_record["variants"][reference_role]
    noisy_variant = pair_record["variants"][noisy_role]
    result = analyze_transcript_pair(
        reference_text=reference_variant["transcript"],
        hypothesis_text=noisy_variant["transcript"],
        medical_terms=medical_terms,
    )

    sample_id = pair_record["sample_id"]
    edit_spans = [
        span.to_public_dict(span_id=f"{sample_id}::edit:{index:04d}")
        for index, span in enumerate(result.edit_spans, start=1)
    ]

    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "sample_id": sample_id,
        "dataset": pair_record["dataset"],
        "source": pair_record["source"],
        "track": pair_record["track"],
        "split": pair_record["split"],
        "target_task": pair_record["target_task"],
        "comparison": {
            "reference_variant": reference_role,
            "reference_variant_name": reference_variant.get("variant_name"),
            "noisy_variant": noisy_role,
            "noisy_variant_name": noisy_variant.get("variant_name"),
            "reference_source_file": reference_variant.get("source_file"),
            "noisy_source_file": noisy_variant.get("source_file"),
            "record_id": noisy_variant.get("record_id"),
        },
        "selected_error_types": SELECTED_ERROR_TYPES,
        "selected_metrics": SELECTED_METRICS,
        "metrics": result.metrics_dict(),
        "error_type_counts": result.error_type_counts,
        "edit_span_count": len(edit_spans),
        "medical_concept_edit_span_count": sum(
            1 for span in edit_spans if span["medical_concept_hit"]
        ),
        "edit_spans": edit_spans,
        "research_use_only": True,
        "clinical_use_warning": pair_record.get(
            "clinical_use_warning",
            "本记录仅用于研究评估，不构成临床建议。",
        ),
        "notes": (
            "本记录由 token 级自动对齐生成，用于 T005 noisy 来源核验、错误类型统计"
            "和后续 repair candidate 定位；span 仍需在关键案例中人工复核。"
        ),
    }


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def build_summary(
    annotation_records: list[dict[str, Any]],
    pairs_jsonl: Path,
    annotations_path: Path,
) -> dict[str, Any]:
    """生成不含 transcript 正文的聚合统计。"""

    pair_counts_by_track: Counter[str] = Counter()
    pair_counts_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    error_counts_by_track: dict[str, Counter[str]] = defaultdict(Counter)
    medical_error_counts_by_track: dict[str, Counter[str]] = defaultdict(Counter)
    span_counts_by_track: Counter[str] = Counter()
    medical_span_counts_by_track: Counter[str] = Counter()
    metric_totals_by_track: dict[str, Counter[str]] = defaultdict(Counter)
    macro_wer_by_track: dict[str, list[float]] = defaultdict(list)
    macro_mc_wer_by_track: dict[str, list[float]] = defaultdict(list)

    total_reference_tokens = 0
    total_errors = 0
    total_mc_reference_tokens = 0
    total_mc_errors = 0
    macro_wer_values: list[float] = []
    macro_mc_wer_values: list[float] = []

    for record in annotation_records:
        track = record["track"]
        split = record["split"]
        metrics = record["metrics"]
        pair_counts_by_track[track] += 1
        pair_counts_by_split[track][split] += 1
        span_counts_by_track[track] += record["edit_span_count"]
        medical_span_counts_by_track[track] += record["medical_concept_edit_span_count"]

        for error_type, count in record["error_type_counts"].items():
            error_counts_by_track[track][error_type] += count

        medical_error_counts_by_track[track][EditType.SUBSTITUTION.value] += metrics[
            "mc_substitution_count"
        ]
        medical_error_counts_by_track[track][EditType.DELETION.value] += metrics[
            "mc_deletion_count"
        ]
        medical_error_counts_by_track[track][EditType.INSERTION.value] += metrics[
            "mc_insertion_count"
        ]

        reference_tokens = metrics["reference_token_count"]
        errors = (
            metrics["substitution_count"] + metrics["deletion_count"] + metrics["insertion_count"]
        )
        mc_reference_tokens = metrics["mc_reference_token_count"]
        mc_errors = (
            metrics["mc_substitution_count"]
            + metrics["mc_deletion_count"]
            + metrics["mc_insertion_count"]
        )

        metric_totals_by_track[track]["reference_token_count"] += reference_tokens
        metric_totals_by_track[track]["error_count"] += errors
        metric_totals_by_track[track]["mc_reference_token_count"] += mc_reference_tokens
        metric_totals_by_track[track]["mc_error_count"] += mc_errors

        total_reference_tokens += reference_tokens
        total_errors += errors
        total_mc_reference_tokens += mc_reference_tokens
        total_mc_errors += mc_errors

        macro_wer_values.append(metrics["wer"])
        macro_wer_by_track[track].append(metrics["wer"])
        if metrics["mc_wer"] is not None:
            macro_mc_wer_values.append(metrics["mc_wer"])
            macro_mc_wer_by_track[track].append(metrics["mc_wer"])

    micro_wer = total_errors / total_reference_tokens if total_reference_tokens else None
    micro_mc_wer = (
        total_mc_errors / total_mc_reference_tokens if total_mc_reference_tokens else None
    )

    aggregate_by_track: dict[str, dict[str, Any]] = {}
    for track, totals in metric_totals_by_track.items():
        reference_tokens = totals["reference_token_count"]
        mc_reference_tokens = totals["mc_reference_token_count"]
        aggregate_by_track[track] = {
            "pair_records": pair_counts_by_track[track],
            "edit_span_count": span_counts_by_track[track],
            "medical_concept_edit_span_count": medical_span_counts_by_track[track],
            "error_type_counts": dict(error_counts_by_track[track]),
            "medical_concept_error_type_counts": dict(medical_error_counts_by_track[track]),
            "micro_wer": totals["error_count"] / reference_tokens if reference_tokens else None,
            "macro_wer": _safe_mean(macro_wer_by_track[track]),
            "micro_mc_wer": (
                totals["mc_error_count"] / mc_reference_tokens if mc_reference_tokens else None
            ),
            "macro_mc_wer": _safe_mean(macro_mc_wer_by_track[track]),
            "reference_token_count": reference_tokens,
            "mc_reference_token_count": mc_reference_tokens,
        }

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "dataset": "aci_bench",
        "task_id": "T005",
        "input_file": str(pairs_jsonl),
        "annotation_file": str(annotations_path),
        "selected_error_types": SELECTED_ERROR_TYPES,
        "selected_metrics": SELECTED_METRICS,
        "metric_definitions": {
            "WER": "(substitution + deletion + insertion) / reference_token_count",
            "MC-WER": (
                "medical/clinical concept WER；V0 使用内置医学/临床关键词、医学后缀、"
                "否定词和数字 token 标记 clinical concept token。"
            ),
        },
        "pair_records": len(annotation_records),
        "pair_counts_by_track": dict(pair_counts_by_track),
        "pair_counts_by_split": {
            track: dict(counter) for track, counter in pair_counts_by_split.items()
        },
        "edit_span_count": sum(span_counts_by_track.values()),
        "medical_concept_edit_span_count": sum(medical_span_counts_by_track.values()),
        "error_type_counts": {
            error_type: sum(counter[error_type] for counter in error_counts_by_track.values())
            for error_type in SELECTED_ERROR_TYPES
        },
        "medical_concept_error_type_counts": {
            error_type: sum(
                counter[error_type] for counter in medical_error_counts_by_track.values()
            )
            for error_type in SELECTED_ERROR_TYPES
        },
        "micro_wer": micro_wer,
        "macro_wer": _safe_mean(macro_wer_values),
        "micro_mc_wer": micro_mc_wer,
        "macro_mc_wer": _safe_mean(macro_mc_wer_values),
        "aggregate_by_track": aggregate_by_track,
        "research_use_only": True,
        "notes": (
            "summary 不含 transcript 正文；annotation JSONL 含局部错误 span，默认不提交 Git。"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs-jsonl",
        type=Path,
        default=DEFAULT_PAIRS_JSONL,
        help="T015 生成的 paired JSONL，默认使用 ACI-Bench V0 note generation pairs。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="T005 输出目录；默认位于 outputs/ 下，避免提交病例片段。",
    )
    parser.add_argument(
        "--annotations-name",
        default=DEFAULT_ANNOTATIONS_NAME,
        help="错误标注 JSONL 文件名。",
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help="聚合摘要 JSON 文件名。",
    )
    parser.add_argument(
        "--medical-terms",
        type=Path,
        default=None,
        help="可选医学术语文本文件，每行一个 term；会与内置轻量词表合并。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pair_records = read_jsonl(args.pairs_jsonl)
    medical_terms = load_medical_terms(args.medical_terms)
    annotation_records = [
        build_annotation_record(pair_record, medical_terms=medical_terms)
        for pair_record in pair_records
    ]

    annotations_path = args.output_dir / args.annotations_name
    summary_path = args.output_dir / args.summary_name
    write_jsonl(annotation_records, annotations_path)
    summary = build_summary(
        annotation_records=annotation_records,
        pairs_jsonl=args.pairs_jsonl,
        annotations_path=annotations_path,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("T005 ACI-Bench noisy 错误标注完成。")
    print(f"- pair records: {summary['pair_records']}")
    print(f"- error types: {', '.join(summary['selected_error_types'])}")
    print(f"- metrics: {', '.join(summary['selected_metrics'])}")
    print(f"- micro WER: {summary['micro_wer']:.4f}")
    if summary["micro_mc_wer"] is not None:
        print(f"- micro MC-WER: {summary['micro_mc_wer']:.4f}")
    print(f"- annotations: {annotations_path}")
    print(f"- summary: {summary_path}")


if __name__ == "__main__":
    main()
