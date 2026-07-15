from __future__ import annotations

import json

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRSegment,
    ASRWord,
    SourceChannel,
)
from clinical_asr_robustness.speaker_diarization import (
    SpeakerDiarizationModelInfo,
    SpeakerDiarizationRecord,
    apply_diarization_to_asr_record,
    diarization_segments_to_rttm,
    map_diarization_to_asr_records,
    map_interval_to_speaker,
    parse_sortformer_output_lines,
    read_speaker_diarization_jsonl,
    write_speaker_diarization_jsonl,
)
from clinical_asr_robustness.speaker_semantic_resolution import (
    apply_semantic_speaker_decisions,
    build_semantic_speaker_prompts,
    parse_semantic_speaker_decisions,
)


def make_diarization_record() -> SpeakerDiarizationRecord:
    segments = parse_sortformer_output_lines(
        [
            "0.000 0.800 speaker_0",
            "0.900 2.000 speaker_1",
        ]
    )
    return SpeakerDiarizationRecord(
        record_id="sortformer_demo_case_0001",
        dataset="demo",
        split="pilot",
        consultation_id="case_0001",
        audio_filepath="data/interim/demo/case_0001.wav",
        source_audio_filepath="data/raw/demo/case_0001.mp3",
        duration_sec=2.0,
        segments=segments,
        speaker_labels=["speaker_0", "speaker_1"],
        model=SpeakerDiarizationModelInfo(
            model_name="diar_streaming_sortformer_4spk-v2.1",
            model_path="data/external/asr_models/nemo/model.nemo",
            model_version="v2.1",
            checkpoint_sha256="a" * 64,
        ),
    )


def make_asr_record() -> ASRConfidenceRecord:
    return ASRConfidenceRecord(
        record_id="asr_demo_case_0001_window_0000",
        sample_id="demo:case_0001:mixed:0000",
        dataset="demo",
        split="pilot",
        consultation_id="case_0001",
        source_channel=SourceChannel.MIXED,
        audio_filepath="data/raw/demo/case_0001.mp3",
        duration_sec=2.0,
        asr_transcript="甲乙",
        asr_words=[
            ASRWord(
                word_index=0,
                text="甲",
                start_sec=0.1,
                end_sec=0.4,
                confidence=0.9,
                char_start=0,
                char_end=1,
            ),
            ASRWord(
                word_index=1,
                text="乙",
                start_sec=1.1,
                end_sec=1.4,
                confidence=0.9,
                char_start=1,
                char_end=2,
            ),
        ],
        asr_segments=[
            ASRSegment(
                segment_id="seg_001",
                text="甲乙",
                start_word_index=0,
                end_word_index=2,
                start_sec=0.1,
                end_sec=1.4,
                confidence=0.9,
            )
        ],
        model=ASRModelInfo(model_name="fake_asr", model_class="FakeASR"),
        decoding=ASRDecodingConfig(strategy="greedy", batch_size=1, device="cpu"),
        confidence=ASRConfidenceConfig(),
        alignment=AlignmentDiagnostics(
            transcript_word_count=2,
            word_timestamp_count=2,
            word_confidence_count=2,
            asr_word_count=2,
            paired_word_count=2,
        ),
        metadata={
            "source_manifest": {
                "timestamp_reference": "source_audio_absolute",
                "timestamp_offset_sec": 0.0,
            }
        },
    )


def make_three_word_asr_record() -> ASRConfidenceRecord:
    record = make_asr_record().model_copy(deep=True)
    record.asr_transcript = "甲中乙"
    record.asr_words = [
        ASRWord(
            word_index=index,
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
            confidence=0.9,
            char_start=index,
            char_end=index + 1,
        )
        for index, (text, start_sec, end_sec) in enumerate(
            [("甲", 0.1, 0.2), ("中", 0.5, 0.6), ("乙", 0.9, 1.0)]
        )
    ]
    record.asr_segments = [
        ASRSegment(
            segment_id="seg_001",
            text="甲中乙",
            start_word_index=0,
            end_word_index=3,
            start_sec=0.1,
            end_sec=1.0,
            confidence=0.9,
        )
    ]
    record.alignment.transcript_word_count = 3
    record.alignment.word_timestamp_count = 3
    record.alignment.word_confidence_count = 3
    record.alignment.asr_word_count = 3
    record.alignment.paired_word_count = 3
    return ASRConfidenceRecord.model_validate(record.model_dump(mode="json"))


