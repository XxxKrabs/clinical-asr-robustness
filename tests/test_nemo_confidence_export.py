from __future__ import annotations

import pytest

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceConfig,
    ASRDecodingConfig,
    ASRModelInfo,
    ConfidenceLevel,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.nemo_confidence_export import (
    build_asr_confidence_record,
    configure_ctc_greedy_confidence,
    summarize_confidence_values,
)


class FakeHypothesis:
    text = "patient reports cough now"
    score = -0.25
    timestamp = {
        "word": [
            {"word": "patient", "start": 0.0, "end": 0.4},
            {"word": "reports", "start": 0.4, "end": 0.8},
            {"word": "cough", "start": 0.8, "end": 1.1},
            {"word": "now", "start": 1.1, "end": 1.3},
            {"word": "", "start": 1.3, "end": 1.3},
        ],
        "segment": [{"segment": "patient reports cough now", "start": 0.0, "end": 1.3}],
    }
    word_confidence = [0.93, 0.77, 0.42]
    token_confidence = [0.9, 0.8]
    frame_confidence = [0.9, 0.8, 0.7]


def make_manifest_record() -> dict:
    return {
        "sample_id": "primock57:demo:patient",
        "dataset": "primock57",
        "split": "seed_asr_v0",
        "consultation_id": "demo",
        "source_channel": "patient",
        "audio_filepath": "data/external/primock57/audio/demo_patient.wav",
        "duration": 1.3,
        "reference_textgrid_path": "data/external/primock57/transcripts/demo_patient.TextGrid",
        "reference_text_included": False,
        "text_is_placeholder": True,
    }


def make_record():
    return build_asr_confidence_record(
        manifest_record=make_manifest_record(),
        hypothesis=FakeHypothesis(),
        model_info=ASRModelInfo(
            model_name="fake_nemo",
            model_path="data/external/asr_models/nemo/fake.nemo",
            model_class="FakeModel",
        ),
        decoding_config=ASRDecodingConfig(
            strategy="greedy",
            batch_size=1,
            device="cpu",
        ),
        confidence_config=ASRConfidenceConfig(aggregation="mean"),
        runtime={"device": "cpu"},
        segment_max_words=2,
    )


def test_build_asr_confidence_record_aligns_words_and_records_mismatch() -> None:
    record = make_record()

    assert record.record_id == "nemo_entropy_primock57_demo_patient"
    assert record.asr_transcript == "patient reports cough now"
    assert len(record.asr_words) == 4
    assert record.asr_words[0].confidence_level == ConfidenceLevel.GREEN
    assert record.asr_words[1].confidence_level == ConfidenceLevel.YELLOW
    assert record.asr_words[2].confidence_level == ConfidenceLevel.RED
    assert record.asr_words[3].confidence_level == ConfidenceLevel.UNKNOWN
    assert record.asr_words[3].alignment_status == "missing_confidence"

    assert record.alignment.transcript_word_count == 4
    assert record.alignment.word_timestamp_count == 5
    assert record.alignment.word_confidence_count == 3
    assert record.alignment.paired_word_count == 3
    assert record.alignment.missing_confidence_word_indices == [3]
    assert len(record.alignment.dropped_extra_word_timestamps) == 1
    assert record.alignment.dropped_extra_word_timestamps[0]["raw_index"] == 4


def test_build_asr_confidence_record_derives_segments_and_uncertain_spans(tmp_path) -> None:
    record = make_record()

    assert len(record.asr_segments) == 2
    assert record.asr_segments[0].text == "patient reports"
    assert record.asr_segments[0].confidence_level == ConfidenceLevel.GREEN
    assert record.asr_segments[1].text == "cough now"
    assert record.asr_segments[1].confidence_level == ConfidenceLevel.RED

    assert len(record.uncertain_spans) == 1
    span = record.uncertain_spans[0]
    assert span.text == "reports cough now"
    assert span.start_word_index == 1
    assert span.end_word_index == 4
    assert span.confidence_level == ConfidenceLevel.RED
    assert span.trigger_reason == "low_confidence"

    output = tmp_path / "asr_confidence.jsonl"
    write_asr_confidence_jsonl([record], output)
    assert read_asr_confidence_jsonl(output) == [record]


def test_summarize_confidence_values_reports_distribution() -> None:
    summary = summarize_confidence_values([0.1, 0.3, None, 0.9])

    assert summary["count"] == 3
    assert summary["min"] == 0.1
    assert summary["max"] == 0.9
    assert summary["mean"] == pytest.approx(1.3 / 3)
    assert summary["median"] == 0.3
    assert summary["p95"] == pytest.approx(0.84)


def test_configure_ctc_greedy_confidence_exposes_method_parameters() -> None:
    pytest.importorskip("omegaconf")
    from omegaconf import OmegaConf

    class FakeModel:
        def __init__(self) -> None:
            self.cfg = OmegaConf.create(
                {
                    "decoding": {
                        "strategy": "greedy",
                        "compute_timestamps": False,
                        "confidence_cfg": {},
                        "greedy": {
                            "preserve_alignments": False,
                            "compute_timestamps": False,
                            "preserve_frame_confidence": False,
                            "confidence_method_cfg": None,
                        },
                    }
                }
            )
            self.decoding_config = None

        def change_decoding_strategy(self, decoding_cfg, verbose=False) -> None:
            self.decoding_config = decoding_cfg

    model = FakeModel()
    config = configure_ctc_greedy_confidence(
        model,
        method_name="max_prob",
        alpha=1.0,
        aggregation="max",
    )

    assert model.decoding_config is not None
    assert config["compute_timestamps"] is True
    assert config["confidence_cfg"]["aggregation"] == "max"
    assert config["confidence_cfg"]["method_cfg"] == {
        "name": "max_prob",
        "alpha": 1.0,
    }
