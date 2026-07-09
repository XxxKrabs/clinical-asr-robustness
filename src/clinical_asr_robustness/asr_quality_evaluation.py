"""ASR noisy transcript 与 clean/reference 的质量评估。

本模块服务于 T031：在已有 ASR confidence / n-best / 医学实体审阅输出之上，
读取 reference transcript 指针，评估：

- noisy ASR 相对 reference 的 WER / MC-WER；
- ASR word confidence 的分桶错误率、ECE、NCE；
- 医学概念错误中有多少被医学实体 gating / uncertain span 覆盖；
- n-best / top-k 候选对 reference 的覆盖情况。

annotation 记录会包含局部 edit span 和 span 候选对照，默认应写入 `outputs/`；
summary 只包含聚合指标，避免把完整 reference transcript 写入报告。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    ASRAlternative,
    ASRConfidenceRecord,
    ConfidenceLevel,
)
from clinical_asr_robustness.error_analysis import (
    DEFAULT_MEDICAL_CONCEPT_TERMS,
    AlignmentOperation,
    AlignmentToken,
    AlignmentType,
    EditType,
    analyze_transcript_pair,
)

ASR_QUALITY_ANNOTATION_SCHEMA_VERSION = "asr_quality_evaluation_annotation/v1"
ASR_QUALITY_SUMMARY_SCHEMA_VERSION = "asr_quality_evaluation_summary/v1"
TEXTGRID_TEXT_PATTERN = re.compile(r"^\s*text\s*=\s*(?P<value>.*)\s*$")
TEXTGRID_TAG_PATTERN = re.compile(r"</?UNSURE>|<UNIN/>|<[^>]+>", flags=re.IGNORECASE)
SELECTED_ERROR_TYPES = [item.value for item in EditType]
SELECTED_METRICS = ["WER", "MC-WER", "ECE", "NCE", "top-k coverage"]


@dataclass(frozen=True)
class ASRWordCharSpan:
    """ASR word 在 `asr_transcript` 中的字符范围。"""

    word_index: int
    text: str
    start_char: int
    end_char: int
    confidence: float | None
    confidence_level: str
    is_medical_entity_review_word: bool
    in_uncertain_span: bool


@dataclass(frozen=True)
class TokenAssessment:
    """一个 hypothesis token 的正确性与置信度评估。"""

    hypothesis_token: AlignmentToken
    reference_tokens: tuple[AlignmentToken, ...]
    operation: AlignmentType
    word_index: int | None
    confidence: float | None
    confidence_level: str
    is_correct: bool
    is_medical_concept_hit: bool
    is_medical_entity_review_word: bool
    in_uncertain_span: bool


def clean_textgrid_utterance(text: str) -> str:
    """清理 TextGrid utterance 文本。

    `<UNSURE>...</UNSURE>` 中的内容会保留，`<UNIN/>` 这类不可辨识标记会移除。
    """

    without_tags = TEXTGRID_TAG_PATTERN.sub(" ", text)
    return " ".join(without_tags.split())


def unquote_textgrid_value(raw_value: str) -> str:
    """解析 Praat TextGrid `text = "..."` 的值。"""

    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.replace('""', '"')


def read_textgrid_transcript(path: str | Path) -> str:
    """从 TextGrid 文件中按出现顺序抽取非空 reference transcript。"""

    utterances: list[str] = []
    textgrid_path = Path(path)
    with textgrid_path.open("r", encoding="utf-8") as file:
        for line in file:
            match = TEXTGRID_TEXT_PATTERN.match(line)
            if match is None:
                continue
            cleaned = clean_textgrid_utterance(unquote_textgrid_value(match.group("value")))
            if cleaned:
                utterances.append(cleaned)
    return " ".join(utterances)


def read_reference_transcript(path: str | Path) -> str:
    """读取 reference transcript。

    当前优先支持 PriMock57 TextGrid；普通文本文件作为后备读取。
    """

    reference_path = Path(path)
    if reference_path.suffix.lower() == ".textgrid":
        return read_textgrid_transcript(reference_path)
    return " ".join(reference_path.read_text(encoding="utf-8").split())


def resolve_project_path(path_value: str | Path, project_root: Path) -> Path:
    """将记录中的相对路径解析到 project root。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return project_root / path


def path_for_record(path: Path, project_root: Path) -> str:
    """输出相对 project root 的 POSIX 风格路径。"""

    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


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


