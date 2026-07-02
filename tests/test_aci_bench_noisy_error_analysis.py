import importlib.util
import json
import sys
from pathlib import Path


def load_analysis_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "analyze_aci_bench_noisy_errors.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_aci_bench_noisy_errors", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_annotation_record_for_noise_harm_track() -> None:
    analyzer = load_analysis_module()
    pair_record = {
        "sample_id": "aci_bench:demo:valid:D001",
        "dataset": "aci_bench",
        "source": "demo",
        "track": "noise_harm",
        "split": "valid",
        "target_task": "sectioned_clinical_note_generation",
        "variants": {
            "clean": {
                "variant_name": "humantrans",
                "source_file": "clean.csv",
                "record_id": "D001",
                "transcript": "patient has iron deficiency anemia",
            },
            "noisy": {
                "variant_name": "asr",
                "source_file": "noisy.csv",
                "record_id": "D001",
                "transcript": "patient has iron severe anemia",
            },
        },
    }

    record = analyzer.build_annotation_record(
        pair_record,
        medical_terms=analyzer.load_medical_terms(None),
    )

    assert record["schema_version"] == analyzer.ANNOTATION_SCHEMA_VERSION
    assert record["comparison"]["reference_variant"] == "clean"
    assert record["comparison"]["noisy_variant"] == "noisy"
    assert record["selected_error_types"] == ["substitution", "deletion", "insertion"]
    assert record["selected_metrics"] == ["WER", "MC-WER"]
    assert record["error_type_counts"]["substitution"] == 1
    assert record["metrics"]["wer"] == 0.2
    assert record["edit_span_count"] == 1
    assert record["edit_spans"][0]["usable_for_repair_candidate"] is True


def test_build_summary_does_not_include_transcript_text(tmp_path) -> None:
    analyzer = load_analysis_module()
    pair_record = {
        "sample_id": "aci_bench:demo:valid:D001",
        "dataset": "aci_bench",
        "source": "demo",
        "track": "repair_gain",
        "split": "valid",
        "target_task": "sectioned_clinical_note_generation",
        "variants": {
            "oracle_repaired": {
                "variant_name": "asrcorr",
                "source_file": "repaired.csv",
                "record_id": "D001",
                "transcript": "take ferrous sulfate daily",
            },
            "noisy": {
                "variant_name": "asr",
                "source_file": "noisy.csv",
                "record_id": "D001",
                "transcript": "take ferrous daily",
            },
        },
    }
    annotation = analyzer.build_annotation_record(
        pair_record,
        medical_terms=analyzer.load_medical_terms(None),
    )

    output_path = tmp_path / "annotations.jsonl"
    analyzer.write_jsonl([annotation], output_path)
    loaded = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    summary = analyzer.build_summary(
        annotation_records=loaded,
        pairs_jsonl=Path("pairs.jsonl"),
        annotations_path=output_path,
    )

    serialized_summary = json.dumps(summary, ensure_ascii=False)
    assert summary["pair_records"] == 1
    assert summary["pair_counts_by_track"] == {"repair_gain": 1}
    assert summary["error_type_counts"]["deletion"] == 1
    assert "ferrous sulfate" not in serialized_summary
    assert summary["selected_metrics"] == ["WER", "MC-WER"]
