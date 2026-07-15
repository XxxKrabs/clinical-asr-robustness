"""T042: schema and utilities for case-summary quality evaluation.

The first T042 milestone is the gold key facts layer.  A gold fact is a
short, de-identified, normalized clinical fact derived from the clean/reference
transcript.  It is used to evaluate whether summaries generated from raw ASR,
confirmed transcript, or reference transcript preserve the same information.

This module intentionally avoids storing full transcript text in summaries.
Per-line annotation files may contain short ``canonical_fact`` labels, but
public aggregate outputs should only contain counts and metadata.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinical_asr_robustness._compat import StrEnum
from clinical_asr_robustness.asr_confidence import (
    CLINICAL_USE_WARNING,
    ASRConfidenceRecord,
    ASRWord,
    ConfidenceLevel,
    SourceChannel,
    UncertainSpan,
    read_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_quality_evaluation import path_for_record, resolve_project_path
from clinical_asr_robustness.case_summary_generation import (
    INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
    INPUT_VARIANT_NOISY_ASR,
    CaseSummary,
    coerce_case_summary_payload,
)
from clinical_asr_robustness.review_workflow import ConfirmedTranscriptRecord

CASE_SUMMARY_EVALUATION_TASK_ID = "T042"
GOLD_KEY_FACT_SCHEMA_VERSION = "gold_key_fact/v1"
GOLD_KEY_FACTS_SUMMARY_SCHEMA_VERSION = "gold_key_facts_summary/v1"
CASE_SUMMARY_FACT_EVALUATION_SCHEMA_VERSION = "case_summary_fact_evaluation/v1"
CASE_SUMMARY_QUALITY_RECORD_SCHEMA_VERSION = "case_summary_quality_record/v1"
CASE_SUMMARY_QUALITY_SUMMARY_SCHEMA_VERSION = "case_summary_quality_summary/v1"
CASE_SUMMARY_QUALITY_SUBTASKS = [
    "T042c_rouge_l_auxiliary",
    "T042d_source_aware_factuality_b_lite",
    "T042e_high_risk_error_and_uncertainty_notes",
    "T042f_asr_confidence_and_review_cost_attribution",
]

GOLD_KEY_FACTS_DEFAULT_INPUT = Path(
    "data/processed/primock57/t042_case_summary_evaluation/gold_key_facts.jsonl"
)
GOLD_KEY_FACTS_DEFAULT_OUTPUT_DIR = Path(
    "outputs/primock57/t042_case_summary_evaluation"
)
CASE_SUMMARY_RECORDS_DEFAULT_INPUT = Path(
    "outputs/primock57/t042_case_summary_variant_generation/"
    "primock57_t042_case_summary_variant_records.jsonl"
)

DEFAULT_FACT_SUPPORT_THRESHOLD = 0.50
DEFAULT_FACT_CONTRADICTION_THRESHOLD = 0.35
MAX_FACT_LABEL_CHARS = 240


class CaseSummaryFactField(StrEnum):
    """Structured T041 summary field that a gold fact belongs to."""

    CHIEF_COMPLAINT = "chief_complaint"
    HISTORY_OF_PRESENT_ILLNESS = "history_of_present_illness"
    SYMPTOMS = "symptoms"
    NEGATED_OR_ABSENT_SYMPTOMS = "negated_or_absent_symptoms"
    RELEVANT_HISTORY = "relevant_history"
    MEDICATIONS = "medications"
    TESTS_OR_EXAM_MENTIONED = "tests_or_exam_mentioned"
    ASSESSMENT_MENTIONED = "assessment_mentioned"
    PLAN_MENTIONED = "plan_mentioned"


class GoldFactPolarity(StrEnum):
    """Whether the fact is asserted, negated, historical, planned, or uncertain."""

    PRESENT = "present"
    ABSENT = "absent"
    HISTORICAL = "historical"
    PLANNED = "planned"
    UNCERTAIN = "uncertain"


class GoldFactSeverity(StrEnum):
    """Importance of preserving this fact in a downstream case summary."""

    MINOR = "minor"
    MAJOR = "major"
    SAFETY_CRITICAL = "safety_critical"


class SummaryHighRiskTag(StrEnum):
    """High-risk error families tracked by T042 source-aware evaluation."""

    MEDICAL_TERM = "medical_term"
    DRUG_NAME = "drug_name"
    MEDICATION_DOSE_OR_ROUTE = "medication_dose_or_route"
    NEGATION_OR_POLARITY = "negation_or_polarity"
    SPEAKER_ATTRIBUTION = "speaker_attribution"
    TEST_OR_EXAM = "test_or_exam"
    ASSESSMENT_OR_DIAGNOSIS = "assessment_or_diagnosis"
    PLAN_OR_FOLLOW_UP = "plan_or_follow_up"
    TEMPORALITY = "temporality"
    UNCERTAINTY = "uncertainty"
    ASR_NOISE_SENSITIVE = "asr_noise_sensitive"


class SummaryFactFactuality(StrEnum):
    """B-lite source-aware factuality label for one generated summary fact."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


class SummaryFactPolarity(StrEnum):
    """Lightweight polarity inferred from the summary field/text."""

    PRESENT = "present"
    ABSENT = "absent"
    HISTORICAL = "historical"
    PLANNED = "planned"
    UNCERTAIN = "uncertain"


class ExtractedSummaryFact(BaseModel):
    """One short atomic-ish fact extracted from a structured T041 summary."""

    model_config = ConfigDict(extra="forbid")

    fact_index: int = Field(ge=0)
    field: CaseSummaryFactField
    text: str = Field(min_length=1, max_length=MAX_FACT_LABEL_CHARS)
    inferred_polarity: SummaryFactPolarity = SummaryFactPolarity.PRESENT

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = _short_fact_label(value)
        if not normalized:
            raise ValueError("summary fact text must not be empty")
        return normalized


