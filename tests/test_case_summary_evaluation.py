from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRWord,
    SourceChannel,
    UncertainSpan,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.case_summary_evaluation import (
    CaseSummaryFactField,
    EvidencePointer,
    GoldFactPolarity,
    GoldFactSeverity,
    GoldKeyFact,
    SummaryFactFactuality,
    SummaryHighRiskTag,
    build_gold_bundle_id,
    build_gold_key_facts_summary,
    read_gold_key_facts_jsonl,
    rouge_l_score,
    run_case_summary_quality_evaluation,
    run_gold_key_facts_validation,
    write_gold_key_facts_jsonl,
    write_jsonl,
)
from clinical_asr_robustness.review_workflow import (
    ConfirmationStatus,
    ConfirmedSpan,
    ConfirmedTranscriptRecord,
    ReviewFeedbackAction,
    write_confirmed_transcripts_jsonl,
)


def make_gold_fact(
    *,
    fact_id: str = "fact_demo_001",
    canonical_fact: str = "patient reports chest pain",
    field: CaseSummaryFactField = CaseSummaryFactField.SYMPTOMS,
    polarity: GoldFactPolarity = GoldFactPolarity.PRESENT,
    severity: GoldFactSeverity = GoldFactSeverity.MAJOR,
    error_tags: list[SummaryHighRiskTag] | None = None,
    normalized_terms: list[str] | None = None,
    sample_id: str = "demo_patient",
    record_id: str | None = None,
    word_start_index: int = 3,
    word_end_index: int = 5,
) -> GoldKeyFact:
    return GoldKeyFact(
        fact_id=fact_id,
        bundle_id=build_gold_bundle_id(dataset="primock57", consultation_id="demo"),
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        field=field,
        canonical_fact=canonical_fact,
        polarity=polarity,
        severity=severity,
        source_channel=SourceChannel.PATIENT,
        evidence_pointer=EvidencePointer(
            source_type="reference_transcript",
            sample_id=sample_id,
            record_id=record_id,
            source_channel=SourceChannel.PATIENT,
            word_start_index=word_start_index,
            word_end_index=word_end_index,
            cue="symptom mention",
        ),
        error_tags=error_tags or [],
        normalized_terms=normalized_terms or ["Chest", " pain "],
        annotator_role="researcher",
        reviewed=True,
    )


def make_asr_confidence_record_for_t042f() -> ASRConfidenceRecord:
    transcript = "patient reports chest pian now"
    words = transcript.split()
    confidences = [0.94, 0.91, 0.42, 0.38, 0.93]
    return ASRConfidenceRecord(
        record_id="record_demo_patient",
        sample_id="demo_patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=5.0,
        reference_textgrid_path="data/external/primock57/transcripts/demo.TextGrid",
        reference_text_included=False,
        asr_transcript=transcript,
        asr_confidence=0.72,
        asr_words=[
            ASRWord(
                word_index=index,
                text=word,
                start_sec=float(index),
                end_sec=float(index + 1),
                confidence=confidences[index],
            )
            for index, word in enumerate(words)
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_chest_pain",
                text="chest pian",
                start_word_index=2,
                end_word_index=4,
                start_sec=2.0,
                end_sec=4.0,
                mean_confidence=0.40,
                min_confidence=0.38,
            )
        ],
        model=ASRModelInfo(
            model_name="fake_nemo",
            model_path="data/external/asr_models/nemo/fake.nemo",
            model_class="FakeModel",
        ),
        decoding=ASRDecodingConfig(strategy="greedy", batch_size=1, device="cpu"),
        confidence=ASRConfidenceConfig(aggregation="mean"),
        alignment=AlignmentDiagnostics(
            transcript_word_count=len(words),
            word_timestamp_count=len(words),
            word_confidence_count=len(words),
            asr_word_count=len(words),
            paired_word_count=len(words),
        ),
    )


def test_gold_key_fact_round_trip_and_normalization(tmp_path) -> None:
    path = tmp_path / "gold_key_facts.jsonl"
    fact = make_gold_fact(error_tags=[SummaryHighRiskTag.MEDICAL_TERM])

    write_gold_key_facts_jsonl([fact], path)
    loaded = read_gold_key_facts_jsonl(path)

    assert len(loaded) == 1
    assert loaded[0].fact_id == "fact_demo_001"
    assert loaded[0].schema_version == "gold_key_fact/v1"
    assert loaded[0].normalized_terms == ["chest", "pain"]
    assert loaded[0].error_tags == [SummaryHighRiskTag.MEDICAL_TERM]


