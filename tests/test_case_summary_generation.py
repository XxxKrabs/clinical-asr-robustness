from __future__ import annotations

import json
from pathlib import Path

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRWord,
    SourceChannel,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.case_summary_generation import (
    INPUT_UNIT_CONSULTATION,
    STATUS_GENERATED,
    STATUS_PROMPT_READY,
    build_case_summary_input_bundles,
    build_case_summary_messages,
    coerce_case_summary_payload,
    run_case_summary_generation,
)
from clinical_asr_robustness.medical_entity_review import parse_json_object


def make_asr_record(
    *,
    record_id: str,
    sample_id: str,
    consultation_id: str,
    channel: SourceChannel,
    transcript: str,
) -> ASRConfidenceRecord:
    words = transcript.split()
    return ASRConfidenceRecord(
        record_id=record_id,
        sample_id=sample_id,
        dataset="primock57",
        split="seed_asr_v0",
        consultation_id=consultation_id,
        source_channel=channel,
        audio_filepath=f"data/external/primock57/audio/{sample_id}.wav",
        duration_sec=float(len(words)),
        reference_textgrid_path=f"data/external/primock57/transcripts/{sample_id}.TextGrid",
        reference_text_included=False,
        asr_transcript=transcript,
        asr_confidence=0.88,
        asr_words=[
            ASRWord(
                word_index=index,
                text=word,
                start_sec=float(index),
                end_sec=float(index + 1),
                confidence=0.88,
            )
            for index, word in enumerate(words)
        ],
        uncertain_spans=[],
        model=ASRModelInfo(
            model_name="fake_nemo",
            model_path="data/external/asr_models/nemo/fake.nemo",
            model_class="FakeModel",
        ),
        decoding=ASRDecodingConfig(strategy="greedy", batch_size=1, device="cpu"),
        confidence=ASRConfidenceConfig(aggregation="mean"),
        alignment=AlignmentDiagnostics(
            transcript_word_count=len(words),
            word_timestamp_count=len(words),
            word_confidence_count=len(words),
            asr_word_count=len(words),
            paired_word_count=len(words),
        ),
    )


def test_consultation_bundle_combines_channel_transcripts() -> None:
    records = [
        make_asr_record(
            record_id="patient_record",
            sample_id="demo_patient",
            consultation_id="demo_consultation",
            channel=SourceChannel.PATIENT,
            transcript="i have tummy pain",
        ),
        make_asr_record(
            record_id="doctor_record",
            sample_id="demo_doctor",
            consultation_id="demo_consultation",
            channel=SourceChannel.DOCTOR,
            transcript="how long have you had diarrhea",
        ),
    ]

    bundles = build_case_summary_input_bundles(records)

    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.input_unit == INPUT_UNIT_CONSULTATION
    assert bundle.consultation_id == "demo_consultation"
    assert "[doctor | sample_id=demo_doctor]" in bundle.input_transcript
    assert "[patient | sample_id=demo_patient]" in bundle.input_transcript
    assert bundle.source_channels == ["doctor", "patient"]


def test_case_summary_prompt_mentions_noisy_asr_and_safety() -> None:
    bundle = build_case_summary_input_bundles(
        [
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript="i have tummy pain and vomiting",
            )
        ]
    )[0]

    messages = build_case_summary_messages(bundle, summary_language="zh")
    prompt_text = "\n".join(message["content"] for message in messages)

    assert "ASR noisy transcript" in prompt_text
    assert "noisy ASR transcript" in prompt_text
    assert "病例摘要" in prompt_text
    assert "不要新增事实" in prompt_text
    assert "uncertainty_notes" in prompt_text


def test_coerce_case_summary_payload_accepts_fenced_json() -> None:
    payload = parse_json_object(
        """```json
        {
          "case_summary": {
            "summary_text": "患者诉腹痛和呕吐。",
            "chief_complaint": "腹痛、呕吐",
            "symptoms": ["腹痛", "呕吐"],
            "negatives": "无便血",
            "plan": ["原文提到补液"]
          }
        }
        ```"""
    )

    summary = coerce_case_summary_payload(payload)

    assert summary.chief_complaint == "腹痛、呕吐"
    assert summary.symptoms == ["腹痛", "呕吐"]
    assert summary.negated_or_absent_symptoms == ["无便血"]
    assert summary.plan_mentioned == ["原文提到补液"]


def test_run_case_summary_generation_dry_run_writes_outputs(tmp_path: Path) -> None:
    transcript = "patient has tummy pain and vomiting"
    asr_path = tmp_path / "asr.jsonl"
    records_path = tmp_path / "records.jsonl"
    summary_path = tmp_path / "summary.json"
    write_asr_confidence_jsonl(
        [
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript=transcript,
            )
        ],
        asr_path,
    )

    summary = run_case_summary_generation(
        asr_input_jsonl=asr_path,
        output_records_jsonl=records_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
        run_llm=False,
    )

    output_records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized_summary = summary_path.read_text(encoding="utf-8")

    assert summary["record_count"] == 1
    assert summary["status_counts"] == {STATUS_PROMPT_READY: 1}
    assert output_records[0]["status"] == STATUS_PROMPT_READY
    assert output_records[0]["case_summary"] is None
    assert transcript in output_records[0]["input_transcript"]
    assert transcript not in serialized_summary


def test_run_case_summary_generation_with_stub_llm(tmp_path: Path) -> None:
    asr_path = tmp_path / "asr.jsonl"
    records_path = tmp_path / "records.jsonl"
    summary_path = tmp_path / "summary.json"
    write_asr_confidence_jsonl(
        [
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript="patient has diarrhea",
            )
        ],
        asr_path,
    )

    summary = run_case_summary_generation(
        asr_input_jsonl=asr_path,
        output_records_jsonl=records_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
        run_llm=True,
        llm_content_generator=lambda _messages: json.dumps(
            {
                "case_summary": {
                    "summary_text": "患者诉腹泻。",
                    "chief_complaint": "腹泻",
                    "symptoms": ["腹泻"],
                    "uncertainty_notes": [],
                }
            },
            ensure_ascii=False,
        ),
    )

    output_record = json.loads(records_path.read_text(encoding="utf-8").splitlines()[0])

    assert summary["status_counts"] == {STATUS_GENERATED: 1}
    assert output_record["status"] == STATUS_GENERATED
    assert output_record["case_summary"]["chief_complaint"] == "腹泻"
