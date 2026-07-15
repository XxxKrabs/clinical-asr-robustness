from __future__ import annotations

import csv
import json

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRSegment,
    ASRWord,
    SourceChannel,
    UncertainSpan,
)
from clinical_asr_robustness.nemo_confidence_export import build_asr_confidence_record
from clinical_asr_robustness.review_workflow import (
    ConfirmationStatus,
    DoctorFeedbackEntry,
    DoctorFeedbackLog,
    ReviewFeedbackAction,
    apply_feedback_to_record,
    build_review_conversations,
    build_review_html,
    build_review_sample,
    read_feedback_entries_jsonl,
    read_review_conversations_jsonl,
    read_review_samples_jsonl,
    write_feedback_entries_jsonl,
    write_review_conversations_jsonl,
    write_review_samples_jsonl,
    write_review_spans_csv,
)


def make_review_record() -> ASRConfidenceRecord:
    span_alternative = ASRAlternative(
        alternative_id="alt_span_001_rank_001",
        scope=AlternativeScope.SPAN,
        rank=1,
        text="reports chest pain",
        span_id="span_001",
        start_word_index=1,
        end_word_index=3,
        score=-0.3,
        confidence=0.61,
        source="nemo_beam",
        alignment_method="sequence_nbest_diff",
    )
    return ASRConfidenceRecord(
        record_id="nemo_entropy_primock57_demo_patient",
        sample_id="primock57:demo:patient",
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id="demo",
        source_channel=SourceChannel.PATIENT,
        audio_filepath="data/external/primock57/audio/demo_patient.wav",
        duration_sec=1.6,
        reference_textgrid_path="data/external/primock57/transcripts/demo_patient.TextGrid",
        reference_text_included=False,
        asr_transcript="patient reports cough now",
        asr_confidence=0.77,
        asr_words=[
            ASRWord(
                word_index=0,
                text="patient",
                start_sec=0.0,
                end_sec=0.4,
                confidence=0.93,
            ),
            ASRWord(
                word_index=1,
                text="reports",
                start_sec=0.4,
                end_sec=0.8,
                confidence=0.77,
            ),
            ASRWord(
                word_index=2,
                text="cough",
                start_sec=0.8,
                end_sec=1.1,
                confidence=0.42,
            ),
            ASRWord(
                word_index=3,
                text="now",
                start_sec=1.1,
                end_sec=1.3,
                confidence=0.94,
            ),
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text="patient reports cough now",
                start_word_index=0,
                end_word_index=4,
                start_sec=0.0,
                end_sec=1.3,
                confidence=0.77,
                confidence_aggregation="mean",
            )
        ],
        uncertain_spans=[
            UncertainSpan(
                span_id="span_001",
                text="reports cough",
                start_word_index=1,
                end_word_index=3,
                start_sec=0.4,
                end_sec=1.1,
                mean_confidence=0.595,
                min_confidence=0.42,
                alternative_ids=["alt_span_001_rank_001"],
            )
        ],
        asr_alternatives=[span_alternative],
        model=ASRModelInfo(
            model_name="fake_nemo",
            model_path="data/external/asr_models/nemo/fake.nemo",
            model_class="FakeModel",
        ),
        decoding=ASRDecodingConfig(
            strategy="greedy",
            batch_size=1,
            device="cpu",
        ),
        confidence=ASRConfidenceConfig(aggregation="mean"),
        alignment=AlignmentDiagnostics(
            transcript_word_count=4,
            word_timestamp_count=4,
            word_confidence_count=4,
            asr_word_count=4,
            paired_word_count=4,
        ),
    )


def test_build_review_sample_and_export_jsonl_csv(tmp_path) -> None:
    sample = build_review_sample(make_review_record())

    assert sample.words[2].confidence_level == "red"
    assert sample.words[2].review_required is True
    assert sample.uncertain_spans[0].alternatives[0].text == "reports chest pain"
    assert sample.review_policy["generated_by"] == "T030"

    jsonl_path = tmp_path / "review_samples.jsonl"
    csv_path = tmp_path / "review_spans.csv"
    write_review_samples_jsonl([sample], jsonl_path)
    write_review_spans_csv([sample], csv_path)

    assert read_review_samples_jsonl(jsonl_path)[0].sample_id == "primock57:demo:patient"
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig")))
    assert rows[0]["span_id"] == "span_001"
    assert rows[0]["candidate_count"] == "1"
    assert "reports chest pain" in rows[0]["candidate_texts"]


