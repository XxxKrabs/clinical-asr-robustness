from __future__ import annotations

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
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
    attach_nbest_candidates_to_record,
)
from clinical_asr_robustness.medical_entity_review import (
    MEDICAL_ENTITY_REVIEW_METADATA_KEY,
    MEDICAL_ENTITY_TRIGGER_REASON,
    MedicalEntityMention,
    apply_medical_entity_review_gating,
    coerce_medical_entity_mentions,
    endpoint_for_chat_completions,
    parse_json_object,
    read_project_env_file,
    resolve_llm_api_config,
)
from clinical_asr_robustness.review_workflow import build_review_html, build_review_sample


def make_medical_entity_record() -> ASRConfidenceRecord:
    return ASRConfidenceRecord(
        record_id="record_medical_entity_demo",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=2.0,
        reference_textgrid_path="data/external/primock57/transcripts/demo_patient.TextGrid",
        reference_text_included=False,
        asr_transcript="patient reports cough and aspirin",
        asr_confidence=0.78,
        asr_words=[
            ASRWord(word_index=0, text="patient", start_sec=0.0, end_sec=0.3, confidence=0.93),
            ASRWord(word_index=1, text="reports", start_sec=0.3, end_sec=0.6, confidence=0.77),
            ASRWord(word_index=2, text="cough", start_sec=0.6, end_sec=0.9, confidence=0.42),
            ASRWord(word_index=3, text="and", start_sec=0.9, end_sec=1.0, confidence=0.88),
            ASRWord(word_index=4, text="aspirin", start_sec=1.0, end_sec=1.4, confidence=0.91),
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text="patient reports cough and aspirin",
                start_word_index=0,
                end_word_index=5,
                start_sec=0.0,
                end_sec=1.4,
                confidence=0.78,
                confidence_aggregation="mean",
            )
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text="reports cough",
                start_word_index=1,
                end_word_index=3,
                start_sec=0.3,
                end_sec=0.9,
                mean_confidence=0.595,
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
            transcript_word_count=5,
            word_timestamp_count=5,
            word_confidence_count=5,
            asr_word_count=5,
            paired_word_count=5,
        ),
    )


def make_record_from_words(
    words: list[str],
    *,
    confidences: list[float] | None = None,
) -> ASRConfidenceRecord:
    transcript = " ".join(words)
    active_confidences = confidences or [0.9 for _ in words]
    return ASRConfidenceRecord(
        record_id="record_medical_entity_postprocess",
        sample_id="primock57:demo:postprocess",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=float(len(words)),
        reference_textgrid_path="data/external/primock57/transcripts/demo_patient.TextGrid",
        reference_text_included=False,
        asr_transcript=transcript,
        asr_confidence=sum(active_confidences) / len(active_confidences),
        asr_words=[
            ASRWord(
                word_index=index,
                text=word,
                start_sec=float(index),
                end_sec=float(index + 1),
                confidence=active_confidences[index],
            )
            for index, word in enumerate(words)
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text=transcript,
                start_word_index=0,
                end_word_index=len(words),
                start_sec=0.0,
                end_sec=float(len(words)),
                confidence=sum(active_confidences) / len(active_confidences),
                confidence_aggregation="mean",
            )
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text=transcript,
                start_word_index=0,
                end_word_index=len(words),
                start_sec=0.0,
                end_sec=float(len(words)),
                mean_confidence=sum(active_confidences) / len(active_confidences),
                min_confidence=min(active_confidences),
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


def test_medical_entity_gating_keeps_only_medical_review_spans() -> None:
    record = make_medical_entity_record()
    gated = apply_medical_entity_review_gating(
        record,
        [
            MedicalEntityMention(text="cough", entity_type="symptom"),
            MedicalEntityMention(text="aspirin", entity_type="medication"),
        ],
    )

    assert len(gated.uncertain_spans) == 1
    assert gated.uncertain_spans[0].text == "cough"
    assert gated.uncertain_spans[0].trigger_reason == MEDICAL_ENTITY_TRIGGER_REASON

    patient_meta = gated.asr_words[0].metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]
    reports_meta = gated.asr_words[1].metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]
    cough_meta = gated.asr_words[2].metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]
    aspirin_meta = gated.asr_words[4].metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]

    assert patient_meta["display_confidence_level"] == "neutral"
    assert reports_meta["display_confidence_level"] == "neutral"
    assert cough_meta["display_confidence_level"] == "red"
    assert aspirin_meta["display_confidence_level"] == "green"

    sample = build_review_sample(gated)
    assert sample.words[1].review_required is False
    assert sample.words[2].review_required is True
    assert sample.words[4].review_required is False
    assert sample.review_policy["target_scope"] == "llm_identified_medical_entities_only"