def word_char_spans_for_record(record: ASRConfidenceRecord) -> list[ASRWordCharSpan]:
    """返回 ASR words 在 transcript 中的字符范围，并附带审阅覆盖信息。"""

    uncertain_word_indices = {
        word_index
        for span in record.uncertain_spans
        for word_index in range(span.start_word_index, span.end_word_index)
    }
    transcript = record.asr_transcript
    transcript_folded = transcript.casefold()
    spans: list[ASRWordCharSpan] = []
    cursor = 0

    for word in record.asr_words:
        if word.char_start is not None and word.char_end is not None:
            start = word.char_start
            end = word.char_end
        else:
            needle = word.text.casefold()
            start = transcript_folded.find(needle, cursor)
            if start < 0:
                start = transcript_folded.find(needle)
            if start < 0:
                start = min(cursor, len(transcript))
            end = min(start + len(word.text), len(transcript))
        cursor = max(cursor, end)

        review_metadata = word.metadata.get("medical_entity_review", {})
        spans.append(
            ASRWordCharSpan(
                word_index=word.word_index,
                text=word.text,
                start_char=start,
                end_char=end,
                confidence=word.confidence,
                confidence_level=word.confidence_level.value,
                is_medical_entity_review_word=bool(
                    review_metadata.get("is_medical_entity")
                ),
                in_uncertain_span=word.word_index in uncertain_word_indices,
            )
        )
    return spans


