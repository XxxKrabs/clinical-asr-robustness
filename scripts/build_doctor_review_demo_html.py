"""生成静态/轻量医生审阅 HTML 小界面（T036）。

页面以单文件 HTML 形式展示 ASR transcript 的绿/黄/红高亮。点击黄/红
uncertain span 后，可选择候选、手动编辑、拒绝或标记无法判断，并导出
反馈 JSONL，供 `scripts/apply_asr_review_feedback.py` 回放生成
`confirmed_transcript`。

静态 HTML 没有后端写文件能力，因此“保存反馈日志”采用浏览器下载
`doctor_feedback_log.jsonl`，同时写入 localStorage 便于临时恢复。
"""

from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl
from clinical_asr_robustness.review_workflow import (
    T036_GENERATED_BY,
    build_review_html,
    build_review_samples,
    read_review_samples_jsonl,
    write_review_samples_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl"
)
DEFAULT_REVIEW_JSONL = (
    PROJECT_ROOT / "outputs/primock57/t030_review_samples/primock57_asr_review_samples.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t036_doctor_review_demo"
DEFAULT_OUTPUT_HTML = DEFAULT_OUTPUT_DIR / "doctor_review_demo.html"
DEFAULT_EMBEDDED_REVIEW_JSONL = DEFAULT_OUTPUT_DIR / "doctor_review_samples.embedded.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t036_doctor_review_demo_run.json"


def path_for_record(path: Path | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-jsonl",
        type=Path,
        default=DEFAULT_REVIEW_JSONL,
        help="T030 review samples JSONL；若文件不存在，则从 --input-jsonl 构建。",
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=DEFAULT_INPUT_JSONL,
        help="ASR confidence JSONL，用于在 review-jsonl 不存在时现场构建样本。",
    )
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    parser.add_argument(
        "--embedded-review-jsonl",
        type=Path,
        default=DEFAULT_EMBEDDED_REVIEW_JSONL,
        help="把 HTML 实际嵌入的 review samples 同步保存一份，便于复现实验。",
    )
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument("--title", default="T036 ASR 置信度医生审阅 demo")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    review_jsonl = resolve_project_path(args.review_jsonl)
    input_jsonl = resolve_project_path(args.input_jsonl)
    output_html = resolve_project_path(args.output_html)
    embedded_review_jsonl = resolve_project_path(args.embedded_review_jsonl)

    if review_jsonl.exists():
        samples = read_review_samples_jsonl(review_jsonl)
        sample_source = review_jsonl
        built_from_asr = False
    else:
        records = read_asr_confidence_jsonl(input_jsonl)
        samples = build_review_samples(records)
        sample_source = input_jsonl
        built_from_asr = True

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        build_review_html(samples, title=args.title, interactive=True),
        encoding="utf-8",
        newline="\n",
    )
    write_review_samples_jsonl(samples, embedded_review_jsonl)

    return build_run_summary(
        sample_source=sample_source,
        output_html=output_html,
        embedded_review_jsonl=embedded_review_jsonl,
        samples=samples,
        built_from_asr=built_from_asr,
    )


def build_run_summary(
    *,
    sample_source: Path,
    output_html: Path,
    embedded_review_jsonl: Path,
    samples: list[Any],
    built_from_asr: bool,
) -> dict[str, Any]:
    total_spans = sum(len(sample.uncertain_spans) for sample in samples)
    spans_with_candidates = sum(
        1
        for sample in samples
        for span in sample.uncertain_spans
        if span.alternatives
    )
    return {
        "task_id": "T036",
        "status": "ok",
        "generated_by": T036_GENERATED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "sample_source": path_for_record(sample_source),
            "built_from_asr_confidence_jsonl": built_from_asr,
            "samples_read": len(samples),
        },
        "outputs": {
            "doctor_review_demo_html": path_for_record(output_html),
            "embedded_review_samples_jsonl": path_for_record(embedded_review_jsonl),
            "expected_feedback_download_name": "doctor_feedback_log.jsonl",
        },
        "validation": {
            "interactive_html": True,
            "total_uncertain_spans": total_spans,
            "spans_with_candidates": spans_with_candidates,
            "supports_actions": [
                "accept_asr",
                "select_alternative",
                "manual_edit",
                "reject",
                "unable_to_judge",
            ],
            "feedback_export": "browser_download_jsonl_and_localStorage",
            "research_use_only": all(sample.research_use_only for sample in samples),
        },
    }


def write_run_config(record: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    run_config_path = resolve_project_path(args.run_config_json)
    try:
        summary = run(args)
        write_run_config(summary, run_config_path)
        print("T036 医生审阅 HTML demo 生成完成。")
        print(f"- doctor_review_demo_html: {resolve_project_path(args.output_html)}")
        print(f"- embedded_review_jsonl: {resolve_project_path(args.embedded_review_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T036",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T036 医生审阅 HTML demo 生成失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
