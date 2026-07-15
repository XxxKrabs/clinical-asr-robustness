"""T045：真实 doctor LLM selector 与 repaired transcript 生成。

本脚本用一个独立 OpenAI-compatible LLM 扮演“模拟临床转写审阅者”，逐个
审阅 ASR 风险 span：

- 可选择候选词；
- 可保留原 ASR；
- 候选都不满意时可输出 manual edit；
- 记录每个 span 的原词、候选、LLM 选择、理由、是否修改；
- 回放反馈，生成 channel-level confirmed transcript；
- 合并为 consultation-level ``doctor_llm_repair`` JSONL，供 T045 评测脚本替换
  no-change baseline 复跑。

重要边界：

- selector 只读取 noisy ASR、候选、局部上下文和置信度，不读取 clean/reference、
  gold facts、病例摘要或评测结果；
- 输出是“模拟医生/LLM 选择”，不是真实医生审阅，也不构成临床建议；
- API key 从项目 `.env` 或环境变量读取，运行记录不写入密钥。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.asr_confidence import (  # noqa: E402
    CLINICAL_USE_WARNING,
    ASRAlternative,
    ASRConfidenceRecord,
    UncertainSpan,
    read_asr_confidence_jsonl,
)
from clinical_asr_robustness.medical_entity_review import (  # noqa: E402
    DEFAULT_API_KEY_ENV,
    endpoint_for_chat_completions,
    parse_json_object,
    resolve_llm_api_config,
)
from clinical_asr_robustness.review_workflow import (  # noqa: E402
    DoctorFeedbackEntry,
    ReviewFeedbackAction,
    apply_feedback_to_records,
    write_confirmed_transcripts_jsonl,
    write_feedback_entries_jsonl,
)

TASK_ID = "T045"
SELECTOR_SCHEMA_VERSION = "t045_doctor_llm_selector_decision/v1"
REPAIR_SCHEMA_VERSION = "t045_doctor_llm_repair_consultation/v1"
RUN_SCHEMA_VERSION = "t045_doctor_llm_selector_run/v1"
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t029_asr_nbest_candidates/"
    "primock57_asr_confidence_full_medical_entity_candidates.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t045_doctor_llm_selector"
DEFAULT_PROCESSED_DIR = (
    PROJECT_ROOT / "data/processed/primock57/t045_case_summary_three_texts"
)
DEFAULT_FEEDBACK_JSONL = DEFAULT_OUTPUT_DIR / "primock57_t045_doctor_llm_feedback.jsonl"
DEFAULT_DECISIONS_JSONL = DEFAULT_OUTPUT_DIR / "primock57_t045_doctor_llm_decisions.jsonl"
DEFAULT_CONFIRMED_CHANNEL_JSONL = (
    DEFAULT_OUTPUT_DIR / "primock57_t045_doctor_llm_confirmed_channel_transcripts.jsonl"
)
DEFAULT_REPAIR_CONSULTATION_JSONL = (
    DEFAULT_PROCESSED_DIR / "primock57_t045_doctor_llm_repair_real_selector.jsonl"
)
DEFAULT_RUN_JSON = DEFAULT_OUTPUT_DIR / "t045_doctor_llm_selector_run.json"

SUPPORTED_SELECTOR_ACTIONS = {
    "select_candidate",
    "keep_asr",
    "manual_edit",
    "reject",
    "unable_to_judge",
}


@dataclass(frozen=True)
class SpanReviewTask:
    decision_id: str
    record: ASRConfidenceRecord
    span: UncertainSpan
    alternatives: tuple[ASRAlternative, ...]
    payload: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=DEFAULT_INPUT_JSONL,
        help="ASR confidence JSONL，建议已包含候选；没有候选时 selector 可 manual_edit。",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--feedback-jsonl", type=Path, default=DEFAULT_FEEDBACK_JSONL)
    parser.add_argument("--decisions-jsonl", type=Path, default=DEFAULT_DECISIONS_JSONL)
    parser.add_argument(
        "--confirmed-channel-jsonl",
        type=Path,
        default=DEFAULT_CONFIRMED_CHANNEL_JSONL,
    )
    parser.add_argument(
        "--repair-consultation-jsonl",
        type=Path,
        default=DEFAULT_REPAIR_CONSULTATION_JSONL,
    )
    parser.add_argument("--run-json", type=Path, default=DEFAULT_RUN_JSON)
    parser.add_argument("--dotenv-path", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--selector-model", default=None)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--context-window-words", type=int, default=8)
    parser.add_argument("--max-candidates-per-span", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument(
        "--max-new-spans",
        type=int,
        default=None,
        help="本次最多新增审阅多少个 span；省略则审阅所有未完成 span。",
    )
    parser.add_argument(
        "--limit-records",
        type=int,
        default=None,
        help="调试用：只读取前 N 条 ASR record。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="默认跳过 decisions JSONL 中已有的 decision_id。",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="忽略已有 decisions，重新生成。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成 payload/run summary，不调用 LLM、不写 feedback。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_json = resolve_project_path(args.run_json)
    try:
        summary = run(args)
        write_json(summary, run_json)
        print("T045 doctor LLM selector 运行完成。")
        print(f"- total risk spans: {summary['counts']['total_risk_spans']}")
        print(f"- new decisions: {summary['counts']['new_decisions']}")
        print(f"- completed decisions: {summary['counts']['completed_decisions']}")
        print(f"- feedback: {summary['outputs']['feedback_jsonl']}")
        print(f"- repair consultation: {summary['outputs']['repair_consultation_jsonl']}")
    except Exception as exc:
        failed = {
            "schema_version": RUN_SCHEMA_VERSION,
            "task_id": TASK_ID,
            "status": "failed",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(failed, run_json)
        print("T045 doctor LLM selector 运行失败。")
        print(f"- error: {exc!r}")
        print(f"- run_json: {run_json}")
        raise SystemExit(1) from exc


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_jsonl = resolve_project_path(args.input_jsonl)
    feedback_jsonl = resolve_project_path(args.feedback_jsonl)
    decisions_jsonl = resolve_project_path(args.decisions_jsonl)
    confirmed_channel_jsonl = resolve_project_path(args.confirmed_channel_jsonl)
    repair_consultation_jsonl = resolve_project_path(args.repair_consultation_jsonl)
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    repair_consultation_jsonl.parent.mkdir(parents=True, exist_ok=True)

    records = read_asr_confidence_jsonl(input_jsonl)
    if args.limit_records is not None:
        records = records[: args.limit_records]

    tasks = build_span_review_tasks(
        records,
        context_window_words=args.context_window_words,
        max_candidates_per_span=args.max_candidates_per_span,
    )
    existing_decisions = (
        read_decisions_jsonl(decisions_jsonl) if args.resume and decisions_jsonl.exists() else {}
    )
    pending_tasks = [
        task for task in tasks if task.decision_id not in existing_decisions
    ]
    if args.max_new_spans is not None:
        pending_tasks = pending_tasks[: args.max_new_spans]

    selector_metadata: dict[str, Any] | None = None
    new_decisions: list[dict[str, Any]] = []
    if not args.dry_run and pending_tasks:
        config = resolve_llm_api_config(
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            model_name=args.selector_model,
            dotenv_path=resolve_project_path(args.dotenv_path),
        )
        selector_metadata = {
            "selector_model": config.model_name,
            "selector_base_url": config.base_url,
            "api_key_env": config.api_key_env,
            "dotenv_path": path_for_record(config.dotenv_path),
        }
        for batch in chunked(pending_tasks, args.batch_size):
            batch_decisions = call_selector_for_batch(
                batch,
                selector_model=config.model_name,
                base_url=config.base_url,
                api_key=config.api_key,
                timeout_sec=args.timeout_sec,
                max_tokens=args.max_tokens,
                retry_count=args.retry_count,
            )
            new_decisions.extend(batch_decisions)
            append_jsonl(batch_decisions, decisions_jsonl)
    elif args.dry_run:
        selector_metadata = {
            "selector_model": args.selector_model,
            "selector_base_url_explicitly_set": bool(args.base_url),
            "dry_run": True,
        }

    all_decisions = {
        **existing_decisions,
        **{str(item["decision_id"]): item for item in new_decisions},
    }
    completed_decisions = [
        all_decisions[task.decision_id]
        for task in tasks
        if task.decision_id in all_decisions
    ]
    if selector_metadata is None and completed_decisions:
        selector_metadata = infer_selector_metadata_from_decisions(completed_decisions)

    feedback_entries = [
        feedback_entry_from_decision(
            decision,
            task_by_decision_id={task.decision_id: task for task in tasks},
        )
        for decision in completed_decisions
    ]
    if feedback_entries:
        write_feedback_entries_jsonl(feedback_entries, feedback_jsonl)
        confirmed_records = apply_feedback_to_records(
            records,
            feedback_entries,
            require_feedback_for_all_spans=False,
        )
        write_confirmed_transcripts_jsonl(confirmed_records, confirmed_channel_jsonl)
        repair_records = build_consultation_repair_records(
            records,
            confirmed_records,
            selector_metadata=selector_metadata or {},
            feedback_jsonl=feedback_jsonl,
        )
        write_jsonl(repair_records, repair_consultation_jsonl)
    else:
        confirmed_records = []
        repair_records = []

    decision_action_counts = Counter(
        str(item.get("action") or "missing") for item in completed_decisions
    )
    changed_count = sum(
        1 for item in completed_decisions if bool(item.get("changed"))
    )
    total_candidate_count = sum(
        len(task.payload.get("candidates") or []) for task in tasks
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "dry_run" if args.dry_run else "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "asr_input_jsonl": path_for_record(input_jsonl),
        },
        "outputs": {
            "feedback_jsonl": path_for_record(feedback_jsonl),
            "decisions_jsonl": path_for_record(decisions_jsonl),
            "confirmed_channel_jsonl": path_for_record(confirmed_channel_jsonl),
            "repair_consultation_jsonl": path_for_record(repair_consultation_jsonl),
            "run_json": path_for_record(args.run_json),
        },
        "parameters": {
            "batch_size": args.batch_size,
            "context_window_words": args.context_window_words,
            "max_candidates_per_span": args.max_candidates_per_span,
            "max_new_spans": args.max_new_spans,
            "limit_records": args.limit_records,
            "resume": args.resume,
            "dry_run": args.dry_run,
            "timeout_sec": args.timeout_sec,
            "max_tokens": args.max_tokens,
            "retry_count": args.retry_count,
        },
        "selector": selector_metadata or {},
        "counts": {
            "asr_records": len(records),
            "total_risk_spans": len(tasks),
            "pending_before_run": len(
                [task for task in tasks if task.decision_id not in existing_decisions]
            ),
            "new_decisions": len(new_decisions),
            "completed_decisions": len(completed_decisions),
            "remaining_decisions": len(tasks) - len(completed_decisions),
            "feedback_entries": len(feedback_entries),
            "confirmed_channel_records": len(confirmed_records),
            "repair_consultation_records": len(repair_records),
            "spans_with_candidates": sum(
                1 for task in tasks if task.payload.get("candidates")
            ),
            "total_candidate_count": total_candidate_count,
            "changed_decision_count": changed_count,
        },
        "decision_action_counts": dict(decision_action_counts),
        "privacy_and_safety": {
            "selector_used_clean_reference": False,
            "selector_used_gold_facts": False,
            "selector_used_case_summary_outputs": False,
            "feedback_contains_full_transcript_text": False,
            "repair_jsonl_contains_full_transcript_text": True,
            "research_use_only": True,
            "clinical_use_warning": CLINICAL_USE_WARNING,
        },
        "limitations": [
            "LLM selector is a simulated reviewer, not a real clinician.",
            (
                "If candidates are missing, selector may keep ASR or manual_edit "
                "using local context only."
            ),
        ],
    }


def build_span_review_tasks(
    records: list[ASRConfidenceRecord],
    *,
    context_window_words: int,
    max_candidates_per_span: int,
) -> list[SpanReviewTask]:
    tasks: list[SpanReviewTask] = []
    for record in records:
        for span in record.uncertain_spans:
            decision_id = build_decision_id(record, span)
            alternatives = tuple(record.alternatives_for_span(span.span_id))
            selected_alternatives = alternatives[:max_candidates_per_span]
            tasks.append(
                SpanReviewTask(
                    decision_id=decision_id,
                    record=record,
                    span=span,
                    alternatives=selected_alternatives,
                    payload=build_selector_payload(
                        decision_id=decision_id,
                        record=record,
                        span=span,
                        alternatives=selected_alternatives,
                        context_window_words=context_window_words,
                    ),
                )
            )
    return tasks


def build_selector_payload(
    *,
    decision_id: str,
    record: ASRConfidenceRecord,
    span: UncertainSpan,
    alternatives: tuple[ASRAlternative, ...],
    context_window_words: int,
) -> dict[str, Any]:
    words = record.asr_transcript.split()
    left_start = max(0, span.start_word_index - context_window_words)
    right_end = min(len(words), span.end_word_index + context_window_words)
    left_context = " ".join(words[left_start : span.start_word_index])
    right_context = " ".join(words[span.end_word_index : right_end])
    return {
        "decision_id": decision_id,
        "record_id": record.record_id,
        "sample_id": record.sample_id,
        "consultation_id": record.consultation_id,
        "speaker": record.source_channel.value,
        "span_id": span.span_id,
        "asr_span_text": span.text,
        "left_context": left_context,
        "right_context": right_context,
        "confidence_level": span.confidence_level.value,
        "mean_confidence": span.mean_confidence,
        "min_confidence": span.min_confidence,
        "entity_type": entity_type_for_span(span),
        "candidates": [
            {
                "candidate_id": alternative.alternative_id,
                "text": alternative.text,
                "source": alternative.source,
                "rank": alternative.rank,
                "score": alternative.score,
                "confidence": alternative.confidence,
                "scope": alternative.scope.value,
            }
            for alternative in alternatives
        ],
    }


def call_selector_for_batch(
    tasks: list[SpanReviewTask],
    *,
    selector_model: str,
    base_url: str,
    api_key: str,
    timeout_sec: float,
    max_tokens: int,
    retry_count: int,
) -> list[dict[str, Any]]:
    messages = build_selector_messages([task.payload for task in tasks])
    payload = {
        "model": selector_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    content = ""
    metadata: dict[str, Any] = {}
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            content, metadata = call_chat_completions(
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                timeout_sec=timeout_sec,
            )
            break
        except Exception as exc:  # noqa: BLE001 - retry with preserved context
            last_error = exc
            if attempt >= retry_count:
                raise
            time.sleep(min(2.0 * (attempt + 1), 5.0))
    if not content and last_error is not None:
        raise last_error

    parsed = parse_json_object(content)
    decisions_payload = parsed.get("decisions") if isinstance(parsed, dict) else parsed
    if not isinstance(decisions_payload, list):
        raise ValueError("selector LLM output must contain a decisions list")
    decisions_by_id = normalize_selector_decisions(
        decisions_payload,
        tasks=tasks,
        response_metadata=metadata,
        raw_response_hash=stable_text_hash(content),
    )
    return [decisions_by_id[task.decision_id] for task in tasks]


def build_selector_messages(spans: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "你是一名模拟临床转写审阅者，只负责审阅 ASR noisy transcript 的风险 span。"
        "你不是在生成诊疗建议，不能根据医学常识补全音频中没有证据的信息。"
        "你只能基于给定 ASR span、局部上下文、speaker、置信度和候选词判断。"
        "不要读取或假设 clean/reference、gold facts、医生 notes 或病例摘要。"
        "如果某个候选明显比 ASR 更可信，选择 select_candidate。"
        "如果 ASR 已经可接受，选择 keep_asr。"
        "如果候选都不满意但局部上下文强烈支持一个简短转写，可选择 manual_edit，"
        "final_text 只能是替换该 span 的短词或短语。"
        "如果无法判断，选择 unable_to_judge。必须返回严格 JSON。"
    )
    user = {
        "instruction": (
            "请逐条审阅 spans，返回 decisions。final_text 必须是英文转写短语；"
            "不要解释成病历摘要；不要新增上下文中没有的疾病/药物/计划。"
        ),
        "output_schema": {
            "decisions": [
                {
                    "decision_id": "same as input",
                    "span_id": "same as input",
                    "action": (
                        "select_candidate|keep_asr|manual_edit|reject|unable_to_judge"
                    ),
                    "selected_candidate_id": None,
                    "final_text": "replacement text for this span",
                    "confidence": "high|medium|low",
                    "brief_reason": "short reason",
                    "risk_flags": ["medication|negation|symptom|test|speaker|none"],
                }
            ]
        },
        "spans": spans,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def call_chat_completions(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_sec: float,
) -> tuple[str, dict[str, Any]]:
    request = urllib.request.Request(
        endpoint_for_chat_completions(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(
            f"selector LLM API 请求失败：HTTP {exc.code}；响应片段：{error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"selector LLM API 请求失败：{exc.reason}") from exc
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("selector LLM API 响应缺少 choices[0].message.content") from exc
    metadata = {
        "model": response_payload.get("model"),
        "usage": response_payload.get("usage"),
        "finish_reason": (
            response_payload.get("choices", [{}])[0].get("finish_reason")
            if isinstance(response_payload.get("choices"), list)
            else None
        ),
    }
    return str(content), metadata


def normalize_selector_decisions(
    raw_decisions: list[Any],
    *,
    tasks: list[SpanReviewTask],
    response_metadata: dict[str, Any],
    raw_response_hash: str,
) -> dict[str, dict[str, Any]]:
    task_by_id = {task.decision_id: task for task in tasks}
    raw_by_id = {
        str(item.get("decision_id") or ""): item
        for item in raw_decisions
        if isinstance(item, dict)
    }
    output: dict[str, dict[str, Any]] = {}
    for task in tasks:
        raw = raw_by_id.get(task.decision_id)
        if raw is None:
            raw = {
                "decision_id": task.decision_id,
                "span_id": task.span.span_id,
                "action": "unable_to_judge",
                "selected_candidate_id": None,
                "final_text": task.span.text,
                "confidence": "low",
                "brief_reason": "selector_output_missing_for_span",
                "risk_flags": ["none"],
            }
        output[task.decision_id] = normalize_one_decision(
            raw,
            task=task_by_id[task.decision_id],
            response_metadata=response_metadata,
            raw_response_hash=raw_response_hash,
        )
    return output


def normalize_one_decision(
    raw: dict[str, Any],
    *,
    task: SpanReviewTask,
    response_metadata: dict[str, Any],
    raw_response_hash: str,
) -> dict[str, Any]:
    action = str(raw.get("action") or "unable_to_judge").strip()
    if action not in SUPPORTED_SELECTOR_ACTIONS:
        action = "unable_to_judge"
    candidate_ids = {alternative.alternative_id for alternative in task.alternatives}
    selected_candidate_id = raw.get("selected_candidate_id")
    if selected_candidate_id is not None:
        selected_candidate_id = str(selected_candidate_id).strip() or None
    if action == "select_candidate" and selected_candidate_id not in candidate_ids:
        action = "manual_edit"
        selected_candidate_id = None
    candidate_text = candidate_text_by_id(task.alternatives, selected_candidate_id)
    final_text = str(raw.get("final_text") or "").strip()
    if action == "select_candidate" and candidate_text:
        final_text = candidate_text
    elif action in {"keep_asr", "reject", "unable_to_judge"}:
        final_text = task.span.text
    elif not final_text:
        final_text = task.span.text
        action = "keep_asr"
    changed = normalize_space(final_text) != normalize_space(task.span.text)
    return {
        "schema_version": SELECTOR_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "decision_id": task.decision_id,
        "record_id": task.record.record_id,
        "sample_id": task.record.sample_id,
        "consultation_id": task.record.consultation_id,
        "source_channel": task.record.source_channel.value,
        "span_id": task.span.span_id,
        "original_text": task.span.text,
        "candidates": task.payload.get("candidates") or [],
        "action": action,
        "selected_candidate_id": selected_candidate_id,
        "final_text": final_text,
        "changed": changed,
        "confidence": str(raw.get("confidence") or "low"),
        "brief_reason": str(raw.get("brief_reason") or "").strip()[:500],
        "risk_flags": coerce_string_list(raw.get("risk_flags")) or ["none"],
        "selector_response_metadata": response_metadata,
        "raw_response_sha256": raw_response_hash,
        "selector_used_clean_reference": False,
        "selector_used_gold_facts": False,
        "selector_used_case_summary_outputs": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
    }


def feedback_entry_from_decision(
    decision: dict[str, Any],
    *,
    task_by_decision_id: dict[str, SpanReviewTask],
) -> DoctorFeedbackEntry:
    task = task_by_decision_id[str(decision["decision_id"])]
    action = str(decision.get("action") or "unable_to_judge")
    if action == "select_candidate":
        review_action = ReviewFeedbackAction.SELECT_ALTERNATIVE
    elif action == "manual_edit":
        review_action = ReviewFeedbackAction.MANUAL_EDIT
    elif action == "keep_asr":
        review_action = ReviewFeedbackAction.ACCEPT_ASR
    elif action == "reject":
        review_action = ReviewFeedbackAction.REJECT
    else:
        review_action = ReviewFeedbackAction.UNABLE_TO_JUDGE
    return DoctorFeedbackEntry(
        feedback_id=f"{decision['decision_id']}::selector",
        record_id=task.record.record_id,
        sample_id=task.record.sample_id,
        span_id=task.span.span_id,
        action=review_action,
        selected_alternative_id=(
            str(decision.get("selected_candidate_id"))
            if review_action == ReviewFeedbackAction.SELECT_ALTERNATIVE
            else None
        ),
        manual_text=(
            str(decision.get("final_text") or "")
            if review_action == ReviewFeedbackAction.MANUAL_EDIT
            else None
        ),
        original_text=task.span.text,
        reviewer_id="doctor_llm_selector",
        reviewer_role="simulated_clinical_transcript_reviewer",
        source="t045_doctor_llm_selector",
        note=str(decision.get("brief_reason") or "")[:240] or None,
        metadata={
            "decision_schema_version": decision.get("schema_version"),
            "decision_id": decision.get("decision_id"),
            "llm_action": decision.get("action"),
            "final_text": decision.get("final_text"),
            "changed": decision.get("changed"),
            "risk_flags": decision.get("risk_flags"),
            "confidence": decision.get("confidence"),
            "candidates": decision.get("candidates"),
            "selector_used_clean_reference": False,
            "selector_used_gold_facts": False,
            "selector_used_case_summary_outputs": False,
        },
    )


def build_consultation_repair_records(
    asr_records: list[ASRConfidenceRecord],
    confirmed_records: list[Any],
    *,
    selector_metadata: dict[str, Any],
    feedback_jsonl: Path,
) -> list[dict[str, Any]]:
    asr_by_key = {record_key(record): record for record in asr_records}
    confirmed_by_consultation: dict[str, list[Any]] = defaultdict(list)
    for record in confirmed_records:
        consultation_id = record.consultation_id or consultation_id_from_sample_id(record.sample_id)
        confirmed_by_consultation[str(consultation_id)].append(record)

    output: list[dict[str, Any]] = []
    for consultation_id, records in sorted(confirmed_by_consultation.items()):
        ordered = sorted(
            records,
            key=lambda item: source_channel_sort_key(item.source_channel.value),
        )
        speaker_turns = []
        action_summary: Counter[str] = Counter()
        changed_span_count = 0
        review_span_count = 0
        unresolved_span_count = 0
        for index, confirmed in enumerate(ordered):
            key = confirmed.record_id or confirmed.sample_id
            asr_record = asr_by_key.get(key)
            action_summary.update(confirmed.action_summary)
            review_span_count += len(confirmed.applied_spans)
            changed_span_count += sum(
                normalize_space(span.original_text) != normalize_space(span.confirmed_text)
                for span in confirmed.applied_spans
            )
            unresolved_span_count += len(confirmed.unresolved_span_ids)
            speaker_turns.append(
                {
                    "turn_index": index,
                    "source_channel": confirmed.source_channel.value,
                    "speaker_label": confirmed.source_channel.value,
                    "start_sec": 0.0,
                    "end_sec": asr_record.duration_sec if asr_record else None,
                    "text": confirmed.confirmed_transcript,
                    "source_record_id": confirmed.record_id,
                    "sample_id": confirmed.sample_id,
                }
            )
        transcript = "\n".join(
            f"{turn['speaker_label'].upper()}: {turn['text']}" for turn in speaker_turns
        )
        output.append(
            {
                "schema_version": REPAIR_SCHEMA_VERSION,
                "task_id": TASK_ID,
                "dataset": "primock57",
                "split": ordered[0].split if ordered else None,
                "sample_id": f"primock57:{consultation_id}",
                "consultation_id": consultation_id,
                "input_unit": "consultation",
                "input_variant": "doctor_llm_repair",
                "doctor_llm_repair_transcript": transcript,
                "confirmed_transcript": transcript,
                "speaker_turns": speaker_turns,
                "repair_mode": "real_doctor_llm_selector",
                "doctor_selector_status": (
                    "complete" if unresolved_span_count == 0 else "needs_review"
                ),
                "uses_clean_reference": False,
                "feedback_log": path_for_record(feedback_jsonl),
                "selector": selector_metadata,
                "review_cost": {
                    "review_span_count": review_span_count,
                    "changed_span_count": changed_span_count,
                    "unresolved_span_count": unresolved_span_count,
                    "action_summary": dict(action_summary),
                },
                "privacy_and_safety": {
                    "record_contains_full_transcript_text": True,
                    "selector_used_clean_reference": False,
                    "selector_used_gold_facts": False,
                    "selector_used_case_summary_outputs": False,
                    "research_use_only": True,
                },
                "clinical_use_warning": CLINICAL_USE_WARNING,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    return output


def read_decisions_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"无法解析 decisions JSONL 第 {line_number} 行：{path}") from exc
            decision_id = str(payload.get("decision_id") or "")
            if decision_id:
                decisions[decision_id] = payload
    return decisions


def infer_selector_metadata_from_decisions(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    models = Counter()
    for decision in decisions:
        metadata = decision.get("selector_response_metadata")
        if not isinstance(metadata, dict):
            continue
        model = metadata.get("model")
        if model:
            models[str(model)] += 1
    return {
        "selector_model": models.most_common(1)[0][0] if models else None,
        "selector_model_counts": dict(models),
        "source": "existing_decisions_jsonl",
    }


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def append_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def build_decision_id(record: ASRConfidenceRecord, span: UncertainSpan) -> str:
    key = record.record_id or record.sample_id
    return f"{key}::{span.span_id}"


def record_key(record: ASRConfidenceRecord) -> str:
    return record.record_id or record.sample_id


def consultation_id_from_sample_id(sample_id: str) -> str:
    parts = sample_id.split(":")
    for part in parts:
        if part.startswith("day") and "_consultation" in part:
            return part
    return sample_id


def entity_type_for_span(span: UncertainSpan) -> str:
    entities = span.metadata.get("medical_entities")
    if isinstance(entities, list) and entities:
        first = entities[0]
        if isinstance(first, dict):
            return str(first.get("entity_type") or "unknown")
    return str(span.metadata.get("entity_type") or "unknown")


def candidate_text_by_id(
    alternatives: tuple[ASRAlternative, ...],
    alternative_id: str | None,
) -> str | None:
    if alternative_id is None:
        return None
    for alternative in alternatives:
        if alternative.alternative_id == alternative_id:
            return alternative.text
    return None


def coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_space(value: str | None) -> str:
    return " ".join(str(value or "").split()).casefold()


def stable_text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunked(items: list[SpanReviewTask], size: int) -> list[list[SpanReviewTask]]:
    if size <= 0:
        raise ValueError("batch-size must be greater than 0")
    return [items[index : index + size] for index in range(0, len(items), size)]


def source_channel_sort_key(channel: str) -> tuple[int, str]:
    if channel == "doctor":
        return (0, channel)
    if channel == "patient":
        return (1, channel)
    return (9, channel)


def resolve_project_path(path_value: str | Path | None) -> Path | None:
    if path_value is None:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def path_for_record(path_value: str | Path | None) -> str | None:
    if path_value is None:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
