import importlib.util
import json
import sys
import wave
from pathlib import Path


def load_builder_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_primock57_asr_manifest.py"
    )
    spec = importlib.util.spec_from_file_location("build_primock57_asr_manifest", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_wav(path: Path, *, duration_sec: float = 0.1, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def write_textgrid(path: Path, *, secret_text: str, xmax: float = 0.1) -> None:
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
                "        intervals: size = 1",
                "        intervals [1]:",
                "            xmin = 0",
                f"            xmax = {xmax}",
                f'            text = "{secret_text}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def create_fake_primock57(root: Path, consultation_ids: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# fake PriMock57\n", encoding="utf-8")
    (root / "LICENSE.md").write_text(
        "# Creative Commons Attribution 4.0 International\n",
        encoding="utf-8",
    )
    for consultation_id in consultation_ids:
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (root / "notes" / f"{consultation_id}.json").write_text(
            json.dumps(
                {
                    "day": 1,
                    "consultation": 1,
                    "presenting_complaint": "SECRET_PRESENTING_COMPLAINT",
                    "note": "SECRET_NOTE_TEXT",
                    "highlights": ["SECRET_HIGHLIGHT"],
                }
            ),
            encoding="utf-8",
        )
        for channel in ("doctor", "patient"):
            write_wav(root / "audio" / f"{consultation_id}_{channel}.wav")
            write_textgrid(
                root / "transcripts" / f"{consultation_id}_{channel}.TextGrid",
                secret_text=f"SECRET_REFERENCE_TEXT_{consultation_id}_{channel}",
            )


def test_build_primock57_manifests_do_not_inline_reference_or_notes(tmp_path) -> None:
    builder = load_builder_module()
    data_root = tmp_path / "primock57"
    create_fake_primock57(
        data_root,
        ["day1_consultation01", "day1_consultation02"],
    )

    consultation_records, nemo_records, summary = builder.build_manifests(
        data_root=data_root,
        limit=2,
        project_root=tmp_path,
    )

    assert len(consultation_records) == 2
    assert len(nemo_records) == 4
    assert summary["available_complete_consultations"] == 2
    assert summary["validation"]["no_inline_reference_text"] is True
    assert summary["validation"]["no_inline_notes_text"] is True
    assert summary["validation"]["sample_count_within_t025_target"] is False

    payload = json.dumps(
        {
            "consultation_records": consultation_records,
            "nemo_records": nemo_records,
            "summary": summary,
        },
        ensure_ascii=False,
    )
    assert "SECRET_REFERENCE_TEXT" not in payload
    assert "SECRET_PRESENTING_COMPLAINT" not in payload
    assert "SECRET_NOTE_TEXT" not in payload
    assert "SECRET_HIGHLIGHT" not in payload

    first_record = consultation_records[0]
    assert first_record["license"]["spdx"] == "CC-BY-4.0"
    assert first_record["channels"]["doctor"]["reference"]["utterance_intervals"] == 1
    assert first_record["channels"]["patient"]["audio"]["sample_rate_hz"] == 16000
    assert nemo_records[0]["text"] == ""
    assert nemo_records[0]["text_is_placeholder"] is True


def test_build_primock57_manifest_writes_jsonl_and_summary(tmp_path) -> None:
    builder = load_builder_module()
    data_root = tmp_path / "primock57"
    output_dir = tmp_path / "manifests"
    create_fake_primock57(
        data_root,
        ["day1_consultation01", "day1_consultation02", "day1_consultation03"],
    )

    consultation_records, nemo_records, summary = builder.build_manifests(
        data_root=data_root,
        limit=3,
        project_root=tmp_path,
    )

    consultation_path = output_dir / "consultations.jsonl"
    nemo_path = output_dir / "nemo.jsonl"
    summary_path = output_dir / "summary.json"
    builder.write_jsonl(consultation_records, consultation_path)
    builder.write_jsonl(nemo_records, nemo_path)
    builder.write_json(summary, summary_path)

    loaded_consultations = [
        json.loads(line) for line in consultation_path.read_text(encoding="utf-8").splitlines()
    ]
    loaded_nemo = [json.loads(line) for line in nemo_path.read_text(encoding="utf-8").splitlines()]
    loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert loaded_consultations == consultation_records
    assert loaded_nemo == nemo_records
    assert loaded_summary["consultation_records"] == 3
    assert loaded_summary["channel_audio_records"] == 6
    assert loaded_summary["validation"]["sample_count_within_t025_target"] is True
