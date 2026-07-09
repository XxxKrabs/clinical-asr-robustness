"""一键串联 ASR 置信度医生审阅 demo 主流程。

默认行为：

1. 复用已有 T028 ASR confidence JSONL 和 T037 n-best JSONL；
2. 运行 T038 医学实体 gating；
3. 运行 T029 n-best/top-k 候选对齐；
4. 运行 T030 审阅样本包；
5. 运行 T036 单文件医生审阅 HTML demo。

如果需要从音频重新跑 ASR 和 n-best，显式增加 `--run-asr`。默认重新跑 ASR 时只取
manifest 前 2 条样本；需要全量时传 `--asr-limit 0`。

所有输出均为研究 demo，不构成临床建议；不要把 `.env`、真实患者隐私或未脱敏
临床数据提交到 Git。
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MANIFEST = Path("data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl")
DEFAULT_MODEL_PATH = Path("data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo")

DEFAULT_ASR_CONFIDENCE_JSONL = Path(
    "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl"
)
DEFAULT_T028_RUN_CONFIG = Path(
    "outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_limit2_run.json"
)
DEFAULT_NBEST_JSONL = Path(
    "outputs/primock57/t037_nemo_asr_nbest/primock57_sequence_nbest_limit2.jsonl"
)
DEFAULT_T037_RUN_CONFIG = Path(
    "outputs/primock57/t037_nemo_asr_nbest/t037_nemo_asr_nbest_limit2_run.json"
)

DEFAULT_MEDICAL_ENTITY_JSONL = Path(
    "outputs/primock57/t038_medical_entity_review/"
    "primock57_asr_confidence_medical_entities.jsonl"
)
DEFAULT_ENTITY_CACHE_JSONL = Path(
    "outputs/primock57/t038_medical_entity_review/primock57_medical_entities_llm.jsonl"
)
DEFAULT_T038_RUN_CONFIG = Path(
    "outputs/primock57/t038_medical_entity_review/t038_medical_entity_review_run.json"
)

DEFAULT_CANDIDATE_JSONL = Path(
    "outputs/primock57/t029_asr_nbest_candidates/"
    "primock57_asr_confidence_medical_entity_candidates.jsonl"
)
DEFAULT_T029_RUN_CONFIG = Path(
    "outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_run.json"
)
DEFAULT_LLM_CANDIDATE_PROMPTS_JSONL = Path(
    "outputs/primock57/t029_asr_nbest_candidates/primock57_llm_word_candidate_prompts.jsonl"
)

DEFAULT_REVIEW_JSONL = Path(
    "outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.jsonl"
)
DEFAULT_REVIEW_CSV = Path(
    "outputs/primock57/t030_review_samples/primock57_medical_entity_review_spans.csv"
)
DEFAULT_REVIEW_HTML = Path(
    "outputs/primock57/t030_review_samples/primock57_medical_entity_review_samples.html"
)
DEFAULT_T030_RUN_CONFIG = Path("outputs/primock57/t030_review_samples/t030_review_samples_run.json")

DEFAULT_DOCTOR_HTML = Path("outputs/primock57/t036_doctor_review_demo/doctor_review_demo.html")
DEFAULT_EMBEDDED_REVIEW_JSONL = Path(
    "outputs/primock57/t036_doctor_review_demo/doctor_review_samples.embedded.jsonl"
)
DEFAULT_T036_RUN_CONFIG = Path(
    "outputs/primock57/t036_doctor_review_demo/t036_doctor_review_demo_run.json"
)

DEFAULT_FEEDBACK_JSONL = Path("outputs/primock57/t036_doctor_review_demo/doctor_feedback_log.jsonl")
DEFAULT_CONFIRMED_JSONL = Path(
    "outputs/primock57/t035_confirmed_transcripts/primock57_confirmed_transcripts.jsonl"
)
DEFAULT_T035_RUN_CONFIG = Path(
    "outputs/primock57/t035_confirmed_transcripts/t035_confirmed_transcripts_run.json"
)

DEFAULT_PIPELINE_RUN_CONFIG = Path(
    "outputs/primock57/asr_review_pipeline/asr_review_pipeline_run.json"
)


@dataclass(frozen=True)
class PipelineStep:
    """一个可执行的流水线步骤。"""

    step_id: str
    title: str
    command: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="用于调用各阶段脚本的 Python；默认使用当前解释器。",
    )
    parser.add_argument(
        "--run-asr",
        action="store_true",
        help="从 manifest/audio 重新跑 T028 confidence 和 T037 n-best；默认复用已有输出。",
    )
    parser.add_argument(
        "--asr-limit",
        type=int,
        default=None,
        help=(
            "重新跑 ASR 时处理前 N 条；默认未指定样本时取 2 条。"
            "传 0 表示不加 limit、跑完整输入。"
        ),
    )
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--transcribe-chunk-size", type=int, default=1)

    parser.add_argument("--asr-confidence-jsonl", type=Path, default=DEFAULT_ASR_CONFIDENCE_JSONL)
    parser.add_argument("--t028-run-config-json", type=Path, default=DEFAULT_T028_RUN_CONFIG)
    parser.add_argument("--nbest-jsonl", type=Path, default=DEFAULT_NBEST_JSONL)
    parser.add_argument("--t037-run-config-json", type=Path, default=DEFAULT_T037_RUN_CONFIG)

    parser.add_argument("--medical-entity-jsonl", type=Path, default=DEFAULT_MEDICAL_ENTITY_JSONL)
    parser.add_argument("--entity-cache-jsonl", type=Path, default=DEFAULT_ENTITY_CACHE_JSONL)
    parser.add_argument("--t038-run-config-json", type=Path, default=DEFAULT_T038_RUN_CONFIG)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--force-refresh-entities", action="store_true")
    parser.add_argument("--llm-timeout-sec", type=float, default=60.0)

    parser.add_argument("--candidate-jsonl", type=Path, default=DEFAULT_CANDIDATE_JSONL)
    parser.add_argument("--t029-run-config-json", type=Path, default=DEFAULT_T029_RUN_CONFIG)
    parser.add_argument(
        "--llm-candidate-prompts-jsonl",
        type=Path,
        default=DEFAULT_LLM_CANDIDATE_PROMPTS_JSONL,
    )
    parser.add_argument("--max-sequence-alternatives", type=int, default=5)
    parser.add_argument("--max-span-alternatives", type=int, default=3)
    parser.add_argument("--run-llm-candidates", action="store_true")
    parser.add_argument("--max-llm-word-candidates", type=int, default=3)
    parser.add_argument("--llm-word-context-window", type=int, default=5)
    parser.add_argument("--max-llm-lexicon-terms", type=int, default=24)

    parser.add_argument("--review-jsonl", type=Path, default=DEFAULT_REVIEW_JSONL)
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--review-html", type=Path, default=DEFAULT_REVIEW_HTML)
    parser.add_argument("--t030-run-config-json", type=Path, default=DEFAULT_T030_RUN_CONFIG)

    parser.add_argument("--doctor-html", type=Path, default=DEFAULT_DOCTOR_HTML)
    parser.add_argument("--embedded-review-jsonl", type=Path, default=DEFAULT_EMBEDDED_REVIEW_JSONL)
    parser.add_argument("--t036-run-config-json", type=Path, default=DEFAULT_T036_RUN_CONFIG)
    parser.add_argument("--html-title", default="T036 医学实体优先 ASR 医生审阅 demo")
    parser.add_argument(
        "--open-html",
        action="store_true",
        help="流程完成后尝试打开最终 T036 HTML；失败时只打印路径。",
    )

    parser.add_argument("--apply-feedback", action="store_true")
    parser.add_argument(
        "--apply-feedback-if-exists",
        action="store_true",
        help="若反馈 JSONL 已存在，则继续跑 T035 confirmed transcript。",
    )
    parser.add_argument("--feedback-jsonl", type=Path, default=DEFAULT_FEEDBACK_JSONL)
    parser.add_argument("--confirmed-jsonl", type=Path, default=DEFAULT_CONFIRMED_JSONL)
    parser.add_argument("--t035-run-config-json", type=Path, default=DEFAULT_T035_RUN_CONFIG)
    parser.add_argument("--require-feedback-for-all-spans", action="store_true")

    parser.add_argument(
        "--pipeline-run-config-json",
        type=Path,
        default=DEFAULT_PIPELINE_RUN_CONFIG,
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令。")

    return parser.parse_args()


def resolve_project_path(path: Path | str) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return PROJECT_ROOT / resolved


def path_for_summary(path: Path | str) -> str:
    resolved = resolve_project_path(path)
    try:
        return resolved.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def command_for_display(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def ensure_file_exists(path: Path, message: str) -> None:
    resolved = resolve_project_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"{message}：{path_for_summary(path)}")


def effective_asr_limit(args: argparse.Namespace) -> int | None:
    if args.asr_limit is not None:
        if args.asr_limit < 0:
            raise ValueError("--asr-limit 不能小于 0")
        return None if args.asr_limit == 0 else args.asr_limit
    if args.sample_ids or args.record_index:
        return None
    return 2


def add_sample_selection(command: list[str], args: argparse.Namespace) -> None:
    for sample_id in args.sample_ids or []:
        command.extend(["--sample-id", sample_id])
    for record_index in args.record_index or []:
        command.extend(["--record-index", str(record_index)])
    asr_limit = effective_asr_limit(args)
    if asr_limit is not None:
        command.extend(["--limit", str(asr_limit)])


def build_t028_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/export_nemo_asr_confidence.py",
        "--manifest",
        str(args.manifest),
        "--model-path",
        str(args.model_path),
        "--output-jsonl",
        str(args.asr_confidence_jsonl),
        "--run-config-json",
        str(args.t028_run_config_json),
        "--device",
        args.device,
        "--batch-size",
        str(args.batch_size),
        "--num-workers",
        str(args.num_workers),
        "--transcribe-chunk-size",
        str(args.transcribe_chunk_size),
    ]
    add_sample_selection(command, args)
    return PipelineStep("T028", "导出 ASR transcript、词级置信度和初始风险 span", command)


def build_t037_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/export_nemo_asr_nbest.py",
        "--manifest",
        str(args.manifest),
        "--model-path",
        str(args.model_path),
        "--output-jsonl",
        str(args.nbest_jsonl),
        "--run-config-json",
        str(args.t037_run_config_json),
        "--device",
        args.device,
        "--batch-size",
        str(args.batch_size),
        "--num-workers",
        str(args.num_workers),
        "--transcribe-chunk-size",
        str(args.transcribe_chunk_size),
    ]
    add_sample_selection(command, args)
    return PipelineStep("T037", "导出 sequence-level n-best / beam 候选", command)


def build_t038_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/extract_medical_entity_review_spans.py",
        "--input-jsonl",
        str(args.asr_confidence_jsonl),
        "--output-jsonl",
        str(args.medical_entity_jsonl),
        "--entity-cache-jsonl",
        str(args.entity_cache_jsonl),
        "--run-config-json",
        str(args.t038_run_config_json),
        "--env-file",
        str(args.env_file),
        "--timeout-sec",
        str(args.llm_timeout_sec),
    ]
    if args.force_refresh_entities:
        command.append("--force-refresh-entities")
    return PipelineStep("T038", "医学实体优先 gating，只高亮医学实体", command)


def build_t029_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/extract_asr_nbest_candidates.py",
        "--input-jsonl",
        str(args.medical_entity_jsonl),
        "--nbest-jsonl",
        str(args.nbest_jsonl),
        "--output-jsonl",
        str(args.candidate_jsonl),
        "--run-config-json",
        str(args.t029_run_config_json),
        "--max-sequence-alternatives",
        str(args.max_sequence_alternatives),
        "--max-span-alternatives",
        str(args.max_span_alternatives),
        "--llm-candidate-prompts-jsonl",
        str(args.llm_candidate_prompts_jsonl),
        "--max-llm-word-candidates",
        str(args.max_llm_word_candidates),
        "--llm-word-context-window",
        str(args.llm_word_context_window),
        "--max-llm-lexicon-terms",
        str(args.max_llm_lexicon_terms),
        "--env-file",
        str(args.env_file),
        "--llm-timeout-sec",
        str(args.llm_timeout_sec),
    ]
    if args.run_llm_candidates:
        command.append("--run-llm-candidates")
    return PipelineStep("T029", "把 n-best/top-k 候选对齐到医学实体待审 span", command)


def build_t030_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/build_asr_review_samples.py",
        "--input-jsonl",
        str(args.candidate_jsonl),
        "--output-jsonl",
        str(args.review_jsonl),
        "--output-csv",
        str(args.review_csv),
        "--output-html",
        str(args.review_html),
        "--run-config-json",
        str(args.t030_run_config_json),
        "--interactive-html",
    ]
    return PipelineStep("T030", "生成审阅样本 JSONL/CSV 和预览 HTML", command)


def build_t036_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/build_doctor_review_demo_html.py",
        "--review-jsonl",
        str(args.review_jsonl),
        "--input-jsonl",
        str(args.candidate_jsonl),
        "--output-html",
        str(args.doctor_html),
        "--embedded-review-jsonl",
        str(args.embedded_review_jsonl),
        "--run-config-json",
        str(args.t036_run_config_json),
        "--title",
        args.html_title,
    ]
    return PipelineStep("T036", "生成最终医生审阅单文件 HTML demo", command)


def build_t035_step(args: argparse.Namespace) -> PipelineStep:
    command = [
        args.python_executable,
        "scripts/apply_asr_review_feedback.py",
        "--input-jsonl",
        str(args.candidate_jsonl),
        "--feedback-jsonl",
        str(args.feedback_jsonl),
        "--output-jsonl",
        str(args.confirmed_jsonl),
        "--run-config-json",
        str(args.t035_run_config_json),
    ]
    if args.require_feedback_for_all_spans:
        command.append("--require-feedback-for-all-spans")
    return PipelineStep("T035", "回放反馈并生成 confirmed transcript", command)


def should_apply_feedback(args: argparse.Namespace) -> bool:
    if args.apply_feedback:
        return True
    if not args.apply_feedback_if_exists:
        return False
    feedback_path = resolve_project_path(args.feedback_jsonl)
    exists = feedback_path.exists()
    if not exists:
        print(f"T035 跳过：未发现反馈日志 {path_for_summary(args.feedback_jsonl)}")
    return exists


def build_steps(args: argparse.Namespace) -> list[PipelineStep]:
    steps: list[PipelineStep] = []
    if args.run_asr:
        steps.extend([build_t028_step(args), build_t037_step(args)])
    steps.extend(
        [
            build_t038_step(args),
            build_t029_step(args),
            build_t030_step(args),
            build_t036_step(args),
        ]
    )
    if should_apply_feedback(args):
        steps.append(build_t035_step(args))
    return steps


def validate_existing_inputs(args: argparse.Namespace) -> None:
    if not args.run_asr:
        ensure_file_exists(
            args.asr_confidence_jsonl,
            "未找到 T028 ASR confidence JSONL；可加 --run-asr 重新生成",
        )
        ensure_file_exists(
            args.nbest_jsonl,
            "未找到 T037 n-best JSONL；可加 --run-asr 重新生成",
        )
    if args.apply_feedback:
        ensure_file_exists(args.feedback_jsonl, "未找到医生反馈 JSONL")


def run_step(step: PipelineStep, *, dry_run: bool) -> dict[str, Any]:
    print(f"\n=== {step.step_id} | {step.title} ===", flush=True)
    print(command_for_display(step.command), flush=True)
    started = time.perf_counter()
    if dry_run:
        return {
            "step_id": step.step_id,
            "title": step.title,
            "status": "dry_run",
            "command": step.command,
            "returncode": None,
            "elapsed_sec": 0.0,
        }

    completed = subprocess.run(step.command, cwd=PROJECT_ROOT, check=False)
    elapsed_sec = round(time.perf_counter() - started, 3)
    status = "ok" if completed.returncode == 0 else "failed"
    return {
        "step_id": step.step_id,
        "title": step.title,
        "status": status,
        "command": step.command,
        "returncode": completed.returncode,
        "elapsed_sec": elapsed_sec,
    }


def run_steps(steps: list[PipelineStep], *, dry_run: bool) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    for step in steps:
        result = run_step(step, dry_run=dry_run)
        results.append(result)
        if result["status"] == "failed":
            return results, False
    return results, True


def running_under_wsl() -> bool:
    proc_version = Path("/proc/version")
    if not proc_version.exists():
        return False
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8").casefold()
    except OSError:
        return False


def open_html(path: Path) -> bool:
    html_path = resolve_project_path(path)
    if not html_path.exists():
        print(f"无法打开 HTML，文件不存在：{path_for_summary(path)}")
        return False

    try:
        if running_under_wsl():
            wslpath = subprocess.run(
                ["wslpath", "-w", str(html_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            windows_path = wslpath.stdout.strip()
            subprocess.run(["cmd.exe", "/c", "start", "", windows_path], check=True)
        else:
            webbrowser.open(html_path.resolve().as_uri())
    except Exception as exc:  # noqa: BLE001
        print(f"自动打开浏览器失败：{exc!r}")
        print(f"请手动打开：{path_for_summary(path)}")
        return False
    return True


def build_summary(
    args: argparse.Namespace,
    *,
    step_results: list[dict[str, Any]],
    success: bool,
) -> dict[str, Any]:
    return {
        "task_id": "ASR_REVIEW_PIPELINE",
        "status": "ok" if success else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "parameters": {
            "run_asr": args.run_asr,
            "effective_asr_limit": effective_asr_limit(args),
            "sample_ids": args.sample_ids,
            "record_indices": args.record_index,
            "force_refresh_entities": args.force_refresh_entities,
            "apply_feedback": args.apply_feedback,
            "apply_feedback_if_exists": args.apply_feedback_if_exists,
            "dry_run": args.dry_run,
        },
        "inputs": {
            "manifest": path_for_summary(args.manifest),
            "model_path": path_for_summary(args.model_path),
            "asr_confidence_jsonl": path_for_summary(args.asr_confidence_jsonl),
            "nbest_jsonl": path_for_summary(args.nbest_jsonl),
            "env_file": path_for_summary(args.env_file),
            "feedback_jsonl": path_for_summary(args.feedback_jsonl),
        },
        "outputs": {
            "medical_entity_jsonl": path_for_summary(args.medical_entity_jsonl),
            "candidate_jsonl": path_for_summary(args.candidate_jsonl),
            "review_jsonl": path_for_summary(args.review_jsonl),
            "review_csv": path_for_summary(args.review_csv),
            "review_html": path_for_summary(args.review_html),
            "doctor_html": path_for_summary(args.doctor_html),
            "embedded_review_jsonl": path_for_summary(args.embedded_review_jsonl),
            "confirmed_jsonl": path_for_summary(args.confirmed_jsonl),
        },
        "steps": step_results,
    }


def write_summary(summary: dict[str, Any], output_path: Path) -> None:
    resolved = resolve_project_path(output_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")


def print_handoff(args: argparse.Namespace, *, success: bool) -> None:
    if not success:
        print("\n流程中断。请先看上面失败步骤的报错，再重跑同一条命令。")
        return

    print("\nASR 医学实体优先医生审阅流程完成。")
    print(f"- 最终 HTML：{path_for_summary(args.doctor_html)}")
    print(f"- 审阅样本：{path_for_summary(args.review_jsonl)}")
    print(f"- 候选输入：{path_for_summary(args.candidate_jsonl)}")
    print(f"- 流水线摘要：{path_for_summary(args.pipeline_run_config_json)}")
    print("\nPowerShell 手动打开 HTML：")
    print(f"Start-Process {str(args.doctor_html)}")
    print("\nHTML 下载反馈后，可把 doctor_feedback_log.jsonl 放到默认输出目录，再运行：")
    print(
        command_for_display(
            [
                "wsl.exe",
                "-d",
                "Ubuntu-22.04",
                "-e",
                "/home/krabs/miniforge3/envs/clinical-asr/bin/python",
                "scripts/run_asr_review_pipeline.py",
                "--apply-feedback",
            ]
        )
    )


def main() -> None:
    args = parse_args()
    try:
        validate_existing_inputs(args)
        steps = build_steps(args)
        step_results, success = run_steps(steps, dry_run=args.dry_run)
        if not args.dry_run:
            summary = build_summary(args, step_results=step_results, success=success)
            write_summary(summary, args.pipeline_run_config_json)
        if success and args.open_html and not args.dry_run:
            open_html(args.doctor_html)
        print_handoff(args, success=success)
        raise SystemExit(0 if success else 1)
    except Exception as exc:
        print(f"\n流水线启动失败：{exc!r}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