def test_review_conversation_groups_windows_and_splits_speaker_turns(tmp_path) -> None:
    first_payload = make_review_record().model_dump(mode="json")
    for index, word in enumerate(first_payload["asr_words"]):
        word["speaker_label"] = "spk_0" if index < 2 else "spk_1"
    first = ASRConfidenceRecord.model_validate(first_payload)

    second_payload = make_review_record().model_dump(mode="json")
    second_payload["record_id"] = "nemo_entropy_primock57_demo_patient_2"
    second_payload["sample_id"] = "primock57:demo:patient:0002"
    for word in second_payload["asr_words"]:
        word["start_sec"] += 1.4
        word["end_sec"] += 1.4
        word["speaker_label"] = "spk_1"
    for segment in second_payload["asr_segments"]:
        segment["start_sec"] += 1.4
        segment["end_sec"] += 1.4
        segment["speaker_label"] = "spk_1"
    second = ASRConfidenceRecord.model_validate(second_payload)

    conversations = build_review_conversations(
        [build_review_sample(first), build_review_sample(second)]
    )

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.consultation_id == "demo"
    assert conversation.sample_ids == [
        "primock57:demo:patient",
        "primock57:demo:patient:0002",
    ]
    assert conversation.diarization_status == "complete"
    assert [turn.speaker_label for turn in conversation.speaker_turns] == [
        "spk_0",
        "spk_1",
    ]
    assert len(conversation.speaker_turns[1].slices) == 2
    assert "[spk_0]" in conversation.conversation_transcript

    output = tmp_path / "review_conversations.jsonl"
    write_review_conversations_jsonl(conversations, output)
    loaded = read_review_conversations_jsonl(output)
    assert loaded[0].conversation_id == "primock57:demo:conversation"
    assert len(loaded[0].review_samples) == 2


def test_apply_feedback_select_alternative_generates_confirmed_transcript() -> None:
    record = make_review_record()
    feedback = DoctorFeedbackEntry(
        record_id=record.record_id,
        sample_id=record.sample_id,
        span_id="span_001",
        action=ReviewFeedbackAction.SELECT_ALTERNATIVE,
        selected_alternative_id="alt_span_001_rank_001",
        original_text="reports cough",
    )

    confirmed = apply_feedback_to_record(record, [feedback])

    assert confirmed.confirmed_transcript == "patient reports chest pain now"
    assert confirmed.confirmation_status == ConfirmationStatus.CONFIRMED
    assert confirmed.applied_spans[0].resolved is True
    assert confirmed.action_summary == {"select_alternative": 1}



def test_apply_feedback_select_word_alternative_replaces_only_target_word() -> None:
    payload = make_review_record().model_dump(mode="json")
    payload["asr_alternatives"].append(
        {
            "alternative_id": "alt_word_001_rank_001",
            "scope": "word",
            "rank": 2,
            "text": "chest pain",
            "span_id": "span_001",
            "start_word_index": 2,
            "end_word_index": 3,
            "source": "llm_word_candidate",
            "alignment_method": "llm_target_word_context_lexicon",
            "metadata": {"generated_by": "T044", "target_word_text": "cough"},
        }
    )
    payload["uncertain_spans"][0]["alternative_ids"].append("alt_word_001_rank_001")
    record = ASRConfidenceRecord.model_validate(payload)
    feedback = DoctorFeedbackEntry(
        record_id=record.record_id,
        sample_id=record.sample_id,
        span_id="span_001",
        action=ReviewFeedbackAction.SELECT_ALTERNATIVE,
        selected_alternative_id="alt_word_001_rank_001",
        original_text="reports cough",
    )

    confirmed = apply_feedback_to_record(record, [feedback])

    assert confirmed.confirmed_transcript == "patient reports chest pain now"
    assert confirmed.applied_spans[0].confirmed_text == "reports chest pain"
    assert confirmed.applied_spans[0].selected_alternative_text == "chest pain"
    assert confirmed.applied_spans[0].metadata["alternative_scope"] == "word"
