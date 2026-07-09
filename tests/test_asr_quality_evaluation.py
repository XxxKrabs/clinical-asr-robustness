from __future__ import annotations

import json

import pytest

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRWord,
    SourceChannel,
    UncertainSpan,
)
from clinical_asr_robustness.asr_quality_evaluation import (
    build_annotation_record,
    build_summary,
    read_textgrid_transcript,
)


def make_quality_eval_record() -> ASRConfidenceRecord:
    return ASRConfidenceRecord(
        record_id="nemo_entropy_primock57_demo_patient",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=1.6,
        reference_textgrid_path="data/external/primock57/transcripts/demo_patient.TextGrid",
        reference_text_included=False,
        asr_transcript="patient reports cough now",
        asr_confidence=0.77,
        asr_words=[
            ASRWord(
                word_index=0,
                text="patient",
                start_sec=0.0,
                end_sec=0.4,
                confidence=0.93,
            ),
            ASRWord(
                word_index=1,
                text="reports",
                start_sec=0.4,
                end_sec=0.8,
                confidence=0.77,
            ),
            ASRWord(
                word_index=2,
                text="cough",
                start_sec=0.8,
                end_sec=1.1,
                confidence=0.42,
                metadata={
                    "medical_entity_review": {
                        "is_medical_entity": True,
                        "display_confidence_level": "red",
                    }
                },
            ),
            ASRWord(
                word_index=3,
                text="now",
                start_sec=1.1,
                end_sec=1.3,
                confidence=0.94,
            ),
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text="cough",
                start_word_index=2,
                end_word_index=3,
                start_sec=0.8,
                end_sec=1.1,
                mean_confidence=0.42,
                min_confidence=0.42,
                alternative_ids=["alt_span_001_rank_1"],
            )
        ],
        asr_alternatives=[
            ASRAlternative(
                alternative_id="alt_span_001_rank_1",
                scope=AlternativeScope.SPAN,
                rank=1,
                text="chest",
                span_id="span_001",
                start_word_index=2,
                end_word_index=3,
                source="unit_test",
            )
        ],
        model=ASRModelInfo(
            model_name="fake_nemo",
            model_path="data/external/asr_models/nemo/fake.nemo",
            model_class="FakeModel",
        ),
        decoding=ASRDecodingConfig(
            strategy="greedy",
            batch_size=1,
            device="cpu",
        ),
        confidence=ASRConfidenceConfig(aggregation="mean"),
        alignment=AlignmentDiagnostics(
            transcript_word_count=4,
            word_timestamp_count=4,
            word_confidence_count=4,
            asr_word_count=4,
            paired_word_count=4,
        ),
    )


def test_read_textgrid_transcript_keeps_unsure_content_and_removes_tags(tmp_path) -> None:
    path = tmp_path / "demo.TextGrid"
    path.write_text(
        '\n'.join(
            [
                'text = ""',
                'text = "Patient has <UNSURE>fever</UNSURE>."',
                'text = "<UNIN/>"',
                'text = "No blood."',
            ]
        ),
        encoding="utf-8",
    )

    transcript = read_textgrid_transcript(path)

    assert "fever" in transcript
    assert "No blood" in transcript
    assert "UNIN" not in transcript
    assert "UNSURE" not in transcript


def test_build_annotation_record_evaluates_wer_confidence_and_topk(tmp_path) -> None:
    record = make_quality_eval_record()
    reference_path = tmp_path / "demo_reference.TextGrid"
    reference_text = "patient reports chest now"
    reference_path.write_text(f'text = "{reference_text}"\n', encoding="utf-8")

    annotation = build_annotation_record(
        record,
        reference_text=reference_text,
        reference_path=reference_path,
        project_root=tmp_path,
        medical_terms={"chest", "cough"},
    )

    assert annotation["metrics"]["wer"] == pytest.approx(1 / 4)
    assert annotation["metrics"]["mc_wer"] == pytest.approx(1.0)
    assert annotation["confidence_by_level"]["red"]["token_count"] == 1
    assert annotation["confidence_by_level"]["red"]["error_rate"] == pytest.approx(1.0)
    assert annotation["confidence_by_level"]["green"]["error_rate"] == pytest.approx(0.0)
    assert annotation["calibration"]["scored_token_count"] == 4
    assert annotation["medical_review_error_coverage"][
        "marked_medical_entity_error_token_coverage"
    ] == pytest.approx(1.0)
    assert annotation["topk"]["span_level"]["total_uncertain_spans"] == 1
    assert annotation["topk"]["span_level"]["exact_reference_covered_spans"] == 1
    assert annotation["topk"]["span_level"]["candidate_count_by_source"] == {
        "unit_test": 1
    }
    assert annotation["span_topk_records"][0]["reference_span_text"] == "chest"


def test_build_summary_contains_aggregates_without_full_reference_text(tmp_path) -> None:
    record = make_quality_eval_record()
    reference_path = tmp_path / "demo_reference.TextGrid"
    reference_text = "patient reports chest now"
    reference_path.write_text(f'text = "{reference_text}"\n', encoding="utf-8")
    annotation = build_annotation_record(
        record,
        reference_text=reference_text,
        reference_path=reference_path,
        project_root=tmp_path,
        medical_terms={"chest", "cough"},
    )

    summary = build_summary(
        [annotation],
        input_jsonl=tmp_path / "input.jsonl",
        annotations_path=tmp_path / "annotations.jsonl",
        project_root=tmp_path,
    )

    assert summary["record_count"] == 1
    assert summary["micro_wer"] == pytest.approx(1 / 4)
    assert summary["topk"]["span_level"]["exact_reference_covered_spans"] == 1
    assert summary["topk"]["span_level"]["candidate_count_by_source"] == {
        "unit_test": 1
    }
    assert summary["topk"]["span_level"][
        "exact_reference_covered_spans_by_source"
    ] == {"unit_test": 1}
    serialized = json.dumps(summary, ensure_ascii=False)
    assert reference_text not in serialized
