import importlib.util
import json
import sys
from pathlib import Path

from clinical_asr_robustness.manifest import PairedTranscriptManifest, TextPointer


def load_builder_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_aci_bench_v0_note_generation.py"
    )
    spec = importlib.util.spec_from_file_location("build_aci_bench_v0_note_generation", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_v0_note_generation_records_from_manifest(tmp_path) -> None:
    builder = load_builder_module()
    data_root = tmp_path / "aci_bench"
    source_dir = data_root / "src_experiment_data"
    source_dir.mkdir(parents=True)

    (source_dir / "valid_demo_clean.csv").write_text(
        "id,dialogue,note\nD001,clean transcript,reference note\n",
        encoding="utf-8",
    )
    (source_dir / "valid_demo_noisy.csv").write_text(
        "id,dialogue,note\nD001,noisy transcript,reference note\n",
        encoding="utf-8",
    )

    manifest_record = PairedTranscriptManifest(
        sample_id="aci_bench:demo:valid:D001",
        dataset="aci_bench",
        track="noise_harm",
        source="demo",
        split="valid",
        variants={
            "clean": TextPointer(
                source_file="src_experiment_data/valid_demo_clean.csv",
                record_id="D001",
                text_column="dialogue",
                variant="humantrans",
                role="clean",
            ),
            "noisy": TextPointer(
                source_file="src_experiment_data/valid_demo_noisy.csv",
                record_id="D001",
                text_column="dialogue",
                variant="asr",
                role="noisy",
            ),
        },
        reference_outputs={
            "clinical_note": TextPointer(
                source_file="src_experiment_data/valid_demo_clean.csv",
                record_id="D001",
                text_column="note",
                variant="gold_note",
                role="reference",
            )
        },
    )

    bundle = builder.build_processed_records(
        data_root=data_root,
        manifest_records=[manifest_record],
        source_manifest="demo_manifest.jsonl",
    )

    assert len(bundle.pair_records) == 1
    assert len(bundle.input_records) == 2
    assert bundle.pair_records[0]["reference_note"] == "reference note"
    assert bundle.pair_records[0]["variants"]["noisy"]["transcript"] == "noisy transcript"
    assert bundle.input_records[0]["input_variant"] == "clean"
    assert bundle.input_records[1]["input_variant"] == "noisy"
    assert bundle.input_records[1]["input_transcript"] == "noisy transcript"
    assert bundle.input_records[1]["reference_note"] == "reference note"
    assert bundle.input_records[1]["research_use_only"] is True

    output_path = tmp_path / "processed" / "inputs.jsonl"
    builder.write_jsonl(bundle.input_records, output_path)
    loaded = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert loaded == bundle.input_records

    summary = builder.build_summary(
        input_records=bundle.input_records,
        pair_records=bundle.pair_records,
        manifest_paths=[Path("demo_manifest.jsonl")],
        output_paths={"inputs": Path("inputs.jsonl"), "pairs": Path("pairs.jsonl")},
    )
    assert summary["pair_records"] == 1
    assert summary["input_records"] == 2
    assert summary["input_counts_by_variant"]["noise_harm"] == {"clean": 1, "noisy": 1}
