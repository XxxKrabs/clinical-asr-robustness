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
    LLM_WORD_AUX_SOURCE,
    MEDICAL_LEXICON_ALIGNMENT_METHOD,
    MEDICAL_LEXICON_AUX_SOURCE,
    SPAN_ALIGNMENT_METHOD,
    align_sequence_candidate_to_span,
    attach_nbest_candidates_to_record,
    build_llm_word_candidate_prompt_records,
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


def test_auxiliary_medical_candidates_fill_medical_span_without_asr_candidate() -> None:
    payload = make_base_record().model_dump(mode="json")
    payload["asr_transcript"] = "patient reports diarrheea now"
    payload["asr_words"][2]["text"] = "diarrheea"
    payload["asr_words"][2]["metadata"] = {
        "medical_entity_review": {
            "is_medical_entity": True,
            "entity_ids": ["ent_001"],
        }
    }
    payload["asr_segments"][0]["text"] = "patient reports diarrheea now"
    payload["uncertain_spans"] = [
        {
            "span_id": "medspan_001",
            "text": "diarrheea",
            "start_word_index": 2,
            "end_word_index": 3,
            "start_sec": 0.8,
            "end_sec": 1.1,
            "mean_confidence": 0.42,
            "min_confidence": 0.42,
            "trigger_reason": "medical_entity_low_or_medium_confidence",
            "metadata": {
                "medical_entity_ids": ["ent_001"],
                "medical_entities": [
                    {"entity_id": "ent_001", "text": "diarrheea", "entity_type": "symptom"}
                ],
            },
        }
    ]
    record = ASRConfidenceRecord.model_validate(payload)

    updated = attach_nbest_candidates_to_record(
        record,
        [{"rank": 1, "text": "patient reports diarrheea now", "score": -0.1}],
        enable_auxiliary_medical_candidates=True,
        medical_candidate_lexicon={"symptom": ["diarrhea", "vomiting"]},
        max_auxiliary_span_alternatives=1,
        aux_min_similarity=0.5,
    )

    span_alternatives = [
        alternative
        for alternative in updated.asr_alternatives
        if alternative.scope == AlternativeScope.SPAN
    ]
    assert [alternative.text for alternative in span_alternatives] == ["diarrhea"]
    assert span_alternatives[0].source == MEDICAL_LEXICON_AUX_SOURCE
    assert span_alternatives[0].alignment_method == MEDICAL_LEXICON_ALIGNMENT_METHOD
    assert span_alternatives[0].metadata["generated_by"] == "T039"
    assert span_alternatives[0].metadata["reference_used"] is False
    assert updated.uncertain_spans[0].alternative_ids == [
        span_alternatives[0].alternative_id
    ]
    assert (
        updated.metadata["t039_auxiliary_candidate_generation"][
            "auxiliary_span_alternatives_added"
        ]
        == 1
    )



def test_llm_word_candidates_target_yellow_red_words_with_context_and_lexicon() -> None:
    payload = make_base_record().model_dump(mode="json")
    payload["uncertain_spans"] = [
        {
            "span_id": "span_word_001",
            "text": "cough now",
            "start_word_index": 2,
            "end_word_index": 4,
            "start_sec": 0.8,
            "end_sec": 1.3,
            "mean_confidence": 0.68,
            "min_confidence": 0.42,
            "metadata": {
                "medical_entities": [
                    {"entity_id": "ent_001", "text": "cough", "entity_type": "symptom"}
                ]
            },
        }
    ]
    record = ASRConfidenceRecord.model_validate(payload)
    lexicon = {"symptom": ["coughing", "chest pain", "fever"]}

    prompts = build_llm_word_candidate_prompt_records(
        record,
        medical_candidate_lexicon=lexicon,
        context_window_words=2,
        max_lexicon_terms=5,
    )

    assert len(prompts) == 1
    assert prompts[0].target_word_text == "cough"
    assert prompts[0].target_confidence_level == "red"
    assert prompts[0].context["window_text"] == "patient reports cough now"
    assert "coughing" in prompts[0].medical_lexicon_terms

    calls: list[list[dict[str, str]]] = []

    def fake_generator(messages: list[dict[str, str]]) -> tuple[str, dict[str, str]]:
        calls.append(messages)
        return '{"candidates": ["coughing", "chest pain", "cough"]}', {
            "model_name": "fake-llm"
        }

    updated = attach_nbest_candidates_to_record(
        record,
        [],
        enable_llm_word_candidates=True,
        llm_word_candidate_generator=fake_generator,
        medical_candidate_lexicon=lexicon,
        max_llm_word_candidates=3,
        llm_word_context_window=2,
        max_llm_lexicon_terms=5,
    )

    word_alternatives = [
        alternative
        for alternative in updated.asr_alternatives
        if alternative.scope == AlternativeScope.WORD
    ]
    assert len(calls) == 1
    assert [alternative.text for alternative in word_alternatives] == [
        "coughing",
        "chest pain",
    ]
    assert {alternative.source for alternative in word_alternatives} == {LLM_WORD_AUX_SOURCE}
    assert word_alternatives[0].span_id == "span_word_001"
    assert word_alternatives[0].start_word_index == 2
    assert word_alternatives[0].end_word_index == 3
    assert word_alternatives[0].metadata["generated_by"] == "T044"
    assert word_alternatives[0].metadata["target_word_text"] == "cough"
    assert updated.uncertain_spans[0].alternative_ids == [
        alternative.alternative_id for alternative in word_alternatives
    ]
    assert (
        updated.metadata["t044_llm_word_candidate_generation"][
            "eligible_yellow_red_words"
        ]
        == 1
    )
    assert (
        updated.metadata["t044_llm_word_candidate_generation"][
            "word_alternatives_added"
        ]
        == 2
    )


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
