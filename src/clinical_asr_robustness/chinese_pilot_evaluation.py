"""中文 ASR pilot 的代理参考与鲁棒性指标。

这些指标只服务于没有人工 reference 时的探索性评估。正式质量结论仍需人工听写、
医生确认和独立 gold facts。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any

from clinical_asr_robustness.asr_confidence import ASRConfidenceRecord

MIXED_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:[-+][A-Za-z0-9]+)*|\d+(?:\.\d+)?|[\u3400-\u9fff]")
PARAMETER_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:v|mv|ma|ua|hz|khz|us|ms|%|伏|毫伏|毫安|微安|赫兹|微秒|毫秒|欧姆)",
    flags=re.IGNORECASE,
)
LATERALITY_TERMS = ("左侧", "右侧", "双侧", "左", "右")
NEGATION_TERMS = ("没有", "未见", "否认", "不是", "无", "不", "没")


def normalize_transcript(text: str) -> str:
    """保留中英文和数字，去除标点/空白，用于中文 CER。"""

    chars: list[str] = []
    for char in unicodedata.normalize("NFKC", text).casefold():
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            chars.append(char)
    return "".join(chars)


def mixed_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [match.group(0) for match in MIXED_TOKEN_PATTERN.finditer(normalized)]


def transcript_error_rates(reference: str, hypothesis: str) -> dict[str, float | int]:
    """计算标准 CER 和中英混合 token error rate。"""

    from jiwer import cer, wer

    reference_chars = normalize_transcript(reference)
    hypothesis_chars = normalize_transcript(hypothesis)
    reference_tokens = mixed_tokens(reference)
    hypothesis_tokens = mixed_tokens(hypothesis)
    char_error_rate = float(cer(reference_chars, hypothesis_chars)) if reference_chars else 0.0
    token_error_rate = (
        float(wer(" ".join(reference_tokens), " ".join(hypothesis_tokens)))
        if reference_tokens
        else 0.0
    )
    return {
        "reference_char_count": len(reference_chars),
        "hypothesis_char_count": len(hypothesis_chars),
        "cer": char_error_rate,
        "reference_mixed_token_count": len(reference_tokens),
        "hypothesis_mixed_token_count": len(hypothesis_tokens),
        "mixed_token_error_rate": token_error_rate,
    }


def hypothesis_error_flags(
    reference: str,
    hypothesis: str,
) -> tuple[list[bool], dict[str, int]]:
    """用可解释序列对齐标出 hypothesis 字符错误；deletion 单独计数。"""

    matcher = SequenceMatcher(a=reference, b=hypothesis, autojunk=False)
    flags = [False] * len(hypothesis)
    counts: Counter[str] = Counter()
    for tag, ref_start, ref_end, hyp_start, hyp_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            counts["substitution_reference_chars"] += ref_end - ref_start
            counts["substitution_hypothesis_chars"] += hyp_end - hyp_start
            for index in range(hyp_start, hyp_end):
                flags[index] = True
        elif tag == "insert":
            counts["insertion_chars"] += hyp_end - hyp_start
            for index in range(hyp_start, hyp_end):
                flags[index] = True
        elif tag == "delete":
            counts["deletion_chars"] += ref_end - ref_start
    counts["detectable_hypothesis_error_chars"] = sum(flags)
    return flags, dict(counts)


def flatten_asr_words(
    records: Sequence[ASRConfidenceRecord],
) -> tuple[str, list[str], list[float | None]]:
    """按绝对时间/窗口顺序拼接 ASR words，并展开到归一化字符级风险。"""

    def record_key(record: ASRConfidenceRecord) -> tuple[float, str]:
        starts = [word.start_sec for word in record.asr_words if word.start_sec is not None]
        return (min(starts) if starts else math.inf, record.sample_id)

    transcript_chars: list[str] = []
    levels: list[str] = []
    scores: list[float | None] = []
    for record in sorted(records, key=record_key):
        for word in record.asr_words:
            normalized = normalize_transcript(word.text)
            transcript_chars.extend(normalized)
            levels.extend([word.confidence_level.value] * len(normalized))
            scores.extend([word.confidence] * len(normalized))
    return "".join(transcript_chars), levels, scores


def confidence_risk_metrics(
    records: Sequence[ASRConfidenceRecord],
    *,
    reference_text: str,
) -> dict[str, Any]:
    """评估颜色分层、可审阅错误捕获、校准和 risk-coverage。"""

    hypothesis, levels, scores = flatten_asr_words(records)
    reference = normalize_transcript(reference_text)
    error_flags, edit_counts = hypothesis_error_flags(reference, hypothesis)
    if not (len(hypothesis) == len(levels) == len(scores) == len(error_flags)):
        raise ValueError("ASR 字符、颜色、分数和对齐错误标记长度不一致")

    by_level: dict[str, dict[str, float | int | None]] = {}
    for level in ("green", "yellow", "red", "unknown"):
        indices = [index for index, item in enumerate(levels) if item == level]
        errors = sum(error_flags[index] for index in indices)
        by_level[level] = {
            "char_count": len(indices),
            "detectable_error_char_count": errors,
            "detectable_error_rate": errors / len(indices) if indices else None,
        }

    review_indices = [index for index, level in enumerate(levels) if level in {"yellow", "red"}]
    detectable_error_count = sum(error_flags)
    review_error_count = sum(error_flags[index] for index in review_indices)
    reviewed_char_count = len(review_indices)
    review_recall = review_error_count / detectable_error_count if detectable_error_count else None
    review_precision = review_error_count / reviewed_char_count if reviewed_char_count else None

    valid = [
        (float(score), bool(error))
        for score, error in zip(scores, error_flags, strict=True)
        if score is not None and math.isfinite(float(score))
    ]
    valid.sort(key=lambda item: item[0], reverse=True)
    curve: list[dict[str, float]] = []
    for step in range(1, 21):
        coverage = step / 20
        count = max(1, int(math.ceil(len(valid) * coverage))) if valid else 0
        retained = valid[:count]
        risk = sum(error for _, error in retained) / count if count else 0.0
        curve.append({"coverage": coverage, "selective_detectable_error_rate": risk})
    aurc = 0.0
    previous_coverage = 0.0
    previous_risk = 0.0
    for point in curve:
        coverage = point["coverage"]
        risk = point["selective_detectable_error_rate"]
        aurc += (coverage - previous_coverage) * (risk + previous_risk) / 2
        previous_coverage = coverage
        previous_risk = risk

    word_scores: list[float] = []
    word_correctness: list[float] = []
    cursor = 0
    for record in sorted(records, key=lambda item: item.sample_id):
        for word in record.asr_words:
            normalized = normalize_transcript(word.text)
            end = cursor + len(normalized)
            if normalized and word.confidence is not None and end <= len(error_flags):
                word_scores.append(float(word.confidence))
                word_correctness.append(float(not any(error_flags[cursor:end])))
            cursor = end
    calibration = binary_calibration_metrics(word_correctness, word_scores)

    return {
        "hypothesis_normalized_char_count": len(hypothesis),
        "reference_normalized_char_count": len(reference),
        "edit_counts_from_sequence_alignment": edit_counts,
        "risk_by_level": by_level,
        "review_policy": "review_yellow_and_red",
        "reviewed_char_fraction": reviewed_char_count / len(hypothesis) if hypothesis else 0.0,
        "detectable_error_recall": review_recall,
        "review_precision_for_detectable_errors": review_precision,
        "green_detectable_error_escape_rate": (
            by_level["green"]["detectable_error_char_count"] / detectable_error_count
            if detectable_error_count
            else None
        ),
        "risk_coverage_curve": curve,
        "aurc_detectable_char_errors": aurc,
        "calibration_on_proxy_word_correctness": calibration,
        "scope_note": (
            "颜色捕获只评估可映射到 hypothesis 字符的替换/插入错误；deletion 无 ASR 字符，"
            "不能归因到颜色。"
        ),
    }


def binary_calibration_metrics(
    correctness: Sequence[float],
    confidences: Sequence[float],
    *,
    bins: int = 10,
) -> dict[str, float | int | None]:
    if not correctness:
        return {"word_count": 0, "ece": None, "brier": None}
    brier = sum(
        (confidence - correct) ** 2
        for confidence, correct in zip(confidences, correctness, strict=True)
    ) / len(correctness)
    ece = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        indices = [
            index
            for index, value in enumerate(confidences)
            if lower <= value < upper or (bin_index == bins - 1 and value == 1.0)
        ]
        if not indices:
            continue
        mean_confidence = sum(confidences[index] for index in indices) / len(indices)
        mean_correctness = sum(correctness[index] for index in indices) / len(indices)
        ece += len(indices) / len(correctness) * abs(mean_confidence - mean_correctness)
    return {"word_count": len(correctness), "ece": ece, "brier": brier}


def term_inventory(text: str, terms_by_category: dict[str, Iterable[str]]) -> dict[str, set[str]]:
    normalized = normalize_transcript(text)
    inventory: dict[str, set[str]] = {}
    for category, terms in terms_by_category.items():
        inventory[category] = {
            term
            for term in {normalize_transcript(item) for item in terms}
            if term and term in normalized
        }
    return inventory


def extract_parameter_values(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return {re.sub(r"\s+", "", match.group(0)) for match in PARAMETER_PATTERN.finditer(normalized)}


def set_recall(reference: set[str], hypothesis: set[str]) -> float | None:
    if not reference:
        return None
    return len(reference & hypothesis) / len(reference)


def critical_information_metrics(
    reference: str,
    hypothesis: str,
    *,
    terms_by_category: dict[str, Iterable[str]],
) -> dict[str, Any]:
    """计算项目自定义 Critical Information Preservation Score。"""

    reference_inventory = term_inventory(reference, terms_by_category)
    hypothesis_inventory = term_inventory(hypothesis, terms_by_category)
    reference_medical = set().union(*reference_inventory.values()) if reference_inventory else set()
    hypothesis_medical = (
        set().union(*hypothesis_inventory.values()) if hypothesis_inventory else set()
    )
    reference_negation = term_inventory(reference, {"negation": NEGATION_TERMS})["negation"]
    hypothesis_negation = term_inventory(hypothesis, {"negation": NEGATION_TERMS})["negation"]
    reference_laterality = term_inventory(reference, {"laterality": LATERALITY_TERMS})["laterality"]
    hypothesis_laterality = term_inventory(hypothesis, {"laterality": LATERALITY_TERMS})[
        "laterality"
    ]
    reference_parameters = extract_parameter_values(reference)
    hypothesis_parameters = extract_parameter_values(hypothesis)
    components = {
        "medical_term_recall": set_recall(reference_medical, hypothesis_medical),
        "negation_recall": set_recall(reference_negation, hypothesis_negation),
        "parameter_value_recall": set_recall(reference_parameters, hypothesis_parameters),
        "laterality_recall": set_recall(reference_laterality, hypothesis_laterality),
    }
    weights = {
        "medical_term_recall": 0.35,
        "negation_recall": 0.20,
        "parameter_value_recall": 0.25,
        "laterality_recall": 0.20,
    }
    available = {key: value for key, value in components.items() if value is not None}
    weight_sum = sum(weights[key] for key in available)
    cips = (
        sum(float(value) * weights[key] for key, value in available.items()) / weight_sum
        if weight_sum
        else None
    )
    return {
        **components,
        "critical_information_preservation_score": cips,
        "reference_counts": {
            "medical_terms": len(reference_medical),
            "negation_terms": len(reference_negation),
            "parameter_values": len(reference_parameters),
            "laterality_terms": len(reference_laterality),
        },
        "definition": (
            "CIPS = available-component weighted mean: medical terms 0.35, negation 0.20, "
            "number+unit parameters 0.25, laterality 0.20. Missing reference components are "
            "excluded and remaining weights are renormalized."
        ),
    }


def proxy_fact_textual_recall(
    proxy_facts: Sequence[dict[str, Any]],
    hypothesis: str,
) -> dict[str, float | int | None]:
    """用代理事实的逐字 evidence_terms 估计病例信息可恢复性。"""

    normalized_hypothesis = normalize_transcript(hypothesis)
    evaluated = 0
    recovered = 0
    critical_evaluated = 0
    critical_recovered = 0
    by_category: dict[str, Counter[str]] = {}
    for fact in proxy_facts:
        terms = [
            normalize_transcript(str(term))
            for term in fact.get("evidence_terms") or []
            if normalize_transcript(str(term))
        ]
        if not terms:
            continue
        hit = any(term in normalized_hypothesis for term in terms)
        evaluated += 1
        recovered += int(hit)
        category = str(fact.get("category") or "other")
        by_category.setdefault(category, Counter())["evaluated"] += 1
        by_category[category]["recovered"] += int(hit)
        if str(fact.get("criticality") or "routine") in {"important", "safety_critical"}:
            critical_evaluated += 1
            critical_recovered += int(hit)
    return {
        "fact_count_with_evidence_terms": evaluated,
        "recovered_fact_count": recovered,
        "proxy_fact_textual_recall": recovered / evaluated if evaluated else None,
        "critical_fact_count_with_evidence_terms": critical_evaluated,
        "critical_recovered_fact_count": critical_recovered,
        "critical_proxy_fact_textual_recall": (
            critical_recovered / critical_evaluated if critical_evaluated else None
        ),
        "by_category": {
            category: {
                "evaluated": counts["evaluated"],
                "recovered": counts["recovered"],
                "recall": counts["recovered"] / counts["evaluated"],
            }
            for category, counts in sorted(by_category.items())
        },
    }


def flatten_case_summary(summary: dict[str, Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for key, value in summary.items():
        if key in {"summary_text", "uncertainty_notes"} or value in (None, "", []):
            continue
        if isinstance(value, list):
            items = [str(item) for item in value if str(item).strip()]
        else:
            items = [str(value)]
        if items:
            fields[key] = items
    return fields


def case_summary_pair_metrics(
    reference_summary: dict[str, Any],
    noisy_summary: dict[str, Any],
    *,
    threshold: float = 0.55,
) -> dict[str, Any]:
    """比较同一模型在 proxy/reference 与 noisy 输入上的结构化病例信息稳定性。"""

    reference_fields = flatten_case_summary(reference_summary)
    noisy_fields = flatten_case_summary(noisy_summary)
    reference_items = [(field, text) for field, texts in reference_fields.items() for text in texts]
    noisy_items = [(field, text) for field, texts in noisy_fields.items() for text in texts]
    matches: list[tuple[int, int, float]] = []
    used_noisy: set[int] = set()
    for reference_index, (reference_field, reference_text) in enumerate(reference_items):
        best: tuple[int, float] | None = None
        reference_key = normalize_transcript(reference_text)
        for noisy_index, (noisy_field, noisy_text) in enumerate(noisy_items):
            if noisy_index in used_noisy or noisy_field != reference_field:
                continue
            score = SequenceMatcher(
                None,
                reference_key,
                normalize_transcript(noisy_text),
                autojunk=False,
            ).ratio()
            if best is None or score > best[1]:
                best = (noisy_index, score)
        if best is not None and best[1] >= threshold:
            used_noisy.add(best[0])
            matches.append((reference_index, best[0], best[1]))
    matched = len(matches)
    precision = matched / len(noisy_items) if noisy_items else None
    recall = matched / len(reference_items) if reference_items else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    critical_fields = {"negated_or_absent_symptoms", "medications", "plan_mentioned"}
    critical_reference_indices = {
        index for index, (field, _) in enumerate(reference_items) if field in critical_fields
    }
    critical_matched = sum(index in critical_reference_indices for index, _, _ in matches)
    return {
        "reference_fact_count": len(reference_items),
        "noisy_fact_count": len(noisy_items),
        "matched_fact_count": matched,
        "fact_precision": precision,
        "fact_recall": recall,
        "fact_f1": f1,
        "critical_reference_fact_count": len(critical_reference_indices),
        "critical_fact_recall": (
            critical_matched / len(critical_reference_indices)
            if critical_reference_indices
            else None
        ),
        "matching_method": f"same_field_normalized_sequence_ratio>={threshold:.2f}",
    }


def safe_mean(values: Iterable[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None
