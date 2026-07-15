"""生成绿/黄/红 ASR 可审阅样本包（T030）。

输入通常是 T029 生成的 `ASRConfidenceRecord` JSONL。脚本输出：

- review samples JSONL：给后续 HTML 或前端消费；
- consultation-level conversation JSONL：一行一例，按说话人 turn 组织完整对话；
- span-level CSV：给研究者快速表格浏览；
- 可选静态 HTML：展示带颜色高亮的 transcript 与候选列表。

本脚本不读取 reference 正文，也不生成临床建议。
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl
from clinical_asr_robustness.review_workflow import (
    T030_GENERATED_BY,
    build_review_conversations,
    build_review_html,
    build_review_samples,
    write_review_conversations_jsonl,
    write_review_samples_jsonl,
    write_review_spans_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t029_asr_nbest_candidates/primock57_asr_confidence_with_candidates.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t030_review_samples"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_asr_review_samples.jsonl"
DEFAULT_CONVERSATION_JSONL = (
    DEFAULT_OUTPUT_DIR / "primock57_asr_review_conversations.jsonl"
)
DEFAULT_OUTPUT_CSV = DEFAULT_OUTPUT_DIR / "primock57_asr_review_spans.csv"
DEFAULT_OUTPUT_HTML = DEFAULT_OUTPUT_DIR / "primock57_asr_review_samples.html"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t030_review_samples_run.json"


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
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument(
        "--conversation-jsonl",
        type=Path,
        default=DEFAULT_CONVERSATION_JSONL,
        help="一行一例的完整对话审阅包；内部保留原推理窗口与说话人 turn。",
    )
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument(
        "--interactive-html",
        action="store_true",
        help="生成带反馈导出控件的 HTML；默认是只读审阅包预览。",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="只生成 JSONL/CSV，不生成 HTML。",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_jsonl = resolve_project_path(args.input_jsonl)
    output_jsonl = resolve_project_path(args.output_jsonl)
    conversation_jsonl = resolve_project_path(args.conversation_jsonl)
    output_csv = resolve_project_path(args.output_csv)
    output_html = resolve_project_path(args.output_html)

    records = read_asr_confidence_jsonl(input_jsonl)
    samples = build_review_samples(records)
    conversations = build_review_conversations(samples)
    write_review_samples_jsonl(samples, output_jsonl)
    write_review_conversations_jsonl(conversations, conversation_jsonl)
    write_review_spans_csv(samples, output_csv)

    html_written = None
    if not args.no_html:
        output_html.parent.mkdir(parents=True, exist_ok=True)
        output_html.write_text(
            build_review_html(
                samples,
                title="T030 ASR 置信度绿/黄/红审阅样本",
                interactive=args.interactive_html,
                html_output_path=output_html,
                project_root=PROJECT_ROOT,
            ),
            encoding="utf-8",
            newline="\n",
        )
        html_written = output_html

    return build_run_summary(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        conversation_jsonl=conversation_jsonl,
        output_csv=output_csv,
        output_html=html_written,
        samples=samples,
        conversations=conversations,
        interactive_html=args.interactive_html,
    )


def build_run_summary(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    conversation_jsonl: Path,
    output_csv: Path,
    output_html: Path | None,
    samples: list[Any],
    conversations: list[Any],
    interactive_html: bool,
) -> dict[str, Any]:
    span_levels = Counter(
        span.confidence_level.value
        for sample in samples
        for span in sample.uncertain_spans
    )
    word_levels = Counter(
        word.confidence_level.value for sample in samples for word in sample.words
    )
    total_spans = sum(len(sample.uncertain_spans) for sample in samples)
    spans_with_candidates = sum(
        1
        for sample in samples
        for span in sample.uncertain_spans
        if span.alternatives
    )
    audio_paths = [
        resolve_project_path(sample.audio_filepath)
        for sample in samples
        if sample.audio_filepath
    ]
    yellow_red_review_words = [
        word
        for sample in samples
        for word in sample.words
        if word.review_required and word.confidence_level.value in {"yellow", "red"}
    ]
    return {
        "task_id": "T030",
        "status": "ok",
        "generated_by": T030_GENERATED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_confidence_jsonl": path_for_record(input_jsonl),
            "records_read": len(samples),
        },
        "outputs": {
            "review_samples_jsonl": path_for_record(output_jsonl),
            "review_conversations_jsonl": path_for_record(conversation_jsonl),
            "review_spans_csv": path_for_record(output_csv),
            "review_html": path_for_record(output_html),
        },
        "parameters": {
            "interactive_html": interactive_html,
            "audio_clip_padding_sec": 1.5,
            "feedback_decision_mode": "mutually_exclusive_single_radio_group",
            "review_unit": "complete_consultation",
            "inference_unit": "window_or_channel_record",
        },
        "validation": {
            "total_words": sum(len(sample.words) for sample in samples),
            "conversation_count": len(conversations),
            "speaker_turn_count": sum(
                len(conversation.speaker_turns) for conversation in conversations
            ),
            "diarization_status_counts": dict(
                Counter(conversation.diarization_status for conversation in conversations)
            ),
            "total_uncertain_spans": total_spans,
            "spans_with_candidates": spans_with_candidates,
            "span_confidence_levels": dict(span_levels),
            "word_confidence_levels": dict(word_levels),
            "audio_samples_with_paths": len(audio_paths),
            "audio_files_existing": sum(path.exists() for path in audio_paths),
            "spans_with_audio_timestamps": sum(
                span.start_sec is not None and span.end_sec is not None
                for sample in samples
                for span in sample.uncertain_spans
            ),
            "yellow_red_review_words": len(yellow_red_review_words),
            "yellow_red_review_words_with_audio_timestamps": sum(
                word.start_sec is not None and word.end_sec is not None
                for word in yellow_red_review_words
            ),
            "no_inline_reference_text": True,
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
        print("T030 ASR 绿/黄/红审阅样本包生成完成。")
        print(f"- review_samples_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(
            f"- review_conversations_jsonl: "
            f"{resolve_project_path(args.conversation_jsonl)}"
        )
        print(f"- review_spans_csv: {resolve_project_path(args.output_csv)}")
        if not args.no_html:
            print(f"- review_html: {resolve_project_path(args.output_html)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T030",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T030 ASR 绿/黄/红审阅样本包生成失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
