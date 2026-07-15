from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_alignment_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_t045_three_text_alignment.py"
    )
    spec = importlib.util.spec_from_file_location("build_t045_three_text_alignment", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def write_textgrid(path: Path, *, secret_text: str, xmax: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                'File type = "ooTextFile"',
                'Object class = "TextGrid"',
                "",
                "xmin = 0",
                f"xmax = {xmax}",
                "tiers? <exists>",
                "size = 1",
                "item []:",
                "    item [1]:",
                '        class = "IntervalTier"',
                '        name = "utterances"',
                "        xmin = 0",
                f"        xmax = {xmax}",
                "        intervals: size = 2",
                "        intervals [1]:",
                "            xmin = 0",
                "            xmax = 0.5",
                f'            text = "{secret_text} <UNSURE>"',
                "        intervals [2]:",
                "            xmin = 0.5",
                f"            xmax = {xmax}",
                '            text = ""',
                "",
            ]
        ),
        encoding="utf-8",
    )


def noisy_record(consultation_id: str, *, secret_text: str) -> dict:
    return {
        "schema_version": "primock57_noisy_transcript_consultation/v0",
        "record_type": "consultation_noisy_transcript",
        "sample_id": f"primock57:{consultation_id}",
        "dataset": "primock57",
        "split": "primock57_full_asr_v0",
        "consultation_id": consultation_id,
        "channels": {
            "doctor": {"sample_id": f"primock57:{consultation_id}:doctor"},
            "patient": {"sample_id": f"primock57:{consultation_id}:patient"},
        },
        "noisy_transcript": secret_text,
        "asr_confidence": 0.91,
        "confidence_level": "green",
        "speaker_turns": [
            {"source_channel": "doctor", "speaker_label": "doctor", "text": secret_text},
            {"source_channel": "patient", "speaker_label": "patient", "text": secret_text},
        ],
    }


def build_fake_inputs(tmp_path: Path) -> tuple[Path, Path]:
    noisy_jsonl = tmp_path / "noisy.jsonl"
    textgrid_dir = tmp_path / "transcripts"
    consultation_ids = ["day1_consultation01", "day1_consultation02"]
    write_jsonl(
        noisy_jsonl,
        [
            noisy_record("day1_consultation01", secret_text="SECRET_NOISY_ONE"),
            noisy_record("day1_consultation02", secret_text="SECRET_NOISY_TWO"),
        ],
    )
    for consultation_id in consultation_ids:
        for channel in ("doctor", "patient"):
            write_textgrid(
                textgrid_dir / f"{consultation_id}_{channel}.TextGrid",
                secret_text=f"SECRET_REFERENCE_{consultation_id}_{channel}",
            )
    return noisy_jsonl, textgrid_dir


def test_t045_alignment_marks_repair_pending_without_inlining_transcripts(tmp_path) -> None:
    builder = load_alignment_module()
    noisy_jsonl, textgrid_dir = build_fake_inputs(tmp_path)
    repair_jsonl = tmp_path / "missing_repair.jsonl"
    generated_at = "2026-07-10T00:00:00+00:00"

    records = builder.build_alignment_records(
        noisy_records=builder.load_jsonl(noisy_jsonl),
        textgrid_pairs=builder.discover_textgrid_pairs(textgrid_dir),
        repair_records=[],
        noisy_jsonl=noisy_jsonl,
        repair_jsonl=repair_jsonl,
        generated_at_utc=generated_at,
    )
    summary = builder.build_summary(
        alignment_records=records,
        noisy_jsonl=noisy_jsonl,
        textgrid_dir=textgrid_dir,
        repair_jsonl=repair_jsonl,
        alignment_jsonl=tmp_path / "alignment.jsonl",
        generated_at_utc=generated_at,
    )

    assert len(records) == 2
    assert records[0]["input_variants"]["noisy_asr"]["channels"] == ["doctor", "patient"]
    assert (
        records[0]["input_variants"]["clean_reference"]["status"]
        == "textgrid_pair_available"
    )
    assert (
        records[0]["input_variants"]["doctor_llm_repair"]["status"]
        == "pending_generation"
    )
    assert summary["counts"]["alignment_records"] == 2
    assert summary["counts"]["clean_reference_textgrid_pair_available"] == 2
    assert summary["counts"]["doctor_llm_repair_pending"] == 2
    assert summary["validation"]["all_noisy_consultations_have_clean_textgrid_pair"] is True
    assert summary["validation"]["summary_contains_full_transcript_text"] is False

    payload = json.dumps({"records": records, "summary": summary}, ensure_ascii=False)
    assert "SECRET_NOISY" not in payload
    assert "SECRET_REFERENCE" not in payload


def test_t045_alignment_accepts_optional_repair_jsonl_without_text_leak(tmp_path) -> None:
    builder = load_alignment_module()
    noisy_jsonl, textgrid_dir = build_fake_inputs(tmp_path)
    repair_jsonl = tmp_path / "repair.jsonl"
    write_jsonl(
        repair_jsonl,
        [
            {
                "sample_id": "primock57:day1_consultation01:doctor",
                "consultation_id": "day1_consultation01",
                "source_channel": "doctor",
                "confirmed_transcript": "SECRET_REPAIR_DOCTOR",
            },
            {
                "sample_id": "primock57:day1_consultation01:patient",
                "consultation_id": "day1_consultation01",
                "source_channel": "patient",
                "confirmed_transcript": "SECRET_REPAIR_PATIENT",
            },
        ],
    )

    records = builder.build_alignment_records(
        noisy_records=builder.load_jsonl(noisy_jsonl),
        textgrid_pairs=builder.discover_textgrid_pairs(textgrid_dir),
        repair_records=builder.load_optional_jsonl(repair_jsonl),
        noisy_jsonl=noisy_jsonl,
        repair_jsonl=repair_jsonl,
        generated_at_utc="2026-07-10T00:00:00+00:00",
    )
    by_id = {record["consultation_id"]: record for record in records}

    repair_status = by_id["day1_consultation01"]["input_variants"]["doctor_llm_repair"]
    assert repair_status["status"] == "available"
    assert repair_status["record_count"] == 2
    assert repair_status["channels"] == ["doctor", "patient"]
    assert (
        by_id["day1_consultation02"]["input_variants"]["doctor_llm_repair"]["status"]
        == "pending_generation"
    )

    payload = json.dumps(records, ensure_ascii=False)
    assert "SECRET_REPAIR" not in payload
