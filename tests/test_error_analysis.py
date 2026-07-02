import pytest

from clinical_asr_robustness.error_analysis import (
    EditType,
    analyze_transcript_pair,
    tokenize_for_alignment,
)


def test_tokenize_marks_medical_concepts_and_negation() -> None:
    tokens = tokenize_for_alignment("[doctor] no chest pain 25 mg")
    by_text = {token.text: token for token in tokens}

    assert by_text["[doctor]"].is_medical_concept is False
    assert by_text["no"].is_medical_concept is True
    assert by_text["chest"].is_medical_concept is True
    assert by_text["pain"].is_medical_concept is True
    assert by_text["25"].is_medical_concept is True
    assert by_text["mg"].is_medical_concept is True


def test_analyze_transcript_pair_counts_selected_error_types() -> None:
    result = analyze_transcript_pair(
        reference_text="patient has iron deficiency anemia",
        hypothesis_text="patient has iron severe anemia",
    )

    assert result.error_type_counts == {
        EditType.SUBSTITUTION.value: 1,
        EditType.DELETION.value: 0,
        EditType.INSERTION.value: 0,
    }
    assert result.reference_token_count == 5
    assert result.wer == pytest.approx(1 / 5)
    assert result.mc_reference_token_count == 3
    assert result.mc_wer == pytest.approx(1 / 3)
    assert len(result.edit_spans) == 1
    assert result.edit_spans[0].error_type == EditType.SUBSTITUTION
    assert result.edit_spans[0].medical_concept_hit is True


def test_analyze_transcript_pair_counts_deletion_and_insertion() -> None:
    deletion_result = analyze_transcript_pair(
        reference_text="take ferrous sulfate daily",
        hypothesis_text="take ferrous daily",
    )
    insertion_result = analyze_transcript_pair(
        reference_text="take iron",
        hypothesis_text="take iron daily",
    )

    assert deletion_result.error_type_counts[EditType.DELETION.value] == 1
    assert deletion_result.wer == pytest.approx(1 / 4)
    assert deletion_result.mc_deletion_count == 1
    assert insertion_result.error_type_counts[EditType.INSERTION.value] == 1
    assert insertion_result.wer == pytest.approx(1 / 2)
