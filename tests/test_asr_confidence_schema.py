import pytest
from pydantic import ValidationError

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRSegment,
    ASRWord,
    ConfidenceLevel,
    SourceChannel,
    UncertainSpan,
    confidence_level_for_score,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)


def make_demo_record() -> ASRConfidenceRecord:
    alternatives = [
        ASRAlternative(
            alternative_id="alt_span_001_rank_1",
            scope=AlternativeScope.SPAN,
            rank=1,
            text="mild cough",
            span_id="span_001",
            score=-0.2,
            confidence=0.62,
            alignment_method="sequence_nbest_diff",
        )
    ]
    return ASRConfidenceRecord(
        record_id="asr_demo_001",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="demo",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/raw/primock57/audio/demo_patient.wav",
        duration_sec=3.2,
        reference_textgrid_path="data/raw/primock57/transcripts/demo.TextGrid",
        asr_transcript="patient reports cough",
        asr_confidence=0.70,
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
                confidence=0.85,
            ),
            ASRWord(
                word_index=2,
                text="cough",
                start_sec=0.8,
                end_sec=1.1,
                confidence=0.42,
            ),
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text="patient reports cough",
                start_word_index=0,
                end_word_index=3,
                start_sec=0.0,
                end_sec=1.1,
                confidence=0.70,
                confidence_aggregation="mean",
            )
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
        asr_alternatives=alternatives,
        model=ASRModelInfo(
            provider="nemo",
            model_name="stt_en_fastconformer_ctc_large",
            model_path="data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo",
            model_class="nemo.collections.asr.models.ctc_bpe_models.EncDecCTCModelBPE",
        ),
        decoding=ASRDecodingConfig(
            strategy="greedy",
            batch_size=1,
            device="cuda",
            timestamps_enabled=True,
            return_hypotheses=True,
        ),
        confidence=ASRConfidenceConfig(aggregation="min"),
        alignment=AlignmentDiagnostics(
            transcript_word_count=3,
            word_timestamp_count=4,
            word_confidence_count=3,
            asr_word_count=3,
            paired_word_count=3,
            dropped_extra_word_timestamps=[
                {
                    "raw_index": 3,
                    "raw_value": {"word": "", "start_offset": 1.1, "end_offset": 1.1},
                    "reason": "timestamp_without_output_word",
                }
            ],
        ),
    )


def test_asr_confidence_record_roundtrip(tmp_path) -> None:
    record = make_demo_record()

    assert record.asr_words[0].confidence_level == ConfidenceLevel.GREEN
    assert record.asr_words[2].confidence_level == ConfidenceLevel.RED
    assert record.uncertain_spans[0].confidence_level == ConfidenceLevel.RED
    assert record.alternatives_for_span("span_001")[0].alternative_id == "alt_span_001_rank_1"
    assert record.words_for_span(record.uncertain_spans[0])[0].text == "cough"

    path = tmp_path / "asr_confidence.jsonl"
    write_asr_confidence_jsonl([record], path)
    assert read_asr_confidence_jsonl(path) == [record]


def test_timestamp_confidence_count_mismatch_is_recorded_without_extra_word() -> None:
    record = make_demo_record()

    assert len(record.asr_words) == 3
    assert record.alignment.word_timestamp_count == 4
    assert record.alignment.word_confidence_count == 3
    assert len(record.alignment.dropped_extra_word_timestamps) == 1


def test_asr_confidence_schema_validates_references_and_ranges() -> None:
    with pytest.raises(ValidationError):
        ASRWord(word_index=0, text="bad", start_sec=2.0, end_sec=1.0, confidence=0.5)

    with pytest.raises(ValidationError):
        ASRAlternative(
            alternative_id="bad_alt",
            scope=AlternativeScope.SPAN,
            rank=1,
            text="candidate without span reference",
        )

    record_payload = make_demo_record().model_dump(mode="json")
    record_payload["uncertain_spans"][0]["alternative_ids"] = ["unknown_alt"]
    with pytest.raises(ValidationError):
        ASRConfidenceRecord.model_validate(record_payload)

    record_payload = make_demo_record().model_dump(mode="json")
    record_payload["reference_text_included"] = True
    with pytest.raises(ValidationError):
        ASRConfidenceRecord.model_validate(record_payload)


def test_confidence_level_thresholds() -> None:
    assert confidence_level_for_score(0.9) == ConfidenceLevel.GREEN
    assert confidence_level_for_score(0.8) == ConfidenceLevel.YELLOW
    assert confidence_level_for_score(0.79) == ConfidenceLevel.RED
    assert confidence_level_for_score(None) == ConfidenceLevel.UNKNOWN
