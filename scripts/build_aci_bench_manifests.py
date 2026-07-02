"""生成 ACI-Bench 第一阶段 paired manifest 与少量种子切片。

本脚本只把 manifest 写成文件指针和字段映射，不在 manifest 中保存病例正文。
种子切片会包含 transcript/note 正文，仅写入默认被 .gitignore 忽略的 data/processed/。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.manifest import (  # noqa: E402
    PairedTranscriptManifest,
    TextPointer,
    write_manifest_jsonl,
)

DATASET = "aci_bench"
TEXT_COLUMN = "dialogue"
REFERENCE_COLUMN = "note"
ID_COLUMN = "id"
SRC_EXPERIMENT_DIR = "src_experiment_data"


@dataclass(frozen=True)
class TrackSpec:
    """ACI-Bench paired 轨道定义。"""

    name: str
    source: str
    splits: tuple[str, ...]
    left_variant: str
    left_role: str
    right_variant: str
    right_role: str
    output_name: str
    description: str


TRACKS: tuple[TrackSpec, ...] = (
    TrackSpec(
        name="noise_harm",
        source="virtscribe",
        splits=("valid", "test1", "test2", "test3"),
        left_variant="humantrans",
        left_role="clean",
        right_variant="asr",
        right_role="noisy",
        output_name="virtscribe_humantrans_vs_asr.jsonl",
        description="VirtScribe human transcript vs ASR transcript，用于评估 ASR 噪声伤害。",
    ),
    TrackSpec(
        name="repair_gain",
        source="aci",
        splits=("valid", "test1", "test2", "test3"),
        left_variant="asr",
        left_role="noisy",
        right_variant="asrcorr",
        right_role="oracle_repaired",
        output_name="aci_asr_vs_asrcorr.jsonl",
        description="ACI ASR vs ASR-corrected transcript，用于评估修复收益。",
    ),
)


def read_csv_by_id(path: Path, id_column: str = ID_COLUMN) -> dict[str, dict[str, str]]:
    """读取 CSV，并按 id 建索引。"""

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV 缺少表头：{path}")
        if id_column not in reader.fieldnames:
            raise ValueError(f"CSV 缺少 id 列 {id_column!r}：{path}")
        required_columns = {TEXT_COLUMN, REFERENCE_COLUMN}
        missing = required_columns.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV 缺少必需列 {sorted(missing)}：{path}")

        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            record_id = row[id_column]
            if not record_id:
                raise ValueError(f"CSV 存在空 id：{path}")
            if record_id in rows:
                raise ValueError(f"CSV 存在重复 id {record_id!r}：{path}")
            rows[record_id] = row
        return rows


def variant_file(split: str, source: str, variant: str) -> str:
    """生成 ACI-Bench src_experiment_data 相对文件名。"""

    return f"{SRC_EXPERIMENT_DIR}/{split}_{source}_{variant}.csv"


def metadata_file(split: str, source: str, variant: str) -> str:
    """生成 ACI-Bench metadata 相对文件名。"""

    return f"{SRC_EXPERIMENT_DIR}/{split}_{source}_{variant}_metadata.csv"


def build_track_records(
    data_root: Path,
    spec: TrackSpec,
) -> tuple[list[PairedTranscriptManifest], dict[str, Any]]:
    """为单个 ACI-Bench paired 轨道构造 manifest 记录。"""

    records: list[PairedTranscriptManifest] = []
    summary: dict[str, Any] = {
        "track": spec.name,
        "source": spec.source,
        "splits": {},
        "total_records": 0,
        "note_mismatch_count": 0,
    }

    for split in spec.splits:
        left_rel = variant_file(split, spec.source, spec.left_variant)
        right_rel = variant_file(split, spec.source, spec.right_variant)
        left_path = data_root / left_rel
        right_path = data_root / right_rel

        if not left_path.exists():
            raise FileNotFoundError(f"找不到左侧版本文件：{left_path}")
        if not right_path.exists():
            raise FileNotFoundError(f"找不到右侧版本文件：{right_path}")

        left_rows = read_csv_by_id(left_path)
        right_rows = read_csv_by_id(right_path)
        paired_ids = sorted(set(left_rows).intersection(right_rows))
        left_only = sorted(set(left_rows).difference(right_rows))
        right_only = sorted(set(right_rows).difference(left_rows))
        note_mismatch_ids: list[str] = []

        for record_id in paired_ids:
            note_consistent = left_rows[record_id][REFERENCE_COLUMN] == right_rows[record_id][
                REFERENCE_COLUMN
            ]
            if not note_consistent:
                note_mismatch_ids.append(record_id)

            sample_id = f"{DATASET}:{spec.source}:{split}:{record_id}"
            records.append(
                PairedTranscriptManifest(
                    sample_id=sample_id,
                    dataset=DATASET,
                    track=spec.name,
                    source=spec.source,
                    split=split,
                    variants={
                        spec.left_role: TextPointer(
                            source_file=left_rel,
                            record_id=record_id,
                            id_column=ID_COLUMN,
                            text_column=TEXT_COLUMN,
                            variant=spec.left_variant,
                            role=spec.left_role,
                        ),
                        spec.right_role: TextPointer(
                            source_file=right_rel,
                            record_id=record_id,
                            id_column=ID_COLUMN,
                            text_column=TEXT_COLUMN,
                            variant=spec.right_variant,
                            role=spec.right_role,
                        ),
                    },
                    reference_outputs={
                        "clinical_note": TextPointer(
                            source_file=left_rel,
                            record_id=record_id,
                            id_column=ID_COLUMN,
                            text_column=REFERENCE_COLUMN,
                            variant="gold_note",
                            role="reference",
                        )
                    },
                    metadata={
                        "track_description": spec.description,
                        "left_metadata_file": metadata_file(split, spec.source, spec.left_variant),
                        "right_metadata_file": metadata_file(
                            split,
                            spec.source,
                            spec.right_variant,
                        ),
                    },
                    checks={
                        "reference_note_consistent": note_consistent,
                    },
                )
            )

        summary["splits"][split] = {
            "left_file": left_rel,
            "right_file": right_rel,
            "left_count": len(left_rows),
            "right_count": len(right_rows),
            "paired_count": len(paired_ids),
            "left_only_count": len(left_only),
            "right_only_count": len(right_only),
            "note_mismatch_count": len(note_mismatch_ids),
        }
        summary["total_records"] += len(paired_ids)
        summary["note_mismatch_count"] += len(note_mismatch_ids)

    return records, summary


def load_source_record(data_root: Path, pointer: TextPointer) -> dict[str, str]:
    """按 manifest 指针读取源记录。"""

    rows = read_csv_by_id(data_root / pointer.source_file, pointer.id_column)
    try:
        return rows[pointer.record_id]
    except KeyError as exc:
        raise KeyError(f"源文件缺少记录 {pointer.record_id!r}：{pointer.source_file}") from exc


def build_seed_examples(
    data_root: Path,
    manifests_by_track: dict[str, list[PairedTranscriptManifest]],
    seed_size: int,
) -> list[dict[str, Any]]:
    """生成包含正文的少量种子切片，用于本地人工核验。"""

    examples: list[dict[str, Any]] = []
    for track, records in manifests_by_track.items():
        for record in records[:seed_size]:
            variants: dict[str, str] = {}
            for role, pointer in record.variants.items():
                source_record = load_source_record(data_root, pointer)
                variants[role] = source_record[pointer.text_column]

            reference_pointer = record.reference_outputs["clinical_note"]
            reference_record = load_source_record(data_root, reference_pointer)
            examples.append(
                {
                    "sample_id": record.sample_id,
                    "dataset": record.dataset,
                    "track": track,
                    "source": record.source,
                    "split": record.split,
                    "variants": variants,
                    "reference_outputs": {
                        "clinical_note": reference_record[reference_pointer.text_column]
                    },
                    "research_use_only": True,
                    "notes": "本文件用于本地人工核验，包含病例文本，默认不提交 Git。",
                }
            )
    return examples


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """写入普通 JSONL。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/external/aci_bench"),
        help="ACI-Bench 本地数据根目录，默认为 data/external/aci_bench。",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=Path("data/interim/aci_bench/manifests"),
        help="manifest 输出目录。",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed/aci_bench/v0_note_generation"),
        help="包含正文的本地 processed 输出目录。",
    )
    parser.add_argument(
        "--seed-size",
        type=int,
        default=3,
        help="每条轨道写入 seed_pairs.jsonl 的样本数；设为 0 则不生成。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifests_by_track: dict[str, list[PairedTranscriptManifest]] = {}
    summaries: list[dict[str, Any]] = []

    for spec in TRACKS:
        records, summary = build_track_records(args.data_root, spec)
        manifests_by_track[spec.name] = records
        summaries.append(summary)
        write_manifest_jsonl(records, args.manifest_dir / spec.output_name)

    seed_count = 0
    if args.seed_size > 0:
        seed_examples = build_seed_examples(args.data_root, manifests_by_track, args.seed_size)
        write_jsonl(seed_examples, args.processed_dir / "seed_pairs.jsonl")
        seed_count = len(seed_examples)

    summary_path = args.manifest_dir / "aci_bench_manifest_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "dataset": DATASET,
                "manifest_dir": str(args.manifest_dir),
                "processed_dir": str(args.processed_dir),
                "seed_examples": seed_count,
                "tracks": summaries,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("ACI-Bench manifest 生成完成。")
    for summary in summaries:
        print(
            f"- {summary['track']}: {summary['total_records']} paired records, "
            f"note mismatches={summary['note_mismatch_count']}"
        )
    print(f"- seed examples: {seed_count}")
    print(f"- summary: {summary_path}")


if __name__ == "__main__":
    main()