def test_gold_key_facts_summary_excludes_fact_text(tmp_path) -> None:
    fact = make_gold_fact()
    input_path = tmp_path / "gold_key_facts.jsonl"
    summary_path = tmp_path / "summary.json"
    write_gold_key_facts_jsonl([fact], input_path)

    summary = run_gold_key_facts_validation(
        input_jsonl=input_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["fact_count"] == 1
    assert summary["bundle_count"] == 1
    assert summary["counts_by_field"] == {"symptoms": 1}
    assert summary["counts_by_source_channel"] == {"patient": 1}
    assert "patient reports chest pain" not in serialized
    assert "patient reports chest pain" not in summary_path.read_text(encoding="utf-8")


def test_duplicate_fact_id_is_rejected(tmp_path) -> None:
    path = tmp_path / "gold_key_facts.jsonl"
    facts = [
        make_gold_fact(fact_id="duplicate_fact"),
        make_gold_fact(fact_id="duplicate_fact", canonical_fact="patient reports cough"),
    ]
    write_gold_key_facts_jsonl(facts, path)

    with pytest.raises(ValueError, match="duplicate fact_id"):
        read_gold_key_facts_jsonl(path)


def test_evidence_pointer_rejects_full_transcript_text_flag() -> None:
    with pytest.raises(ValidationError, match="must not contain full transcript text"):
        EvidencePointer(
            sample_id="demo_patient",
            cue="this intentionally marks a bad evidence payload",
            contains_full_transcript_text=True,
        )


def test_negated_symptom_fact_requires_absent_polarity() -> None:
    with pytest.raises(ValidationError, match="polarity='absent'"):
        make_gold_fact(
            field=CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS,
            polarity=GoldFactPolarity.PRESENT,
            canonical_fact="patient denies fever",
        )


def test_build_gold_key_facts_summary_counts_high_risk_tags(tmp_path) -> None:
    facts = [
        make_gold_fact(
            fact_id="fact_demo_001",
            error_tags=[SummaryHighRiskTag.NEGATION_OR_POLARITY],
        ),
        make_gold_fact(
            fact_id="fact_demo_002",
            canonical_fact="patient denies fever",
            field=CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS,
            polarity=GoldFactPolarity.ABSENT,
            severity=GoldFactSeverity.SAFETY_CRITICAL,
            error_tags=[SummaryHighRiskTag.NEGATION_OR_POLARITY],
        ),
    ]

    summary = build_gold_key_facts_summary(
        facts,
        input_jsonl=tmp_path / "gold_key_facts.jsonl",
        project_root=tmp_path,
    )

    assert summary["fact_count"] == 2
    assert summary["counts_by_polarity"] == {"present": 1, "absent": 1}
    assert summary["counts_by_severity"] == {"major": 1, "safety_critical": 1}
    assert summary["high_risk_tag_counts"] == {"negation_or_polarity": 2}


def test_rouge_l_score_handles_mixed_chinese_and_english() -> None:
    score = rouge_l_score("患者腹痛 vomiting", "患者腹痛并伴 vomiting")

    assert score["lcs"] > 0
    assert 0 < score["f1"] <= 1
    assert score["candidate_token_count"] > 0
    assert score["reference_token_count"] > 0


def test_run_case_summary_quality_evaluation_scores_supported_and_unsupported_facts(
    tmp_path,
) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"
    gold_facts = [
        make_gold_fact(
            fact_id="demo__symptoms__001",
            canonical_fact="patient reports chest pain",
            normalized_terms=["chest pain"],
            error_tags=[SummaryHighRiskTag.MEDICAL_TERM],
        ),
        make_gold_fact(
            fact_id="demo__negated__001",
            canonical_fact="patient denies fever",
            field=CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS,
            polarity=GoldFactPolarity.ABSENT,
            severity=GoldFactSeverity.SAFETY_CRITICAL,
            normalized_terms=["fever"],
            error_tags=[SummaryHighRiskTag.NEGATION_OR_POLARITY],
        ),
    ]
    write_gold_key_facts_jsonl(gold_facts, gold_path)
    write_jsonl(
        [
            {
                "schema_version": "case_summary_generation_record/v1",
                "task_id": "T041",
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "dataset": "primock57",
                "split": "seed_asr_v0",
                "consultation_id": "demo",
                "input_unit": "consultation",
                "input_variant": "noisy_asr",
                "prompt_version": "case_summary_prompt/v2_input_variant_aware",
                "status": "generated",
                "case_summary": {
                    "symptoms": ["chest pain"],
                    "negated_or_absent_symptoms": ["no fever"],
                    "medications": ["aspirin"],
                },
            }
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )
    fact_evaluations = [
        json.loads(line)
        for line in fact_evaluations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized_summary = summary_path.read_text(encoding="utf-8")
    serialized_fact_evaluations = fact_evaluations_path.read_text(encoding="utf-8")

    assert summary["evaluated_record_count"] == 1
    assert summary["skipped_record_count"] == 0
    assert summary["summary_fact_count"] == 3
    assert summary["fact_precision_micro"] == pytest.approx(2 / 3)
    assert summary["fact_recall_micro"] == pytest.approx(1.0)
    assert summary["critical_fact_recall_macro"] == pytest.approx(1.0)
    assert summary["factuality_counts"] == {
        SummaryFactFactuality.SUPPORTED.value: 2,
        SummaryFactFactuality.UNSUPPORTED.value: 1,
    }
    assert len(fact_evaluations) == 3
    assert "summary_fact_text" not in fact_evaluations[0]
    assert "chest pain" not in serialized_summary
    assert "patient reports chest pain" not in serialized_summary
    assert "chest pain" not in serialized_fact_evaluations
    assert "patient reports chest pain" not in serialized_fact_evaluations


def test_case_summary_quality_evaluation_detects_negation_contradiction(tmp_path) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"
    write_gold_key_facts_jsonl(
        [
            make_gold_fact(
                fact_id="demo__symptoms__001",
                canonical_fact="patient reports chest pain",
                normalized_terms=["chest pain"],
                error_tags=[SummaryHighRiskTag.NEGATION_OR_POLARITY],
            )
        ],
        gold_path,
    )
    write_jsonl(
        [
            {
                "schema_version": "case_summary_generation_record/v1",
                "task_id": "T041",
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "dataset": "primock57",
                "split": "seed_asr_v0",
                "consultation_id": "demo",
                "input_unit": "consultation",
                "input_variant": "noisy_asr",
                "prompt_version": "case_summary_prompt/v2_input_variant_aware",
                "status": "generated",
                "case_summary": {
                    "negated_or_absent_symptoms": ["no chest pain"],
                },
            }
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )
    fact_evaluation = json.loads(
        fact_evaluations_path.read_text(encoding="utf-8").splitlines()[0]
    )

    assert summary["factuality_counts"] == {
        SummaryFactFactuality.CONTRADICTED.value: 1
    }
    assert fact_evaluation["factuality_label"] == SummaryFactFactuality.CONTRADICTED
    assert fact_evaluation["reason"] == "matched_gold_fact_with_polarity_conflict"
    assert summary["fact_recall_micro"] == pytest.approx(0.0)


def test_case_summary_quality_evaluation_tracks_high_risk_and_uncertainty_notes(
    tmp_path,
) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"
    write_gold_key_facts_jsonl(
        [
            make_gold_fact(
                fact_id="demo__medications__001",
                canonical_fact="patient takes warfarin",
                field=CaseSummaryFactField.MEDICATIONS,
                normalized_terms=["warfarin"],
                error_tags=[SummaryHighRiskTag.DRUG_NAME],
            ),
            make_gold_fact(
                fact_id="demo__negated__001",
                canonical_fact="patient denies fever",
                field=CaseSummaryFactField.NEGATED_OR_ABSENT_SYMPTOMS,
                polarity=GoldFactPolarity.ABSENT,
                severity=GoldFactSeverity.SAFETY_CRITICAL,
                normalized_terms=["fever"],
                error_tags=[SummaryHighRiskTag.NEGATION_OR_POLARITY],
            ),
        ],
        gold_path,
    )
    write_jsonl(
        [
            {
                "schema_version": "case_summary_generation_record/v1",
                "task_id": "T041",
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "dataset": "primock57",
                "split": "seed_asr_v0",
                "consultation_id": "demo",
                "input_unit": "consultation",
                "input_variant": "noisy_asr",
                "prompt_version": "case_summary_prompt/v2_input_variant_aware",
                "status": "generated",
                "uncertain_span_count": 2,
                "case_summary": {
                    "symptoms": ["fever"],
                    "medications": ["aspirin 10 mg"],
                    "uncertainty_notes": ["ASR 低置信，药名和否定信息不确定"],
                },
            }
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )
    quality_record = json.loads(
        quality_records_path.read_text(encoding="utf-8").splitlines()[0]
    )
    fact_evaluations = [
        json.loads(line)
        for line in fact_evaluations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized_quality_records = quality_records_path.read_text(encoding="utf-8")
    serialized_summary = summary_path.read_text(encoding="utf-8")

    assert summary["factuality_counts"] == {
        SummaryFactFactuality.CONTRADICTED.value: 1,
        SummaryFactFactuality.UNSUPPORTED.value: 1,
    }
    assert summary["high_risk_error_type_counts"]["drug_name"] >= 1
    assert summary["high_risk_error_type_counts"]["medication_dose_or_route"] >= 1
    assert summary["high_risk_error_type_counts"]["negation_or_polarity"] >= 1
    assert (
        summary["uncertainty_note_summary"]["required_record_count"] == 1
    )
    assert summary["uncertainty_note_summary"]["missing_record_count"] == 0
    assert (
        summary["uncertainty_note_summary"]["category_covered_record_count"] == 1
    )
    assert quality_record["uncertainty_note_evaluation"]["coverage_status"] == (
        "covered_by_category"
    )
    assert any(
        evaluation["is_high_risk_error"]
        and "drug_name" in evaluation["high_risk_error_types"]
        for evaluation in fact_evaluations
    )
    assert "ASR 低置信" not in serialized_quality_records
    assert "ASR 低置信" not in serialized_summary


def test_case_summary_quality_evaluation_flags_missing_uncertainty_notes_for_noisy_asr(
    tmp_path,
) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"
    write_gold_key_facts_jsonl([make_gold_fact()], gold_path)
    write_jsonl(
        [
            {
                "schema_version": "case_summary_generation_record/v1",
                "task_id": "T041",
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "dataset": "primock57",
                "split": "seed_asr_v0",
                "consultation_id": "demo",
                "input_unit": "consultation",
                "input_variant": "noisy_asr",
                "prompt_version": "case_summary_prompt/v2_input_variant_aware",
                "status": "generated",
                "uncertain_span_count": 3,
                "case_summary": {
                    "symptoms": ["chest pain"],
                    "uncertainty_notes": [],
                },
            }
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )
    quality_record = json.loads(
        quality_records_path.read_text(encoding="utf-8").splitlines()[0]
    )

    assert summary["fact_precision_micro"] == pytest.approx(1.0)
    assert summary["uncertainty_note_summary"]["required_record_count"] == 1
    assert summary["uncertainty_note_summary"]["missing_record_count"] == 1
    assert summary["uncertainty_note_summary"]["loose_coverage_rate"] == 0.0
    assert quality_record["uncertainty_note_evaluation"]["coverage_status"] == "missing"
    assert quality_record["uncertainty_note_evaluation"]["missing_reasons_loose"] == [
        "noisy_asr_uncertain_spans"
    ]


def test_case_summary_quality_evaluation_links_asr_confidence_and_review_benefit(
    tmp_path,
) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    asr_path = tmp_path / "asr_confidence.jsonl"
    confirmed_path = tmp_path / "confirmed.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"

    write_gold_key_facts_jsonl(
        [
            make_gold_fact(
                fact_id="demo__symptoms__001",
                canonical_fact="patient reports chest pain",
                normalized_terms=["chest pain"],
                error_tags=[SummaryHighRiskTag.MEDICAL_TERM],
                record_id="record_demo_patient",
                word_start_index=2,
                word_end_index=4,
            )
        ],
        gold_path,
    )
    write_asr_confidence_jsonl([make_asr_confidence_record_for_t042f()], asr_path)
    write_confirmed_transcripts_jsonl(
        [
            ConfirmedTranscriptRecord(
                record_id="record_demo_patient",
                sample_id="demo_patient",
                dataset="primock57",
                split="seed_asr_v0",
                consultation_id="demo",
                source_channel=SourceChannel.PATIENT,
                asr_transcript="patient reports chest pian now",
                confirmed_transcript="patient reports chest pain now",
                confirmation_status=ConfirmationStatus.CONFIRMED,
                applied_spans=[
                    ConfirmedSpan(
                        span_id="span_chest_pain",
                        action=ReviewFeedbackAction.MANUAL_EDIT,
                        original_text="chest pian",
                        confirmed_text="chest pain",
                        resolved=True,
                    )
                ],
                action_summary={"manual_edit": 1},
            )
        ],
        confirmed_path,
    )
    common_record = {
        "schema_version": "case_summary_generation_record/v1",
        "task_id": "T041",
        "dataset": "primock57",
        "split": "seed_asr_v0",
        "consultation_id": "demo",
        "input_unit": "consultation",
        "prompt_version": "case_summary_prompt/v2_input_variant_aware",
        "status": "generated",
        "source_record_count": 1,
        "source_record_ids": ["record_demo_patient"],
        "source_sample_ids": ["demo_patient"],
        "source_channels": ["patient"],
        "uncertain_span_count": 1,
    }
    write_jsonl(
        [
            {
                **common_record,
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "input_variant": "noisy_asr",
                "case_summary": {
                    "symptoms": ["chest pian"],
                    "uncertainty_notes": ["ASR 低置信，症状词可能有误"],
                },
            },
            {
                **common_record,
                "bundle_id": "primock57:demo:confirmed_transcript:consultation",
                "input_variant": "confirmed_transcript",
                "case_summary": {
                    "symptoms": ["chest pain"],
                    "uncertainty_notes": [],
                },
            },
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        asr_confidence_jsonl=asr_path,
        confirmed_transcripts_jsonl=confirmed_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )
    quality_records = [
        json.loads(line)
        for line in quality_records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fact_evaluations = [
        json.loads(line)
        for line in fact_evaluations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized_summary = summary_path.read_text(encoding="utf-8")

    noisy_record = next(
        record for record in quality_records if record["input_variant"] == "noisy_asr"
    )
    assert summary["confidence_attribution_summary"]["evaluation_status_counts"] == {
        "evaluated": 2
    }
    assert summary["review_cost_attribution_summary"]["action_summary"] == {
        "manual_edit": 1
    }
    assert summary["review_benefit_summary"]["paired_consultation_count"] == 1
    assert summary["review_benefit_summary"]["fact_f1_improvement_macro"] == pytest.approx(
        1.0
    )
    assert (
        noisy_record["confidence_attribution"][
            "fact_evidence_dominant_risk_level_counts"
        ]["red"]
        == 1
    )
    assert noisy_record["review_cost_attribution"]["changed_span_count"] == 1
    assert any(
        evaluation["confidence_attribution"]["overlapping_review_span_ids"]
        == ["span_chest_pain"]
        for evaluation in fact_evaluations
    )
    assert "chest pain" not in serialized_summary
    assert "chest pian" not in serialized_summary


def test_case_summary_quality_evaluation_skips_prompt_ready_records(tmp_path) -> None:
    gold_path = tmp_path / "gold_key_facts.jsonl"
    summary_records_path = tmp_path / "summary_records.jsonl"
    quality_records_path = tmp_path / "quality_records.jsonl"
    fact_evaluations_path = tmp_path / "fact_evaluations.jsonl"
    summary_path = tmp_path / "quality_summary.json"
    write_gold_key_facts_jsonl([make_gold_fact()], gold_path)
    write_jsonl(
        [
            {
                "schema_version": "case_summary_generation_record/v1",
                "task_id": "T041",
                "bundle_id": "primock57:demo:noisy_asr:consultation",
                "dataset": "primock57",
                "split": "seed_asr_v0",
                "consultation_id": "demo",
                "input_unit": "consultation",
                "input_variant": "noisy_asr",
                "prompt_version": "case_summary_prompt/v2_input_variant_aware",
                "status": "prompt_ready",
                "case_summary": None,
            }
        ],
        summary_records_path,
    )

    summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=summary_records_path,
        gold_key_facts_jsonl=gold_path,
        output_records_jsonl=quality_records_path,
        output_fact_evaluations_jsonl=fact_evaluations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
    )

    assert summary["evaluated_record_count"] == 0
    assert summary["skipped_record_count"] == 1
    assert summary["skipped_record_reasons"] == {"missing_case_summary": 1}
    assert fact_evaluations_path.read_text(encoding="utf-8") == ""