def make_custom_diarization_record(lines: list[str]) -> SpeakerDiarizationRecord:
    record = make_diarization_record().model_copy(deep=True)
    record.segments = parse_sortformer_output_lines(lines)
    record.speaker_labels = sorted({segment.speaker_label for segment in record.segments})
    return SpeakerDiarizationRecord.model_validate(record.model_dump(mode="json"))


def make_single_word_window(
    index: int,
    text: str,
    start_sec: float,
    end_sec: float,
) -> ASRConfidenceRecord:
    record = make_asr_record().model_copy(deep=True)
    record.record_id = f"asr_demo_case_0001_window_{index:04d}"
    record.sample_id = f"demo:case_0001:mixed:{index:04d}"
    record.audio_filepath = f"data/interim/demo/window_{index:04d}.wav"
    record.asr_transcript = text
    record.asr_words = [
        ASRWord(
            word_index=0,
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
            confidence=0.9,
            char_start=0,
            char_end=1,
        )
    ]
    record.asr_segments = [
        ASRSegment(
            segment_id="seg_001",
            text=text,
            start_word_index=0,
            end_word_index=1,
            start_sec=start_sec,
            end_sec=end_sec,
            confidence=0.9,
        )
    ]
    record.alignment.transcript_word_count = 1
    record.alignment.word_timestamp_count = 1
    record.alignment.word_confidence_count = 1
    record.alignment.asr_word_count = 1
    record.alignment.paired_word_count = 1
    return ASRConfidenceRecord.model_validate(record.model_dump(mode="json"))


def test_parse_sortformer_lines_and_write_rttm() -> None:
    segments = parse_sortformer_output_lines(
        ["1.250 2.000 speaker_1", "0.000 1.000 speaker_0"]
    )

    assert [segment.segment_id for segment in segments] == [
        "diar_seg_00001",
        "diar_seg_00002",
    ]
    assert [segment.speaker_label for segment in segments] == ["speaker_0", "speaker_1"]
    assert diarization_segments_to_rttm("case_0001", segments) == [
        "SPEAKER case_0001 1 0.000 1.000 <NA> <NA> speaker_0 <NA> <NA>",
        "SPEAKER case_0001 1 1.250 0.750 <NA> <NA> speaker_1 <NA> <NA>",
    ]


def test_map_interval_is_conservative_for_overlapped_speech() -> None:
    segments = parse_sortformer_output_lines(
        ["0.000 1.000 speaker_0", "0.800 2.000 speaker_1"]
    )

    direct = map_interval_to_speaker(0.2, 0.5, segments)
    ambiguous = map_interval_to_speaker(0.85, 0.95, segments)
    missing = map_interval_to_speaker(None, None, segments)

    assert direct.speaker_label == "speaker_0"
    assert direct.status == "mapped_max_overlap"
    assert ambiguous.speaker_label is None
    assert ambiguous.status == "ambiguous_overlap"
    assert missing.status == "missing_timestamp"


def test_apply_diarization_maps_words_and_marks_mixed_segment() -> None:
    mapped = apply_diarization_to_asr_record(
        make_asr_record(),
        make_diarization_record(),
    )

    assert [word.speaker_label for word in mapped.asr_words] == ["speaker_0", "speaker_1"]
    assert mapped.asr_segments[0].speaker_label == "mixed"
    assert mapped.metadata["diarization"]["mapping_status"] == "complete"
    assert mapped.metadata["diarization"]["mapping_coverage"] == 1.0
    assert mapped.metadata["diarization"]["speaker_roles_assigned"] is False


def test_batch_mapping_bridges_short_same_speaker_no_overlap_gap() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_0"]
    )

    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )

    assert [word.speaker_label for word in mapped.asr_words] == [
        "speaker_0",
        "speaker_0",
        "speaker_0",
    ]
    evidence = mapped.asr_words[1].metadata["diarization"]
    assert evidence["speaker_label"] is None
    assert evidence["mapping_status"] == "no_overlap"
    assert evidence["smoothing_status"] == "bridged_same_speaker_context"
    assert evidence["smoothing"]["ambiguous_overlap_bridged"] is False
    assert mapped.metadata["diarization"]["mapped_word_count"] == 2
    assert mapped.metadata["diarization"]["resolved_word_count"] == 3
    assert mapped.metadata["diarization"]["smoothed_word_count"] == 1
    assert mapped.asr_segments[0].speaker_label == "speaker_0"


