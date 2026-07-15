from __future__ import annotations

import pytest

from clinical_asr_robustness.chinese_pilot_evaluation import (
    binary_calibration_metrics,
    case_summary_pair_metrics,
    critical_information_metrics,
    hypothesis_error_flags,
    normalize_transcript,
    proxy_fact_textual_recall,
)


def test_normalize_transcript_keeps_cjk_latin_and_digits() -> None:
    assert normalize_transcript("左侧 DBS：2.5 mA！") == "左侧dbs25ma"


def test_hypothesis_error_flags_separate_deletions() -> None:
    flags, counts = hypothesis_error_flags("左侧震颤", "右侧颤")

    assert len(flags) == len("右侧颤")
    assert any(flags)
    assert counts["deletion_chars"] == 1


def test_critical_information_score_renormalizes_available_components() -> None:
    result = critical_information_metrics(
        "左侧震颤，幅度 2.5 mA",
        "左侧震颤，幅度 2.5 mA",
        terms_by_category={"symptom": ["震颤"]},
    )

    assert result["critical_information_preservation_score"] == pytest.approx(1.0)
    assert result["parameter_value_recall"] == pytest.approx(1.0)


def test_proxy_fact_textual_recall_uses_evidence_terms() -> None:
    result = proxy_fact_textual_recall(
        [
            {
                "category": "symptom",
                "criticality": "important",
                "evidence_terms": ["震颤", "手抖"],
            },
            {
                "category": "medication",
                "criticality": "routine",
                "evidence_terms": ["美多芭"],
            },
        ],
        "患者仍有手抖。",
    )

    assert result["proxy_fact_textual_recall"] == pytest.approx(0.5)
    assert result["critical_proxy_fact_textual_recall"] == pytest.approx(1.0)


def test_case_summary_pair_metrics_tracks_critical_fields() -> None:
    result = case_summary_pair_metrics(
        {
            "symptoms": ["左手震颤"],
            "medications": ["美多芭"],
            "plan_mentioned": ["一个月后复诊"],
        },
        {
            "symptoms": ["左手震颤明显"],
            "medications": ["美多芭"],
            "plan_mentioned": [],
        },
    )

    assert result["fact_recall"] == pytest.approx(2 / 3)
    assert result["critical_fact_recall"] == pytest.approx(0.5)


def test_binary_calibration_metrics() -> None:
    result = binary_calibration_metrics([1.0, 0.0], [0.8, 0.2], bins=2)

    assert result["word_count"] == 2
    assert result["brier"] == pytest.approx(0.04)
    assert result["ece"] == pytest.approx(0.2)
