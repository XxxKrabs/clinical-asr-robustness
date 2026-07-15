"""用项目 .env 中的 LLM 配置补全残余 speaker gaps。"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_nbest_candidates import (
    generate_llm_word_candidate_content_with_api,
)
from clinical_asr_robustness.medical_entity_review import DEFAULT_API_KEY_ENV
from clinical_asr_robustness.speaker_semantic_resolution import (
    SemanticSpeakerDecision,
    SemanticSpeakerPrompt,
    apply_semantic_speaker_decisions,
    build_semantic_speaker_prompts,
    parse_semantic_speaker_decisions,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/remote_programming_40/t070_sortformer_pilot"
DEFAULT_INPUT_JSONL = (
    DEFAULT_OUTPUT_DIR
    / "remote_programming_40_shortest_full_candidates_diarized_smoothed.jsonl"
)
DEFAULT_OUTPUT_JSONL = (
    DEFAULT_OUTPUT_DIR
    / "remote_programming_40_shortest_full_candidates_diarized_semantic.jsonl"
)
DEFAULT_PROMPTS_JSONL = DEFAULT_OUTPUT_DIR / "semantic_speaker_prompts.jsonl"
DEFAULT_RESPONSES_JSONL = DEFAULT_OUTPUT_DIR / "semantic_speaker_responses.jsonl"
DEFAULT_RUN_JSON = DEFAULT_OUTPUT_DIR / "semantic_speaker_resolution_run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--prompts-jsonl", type=Path, default=DEFAULT_PROMPTS_JSONL)
    parser.add_argument("--responses-jsonl", type=Path, default=DEFAULT_RESPONSES_JSONL)
    parser.add_argument("--run-summary-json", type=Path, default=DEFAULT_RUN_JSON)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--llm-timeout-sec", type=float, default=120.0)
    parser.add_argument("--llm-max-tokens", type=int, default=4000)
    parser.add_argument("--llm-max-retries", type=int, default=3)
    parser.add_argument("--min-confidence", type=float, default=0.80)
    parser.add_argument("--force-resolve-all", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def messages_cache_key(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_response_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            item = json.loads(line)
            cache_key = str(item.get("cache_key") or "")
            if cache_key and isinstance(item.get("content"), str):
                cache[cache_key] = item
    return cache


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(item, ensure_ascii=False))
        file.write("\n")


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for item in items:
            file.write(json.dumps(item, ensure_ascii=False))
            file.write("\n")


def unresolved_word_count(records: list[ASRConfidenceRecord]) -> int:
    return sum(
        1
        for record in records
        for word in record.asr_words
        if not str(word.speaker_label or "").strip()
    )


def resolve_prompt_with_llm(
    prompt: SemanticSpeakerPrompt,
    *,
    args: argparse.Namespace,
    env_file: Path,
    response_cache: dict[str, dict[str, Any]],
    responses_path: Path,
) -> tuple[list[SemanticSpeakerDecision], dict[str, Any], bool, int]:
    messages = list(prompt.messages)
    cache_key = messages_cache_key(messages)
    cached = response_cache.get(cache_key)
    if cached is not None:
        try:
            decisions = parse_semantic_speaker_decisions(
                str(cached["content"]),
                prompt=prompt,
                require_all=True,
            )
            metadata = {**dict(cached.get("metadata") or {}), "cache_hit": True}
            return decisions, metadata, True, 0
        except (ValueError, TypeError):
            pass

    last_error: Exception | None = None
    for attempt in range(1, args.llm_max_retries + 1):
        try:
            content, metadata = generate_llm_word_candidate_content_with_api(
                messages,
                api_key_env=args.api_key_env,
                base_url=args.llm_base_url,
                model_name=args.llm_model,
                dotenv_path=env_file,
                timeout_sec=args.llm_timeout_sec,
                max_tokens=args.llm_max_tokens,
            )
            decisions = parse_semantic_speaker_decisions(
                content,
                prompt=prompt,
                require_all=True,
            )
            item = {
                "cache_key": cache_key,
                "prompt_id": prompt.prompt_id,
                "content": content,
                "metadata": metadata,
                "decision_count": len(decisions),
            }
            append_jsonl(responses_path, item)
            response_cache[cache_key] = item
            return decisions, {**metadata, "cache_hit": False}, False, 1
        except (ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt >= args.llm_max_retries:
                raise
            messages = [
                *prompt.messages,
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过结构校验。请重新输出严格 JSON，逐个覆盖所有 gap，"
                        "不要使用 allowed_speaker_labels 之外的标签。"
                    ),
                },
            ]
            time.sleep(min(float(attempt), 2.0))
    raise RuntimeError("LLM speaker resolution retries exhausted") from last_error


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.llm_max_retries <= 0:
        raise ValueError("--llm-max-retries 必须大于 0")
    if not 0.0 <= args.min_confidence <= 1.0:
        raise ValueError("--min-confidence 必须位于 [0, 1]")

    input_path = resolve_project_path(args.input_jsonl)
    output_path = resolve_project_path(args.output_jsonl)
    prompts_path = resolve_project_path(args.prompts_jsonl)
    responses_path = resolve_project_path(args.responses_jsonl)
    run_summary_path = resolve_project_path(args.run_summary_json)
    env_file = resolve_project_path(args.env_file)
    records = read_asr_confidence_jsonl(input_path)
    prompts = build_semantic_speaker_prompts(records)
    write_jsonl(
        prompts_path,
        [prompt.model_dump(mode="json") for prompt in prompts],
    )

    before_unresolved = unresolved_word_count(records)
    output_records = records
    response_cache = read_response_cache(responses_path)
    response_records: list[dict[str, Any]] = []
    api_request_count = 0
    cache_hit_count = 0
    all_decisions: list[SemanticSpeakerDecision] = []
    if args.run_llm:
        for prompt in prompts:
            decisions, metadata, cache_hit, api_requests = resolve_prompt_with_llm(
                prompt,
                args=args,
                env_file=env_file,
                response_cache=response_cache,
                responses_path=responses_path,
            )
            api_request_count += api_requests
            cache_hit_count += int(cache_hit)
            all_decisions.extend(decisions)
            output_records = apply_semantic_speaker_decisions(
                output_records,
                prompt=prompt,
                decisions=decisions,
                min_confidence=args.min_confidence,
                force_resolve_all=args.force_resolve_all,
                llm_metadata=metadata,
            )
            response_records.append(
                {
                    "prompt_id": prompt.prompt_id,
                    "dataset": prompt.dataset,
                    "consultation_id": prompt.consultation_id,
                    "decisions": [
                        decision.model_dump(mode="json") for decision in decisions
                    ],
                    "metadata": metadata,
                }
            )
        write_asr_confidence_jsonl(output_records, output_path)

    after_unresolved = unresolved_word_count(output_records)
    reason_counts = Counter(decision.reason_code for decision in all_decisions)
    speaker_counts = Counter(decision.speaker_label for decision in all_decisions)
    confidence_bands = Counter(
        "high"
        if decision.confidence >= 0.80
        else "medium" if decision.confidence >= 0.50 else "low"
        for decision in all_decisions
    )
    summary: dict[str, Any] = {
        "task_id": "T070",
        "schema_version": "semantic_speaker_resolution/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "completed" if args.run_llm else "prompts_only",
        "input_jsonl": project_relative(input_path),
        "output_jsonl": project_relative(output_path) if args.run_llm else None,
        "prompts_jsonl": project_relative(prompts_path),
        "responses_jsonl": project_relative(responses_path),
        "consultation_count": len(prompts),
        "gap_count": sum(len(prompt.gaps) for prompt in prompts),
        "gap_word_count": before_unresolved,
        "decision_count": len(all_decisions),
        "unresolved_word_count_before": before_unresolved,
        "unresolved_word_count_after": after_unresolved,
        "semantic_resolved_word_count": before_unresolved - after_unresolved,
        "force_resolve_all": args.force_resolve_all,
        "min_confidence": args.min_confidence,
        "api_request_count": api_request_count,
        "cache_hit_count": cache_hit_count,
        "decision_speaker_counts": dict(sorted(speaker_counts.items())),
        "decision_confidence_band_counts": dict(sorted(confidence_bands.items())),
        "decision_reason_counts": dict(sorted(reason_counts.items())),
        "acoustic_evidence_preserved": True,
        "semantic_labels_are_not_acoustic_ground_truth": True,
        "reference_used": False,
    }
    run_summary_path.parent.mkdir(parents=True, exist_ok=True)
    run_summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if response_records:
        decisions_path = responses_path.with_name(
            f"{responses_path.stem}_parsed{responses_path.suffix}"
        )
        write_jsonl(decisions_path, response_records)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
