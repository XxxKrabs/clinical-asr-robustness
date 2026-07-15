"""T042a: validate source-aware gold key facts for case-summary evaluation.

The default input path is under ``data/processed/`` because real annotation
files may contain short clinical fact labels and should not be committed.  The
aggregate summary written to ``outputs/`` intentionally excludes
``canonical_fact`` text and full transcript text.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.asr_quality_evaluation import resolve_project_path  # noqa: E402
from clinical_asr_robustness.case_summary_evaluation import (  # noqa: E402
    GOLD_KEY_FACTS_DEFAULT_INPUT,
    GOLD_KEY_FACTS_DEFAULT_OUTPUT_DIR,
    run_gold_key_facts_validation,
    write_json,
)

DEFAULT_SUMMARY_NAME = "primock57_t042_gold_key_facts_summary.json"
DEFAULT_RUN_CONFIG_NAME = "t042_gold_key_facts_validation_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=GOLD_KEY_FACTS_DEFAULT_INPUT,
        help=(
            "gold_key_facts.jsonl path. Defaults to data/processed so real "
            "annotation files stay outside Git."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=GOLD_KEY_FACTS_DEFAULT_OUTPUT_DIR,
        help="Directory for T042a aggregate validation outputs.",
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help="Aggregate summary JSON filename.",
    )
    parser.add_argument(
        "--run-config-name",
        default=DEFAULT_RUN_CONFIG_NAME,
        help="Run config JSON filename.",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    summary_path = output_dir / args.summary_name
    return run_gold_key_facts_validation(
        input_jsonl=args.input_jsonl,
        output_summary_json=summary_path,
        project_root=PROJECT_ROOT,
    )


def build_run_config(
    args: argparse.Namespace,
    summary: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    record: dict[str, Any] = {
        "task_id": "T042a",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "gold_key_facts_jsonl": _path_for_record(
                resolve_project_path(args.input_jsonl, PROJECT_ROOT)
            ),
        },
        "outputs": {
            "summary_json": _path_for_record(output_dir / args.summary_name),
            "run_config_json": _path_for_record(output_dir / args.run_config_name),
        },
        "validation": {
            "fact_count": summary.get("fact_count", 0),
            "bundle_count": summary.get("bundle_count", 0),
            "summary_contains_canonical_fact_text": False,
            "summary_contains_full_transcript_text": False,
            "research_use_only": True,
        },
    }
    if error is not None:
        record["error"] = error
    if traceback_text is not None:
        record["traceback"] = traceback_text
    return record


def _path_for_record(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    run_config_path = output_dir / args.run_config_name
    try:
        summary = run(args)
        run_config = build_run_config(args, summary, status="ok")
        write_json(run_config, run_config_path)
        print("T042a gold key facts validation completed.")
        print(f"- facts: {summary['fact_count']}")
        print(f"- bundles: {summary['bundle_count']}")
        print(f"- reviewed: {summary['reviewed_count']}")
        print(f"- summary: {output_dir / args.summary_name}")
    except Exception as exc:
        failed_summary: dict[str, Any] = {}
        run_config = build_run_config(
            args,
            failed_summary,
            status="failed",
            error=repr(exc),
            traceback_text=traceback.format_exc(),
        )
        write_json(run_config, run_config_path)
        print("T042a gold key facts validation failed.")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
