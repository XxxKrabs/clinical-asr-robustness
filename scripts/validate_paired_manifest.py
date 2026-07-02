"""校验 paired transcript manifest 的文件指针和字段映射。

这个脚本是数据集无关的：只要 manifest 使用
`paired_transcript_manifest/v1` 结构，就可以用它检查源 CSV 是否存在、
记录 id 是否存在、字段是否存在，以及 manifest 中是否误写入正文。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.manifest import (  # noqa: E402
    PairedTranscriptManifest,
    read_manifest_jsonl,
)

TEXTLIKE_FORBIDDEN_KEYS = {
    "dialogue",
    "note",
    "transcript",
    "clean_transcript",
    "noisy_transcript",
    "repaired_transcript",
    "clinical_note",
}


def read_csv_index(path: Path, id_column: str) -> tuple[dict[str, dict[str, str]], set[str]]:
    """读取 CSV，返回按 id 索引的记录和字段集合。"""

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV 缺少表头：{path}")
        if id_column not in reader.fieldnames:
            raise ValueError(f"CSV 缺少 id 列 {id_column!r}：{path}")
        rows = {row[id_column]: row for row in reader}
        return rows, set(reader.fieldnames)


def assert_manifest_has_no_inline_text(record: PairedTranscriptManifest) -> None:
    """检查 manifest 顶层和 metadata/checks 没有直接保存常见正文键。"""

    dumped = record.model_dump(mode="json")
    shallow_dicts = [dumped, dumped.get("metadata", {}), dumped.get("checks", {})]
    for dictionary in shallow_dicts:
        forbidden = TEXTLIKE_FORBIDDEN_KEYS.intersection(dictionary)
        if forbidden:
            raise ValueError(
                f"manifest {record.sample_id} 存在疑似正文键 {sorted(forbidden)}；"
                "manifest 应只保存文件指针。"
            )


def validate_records(
    dataset_root: Path,
    records: list[PairedTranscriptManifest],
) -> dict[str, object]:
    """校验 manifest 记录，并返回统计。"""

    csv_cache: dict[tuple[str, str], tuple[dict[str, dict[str, str]], set[str]]] = {}
    role_counts: Counter[str] = Counter()
    track_counts: Counter[str] = Counter()
    split_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for record in records:
        assert_manifest_has_no_inline_text(record)
        track_counts[record.track] += 1
        split_counts[record.track][record.split] += 1

        pointers = list(record.variants.values()) + list(record.reference_outputs.values())
        for pointer in pointers:
            role_counts[pointer.role or "unknown"] += 1
            source_path = dataset_root / pointer.source_file
            if not source_path.exists():
                raise FileNotFoundError(f"源文件不存在：{source_path}")

            cache_key = (pointer.source_file, pointer.id_column)
            if cache_key not in csv_cache:
                csv_cache[cache_key] = read_csv_index(source_path, pointer.id_column)

            rows, columns = csv_cache[cache_key]
            if pointer.record_id not in rows:
                raise KeyError(f"源文件 {source_path} 缺少记录 id={pointer.record_id!r}")
            if pointer.text_column not in columns:
                raise KeyError(f"源文件 {source_path} 缺少字段 {pointer.text_column!r}")

    return {
        "records": len(records),
        "tracks": dict(track_counts),
        "splits": {track: dict(counter) for track, counter in split_counts.items()},
        "roles": dict(role_counts),
        "source_files": len(
            {pointer.source_file for record in records for pointer in record.variants.values()}
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifests",
        type=Path,
        nargs="+",
        help="一个或多个 paired manifest JSONL 文件。",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("data/external/aci_bench"),
        help="manifest 中 source_file 的相对根目录。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    total = 0
    for manifest_path in args.manifests:
        records = read_manifest_jsonl(manifest_path)
        stats = validate_records(args.dataset_root, records)
        total += len(records)
        print(f"{manifest_path}: OK")
        print(f"- records: {stats['records']}")
        print(f"- tracks: {stats['tracks']}")
        print(f"- splits: {stats['splits']}")
        print(f"- roles: {stats['roles']}")
    print(f"全部 manifest 校验通过，总记录数：{total}")


if __name__ == "__main__":
    main()