def test_misaligned_llm_char_offsets_fall_back_to_entity_text() -> None:
    record = make_record_from_words(
        ["eating", "drinking", "okay", "weakness", "tingling"],
    )
    gated = apply_medical_entity_review_gating(
        record,
        [
            MedicalEntityMention(
                text="weakness",
                entity_type="symptom",
                start_char=0,
                end_char=6,
            )
        ],
    )

    review = [
        word.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]["is_medical_entity"]
        for word in gated.asr_words
    ]
    assert review == [False, False, False, True, False]


def test_chinese_entity_matching_ignores_asr_spaces_and_preserves_word_range() -> None:
    record = make_record_from_words(
        ["患者", "左", "侧", "肢体", "震颤"],
        confidences=[0.95, 0.75, 0.72, 0.45, 0.93],
    )

    gated = apply_medical_entity_review_gating(
        record,
        [MedicalEntityMention(text="左侧肢体", entity_type="anatomy")],
    )

    metadata = gated.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]
    assert metadata["matched_entity_count"] == 1
    assert metadata["medical_words_colored"] == [1, 2, 3]
    assert len(gated.uncertain_spans) == 1
    assert gated.uncertain_spans[0].start_word_index == 1
    assert gated.uncertain_spans[0].end_word_index == 4
    assert gated.uncertain_spans[0].text == "左侧肢体"


def test_medical_entity_postprocess_trims_question_words_and_drops_false_positives() -> None:
    record = make_record_from_words(
        [
            "do",
            "you",
            "mean",
            "diarrhea",
            "and",
            "what",
            "kind",
            "of",
            "food",
            "noticed",
            "any",
            "other",
        ],
        confidences=[0.92, 0.91, 0.9, 0.41, 0.9, 0.9, 0.9, 0.9, 0.3, 0.9, 0.9, 0.9],
    )

    gated = apply_medical_entity_review_gating(
        record,
        [
            MedicalEntityMention(text="do you mean diarrhea", entity_type="symptom"),
            MedicalEntityMention(text="what kind of food", entity_type="other_medical_term"),
            MedicalEntityMention(text="noticed any other", entity_type="other_medical_term"),
        ],
    )

    display_levels = [
        word.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]["display_confidence_level"]
        for word in gated.asr_words
    ]
    assert display_levels[0:3] == ["neutral", "neutral", "neutral"]
    assert display_levels[3] == "red"
    assert display_levels[4:] == ["neutral"] * 8
    assert [span.text for span in gated.uncertain_spans] == ["diarrhea"]

    review_metadata = gated.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]
    assert review_metadata["trimmed_entity_count"] >= 1
    assert review_metadata["dropped_nonmedical_entity_count"] >= 2


