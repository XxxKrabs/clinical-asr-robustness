from __future__ import annotations

import pytest

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceConfig,
    ASRDecodingConfig,
    ASRModelInfo,
    ConfidenceLevel,
    ConfidenceThresholds,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.nemo_confidence_export import (
    apply_demo_quantile_risk_levels,
    build_asr_confidence_record,
    configure_ctc_greedy_confidence,
    reclassify_confidence_record,
    summarize_confidence_values,
)
from scripts.export_nemo_asr_confidence import total_manifest_audio_duration_sec


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
    word_confidence = [0.96, 0.85, 0.42]
    token_confidence = [0.9, 0.8]
    frame_confidence = [0.9, 0.8, 0.7]


class FakeChineseHypothesis:
    text = "患者咳嗽"
    timestamp = {
        "word": [
            {"word": text, "start": index * 0.2, "end": (index + 1) * 0.2}
            for index, text in enumerate("患者咳嗽")
        ]
    }
    word_confidence = [0.96, 0.95, 0.42, 0.40]
    token_confidence = []
    frame_confidence = []


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


def test_total_manifest_audio_duration_uses_window_durations() -> None:
    assert total_manifest_audio_duration_sec(
        [
            {"duration": 30.0, "source_duration_sec": 280.704},
            {"duration_sec": 10.661375, "source_duration_sec": 280.704},
            {"duration": None},
        ]
    ) == pytest.approx(40.661375)


def test_chinese_auto_units_preserve_surface_without_spaces() -> None:
    record = build_asr_confidence_record(
        manifest_record={
            "sample_id": "remote_programming_40:case_demo:mixed",
            "dataset": "remote_programming_40",
            "source_channel": "mixed",
            "text_unit_mode": "auto",
        },
        hypothesis=FakeChineseHypothesis(),
        model_info={"model_name": "fake_hybrid_zh"},
        decoding_config={"strategy": "greedy"},
    )

    assert [word.text for word in record.asr_words] == list("患者咳嗽")
    assert [word.char_start for word in record.asr_words] == [0, 1, 2, 3]
    assert record.asr_segments[0].text == "患者咳嗽"
    assert record.uncertain_spans[0].text == "咳嗽"
    assert record.alignment.metadata["text_unit_mode_active"] == "timestamp"


def test_window_record_uses_source_audio_and_absolute_timestamps() -> None:
    manifest_record = {
        "sample_id": "remote_programming_40:case_demo:0001",
        "parent_sample_id": "remote_programming_40:case_demo:mixed",
        "unit_id": "case_demo:window_0001",
        "dataset": "remote_programming_40",
        "source_channel": "mixed",
        "text_unit_mode": "auto",
        "audio_filepath": "data/interim/remote_programming_40/audio_16k/window.wav",
        "duration_sec": 30.0,
        "source_audio_filepath": "data/raw/remote_programming_40/case_demo.mp3",
        "source_audio_sha256": "abc123",
        "source_duration_sec": 300.0,
        "source_start_sec": 30.0,
        "source_end_sec": 60.0,
    }

    record = build_asr_confidence_record(
        manifest_record=manifest_record,
        hypothesis=FakeChineseHypothesis(),
        model_info={"model_name": "fake_hybrid_zh"},
        decoding_config={"strategy": "greedy"},
    )

    assert record.audio_filepath == "data/raw/remote_programming_40/case_demo.mp3"
    assert record.duration_sec == 300.0
    assert record.asr_words[0].start_sec == pytest.approx(30.0)
    assert record.asr_words[-1].end_sec == pytest.approx(30.8)
    source = record.metadata["source_manifest"]
    assert source["asr_input_audio_filepath"].endswith("window.wav")
    assert source["timestamp_reference"] == "source_audio_absolute"
    assert source["timestamp_offset_sec"] == 30.0


def test_reclassify_confidence_record_rebuilds_three_risk_levels() -> None:
    record = make_record()
    updated = reclassify_confidence_record(
        record,
        ConfidenceThresholds(green_min=0.90, yellow_min=0.80),
    )

    assert [word.confidence_level for word in updated.asr_words] == [
        ConfidenceLevel.GREEN,
        ConfidenceLevel.YELLOW,
        ConfidenceLevel.RED,
        ConfidenceLevel.UNKNOWN,
    ]
    assert updated.confidence.thresholds.green_min == 0.90
    assert updated.confidence.thresholds.yellow_min == 0.80
    assert updated.uncertain_spans[0].start_word_index == 1
    assert updated.metadata["confidence_threshold_reclassification"][
        "clinical_calibration"
    ] is False
    assert record.metadata.get("confidence_threshold_reclassification") is None


def test_demo_quantile_policy_is_rank_based_and_marked_uncalibrated() -> None:
    updated = apply_demo_quantile_risk_levels([make_record()])[0]

    levels = [word.confidence_level for word in updated.asr_words]
    assert levels.count(ConfidenceLevel.RED) == 1
    assert levels.count(ConfidenceLevel.YELLOW) == 1
    assert levels.count(ConfidenceLevel.GREEN) == 1
    assert levels.count(ConfidenceLevel.UNKNOWN) == 1
    policy = updated.confidence.metadata["risk_level_policy"]
    assert policy["policy"] == "demo_quantile_v0"
    assert policy["calibrated"] is False


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
