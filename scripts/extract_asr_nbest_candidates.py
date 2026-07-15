"""为 ASR confidence JSONL 追加 n-best/top-k 候选（T029）。

输入通常是 T028 生成的 ASR confidence JSONL；可额外提供 sequence-level
n-best JSONL。脚本会：

1. 把 n-best 保存为 `scope="sequence"` 的 `asr_alternatives`；
2. 将 sequence n-best 与 `uncertain_spans` 做词级 diff 对齐；
3. 为每个 uncertain span 生成 `scope="span"` 候选，并回写
   `uncertain_spans[].alternative_ids`。

本脚本不读取 reference 正文，也不把候选视为临床建议。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    AlternativeScope,
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_nbest_candidates import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_AUX_MIN_SIMILARITY,
    DEFAULT_LLM_CANDIDATE_PROMPT_PROFILE,
    DEFAULT_LLM_WORD_CANDIDATES,
    DEFAULT_LLM_WORD_CONTEXT_WINDOW,
    DEFAULT_LLM_WORD_LEXICON_TERMS,
    DEFAULT_NBEST_SOURCE,
    LLM_WORD_AUX_SOURCE,
    MEDICAL_LEXICON_AUX_SOURCE,
    SEQUENCE_ALIGNMENT_METHOD,
    SPAN_ALIGNMENT_METHOD,
    attach_nbest_candidates_to_record,
    build_llm_conversation_contexts,
    build_llm_word_candidate_prompt_records,
    generate_llm_word_candidate_content_with_api,
    llm_prompt_to_json_record,
    load_medical_candidate_lexicon,
    load_nbest_jsonl,
    nbest_items_for_record,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t029_asr_nbest_candidates"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_asr_confidence_with_candidates.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t029_asr_nbest_candidates_run.json"
DEFAULT_AUX_LEXICON_JSON = PROJECT_ROOT / "configs/medical_candidate_lexicon.example.json"
DEFAULT_LLM_CANDIDATE_PROMPTS_JSONL = (
    DEFAULT_OUTPUT_DIR / "primock57_llm_word_candidate_prompts.jsonl"
)
DEFAULT_LLM_CANDIDATE_CACHE_JSONL = (
    DEFAULT_OUTPUT_DIR / "primock57_llm_word_candidate_responses.jsonl"
)


def path_for_record(path: Path, project_root: Path = PROJECT_ROOT) -> str:
    """输出相对 project root 的 POSIX 风格路径；无法相对化时保留绝对路径。"""

    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path) -> Path:
    """将 CLI 中的相对路径解析到 project root。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def write_llm_candidate_prompts_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def llm_messages_cache_key(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_llm_candidate_cache(path: Path) -> dict[str, dict[str, Any]]:
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


def append_llm_candidate_cache(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(item, ensure_ascii=False))
        file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument(
        "--nbest-jsonl",
        type=Path,
        default=None,
        help=(
            "sequence-level n-best JSONL；支持字段 nbest/alternatives/beams/hypotheses。"
            "若省略，则尝试复用输入 record 内已有 scope=sequence 候选。"
        ),
    )
    parser.add_argument("--default-source", default=DEFAULT_NBEST_SOURCE)
    parser.add_argument("--max-sequence-alternatives", type=int, default=5)
    parser.add_argument("--max-span-alternatives", type=int, default=3)
    parser.add_argument(
        "--include-unchanged-span-candidates",
        action="store_true",
        help="默认跳过与原 uncertain span 文本完全相同的 span 候选。",
    )
    parser.add_argument(
        "--disable-aux-medical-candidates",
        action="store_false",
        dest="enable_auxiliary_medical_candidates",
        help=(
            "Disable T039 medical lexicon/fuzzy fallback candidates. "
            "Fallback candidates are enabled by default and are only added "
            "when a medical entity span has no ASR-native span candidate."
        ),
    )
    parser.set_defaults(enable_auxiliary_medical_candidates=True)
    parser.add_argument(
        "--aux-medical-lexicon-json",
        type=Path,
        default=DEFAULT_AUX_LEXICON_JSON,
        help="Optional JSON lexicon for T039 auxiliary medical candidates.",
    )
    parser.add_argument(
        "--max-auxiliary-span-alternatives",
        type=int,
        default=None,
        help="Max T039 auxiliary candidates per span; defaults to --max-span-alternatives.",
    )
    parser.add_argument(
        "--aux-min-similarity",
        type=float,
        default=DEFAULT_AUX_MIN_SIMILARITY,
        help="Minimum fuzzy similarity for T039 auxiliary candidates.",
    )
    parser.add_argument(
        "--llm-candidate-prompts-jsonl",
        type=Path,
        default=DEFAULT_LLM_CANDIDATE_PROMPTS_JSONL,
        help="Prompt-ready JSONL for T044 yellow/red word LLM candidate generation.",
    )
    parser.add_argument(
        "--llm-candidate-cache-jsonl",
        type=Path,
        default=DEFAULT_LLM_CANDIDATE_CACHE_JSONL,
        help="T044 LLM 响应缓存；只保存 prompt 哈希、响应和调用元数据。",
    )
    parser.add_argument(
        "--run-llm-candidates",
        action="store_true",
        help="Actually call the OpenAI-compatible LLM API for T044 word candidates.",
    )
    parser.add_argument(
        "--max-llm-word-candidates",
        type=int,
        default=DEFAULT_LLM_WORD_CANDIDATES,
        help="Max T044 LLM candidates per yellow/red target word.",
    )
    parser.add_argument(
        "--llm-word-context-window",
        type=int,
        default=DEFAULT_LLM_WORD_CONTEXT_WINDOW,
        help="Number of words kept on each side of a target word for T044 prompts.",
    )
    parser.add_argument(
        "--max-llm-lexicon-terms",
        type=int,
        default=DEFAULT_LLM_WORD_LEXICON_TERMS,
        help="Max medical lexicon terms included in each T044 prompt.",
    )
    parser.add_argument(
        "--llm-candidate-prompt-profile",
        default=DEFAULT_LLM_CANDIDATE_PROMPT_PROFILE,
        help=(
            "候选提示词配置；中文远程程控数据使用 "
            "zh_dbs_remote_programming_v1。"
        ),
    )
    parser.add_argument(
        "--llm-candidate-context-scope",
        choices=["local_window", "complete_consultation"],
        default="local_window",
        help="LLM 候选仅看局部窗口，或同时接收完整病例 ASR 对话。",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Project .env for LLM candidate API config; ignored unless --run-llm-candidates.",
    )
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible base URL for T044 candidates; defaults to .env/env.",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="LLM model for T044 candidates; defaults to .env/env.",
    )
    parser.add_argument("--llm-timeout-sec", type=float, default=60.0)
    parser.add_argument("--llm-max-tokens", type=int, default=500)
    parser.add_argument("--llm-workers", type=int, default=1)
    parser.add_argument("--llm-max-retries", type=int, default=3)
    return parser.parse_args()


