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
    EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1,
    EVIDENCE_WEIGHTING_ROLE_BLIND,
    INPUT_UNIT_CONSULTATION,
    INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
    INPUT_VARIANT_NOISY_ASR,
    INPUT_VARIANT_REFERENCE_ORACLE,
    STATUS_GENERATED,
    STATUS_PROMPT_READY,
    build_case_summary_input_bundles,
    build_case_summary_messages,
    coerce_case_summary_payload,
    evidence_weighting_metadata,
    run_case_summary_generation,
)
from clinical_asr_robustness.medical_entity_review import parse_json_object
from clinical_asr_robustness.review_workflow import (
    ConfirmationStatus,
    ConfirmedTranscriptRecord,
    write_confirmed_transcripts_jsonl,
)


def make_asr_record(
    *,
    record_id: str,
    sample_id: str,
    consultation_id: str,
    channel: SourceChannel,
    transcript: str,
    reference_transcript_path: str | None = None,
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
        reference_textgrid_path=(
            None
            if reference_transcript_path is not None
            else f"data/external/primock57/transcripts/{sample_id}.TextGrid"
        ),
        reference_transcript_path=reference_transcript_path,
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


def test_reference_bundle_deduplicates_shared_consultation_pointer() -> None:
    reference_path = "data/processed/demo/proxy_reference.txt"
    records = [
        make_asr_record(
            record_id=f"window_{index}",
            sample_id=f"demo_window_{index}",
            consultation_id="demo_consultation",
            channel=SourceChannel.MIXED,
            transcript=f"noisy window {index}",
            reference_transcript_path=reference_path,
        )
        for index in range(3)
    ]

    bundle = build_case_summary_input_bundles(
        records,
        input_variant=INPUT_VARIANT_REFERENCE_ORACLE,
        transcript_getter=lambda _: "shared proxy reference",
    )[0]

    assert bundle.input_transcript.count("shared proxy reference") == 1


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
    assert "字段条件化的说话人软权重" in prompt_text
    assert "assessment_mentioned: doctor=1.5, patient=0.8" in prompt_text
    assert "医生的提问不算事实陈述" in prompt_text
    assert "不得静默用高权重一方覆盖另一方" in prompt_text


def test_case_summary_prompt_supports_role_blind_ablation() -> None:
    bundle = build_case_summary_input_bundles(
        [
            make_asr_record(
                record_id="doctor_record",
                sample_id="demo_doctor",
                consultation_id="demo_consultation",
                channel=SourceChannel.DOCTOR,
                transcript="we will arrange an ultrasound",
            ),
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript="i have abdominal pain",
            ),
        ]
    )[0]

    messages = build_case_summary_messages(
        bundle,
        evidence_weighting_profile=EVIDENCE_WEIGHTING_ROLE_BLIND,
    )
    prompt_text = "\n".join(message["content"] for message in messages)
    metadata = evidence_weighting_metadata(EVIDENCE_WEIGHTING_ROLE_BLIND)

    assert "role_blind 消融" in prompt_text
    assert "field_conditioned_v1" not in prompt_text
    assert metadata["mode"] == "role_blind_ablation"
    assert metadata["field_role_weights"]["plan_mentioned"] == {
        "doctor": 1.0,
        "patient": 1.0,
    }


def test_case_summary_prompt_is_input_variant_aware() -> None:
    bundle = build_case_summary_input_bundles(
        [
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript="patient reports no fever",
            )
        ],
        input_variant=INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
        transcript_getter=lambda _record: "patient confirms no fever",
    )[0]

    messages = build_case_summary_messages(bundle, summary_language="zh")
    prompt_text = "\n".join(message["content"] for message in messages)

    assert "confirmed transcript" in prompt_text
    assert "input_variant: confirmed_transcript" in prompt_text
    assert "patient confirms no fever" in prompt_text
    assert "请从下面的 noisy ASR transcript" not in prompt_text


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
    assert output_records[0]["evidence_weighting"]["profile"] == (
        EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1
    )
    assert summary["evidence_weighting"]["profile"] == (
        EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1
    )
    assert summary["evidence_weighting"]["gold_facts_unchanged"] is True
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


