from __future__ import annotations

import numpy as np
import pytest

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceConfig,
    ASRDecodingConfig,
    ASRModelInfo,
    ConfidenceLevel,
)
from clinical_asr_robustness.ctc_word_confidence import (
    compute_ctc_word_confidence,
    frame_confidence_from_probabilities,
    read_ctc_frame_distribution_artifact,
    save_ctc_frame_distribution_artifact,
    word_confidence_metadata,
)
from clinical_asr_robustness.nemo_confidence_export import build_asr_confidence_record


class FakeHypothesis:
    text = "chest pain"
    score = -0.1
    timestamp = {
        "word": [
            {"word": "chest", "start": 0.0, "end": 0.5},
            {"word": "pain", "start": 0.5, "end": 0.9},
        ]
    }
    word_confidence = [0.99, 0.99]


def log_probs(rows: list[list[float]]) -> np.ndarray:
    probabilities = np.asarray(rows, dtype=np.float64)
    probabilities = probabilities / probabilities.sum(axis=1, keepdims=True)
    return np.log(probabilities)


def test_entropy_confidence_is_higher_for_peaked_posterior() -> None:
    probabilities = np.asarray(
        [
            [0.97, 0.01, 0.01, 0.01],
            [0.40, 0.30, 0.20, 0.10],
        ],
        dtype=np.float64,
    )

    confidence = frame_confidence_from_probabilities(
        probabilities,
        method_name="entropy",
        entropy_type="tsallis",
        alpha=0.33,
        entropy_norm="lin",
    )

    assert confidence[0] > confidence[1]
    assert 0.0 <= confidence[1] <= confidence[0] <= 1.0


def test_ctc_frame_entropy_aggregates_to_word_confidence() -> None:
    # token ids: 0=▁ch, 1=est, 2=▁pain, 3=<blank>
    frame_log_probs = log_probs(
        [
            [0.97, 0.01, 0.01, 0.01],
            [0.96, 0.02, 0.01, 0.01],
            [0.02, 0.95, 0.02, 0.01],
            [0.01, 0.01, 0.01, 0.97],
            [0.20, 0.20, 0.40, 0.20],
            [0.15, 0.25, 0.35, 0.25],
        ]
    )

    result = compute_ctc_word_confidence(
        frame_log_probs,
        score_type="log_probs",
        blank_id=3,
        transcript="chest pain",
        token_texts_by_id={0: "▁ch", 1: "est", 2: "▁pain", 3: "<blank>"},
        method_name="entropy",
        entropy_type="tsallis",
        alpha=0.33,
        entropy_norm="lin",
        token_aggregation="mean",
        word_aggregation="min",
    )

    assert [span.token_id for span in result.token_spans] == [0, 1, 2]
    assert result.word_token_spans == [(0, 2), (2, 3)]
    assert len(result.word_confidences) == 2
    assert result.word_confidences[0] is not None
    assert result.word_confidences[1] is not None
    assert result.word_confidences[0] > result.word_confidences[1]


def test_ctc_surface_alignment_supports_chinese_character_units() -> None:
    # token 0 同时覆盖“患”“者”，项目层允许两个可审阅字符共享同一 acoustic 证据。
    frame_log_probs = log_probs(
        [
            [0.96, 0.01, 0.01, 0.02],
            [0.01, 0.95, 0.02, 0.02],
            [0.01, 0.02, 0.95, 0.02],
        ]
    )

    result = compute_ctc_word_confidence(
        frame_log_probs,
        score_type="log_probs",
        blank_id=3,
        transcript="患者咳嗽",
        transcript_units=list("患者咳嗽"),
        token_texts_by_id={0: "▁患者", 1: "▁咳", 2: "嗽", 3: "<blank>"},
    )

    assert result.word_token_spans == [(0, 1), (0, 1), (1, 2), (2, 3)]
    assert all(value is not None for value in result.word_confidences)
    assert result.metadata["transcript_unit_source"] == "explicit_language_aware_units"


def test_ctc_frame_artifact_roundtrip(tmp_path) -> None:
    frame_log_probs = log_probs(
        [
            [0.90, 0.05, 0.03, 0.02],
            [0.05, 0.90, 0.03, 0.02],
            [0.02, 0.02, 0.02, 0.94],
        ]
    )
    result = compute_ctc_word_confidence(
        frame_log_probs,
        score_type="log_probs",
        blank_id=3,
        transcript="chest",
        token_texts_by_id={0: "▁ch", 1: "est", 2: "x", 3: "<blank>"},
    )
    artifact = tmp_path / "ctc_frames.npz"

    save_ctc_frame_distribution_artifact(
        artifact,
        frame_values=frame_log_probs,
        value_type="log_probs",
        result=result,
        transcript="chest",
        metadata={"sample_id": "demo"},
    )
    loaded = read_ctc_frame_distribution_artifact(artifact)

    assert loaded.value_type == "log_probs"
    assert loaded.frame_values.shape == frame_log_probs.shape
    assert loaded.metadata["sample_id"] == "demo"
    assert loaded.metadata["result_metadata"]["emitted_token_count"] == 2


def test_build_record_can_use_ctc_word_confidence_override() -> None:
    word_confidences = [0.92, 0.31]
    metadata_by_word = word_confidence_metadata(
        compute_ctc_word_confidence(
            log_probs(
                [
                    [0.90, 0.05, 0.03, 0.02],
                    [0.05, 0.90, 0.03, 0.02],
                    [0.02, 0.02, 0.02, 0.94],
                    [0.20, 0.20, 0.40, 0.20],
                ]
            ),
            score_type="log_probs",
            blank_id=3,
            transcript="chest pain",
            token_texts_by_id={0: "▁ch", 1: "est", 2: "▁pain", 3: "<blank>"},
        )
    )

    record = build_asr_confidence_record(
        manifest_record={
            "sample_id": "primock57:demo:patient",
            "dataset": "primock57",
            "source_channel": "patient",
            "reference_text_included": False,
        },
        hypothesis=FakeHypothesis(),
        model_info=ASRModelInfo(model_name="fake_nemo"),
        decoding_config=ASRDecodingConfig(strategy="greedy", batch_size=1),
        confidence_config=ASRConfidenceConfig(
            method_name="entropy",
            source_field="ctc_frame_distribution.word_confidence",
        ),
        word_confidences_override=word_confidences,
        word_confidence_source="ctc_frame_distribution.word_confidence",
        word_confidence_metadata_by_index=metadata_by_word,
    )

    assert [word.confidence for word in record.asr_words] == word_confidences
    assert record.asr_words[1].confidence_level == ConfidenceLevel.RED
    assert record.asr_words[1].confidence_source == "ctc_frame_distribution.word_confidence"
    assert "ctc_word_confidence" in record.asr_words[1].metadata
    assert record.uncertain_spans[0].text == "pain"
    assert record.alignment.metadata["confidence_override_used"] is True


def test_build_record_requires_override_support_is_wired() -> None:
    with pytest.raises(TypeError):
        # This assertion protects the T043 integration: if the adapter signature loses
        # the override argument, tests fail loudly instead of silently using NeMo word_confidence.
        build_asr_confidence_record(unknown_override=True)  # type: ignore[call-arg]
