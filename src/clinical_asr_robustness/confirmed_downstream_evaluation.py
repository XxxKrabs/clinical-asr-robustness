"""Confirmed transcript 与轻量下游医学信息抽取评估（T040）。

本模块回答 T040 的核心问题：医生/研究者确认后的 transcript 是否比 raw ASR
更接近 clean/reference，并且是否能改善一个可复现的下游病例信息整理代理任务。

V0 下游任务使用轻量医学/临床概念 token 抽取：

- 用 `error_analysis.tokenize_for_alignment()` 标记医学/临床关键 token；
- 把 reference 与 hypothesis 的医学概念 token 当作 multiset 比较；
- 输出 precision / recall / F1。

该指标不是最终医学实体归一化模型，但适合作为第一版闭环效果看板：无需联网、
可复跑、能直接比较 raw ASR / confirmed / reference oracle 三类输入。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_quality_evaluation import (
    path_for_record,
    read_reference_transcript,
    resolve_project_path,
)
from clinical_asr_robustness.error_analysis import (
    DEFAULT_MEDICAL_CONCEPT_TERMS,
    analyze_transcript_pair,
    tokenize_for_alignment,
)
from clinical_asr_robustness.review_workflow import (
    CLINICAL_USE_WARNING,
    CONFIRMED_TRANSCRIPT_SCHEMA_VERSION,
    ConfirmedTranscriptRecord,
)

CONFIRMED_DOWNSTREAM_ANNOTATION_SCHEMA_VERSION = (
    "confirmed_downstream_evaluation_annotation/v1"
)
CONFIRMED_DOWNSTREAM_SUMMARY_SCHEMA_VERSION = (
    "confirmed_downstream_evaluation_summary/v1"
)

VARIANT_RAW_ASR = "raw_asr"
VARIANT_CONFIRMED = "confirmed_transcript"
VARIANT_REFERENCE = "reference_oracle"


def read_confirmed_transcripts_jsonl(
    path: str | Path,
) -> list[ConfirmedTranscriptRecord]:
    """读取 T035 confirmed transcript JSONL。"""

    confirmed_path = Path(path)
    records: list[ConfirmedTranscriptRecord] = []
    with confirmed_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(ConfirmedTranscriptRecord.model_validate_json(stripped))
            except Exception as exc:  # noqa: BLE001 - 保留行号便于排错
                raise ValueError(
                    f"无法解析 confirmed transcript JSONL 第 {line_number} 行："
                    f"{confirmed_path}"
                ) from exc
    return records


def load_medical_terms(path: str | Path | None) -> set[str]:
    """读取可选医学术语表；默认使用项目内置轻量词表。"""

    terms = set(DEFAULT_MEDICAL_CONCEPT_TERMS)
    if path is None:
        return terms
    with Path(path).open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            terms.add(line.casefold())
    return terms


def build_confirmed_index(
    confirmed_records: Iterable[ConfirmedTranscriptRecord],
) -> dict[str, ConfirmedTranscriptRecord]:
    """按 record_id / sample_id 建立 confirmed transcript 查找表。"""

    index: dict[str, ConfirmedTranscriptRecord] = {}
    for record in confirmed_records:
        if record.record_id:
            index[record.record_id] = record
        index[record.sample_id] = record
    return index


def find_confirmed_for_asr_record(
    record: ASRConfidenceRecord,
    confirmed_index: dict[str, ConfirmedTranscriptRecord],
) -> ConfirmedTranscriptRecord | None:
    """优先按 record_id，再按 sample_id 匹配 confirmed transcript。"""

    if record.record_id and record.record_id in confirmed_index:
        return confirmed_index[record.record_id]
    return confirmed_index.get(record.sample_id)


def medical_concept_counter(text: str, medical_terms: set[str]) -> Counter[str]:
    """抽取医学/临床关键 token multiset。"""

    counter: Counter[str] = Counter()
    for token in tokenize_for_alignment(text, medical_terms=medical_terms):
        if token.is_medical_concept:
            counter[token.normalized] += 1
    return counter


def compare_concept_counters(
    reference_counter: Counter[str],
    hypothesis_counter: Counter[str],
) -> dict[str, Any]:
    """比较 reference/hypothesis 医学概念 token multiset。"""

    true_positive = sum(
        min(reference_counter[term], hypothesis_counter[term])
        for term in reference_counter.keys() | hypothesis_counter.keys()
    )
    false_positive = sum(
        max(hypothesis_counter[term] - reference_counter[term], 0)
        for term in hypothesis_counter
    )
    false_negative = sum(
        max(reference_counter[term] - hypothesis_counter[term], 0)
        for term in reference_counter
    )
    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    f1 = _f1(precision, recall)
    return {
        "task_name": "medical_concept_token_extraction_v0",
        "reference_concept_token_count": sum(reference_counter.values()),
        "hypothesis_concept_token_count": sum(hypothesis_counter.values()),
        "true_positive_count": true_positive,
        "false_positive_count": false_positive,
        "false_negative_count": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_transcript_variant(
    *,
    reference_text: str,
    hypothesis_text: str,
    medical_terms: set[str],
) -> dict[str, Any]:
    """评估一个 transcript variant 相对 reference 的 WER/MC-WER 与下游代理指标。"""

    result = analyze_transcript_pair(
        reference_text=reference_text,
        hypothesis_text=hypothesis_text,
        medical_terms=medical_terms,
    )
    reference_concepts = medical_concept_counter(reference_text, medical_terms)
    hypothesis_concepts = medical_concept_counter(hypothesis_text, medical_terms)
    downstream = compare_concept_counters(reference_concepts, hypothesis_concepts)
    return {
        "reference_token_count": result.reference_token_count,
        "hypothesis_token_count": result.hypothesis_token_count,
        "substitution_count": result.substitution_count,
        "deletion_count": result.deletion_count,
        "insertion_count": result.insertion_count,
        "error_count": result.error_count,
        "wer": result.wer,
        "mc_reference_token_count": result.mc_reference_token_count,
        "mc_substitution_count": result.mc_substitution_count,
        "mc_deletion_count": result.mc_deletion_count,
        "mc_insertion_count": result.mc_insertion_count,
        "mc_error_count": result.mc_error_count,
        "mc_wer": result.mc_wer,
        "downstream": downstream,
    }


def summarize_review_cost(
    asr_record: ASRConfidenceRecord,
    confirmed_record: ConfirmedTranscriptRecord,
) -> dict[str, Any]:
    """汇总单条 record 的审阅成本与确认动作。"""

    action_summary = Counter(confirmed_record.action_summary)
    changed_spans = [
        span
        for span in confirmed_record.applied_spans
        if span.confirmed_text.strip() != span.original_text.strip()
    ]
    resolved_spans = [span for span in confirmed_record.applied_spans if span.resolved]
    text_changed = (
        confirmed_record.confirmed_transcript.strip()
        != confirmed_record.asr_transcript.strip()
    )
    return {
        "review_span_count": len(asr_record.uncertain_spans),
        "applied_span_count": len(confirmed_record.applied_spans),
        "resolved_span_count": len(resolved_spans),
        "missing_feedback_span_count": len(confirmed_record.missing_feedback_span_ids),
        "unresolved_span_count": len(confirmed_record.unresolved_span_ids),
        "changed_span_count": len(changed_spans),
        "text_changed": text_changed,
        "action_summary": dict(action_summary),
        "confirmation_status": confirmed_record.confirmation_status.value,
    }


def build_annotation_record(
    asr_record: ASRConfidenceRecord,
    confirmed_record: ConfirmedTranscriptRecord,
    *,
    reference_text: str,
    reference_path: Path,
    project_root: Path,
    medical_terms: set[str],
) -> dict[str, Any]:
    """生成单条 T040 annotation；不写入完整 transcript 正文。"""

    raw_metrics = evaluate_transcript_variant(
        reference_text=reference_text,
        hypothesis_text=asr_record.asr_transcript,
        medical_terms=medical_terms,
    )
    confirmed_metrics = evaluate_transcript_variant(
        reference_text=reference_text,
        hypothesis_text=confirmed_record.confirmed_transcript,
        medical_terms=medical_terms,
    )
    reference_metrics = evaluate_transcript_variant(
        reference_text=reference_text,
        hypothesis_text=reference_text,
        medical_terms=medical_terms,
    )
    return {
        "schema_version": CONFIRMED_DOWNSTREAM_ANNOTATION_SCHEMA_VERSION,
        "sample_id": asr_record.sample_id,
        "record_id": asr_record.record_id,
        "dataset": asr_record.dataset,
        "split": asr_record.split,
        "consultation_id": asr_record.consultation_id,
        "source_channel": asr_record.source_channel.value,
        "comparison": {
            "reference_source": path_for_record(reference_path, project_root),
            "asr_confidence_record_id": asr_record.record_id,
            "confirmed_record_id": confirmed_record.record_id,
            "confirmed_schema_version": CONFIRMED_TRANSCRIPT_SCHEMA_VERSION,
            "reference_text_included": False,
            "transcript_text_included": False,
        },
        "review_cost": summarize_review_cost(asr_record, confirmed_record),
        "variants": {
            VARIANT_RAW_ASR: raw_metrics,
            VARIANT_CONFIRMED: confirmed_metrics,
            VARIANT_REFERENCE: reference_metrics,
        },
        "deltas": build_confirmed_vs_raw_deltas(raw_metrics, confirmed_metrics),
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
        "notes": (
            "T040 V0 使用 token 级 WER/MC-WER 与医学概念 token 抽取 F1 作为"
            " confirmed transcript 效果看板；annotation 不包含完整 transcript 正文。"
        ),
    }


def build_confirmed_vs_raw_deltas(
    raw_metrics: dict[str, Any],
    confirmed_metrics: dict[str, Any],
) -> dict[str, Any]:
    """计算 confirmed 相对 raw ASR 的变化；正数 improvement 表示更好。"""

    raw_downstream = raw_metrics["downstream"]
    confirmed_downstream = confirmed_metrics["downstream"]
    return {
        "wer_improvement": _difference(raw_metrics["wer"], confirmed_metrics["wer"]),
        "mc_wer_improvement": _difference(
            raw_metrics["mc_wer"],
            confirmed_metrics["mc_wer"],
        ),
        "medical_concept_f1_improvement": _difference(
            confirmed_downstream["f1"],
            raw_downstream["f1"],
        ),
        "medical_concept_recall_improvement": _difference(
            confirmed_downstream["recall"],
            raw_downstream["recall"],
        ),
        "medical_concept_precision_improvement": _difference(
            confirmed_downstream["precision"],
            raw_downstream["precision"],
        ),
        "error_count_reduction": raw_metrics["error_count"]
        - confirmed_metrics["error_count"],
        "mc_error_count_reduction": raw_metrics["mc_error_count"]
        - confirmed_metrics["mc_error_count"],
    }


def build_summary(
    annotation_records: list[dict[str, Any]],
    *,
    asr_input_jsonl: Path,
    confirmed_input_jsonl: Path,
    annotations_path: Path,
    project_root: Path,
    skipped_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成 T040 聚合 summary；不包含完整 transcript 正文。"""

    variant_totals = {
        variant: _aggregate_variant_metrics(annotation_records, variant)
        for variant in (VARIANT_RAW_ASR, VARIANT_CONFIRMED, VARIANT_REFERENCE)
    }
    review_cost = _aggregate_review_cost(annotation_records)
    deltas = _aggregate_deltas(annotation_records)
    return {
        "schema_version": CONFIRMED_DOWNSTREAM_SUMMARY_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "primock57",
        "task_id": "T040",
        "input_files": {
            "asr_confidence_jsonl": path_for_record(asr_input_jsonl, project_root),
            "confirmed_transcripts_jsonl": path_for_record(
                confirmed_input_jsonl,
                project_root,
            ),
        },
        "annotation_file": path_for_record(annotations_path, project_root),
        "record_count": len(annotation_records),
        "variant_metrics": variant_totals,
        "confirmed_vs_raw": deltas,
        "review_cost": review_cost,
        "metric_definitions": {
            "WER": "(substitution + deletion + insertion) / reference_token_count；越低越好。",
            "MC-WER": (
                "医学/临床关键 token 上的 WER；V0 使用内置轻量词表、医学后缀、"
                "否定词和数字 token。"
            ),
            "medical_concept_token_extraction_v0": (
                "把医学/临床关键 token 当作 multiset，从 hypothesis 中抽取后与 reference 比较，"
                "输出 precision / recall / F1；越高越好。"
            ),
            "confirmed_vs_raw.improvement": (
                "WER/MC-WER improvement = raw - confirmed；"
                "F1/precision/recall improvement = confirmed - raw。"
            ),
        },
        "privacy_and_safety": {
            "summary_contains_full_reference_text": False,
            "annotation_contains_full_transcript_text": False,
            "research_use_only": True,
        },
        "records_skipped": len(skipped_records or []),
        "skipped_records": skipped_records or [],
        "notes": (
            "T040 V0 是全流程效果看板：比较 raw ASR / confirmed transcript / reference oracle。"
            "若 confirmed 来自 simulated accept_asr，质量指标通常不会改善，只代表回放链路可运行。"
        ),
    }