def test_run_case_summary_generation_retries_one_malformed_response(
    tmp_path: Path,
) -> None:
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
    responses = iter(
        [
            '{"case_summary": {"chief_complaint": "diarrhea"',
            json.dumps({"case_summary": {"chief_complaint": "diarrhea"}}),
        ]
    )

    summary = run_case_summary_generation(
        asr_input_jsonl=asr_path,
        output_records_jsonl=records_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
        run_llm=True,
        llm_content_generator=lambda _messages: next(responses),
        max_attempts=2,
    )

    output_record = json.loads(records_path.read_text(encoding="utf-8").splitlines()[0])
    assert summary["status_counts"] == {STATUS_GENERATED: 1}
    assert output_record["case_summary"]["chief_complaint"] == "diarrhea"


def test_run_case_summary_generation_aligns_three_input_variants(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.txt"
    reference_path.write_text("patient has chest pain and no fever", encoding="utf-8")
    asr_path = tmp_path / "asr.jsonl"
    confirmed_path = tmp_path / "confirmed.jsonl"
    records_path = tmp_path / "records.jsonl"
    summary_path = tmp_path / "summary.json"
    write_asr_confidence_jsonl(
        [
            make_asr_record(
                record_id="patient_record",
                sample_id="demo_patient",
                consultation_id="demo_consultation",
                channel=SourceChannel.PATIENT,
                transcript="patient has chess pain",
                reference_transcript_path=str(reference_path),
            )
        ],
        asr_path,
    )
    write_confirmed_transcripts_jsonl(
        [
            ConfirmedTranscriptRecord(
                record_id="patient_record",
                sample_id="demo_patient",
                dataset="primock57",
                split="seed_asr_v0",
                consultation_id="demo_consultation",
                source_channel=SourceChannel.PATIENT,
                asr_transcript="patient has chess pain",
                confirmed_transcript="patient has chest pain",
                confirmation_status=ConfirmationStatus.CONFIRMED,
            )
        ],
        confirmed_path,
    )

    summary = run_case_summary_generation(
        asr_input_jsonl=asr_path,
        confirmed_input_jsonl=confirmed_path,
        output_records_jsonl=records_path,
        output_summary_json=summary_path,
        project_root=tmp_path,
        input_variants=(
            INPUT_VARIANT_NOISY_ASR,
            INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
            INPUT_VARIANT_REFERENCE_ORACLE,
        ),
        run_llm=False,
    )

    output_records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records_by_variant = {record["input_variant"]: record for record in output_records}
    serialized_summary = summary_path.read_text(encoding="utf-8")

    assert summary["record_count"] == 3
    assert summary["records_skipped"] == 0
    assert summary["input_variant_counts"] == {
        INPUT_VARIANT_NOISY_ASR: 1,
        INPUT_VARIANT_CONFIRMED_TRANSCRIPT: 1,
        INPUT_VARIANT_REFERENCE_ORACLE: 1,
    }
    assert set(records_by_variant) == {
        INPUT_VARIANT_NOISY_ASR,
        INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
        INPUT_VARIANT_REFERENCE_ORACLE,
    }
    assert "patient has chess pain" in records_by_variant[
        INPUT_VARIANT_NOISY_ASR
    ]["input_transcript"]
    assert "patient has chest pain" in records_by_variant[
        INPUT_VARIANT_CONFIRMED_TRANSCRIPT
    ]["input_transcript"]
    assert "no fever" in records_by_variant[INPUT_VARIANT_REFERENCE_ORACLE][
        "input_transcript"
    ]
    assert records_by_variant[INPUT_VARIANT_REFERENCE_ORACLE]["prompt_version"]
    assert "patient has chest pain and no fever" not in serialized_summary
