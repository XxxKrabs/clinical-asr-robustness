"""T041：从 noisy ASR transcript 生成病例摘要下游任务。

默认只生成 prompt-ready JSONL，不访问外部 LLM。若确认 `.env` 中已有 API_KEY /
BASE_URL / MODEL_ID，可加 `--run-llm` 调用 OpenAI-compatible Chat Completions API。
所有输出均为研究评估用途，不构成临床建议。
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
from clinical_asr_robustness.case_summary_generation import (  # noqa: E402
    DEFAULT_SUMMARY_LANGUAGE,
    INPUT_UNIT_CONSULTATION,
    INPUT_UNIT_RECORD,
    run_case_summary_generation,
    write_json,
)
from clinical_asr_robustness.medical_entity_review import DEFAULT_API_KEY_ENV  # noqa: E402

DEFAULT_ASR_INPUT_JSONL = Path(
    "outputs/primock57/t029_asr_nbest_candidates/"
    "primock57_asr_confidence_medical_entity_candidates.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("outputs/primock57/t041_case_summary_generation")
DEFAULT_RECORDS_NAME = "primock57_t041_case_summary_records.jsonl"
DEFAULT_SUMMARY_NAME = "primock57_t041_case_summary_summary.json"
DEFAULT_RUN_CONFIG_NAME = "t041_case_summary_generation_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asr-input-jsonl",
        type=Path,
        default=DEFAULT_ASR_INPUT_JSONL,
        help="ASR confidence JSONL，默认使用 T029 医学实体候选输出。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="T041 输出目录；默认位于 outputs/ 下。",
    )
    parser.add_argument(
        "--records-name",
        default=DEFAULT_RECORDS_NAME,
        help="逐条病例摘要任务 JSONL 文件名。",
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help="聚合 summary JSON 文件名。",
    )
    parser.add_argument(
        "--run-config-name",
        default=DEFAULT_RUN_CONFIG_NAME,
        help="运行摘要 JSON 文件名。",
    )
    parser.add_argument(
        "--group-by",
        choices=[INPUT_UNIT_CONSULTATION, INPUT_UNIT_RECORD],
        default=INPUT_UNIT_CONSULTATION,
        help="病例摘要输入粒度；默认按 consultation_id 合并 doctor/patient 分声道转写。",
    )
    parser.add_argument(
        "--summary-language",
        choices=["zh", "en"],
        default=DEFAULT_SUMMARY_LANGUAGE,
        help="病例摘要输出语言；默认中文。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="可选，只读取前 N 条 ASR record，便于快速调试。",
    )
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="实际调用 LLM 生成病例摘要；默认不调用，只导出 prompt-ready JSONL。",
    )
    parser.add_argument(
        "--exclude-prompts",
        action="store_true",
        help="不在逐条 JSONL 中保存 prompt_messages；默认保存，便于审阅和复跑。",
    )
    parser.add_argument(
        "--dotenv-path",
        type=Path,
        default=Path(".env"),
        help="LLM 配置文件路径；仅 --run-llm 时使用，默认项目根目录 .env。",
    )
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        help="API key 环境变量名；不要把真实 key 写到命令行。",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL；默认从 .env/环境变量读取。",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="模型名；默认从 .env/环境变量读取。",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=90.0,
        help="LLM API 超时时间。",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1600,
        help="LLM 输出 max_tokens。",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = resolve_project_path(args.output_dir, PROJECT_ROOT)
    records_path = output_dir / args.records_name
    summary_path = output_dir / args.summary_name
    return run_case_summary_generation(
        asr_input_jsonl=args.asr_input_jsonl,
        output_records_jsonl=records_path,
        output_summary_json=summary_path,
        project_root=PROJECT_ROOT,
        group_by=args.group_by,
        run_llm=args.run_llm,
        limit=args.limit,
        summary_language=args.summary_language,
        include_prompt=not args.exclude_prompts,
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        model_name=args.model,
        dotenv_path=args.dotenv_path,
        timeout_sec=args.timeout_sec,
        max_tokens=args.max_tokens,
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
        "task_id": "T041",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_input_jsonl": _path_for_record(
                resolve_project_path(args.asr_input_jsonl, PROJECT_ROOT)
            ),
            "group_by": args.group_by,
            "limit": args.limit,
            "summary_language": args.summary_language,
            "run_llm": args.run_llm,
            "dotenv_path": _path_for_record(
                resolve_project_path(args.dotenv_path, PROJECT_ROOT)
            )
            if args.run_llm
            else None,
            "api_key_env": args.api_key_env if args.run_llm else None,
            "base_url_explicitly_set": bool(args.base_url),
            "model_explicitly_set": bool(args.model),
        },
        "outputs": {
            "records_jsonl": _path_for_record(output_dir / args.records_name),
            "summary_json": _path_for_record(output_dir / args.summary_name),
            "run_config_json": _path_for_record(output_dir / args.run_config_name),
        },
        "validation": {
            "input_units": summary.get("record_count", 0),
            "source_records": summary.get("source_record_count", 0),
            "summary_contains_full_transcript_text": False,
            "records_jsonl_contains_full_transcript_text": True,
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
        mode = "病例摘要已生成" if args.run_llm else "病例摘要 prompt 已准备"
        print(f"T041 {mode}。")
        print(f"- input units: {summary['record_count']}")
        print(f"- source ASR records: {summary['source_record_count']}")
        print(f"- group_by: {summary['group_by']}")
        print(f"- status counts: {summary['status_counts']}")
        print(f"- records: {output_dir / args.records_name}")
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
        print("T041 病例摘要下游任务失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
