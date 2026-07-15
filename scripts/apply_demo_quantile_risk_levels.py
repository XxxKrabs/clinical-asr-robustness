"""对已有 ASR confidence JSONL 应用未校准 demo_quantile_v0 风险等级。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from clinical_asr_robustness.asr_confidence import (
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.nemo_confidence_export import (
    apply_demo_quantile_risk_levels,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--run-config-json", type=Path, required=True)
    parser.add_argument("--red-fraction", type=float, default=0.10)
    parser.add_argument("--yellow-fraction", type=float, default=0.20)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    args = parse_args()
    input_path = resolve(args.input_jsonl)
    output_path = resolve(args.output_jsonl)
    records = apply_demo_quantile_risk_levels(
        read_asr_confidence_jsonl(input_path),
        red_fraction=args.red_fraction,
        yellow_fraction=args.yellow_fraction,
    )
    write_asr_confidence_jsonl(records, output_path)
    level_counts: dict[str, int] = {}
    for record in records:
        for word in record.asr_words:
            key = word.confidence_level.value
            level_counts[key] = level_counts.get(key, 0) + 1
    summary = {
        "task_id": "T056",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": "demo_quantile_v0",
        "calibrated": False,
        "input_jsonl": str(args.input_jsonl),
        "output_jsonl": str(args.output_jsonl),
        "record_count": len(records),
        "unit_level_counts": dict(sorted(level_counts.items())),
        "red_fraction": args.red_fraction,
        "yellow_fraction": args.yellow_fraction,
    }
    run_config = resolve(args.run_config_json)
    run_config.parent.mkdir(parents=True, exist_ok=True)
    run_config.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
