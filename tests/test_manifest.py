import pytest
from pydantic import ValidationError

from clinical_asr_robustness.manifest import (
    PairedTranscriptManifest,
    TextPointer,
    read_manifest_jsonl,
    write_manifest_jsonl,
)


def test_paired_manifest_roundtrip(tmp_path) -> None:
    record = PairedTranscriptManifest(
        sample_id="aci_bench:virtscribe:valid:VS014",
        dataset="aci_bench",
        track="noise_harm",
        source="virtscribe",
        split="valid",
        variants={
            "clean": TextPointer(
                source_file="src_experiment_data/valid_virtscribe_humantrans.csv",
                record_id="VS014",
                text_column="dialogue",
                variant="humantrans",
                role="clean",
            ),
            "noisy": TextPointer(
                source_file="src_experiment_data/valid_virtscribe_asr.csv",
                record_id="VS014",
                text_column="dialogue",
                variant="asr",
                role="noisy",
            ),
        },
        reference_outputs={
            "clinical_note": TextPointer(
                source_file="src_experiment_data/valid_virtscribe_humantrans.csv",
                record_id="VS014",
                text_column="note",
                variant="gold_note",
                role="reference",
            )
        },
    )

    path = tmp_path / "manifest.jsonl"
    write_manifest_jsonl([record], path)

    loaded = read_manifest_jsonl(path)
    assert loaded == [record]


def test_manifest_rejects_unexpected_inline_fields() -> None:
    with pytest.raises(ValidationError):
        PairedTranscriptManifest.model_validate(
            {
                "sample_id": "demo",
                "dataset": "demo",
                "track": "demo_track",
                "source": "demo_source",
                "split": "valid",
                "variants": {},
                "dialogue": "manifest 不应直接保存正文",
            }
        )
