"""生成 ACI-Bench V0 note generation processed JSONL。

输入是 T003 已生成的 paired manifest；输出会展开源 CSV 正文，因此只写入
默认被 .gitignore 忽略的 data/processed/ 目录，用于本地实验，不应提交 Git。

默认生成三个文件：
- v0_note_generation_inputs.jsonl：长表格式，每行一个 input transcript variant。
- v0_note_generation_pairs.jsonl：配对格式，每行一个 paired manifest 样本。
- v0_note_generation_summary.json：计数摘要，不包含病例正文。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.manifest import (  # noqa: E402
    PairedTranscriptManifest,
    TextPointer,
    read_manifest_jsonl,
)

INPUT_SCHEMA_VERSION = "aci_bench_v0_note_generation/input/v1"
PAIR_SCHEMA_VERSION = "aci_bench_v0_note_generation/pair/v1"
SUMMARY_SCHEMA_VERSION = "aci_bench_v0_note_generation/summary/v1"
REFERENCE_OUTPUT_NAME = "clinical_note"
TARGET_TASK = "sectioned_clinical_note_generation"
CLINICAL_USE_WARNING = "本记录仅用于研究评估，不构成临床建议。"

DEFAULT_MANIFESTS = (
    Path("data/interim/aci_bench/manifests/virtscribe_humantrans_vs_asr.jsonl"),
    Path("data/interim/aci_bench/manifests/aci_asr_vs_asrcorr.jsonl"),
)


@dataclass
class ProcessedBundle:
    """展开后的 processed 记录集合。"""

    input_records: list[dict[str, Any]]
    pair_records: list[dict[str, Any]]


def read_csv_index(path: Path, id_column: str) -> tuple[dict[str, dict[str, str]], set[str]]:
    """读取源 CSV，并按 id 建索引。"""

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV 缺少表头：{path}")
        if id_column not in reader.fieldnames:
            raise ValueError(f"CSV 缺少 id 列 {id_column!r}：{path}")
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            record_id = row[id_column]
            if not record_id:
                raise ValueError(f"CSV 存在空 id：{path}")
            if record_id in rows:
                raise ValueError(f"CSV 存在重复 id {record_id!r}：{path}")
            rows[record_id] = row
        return rows, set(reader.fieldnames)


def pointer_dict(pointer: TextPointer) -> dict[str, str | None]:
    """把文本指针转为可写入 JSON 的轻量字典。"""

    return pointer.model_dump(mode="json")


def resolve_pointer_text(
    data_root: Path,
    pointer: TextPointer,
    csv_cache: dict[tuple[str, str], tuple[dict[str, dict[str, str]], set[str]]],
) -> str:
    """根据 manifest 文本指针读取源正文。"""

    cache_key = (pointer.source_file, pointer.id_column)
    if cache_key not in csv_cache:
        source_path = data_root / pointer.source_file
        if not source_path.exists():
            raise FileNotFoundError(f"源文件不存在：{source_path}")
        csv_cache[cache_key] = read_csv_index(source_path, pointer.id_column)

    rows, columns = csv_cache[cache_key]
    if pointer.record_id not in rows:
        raise KeyError(f"源文件 {pointer.source_file} 缺少记录 id={pointer.record_id!r}")
    if pointer.text_column not in columns:
        raise KeyError(f"源文件 {pointer.source_file} 缺少字段 {pointer.text_column!r}")

    text = rows[pointer.record_id][pointer.text_column]
    if text is None:
        raise ValueError(f"源字段为空：{pointer.source_file} id={pointer.record_id}")
    return text


def get_reference_pointer(record: PairedTranscriptManifest) -> TextPointer:
    """取得 note generation 的 reference note 指针。"""

    try:
        return record.reference_outputs[REFERENCE_OUTPUT_NAME]
    except KeyError as exc:
        raise KeyError(
            f"manifest {record.sample_id} 缺少 {REFERENCE_OUTPUT_NAME!r} reference output。"
        ) from exc


def build_processed_records(
    data_root: Path,
    manifest_records: list[PairedTranscriptManifest],
    source_manifest: str,
) -> ProcessedBundle:
    """从 paired manifest 生成 V0 note generation processed 记录。"""

    input_records: list[dict[str, Any]] = []
    pair_records: list[dict[str, Any]] = []
    csv_cache: dict[tuple[str, str], tuple[dict[str, dict[str, str]], set[str]]] = {}

    for record in manifest_records:
        reference_pointer = get_reference_pointer(record)
        reference_note = resolve_pointer_text(data_root, reference_pointer, csv_cache)
        variants: dict[str, dict[str, Any]] = {}

        for role, pointer in record.variants.items():
            transcript = resolve_pointer_text(data_root, pointer, csv_cache)
            variant_record = {
                "variant_role": role,
                "variant_name": pointer.variant,
                "text_column": pointer.text_column,
                "source_file": pointer.source_file,
                "record_id": pointer.record_id,
                "transcript": transcript,
            }
            variants[role] = variant_record

            input_records.append(
                {
                    "schema_version": INPUT_SCHEMA_VERSION,
                    "example_id": f"{record.sample_id}::{role}",
                    "sample_id": record.sample_id,
                    "dataset": record.dataset,
                    "source": record.source,
                    "track": record.track,
                    "split": record.split,
                    "target_task": TARGET_TASK,
                    "input_variant": role,
                    "input_variant_name": pointer.variant,
                    "input_transcript": transcript,
                    "reference_output": REFERENCE_OUTPUT_NAME,
                    "reference_note": reference_note,
                    "variant_roles_in_pair": list(record.variants.keys()),
                    "source_pointer": pointer_dict(pointer),
                    "reference_pointer": pointer_dict(reference_pointer),
                    "source_manifest": source_manifest,
                    "metadata": record.metadata,
                    "checks": record.checks,
                    "research_use_only": True,
                    "clinical_use_warning": CLINICAL_USE_WARNING,
                }
            )

        pair_records.append(
            {
                "schema_version": PAIR_SCHEMA_VERSION,
                "sample_id": record.sample_id,
                "dataset": record.dataset,
                "source": record.source,
                "track": record.track,
                "split": record.split,
                "target_task": TARGET_TASK,
                "variants": variants,
                "reference_output": REFERENCE_OUTPUT_NAME,
                "reference_note": reference_note,
                "reference_pointer": pointer_dict(reference_pointer),
                "source_manifest": source_manifest,
                "metadata": record.metadata,
                "checks": record.checks,
                "research_use_only": True,
                "clinical_use_warning": CLINICAL_USE_WARNING,
            }
        )

    return ProcessedBundle(input_records=input_records, pair_records=pair_records)


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """写入 JSONL。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def build_summary(
    input_records: list[dict[str, Any]],
    pair_records: list[dict[str, Any]],
    manifest_paths: list[Path],
    output_paths: dict[str, Path],
) -> dict[str, Any]:
    """构造不含病例正文的摘要。"""

    pair_counts_by_track: Counter[str] = Counter()
    pair_counts_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    input_counts_by_track: Counter[str] = Counter()
    input_counts_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    input_counts_by_variant: dict[str, Counter[str]] = defaultdict(Counter)

    for record in pair_records:
        track = record["track"]
        pair_counts_by_track[track] += 1
        pair_counts_by_split[track][record["split"]] += 1

    for record in input_records:
        track = record["track"]
        input_counts_by_track[track] += 1
        input_counts_by_split[track][record["split"]] += 1
        input_counts_by_variant[track][record["input_variant"]] += 1

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "dataset": "aci_bench",
        "target_task": TARGET_TASK,
        "manifest_files": [str(path) for path in manifest_paths],
        "output_files": {name: str(path) for name, path in output_paths.items()},
        "pair_records": len(pair_records),
        "input_records": len(input_records),
        "pair_counts_by_track": dict(pair_counts_by_track),
        "pair_counts_by_split": {
            track: dict(counter) for track, counter in pair_counts_by_split.items()
        },
        "input_counts_by_track": dict(input_counts_by_track),
        "input_counts_by_split": {
            track: dict(counter) for track, counter in input_counts_by_split.items()
        },
        "input_counts_by_variant": {
            track: dict(counter) for track, counter in input_counts_by_variant.items()
        },
        "research_use_only": True,
        "notes": (
            "processed JSONL 文件包含 transcript 与 reference note 正文，"
            "仅用于本地研究实验，默认不提交 Git。"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/external/aci_bench"),
        help="ACI-Bench 本地数据根目录，默认为 data/external/aci_bench。",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        nargs="*",
        default=list(DEFAULT_MANIFESTS),
        help="一个或多个 paired manifest JSONL；默认使用第一阶段两条 ACI-Bench 轨道。",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed/aci_bench/v0_note_generation"),
        help="processed JSONL 输出目录。",
    )
    parser.add_argument(
        "--inputs-name",
        default="v0_note_generation_inputs.jsonl",
        help="长表 input JSONL 文件名。",
    )
    parser.add_argument(
        "--pairs-name",
        default="v0_note_generation_pairs.jsonl",
        help="配对 JSONL 文件名。",
    )
    parser.add_argument(
        "--summary-name",
        default="v0_note_generation_summary.json",
        help="摘要 JSON 文件名。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_records: list[dict[str, Any]] = []
    pair_records: list[dict[str, Any]] = []

    for manifest_path in args.manifest:
        records = read_manifest_jsonl(manifest_path)
        bundle = build_processed_records(
            data_root=args.data_root,
            manifest_records=records,
            source_manifest=str(manifest_path),
        )
        input_records.extend(bundle.input_records)
        pair_records.extend(bundle.pair_records)

    output_paths = {
        "inputs": args.processed_dir / args.inputs_name,
        "pairs": args.processed_dir / args.pairs_name,
        "summary": args.processed_dir / args.summary_name,
    }

    write_jsonl(input_records, output_paths["inputs"])
    write_jsonl(pair_records, output_paths["pairs"])

    summary = build_summary(input_records, pair_records, list(args.manifest), output_paths)
    output_paths["summary"].parent.mkdir(parents=True, exist_ok=True)
    with output_paths["summary"].open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("ACI-Bench V0 note generation processed JSONL 生成完成。")
    print(f"- pair records: {len(pair_records)}")
    print(f"- input records: {len(input_records)}")
    print(f"- inputs: {output_paths['inputs']}")
    print(f"- pairs: {output_paths['pairs']}")
    print(f"- summary: {output_paths['summary']}")


if __name__ == "__main__":
    main()
