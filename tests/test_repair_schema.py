import pytest
from pydantic import ValidationError

from clinical_asr_robustness.repair import (
    DoctorFeedback,
    DoctorFeedbackAction,
    FeedbackSource,
    InteractiveRepairRecord,
    RepairCandidate,
    RepairDecision,
    RepairDecisionType,
    RepairSpan,
    read_repair_jsonl,
    write_repair_jsonl,
)
from clinical_asr_robustness.schema import ErrorTag


def test_interactive_repair_record_roundtrip(tmp_path) -> None:
    record = InteractiveRepairRecord(
        repair_id="repair_demo_001",
        sample_id="demo_001",
        dataset="synthetic_demo",
        noisy_transcript="Patient chest pain.",
        spans=[
            RepairSpan(
                span_id="span_001",
                original_text="Patient chest pain",
                start_char=0,
                end_char=18,
                error_tags=[ErrorTag.NEGATION_OMISSION],
            )
        ],
        repair_candidates=[
            RepairCandidate(
                candidate_id="cand_001",
                span_id="span_001",
                rank=1,
                original_text="Patient chest pain",
                replacement_text="Patient denies chest pain",
                confidence=0.93,
                method_source="rule_negation_demo",
                rationale="根据参考否定表达规则恢复 denies。",
                error_tags=[ErrorTag.NEGATION_OMISSION],
            )
        ],
        decisions=[
            RepairDecision(
                span_id="span_001",
                decision_type=RepairDecisionType.AUTO_ACCEPTED,
                selected_candidate_id="cand_001",
                final_text="Patient denies chest pain",
                confidence=0.93,
                threshold=0.90,
            )
        ],
        final_repaired_transcript="Patient denies chest pain.",
        confidence_threshold=0.90,
        method_name="rule_demo",
    )

    assert record.candidates_for_span("span_001")[0].candidate_id == "cand_001"
    assert record.decisions_requiring_review() == []

    path = tmp_path / "repair.jsonl"
    write_repair_jsonl([record], path)
    assert read_repair_jsonl(path) == [record]


def test_low_confidence_doctor_feedback_path() -> None:
    feedback = DoctorFeedback(
        action=DoctorFeedbackAction.EDIT_TEXT,
        feedback_source=FeedbackSource.CLINICAL_REVIEWER,
        actor_role="medical_reviewer",
        edited_text="Patient denies chest pain",
        comment="选择候选后微调用词。",
    )
    decision = RepairDecision(
        span_id="span_001",
        decision_type=RepairDecisionType.DOCTOR_EDITED,
        final_text="Patient denies chest pain",
        confidence=0.62,
        threshold=0.85,
        doctor_feedback=feedback,
    )

    assert decision.requires_doctor_review is True
    assert decision.doctor_feedback is not None
    assert decision.doctor_feedback.edited_text == "Patient denies chest pain"


def test_repair_schema_validates_confidence_and_references() -> None:
    with pytest.raises(ValidationError):
        RepairCandidate(
            candidate_id="cand_bad",
            span_id="span_001",
            rank=1,
            original_text="pain",
            replacement_text="chest pain",
            confidence=1.5,
            method_source="demo",
        )

    with pytest.raises(ValidationError):
        InteractiveRepairRecord(
            repair_id="repair_bad",
            sample_id="demo_001",
            dataset="synthetic_demo",
            noisy_transcript="Patient chest pain.",
            spans=[RepairSpan(span_id="span_001", original_text="Patient chest pain")],
            repair_candidates=[
                RepairCandidate(
                    candidate_id="cand_001",
                    span_id="unknown_span",
                    rank=1,
                    original_text="Patient chest pain",
                    replacement_text="Patient denies chest pain",
                    confidence=0.8,
                    method_source="demo",
                )
            ],
            final_repaired_transcript="Patient chest pain.",
        )


def test_doctor_feedback_requires_payload_for_select_and_edit() -> None:
    with pytest.raises(ValidationError):
        DoctorFeedback(action=DoctorFeedbackAction.SELECT_CANDIDATE)

    with pytest.raises(ValidationError):
        DoctorFeedback(action=DoctorFeedbackAction.EDIT_TEXT)

    with pytest.raises(ValidationError):
        RepairDecision(
            span_id="span_001",
            decision_type=RepairDecisionType.AUTO_ACCEPTED,
            final_text="Patient denies chest pain",
            confidence=0.95,
            threshold=0.90,
        )