def test_apply_feedback_manual_edit_and_reject_policies() -> None:
    record = make_review_record()
    manual = DoctorFeedbackEntry(
        record_id=record.record_id,
        span_id="span_001",
        action=ReviewFeedbackAction.MANUAL_EDIT,
        manual_text="reports dry cough",
    )
    manual_confirmed = apply_feedback_to_record(record, [manual])
    assert manual_confirmed.confirmed_transcript == "patient reports dry cough now"
    assert manual_confirmed.confirmation_status == ConfirmationStatus.CONFIRMED

    reject = DoctorFeedbackEntry(
        record_id=record.record_id,
        span_id="span_001",
        action=ReviewFeedbackAction.REJECT,
        note="candidate mismatch",
    )
    rejected = apply_feedback_to_record(record, [reject])
    assert rejected.confirmed_transcript == "patient reports cough now"
    assert rejected.confirmation_status == ConfirmationStatus.NEEDS_REVIEW
    assert rejected.unresolved_span_ids == ["span_001"]


def test_chinese_feedback_replay_uses_character_offsets_without_inserting_spaces() -> None:
    class ChineseHypothesis:
        text = "患者咳嗽"
        timestamp = {
            "word": [
                {"word": text, "start": index * 0.2, "end": (index + 1) * 0.2}
                for index, text in enumerate("患者咳嗽")
            ]
        }
        word_confidence = [0.96, 0.95, 0.42, 0.40]

    record = build_asr_confidence_record(
        manifest_record={
            "sample_id": "remote_programming_40:case_demo:mixed",
            "dataset": "remote_programming_40",
            "source_channel": "mixed",
            "text_unit_mode": "auto",
        },
        hypothesis=ChineseHypothesis(),
        model_info={"model_name": "fake_hybrid_zh"},
        decoding_config={"strategy": "greedy"},
    )
    feedback = DoctorFeedbackEntry(
        record_id=record.record_id,
        span_id=record.uncertain_spans[0].span_id,
        action=ReviewFeedbackAction.MANUAL_EDIT,
        manual_text="头晕",
    )

    confirmed = apply_feedback_to_record(record, [feedback])

    assert confirmed.confirmed_transcript == "患者头晕"
    assert " " not in confirmed.confirmed_transcript


def test_feedback_jsonl_accepts_entry_and_log_wrapper(tmp_path) -> None:
    entry = DoctorFeedbackEntry(
        record_id="record-1",
        span_id="span_001",
        action=ReviewFeedbackAction.ACCEPT_ASR,
    )
    entry_path = tmp_path / "feedback_entries.jsonl"
    write_feedback_entries_jsonl([entry], entry_path)
    assert read_feedback_entries_jsonl(entry_path)[0].action == ReviewFeedbackAction.ACCEPT_ASR

    log_path = tmp_path / "feedback_log.jsonl"
    log = DoctorFeedbackLog(entries=[entry])
    log_path.write_text(
        json.dumps(log.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert read_feedback_entries_jsonl(log_path)[0].span_id == "span_001"


def test_feedback_jsonl_accepts_utf8_bom(tmp_path) -> None:
    entry = DoctorFeedbackEntry(
        record_id="record-1",
        span_id="span_001",
        action=ReviewFeedbackAction.ACCEPT_ASR,
    )
    payload = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n"
    feedback_path = tmp_path / "feedback_entries_bom.jsonl"
    feedback_path.write_text(payload, encoding="utf-8-sig")

    entries = read_feedback_entries_jsonl(feedback_path)

    assert entries[0].record_id == "record-1"
    assert entries[0].action == ReviewFeedbackAction.ACCEPT_ASR


def test_build_review_html_contains_audio_and_mutually_exclusive_decisions(
    tmp_path,
) -> None:
    sample = build_review_sample(make_review_record())
    html = build_review_html(
        [sample],
        title="T036 ASR demo",
        interactive=True,
        html_output_path=tmp_path / "outputs/review.html",
        project_root=tmp_path,
    )

    assert "T036" in html
    assert "select_alternative" in html
    assert "doctor_feedback_log.jsonl" in html
    assert "reports chest pain" in html
    assert 'id="conversation-trigger"' in html
    assert 'id="conversation-list"' in html
    assert "setActiveSample" in html
    assert "groupSamplesByConversation" in html
    assert 'class="conversation-turns"' in html
    assert "完整对话" in html
    assert "speakerIdentity" in html
    assert "position: sticky" in html
    assert "保存并下一个" in html
    assert 'id="review-audio"' in html
    assert 'class="audio-cue-button"' in html
    assert 'id="play-span-audio"' in html
    assert "playAudioClip" in html
    assert "../data/external/primock57/audio/demo_patient.wav" in html
    assert 'name="decision"' in html
    assert 'data-decision-action="select_alternative"' in html
    assert 'name="candidate"' not in html
    assert 'name="action"' not in html
    assert "audio_play_count" in html
