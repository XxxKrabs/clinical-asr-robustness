import pytest

from clinical_asr_robustness.metrics import relative_recovery, term_recall, word_error_rate
from clinical_asr_robustness.schema import ErrorTag, TranscriptSample, TranscriptVariant


def test_transcript_sample_schema() -> None:
    sample = TranscriptSample(
        sample_id="demo_001",
        dataset="demo",
        clean_transcript="Patient denies chest pain.",
        noisy_transcript="Patient chest pain.",
        error_tags=[ErrorTag.NEGATION_OMISSION],
    )

    assert sample.get_variant(TranscriptVariant.CLEAN) == "Patient denies chest pain."
    assert sample.error_tags == [ErrorTag.NEGATION_OMISSION]


def test_basic_metrics() -> None:
    assert word_error_rate("patient denies chest pain", "patient chest pain") > 0
    assert term_recall(["chest pain"], "Patient denies chest pain.") == 1.0
    assert relative_recovery(clean_score=1.0, noisy_score=0.4, repaired_score=0.7) == pytest.approx(
        0.5
    )
