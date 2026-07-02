"""实验样本 manifest 数据结构与 JSONL 读写工具。

manifest 只保存样本索引、文件指针和字段映射，默认不保存病例正文。
这样可以把“数据如何配对”和“病例文本内容”分开，便于复现，也降低误提交正文的风险。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_VERSION = "paired_transcript_manifest/v1"


class TextPointer(BaseModel):
    """指向某个源文件中某条文本字段的轻量指针。"""

    model_config = ConfigDict(extra="forbid")

    source_file: str
    record_id: str
    id_column: str = "id"
    text_column: str
    variant: str | None = None
    role: str | None = None


class PairedTranscriptManifest(BaseModel):
    """一个 paired transcript 样本的实验索引。

    `variants` 使用角色名作为 key，例如：
    - clean / noisy
    - noisy / oracle_repaired
    - noisy / repaired_rule_v1

    后续接入新数据集时，可以复用这个结构，只需要让对应 builder
    生成一致的文件指针和字段映射。
    """

    model_config = ConfigDict(extra="forbid")

    manifest_version: str = MANIFEST_VERSION
    sample_id: str
    dataset: str
    track: str
    source: str
    split: str
    variants: dict[str, TextPointer]
    reference_outputs: dict[str, TextPointer] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, Any] = Field(default_factory=dict)


def read_manifest_jsonl(path: str | Path) -> list[PairedTranscriptManifest]:
    """读取 paired transcript manifest JSONL。"""

    records: list[PairedTranscriptManifest] = []
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(PairedTranscriptManifest.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - 保留文件与行号便于定位
                raise ValueError(f"无法解析 manifest 第 {line_number} 行：{manifest_path}") from exc
    return records


def write_manifest_jsonl(
    records: Iterable[PairedTranscriptManifest],
    path: str | Path,
) -> None:
    """写入 paired transcript manifest JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")
