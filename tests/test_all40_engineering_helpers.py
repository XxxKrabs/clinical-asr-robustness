from pathlib import Path

import pytest

from clinical_asr_robustness.svg_charts import (
    write_grouped_bar_svg,
    write_stacked_bar_svg,
)
from scripts.assemble_full_audio_from_windows import group_windows, validate_windows
from scripts.evaluate_chinese_all40_engineering import build_aggregate, case_id_from_values


def test_case_id_from_values_supports_manifest_and_sample_id() -> None:
    assert case_id_from_values("case_0068") == "case_0068"
    assert case_id_from_values(None, "remote_programming_40:case_0021:mixed:0001") == (
        "case_0021"
    )
    assert case_id_from_values(None, "unknown") is None


def test_window_grouping_and_continuity_validation() -> None:
    rows = [
        {
            "parent_sample_id": "remote_programming_40:case_0068:mixed",
            "source_start_sec": 30.0,
            "source_end_sec": 60.0,
            "sample_rate_hz": 16_000,
            "channels": 1,
        },
        {
            "parent_sample_id": "remote_programming_40:case_0068:mixed",
            "source_start_sec": 0.0,
            "source_end_sec": 30.0,
            "sample_rate_hz": 16_000,
            "channels": 1,
        },
    ]
    grouped = group_windows(rows)
    windows = grouped["remote_programming_40:case_0068:mixed"]
    assert windows[0]["source_start_sec"] == 0.0
    assert validate_windows(
        "case_0068",
        windows,
        tolerance_sec=0.002,
    ) == (16_000, 1, 0.0, 60.0)

    windows[1]["source_start_sec"] = 30.01
    with pytest.raises(ValueError, match="时间轴不连续"):
        validate_windows("case_0068", windows, tolerance_sec=0.002)


def test_svg_helpers_support_wide_rotated_and_stacked_charts(tmp_path: Path) -> None:
    grouped_path = tmp_path / "grouped.svg"
    write_grouped_bar_svg(
        grouped_path,
        labels=["0001", "0002"],
        series=[("count", [1.0, 2.0], "#123456")],
        title="wide",
        y_label="count",
        width=1200,
        height=560,
        rotate_labels=True,
        show_values=False,
    )
    grouped = grouped_path.read_text(encoding="utf-8")
    assert 'width="1200"' in grouped
    assert "rotate(45" in grouped

    stacked_path = tmp_path / "stacked.svg"
    write_stacked_bar_svg(
        stacked_path,
        labels=["0001", "0002"],
        series=[
            ("green", [0.7, 0.6], "#00aa00"),
            ("yellow", [0.2, 0.3], "#aaaa00"),
            ("red", [0.1, 0.1], "#aa0000"),
        ],
        title="risk",
        y_label="share",
    )
    stacked = stacked_path.read_text(encoding="utf-8")
    assert "green" in stacked
    assert "red" in stacked
    assert stacked.count("<rect") >= 7


def test_all40_aggregate_exposes_fallback_and_candidate_coverage() -> None:
    row = {
        "source_duration_sec": 60.0,
        "window_count": 2,
        "asr_record_count": 2,
        "empty_asr_record_count": 0,
        "timestamp_order_violation_count": 0,
        "missing_word_timestamp_count": 1,
        "green_words": 7,
        "yellow_words": 2,
        "red_words": 1,
        "mean_word_confidence": 0.9,
        "nbest_record_count": 2,
        "nbest_beam_count": 9,
        "nbest_multiple_record_count": 2,
        "detected_speakers": 2,
        "acoustic_speaker_mapping_coverage": 0.8,
        "resolved_speaker_mapping_coverage": 0.9,
    }
    runs = {
        "confidence": {
            "confidence_distribution": {
                "ctc_frame_distribution": {"unaligned_fallback_count": 1}
            }
        },
        "candidates": {
            "validation": {"total_uncertain_spans": 5, "spans_with_alternatives": 2}
        },
    }

    aggregate = build_aggregate([row], runs)

    assert aggregate["unaligned_confidence_fallback_count"] == 1
    assert aggregate["candidate_span_coverage"] == pytest.approx(0.4)