class EvidencePointer(BaseModel):
    """Pointer to evidence without copying the full transcript.

    ``cue`` is a short de-identified label such as "vomiting mentioned" or
    "denies blood in stool".  It is not meant to be a full utterance.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(
        default="reference_transcript",
        description="reference_transcript, reference_note, audio_time_range, etc.",
    )
    sample_id: str | None = None
    record_id: str | None = None
    source_channel: SourceChannel = SourceChannel.UNKNOWN
    turn_index: int | None = Field(default=None, ge=0)
    word_start_index: int | None = Field(default=None, ge=0)
    word_end_index: int | None = Field(default=None, ge=0)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    cue: str | None = Field(
        default=None,
        max_length=120,
        description="Short de-identified evidence cue; do not paste full text.",
    )
    contains_full_transcript_text: bool = False

    @field_validator("source_type", "sample_id", "record_id", "cue")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("cue")
    @classmethod
    def reject_multiline_cue(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if "\n" in value or "\r" in value:
            raise ValueError("evidence cue must be a short single-line label")
        return value

    @model_validator(mode="after")
    def validate_ranges_and_privacy(self) -> EvidencePointer:
        if self.contains_full_transcript_text:
            raise ValueError(
                "evidence_pointer must not contain full transcript text; "
                "store word/time indices and a short de-identified cue instead"
            )
        if (
            self.word_start_index is not None
            and self.word_end_index is not None
            and self.word_end_index <= self.word_start_index
        ):
            raise ValueError("word_end_index must be greater than word_start_index")
        if (
            self.start_sec is not None
            and self.end_sec is not None
            and self.end_sec < self.start_sec
        ):
            raise ValueError("end_sec must be greater than or equal to start_sec")
        return self


class GoldKeyFact(BaseModel):
    """One reference gold key fact for T042 case-summary quality evaluation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = GOLD_KEY_FACT_SCHEMA_VERSION
    fact_id: str
    bundle_id: str
    dataset: str = "primock57"
    split: str | None = None
    consultation_id: str | None = None
    field: CaseSummaryFactField
    canonical_fact: str = Field(
        min_length=1,
        max_length=240,
        description="Short normalized fact label, not a full transcript sentence.",
    )
    polarity: GoldFactPolarity = GoldFactPolarity.PRESENT
    severity: GoldFactSeverity = GoldFactSeverity.MAJOR
    source_channel: SourceChannel = SourceChannel.UNKNOWN
    evidence_pointer: EvidencePointer
    error_tags: list[SummaryHighRiskTag] = Field(default_factory=list)
    normalized_terms: list[str] = Field(default_factory=list)
    annotator_role: str | None = Field(
        default=None,
        description="researcher, clinician, adjudicator, etc.; no personal identity.",
    )
    reviewed: bool = False
    notes: str | None = Field(
        default=None,
        max_length=240,
        description="Optional de-identified annotation note.",
    )
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != GOLD_KEY_FACT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported gold key fact schema_version: {value}; "
                f"expected {GOLD_KEY_FACT_SCHEMA_VERSION}"
            )
        return value

    @field_validator("fact_id", "bundle_id", "dataset", "consultation_id", "notes")
    @classmethod
    def strip_optional_fields(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("canonical_fact")
    @classmethod
    def validate_canonical_fact(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("canonical_fact must not be empty")
        if "\n" in stripped or "\r" in stripped:
            raise ValueError("canonical_fact must be a short single-line label")
        return stripped

    @field_validator("normalized_terms")
    @classmethod
    def normalize_terms(cls, value: list[str]) -> list[str]:
        return [term.strip().casefold() for term in value if term.strip()]

    @model_validator(mode="after")
    def validate_source_channel_consistency(self) -> GoldKeyFact:
        pointer_channel = self.evidence_pointer.source_channel
        if (
            pointer_channel != SourceChannel.UNKNOWN
            and self.source_channel != SourceChannel.UNKNOWN
            and pointer_channel != self.source_channel
        ):
            raise ValueError(
                "source_channel must match evidence_pointer.source_channel when both "
                "are known"
            )
        if self.field == CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS and (
            self.polarity != GoldFactPolarity.ABSENT
        ):
            raise ValueError(
                "negated_or_absent_symptoms facts must use polarity='absent'"
            )
        if self.field == CaseSummaryFactField.PLAN_MENTIONED and (
            self.polarity == GoldFactPolarity.ABSENT
        ):
            raise ValueError("plan_mentioned facts should not use polarity='absent'")
        return self


def build_gold_bundle_id(
    *,
    dataset: str,
    consultation_id: str,
    input_unit: str = "consultation",
) -> str:
    """Build a variant-neutral T042 bundle id for gold facts."""

    return f"{dataset}:{consultation_id}:gold_key_facts:{input_unit}"


def read_gold_key_facts_jsonl(path: str | Path) -> list[GoldKeyFact]:
    """Read and validate ``gold_key_facts.jsonl``."""

    facts_path = Path(path)
    facts: list[GoldKeyFact] = []
    seen_fact_ids: set[str] = set()
    with facts_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                fact = GoldKeyFact.model_validate_json(stripped)
            except Exception as exc:  # noqa: BLE001 - include line number for annotators
                raise ValueError(
                    f"cannot parse gold key facts JSONL line {line_number}: {facts_path}"
                ) from exc
            if fact.fact_id in seen_fact_ids:
                raise ValueError(
                    f"duplicate fact_id in gold key facts JSONL line {line_number}: "
                    f"{fact.fact_id}"
                )
            seen_fact_ids.add(fact.fact_id)
            facts.append(fact)
    return facts


def write_gold_key_facts_jsonl(
    facts: Iterable[GoldKeyFact | dict[str, Any]],
    path: str | Path,
) -> None:
    """Write validated gold key facts JSONL."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for item in facts:
            fact = item if isinstance(item, GoldKeyFact) else GoldKeyFact.model_validate(item)
            file.write(json.dumps(fact.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def build_gold_key_facts_summary(
    facts: Iterable[GoldKeyFact],
    *,
    input_jsonl: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Build an aggregate summary that does not include fact text."""

    fact_list = list(facts)
    by_field = Counter(fact.field.value for fact in fact_list)
    by_polarity = Counter(fact.polarity.value for fact in fact_list)
    by_severity = Counter(fact.severity.value for fact in fact_list)
    by_channel = Counter(fact.source_channel.value for fact in fact_list)
    by_bundle = Counter(fact.bundle_id for fact in fact_list)
    high_risk_tag_counts: Counter[str] = Counter()
    reviewed_count = 0
    for fact in fact_list:
        high_risk_tag_counts.update(tag.value for tag in fact.error_tags)
        if fact.reviewed:
            reviewed_count += 1
    return {
        "schema_version": GOLD_KEY_FACTS_SUMMARY_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_EVALUATION_TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_files": {
            "gold_key_facts_jsonl": path_for_record(input_jsonl, project_root),
        },
        "fact_count": len(fact_list),
        "bundle_count": len(by_bundle),
        "counts_by_field": dict(by_field),
        "counts_by_polarity": dict(by_polarity),
        "counts_by_severity": dict(by_severity),
        "counts_by_source_channel": dict(by_channel),
        "high_risk_tag_counts": dict(high_risk_tag_counts),
        "reviewed_count": reviewed_count,
        "unreviewed_count": len(fact_list) - reviewed_count,
        "privacy_and_safety": {
            "summary_contains_canonical_fact_text": False,
            "summary_contains_full_transcript_text": False,
            "gold_jsonl_should_not_contain_full_transcript_text": True,
            "research_use_only": True,
        },
        "notes": (
            "T042a validates the source-aware gold key facts layer. Join these facts "
            "to T041 summary records by dataset/consultation_id/input_unit rather than "
            "by input_variant-specific summary text."
        ),
    }


def run_gold_key_facts_validation(
    *,
    input_jsonl: str | Path,
    output_summary_json: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate gold key facts and write an aggregate summary JSON."""

    root = Path(project_root)
    input_path = resolve_project_path(input_jsonl, root)
    output_path = resolve_project_path(output_summary_json, root)
    facts = read_gold_key_facts_jsonl(input_path)
    summary = build_gold_key_facts_summary(
        facts,
        input_jsonl=input_path,
        project_root=root,
    )
    write_json(summary, output_path)
    return summary


def read_case_summary_generation_records_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read T041/T042b case-summary generation records as dictionaries."""

    records_path = Path(path)
    records: list[dict[str, Any]] = []
    with records_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"cannot parse case-summary records JSONL line {line_number}: "
                    f"{records_path}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(
                    f"case-summary records JSONL line {line_number} is not an object: "
                    f"{records_path}"
                )
            records.append(payload)
    return records


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    """Write JSONL with UTF-8 encoding."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def rouge_l_score(candidate: str, reference: str) -> dict[str, float | int]:
    """Compute a dependency-free ROUGE-L precision/recall/F1 score.

    The tokenizer keeps English/number spans as word tokens and treats CJK
    characters as individual tokens.  This is intentionally lightweight: T042c
    uses ROUGE-L only as an auxiliary comparability layer, not as the primary
    factuality metric.
    """

    candidate_tokens = _tokenize_for_rouge(candidate)
    reference_tokens = _tokenize_for_rouge(reference)
    if not candidate_tokens or not reference_tokens:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "lcs": 0,
            "candidate_token_count": len(candidate_tokens),
            "reference_token_count": len(reference_tokens),
        }
    lcs = _lcs_length(candidate_tokens, reference_tokens)
    precision = lcs / len(candidate_tokens)
    recall = lcs / len(reference_tokens)
    f1 = _safe_f1(precision, recall)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "lcs": lcs,
        "candidate_token_count": len(candidate_tokens),
        "reference_token_count": len(reference_tokens),
    }


def extract_summary_facts(case_summary: CaseSummary | dict[str, Any]) -> list[ExtractedSummaryFact]:
    """Extract short field-level facts from a structured T041 ``case_summary``."""

    summary = (
        case_summary
        if isinstance(case_summary, CaseSummary)
        else coerce_case_summary_payload(case_summary)
    )
    payload = summary.model_dump(mode="json")
    fact_specs: list[tuple[CaseSummaryFactField, str]] = []
    for field in (
        CaseSummaryFactField.CHIEF_COMPLAINT,
        CaseSummaryFactField.HISTORY_OF_PRESENT_ILLNESS,
        CaseSummaryFactField.SYMPTOMS,
        CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS,
        CaseSummaryFactField.RELEVANT_HISTORY,
        CaseSummaryFactField.MEDICATIONS,
        CaseSummaryFactField.TESTS_OR_EXAM_MENTIONED,
        CaseSummaryFactField.ASSESSMENT_MENTIONED,
        CaseSummaryFactField.PLAN_MENTIONED,
    ):
        value = payload.get(field.value)
        if isinstance(value, list):
            fact_specs.extend((field, str(item)) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            fact_specs.append((field, value))

    facts: list[ExtractedSummaryFact] = []
    for index, (field, text) in enumerate(fact_specs):
        label = _short_fact_label(text)
        if not label:
            continue
        facts.append(
            ExtractedSummaryFact(
                fact_index=index,
                field=field,
                text=label,
                inferred_polarity=infer_summary_fact_polarity(field, label),
            )
        )
    return facts


def infer_summary_fact_polarity(
    field: CaseSummaryFactField,
    text: str,
) -> SummaryFactPolarity:
    """Infer a lightweight polarity label for B-lite matching."""

    normalized = _normalize_for_matching(text)
    if field == CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS:
        return SummaryFactPolarity.ABSENT
    if field == CaseSummaryFactField.PLAN_MENTIONED:
        return SummaryFactPolarity.PLANNED
    if any(marker in normalized for marker in _NEGATION_MARKERS):
        return SummaryFactPolarity.ABSENT
    if any(marker in normalized for marker in _UNCERTAINTY_MARKERS):
        return SummaryFactPolarity.UNCERTAIN
    if any(marker in normalized for marker in _HISTORICAL_MARKERS):
        return SummaryFactPolarity.HISTORICAL
    if any(marker in normalized for marker in _PLANNED_MARKERS):
        return SummaryFactPolarity.PLANNED
    return SummaryFactPolarity.PRESENT


def score_summary_fact_against_gold(
    summary_fact: ExtractedSummaryFact,
    gold_fact: GoldKeyFact,
) -> dict[str, Any]:
    """Score one generated summary fact against one gold key fact."""

    rouge = rouge_l_score(summary_fact.text, gold_fact.canonical_fact)
    term_coverage = _normalized_term_coverage(summary_fact.text, gold_fact.normalized_terms)
    score = max(float(rouge["f1"]), term_coverage)
    polarity_compatible = _polarity_is_compatible(
        summary_fact.inferred_polarity,
        gold_fact.polarity,
    )
    return {
        "match_score": score,
        "rouge_l": rouge,
        "term_coverage": term_coverage,
        "polarity_compatible": polarity_compatible,
        "field_matches": summary_fact.field == gold_fact.field,
    }


def evaluate_summary_record(
    summary_record: dict[str, Any],
    gold_facts: Sequence[GoldKeyFact],
    *,
    asr_attribution_index: dict[str, Any] | None = None,
    confirmed_index: dict[str, ConfirmedTranscriptRecord] | None = None,
    support_threshold: float = DEFAULT_FACT_SUPPORT_THRESHOLD,
    contradiction_threshold: float = DEFAULT_FACT_CONTRADICTION_THRESHOLD,
    include_fact_text: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate one T041/T042b summary record against source-aware gold facts."""

    summary_payload = summary_record.get("case_summary")
    bundle_id = str(summary_record.get("bundle_id") or "")
    dataset = str(summary_record.get("dataset") or "")
    consultation_id = summary_record.get("consultation_id")
    input_unit = str(summary_record.get("input_unit") or "consultation")
    input_variant = str(summary_record.get("input_variant") or "")
    gold_bundle_id = (
        build_gold_bundle_id(
            dataset=dataset,
            consultation_id=str(consultation_id),
            input_unit=input_unit,
        )
        if consultation_id
        else None
    )

    base_record: dict[str, Any] = {
        "schema_version": CASE_SUMMARY_QUALITY_RECORD_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_EVALUATION_TASK_ID,
        "t042_subtasks": CASE_SUMMARY_QUALITY_SUBTASKS,
        "bundle_id": bundle_id,
        "gold_bundle_id": gold_bundle_id,
        "dataset": dataset,
        "split": summary_record.get("split"),
        "consultation_id": consultation_id,
        "input_unit": input_unit,
        "input_variant": input_variant,
        "prompt_version": summary_record.get("prompt_version"),
        "case_summary_status": summary_record.get("status"),
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
    }

    if not summary_payload:
        skipped = {
            **base_record,
            "evaluation_status": "skipped",
            "skip_reason": "missing_case_summary",
            "summary_fact_count": 0,
            "gold_fact_count": len(gold_facts),
            "factuality_counts": {},
            "fact_precision": None,
            "fact_recall": None,
            "fact_f1": None,
            "critical_fact_recall": None,
            "omission_count": None,
            "rouge_l_against_gold_facts": None,
            "high_risk_error_counts": {},
            "high_risk_error_type_counts": {},
            "uncertainty_note_evaluation": {
                "evaluation_status": "skipped",
                "skip_reason": "missing_case_summary",
                "requires_uncertainty_notes": False,
                "coverage_status": "not_evaluated",
                "note_count": 0,
                "uncertain_span_count": _coerce_non_negative_int(
                    summary_record.get("uncertain_span_count")
                ),
            },
            "privacy_and_safety": _quality_privacy_flags(
                include_fact_text=include_fact_text,
            ),
        }
        return skipped, []

    case_summary = coerce_case_summary_payload(summary_payload)
    summary_facts = extract_summary_facts(case_summary)
    gold_fact_list = list(gold_facts)
    fact_evaluations = [
        _evaluate_one_summary_fact(
            summary_fact,
            summary_record=summary_record,
            gold_facts=gold_fact_list,
            support_threshold=support_threshold,
            contradiction_threshold=contradiction_threshold,
            include_fact_text=include_fact_text,
        )
        for summary_fact in summary_facts
    ]
    factuality_counts = Counter(
        item["factuality_label"] for item in fact_evaluations
    )
    recovered_gold_fact_ids = _recovered_gold_fact_ids(
        summary_facts,
        gold_fact_list,
        support_threshold=support_threshold,
    )
    omitted_gold_fact_ids = [
        fact.fact_id
        for fact in gold_fact_list
        if fact.fact_id not in recovered_gold_fact_ids
    ]
    safety_critical_fact_ids = [
        fact.fact_id
        for fact in gold_fact_list
        if fact.severity == GoldFactSeverity.SAFETY_CRITICAL
    ]
    safety_recovered = [
        fact_id
        for fact_id in safety_critical_fact_ids
        if fact_id in recovered_gold_fact_ids
    ]
    supported_count = factuality_counts[SummaryFactFactuality.SUPPORTED.value]
    summary_fact_count = len(summary_facts)
    gold_fact_count = len(gold_fact_list)
    precision = (
        supported_count / summary_fact_count
        if summary_fact_count and gold_fact_count
        else None
    )
    recall = (
        len(recovered_gold_fact_ids) / gold_fact_count
        if gold_fact_count
        else None
    )
    f1 = _safe_f1_or_none(precision, recall)
    critical_recall = (
        len(safety_recovered) / len(safety_critical_fact_ids)
        if safety_critical_fact_ids
        else None
    )
    rouge_reference = _flatten_gold_facts(gold_fact_list)
    rouge_candidate = _flatten_summary_facts(summary_facts)
    rouge = (
        rouge_l_score(rouge_candidate, rouge_reference)
        if rouge_candidate and rouge_reference
        else None
    )

    high_risk_error_counts = _high_risk_error_counts(
        fact_evaluations,
        gold_fact_list,
        omitted_gold_fact_ids=omitted_gold_fact_ids,
    )
    high_risk_error_type_counts = _high_risk_error_type_counts(
        fact_evaluations,
        gold_fact_list,
        omitted_gold_fact_ids=omitted_gold_fact_ids,
    )
    t042f_attribution = _attribute_summary_record_to_asr_and_review(
        summary_record=summary_record,
        gold_facts=gold_fact_list,
        fact_evaluations=fact_evaluations,
        omitted_gold_fact_ids=omitted_gold_fact_ids,
        asr_attribution_index=asr_attribution_index,
        confirmed_index=confirmed_index,
    )
    uncertainty_note_evaluation = _evaluate_uncertainty_notes(
        case_summary,
        summary_record=summary_record,
        fact_evaluations=fact_evaluations,
        gold_facts=gold_fact_list,
        omitted_gold_fact_ids=omitted_gold_fact_ids,
        high_risk_error_type_counts=high_risk_error_type_counts,
    )
    record = {
        **base_record,
        "evaluation_status": "evaluated",
        "skip_reason": None,
        "summary_fact_count": summary_fact_count,
        "gold_fact_count": gold_fact_count,
        "factuality_counts": dict(factuality_counts),
        "fact_precision": precision,
        "fact_recall": recall,
        "fact_f1": f1,
        "critical_fact_recall": critical_recall,
        "critical_fact_count": len(safety_critical_fact_ids),
        "critical_fact_recovered_count": len(safety_recovered),
        "omission_count": len(omitted_gold_fact_ids),
        "omitted_gold_fact_ids": omitted_gold_fact_ids,
        "recovered_gold_fact_count": len(recovered_gold_fact_ids),
        "rouge_l_against_gold_facts": rouge,
        "high_risk_error_counts": high_risk_error_counts,
        "high_risk_error_type_counts": high_risk_error_type_counts,
        "uncertainty_note_evaluation": uncertainty_note_evaluation,
        "confidence_attribution": t042f_attribution["confidence_attribution"],
        "review_cost_attribution": t042f_attribution["review_cost_attribution"],
        "thresholds": {
            "support_threshold": support_threshold,
            "contradiction_threshold": contradiction_threshold,
        },
        "privacy_and_safety": _quality_privacy_flags(
            include_fact_text=include_fact_text,
        ),
        "notes": (
            "T042c ROUGE-L compares flattened structured summary facts against "
            "gold canonical fact labels as an auxiliary metric. T042d B-lite uses "
            "heuristic source-aware matching. T042e adds high-risk error family "
            "and uncertainty-note coverage checks. T042f links gold evidence pointers "
            "to ASR confidence/review spans when ASR records are provided. "
            "These deterministic checks are "
            "not a substitute for manual clinical adjudication."
        ),
    }
    return record, fact_evaluations


def build_case_summary_quality_summary(
    quality_records: Sequence[dict[str, Any]],
    fact_evaluations: Sequence[dict[str, Any]],
    *,
    summary_records_jsonl: Path,
    gold_key_facts_jsonl: Path,
    asr_confidence_jsonl: Path | None = None,
    confirmed_transcripts_jsonl: Path | None = None,
    output_records_jsonl: Path,
    output_fact_evaluations_jsonl: Path,
    project_root: Path,
    include_fact_text: bool = False,
) -> dict[str, Any]:
    """Build an aggregate T042c/T042d summary without fact or transcript text."""

    evaluated_records = [
        record for record in quality_records if record["evaluation_status"] == "evaluated"
    ]
    skipped_records = [
        record for record in quality_records if record["evaluation_status"] == "skipped"
    ]
    by_variant: dict[str, dict[str, Any]] = {}
    for variant, records in _group_records_by(quality_records, "input_variant").items():
        evaluated_for_variant = [
            record for record in records if record["evaluation_status"] == "evaluated"
        ]
        by_variant[variant] = {
            "record_count": len(records),
            "evaluated_record_count": len(evaluated_for_variant),
            "skipped_record_count": len(records) - len(evaluated_for_variant),
            "summary_fact_count": sum(
                record.get("summary_fact_count", 0) for record in evaluated_for_variant
            ),
            "gold_fact_count": sum(
                record.get("gold_fact_count", 0) for record in evaluated_for_variant
            ),
            "factuality_counts": _sum_counter_field(
                evaluated_for_variant,
                "factuality_counts",
            ),
            "fact_precision_macro": _mean_metric(
                evaluated_for_variant,
                "fact_precision",
            ),
            "fact_recall_macro": _mean_metric(evaluated_for_variant, "fact_recall"),
            "fact_f1_macro": _mean_metric(evaluated_for_variant, "fact_f1"),
            "critical_fact_recall_macro": _mean_metric(
                evaluated_for_variant,
                "critical_fact_recall",
            ),
            "rouge_l_f1_macro": _mean_nested_metric(
                evaluated_for_variant,
                ("rouge_l_against_gold_facts", "f1"),
            ),
            "omission_count": sum(
                record.get("omission_count", 0) for record in evaluated_for_variant
            ),
            "high_risk_error_counts": _sum_counter_field(
                evaluated_for_variant,
                "high_risk_error_counts",
            ),
            "high_risk_error_type_counts": _sum_counter_field(
                evaluated_for_variant,
                "high_risk_error_type_counts",
            ),
            "uncertainty_note_summary": _aggregate_uncertainty_note_evaluations(
                evaluated_for_variant
            ),
            "confidence_attribution_summary": _aggregate_confidence_attributions(
                evaluated_for_variant
            ),
            "review_cost_attribution_summary": _aggregate_review_cost_attributions(
                evaluated_for_variant
            ),
        }

    factuality_counts = Counter(
        item["factuality_label"] for item in fact_evaluations
    )
    total_summary_facts = sum(
        record.get("summary_fact_count", 0) for record in evaluated_records
    )
    total_gold_facts = sum(record.get("gold_fact_count", 0) for record in evaluated_records)
    total_recovered_gold = sum(
        record.get("recovered_gold_fact_count", 0) for record in evaluated_records
    )
    supported_summary_facts = factuality_counts[SummaryFactFactuality.SUPPORTED.value]
    micro_precision = (
        supported_summary_facts / total_summary_facts if total_summary_facts else None
    )
    micro_recall = total_recovered_gold / total_gold_facts if total_gold_facts else None

    input_files = {
        "summary_records_jsonl": path_for_record(
            summary_records_jsonl,
            project_root,
        ),
        "gold_key_facts_jsonl": path_for_record(
            gold_key_facts_jsonl,
            project_root,
        ),
    }
    if asr_confidence_jsonl is not None:
        input_files["asr_confidence_jsonl"] = path_for_record(
            asr_confidence_jsonl,
            project_root,
        )
    if confirmed_transcripts_jsonl is not None:
        input_files["confirmed_transcripts_jsonl"] = path_for_record(
            confirmed_transcripts_jsonl,
            project_root,
        )

    return {
        "schema_version": CASE_SUMMARY_QUALITY_SUMMARY_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_EVALUATION_TASK_ID,
        "t042_subtasks": CASE_SUMMARY_QUALITY_SUBTASKS,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_files": input_files,
        "output_files": {
            "quality_records_jsonl": path_for_record(
                output_records_jsonl,
                project_root,
            ),
            "fact_evaluations_jsonl": path_for_record(
                output_fact_evaluations_jsonl,
                project_root,
            ),
        },
        "summary_record_count": len(quality_records),
        "evaluated_record_count": len(evaluated_records),
        "skipped_record_count": len(skipped_records),
        "skipped_record_reasons": dict(
            Counter(record.get("skip_reason") for record in skipped_records)
        ),
        "summary_fact_count": total_summary_facts,
        "gold_fact_count": total_gold_facts,
        "factuality_counts": dict(factuality_counts),
        "fact_precision_micro": micro_precision,
        "fact_recall_micro": micro_recall,
        "fact_f1_micro": _safe_f1_or_none(micro_precision, micro_recall),
        "fact_precision_macro": _mean_metric(evaluated_records, "fact_precision"),
        "fact_recall_macro": _mean_metric(evaluated_records, "fact_recall"),
        "fact_f1_macro": _mean_metric(evaluated_records, "fact_f1"),
        "critical_fact_recall_macro": _mean_metric(
            evaluated_records,
            "critical_fact_recall",
        ),
        "rouge_l_f1_macro": _mean_nested_metric(
            evaluated_records,
            ("rouge_l_against_gold_facts", "f1"),
        ),
        "omission_count": sum(
            record.get("omission_count", 0) for record in evaluated_records
        ),
        "high_risk_error_counts": _sum_counter_field(
            evaluated_records,
            "high_risk_error_counts",
        ),
        "high_risk_error_type_counts": _sum_counter_field(
            evaluated_records,
            "high_risk_error_type_counts",
        ),
        "uncertainty_note_summary": _aggregate_uncertainty_note_evaluations(
            evaluated_records
        ),
        "confidence_attribution_summary": _aggregate_confidence_attributions(
            evaluated_records
        ),
        "review_cost_attribution_summary": _aggregate_review_cost_attributions(
            evaluated_records
        ),
        "review_benefit_summary": _build_review_benefit_summary(evaluated_records),
        "by_input_variant": by_variant,
        "privacy_and_safety": {
            "summary_contains_fact_text": False,
            "summary_contains_full_transcript_text": False,
            "quality_records_contain_fact_text": False,
            "fact_evaluations_contain_fact_text": include_fact_text,
            "research_use_only": True,
        },
        "limitations": [
            (
                "ROUGE-L is auxiliary and uses gold canonical fact labels, "
                "not a human-written reference summary."
            ),
            (
                "B-lite factuality uses deterministic lexical/term matching "
                "and polarity heuristics; manual adjudication is still required "
                "for final claims."
            ),
            (
                "Dry-run T041 records without case_summary are skipped until "
                "--run-llm or manual summaries are provided."
            ),
        ],
    }


def run_case_summary_quality_evaluation(
    *,
    summary_records_jsonl: str | Path,
    gold_key_facts_jsonl: str | Path,
    asr_confidence_jsonl: str | Path | None = None,
    confirmed_transcripts_jsonl: str | Path | None = None,
    output_records_jsonl: str | Path,
    output_fact_evaluations_jsonl: str | Path,
    output_summary_json: str | Path,
    project_root: str | Path,
    support_threshold: float = DEFAULT_FACT_SUPPORT_THRESHOLD,
    contradiction_threshold: float = DEFAULT_FACT_CONTRADICTION_THRESHOLD,
    include_fact_text: bool = False,
) -> dict[str, Any]:
    """Run T042c/T042d quality evaluation and write records + aggregate summary."""

    root = Path(project_root)
    summary_records_path = resolve_project_path(summary_records_jsonl, root)
    gold_path = resolve_project_path(gold_key_facts_jsonl, root)
    asr_path = (
        resolve_project_path(asr_confidence_jsonl, root)
        if asr_confidence_jsonl is not None
        else None
    )
    confirmed_path = (
        resolve_project_path(confirmed_transcripts_jsonl, root)
        if confirmed_transcripts_jsonl is not None
        else None
    )
    records_path = resolve_project_path(output_records_jsonl, root)
    fact_eval_path = resolve_project_path(output_fact_evaluations_jsonl, root)
    summary_path = resolve_project_path(output_summary_json, root)

    summary_records = read_case_summary_generation_records_jsonl(summary_records_path)
    gold_facts = read_gold_key_facts_jsonl(gold_path)
    gold_by_key = _group_gold_facts(gold_facts)
    asr_attribution_index = (
        _build_asr_attribution_index(read_asr_confidence_jsonl(asr_path))
        if asr_path is not None
        else None
    )
    confirmed_index = (
        _build_confirmed_attribution_index(read_confirmed_transcripts_jsonl(confirmed_path))
        if confirmed_path is not None
        else None
    )

    quality_records: list[dict[str, Any]] = []
    fact_evaluations: list[dict[str, Any]] = []
    for summary_record in summary_records:
        gold_for_record = _gold_facts_for_summary_record(summary_record, gold_by_key)
        quality_record, record_fact_evaluations = evaluate_summary_record(
            summary_record,
            gold_for_record,
            asr_attribution_index=asr_attribution_index,
            confirmed_index=confirmed_index,
            support_threshold=support_threshold,
            contradiction_threshold=contradiction_threshold,
            include_fact_text=include_fact_text,
        )
        quality_records.append(quality_record)
        fact_evaluations.extend(record_fact_evaluations)

    write_jsonl(quality_records, records_path)
    write_jsonl(fact_evaluations, fact_eval_path)
    summary = build_case_summary_quality_summary(
        quality_records,
        fact_evaluations,
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        asr_confidence_jsonl=asr_path,
        confirmed_transcripts_jsonl=confirmed_path,
        output_records_jsonl=records_path,
        output_fact_evaluations_jsonl=fact_eval_path,
        project_root=root,
        include_fact_text=include_fact_text,
    )
    write_json(summary, summary_path)
    return summary


def read_confirmed_transcripts_jsonl(path: str | Path) -> list[ConfirmedTranscriptRecord]:
    """Read T035 confirmed transcript records for T042f attribution."""

    confirmed_path = Path(path)
    records: list[ConfirmedTranscriptRecord] = []
    with confirmed_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(ConfirmedTranscriptRecord.model_validate_json(stripped))
            except Exception as exc:  # noqa: BLE001 - keep file/line for debugging
                raise ValueError(
                    "cannot parse confirmed transcript JSONL line "
                    f"{line_number}: {confirmed_path}"
                ) from exc
    return records


def _build_asr_attribution_index(
    records: Sequence[ASRConfidenceRecord],
) -> dict[str, Any]:
    """Build lookup tables used to join gold evidence pointers to ASR records."""

    by_record_id: dict[str, ASRConfidenceRecord] = {}
    by_sample_id: dict[str, ASRConfidenceRecord] = {}
    by_dataset_consultation: dict[tuple[str, str | None], list[ASRConfidenceRecord]] = (
        defaultdict(list)
    )
    for record in records:
        if record.record_id:
            by_record_id[record.record_id] = record
        by_sample_id[record.sample_id] = record
        by_dataset_consultation[(record.dataset, record.consultation_id)].append(record)
    return {
        "records": list(records),
        "by_record_id": by_record_id,
        "by_sample_id": by_sample_id,
        "by_dataset_consultation": by_dataset_consultation,
    }


def _build_confirmed_attribution_index(
    records: Sequence[ConfirmedTranscriptRecord],
) -> dict[str, ConfirmedTranscriptRecord]:
    """Build record_id/sample_id lookup for confirmed transcript records."""

    index: dict[str, ConfirmedTranscriptRecord] = {}
    for record in records:
        if record.record_id:
            index[record.record_id] = record
        index[record.sample_id] = record
    return index


def _find_confirmed_for_asr_record(
    record: ASRConfidenceRecord,
    confirmed_index: dict[str, ConfirmedTranscriptRecord] | None,
) -> ConfirmedTranscriptRecord | None:
    if confirmed_index is None:
        return None
    if record.record_id and record.record_id in confirmed_index:
        return confirmed_index[record.record_id]
    return confirmed_index.get(record.sample_id)


def _attribute_summary_record_to_asr_and_review(
    *,
    summary_record: dict[str, Any],
    gold_facts: Sequence[GoldKeyFact],
    fact_evaluations: list[dict[str, Any]],
    omitted_gold_fact_ids: Sequence[str],
    asr_attribution_index: dict[str, Any] | None,
    confirmed_index: dict[str, ConfirmedTranscriptRecord] | None,
) -> dict[str, Any]:
    """Add T042f ASR confidence/review-cost attribution to one quality record.

    The function mutates ``fact_evaluations`` to attach safe fact-level
    attribution metadata.  It never copies transcript text, summary fact text,
    confirmed span text, or gold canonical fact text.
    """

    if asr_attribution_index is None:
        for evaluation in fact_evaluations:
            evaluation["confidence_attribution"] = _skipped_fact_confidence_attribution(
                "missing_asr_confidence_jsonl"
            )
            evaluation["summary_error_attribution"] = "not_evaluated"
        return {
            "confidence_attribution": _skipped_record_confidence_attribution(
                "missing_asr_confidence_jsonl"
            ),
            "review_cost_attribution": _skipped_review_cost_attribution(
                "missing_asr_confidence_jsonl"
            ),
        }

    source_records = _source_asr_records_for_summary_record(
        summary_record,
        asr_attribution_index,
    )
    if not source_records:
        for evaluation in fact_evaluations:
            evaluation["confidence_attribution"] = _skipped_fact_confidence_attribution(
                "no_matching_asr_source_record"
            )
            evaluation["summary_error_attribution"] = "not_evaluated"
        return {
            "confidence_attribution": _skipped_record_confidence_attribution(
                "no_matching_asr_source_record"
            ),
            "review_cost_attribution": _skipped_review_cost_attribution(
                "no_matching_asr_source_record"
            ),
        }

    facts_by_id = {fact.fact_id: fact for fact in gold_facts}
    for evaluation in fact_evaluations:
        best_gold = facts_by_id.get(str(evaluation.get("best_gold_fact_id") or ""))
        attribution = _attribute_gold_fact_evidence_to_asr(
            best_gold,
            source_records=source_records,
            confirmed_index=confirmed_index,
        )
        evaluation["confidence_attribution"] = attribution
        evaluation["summary_error_attribution"] = _classify_summary_fact_error_source(
            evaluation,
            attribution,
        )

    omitted_gold_fact_attributions = []
    for fact_id in omitted_gold_fact_ids:
        gold_fact = facts_by_id.get(fact_id)
        attribution = _attribute_gold_fact_evidence_to_asr(
            gold_fact,
            source_records=source_records,
            confirmed_index=confirmed_index,
        )
        omitted_gold_fact_attributions.append(
            {
                "gold_fact_id": fact_id,
                "evidence_attribution": attribution,
                "omission_attribution": _classify_omitted_gold_fact_source(
                    attribution
                ),
            }
        )

    return {
        "confidence_attribution": _record_confidence_attribution_summary(
            source_records=source_records,
            fact_evaluations=fact_evaluations,
            omitted_gold_fact_attributions=omitted_gold_fact_attributions,
        ),
        "review_cost_attribution": _review_cost_attribution_for_source_records(
            source_records,
            confirmed_index=confirmed_index,
        ),
    }


def _source_asr_records_for_summary_record(
    summary_record: dict[str, Any],
    asr_attribution_index: dict[str, Any],
) -> list[ASRConfidenceRecord]:
    """Find ASR source records for a T041/T042b summary record."""

    candidates: list[ASRConfidenceRecord] = []
    by_record_id: dict[str, ASRConfidenceRecord] = asr_attribution_index["by_record_id"]
    by_sample_id: dict[str, ASRConfidenceRecord] = asr_attribution_index["by_sample_id"]
    by_dataset_consultation = asr_attribution_index["by_dataset_consultation"]

    for record_id in _coerce_str_list(summary_record.get("source_record_ids")):
        record = by_record_id.get(record_id)
        if record is not None:
            candidates.append(record)
    for sample_id in _coerce_str_list(summary_record.get("source_sample_ids")):
        record = by_sample_id.get(sample_id)
        if record is not None:
            candidates.append(record)

    if not candidates:
        dataset = str(summary_record.get("dataset") or "")
        consultation_id = summary_record.get("consultation_id")
        candidates.extend(by_dataset_consultation.get((dataset, consultation_id), []))

    return _dedupe_asr_records(candidates)


def _dedupe_asr_records(records: Sequence[ASRConfidenceRecord]) -> list[ASRConfidenceRecord]:
    seen: set[str] = set()
    deduped: list[ASRConfidenceRecord] = []
    for record in records:
        key = _asr_record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _asr_record_key(record: ASRConfidenceRecord) -> str:
    return record.record_id or record.sample_id


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None and str(item).strip()]
    return []


