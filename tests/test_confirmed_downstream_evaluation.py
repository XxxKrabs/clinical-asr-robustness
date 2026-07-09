from __future__ import annotations

import json

import pytest

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
from clinical_asr_robustness.confirmed_downstream_evaluation import (
    VARIANT_CONFIRMED,
    VARIANT_RAW_ASR,
    build_annotation_record,
    build_summary,
    evaluate_transcript_variant,
    run_confirmed_downstream_evaluation,
)
from clinical_asr_robustness.review_workflow import (
    ConfirmationStatus,
    ConfirmedSpan,
    ConfirmedTranscriptRecord,
    ReviewFeedbackAction,
    write_confirmed_transcripts_jsonl,
)


def make_asr_record() -> ASRConfidenceRecord:
    return ASRConfidenceRecord(
        record_id="record_demo_patient",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=1.6,
        reference_textgrid_path="reference.TextGrid",
        reference_text_included=False,
        asr_transcript="patient reports cough now",
        asr_confidence=0.77,
        asr_words=[
            ASRWord(word_index=0, text="patient", confidence=0.93),
            ASRWord(word_index=1, text="reports", confidence=0.88),
            ASRWord(word_index=2, text="cough", confidence=0.42),
            ASRWord(word_index=3, text="now", confidence=0.94),
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text="cough",
                start_word_index=2,
                end_word_index=3,
                mean_confidence=0.42,
                min_confidence=0.42,
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
            transcript_word_count=4,
            word_timestamp_count=0,
            word_confidence_count=4,
            asr_word_count=4,
            paired_word_count=4,
        ),
    )


def make_confirmed_record() -> ConfirmedTranscriptRecord:
    return ConfirmedTranscriptRecord(
        record_id="record_demo_patient",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        asr_transcript="patient reports cough now",
        confirmed_transcript="patient reports chest pain now",
        confirmation_status=ConfirmationStatus.CONFIRMED,
        applied_spans=[
            ConfirmedSpan(
                span_id="span_001",
                action=ReviewFeedbackAction.MANUAL_EDIT,
                original_text="cough",
                confirmed_text="chest pain",
                resolved=True,
            )
        ],
        action_summary={"manual_edit": 1},
    )


def test_evaluate_transcript_variant_reports_downstream_concept_f1() -> None:
    reference_text = "patient reports chest pain now"
    raw_text = "patient reports cough now"

    raw = evaluate_transcript_variant(
        reference_text=reference_text,
        hypothesis_text=raw_text,
        medical_terms={"chest", "pain", "cough"},
    )
    confirmed = evaluate_transcript_variant(
        reference_text=reference_text,
        hypothesis_text=reference_text,
        medical_terms={"chest", "pain", "cough"},
    )

    assert raw["wer"] == pytest.approx(2 / 5)
    assert raw["mc_wer"] == pytest.approx(1.0)
    assert raw["downstream"]["f1"] == pytest.approx(0.0)
    assert confirmed["wer"] == pytest.approx(0.0)
    assert confirmed["mc_wer"] == pytest.approx(0.0)
    assert confirmed["downstream"]["f1"] == pytest.approx(1.0)


def test_build_summary_compares_raw_confirmed_without_full_text(tmp_path) -> None:
    asr_record = make_asr_record()
    confirmed_record = make_confirmed_record()
    reference_text = "patient reports chest pain now"
    reference_path = tmp_path / "reference.TextGrid"
    reference_path.write_text(f'text = "{reference_text}"\n', encoding="utf-8")

    annotation = build_annotation_record(
        asr_record,
        confirmed_record,
        reference_text=reference_text,
        reference_path=reference_path,
        project_root=tmp_path,
        medical_terms={"chest", "pain", "cough"},
    )
    summary = build_summary(
        [annotation],
        asr_input_jsonl=tmp_path / "asr.jsonl",
        confirmed_input_jsonl=tmp_path / "confirmed.jsonl",
        annotations_path=tmp_path / "annotations.jsonl",
        project_root=tmp_path,
    )

    assert annotation["review_cost"]["changed_span_count"] == 1
    assert summary["variant_metrics"][VARIANT_RAW_ASR]["micro_wer"] == pytest.approx(
        2 / 5
    )
    assert summary["variant_metrics"][VARIANT_CONFIRMED]["micro_wer"] == pytest.approx(
        0.0
    )
    assert summary["confirmed_vs_raw"]["mean_wer_improvement"] == pytest.approx(2 / 5)
    assert summary["confirmed_vs_raw"]["mean_medical_concept_f1_improvement"] == (
        pytest.approx(1.0)
    )
    serialized = json.dumps(summary, ensure_ascii=False)
    assert reference_text not in serialized
    assert "patient reports cough now" not in serialized


def test_run_confirmed_downstream_evaluation_writes_outputs(tmp_path) -> None:
    asr_record = make_asr_record().model_copy(
        update={"reference_textgrid_path": "reference.TextGrid"}
    )
    confirmed_record = make_confirmed_record()
    reference_path = tmp_path / "reference.TextGrid"
    reference_path.write_text(
        'text = "patient reports chest pain now"\n',
        encoding="utf-8",
    )
    asr_path = tmp_path / "asr.jsonl"
    confirmed_path = tmp_path / "confirmed.jsonl"
    annotations_path = tmp_path / "annotations.jsonl"
    summary_path = tmp_path / "summary.json"
    write_asr_confidence_jsonl([asr_record], asr_path)
    write_confirmed_transcripts_jsonl([confirmed_record], confirmed_path)

    summary = run_confirmed_downstream_evaluation(
        asr_input_jsonl=asr_path,
        confirmed_input_jsonl=confirmed_path,
        output_annotations_jsonl=annotations_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
        medical_terms_path=None,
    )

    assert summary["record_count"] == 1
    assert summary["records_skipped"] == 0
    assert annotations_path.exists()
    assert summary_path.exists()