def run_extraction(args: argparse.Namespace) -> tuple[list[ASRConfidenceRecord], dict[str, Any]]:
    """执行 T029 候选追加。"""

    input_jsonl = resolve_project_path(args.input_jsonl)
    output_jsonl = resolve_project_path(args.output_jsonl)
    nbest_jsonl = resolve_project_path(args.nbest_jsonl) if args.nbest_jsonl else None
    llm_candidate_prompts_jsonl = (
        resolve_project_path(args.llm_candidate_prompts_jsonl)
        if args.llm_candidate_prompts_jsonl
        else None
    )
    llm_candidate_cache_jsonl = (
        resolve_project_path(args.llm_candidate_cache_jsonl)
        if args.llm_candidate_cache_jsonl
        else None
    )
    if args.llm_workers <= 0:
        raise ValueError("--llm-workers must be greater than 0")
    if args.llm_max_retries <= 0:
        raise ValueError("--llm-max-retries must be greater than 0")
    records = read_asr_confidence_jsonl(input_jsonl)
    conversation_contexts = (
        build_llm_conversation_contexts(records)
        if args.llm_candidate_context_scope == "complete_consultation"
        else {}
    )
    nbest_by_key = (
        load_nbest_jsonl(nbest_jsonl, default_source=args.default_source)
        if nbest_jsonl is not None
        else {}
    )
    aux_lexicon_json = (
        resolve_project_path(args.aux_medical_lexicon_json)
        if args.aux_medical_lexicon_json is not None
        else None
    )
    aux_medical_lexicon = None
    aux_lexicon_loaded = False
    if aux_lexicon_json is not None and aux_lexicon_json.exists():
        aux_medical_lexicon = load_medical_candidate_lexicon(aux_lexicon_json)
        aux_lexicon_loaded = True

    llm_prompt_records = [
        llm_prompt_to_json_record(prompt)
        for record in records
        for prompt in build_llm_word_candidate_prompt_records(
            record,
            medical_candidate_lexicon=aux_medical_lexicon,
            context_window_words=args.llm_word_context_window,
            max_lexicon_terms=args.max_llm_lexicon_terms,
            prompt_profile=args.llm_candidate_prompt_profile,
            conversation_context=conversation_contexts.get(record.sample_id),
        )
    ]
    if llm_candidate_prompts_jsonl is not None:
        write_llm_candidate_prompts_jsonl(llm_prompt_records, llm_candidate_prompts_jsonl)

    llm_word_candidate_generator = None
    llm_cache_hits = 0
    llm_api_requests = 0
    if args.run_llm_candidates:
        llm_env_file = resolve_project_path(args.env_file) if args.env_file else None
        llm_cache = (
            read_llm_candidate_cache(llm_candidate_cache_jsonl)
            if llm_candidate_cache_jsonl is not None
            else {}
        )
        llm_cache_lock = threading.Lock()

        def llm_word_candidate_generator(
            messages: list[dict[str, str]],
        ) -> tuple[str, dict[str, Any]]:
            nonlocal llm_api_requests, llm_cache_hits
            cache_key = llm_messages_cache_key(messages)
            with llm_cache_lock:
                cached = llm_cache.get(cache_key)
                if cached is not None:
                    llm_cache_hits += 1
                    return cached["content"], {
                        **dict(cached.get("metadata") or {}),
                        "cache_hit": True,
                    }

            last_error: Exception | None = None
            for attempt in range(1, args.llm_max_retries + 1):
                try:
                    content, metadata = generate_llm_word_candidate_content_with_api(
                        messages,
                        api_key_env=args.api_key_env,
                        base_url=args.llm_base_url,
                        model_name=args.llm_model,
                        dotenv_path=llm_env_file,
                        timeout_sec=args.llm_timeout_sec,
                        max_tokens=args.llm_max_tokens,
                    )
                    with llm_cache_lock:
                        llm_api_requests += 1
                        item = {
                            "cache_key": cache_key,
                            "content": content,
                            "metadata": metadata,
                        }
                        llm_cache[cache_key] = item
                        if llm_candidate_cache_jsonl is not None:
                            append_llm_candidate_cache(
                                llm_candidate_cache_jsonl,
                                item,
                            )
                    return content, {**metadata, "cache_hit": False}
                except (ValueError, RuntimeError) as exc:
                    last_error = exc
                    if attempt >= args.llm_max_retries:
                        raise
                    time.sleep(min(float(attempt), 2.0))
            raise RuntimeError("LLM candidate retries exhausted") from last_error

    records_with_nbest_input = sum(
        bool(nbest_items_for_record(record, nbest_by_key)) for record in records
    )

    def process_record(record: ASRConfidenceRecord) -> ASRConfidenceRecord:
        nbest_items = nbest_items_for_record(record, nbest_by_key)
        return attach_nbest_candidates_to_record(
            record,
            nbest_items,
            max_sequence_alternatives=args.max_sequence_alternatives,
            max_span_alternatives=args.max_span_alternatives,
            default_source=args.default_source,
            include_unchanged_span_candidates=args.include_unchanged_span_candidates,
            enable_auxiliary_medical_candidates=args.enable_auxiliary_medical_candidates,
            medical_candidate_lexicon=aux_medical_lexicon,
            max_auxiliary_span_alternatives=args.max_auxiliary_span_alternatives,
            aux_min_similarity=args.aux_min_similarity,
            enable_llm_word_candidates=args.run_llm_candidates,
            llm_word_candidate_generator=llm_word_candidate_generator,
            max_llm_word_candidates=args.max_llm_word_candidates,
            llm_word_context_window=args.llm_word_context_window,
            max_llm_lexicon_terms=args.max_llm_lexicon_terms,
            llm_candidate_prompt_profile=args.llm_candidate_prompt_profile,
            llm_conversation_context=conversation_contexts.get(record.sample_id),
        )

    if args.run_llm_candidates and args.llm_workers > 1:
        with ThreadPoolExecutor(max_workers=args.llm_workers) as executor:
            output_records = list(executor.map(process_record, records))
    else:
        output_records = [process_record(record) for record in records]

    write_asr_confidence_jsonl(output_records, output_jsonl)
    run_summary = build_run_summary(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        nbest_jsonl=nbest_jsonl,
        records=output_records,
        records_with_nbest_input=records_with_nbest_input,
        aux_lexicon_json=aux_lexicon_json,
        aux_lexicon_loaded=aux_lexicon_loaded,
        llm_candidate_prompts_jsonl=llm_candidate_prompts_jsonl,
        llm_candidate_cache_jsonl=llm_candidate_cache_jsonl,
        llm_prompt_record_count=len(llm_prompt_records),
        llm_cache_hits=llm_cache_hits,
        llm_api_requests=llm_api_requests,
        args=args,
    )
    return output_records, run_summary