def _attribute_gold_fact_evidence_to_asr(
    gold_fact: GoldKeyFact | None,
    *,
    source_records: Sequence[ASRConfidenceRecord],
    confirmed_index: dict[str, ConfirmedTranscriptRecord] | None,
) -> dict[str, Any]:
    """Attribute one gold fact's evidence pointer to ASR confidence/review spans."""

    if gold_fact is None:
        return _skipped_fact_confidence_attribution("missing_best_gold_fact")

    pointer = gold_fact.evidence_pointer
    asr_record, match_method = _match_evidence_pointer_to_asr_record(
        pointer,
        source_records,
    )
    base: dict[str, Any] = {
        "schema_version": "case_summary_asr_confidence_attribution/v1",
        "evaluation_status": "evaluated",
        "gold_fact_id": gold_fact.fact_id,
        "evidence_pointer": _safe_evidence_pointer_reference(pointer),
        "asr_record_match_method": match_method,
        "asr_record_id": asr_record.record_id if asr_record is not None else None,
        "sample_id": asr_record.sample_id if asr_record is not None else None,
        "source_channel": (
            asr_record.source_channel.value if asr_record is not None else None
        ),
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_gold_canonical_fact_text": False,
            "contains_summary_fact_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }
    if asr_record is None:
        return {
            **base,
            "evaluation_status": "skipped",
            "skip_reason": "no_asr_record_match_for_evidence_pointer",
            "word_alignment_method": None,
            "word_count": 0,
            "confidence_level_counts": {},
            "dominant_risk_level": None,
            "has_asr_noise_signal": False,
            "overlapping_review_span_count": 0,
            "overlapping_review_span_ids": [],
            "review_action_counts": {},
            "changed_review_span_count": 0,
            "manual_edit_count": 0,
        }

    word_indices, word_alignment_method = _evidence_word_indices(pointer, asr_record)
    words = [asr_record.asr_words[index] for index in word_indices]
    level_counts = Counter(_word_confidence_level_value(word) for word in words)
    confidence_values = [
        float(word.confidence) for word in words if word.confidence is not None
    ]
    review_spans = _overlapping_review_spans(pointer, asr_record, word_indices)
    review_actions = _review_actions_for_spans(
        review_spans,
        _find_confirmed_for_asr_record(asr_record, confirmed_index),
    )
    dominant_risk_level = _dominant_risk_level(level_counts)
    return {
        **base,
        "word_alignment_method": word_alignment_method,
        "word_start_index": min(word_indices) if word_indices else None,
        "word_end_index": (max(word_indices) + 1) if word_indices else None,
        "word_count": len(words),
        "confidence_level_counts": dict(level_counts),
        "mean_confidence": (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else None
        ),
        "min_confidence": min(confidence_values) if confidence_values else None,
        "dominant_risk_level": dominant_risk_level,
        "has_asr_noise_signal": _has_asr_noise_signal(
            dominant_risk_level,
            review_spans,
        ),
        "overlapping_review_span_count": len(review_spans),
        "overlapping_review_span_ids": [span.span_id for span in review_spans],
        "review_action_counts": review_actions["action_counts"],
        "changed_review_span_count": review_actions["changed_review_span_count"],
        "manual_edit_count": review_actions["manual_edit_count"],
        "select_alternative_count": review_actions["select_alternative_count"],
        "resolved_review_span_count": review_actions["resolved_review_span_count"],
        "unresolved_or_missing_review_span_count": review_actions[
            "unresolved_or_missing_review_span_count"
        ],
    }


def _match_evidence_pointer_to_asr_record(
    pointer: EvidencePointer,
    source_records: Sequence[ASRConfidenceRecord],
) -> tuple[ASRConfidenceRecord | None, str]:
    if pointer.record_id:
        for record in source_records:
            if record.record_id == pointer.record_id:
                return record, "evidence_pointer.record_id"
    if pointer.sample_id:
        for record in source_records:
            if record.sample_id == pointer.sample_id:
                return record, "evidence_pointer.sample_id"
    if pointer.source_channel != SourceChannel.UNKNOWN:
        channel_matches = [
            record for record in source_records if record.source_channel == pointer.source_channel
        ]
        if len(channel_matches) == 1:
            return channel_matches[0], "evidence_pointer.source_channel"
    if len(source_records) == 1:
        return source_records[0], "single_source_record"
    return None, "no_match"


def _evidence_word_indices(
    pointer: EvidencePointer,
    record: ASRConfidenceRecord,
) -> tuple[list[int], str]:
    word_count = len(record.asr_words)
    if pointer.word_start_index is not None and pointer.word_end_index is not None:
        start = pointer.word_start_index
        end = pointer.word_end_index
        if start < word_count and end <= word_count:
            return list(range(start, end)), "word_index_range"
        if pointer.start_sec is None or pointer.end_sec is None:
            return [], "word_index_range_out_of_bounds"

    if pointer.start_sec is not None and pointer.end_sec is not None:
        indices = [
            word.word_index
            for word in record.asr_words
            if _word_overlaps_time(word, pointer.start_sec, pointer.end_sec)
        ]
        return indices, "time_overlap" if indices else "time_overlap_no_words"

    return [], "missing_word_or_time_pointer"


def _word_overlaps_time(word: ASRWord, start_sec: float, end_sec: float) -> bool:
    if word.start_sec is None or word.end_sec is None:
        return False
    return word.end_sec >= start_sec and word.start_sec <= end_sec


def _overlapping_review_spans(
    pointer: EvidencePointer,
    record: ASRConfidenceRecord,
    word_indices: Sequence[int],
) -> list[UncertainSpan]:
    if word_indices:
        start = min(word_indices)
        end = max(word_indices) + 1
        return [
            span
            for span in record.uncertain_spans
            if _ranges_overlap(start, end, span.start_word_index, span.end_word_index)
        ]
    if pointer.start_sec is not None and pointer.end_sec is not None:
        return [
            span
            for span in record.uncertain_spans
            if span.start_sec is not None
            and span.end_sec is not None
            and span.end_sec >= pointer.start_sec
            and span.start_sec <= pointer.end_sec
        ]
    return []


def _ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _word_confidence_level_value(word: ASRWord) -> str:
    review_metadata = word.metadata.get("medical_entity_review")
    if isinstance(review_metadata, dict):
        display_level = review_metadata.get("display_confidence_level")
        if display_level:
            return str(display_level)
    return word.confidence_level.value


def _dominant_risk_level(level_counts: Counter[str]) -> str | None:
    for level in (
        ConfidenceLevel.RED.value,
        ConfidenceLevel.YELLOW.value,
        ConfidenceLevel.UNKNOWN.value,
        ConfidenceLevel.GREEN.value,
    ):
        if level_counts.get(level):
            return level
    return None


def _has_asr_noise_signal(
    dominant_risk_level: str | None,
    review_spans: Sequence[UncertainSpan],
) -> bool:
    return bool(
        dominant_risk_level
        in {
            ConfidenceLevel.RED.value,
            ConfidenceLevel.YELLOW.value,
            ConfidenceLevel.UNKNOWN.value,
        }
        or review_spans
    )


def _review_actions_for_spans(
    review_spans: Sequence[UncertainSpan],
    confirmed_record: ConfirmedTranscriptRecord | None,
) -> dict[str, Any]:
    action_counts: Counter[str] = Counter()
    changed_count = 0
    resolved_count = 0
    unresolved_or_missing_count = 0
    if confirmed_record is None:
        if review_spans:
            action_counts["missing_confirmed_transcript"] = len(review_spans)
            unresolved_or_missing_count = len(review_spans)
        return {
            "action_counts": dict(action_counts),
            "changed_review_span_count": changed_count,
            "manual_edit_count": 0,
            "select_alternative_count": 0,
            "resolved_review_span_count": resolved_count,
            "unresolved_or_missing_review_span_count": unresolved_or_missing_count,
        }

    applied_by_id = {span.span_id: span for span in confirmed_record.applied_spans}
    for review_span in review_spans:
        applied = applied_by_id.get(review_span.span_id)
        if applied is None or applied.action is None:
            action_counts["missing_feedback"] += 1
            unresolved_or_missing_count += 1
            continue
        action = applied.action.value
        action_counts[action] += 1
        if applied.resolved:
            resolved_count += 1
        else:
            unresolved_or_missing_count += 1
        if applied.confirmed_text.strip() != applied.original_text.strip():
            changed_count += 1
    return {
        "action_counts": dict(action_counts),
        "changed_review_span_count": changed_count,
        "manual_edit_count": action_counts.get("manual_edit", 0),
        "select_alternative_count": action_counts.get("select_alternative", 0),
        "resolved_review_span_count": resolved_count,
        "unresolved_or_missing_review_span_count": unresolved_or_missing_count,
    }


def _safe_evidence_pointer_reference(pointer: EvidencePointer) -> dict[str, Any]:
    """Return location-only evidence metadata; do not copy the cue text."""

    return {
        "source_type": pointer.source_type,
        "sample_id": pointer.sample_id,
        "record_id": pointer.record_id,
        "source_channel": pointer.source_channel.value,
        "turn_index": pointer.turn_index,
        "word_start_index": pointer.word_start_index,
        "word_end_index": pointer.word_end_index,
        "start_sec": pointer.start_sec,
        "end_sec": pointer.end_sec,
        "cue_sha256_16": _short_sha256(pointer.cue) if pointer.cue else None,
        "contains_full_transcript_text": False,
    }


def _classify_summary_fact_error_source(
    evaluation: dict[str, Any],
    attribution: dict[str, Any],
) -> str:
    label = evaluation.get("factuality_label")
    if label == SummaryFactFactuality.SUPPORTED.value:
        return "supported_by_gold"
    if attribution.get("evaluation_status") != "evaluated":
        if label == SummaryFactFactuality.UNVERIFIABLE.value:
            return "model_hallucination_possible_no_gold"
        return "not_attributed_to_asr"
    if attribution.get("changed_review_span_count", 0) > 0:
        return "review_modified_evidence_span"
    if attribution.get("has_asr_noise_signal"):
        return "asr_induced_possible"
    if label == SummaryFactFactuality.CONTRADICTED.value:
        return "summary_generation_polarity_error_possible"
    return "model_hallucination_possible"


def _classify_omitted_gold_fact_source(attribution: dict[str, Any]) -> str:
    if attribution.get("evaluation_status") != "evaluated":
        return "not_attributed_to_asr"
    if attribution.get("changed_review_span_count", 0) > 0:
        return "review_modified_evidence_span"
    if attribution.get("has_asr_noise_signal"):
        return "asr_induced_omission_possible"
    return "summary_generation_omission_possible"


def _record_confidence_attribution_summary(
    *,
    source_records: Sequence[ASRConfidenceRecord],
    fact_evaluations: Sequence[dict[str, Any]],
    omitted_gold_fact_attributions: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    level_counts: Counter[str] = Counter()
    dominant_level_counts: Counter[str] = Counter()
    match_status_counts: Counter[str] = Counter()
    summary_error_attribution_counts: Counter[str] = Counter()
    omitted_attribution_counts: Counter[str] = Counter()
    overlapping_review_span_count = 0
    changed_review_span_count = 0
    for evaluation in fact_evaluations:
        attribution = evaluation.get("confidence_attribution") or {}
        match_status_counts[str(attribution.get("evaluation_status") or "unknown")] += 1
        level_counts.update(attribution.get("confidence_level_counts") or {})
        dominant_level = attribution.get("dominant_risk_level")
        if dominant_level:
            dominant_level_counts[str(dominant_level)] += 1
        summary_error_attribution_counts[
            str(evaluation.get("summary_error_attribution") or "unknown")
        ] += 1
        overlapping_review_span_count += int(
            attribution.get("overlapping_review_span_count") or 0
        )
        changed_review_span_count += int(
            attribution.get("changed_review_span_count") or 0
        )

    for item in omitted_gold_fact_attributions:
        omitted_attribution_counts[str(item.get("omission_attribution") or "unknown")] += 1

    return {
        "evaluation_status": "evaluated",
        "source_record_count": len(source_records),
        "source_record_ids": [record.record_id for record in source_records],
        "source_sample_ids": [record.sample_id for record in source_records],
        "fact_evaluation_count": len(fact_evaluations),
        "fact_evidence_match_status_counts": dict(match_status_counts),
        "fact_evidence_confidence_level_counts": dict(level_counts),
        "fact_evidence_dominant_risk_level_counts": dict(dominant_level_counts),
        "summary_error_attribution_counts": dict(summary_error_attribution_counts),
        "overlapping_review_span_count": overlapping_review_span_count,
        "changed_review_span_count": changed_review_span_count,
        "omitted_gold_fact_count": len(omitted_gold_fact_attributions),
        "omission_attribution_counts": dict(omitted_attribution_counts),
        "omitted_gold_fact_attributions": list(omitted_gold_fact_attributions),
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_gold_canonical_fact_text": False,
            "contains_summary_fact_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }


def _review_cost_attribution_for_source_records(
    source_records: Sequence[ASRConfidenceRecord],
    *,
    confirmed_index: dict[str, ConfirmedTranscriptRecord] | None,
) -> dict[str, Any]:
    action_summary: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    status_summary: Counter[str] = Counter()
    text_changed_record_count = 0

    for record in source_records:
        totals["review_span_count"] += len(record.uncertain_spans)
        confirmed = _find_confirmed_for_asr_record(record, confirmed_index)
        if confirmed is None:
            totals["missing_confirmed_record_count"] += 1
            continue
        totals["confirmed_record_count"] += 1
        status_summary[confirmed.confirmation_status.value] += 1
        action_summary.update(confirmed.action_summary)
        totals["applied_span_count"] += len(confirmed.applied_spans)
        totals["resolved_span_count"] += sum(1 for span in confirmed.applied_spans if span.resolved)
        totals["missing_feedback_span_count"] += len(confirmed.missing_feedback_span_ids)
        totals["unresolved_span_count"] += len(confirmed.unresolved_span_ids)
        changed_spans = [
            span
            for span in confirmed.applied_spans
            if span.confirmed_text.strip() != span.original_text.strip()
        ]
        totals["changed_span_count"] += len(changed_spans)
        if confirmed.confirmed_transcript.strip() != confirmed.asr_transcript.strip():
            text_changed_record_count += 1

    status = (
        "evaluated"
        if confirmed_index is not None
        else "evaluated_without_confirmed_transcripts"
    )
    return {
        "evaluation_status": status,
        "source_record_count": len(source_records),
        "source_record_ids": [record.record_id for record in source_records],
        "source_sample_ids": [record.sample_id for record in source_records],
        "confirmed_record_count": totals["confirmed_record_count"],
        "missing_confirmed_record_count": totals["missing_confirmed_record_count"],
        "review_span_count": totals["review_span_count"],
        "applied_span_count": totals["applied_span_count"],
        "resolved_span_count": totals["resolved_span_count"],
        "missing_feedback_span_count": totals["missing_feedback_span_count"],
        "unresolved_span_count": totals["unresolved_span_count"],
        "changed_span_count": totals["changed_span_count"],
        "records_with_text_changes": text_changed_record_count,
        "action_summary": dict(action_summary),
        "confirmation_status": dict(status_summary),
        "resolved_span_rate": _safe_ratio(
            totals["resolved_span_count"],
            totals["review_span_count"],
        ),
        "changed_span_rate": _safe_ratio(
            totals["changed_span_count"],
            totals["review_span_count"],
        ),
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }


def _skipped_fact_confidence_attribution(skip_reason: str) -> dict[str, Any]:
    return {
        "schema_version": "case_summary_asr_confidence_attribution/v1",
        "evaluation_status": "skipped",
        "skip_reason": skip_reason,
        "confidence_level_counts": {},
        "dominant_risk_level": None,
        "has_asr_noise_signal": False,
        "overlapping_review_span_count": 0,
        "overlapping_review_span_ids": [],
        "review_action_counts": {},
        "changed_review_span_count": 0,
        "manual_edit_count": 0,
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_gold_canonical_fact_text": False,
            "contains_summary_fact_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }


def _skipped_record_confidence_attribution(skip_reason: str) -> dict[str, Any]:
    return {
        "evaluation_status": "skipped",
        "skip_reason": skip_reason,
        "source_record_count": 0,
        "fact_evaluation_count": 0,
        "fact_evidence_match_status_counts": {},
        "fact_evidence_confidence_level_counts": {},
        "fact_evidence_dominant_risk_level_counts": {},
        "summary_error_attribution_counts": {},
        "overlapping_review_span_count": 0,
        "changed_review_span_count": 0,
        "omitted_gold_fact_count": 0,
        "omission_attribution_counts": {},
        "omitted_gold_fact_attributions": [],
    }


def _skipped_review_cost_attribution(skip_reason: str) -> dict[str, Any]:
    return {
        "evaluation_status": "skipped",
        "skip_reason": skip_reason,
        "source_record_count": 0,
        "source_record_ids": [],
        "source_sample_ids": [],
        "confirmed_record_count": 0,
        "missing_confirmed_record_count": 0,
        "review_span_count": 0,
        "applied_span_count": 0,
        "resolved_span_count": 0,
        "missing_feedback_span_count": 0,
        "unresolved_span_count": 0,
        "changed_span_count": 0,
        "records_with_text_changes": 0,
        "action_summary": {},
        "confirmation_status": {},
        "resolved_span_rate": None,
        "changed_span_rate": None,
    }


def write_json(record: dict[str, Any], path: str | Path) -> None:
    """Write JSON with UTF-8 encoding."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


_NEGATION_MARKERS = (
    "否认",
    "无",
    "未见",
    "未",
    "没有",
    "沒",
    "denies",
    "deny",
    "denied",
    "no ",
    "not ",
    "without",
    "negative for",
)
_UNCERTAINTY_MARKERS = (
    "可能",
    "疑似",
    "不确定",
    "不清楚",
    "待查",
    "uncertain",
    "possible",
    "possibly",
    "suspected",
    "questionable",
)
_HISTORICAL_MARKERS = (
    "既往",
    "曾",
    "过去",
    "history of",
    "previous",
    "previously",
)
_PLANNED_MARKERS = (
    "计划",
    "建议",
    "随访",
    "复查",
    "planned",
    "plan",
    "follow up",
    "follow-up",
    "recommend",
)
_DOSE_OR_ROUTE_MARKERS = (
    "mg",
    "mcg",
    "ml",
    "tablet",
    "tab",
    "capsule",
    "cap",
    "dose",
    "daily",
    "bid",
    "tid",
    "qid",
    "po",
    "iv",
    "im",
    "口服",
    "静脉",
    "肌注",
    "片",
    "粒",
    "毫克",
    "毫升",
    "每日",
    "每天",
    "一日",
)
_UNCERTAINTY_NOTE_CATEGORY_MARKERS: dict[str, tuple[str, ...]] = {
    "asr_confidence_or_noise": (
        "asr",
        "audio",
        "noise",
        "noisy",
        "transcript",
        "confidence",
        "low confidence",
        "recognition",
        "转写",
        "听写",
        "识别",
        "置信",
        "低置信",
        "噪声",
        "听不清",
        "录音",
    ),
    "insufficient_evidence": (
        "evidence",
        "unsupported",
        "unverifiable",
        "insufficient",
        "cannot verify",
        "证据",
        "不足",
        "无法确认",
        "无法判断",
        "未确认",
        "不支持",
        "不可验证",
    ),
    SummaryHighRiskTag.NEGATION_OR_POLARITY.value: (
        "negation",
        "polarity",
        "negative",
        "denies",
        "deny",
        "否认",
        "否定",
        "极性",
        "没有",
        "无",
        "未",
    ),
    SummaryHighRiskTag.DRUG_NAME.value: (
        "drug",
        "medication",
        "medicine",
        "药",
        "药名",
        "用药",
    ),
    SummaryHighRiskTag.MEDICATION_DOSE_OR_ROUTE.value: (
        "dose",
        "route",
        "dosage",
        "剂量",
        "给药",
        "途径",
        "用法",
    ),
    SummaryHighRiskTag.TEST_OR_EXAM.value: (
        "test",
        "exam",
        "investigation",
        "检查",
        "检验",
        "化验",
    ),
    SummaryHighRiskTag.PLAN_OR_FOLLOW_UP.value: (
        "plan",
        "follow up",
        "follow-up",
        "计划",
        "随访",
        "复查",
    ),
    SummaryHighRiskTag.SPEAKER_ATTRIBUTION.value: (
        "speaker",
        "doctor",
        "patient",
        "说话人",
        "医生",
        "患者",
        "归属",
    ),
    SummaryHighRiskTag.ASSESSMENT_OR_DIAGNOSIS.value: (
        "assessment",
        "diagnosis",
        "诊断",
        "判断",
        "评估",
    ),
    SummaryHighRiskTag.UNCERTAINTY.value: _UNCERTAINTY_MARKERS
    + (
        "unclear",
        "ambiguous",
        "不明确",
        "不稳定",
    ),
    "safety_critical_fact": (
        "safety",
        "critical",
        "risk",
        "安全",
        "高风险",
        "关键",
    ),
}


def _short_fact_label(text: str) -> str:
    one_line = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if len(one_line) <= MAX_FACT_LABEL_CHARS:
        return one_line
    return one_line[: MAX_FACT_LABEL_CHARS - 1].rstrip() + "…"


def _dedupe_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def _coerce_non_negative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _contains_dose_or_route_marker(text: str) -> bool:
    normalized = _normalize_for_matching(text)
    if any(char.isdigit() for char in normalized):
        return True
    return any(marker in normalized for marker in _DOSE_OR_ROUTE_MARKERS)


def _uncertainty_note_categories(text: str) -> list[str]:
    normalized = _normalize_for_matching(text)
    categories = [
        category
        for category, markers in _UNCERTAINTY_NOTE_CATEGORY_MARKERS.items()
        if any(marker in normalized for marker in markers)
    ]
    return _dedupe_sorted(categories)


def _normalize_for_matching(text: str) -> str:
    normalized_chars: list[str] = []
    previous_was_space = False
    for char in unicodedata.normalize("NFKC", text).casefold():
        category = unicodedata.category(char)
        if category.startswith("P") or category.startswith("S"):
            if not previous_was_space:
                normalized_chars.append(" ")
                previous_was_space = True
            continue
        if char.isspace():
            if not previous_was_space:
                normalized_chars.append(" ")
                previous_was_space = True
            continue
        normalized_chars.append(char)
        previous_was_space = False
    return "".join(normalized_chars).strip()


def _tokenize_for_rouge(text: str) -> list[str]:
    tokens: list[str] = []
    current_word: list[str] = []

    def flush_word() -> None:
        if current_word:
            tokens.append("".join(current_word))
            current_word.clear()

    for char in unicodedata.normalize("NFKC", text).casefold():
        if _is_cjk(char):
            flush_word()
            tokens.append(char)
        elif char.isalnum():
            current_word.append(char)
        else:
            flush_word()
    flush_word()
    return tokens


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
    )


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    if len(left) < len(right):
        shorter, longer = left, right
    else:
        shorter, longer = right, left
    previous = [0] * (len(shorter) + 1)
    for token in longer:
        current = [0] * (len(shorter) + 1)
        for index, other_token in enumerate(shorter, start=1):
            if token == other_token:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current
    return previous[-1]


def _safe_f1(precision: float, recall: float) -> float:
    denominator = precision + recall
    if denominator == 0:
        return 0.0
    return 2 * precision * recall / denominator


def _safe_f1_or_none(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return _safe_f1(precision, recall)


def _normalized_term_coverage(text: str, normalized_terms: Sequence[str]) -> float:
    terms = [_normalize_for_matching(term) for term in normalized_terms if term.strip()]
    if not terms:
        return 0.0
    normalized_text = _normalize_for_matching(text)
    covered = 0
    for term in terms:
        if term and term in normalized_text:
            covered += 1
    return covered / len(terms)


def _polarity_is_compatible(
    summary_polarity: SummaryFactPolarity,
    gold_polarity: GoldFactPolarity,
) -> bool:
    if summary_polarity == SummaryFactPolarity.UNCERTAIN:
        return gold_polarity == GoldFactPolarity.UNCERTAIN
    if summary_polarity == SummaryFactPolarity.ABSENT:
        return gold_polarity == GoldFactPolarity.ABSENT
    if gold_polarity == GoldFactPolarity.ABSENT:
        return summary_polarity == SummaryFactPolarity.ABSENT
    if gold_polarity == GoldFactPolarity.PLANNED:
        return summary_polarity in {
            SummaryFactPolarity.PLANNED,
            SummaryFactPolarity.PRESENT,
        }
    if gold_polarity == GoldFactPolarity.HISTORICAL:
        return summary_polarity in {
            SummaryFactPolarity.HISTORICAL,
            SummaryFactPolarity.PRESENT,
        }
    return summary_polarity in {
        SummaryFactPolarity.PRESENT,
        SummaryFactPolarity.HISTORICAL,
        SummaryFactPolarity.PLANNED,
    }


def _evaluate_one_summary_fact(
    summary_fact: ExtractedSummaryFact,
    *,
    summary_record: dict[str, Any],
    gold_facts: Sequence[GoldKeyFact],
    support_threshold: float,
    contradiction_threshold: float,
    include_fact_text: bool,
) -> dict[str, Any]:
    best_gold: GoldKeyFact | None = None
    best_score: dict[str, Any] | None = None
    for gold_fact in gold_facts:
        score = score_summary_fact_against_gold(summary_fact, gold_fact)
        if best_score is None or score["match_score"] > best_score["match_score"]:
            best_gold = gold_fact
            best_score = score

    if best_gold is None or best_score is None:
        label = SummaryFactFactuality.UNVERIFIABLE
        reason = "no_gold_facts_for_record"
    elif (
        best_score["match_score"] >= support_threshold
        and best_score["polarity_compatible"]
    ):
        label = SummaryFactFactuality.SUPPORTED
        reason = "matched_gold_fact"
    elif (
        best_score["match_score"] >= contradiction_threshold
        and not best_score["polarity_compatible"]
    ):
        label = SummaryFactFactuality.CONTRADICTED
        reason = "matched_gold_fact_with_polarity_conflict"
    else:
        label = SummaryFactFactuality.UNSUPPORTED
        reason = "no_sufficient_gold_match"

    high_risk_error_types = _high_risk_error_types_for_summary_fact_evaluation(
        summary_fact,
        factuality_label=label,
        best_gold_fact=best_gold,
    )
    bundle_id = str(summary_record.get("bundle_id") or "")
    summary_fact_id = (
        f"{bundle_id}__{summary_fact.field.value}__{summary_fact.fact_index:03d}"
    )
    record: dict[str, Any] = {
        "schema_version": CASE_SUMMARY_FACT_EVALUATION_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_EVALUATION_TASK_ID,
        "t042_subtask": "T042d_source_aware_factuality_b_lite",
        "bundle_id": bundle_id,
        "dataset": summary_record.get("dataset"),
        "split": summary_record.get("split"),
        "consultation_id": summary_record.get("consultation_id"),
        "input_unit": summary_record.get("input_unit"),
        "input_variant": summary_record.get("input_variant"),
        "summary_fact_id": summary_fact_id,
        "summary_fact_index": summary_fact.fact_index,
        "summary_fact_field": summary_fact.field.value,
        "summary_fact_text_sha256_16": _short_sha256(summary_fact.text),
        "summary_fact_inferred_polarity": summary_fact.inferred_polarity.value,
        "factuality_label": label.value,
        "reason": reason,
        "best_gold_fact_id": best_gold.fact_id if best_gold is not None else None,
        "best_gold_field": best_gold.field.value if best_gold is not None else None,
        "best_gold_polarity": best_gold.polarity.value if best_gold is not None else None,
        "best_gold_severity": best_gold.severity.value if best_gold is not None else None,
        "best_gold_error_tags": (
            [tag.value for tag in best_gold.error_tags] if best_gold is not None else []
        ),
        "best_match_score": best_score["match_score"] if best_score is not None else None,
        "best_match_rouge_l": best_score["rouge_l"] if best_score is not None else None,
        "best_match_term_coverage": (
            best_score["term_coverage"] if best_score is not None else None
        ),
        "field_matches_best_gold": (
            best_score["field_matches"] if best_score is not None else None
        ),
        "polarity_compatible_with_best_gold": (
            best_score["polarity_compatible"] if best_score is not None else None
        ),
        "is_high_risk_error": bool(high_risk_error_types),
        "high_risk_error_types": high_risk_error_types,
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
        "privacy_and_safety": _quality_privacy_flags(
            include_fact_text=include_fact_text,
        ),
    }
    if include_fact_text:
        record["summary_fact_text"] = summary_fact.text
    return record


def _short_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _recovered_gold_fact_ids(
    summary_facts: Sequence[ExtractedSummaryFact],
    gold_facts: Sequence[GoldKeyFact],
    *,
    support_threshold: float,
) -> set[str]:
    recovered: set[str] = set()
    for gold_fact in gold_facts:
        for summary_fact in summary_facts:
            score = score_summary_fact_against_gold(summary_fact, gold_fact)
            if score["match_score"] >= support_threshold and score["polarity_compatible"]:
                recovered.add(gold_fact.fact_id)
                break
    return recovered


def _flatten_gold_facts(gold_facts: Sequence[GoldKeyFact]) -> str:
    return " ".join(fact.canonical_fact for fact in gold_facts)


def _flatten_summary_facts(summary_facts: Sequence[ExtractedSummaryFact]) -> str:
    return " ".join(fact.text for fact in summary_facts)


def _high_risk_error_counts(
    fact_evaluations: Sequence[dict[str, Any]],
    gold_facts: Sequence[GoldKeyFact],
    *,
    omitted_gold_fact_ids: Sequence[str],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    error_labels = {
        SummaryFactFactuality.UNSUPPORTED.value,
        SummaryFactFactuality.CONTRADICTED.value,
    }
    for evaluation in fact_evaluations:
        if evaluation["factuality_label"] not in error_labels:
            continue
        tags = evaluation.get("best_gold_error_tags") or []
        if tags:
            counts.update(tags)
        else:
            counts["unsupported_without_gold_tag"] += 1
    facts_by_id = {fact.fact_id: fact for fact in gold_facts}
    for fact_id in omitted_gold_fact_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            continue
        tags = [tag.value for tag in fact.error_tags]
        if tags:
            counts.update(f"omitted_{tag}" for tag in tags)
        else:
            counts["omitted_without_gold_tag"] += 1
    return dict(counts)


def _high_risk_error_types_for_summary_fact_evaluation(
    summary_fact: ExtractedSummaryFact,
    *,
    factuality_label: SummaryFactFactuality,
    best_gold_fact: GoldKeyFact | None,
) -> list[str]:
    """Infer T042e high-risk error families for one summary-fact evaluation."""

    if factuality_label == SummaryFactFactuality.SUPPORTED:
        return []

    error_types: list[str] = []
    if factuality_label == SummaryFactFactuality.CONTRADICTED:
        error_types.append(SummaryHighRiskTag.NEGATION_OR_POLARITY.value)
    if factuality_label == SummaryFactFactuality.UNVERIFIABLE:
        error_types.append("unverifiable_fact")

    error_types.extend(_high_risk_types_for_summary_fact(summary_fact))
    if best_gold_fact is not None:
        error_types.extend(_high_risk_types_for_gold_fact(best_gold_fact))

    if not error_types and factuality_label == SummaryFactFactuality.UNSUPPORTED:
        error_types.append("unsupported_without_gold_tag")
    return _dedupe_sorted(error_types)


def _high_risk_types_for_summary_fact(summary_fact: ExtractedSummaryFact) -> list[str]:
    """Infer risk families from the generated summary fact field/text."""

    error_types: list[str] = []
    if (
        summary_fact.field == CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS
        or summary_fact.inferred_polarity == SummaryFactPolarity.ABSENT
    ):
        error_types.append(SummaryHighRiskTag.NEGATION_OR_POLARITY.value)
    if summary_fact.inferred_polarity == SummaryFactPolarity.UNCERTAIN:
        error_types.append(SummaryHighRiskTag.UNCERTAINTY.value)

    if summary_fact.field == CaseSummaryFactField.MEDICATIONS:
        error_types.append(SummaryHighRiskTag.DRUG_NAME.value)
        if _contains_dose_or_route_marker(summary_fact.text):
            error_types.append(SummaryHighRiskTag.MEDICATION_DOSE_OR_ROUTE.value)
    elif summary_fact.field == CaseSummaryFactField.TESTS_OR_EXAM_MENTIONED:
        error_types.append(SummaryHighRiskTag.TEST_OR_EXAM.value)
    elif summary_fact.field == CaseSummaryFactField.PLAN_MENTIONED:
        error_types.append(SummaryHighRiskTag.PLAN_OR_FOLLOW_UP.value)
    elif summary_fact.field == CaseSummaryFactField.ASSESSMENT_MENTIONED:
        error_types.append(SummaryHighRiskTag.ASSESSMENT_OR_DIAGNOSIS.value)
    elif summary_fact.field in {
        CaseSummaryFactField.CHIEF_COMPLAINT,
        CaseSummaryFactField.HISTORY_OF_PRESENT_ILLNESS,
        CaseSummaryFactField.SYMPTOMS,
        CaseSummaryFactField.RELEVANT_HISTORY,
    }:
        error_types.append(SummaryHighRiskTag.MEDICAL_TERM.value)
    return _dedupe_sorted(error_types)


def _high_risk_types_for_gold_fact(gold_fact: GoldKeyFact) -> list[str]:
    """Infer risk families from gold-fact metadata and field semantics."""

    error_types = [tag.value for tag in gold_fact.error_tags]
    if gold_fact.severity == GoldFactSeverity.SAFETY_CRITICAL:
        error_types.append("safety_critical_fact")
    if (
        gold_fact.field == CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS
        or gold_fact.polarity == GoldFactPolarity.ABSENT
    ):
        error_types.append(SummaryHighRiskTag.NEGATION_OR_POLARITY.value)
    if gold_fact.polarity == GoldFactPolarity.UNCERTAIN:
        error_types.append(SummaryHighRiskTag.UNCERTAINTY.value)
    if gold_fact.field == CaseSummaryFactField.MEDICATIONS:
        error_types.append(SummaryHighRiskTag.DRUG_NAME.value)
    elif gold_fact.field == CaseSummaryFactField.TESTS_OR_EXAM_MENTIONED:
        error_types.append(SummaryHighRiskTag.TEST_OR_EXAM.value)
    elif gold_fact.field == CaseSummaryFactField.PLAN_MENTIONED:
        error_types.append(SummaryHighRiskTag.PLAN_OR_FOLLOW_UP.value)
    elif gold_fact.field == CaseSummaryFactField.ASSESSMENT_MENTIONED:
        error_types.append(SummaryHighRiskTag.ASSESSMENT_OR_DIAGNOSIS.value)
    elif gold_fact.field in {
        CaseSummaryFactField.CHIEF_COMPLAINT,
        CaseSummaryFactField.HISTORY_OF_PRESENT_ILLNESS,
        CaseSummaryFactField.SYMPTOMS,
        CaseSummaryFactField.RELEVANT_HISTORY,
    }:
        error_types.append(SummaryHighRiskTag.MEDICAL_TERM.value)
    return _dedupe_sorted(error_types)


def _high_risk_error_type_counts(
    fact_evaluations: Sequence[dict[str, Any]],
    gold_facts: Sequence[GoldKeyFact],
    *,
    omitted_gold_fact_ids: Sequence[str],
) -> dict[str, int]:
    """Count T042e high-risk error families without outputting fact text."""

    counts: Counter[str] = Counter()
    for evaluation in fact_evaluations:
        if evaluation.get("is_high_risk_error"):
            counts.update(evaluation.get("high_risk_error_types") or [])

    facts_by_id = {fact.fact_id: fact for fact in gold_facts}
    for fact_id in omitted_gold_fact_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            continue
        types = _high_risk_types_for_gold_fact(fact)
        if types:
            counts.update(f"omitted_{error_type}" for error_type in types)
        else:
            counts["omitted_without_high_risk_type"] += 1
    return dict(counts)


def _evaluate_uncertainty_notes(
    case_summary: CaseSummary,
    *,
    summary_record: dict[str, Any],
    fact_evaluations: Sequence[dict[str, Any]],
    gold_facts: Sequence[GoldKeyFact],
    omitted_gold_fact_ids: Sequence[str],
    high_risk_error_type_counts: dict[str, int],
) -> dict[str, Any]:
    """Evaluate whether uncertainty notes cover noisy/evidence-risk signals."""

    notes = [
        _short_fact_label(note)
        for note in case_summary.uncertainty_notes
        if str(note).strip()
    ]
    note_category_counts: Counter[str] = Counter()
    for note in notes:
        note_category_counts.update(_uncertainty_note_categories(note))
    note_category_set = set(note_category_counts)

    factuality_counts = Counter(
        evaluation.get("factuality_label") for evaluation in fact_evaluations
    )
    uncertain_span_count = _coerce_non_negative_int(
        summary_record.get("uncertain_span_count")
    )
    input_variant = str(summary_record.get("input_variant") or "")
    facts_by_id = {fact.fact_id: fact for fact in gold_facts}
    omitted_gold_facts = [
        facts_by_id[fact_id]
        for fact_id in omitted_gold_fact_ids
        if fact_id in facts_by_id
    ]
    omitted_safety_critical = [
        fact
        for fact in omitted_gold_facts
        if fact.severity == GoldFactSeverity.SAFETY_CRITICAL
    ]
    omitted_high_risk = [
        fact for fact in omitted_gold_facts if _high_risk_types_for_gold_fact(fact)
    ]

    expected_reasons: list[dict[str, Any]] = []

    def add_reason(
        reason: str,
        count: int,
        expected_categories: Sequence[str],
    ) -> None:
        if count <= 0:
            return
        categories = _dedupe_sorted(expected_categories)
        matched_categories = sorted(set(categories) & note_category_set)
        expected_reasons.append(
            {
                "reason": reason,
                "count": count,
                "expected_note_categories": categories,
                "covered_loose": bool(notes),
                "covered_by_category": bool(matched_categories),
                "matched_note_categories": matched_categories,
            }
        )

    if input_variant == INPUT_VARIANT_NOISY_ASR:
        add_reason(
            "noisy_asr_uncertain_spans",
            uncertain_span_count,
            ("asr_confidence_or_noise", SummaryHighRiskTag.UNCERTAINTY.value),
        )
    add_reason(
        "unsupported_summary_facts",
        factuality_counts[SummaryFactFactuality.UNSUPPORTED.value],
        ("insufficient_evidence", SummaryHighRiskTag.UNCERTAINTY.value),
    )
    add_reason(
        "contradicted_or_polarity_conflict",
        factuality_counts[SummaryFactFactuality.CONTRADICTED.value],
        (
            SummaryHighRiskTag.NEGATION_OR_POLARITY.value,
            SummaryHighRiskTag.UNCERTAINTY.value,
        ),
    )
    add_reason(
        "unverifiable_summary_facts",
        factuality_counts[SummaryFactFactuality.UNVERIFIABLE.value],
        ("insufficient_evidence", SummaryHighRiskTag.UNCERTAINTY.value),
    )
    add_reason(
        "omitted_safety_critical_gold_facts",
        len(omitted_safety_critical),
        ("safety_critical_fact", SummaryHighRiskTag.UNCERTAINTY.value),
    )
    omitted_high_risk_categories: list[str] = []
    for fact in omitted_high_risk:
        omitted_high_risk_categories.extend(_high_risk_types_for_gold_fact(fact))
    add_reason(
        "omitted_high_risk_gold_facts",
        len(omitted_high_risk),
        omitted_high_risk_categories
        or ("insufficient_evidence", SummaryHighRiskTag.UNCERTAINTY.value),
    )

    high_risk_error_total = sum(high_risk_error_type_counts.values())
    if high_risk_error_total and not expected_reasons:
        add_reason(
            "high_risk_summary_fact_errors",
            high_risk_error_total,
            tuple(high_risk_error_type_counts) + (SummaryHighRiskTag.UNCERTAINTY.value,),
        )

    missing_loose = [
        reason["reason"]
        for reason in expected_reasons
        if not reason["covered_loose"]
    ]
    missing_by_category = [
        reason["reason"]
        for reason in expected_reasons
        if not reason["covered_by_category"]
    ]
    if not expected_reasons:
        coverage_status = "not_required"
    elif not notes:
        coverage_status = "missing"
    elif not missing_by_category:
        coverage_status = "covered_by_category"
    else:
        coverage_status = "generic_note_present"

    return {
        "evaluation_status": "evaluated",
        "requires_uncertainty_notes": bool(expected_reasons),
        "coverage_status": coverage_status,
        "note_count": len(notes),
        "has_uncertainty_notes": bool(notes),
        "note_category_counts": dict(note_category_counts),
        "uncertain_span_count": uncertain_span_count,
        "expected_uncertainty_reason_count": len(expected_reasons),
        "expected_uncertainty_reasons": expected_reasons,
        "missing_reason_count_loose": len(missing_loose),
        "missing_reasons_loose": missing_loose,
        "missing_reason_count_category": len(missing_by_category),
        "missing_reasons_category": missing_by_category,
        "privacy_and_safety": {
            "contains_uncertainty_note_text": False,
            "contains_full_transcript_text": False,
            "research_use_only": True,
        },
    }


def _aggregate_uncertainty_note_evaluations(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate record-level T042e uncertainty-note coverage checks."""

    evaluations = [
        record.get("uncertainty_note_evaluation")
        for record in records
        if isinstance(record.get("uncertainty_note_evaluation"), dict)
        and record["uncertainty_note_evaluation"].get("evaluation_status") == "evaluated"
    ]
    required = [
        evaluation
        for evaluation in evaluations
        if evaluation.get("requires_uncertainty_notes")
    ]
    expected_reason_counts: Counter[str] = Counter()
    missing_reason_counts_loose: Counter[str] = Counter()
    missing_reason_counts_category: Counter[str] = Counter()
    note_category_counts: Counter[str] = Counter()
    for evaluation in evaluations:
        note_category_counts.update(evaluation.get("note_category_counts") or {})
        for reason in evaluation.get("expected_uncertainty_reasons") or []:
            reason_name = str(reason.get("reason") or "unknown")
            count = int(reason.get("count") or 0)
            expected_reason_counts[reason_name] += count
            if not reason.get("covered_loose"):
                missing_reason_counts_loose[reason_name] += count
            if not reason.get("covered_by_category"):
                missing_reason_counts_category[reason_name] += count

    loose_covered_records = [
        evaluation
        for evaluation in required
        if not evaluation.get("missing_reason_count_loose")
    ]
    category_covered_records = [
        evaluation
        for evaluation in required
        if not evaluation.get("missing_reason_count_category")
    ]
    missing_records = [
        evaluation
        for evaluation in required
        if evaluation.get("coverage_status") == "missing"
    ]
    generic_note_records = [
        evaluation
        for evaluation in required
        if evaluation.get("coverage_status") == "generic_note_present"
    ]
    required_count = len(required)
    return {
        "evaluated_record_count": len(evaluations),
        "required_record_count": required_count,
        "not_required_record_count": len(evaluations) - required_count,
        "note_present_record_count": sum(
            1 for evaluation in evaluations if evaluation.get("has_uncertainty_notes")
        ),
        "missing_record_count": len(missing_records),
        "generic_note_only_record_count": len(generic_note_records),
        "loose_covered_record_count": len(loose_covered_records),
        "category_covered_record_count": len(category_covered_records),
        "loose_coverage_rate": (
            len(loose_covered_records) / required_count if required_count else None
        ),
        "category_coverage_rate": (
            len(category_covered_records) / required_count if required_count else None
        ),
        "expected_reason_counts": dict(expected_reason_counts),
        "missing_reason_counts_loose": dict(missing_reason_counts_loose),
        "missing_reason_counts_category": dict(missing_reason_counts_category),
        "note_category_counts": dict(note_category_counts),
    }


def _aggregate_confidence_attributions(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate T042f ASR confidence attribution without fact text."""

    status_counts: Counter[str] = Counter()
    fact_match_status_counts: Counter[str] = Counter()
    fact_level_counts: Counter[str] = Counter()
    dominant_level_counts: Counter[str] = Counter()
    summary_error_attribution_counts: Counter[str] = Counter()
    omission_attribution_counts: Counter[str] = Counter()
    totals: Counter[str] = Counter()

    for record in records:
        attribution = record.get("confidence_attribution")
        if not isinstance(attribution, dict):
            status_counts["missing"] += 1
            continue
        status_counts[str(attribution.get("evaluation_status") or "unknown")] += 1
        fact_match_status_counts.update(
            attribution.get("fact_evidence_match_status_counts") or {}
        )
        fact_level_counts.update(
            attribution.get("fact_evidence_confidence_level_counts") or {}
        )
        dominant_level_counts.update(
            attribution.get("fact_evidence_dominant_risk_level_counts") or {}
        )
        summary_error_attribution_counts.update(
            attribution.get("summary_error_attribution_counts") or {}
        )
        omission_attribution_counts.update(
            attribution.get("omission_attribution_counts") or {}
        )
        totals["source_record_count"] += int(attribution.get("source_record_count") or 0)
        totals["fact_evaluation_count"] += int(
            attribution.get("fact_evaluation_count") or 0
        )
        totals["overlapping_review_span_count"] += int(
            attribution.get("overlapping_review_span_count") or 0
        )
        totals["changed_review_span_count"] += int(
            attribution.get("changed_review_span_count") or 0
        )
        totals["omitted_gold_fact_count"] += int(
            attribution.get("omitted_gold_fact_count") or 0
        )

    return {
        "record_count": len(records),
        "evaluation_status_counts": dict(status_counts),
        "source_record_count": totals["source_record_count"],
        "fact_evaluation_count": totals["fact_evaluation_count"],
        "fact_evidence_match_status_counts": dict(fact_match_status_counts),
        "fact_evidence_confidence_level_counts": dict(fact_level_counts),
        "fact_evidence_dominant_risk_level_counts": dict(dominant_level_counts),
        "summary_error_attribution_counts": dict(summary_error_attribution_counts),
        "overlapping_review_span_count": totals["overlapping_review_span_count"],
        "changed_review_span_count": totals["changed_review_span_count"],
        "omitted_gold_fact_count": totals["omitted_gold_fact_count"],
        "omission_attribution_counts": dict(omission_attribution_counts),
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_gold_canonical_fact_text": False,
            "contains_summary_fact_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }


def _aggregate_review_cost_attributions(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate T042f review-cost metadata across quality records."""

    status_counts: Counter[str] = Counter()
    action_summary: Counter[str] = Counter()
    confirmation_status: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    seen_source_keys: set[tuple[str, ...]] = set()
    duplicated_source_record_count = 0
    for record in records:
        cost = record.get("review_cost_attribution")
        if not isinstance(cost, dict):
            status_counts["missing"] += 1
            continue
        status_counts[str(cost.get("evaluation_status") or "unknown")] += 1
        source_key = tuple(
            _coerce_str_list(cost.get("source_record_ids"))
            or _coerce_str_list(cost.get("source_sample_ids"))
            or [str(record.get("bundle_id") or "unknown")]
        )
        if source_key in seen_source_keys:
            duplicated_source_record_count += 1
            continue
        seen_source_keys.add(source_key)
        for key in (
            "source_record_count",
            "confirmed_record_count",
            "missing_confirmed_record_count",
            "review_span_count",
            "applied_span_count",
            "resolved_span_count",
            "missing_feedback_span_count",
            "unresolved_span_count",
            "changed_span_count",
            "records_with_text_changes",
        ):
            totals[key] += int(cost.get(key) or 0)
        action_summary.update(cost.get("action_summary") or {})
        confirmation_status.update(cost.get("confirmation_status") or {})

    return {
        "record_count": len(records),
        "unique_review_cost_source_group_count": len(seen_source_keys),
        "duplicated_review_cost_source_group_count": duplicated_source_record_count,
        "evaluation_status_counts": dict(status_counts),
        "source_record_count": totals["source_record_count"],
        "confirmed_record_count": totals["confirmed_record_count"],
        "missing_confirmed_record_count": totals["missing_confirmed_record_count"],
        "review_span_count": totals["review_span_count"],
        "applied_span_count": totals["applied_span_count"],
        "resolved_span_count": totals["resolved_span_count"],
        "missing_feedback_span_count": totals["missing_feedback_span_count"],
        "unresolved_span_count": totals["unresolved_span_count"],
        "changed_span_count": totals["changed_span_count"],
        "records_with_text_changes": totals["records_with_text_changes"],
        "action_summary": dict(action_summary),
        "confirmation_status": dict(confirmation_status),
        "resolved_span_rate": _safe_ratio(
            totals["resolved_span_count"],
            totals["review_span_count"],
        ),
        "changed_span_rate": _safe_ratio(
            totals["changed_span_count"],
            totals["review_span_count"],
        ),
    }


def _build_review_benefit_summary(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Compare noisy ASR vs confirmed-summary quality at matched consultation level."""

    records_by_key: dict[tuple[str, str | None, str], dict[str, dict[str, Any]]] = (
        defaultdict(dict)
    )
    for record in records:
        key = (
            str(record.get("dataset") or ""),
            record.get("consultation_id"),
            str(record.get("input_unit") or "consultation"),
        )
        records_by_key[key][str(record.get("input_variant") or "")] = record

    paired_records: list[dict[str, Any]] = []
    for (dataset, consultation_id, input_unit), variants in records_by_key.items():
        noisy = variants.get(INPUT_VARIANT_NOISY_ASR)
        confirmed = variants.get(INPUT_VARIANT_CONFIRMED_TRANSCRIPT)
        if noisy is None or confirmed is None:
            continue
        review_cost = confirmed.get("review_cost_attribution") or {}
        fact_f1_delta = _subtract_optional(
            confirmed.get("fact_f1"),
            noisy.get("fact_f1"),
        )
        fact_recall_delta = _subtract_optional(
            confirmed.get("fact_recall"),
            noisy.get("fact_recall"),
        )
        critical_recall_delta = _subtract_optional(
            confirmed.get("critical_fact_recall"),
            noisy.get("critical_fact_recall"),
        )
        omission_reduction = _subtract_optional(
            noisy.get("omission_count"),
            confirmed.get("omission_count"),
        )
        fact_error_reduction = _fact_error_count(noisy) - _fact_error_count(confirmed)
        review_span_count = int(review_cost.get("review_span_count") or 0)
        changed_span_count = int(review_cost.get("changed_span_count") or 0)
        action_summary = review_cost.get("action_summary") or {}
        manual_edit_count = int(action_summary.get("manual_edit") or 0)
        paired_records.append(
            {
                "dataset": dataset,
                "consultation_id": consultation_id,
                "input_unit": input_unit,
                "fact_f1_improvement": fact_f1_delta,
                "fact_recall_improvement": fact_recall_delta,
                "critical_fact_recall_improvement": critical_recall_delta,
                "omission_reduction": omission_reduction,
                "fact_error_reduction": fact_error_reduction,
                "review_span_count": review_span_count,
                "changed_span_count": changed_span_count,
                "manual_edit_count": manual_edit_count,
                "select_alternative_count": int(
                    action_summary.get("select_alternative") or 0
                ),
                "fact_f1_improvement_per_review_span": _safe_ratio(
                    fact_f1_delta,
                    review_span_count,
                ),
                "fact_f1_improvement_per_changed_span": _safe_ratio(
                    fact_f1_delta,
                    changed_span_count,
                ),
                "fact_f1_improvement_per_manual_edit": _safe_ratio(
                    fact_f1_delta,
                    manual_edit_count,
                ),
            }
        )

    if not paired_records:
        return {
            "evaluation_status": "skipped",
            "skip_reason": "missing_noisy_asr_or_confirmed_transcript_pair",
            "paired_consultation_count": 0,
        }

    total_review_spans = sum(item["review_span_count"] for item in paired_records)
    total_changed_spans = sum(item["changed_span_count"] for item in paired_records)
    total_manual_edits = sum(item["manual_edit_count"] for item in paired_records)
    f1_deltas = [
        item["fact_f1_improvement"]
        for item in paired_records
        if item["fact_f1_improvement"] is not None
    ]
    total_f1_delta = sum(f1_deltas) if f1_deltas else None
    return {
        "evaluation_status": "evaluated",
        "paired_consultation_count": len(paired_records),
        "fact_f1_improvement_macro": _safe_mean(f1_deltas),
        "fact_recall_improvement_macro": _safe_mean(
            [
                item["fact_recall_improvement"]
                for item in paired_records
                if item["fact_recall_improvement"] is not None
            ]
        ),
        "critical_fact_recall_improvement_macro": _safe_mean(
            [
                item["critical_fact_recall_improvement"]
                for item in paired_records
                if item["critical_fact_recall_improvement"] is not None
            ]
        ),
        "omission_reduction_total": sum(
            int(item["omission_reduction"] or 0) for item in paired_records
        ),
        "fact_error_reduction_total": sum(
            int(item["fact_error_reduction"] or 0) for item in paired_records
        ),
        "review_span_count": total_review_spans,
        "changed_span_count": total_changed_spans,
        "manual_edit_count": total_manual_edits,
        "fact_f1_improvement_per_review_span_micro": _safe_ratio(
            total_f1_delta,
            total_review_spans,
        ),
        "fact_f1_improvement_per_changed_span_micro": _safe_ratio(
            total_f1_delta,
            total_changed_spans,
        ),
        "fact_f1_improvement_per_manual_edit_micro": _safe_ratio(
            total_f1_delta,
            total_manual_edits,
        ),
        "by_consultation": paired_records,
        "privacy_and_safety": {
            "contains_full_transcript_text": False,
            "contains_gold_canonical_fact_text": False,
            "contains_summary_fact_text": False,
            "contains_confirmed_span_text": False,
            "research_use_only": True,
        },
    }


def _quality_privacy_flags(*, include_fact_text: bool) -> dict[str, Any]:
    return {
        "contains_full_transcript_text": False,
        "contains_prompt_text": False,
        "contains_summary_fact_text": include_fact_text,
        "contains_gold_canonical_fact_text": False,
        "research_use_only": True,
    }


def _group_gold_facts(
    gold_facts: Sequence[GoldKeyFact],
) -> dict[tuple[str, str | None, str], list[GoldKeyFact]]:
    grouped: dict[tuple[str, str | None, str], list[GoldKeyFact]] = defaultdict(list)
    for fact in gold_facts:
        input_unit = _input_unit_from_gold_bundle_id(fact.bundle_id)
        grouped[(fact.dataset, fact.consultation_id, input_unit)].append(fact)
    return grouped


def _input_unit_from_gold_bundle_id(bundle_id: str) -> str:
    parts = bundle_id.split(":")
    if len(parts) >= 4 and parts[-2] == "gold_key_facts":
        return parts[-1]
    return "consultation"


def _gold_facts_for_summary_record(
    summary_record: dict[str, Any],
    gold_by_key: dict[tuple[str, str | None, str], list[GoldKeyFact]],
) -> list[GoldKeyFact]:
    dataset = str(summary_record.get("dataset") or "")
    consultation_id = summary_record.get("consultation_id")
    input_unit = str(summary_record.get("input_unit") or "consultation")
    return list(gold_by_key.get((dataset, consultation_id, input_unit), []))


def _group_records_by(
    records: Sequence[dict[str, Any]],
    key: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "unknown")].append(record)
    return grouped


def _sum_counter_field(records: Sequence[dict[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(record.get(key) or {})
    return dict(counts)


def _mean_metric(records: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [record.get(key) for record in records if record.get(key) is not None]
    if not values:
        return None
    return float(sum(values) / len(values))


def _mean_nested_metric(
    records: Sequence[dict[str, Any]],
    key_path: tuple[str, str],
) -> float | None:
    values: list[float] = []
    outer, inner = key_path
    for record in records:
        payload = record.get(outer)
        if not isinstance(payload, dict):
            continue
        value = payload.get(inner)
        if value is not None:
            values.append(float(value))
    if not values:
        return None
    return float(sum(values) / len(values))


def _safe_mean(values: Sequence[float | int]) -> float | None:
    if not values:
        return None
    return float(sum(float(value) for value in values) / len(values))


def _safe_ratio(
    numerator: float | int | None,
    denominator: float | int | None,
) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _subtract_optional(
    left: float | int | None,
    right: float | int | None,
) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _fact_error_count(record: dict[str, Any]) -> int:
    counts = record.get("factuality_counts") or {}
    return int(
        counts.get(SummaryFactFactuality.UNSUPPORTED.value, 0)
        + counts.get(SummaryFactFactuality.CONTRADICTED.value, 0)
        + counts.get(SummaryFactFactuality.UNVERIFIABLE.value, 0)
    )
