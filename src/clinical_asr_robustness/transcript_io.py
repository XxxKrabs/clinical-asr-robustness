"""JSONL 转写样本读写工具。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from clinical_asr_robustness.schema import TranscriptSample


def read_samples_jsonl(path: str | Path) -> list[TranscriptSample]:
    """读取 JSONL 样本文件。"""

    samples: list[TranscriptSample] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(TranscriptSample.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - 这里保留上下文更利于定位脏数据
                raise ValueError(f"无法解析第 {line_number} 行：{path}") from exc
    return samples


def write_samples_jsonl(samples: Iterable[TranscriptSample], path: str | Path) -> None:
    """写入 JSONL 样本文件。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for sample in samples:
            file.write(json.dumps(sample.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")
