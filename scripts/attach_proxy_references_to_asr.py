"""把显式标源的 proxy reference 路径接到 ASR records，供下游双输入评估。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-jsonl", type=Path, required=True)
    parser.add_argument("--proxy-reference-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--run-summary-json", type=Path, required=True)
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def run(args: argparse.Namespace) -> dict[str, Any]:
    asr_path = resolve_project_path(args.asr_jsonl)
    proxy_path = resolve_project_path(args.proxy_reference_jsonl)
    output_path = resolve_project_path(args.output_jsonl)
    summary_path = resolve_project_path(args.run_summary_json)
    proxy_index = {str(row.get("consultation_id")): row for row in read_jsonl(proxy_path)}
    records = read_asr_confidence_jsonl(asr_path)
    output_records = []
    missing: set[str] = set()
    for record in records:
        case_id = str(record.consultation_id or record.sample_id)
        proxy = proxy_index.get(case_id)
        if proxy is None:
            missing.add(case_id)
            output_records.append(record)
            continue
        metadata = {
            **record.metadata,
            "proxy_reference": {
                "reference_type": proxy.get("reference_type"),
                "audio_used": proxy.get("audio_used"),
                "human_transcriber_used": proxy.get("human_transcriber_used"),
                "is_gold": proxy.get("is_gold"),
                "formal_quality_claim_allowed": False,
            },
        }
        output_records.append(
            record.model_copy(
                update={
                    "reference_transcript_path": proxy["reference_transcript_path"],
                    "reference_text_included": False,
                    "metadata": metadata,
                }
            )
        )
    write_asr_confidence_jsonl(output_records, output_path)
    summary = {
        "task_id": "T063_PROXY_POINTER_ATTACHMENT",
        "status": "ok" if not missing else "partial",
        "input_record_count": len(records),
        "attached_record_count": sum(
            record.reference_transcript_path is not None for record in output_records
        ),
        "missing_consultation_ids": sorted(missing),
        "reference_type": "llm_multi_asr_consensus_proxy",
        "formal_quality_claim_allowed": False,
        "inputs": {
            "asr_jsonl": project_relative(asr_path),
            "proxy_reference_jsonl": project_relative(proxy_path),
        },
        "output_jsonl": project_relative(output_path),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