def run_confirmed_downstream_evaluation(
    *,
    asr_input_jsonl: str | Path,
    confirmed_input_jsonl: str | Path,
    output_annotations_jsonl: str | Path,
    output_summary_json: str | Path,
    project_root: str | Path,
    medical_terms_path: str | Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """执行 T040 评估并写出 annotation / summary。"""

    root = Path(project_root)
    asr_path = resolve_project_path(asr_input_jsonl, root)
    confirmed_path = resolve_project_path(confirmed_input_jsonl, root)
    annotations_path = resolve_project_path(output_annotations_jsonl, root)
    summary_path = resolve_project_path(output_summary_json, root)
    terms_path = (
        resolve_project_path(medical_terms_path, root)
        if medical_terms_path is not None
        else None
    )

    asr_records = read_asr_confidence_jsonl(asr_path)
    if limit is not None:
        asr_records = asr_records[:limit]
    confirmed_records = read_confirmed_transcripts_jsonl(confirmed_path)
    confirmed_index = build_confirmed_index(confirmed_records)
    medical_terms = load_medical_terms(terms_path)

    annotations: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    for asr_record in asr_records:
        confirmed_record = find_confirmed_for_asr_record(asr_record, confirmed_index)
        if confirmed_record is None:
            skipped_records.append(
                {
                    "sample_id": asr_record.sample_id,
                    "record_id": asr_record.record_id,
                    "reason": "missing_confirmed_transcript",
                }
            )
            continue
        reference_pointer = (
            asr_record.reference_textgrid_path or asr_record.reference_transcript_path
        )
        if reference_pointer is None:
            skipped_records.append(
                {
                    "sample_id": asr_record.sample_id,
                    "record_id": asr_record.record_id,
                    "reason": "missing_reference_pointer",
                }
            )
            continue
        reference_path = resolve_project_path(reference_pointer, root)
        if not reference_path.exists():
            skipped_records.append(
                {
                    "sample_id": asr_record.sample_id,
                    "record_id": asr_record.record_id,
                    "reference_path": str(reference_path),
                    "reason": "reference_file_not_found",
                }
            )
            continue
        reference_text = read_reference_transcript(reference_path)
        annotations.append(
            build_annotation_record(
                asr_record,
                confirmed_record,
                reference_text=reference_text,
                reference_path=reference_path,
                project_root=root,
                medical_terms=medical_terms,
            )
        )

    write_jsonl(annotations, annotations_path)
    summary = build_summary(
        annotations,
        asr_input_jsonl=asr_path,
        confirmed_input_jsonl=confirmed_path,
        annotations_path=annotations_path,
        project_root=root,
        skipped_records=skipped_records,
    )
    write_json(summary, summary_path)
    return summary


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    """写入 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: str | Path) -> None:
    """写入 JSON。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _aggregate_variant_metrics(
    annotation_records: list[dict[str, Any]],
    variant: str,
) -> dict[str, Any]:
    totals = Counter()
    macro_wer_values: list[float] = []
    macro_mc_wer_values: list[float] = []
    macro_precision_values: list[float] = []
    macro_recall_values: list[float] = []
    macro_f1_values: list[float] = []

    for record in annotation_records:
        metrics = record["variants"][variant]
        downstream = metrics["downstream"]
        totals["reference_token_count"] += metrics["reference_token_count"]
        totals["hypothesis_token_count"] += metrics["hypothesis_token_count"]
        totals["substitution_count"] += metrics["substitution_count"]
        totals["deletion_count"] += metrics["deletion_count"]
        totals["insertion_count"] += metrics["insertion_count"]
        totals["error_count"] += metrics["error_count"]
        totals["mc_reference_token_count"] += metrics["mc_reference_token_count"]
        totals["mc_error_count"] += metrics["mc_error_count"]
        totals["reference_concept_token_count"] += downstream[
            "reference_concept_token_count"
        ]
        totals["hypothesis_concept_token_count"] += downstream[
            "hypothesis_concept_token_count"
        ]
        totals["true_positive_count"] += downstream["true_positive_count"]
        totals["false_positive_count"] += downstream["false_positive_count"]
        totals["false_negative_count"] += downstream["false_negative_count"]
        macro_wer_values.append(metrics["wer"])
        if metrics["mc_wer"] is not None:
            macro_mc_wer_values.append(metrics["mc_wer"])
        if downstream["precision"] is not None:
            macro_precision_values.append(downstream["precision"])
        if downstream["recall"] is not None:
            macro_recall_values.append(downstream["recall"])
        if downstream["f1"] is not None:
            macro_f1_values.append(downstream["f1"])

    micro_precision = _safe_ratio(
        totals["true_positive_count"],
        totals["true_positive_count"] + totals["false_positive_count"],
    )
    micro_recall = _safe_ratio(
        totals["true_positive_count"],
        totals["true_positive_count"] + totals["false_negative_count"],
    )
    return {
        "reference_token_count": totals["reference_token_count"],
        "hypothesis_token_count": totals["hypothesis_token_count"],
        "error_type_counts": {
            "substitution": totals["substitution_count"],
            "deletion": totals["deletion_count"],
            "insertion": totals["insertion_count"],
        },
        "error_count": totals["error_count"],
        "micro_wer": _safe_ratio(
            totals["error_count"],
            totals["reference_token_count"],
        ),
        "macro_wer": _safe_mean(macro_wer_values),
        "mc_reference_token_count": totals["mc_reference_token_count"],
        "mc_error_count": totals["mc_error_count"],
        "micro_mc_wer": _safe_ratio(
            totals["mc_error_count"],
            totals["mc_reference_token_count"],
        ),
        "macro_mc_wer": _safe_mean(macro_mc_wer_values),
        "downstream": {
            "task_name": "medical_concept_token_extraction_v0",
            "reference_concept_token_count": totals["reference_concept_token_count"],
            "hypothesis_concept_token_count": totals["hypothesis_concept_token_count"],
            "true_positive_count": totals["true_positive_count"],
            "false_positive_count": totals["false_positive_count"],
            "false_negative_count": totals["false_negative_count"],
            "micro_precision": micro_precision,
            "micro_recall": micro_recall,
            "micro_f1": _f1(micro_precision, micro_recall),
            "macro_precision": _safe_mean(macro_precision_values),
            "macro_recall": _safe_mean(macro_recall_values),
            "macro_f1": _safe_mean(macro_f1_values),
        },
    }


def _aggregate_review_cost(annotation_records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter()
    action_summary: Counter[str] = Counter()
    status_summary: Counter[str] = Counter()
    spans_per_record: list[int] = []
    records_with_text_changes = 0

    for record in annotation_records:
        cost = record["review_cost"]
        totals["review_span_count"] += cost["review_span_count"]
        totals["applied_span_count"] += cost["applied_span_count"]
        totals["resolved_span_count"] += cost["resolved_span_count"]
        totals["missing_feedback_span_count"] += cost["missing_feedback_span_count"]
        totals["unresolved_span_count"] += cost["unresolved_span_count"]
        totals["changed_span_count"] += cost["changed_span_count"]
        action_summary.update(cost["action_summary"])
        status_summary[cost["confirmation_status"]] += 1
        spans_per_record.append(cost["review_span_count"])
        if cost["text_changed"]:
            records_with_text_changes += 1

    return {
        "review_span_count": totals["review_span_count"],
        "applied_span_count": totals["applied_span_count"],
        "resolved_span_count": totals["resolved_span_count"],
        "missing_feedback_span_count": totals["missing_feedback_span_count"],
        "unresolved_span_count": totals["unresolved_span_count"],
        "changed_span_count": totals["changed_span_count"],
        "records_with_text_changes": records_with_text_changes,
        "action_summary": dict(action_summary),
        "confirmation_status": dict(status_summary),
        "mean_review_spans_per_record": _safe_mean(spans_per_record),
        "resolved_span_rate": _safe_ratio(
            totals["resolved_span_count"],
            totals["review_span_count"],
        ),
        "changed_span_rate": _safe_ratio(
            totals["changed_span_count"],
            totals["review_span_count"],
        ),
    }


def _aggregate_deltas(annotation_records: list[dict[str, Any]]) -> dict[str, Any]:
    wer_improvements: list[float] = []
    mc_wer_improvements: list[float] = []
    f1_improvements: list[float] = []
    recall_improvements: list[float] = []
    precision_improvements: list[float] = []
    error_reductions = 0
    mc_error_reductions = 0
    wer_direction = Counter()
    f1_direction = Counter()

    for record in annotation_records:
        deltas = record["deltas"]
        if deltas["wer_improvement"] is not None:
            value = deltas["wer_improvement"]
            wer_improvements.append(value)
            wer_direction[_direction(value)] += 1
        if deltas["mc_wer_improvement"] is not None:
            mc_wer_improvements.append(deltas["mc_wer_improvement"])
        if deltas["medical_concept_f1_improvement"] is not None:
            value = deltas["medical_concept_f1_improvement"]
            f1_improvements.append(value)
            f1_direction[_direction(value)] += 1
        if deltas["medical_concept_recall_improvement"] is not None:
            recall_improvements.append(deltas["medical_concept_recall_improvement"])
        if deltas["medical_concept_precision_improvement"] is not None:
            precision_improvements.append(
                deltas["medical_concept_precision_improvement"]
            )
        error_reductions += deltas["error_count_reduction"]
        mc_error_reductions += deltas["mc_error_count_reduction"]

    return {
        "mean_wer_improvement": _safe_mean(wer_improvements),
        "mean_mc_wer_improvement": _safe_mean(mc_wer_improvements),
        "mean_medical_concept_f1_improvement": _safe_mean(f1_improvements),
        "mean_medical_concept_recall_improvement": _safe_mean(recall_improvements),
        "mean_medical_concept_precision_improvement": _safe_mean(
            precision_improvements
        ),
        "total_error_count_reduction": error_reductions,
        "total_mc_error_count_reduction": mc_error_reductions,
        "records_by_wer_change": dict(wer_direction),
        "records_by_medical_concept_f1_change": dict(f1_direction),
    }


def _direction(value: float) -> str:
    if value > 1e-12:
        return "improved"
    if value < -1e-12:
        return "worse"
    return "unchanged"


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _safe_mean(values: Iterable[float | int | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return mean(numbers) if numbers else None


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