def build_run_summary(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    nbest_jsonl: Path | None,
    records: list[ASRConfidenceRecord],
    records_with_nbest_input: int,
    aux_lexicon_json: Path | None,
    aux_lexicon_loaded: bool,
    llm_candidate_prompts_jsonl: Path | None,
    llm_candidate_cache_jsonl: Path | None,
    llm_prompt_record_count: int,
    llm_cache_hits: int,
    llm_api_requests: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """构造 T029 运行摘要。"""

    sequence_alternative_count = sum(
        1
        for record in records
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    )
    span_alternatives = [
        alternative
        for record in records
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.SPAN
    ]
    span_alternative_count = len(span_alternatives)
    span_alternative_count_by_source = Counter(
        alternative.source for alternative in span_alternatives
    )
    word_alternatives = [
        alternative
        for record in records
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.WORD
    ]
    word_alternative_count = len(word_alternatives)
    word_alternative_count_by_source = Counter(
        alternative.source for alternative in word_alternatives
    )
    spans_with_alternatives_by_source: Counter[str] = Counter()
    for record in records:
        for span in record.uncertain_spans:
            span_sources = {
                alternative.source
                for alternative in record.alternatives_for_span(span.span_id)
            }
            for source in span_sources:
                spans_with_alternatives_by_source[source] += 1
    spans_with_alternatives = sum(
        1
        for record in records
        for span in record.uncertain_spans
        if span.alternative_ids
    )
    total_uncertain_spans = sum(len(record.uncertain_spans) for record in records)
    records_with_sequence_alternatives = sum(
        any(
            alternative.scope == AlternativeScope.SEQUENCE
            for alternative in record.asr_alternatives
        )
        for record in records
    )
    records_with_span_alternatives = sum(
        any(alternative.scope == AlternativeScope.SPAN for alternative in record.asr_alternatives)
        for record in records
    )
    records_with_word_alternatives = sum(
        any(alternative.scope == AlternativeScope.WORD for alternative in record.asr_alternatives)
        for record in records
    )

    return {
        "task_id": "T029",
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_confidence_jsonl": path_for_record(input_jsonl),
            "nbest_jsonl": path_for_record(nbest_jsonl) if nbest_jsonl else None,
            "records_read": len(records),
            "records_with_external_nbest_input": records_with_nbest_input,
        },
        "outputs": {
            "asr_confidence_with_candidates_jsonl": path_for_record(output_jsonl),
            "llm_word_candidate_prompts_jsonl": (
                path_for_record(llm_candidate_prompts_jsonl)
                if llm_candidate_prompts_jsonl
                else None
            ),
            "llm_word_candidate_cache_jsonl": (
                path_for_record(llm_candidate_cache_jsonl)
                if llm_candidate_cache_jsonl
                else None
            ),
        },
        "parameters": {
            "default_source": args.default_source,
            "max_sequence_alternatives": args.max_sequence_alternatives,
            "max_span_alternatives": args.max_span_alternatives,
            "include_unchanged_span_candidates": args.include_unchanged_span_candidates,
            "sequence_alignment_method": SEQUENCE_ALIGNMENT_METHOD,
            "span_alignment_method": SPAN_ALIGNMENT_METHOD,
            "enable_auxiliary_medical_candidates": (
                args.enable_auxiliary_medical_candidates
            ),
            "auxiliary_candidate_source": MEDICAL_LEXICON_AUX_SOURCE,
            "aux_medical_lexicon_json": (
                path_for_record(aux_lexicon_json) if aux_lexicon_json else None
            ),
            "aux_medical_lexicon_loaded": aux_lexicon_loaded,
            "max_auxiliary_span_alternatives": args.max_auxiliary_span_alternatives,
            "aux_min_similarity": args.aux_min_similarity,
            "llm_word_candidate_source": LLM_WORD_AUX_SOURCE,
            "run_llm_candidates": args.run_llm_candidates,
            "max_llm_word_candidates": args.max_llm_word_candidates,
            "llm_word_context_window": args.llm_word_context_window,
            "max_llm_lexicon_terms": args.max_llm_lexicon_terms,
            "llm_candidate_prompt_profile": args.llm_candidate_prompt_profile,
            "llm_candidate_context_scope": args.llm_candidate_context_scope,
            "llm_timeout_sec": args.llm_timeout_sec,
            "llm_max_tokens": args.llm_max_tokens,
            "llm_workers": args.llm_workers,
            "llm_max_retries": args.llm_max_retries,
        },
        "validation": {
            "sequence_alternatives": sequence_alternative_count,
            "span_alternatives": span_alternative_count,
            "span_alternatives_by_source": dict(span_alternative_count_by_source),
            "word_alternatives": word_alternative_count,
            "word_alternatives_by_source": dict(word_alternative_count_by_source),
            "llm_word_candidate_prompt_records": llm_prompt_record_count,
            "llm_candidate_cache_hits": llm_cache_hits,
            "llm_candidate_api_requests": llm_api_requests,
            "total_uncertain_spans": total_uncertain_spans,
            "spans_with_alternatives": spans_with_alternatives,
            "spans_with_alternatives_by_source": dict(
                spans_with_alternatives_by_source
            ),
            "records_with_sequence_alternatives": records_with_sequence_alternatives,
            "records_with_span_alternatives": records_with_span_alternatives,
            "records_with_word_alternatives": records_with_word_alternatives,
            "no_inline_reference_text": all(
                not record.reference_text_included for record in records
            ),
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
        output_records, run_summary = run_extraction(args)
        write_run_config(run_summary, run_config_path)
        print("T029 ASR n-best/top-k 候选抽取完成。")
        print(f"- records: {len(output_records)}")
        print(f"- output_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T029",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T029 ASR n-best/top-k 候选抽取失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