def test_medical_entity_keyword_fallback_adds_missed_obvious_terms() -> None:
    record = make_record_from_words(
        [
            "patient",
            "reports",
            "diarrheea",
            "with",
            "tummy",
            "pain",
            "and",
            "loose",
            "stools",
            "after",
            "vomiting",
        ],
        confidences=[0.95, 0.88, 0.4, 0.89, 0.52, 0.45, 0.9, 0.5, 0.48, 0.9, 0.43],
    )

    gated = apply_medical_entity_review_gating(record, [])

    medical_words = [
        word.text
        for word in gated.asr_words
        if word.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]["is_medical_entity"]
    ]
    assert medical_words == ["diarrheea", "tummy", "pain", "loose", "stools", "vomiting"]

    neutral_words = {
        word.text
        for word in gated.asr_words
        if word.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY]["display_confidence_level"]
        == "neutral"
    }
    assert {"patient", "reports", "with", "and", "after"}.issubset(neutral_words)
    assert [span.text for span in gated.uncertain_spans] == [
        "diarrheea",
        "tummy pain",
        "loose stools",
        "vomiting",
    ]
    assert (
        gated.metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY][
            "keyword_fallback_entity_count"
        ]
        == 4
    )


def test_medical_entity_gating_limits_span_candidates_to_medical_entities() -> None:
    gated = apply_medical_entity_review_gating(
        make_medical_entity_record(),
        [
            MedicalEntityMention(text="cough", entity_type="symptom"),
            MedicalEntityMention(text="aspirin", entity_type="medication"),
        ],
    )

    with_candidates = attach_nbest_candidates_to_record(
        gated,
        [{"text": "patient reports chest pain and aspirin", "rank": 1, "score": -0.2}],
    )

    span_alternatives = [
        alternative
        for alternative in with_candidates.asr_alternatives
        if alternative.scope == "span"
    ]
    assert len(span_alternatives) == 1
    assert span_alternatives[0].span_id == "medspan_001"
    assert span_alternatives[0].text == "chest pain"
    assert with_candidates.uncertain_spans[0].alternative_ids == [
        span_alternatives[0].alternative_id
    ]


def test_review_html_uses_neutral_display_for_non_medical_words() -> None:
    gated = apply_medical_entity_review_gating(
        make_medical_entity_record(),
        [
            MedicalEntityMention(text="cough", entity_type="symptom"),
            MedicalEntityMention(text="aspirin", entity_type="medication"),
        ],
    )
    sample = build_review_sample(gated)
    html = build_review_html([sample], title="T038 医学实体审阅 demo", interactive=True)

    assert "word neutral" in html
    assert "medical-entity" in html
    assert "医学实体优先" in html
    assert "非重点上下文" in html


def test_llm_entity_json_parser_accepts_fenced_json() -> None:
    payload = parse_json_object(
        '```json\n{"entities":[{"text":"chest pain","entity_type":"symptom"}]}\n```'
    )
    entities = coerce_medical_entity_mentions(payload)

    assert len(entities) == 1
    assert entities[0].text == "chest pain"
    assert entities[0].entity_type == "symptom"


def test_llm_entity_json_parser_accepts_valid_payload_before_extra_data() -> None:
    payload = parse_json_object(
        '{"entities":[{"text":"tremor","entity_type":"symptom"}]}\n'
        '{"note":"duplicate explanation payload"}'
    )
    entities = coerce_medical_entity_mentions(payload)

    assert len(entities) == 1
    assert entities[0].text == "tremor"


def test_project_env_file_resolves_llm_config_without_global_env(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "API_KEY=local-test-key",
                "BASE_URL=https://llmapi.paratera.com/v1/",
                "MODEL_ID=Qwen3-Next-80B-A3B-Instruct",
            ]
        ),
        encoding="utf-8",
    )

    env_values = read_project_env_file(env_path)
    config = resolve_llm_api_config(
        dotenv_values=env_values,
        use_os_environ=False,
    )

    assert config.api_key == "local-test-key"
    assert config.base_url == "https://llmapi.paratera.com/v1/"
    assert config.model_name == "Qwen3-Next-80B-A3B-Instruct"
    assert (
        endpoint_for_chat_completions(config.base_url)
        == "https://llmapi.paratera.com/v1/chat/completions"
    )
