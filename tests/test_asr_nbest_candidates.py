from __future__ import annotations

import json

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    AlternativeScope,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRSegment,
    ASRWord,
    SourceChannel,
    UncertainSpan,
)
from clinical_asr_robustness.asr_nbest_candidates import (
    SPAN_ALIGNMENT_METHOD,
    align_sequence_candidate_to_span,
    attach_nbest_candidates_to_record,
    load_nbest_jsonl,
    nbest_items_for_record,
)


def make_base_record() -> ASRConfidenceRecord:
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
            ),
            ASRWord(
                word_index=3,
                text="now",
                start_sec=1.1,
                end_sec=1.3,
                confidence=0.94,
            ),
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text="patient reports cough now",
                start_word_index=0,
                end_word_index=4,
                start_sec=0.0,
                end_sec=1.3,
                confidence=0.77,
                confidence_aggregation="mean",
            )
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text="reports cough",
                start_word_index=1,
                end_word_index=3,
                start_sec=0.4,
                end_sec=1.1,
                mean_confidence=0.595,
                min_confidence=0.42,
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


def test_align_sequence_candidate_to_span_keeps_local_candidate_window() -> None:
    result = align_sequence_candidate_to_span(
        base_words="patient reports cough now".split(),
        candidate_words="patient reports chest pain now".split(),
        span_start_word_index=1,
        span_end_word_index=3,
    )

    assert result is not None
    assert result.text == "reports chest pain"
    assert result.changed is True

    insertion = align_sequence_candidate_to_span(
        base_words="patient cough now".split(),
        candidate_words="patient dry cough now".split(),
        span_start_word_index=1,
        span_end_word_index=2,
    )

    assert insertion is not None
    assert insertion.text == "dry cough"
    assert insertion.changed is True


def test_attach_nbest_candidates_adds_sequence_and_span_alternatives() -> None:
    record = make_base_record()

    updated = attach_nbest_candidates_to_record(
        record,
        [
            {"rank": 1, "text": "patient reports cough now", "score": -0.1},
            {"rank": 2, "text": "patient reports chest pain now", "score": -0.3},
            {"rank": 3, "text": "patient denies cough now", "score": -0.4},
        ],
        max_sequence_alternatives=3,
        max_span_alternatives=2,
    )

    sequence_alternatives = [
        alternative
        for alternative in updated.asr_alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    ]
    span_alternatives = [
        alternative
        for alternative in updated.asr_alternatives
        if alternative.scope == AlternativeScope.SPAN
    ]

    assert [alternative.text for alternative in sequence_alternatives] == [
        "patient reports cough now",
        "patient reports chest pain now",
        "patient denies cough now",
    ]
    assert [alternative.text for alternative in span_alternatives] == [
        "reports chest pain",
        "denies cough",
    ]
    assert span_alternatives[0].span_id == "span_001"
    assert span_alternatives[0].start_word_index == 1
    assert span_alternatives[0].end_word_index == 3
    assert span_alternatives[0].alignment_method == SPAN_ALIGNMENT_METHOD
    assert updated.uncertain_spans[0].alternative_ids == [
        alternative.alternative_id for alternative in span_alternatives
    ]
    assert updated.metadata["t029_nbest_candidate_extraction"]["span_alternatives_added"] == 2


def test_load_nbest_jsonl_supports_record_level_and_item_level_formats(tmp_path) -> None:
    path = tmp_path / "nbest.jsonl"
    lines = [
        {
            "sample_id": "primock57:demo:patient",
            "source": "nemo_beam",
            "beams": [
                ["patient reports cough now", -0.1],
                ["patient reports chest pain now", -0.3],
            ],
        },
        {
            "record_id": "nemo_entropy_other",
            "rank": 1,
            "text": "hello there",
            "score": -1.2,
            "source": "mock_beam",
        },
    ]
    path.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
        encoding="utf-8",
    )

    by_key = load_nbest_jsonl(path)

    record = make_base_record()
    items = nbest_items_for_record(record, by_key)
    assert [item.text for item in items] == [
        "patient reports cough now",
        "patient reports chest pain now",
    ]
    updated = attach_nbest_candidates_to_record(record, items)
    sequence_sources = {
        alternative.source
        for alternative in updated.asr_alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    }
    assert sequence_sources == {"nemo_beam"}
    assert by_key["record_id:nemo_entropy_other"][0].text == "hello there"
    assert by_key["record_id:nemo_entropy_other"][0].source == "mock_beam"