def word_span_for_hypothesis_token(
    token: AlignmentToken,
    word_spans: list[ASRWordCharSpan],
) -> ASRWordCharSpan | None:
    """把 hypothesis token 映射回 ASR word。"""

    best_span: ASRWordCharSpan | None = None
    best_overlap = 0
    for word_span in word_spans:
        overlap = min(token.end_char, word_span.end_char) - max(
            token.start_char,
            word_span.start_char,
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_span = word_span
    if best_span is not None:
        return best_span

    for word_span in word_spans:
        if word_span.start_char <= token.start_char <= word_span.end_char:
            return word_span
    return None


def build_token_assessments(
    operations: Iterable[AlignmentOperation],
    word_spans: list[ASRWordCharSpan],
) -> list[TokenAssessment]:
    """把 token 对齐操作转换成可用于 confidence 校准的 hypothesis-token 评估。"""

    assessments: list[TokenAssessment] = []
    for operation in operations:
        if operation.operation == AlignmentType.DELETION:
            continue
        is_correct = operation.operation == AlignmentType.EQUAL
        is_medical_concept_hit = any(
            token.is_medical_concept
            for token in operation.reference_tokens + operation.hypothesis_tokens
        )
        for hypothesis_token in operation.hypothesis_tokens:
            word_span = word_span_for_hypothesis_token(hypothesis_token, word_spans)
            assessments.append(
                TokenAssessment(
                    hypothesis_token=hypothesis_token,
                    reference_tokens=operation.reference_tokens,
                    operation=operation.operation,
                    word_index=word_span.word_index if word_span is not None else None,
                    confidence=word_span.confidence if word_span is not None else None,
                    confidence_level=(
                        word_span.confidence_level
                        if word_span is not None
                        else ConfidenceLevel.UNKNOWN.value
                    ),
                    is_correct=is_correct,
                    is_medical_concept_hit=is_medical_concept_hit,
                    is_medical_entity_review_word=(
                        word_span.is_medical_entity_review_word
                        if word_span is not None
                        else False
                    ),
                    in_uncertain_span=word_span.in_uncertain_span
                    if word_span is not None
                    else False,
                )
            )
    return assessments


def summarize_confidence_by_level(
    assessments: Iterable[TokenAssessment],
) -> dict[str, dict[str, Any]]:
    """按 green/yellow/red/unknown 汇总 token 错误率。"""

    by_level: dict[str, list[TokenAssessment]] = defaultdict(list)
    for assessment in assessments:
        by_level[assessment.confidence_level].append(assessment)

    summary: dict[str, dict[str, Any]] = {}
    for level in (
        ConfidenceLevel.GREEN.value,
        ConfidenceLevel.YELLOW.value,
        ConfidenceLevel.RED.value,
        ConfidenceLevel.UNKNOWN.value,
    ):
        items = by_level.get(level, [])
        errors = [item for item in items if not item.is_correct]
        medical_items = [item for item in items if item.is_medical_concept_hit]
        medical_errors = [item for item in medical_items if not item.is_correct]
        confidence_values = [
            item.confidence for item in items if item.confidence is not None
        ]
        summary[level] = {
            "token_count": len(items),
            "error_count": len(errors),
            "accuracy": _safe_ratio(len(items) - len(errors), len(items)),
            "error_rate": _safe_ratio(len(errors), len(items)),
            "mean_confidence": _safe_mean(confidence_values),
            "medical_concept_token_count": len(medical_items),
            "medical_concept_error_count": len(medical_errors),
            "medical_concept_error_rate": _safe_ratio(
                len(medical_errors),
                len(medical_items),
            ),
        }
    return summary


def compute_calibration_metrics(
    assessments: Iterable[TokenAssessment],
    *,
    bin_count: int = 10,
) -> dict[str, Any]:
    """计算 confidence 作为“token 正确概率”时的 ECE / NCE / Brier。"""

    scored = [
        item
        for item in assessments
        if item.confidence is not None and 0.0 <= item.confidence <= 1.0
    ]
    if not scored:
        return {
            "scored_token_count": 0,
            "ece": None,
            "nce": None,
            "brier_score": None,
            "bins": [],
        }

    bins: list[dict[str, Any]] = []
    ece = 0.0
    total = len(scored)
    for bin_index in range(bin_count):
        lower = bin_index / bin_count
        upper = (bin_index + 1) / bin_count
        if bin_index == bin_count - 1:
            items = [
                item
                for item in scored
                if item.confidence is not None and lower <= item.confidence <= upper
            ]
        else:
            items = [
                item
                for item in scored
                if item.confidence is not None and lower <= item.confidence < upper
            ]
        if not items:
            bins.append(
                {
                    "bin_index": bin_index,
                    "lower": lower,
                    "upper": upper,
                    "token_count": 0,
                    "mean_confidence": None,
                    "accuracy": None,
                    "error_rate": None,
                    "ece_contribution": 0.0,
                }
            )
            continue
        confidence = mean(item.confidence for item in items if item.confidence is not None)
        accuracy = mean(1.0 if item.is_correct else 0.0 for item in items)
        contribution = (len(items) / total) * abs(accuracy - confidence)
        ece += contribution
        bins.append(
            {
                "bin_index": bin_index,
                "lower": lower,
                "upper": upper,
                "token_count": len(items),
                "mean_confidence": confidence,
                "accuracy": accuracy,
                "error_rate": 1.0 - accuracy,
                "ece_contribution": contribution,
            }
        )

    labels = [1.0 if item.is_correct else 0.0 for item in scored]
    probabilities = [float(item.confidence) for item in scored if item.confidence is not None]
    brier = mean(
        (probability - label) ** 2
        for probability, label in zip(probabilities, labels, strict=True)
    )
    model_cross_entropy = _binary_cross_entropy(labels, probabilities)
    prior_accuracy = mean(labels)
    prior_cross_entropy = _binary_cross_entropy(labels, [prior_accuracy] * len(labels))
    nce = (
        1.0 - model_cross_entropy / prior_cross_entropy
        if prior_cross_entropy and prior_cross_entropy > 0
        else None
    )

    return {
        "scored_token_count": total,
        "bin_count": bin_count,
        "ece": ece,
        "nce": nce,
        "brier_score": brier,
        "base_accuracy": prior_accuracy,
        "model_cross_entropy": model_cross_entropy,
        "prior_cross_entropy": prior_cross_entropy,
        "bins": bins,
    }


def summarize_medical_review_error_coverage(
    assessments: Iterable[TokenAssessment],
) -> dict[str, Any]:
    """统计医学概念错误是否被医学实体 gating 或 uncertain span 覆盖。"""

    medical_errors = [
        item for item in assessments if item.is_medical_concept_hit and not item.is_correct
    ]
    marked_medical_entity = [
        item for item in medical_errors if item.is_medical_entity_review_word
    ]
    in_uncertain_span = [item for item in medical_errors if item.in_uncertain_span]
    return {
        "medical_concept_error_token_count": len(medical_errors),
        "marked_medical_entity_error_token_count": len(marked_medical_entity),
        "uncertain_span_medical_error_token_count": len(in_uncertain_span),
        "marked_medical_entity_error_token_coverage": _safe_ratio(
            len(marked_medical_entity),
            len(medical_errors),
        ),
        "uncertain_span_medical_error_token_coverage": _safe_ratio(
            len(in_uncertain_span),
            len(medical_errors),
        ),
    }


def normalize_for_coverage(text: str) -> str:
    """候选覆盖判断用的轻量规整。"""

    return " ".join(
        match.group(0).casefold()
        for match in re.finditer(r"[A-Za-z]+(?:[-'][A-Za-z]+)*|\d+(?:[/-]\d+)*", text)
    )


def reference_text_for_span(
    span_start_word_index: int,
    span_end_word_index: int,
    operations: Iterable[AlignmentOperation],
    token_word_indices: dict[int, int | None],
) -> str:
    """根据 ASR span 的 word 范围回收其对齐到的 reference token 文本。"""

    reference_tokens: list[AlignmentToken] = []
    seen_reference_indices: set[int] = set()
    for operation in operations:
        hypothesis_indices = [
            token.index
            for token in operation.hypothesis_tokens
            if token_word_indices.get(token.index) is not None
            and span_start_word_index
            <= int(token_word_indices[token.index])
            < span_end_word_index
        ]
        if not hypothesis_indices:
            continue
        for reference_token in operation.reference_tokens:
            if reference_token.index in seen_reference_indices:
                continue
            seen_reference_indices.add(reference_token.index)
            reference_tokens.append(reference_token)
    return " ".join(token.text for token in reference_tokens)


def evaluate_span_topk_coverage(
    record: ASRConfidenceRecord,
    operations: Iterable[AlignmentOperation],
    assessments: Iterable[TokenAssessment],
    *,
    medical_terms: set[str],
) -> list[dict[str, Any]]:
    """评估 uncertain spans 的 span-level top-k 候选是否覆盖 reference。"""

    token_word_indices = {
        assessment.hypothesis_token.index: assessment.word_index
        for assessment in assessments
    }
    span_records: list[dict[str, Any]] = []
    for span in record.uncertain_spans:
        reference_span_text = reference_text_for_span(
            span.start_word_index,
            span.end_word_index,
            operations,
            token_word_indices,
        )
        span_alternatives = record.alternatives_for_span(span.span_id)
        ranked_candidates = [
            build_span_candidate_evaluation(
                alternative,
                reference_span_text,
                medical_terms=medical_terms,
            )
            for alternative in span_alternatives
        ]
        exact_matches = [
            item for item in ranked_candidates if item["exact_reference_match"]
        ]
        best_candidate_wer = _safe_min(
            [
                item["candidate_wer"]
                for item in ranked_candidates
                if item["candidate_wer"] is not None
            ]
        )
        span_records.append(
            {
                "span_id": span.span_id,
                "start_word_index": span.start_word_index,
                "end_word_index": span.end_word_index,
                "confidence_level": span.confidence_level.value,
                "mean_confidence": span.mean_confidence,
                "min_confidence": span.min_confidence,
                "asr_span_text": span.text,
                "reference_span_text": reference_span_text,
                "candidate_count": len(span_alternatives),
                "exact_reference_covered": bool(exact_matches),
                "best_candidate_wer": best_candidate_wer,
                "candidates": ranked_candidates,
            }
        )
    return span_records


def build_span_candidate_evaluation(
    alternative: ASRAlternative,
    reference_span_text: str,
    *,
    medical_terms: set[str],
) -> dict[str, Any]:
    """评估单个 span-level alternative。"""

    if reference_span_text:
        candidate_result = analyze_transcript_pair(
            reference_text=reference_span_text,
            hypothesis_text=alternative.text,
            medical_terms=medical_terms,
        )
        candidate_wer: float | None = candidate_result.wer
        candidate_mc_wer = candidate_result.mc_wer
    else:
        candidate_wer = None
        candidate_mc_wer = None

    return {
        "alternative_id": alternative.alternative_id,
        "rank": alternative.rank,
        "text": alternative.text,
        "score": alternative.score,
        "confidence": alternative.confidence,
        "source": alternative.source,
        "alignment_method": alternative.alignment_method,
        "candidate_type": alternative.metadata.get("candidate_type"),
        "generated_by": alternative.metadata.get("generated_by"),
        "asr_native_candidate": alternative.metadata.get(
            "asr_native_candidate",
            alternative.metadata.get("generated_by") != "T039",
        ),
        "candidate_wer": candidate_wer,
        "candidate_mc_wer": candidate_mc_wer,
        "exact_reference_match": bool(reference_span_text)
        and normalize_for_coverage(alternative.text)
        == normalize_for_coverage(reference_span_text),
    }


def evaluate_sequence_topk(
    record: ASRConfidenceRecord,
    reference_text: str,
    *,
    greedy_wer: float,
    greedy_mc_wer: float | None,
    medical_terms: set[str],
) -> dict[str, Any]:
    """评估 sequence-level n-best 候选相对 full reference 的 oracle 表现。"""

    sequence_alternatives = [
        alternative
        for alternative in record.asr_alternatives
        if alternative.scope.value == "sequence"
    ]
    candidate_records: list[dict[str, Any]] = []
    for alternative in sorted(sequence_alternatives, key=lambda item: item.rank):
        result = analyze_transcript_pair(
            reference_text=reference_text,
            hypothesis_text=alternative.text,
            medical_terms=medical_terms,
        )
        candidate_records.append(
            {
                "alternative_id": alternative.alternative_id,
                "rank": alternative.rank,
                "score": alternative.score,
                "confidence": alternative.confidence,
                "source": alternative.source,
                "wer": result.wer,
                "mc_wer": result.mc_wer,
                "improves_over_greedy_wer": result.wer < greedy_wer,
                "improves_over_greedy_mc_wer": (
                    result.mc_wer < greedy_mc_wer
                    if result.mc_wer is not None and greedy_mc_wer is not None
                    else None
                ),
            }
        )

    best_wer = _safe_min([item["wer"] for item in candidate_records])
    best_mc_wer = _safe_min(
        [item["mc_wer"] for item in candidate_records if item["mc_wer"] is not None]
    )
    return {
        "candidate_count": len(candidate_records),
        "best_sequence_wer": best_wer,
        "best_sequence_mc_wer": best_mc_wer,
        "oracle_wer_improvement": (
            greedy_wer - best_wer if best_wer is not None else None
        ),
        "oracle_mc_wer_improvement": (
            greedy_mc_wer - best_mc_wer
            if greedy_mc_wer is not None and best_mc_wer is not None
            else None
        ),
        "any_sequence_candidate_improves_wer": any(
            item["improves_over_greedy_wer"] for item in candidate_records
        ),
        "candidates": candidate_records,
    }


def build_annotation_record(
    record: ASRConfidenceRecord,
    *,
    reference_text: str,
    reference_path: Path,
    project_root: Path,
    medical_terms: set[str],
) -> dict[str, Any]:
    """对单条 ASR record 生成 T031 评估 annotation。"""

    result = analyze_transcript_pair(
        reference_text=reference_text,
        hypothesis_text=record.asr_transcript,
        medical_terms=medical_terms,
    )
    word_spans = word_char_spans_for_record(record)
    assessments = build_token_assessments(result.operations, word_spans)
    confidence_by_level = summarize_confidence_by_level(assessments)
    calibration = compute_calibration_metrics(assessments)
    medical_review_coverage = summarize_medical_review_error_coverage(assessments)
    span_topk = evaluate_span_topk_coverage(
        record,
        result.operations,
        assessments,
        medical_terms=medical_terms,
    )
    sequence_topk = evaluate_sequence_topk(
        record,
        reference_text,
        greedy_wer=result.wer,
        greedy_mc_wer=result.mc_wer,
        medical_terms=medical_terms,
    )

    sample_id = record.sample_id
    edit_spans = [
        span.to_public_dict(span_id=f"{sample_id}::edit:{index:04d}")
        for index, span in enumerate(result.edit_spans, start=1)
    ]

    return {
        "schema_version": ASR_QUALITY_ANNOTATION_SCHEMA_VERSION,
        "sample_id": record.sample_id,
        "record_id": record.record_id,
        "dataset": record.dataset,
        "split": record.split,
        "consultation_id": record.consultation_id,
        "source_channel": record.source_channel.value,
        "comparison": {
            "reference_source": path_for_record(reference_path, project_root),
            "hypothesis_variant": "asr_transcript",
            "asr_confidence_record_id": record.record_id,
            "asr_confidence_source_file": None,
            "reference_text_included": False,
        },
        "selected_error_types": SELECTED_ERROR_TYPES,
        "selected_metrics": SELECTED_METRICS,
        "metrics": result.metrics_dict(),
        "error_type_counts": result.error_type_counts,
        "edit_span_count": len(edit_spans),
        "medical_concept_edit_span_count": sum(
            1 for span in edit_spans if span["medical_concept_hit"]
        ),
        "confidence_by_level": confidence_by_level,
        "calibration": calibration,
        "medical_review_error_coverage": medical_review_coverage,
        "topk": {
            "span_level": summarize_span_topk(span_topk),
            "sequence_level": {
                key: value
                for key, value in sequence_topk.items()
                if key != "candidates"
            },
        },
        "edit_spans": edit_spans,
        "span_topk_records": span_topk,
        "sequence_topk_candidates": sequence_topk["candidates"],
        "research_use_only": True,
        "clinical_use_warning": record.clinical_use_warning,
        "notes": (
            "本记录由 reference/noisy token 自动对齐生成；局部 span 用于研究排错，"
            "关键结论仍需人工抽样复核。"
        ),
    }


def summarize_span_topk(span_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize span-level top-k coverage, including source-level diagnostics."""

    spans_with_candidates = [item for item in span_records if item["candidate_count"] > 0]
    exact_all = [item for item in span_records if item["exact_reference_covered"]]
    exact_with_candidates = [
        item for item in spans_with_candidates if item["exact_reference_covered"]
    ]
    best_wers = [
        item["best_candidate_wer"]
        for item in spans_with_candidates
        if item["best_candidate_wer"] is not None
    ]

    candidate_count_by_source: Counter[str] = Counter()
    spans_with_candidates_by_source: Counter[str] = Counter()
    exact_reference_covered_by_source: Counter[str] = Counter()
    for span_record in span_records:
        candidates = span_record.get("candidates", [])
        span_sources = {
            str(candidate.get("source") or "unknown") for candidate in candidates
        }
        exact_sources = {
            str(candidate.get("source") or "unknown")
            for candidate in candidates
            if candidate.get("exact_reference_match")
        }
        for candidate in candidates:
            candidate_count_by_source[str(candidate.get("source") or "unknown")] += 1
        for source in span_sources:
            spans_with_candidates_by_source[source] += 1
        for source in exact_sources:
            exact_reference_covered_by_source[source] += 1

    return {
        "total_uncertain_spans": len(span_records),
        "spans_with_candidates": len(spans_with_candidates),
        "exact_reference_covered_spans": len(exact_all),
        "exact_reference_coverage_over_all_spans": _safe_ratio(
            len(exact_all),
            len(span_records),
        ),
        "exact_reference_coverage_over_spans_with_candidates": _safe_ratio(
            len(exact_with_candidates),
            len(spans_with_candidates),
        ),
        "mean_best_candidate_wer": _safe_mean(best_wers),
        "candidate_count_by_source": dict(candidate_count_by_source),
        "spans_with_candidates_by_source": dict(spans_with_candidates_by_source),
        "exact_reference_covered_spans_by_source": dict(
            exact_reference_covered_by_source
        ),
        "exact_reference_coverage_over_all_spans_by_source": {
            source: _safe_ratio(count, len(span_records))
            for source, count in exact_reference_covered_by_source.items()
        },
        "exact_reference_coverage_over_spans_with_candidates_by_source": {
            source: _safe_ratio(count, spans_with_candidates_by_source[source])
            for source, count in exact_reference_covered_by_source.items()
        },
    }


def build_summary(
    annotation_records: list[dict[str, Any]],
    *,
    input_jsonl: Path,
    annotations_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    """生成不含 transcript 正文的聚合 summary。"""

    totals = Counter()
    error_counts = Counter()
    level_totals: dict[str, Counter[str]] = defaultdict(Counter)
    calibration_values: dict[str, list[float]] = defaultdict(list)
    macro_wer_values: list[float] = []
    macro_mc_wer_values: list[float] = []
    sequence_candidate_counts = 0
    sequence_improved_records = 0
    sequence_oracle_wer_improvements: list[float] = []
    span_topk_totals = Counter()
    span_topk_source_totals: dict[str, Counter[str]] = defaultdict(Counter)
    medical_review_totals = Counter()

    for record in annotation_records:
        metrics = record["metrics"]
        reference_token_count = metrics["reference_token_count"]
        error_count = (
            metrics["substitution_count"]
            + metrics["deletion_count"]
            + metrics["insertion_count"]
        )
        mc_reference_token_count = metrics["mc_reference_token_count"]
        mc_error_count = (
            metrics["mc_substitution_count"]
            + metrics["mc_deletion_count"]
            + metrics["mc_insertion_count"]
        )
        totals["records"] += 1
        totals["reference_token_count"] += reference_token_count
        totals["noisy_token_count"] += metrics["noisy_token_count"]
        totals["error_count"] += error_count
        totals["mc_reference_token_count"] += mc_reference_token_count
        totals["mc_error_count"] += mc_error_count
        totals["edit_span_count"] += record["edit_span_count"]
        totals["medical_concept_edit_span_count"] += record[
            "medical_concept_edit_span_count"
        ]
        macro_wer_values.append(metrics["wer"])
        if metrics["mc_wer"] is not None:
            macro_mc_wer_values.append(metrics["mc_wer"])
        for error_type, count in record["error_type_counts"].items():
            error_counts[error_type] += count

        for level, level_summary in record["confidence_by_level"].items():
            level_totals[level]["token_count"] += level_summary["token_count"]
            level_totals[level]["error_count"] += level_summary["error_count"]
            level_totals[level]["medical_concept_token_count"] += level_summary[
                "medical_concept_token_count"
            ]
            level_totals[level]["medical_concept_error_count"] += level_summary[
                "medical_concept_error_count"
            ]
            if level_summary["mean_confidence"] is not None:
                calibration_values[f"{level}:mean_confidence"].append(
                    level_summary["mean_confidence"]
                )

        calibration = record["calibration"]
        for key in ("ece", "nce", "brier_score"):
            if calibration.get(key) is not None:
                calibration_values[key].append(calibration[key])

        coverage = record["medical_review_error_coverage"]
        medical_review_totals["medical_concept_error_token_count"] += coverage[
            "medical_concept_error_token_count"
        ]
        medical_review_totals["marked_medical_entity_error_token_count"] += coverage[
            "marked_medical_entity_error_token_count"
        ]
        medical_review_totals["uncertain_span_medical_error_token_count"] += coverage[
            "uncertain_span_medical_error_token_count"
        ]

        span_level = record["topk"]["span_level"]
        for key in (
            "total_uncertain_spans",
            "spans_with_candidates",
            "exact_reference_covered_spans",
        ):
            span_topk_totals[key] += span_level[key]
        for source, count in span_level.get("candidate_count_by_source", {}).items():
            span_topk_source_totals[source]["candidate_count"] += count
        for source, count in span_level.get(
            "spans_with_candidates_by_source", {}
        ).items():
            span_topk_source_totals[source]["spans_with_candidates"] += count
        for source, count in span_level.get(
            "exact_reference_covered_spans_by_source", {}
        ).items():
            span_topk_source_totals[source]["exact_reference_covered_spans"] += count

        sequence_level = record["topk"]["sequence_level"]
        sequence_candidate_counts += sequence_level["candidate_count"]
        if sequence_level["any_sequence_candidate_improves_wer"]:
            sequence_improved_records += 1
        if sequence_level["oracle_wer_improvement"] is not None:
            sequence_oracle_wer_improvements.append(
                sequence_level["oracle_wer_improvement"]
            )

    confidence_by_level = {}
    for level in (
        ConfidenceLevel.GREEN.value,
        ConfidenceLevel.YELLOW.value,
        ConfidenceLevel.RED.value,
        ConfidenceLevel.UNKNOWN.value,
    ):
        level_counter = level_totals[level]
        token_count = level_counter["token_count"]
        error_count = level_counter["error_count"]
        medical_token_count = level_counter["medical_concept_token_count"]
        medical_error_count = level_counter["medical_concept_error_count"]
        confidence_by_level[level] = {
            "token_count": token_count,
            "error_count": error_count,
            "accuracy": _safe_ratio(token_count - error_count, token_count),
            "error_rate": _safe_ratio(error_count, token_count),
            "medical_concept_token_count": medical_token_count,
            "medical_concept_error_count": medical_error_count,
            "medical_concept_error_rate": _safe_ratio(
                medical_error_count,
                medical_token_count,
            ),
            "macro_mean_confidence": _safe_mean(
                calibration_values[f"{level}:mean_confidence"]
            ),
        }

    micro_wer = _safe_ratio(totals["error_count"], totals["reference_token_count"])
    micro_mc_wer = _safe_ratio(
        totals["mc_error_count"],
        totals["mc_reference_token_count"],
    )

    return {
        "schema_version": ASR_QUALITY_SUMMARY_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "dataset": "primock57",
        "task_id": "T031",
        "input_file": path_for_record(input_jsonl, project_root),
        "annotation_file": path_for_record(annotations_path, project_root),
        "selected_error_types": SELECTED_ERROR_TYPES,
        "selected_metrics": SELECTED_METRICS,
        "metric_definitions": {
            "WER": "(substitution + deletion + insertion) / reference_token_count",
            "MC-WER": (
                "medical/clinical concept WER；V0 使用内置医学/临床关键词、医学后缀、"
                "否定词和数字 token 标记 clinical concept token。"
            ),
            "ECE": (
                "按 token confidence 估计 correctness probability 的 "
                "expected calibration error。"
            ),
            "NCE": (
                "1 - model binary cross entropy / prior binary cross entropy；"
                "高于 0 表示 confidence 比只用总体正确率更有信息量。"
            ),
            "top-k coverage": "span-level 候选是否精确覆盖该 ASR span 对齐到的 reference span。",
        },
        "record_count": totals["records"],
        "reference_token_count": totals["reference_token_count"],
        "noisy_token_count": totals["noisy_token_count"],
        "edit_span_count": totals["edit_span_count"],
        "medical_concept_edit_span_count": totals["medical_concept_edit_span_count"],
        "error_type_counts": {
            error_type: error_counts[error_type] for error_type in SELECTED_ERROR_TYPES
        },
        "micro_wer": micro_wer,
        "macro_wer": _safe_mean(macro_wer_values),
        "micro_mc_wer": micro_mc_wer,
        "macro_mc_wer": _safe_mean(macro_mc_wer_values),
        "confidence_by_level": confidence_by_level,
        "calibration": {
            "macro_ece": _safe_mean(calibration_values["ece"]),
            "macro_nce": _safe_mean(calibration_values["nce"]),
            "macro_brier_score": _safe_mean(calibration_values["brier_score"]),
        },
        "medical_review_error_coverage": {
            "medical_concept_error_token_count": medical_review_totals[
                "medical_concept_error_token_count"
            ],
            "marked_medical_entity_error_token_count": medical_review_totals[
                "marked_medical_entity_error_token_count"
            ],
            "uncertain_span_medical_error_token_count": medical_review_totals[
                "uncertain_span_medical_error_token_count"
            ],
            "marked_medical_entity_error_token_coverage": _safe_ratio(
                medical_review_totals["marked_medical_entity_error_token_count"],
                medical_review_totals["medical_concept_error_token_count"],
            ),
            "uncertain_span_medical_error_token_coverage": _safe_ratio(
                medical_review_totals["uncertain_span_medical_error_token_count"],
                medical_review_totals["medical_concept_error_token_count"],
            ),
        },
        "topk": {
            "span_level": {
                "total_uncertain_spans": span_topk_totals["total_uncertain_spans"],
                "spans_with_candidates": span_topk_totals["spans_with_candidates"],
                "exact_reference_covered_spans": span_topk_totals[
                    "exact_reference_covered_spans"
                ],
                "exact_reference_coverage_over_all_spans": _safe_ratio(
                    span_topk_totals["exact_reference_covered_spans"],
                    span_topk_totals["total_uncertain_spans"],
                ),
                "exact_reference_coverage_over_spans_with_candidates": _safe_ratio(
                    span_topk_totals["exact_reference_covered_spans"],
                    span_topk_totals["spans_with_candidates"],
                ),
                "candidate_count_by_source": {
                    source: counts["candidate_count"]
                    for source, counts in sorted(span_topk_source_totals.items())
                },
                "spans_with_candidates_by_source": {
                    source: counts["spans_with_candidates"]
                    for source, counts in sorted(span_topk_source_totals.items())
                },
                "exact_reference_covered_spans_by_source": {
                    source: counts["exact_reference_covered_spans"]
                    for source, counts in sorted(span_topk_source_totals.items())
                },
                "exact_reference_coverage_over_all_spans_by_source": {
                    source: _safe_ratio(
                        counts["exact_reference_covered_spans"],
                        span_topk_totals["total_uncertain_spans"],
                    )
                    for source, counts in sorted(span_topk_source_totals.items())
                },
                "exact_reference_coverage_over_spans_with_candidates_by_source": {
                    source: _safe_ratio(
                        counts["exact_reference_covered_spans"],
                        counts["spans_with_candidates"],
                    )
                    for source, counts in sorted(span_topk_source_totals.items())
                },
            },
            "sequence_level": {
                "sequence_candidate_count": sequence_candidate_counts,
                "records_with_sequence_candidate_wer_improvement": sequence_improved_records,
                "mean_oracle_wer_improvement": _safe_mean(
                    sequence_oracle_wer_improvements
                ),
            },
        },
        "privacy_and_safety": {
            "summary_contains_full_reference_text": False,
            "annotation_contains_local_error_spans": True,
            "research_use_only": True,
        },
        "notes": (
            "summary 不含完整 transcript 正文；annotation JSONL 含局部错误 span 和候选 span，"
            "默认放在 outputs/ 下且不提交 Git。"
        ),
    }


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


def _binary_cross_entropy(labels: list[float], probabilities: list[float]) -> float:
    epsilon = 1e-12
    losses = []
    for label, probability in zip(labels, probabilities, strict=True):
        clipped = min(max(probability, epsilon), 1.0 - epsilon)
        losses.append(
            -(label * math.log(clipped) + (1.0 - label) * math.log(1.0 - clipped))
        )
    return mean(losses)


def _safe_mean(values: Iterable[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    return mean(numbers) if numbers else None


def _safe_min(values: Iterable[float]) -> float | None:
    numbers = list(values)
    return min(numbers) if numbers else None


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator
