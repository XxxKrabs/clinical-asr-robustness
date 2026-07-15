from __future__ import annotations

import json
from types import SimpleNamespace

from clinical_asr_robustness.asr_nbest_candidates import load_nbest_jsonl
from clinical_asr_robustness.nemo_nbest_export import (
    NBEST_SCHEMA_VERSION,
    build_nbest_jsonl_record,
    extract_beam_candidates,
    flatten_nbest_transcription_results,
    safe_id,
    write_nbest_jsonl,
)


class FakeTensorScore:
    def __init__(self, value: float) -> None:
        self.value = value

    def detach(self) -> FakeTensorScore:
        return self

    def cpu(self) -> FakeTensorScore:
        return self

    def item(self) -> float:
        return self.value


def test_flatten_nbest_transcription_results_supports_nested_and_nbest_objects() -> None:
    hyp_a = SimpleNamespace(text="patient has cough", score=-1.0)
    hyp_b = SimpleNamespace(text="patient has calf", score=-2.0)
    hyp_c = SimpleNamespace(text="doctor says hello", score=-3.0)
    nbest = SimpleNamespace(n_best_hypotheses=[hyp_a, hyp_b])

    assert flatten_nbest_transcription_results(([nbest, [hyp_c]], "unused")) == [
        [hyp_a, hyp_b],
        [hyp_c],
    ]


def test_extract_beam_candidates_normalizes_scores_and_deduplicates() -> None:
    candidates = extract_beam_candidates(
        [
            SimpleNamespace(text="patient has cough", score=FakeTensorScore(-1.25)),
            ("patient has cough", -1.3),
            {"rank": 7, "text": "patient has calf", "score": "-2.5"},
        ],
        max_beams=5,
    )

    assert [candidate.text for candidate in candidates] == [
        "patient has cough",
        "patient has calf",
    ]
    assert candidates[0].rank == 1
    assert candidates[0].score == -1.25
    assert candidates[1].metadata["original_rank"] == 7


def test_build_t037_nbest_jsonl_record_is_consumable_by_t029(tmp_path) -> None:
    manifest_record = {
        "sample_id": "primock57:demo:patient",
        "dataset": "primock57",
        "split": "seed_asr_v0",
        "consultation_id": "demo",
        "source_channel": "patient",
        "audio_filepath": "data/external/primock57/audio/demo_patient.wav",
        "duration": 12.3,
        "reference_text_included": False,
    }
    record = build_nbest_jsonl_record(
        manifest_record=manifest_record,
        hypothesis_group=[
            SimpleNamespace(text="i have diarrhoea", score=-1.0),
            SimpleNamespace(text="i have diarrhea", score=-1.5),
        ],
        model_info={"model_name": "fake"},
        decoding_config={"strategy": "beam_batch"},
        runtime={"device": "cpu"},
    )
    output = tmp_path / "nbest.jsonl"
    write_nbest_jsonl([record], output)

    payload = json.loads(output.read_text(encoding="utf-8").strip())
    assert payload["schema_version"] == NBEST_SCHEMA_VERSION
    assert payload["record_id"] == f"nemo_entropy_{safe_id('primock57:demo:patient')}"
    assert payload["beams"][0] == ["i have diarrhoea", -1.0]
    assert payload["research_use_only"] is True

    by_key = load_nbest_jsonl(output)
    assert by_key["sample_id:primock57:demo:patient"][1].text == "i have diarrhea"
    assert by_key["record_id:nemo_entropy_primock57_demo_patient"][0].source == "nemo_beam_batch"


def test_nbest_window_record_uses_source_audio_for_review() -> None:
    record = build_nbest_jsonl_record(
        manifest_record={
            "sample_id": "remote_programming_40:case_demo:0001",
            "dataset": "remote_programming_40",
            "audio_filepath": "data/interim/window.wav",
            "duration_sec": 30.0,
            "source_audio_filepath": "data/raw/remote_programming_40/case_demo.mp3",
            "source_duration_sec": 300.0,
            "source_start_sec": 30.0,
            "source_end_sec": 60.0,
        },
        hypothesis_group=[SimpleNamespace(text="候选", score=-1.0)],
    )

    assert record["audio_filepath"].endswith("case_demo.mp3")
    assert record["duration_sec"] == 300.0
    source = record["metadata"]["source_manifest"]
    assert source["asr_input_audio_filepath"].endswith("window.wav")
    assert source["timestamp_reference"] == "source_audio_absolute"