def test_batch_mapping_does_not_bridge_ambiguous_overlap() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 1.200 speaker_0", "0.450 0.650 speaker_1"]
    )

    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )

    assert mapped.asr_words[1].speaker_label is None
    evidence = mapped.asr_words[1].metadata["diarization"]
    assert evidence["mapping_status"] == "ambiguous_overlap"
    assert "smoothing_status" not in evidence


def test_batch_mapping_does_not_bridge_different_speakers() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_1"]
    )

    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )

    assert [word.speaker_label for word in mapped.asr_words] == [
        "speaker_0",
        None,
        "speaker_1",
    ]
    assert mapped.metadata["diarization"]["smoothed_word_count"] == 0


def test_batch_mapping_bridges_across_asr_window_boundaries() -> None:
    records = [
        make_single_word_window(0, "甲", 0.1, 0.2),
        make_single_word_window(1, "中", 0.5, 0.6),
        make_single_word_window(2, "乙", 0.9, 1.0),
    ]
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_0"]
    )

    mapped = map_diarization_to_asr_records(records, [diarization])

    assert [record.asr_words[0].speaker_label for record in mapped] == [
        "speaker_0",
        "speaker_0",
        "speaker_0",
    ]
    assert mapped[1].metadata["diarization"]["smoothed_word_count"] == 1


def test_semantic_speaker_prompt_covers_remaining_gap() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_1"]
    )
    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )

    [prompt] = build_semantic_speaker_prompts([mapped])

    assert len(prompt.gaps) == 1
    gap = prompt.gaps[0]
    assert gap.left_speaker_label == "speaker_0"
    assert gap.right_speaker_label == "speaker_1"
    assert gap.allowed_speaker_labels == ["speaker_0", "speaker_1"]
    assert gap.original_mapping_statuses == ["no_overlap"]
    assert gap.gap_id in prompt.messages[1]["content"]


def test_force_semantic_speaker_resolution_preserves_acoustic_evidence() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_1"]
    )
    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )
    [prompt] = build_semantic_speaker_prompts([mapped])
    content = (
        '{"decisions":[{"gap_id":"'
        + prompt.gaps[0].gap_id
        + '","speaker_label":"speaker_0","confidence":0.45,'
        '"reason_code":"uncertain_best_guess"}]}'
    )
    decisions = parse_semantic_speaker_decisions(content, prompt=prompt)

    [resolved] = apply_semantic_speaker_decisions(
        [mapped],
        prompt=prompt,
        decisions=decisions,
        force_resolve_all=True,
        llm_metadata={"model_name": "stub"},
    )

    assert resolved.asr_words[1].speaker_label == "speaker_0"
    evidence = resolved.asr_words[1].metadata["diarization"]
    assert evidence["speaker_label"] is None
    assert evidence["mapping_status"] == "no_overlap"
    assert evidence["semantic_resolution"]["application_mode"] == "forced_all"
    assert evidence["semantic_resolution"]["confidence"] == 0.45
    assert resolved.metadata["diarization"]["semantic_resolved_word_count"] == 1


def test_confidence_gated_semantic_resolution_keeps_low_confidence_gap() -> None:
    diarization = make_custom_diarization_record(
        ["0.000 0.400 speaker_0", "0.800 1.200 speaker_1"]
    )
    [mapped] = map_diarization_to_asr_records(
        [make_three_word_asr_record()],
        [diarization],
    )
    [prompt] = build_semantic_speaker_prompts([mapped])
    content = json.dumps(
        {
            "decisions": [
                {
                    "gap_id": prompt.gaps[0].gap_id,
                    "speaker_label": "speaker_0",
                    "confidence": 0.45,
                    "reason_code": "uncertain_best_guess",
                }
            ]
        }
    )
    decisions = parse_semantic_speaker_decisions(content, prompt=prompt)

    [resolved] = apply_semantic_speaker_decisions(
        [mapped],
        prompt=prompt,
        decisions=decisions,
        min_confidence=0.8,
    )

    assert resolved.asr_words[1].speaker_label is None
    assert resolved.metadata["diarization"]["semantic_resolved_word_count"] == 0


def test_speaker_diarization_jsonl_roundtrip(tmp_path) -> None:
    output_path = tmp_path / "diarization.jsonl"
    write_speaker_diarization_jsonl([make_diarization_record()], output_path)

    restored = read_speaker_diarization_jsonl(output_path)

    assert len(restored) == 1
    assert restored[0].consultation_id == "case_0001"
    assert restored[0].speaker_labels == ["speaker_0", "speaker_1"]
