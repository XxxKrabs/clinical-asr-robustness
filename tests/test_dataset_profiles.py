from pathlib import Path

import pytest

from clinical_asr_robustness.dataset_profiles import (
    PRIMOCK57,
    REMOTE_PROGRAMMING_40,
    infer_dataset_id,
    resolve_dataset_profile,
)


def test_explicit_and_alias_dataset_routing() -> None:
    assert infer_dataset_id(dataset="primock57") == PRIMOCK57
    assert infer_dataset_id(dataset="zh") == REMOTE_PROGRAMMING_40


def test_manifest_record_routes_chinese_dataset() -> None:
    records = [{"dataset": "remote_programming_40", "sample_id": "case_0001"}]
    profile = resolve_dataset_profile(records=records)
    assert profile.language == "zh-CN"
    assert "Parakeet-Hybrid" in profile.default_model_path.name
    assert profile.text_unit_mode == "auto"
    assert profile.default_manifest.name == "remote_programming_40_asr_16k_windows.jsonl"
    assert profile.word_confidence_source == "ctc_frame_distribution"
    assert profile.save_frame_distributions is True
    assert profile.llm_candidate_prompt_profile == "zh_dbs_remote_programming_v1"
    assert profile.llm_candidate_context_scope == "complete_consultation"
    assert profile.run_llm_candidates_default is True
    assert profile.medical_candidate_lexicon_path.name.endswith(
        "remote_programming_40.json"
    )


def test_missing_or_legacy_manifest_keeps_english_default() -> None:
    profile = resolve_dataset_profile(manifest_path=Path("missing.jsonl"))
    assert profile.dataset_id == PRIMOCK57
    assert profile.language == "en"
    assert profile.word_confidence_source == "nemo_word_confidence"
    assert profile.save_frame_distributions is False
    assert profile.run_llm_candidates_default is False


def test_mixed_dataset_manifest_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能混用多个数据集"):
        infer_dataset_id(
            records=[{"dataset": PRIMOCK57}, {"dataset": REMOTE_PROGRAMMING_40}]
        )
