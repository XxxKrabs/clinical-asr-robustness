"""T038：用 LLM 医学实体抽取限定 ASR 审阅/候选范围。

默认流程：

1. 读取 T028 ASR confidence JSONL；
2. 对每条 ASR transcript 调用 OpenAI-compatible LLM API 抽取医学实体；
3. 只保留医学实体中低/中/未知置信度片段为 `uncertain_spans`；
4. 给医学实体词写入显示 metadata，使 T030/T036 中只有医学词显示绿/黄/红，
   非医学词显示普通黑字；
5. 写出新的 ASR confidence JSONL，供 T029 继续生成 span candidates。

API key 默认从项目根目录 `.env` 读取，也兼容环境变量；不要把真实 `.env`
或密钥提交到 Git 仓库。
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.medical_entity_review import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_PARATERA_BASE_URL,
    DEFAULT_PARATERA_MODEL,
    MEDICAL_ENTITY_REVIEW_METADATA_KEY,
    T038_GENERATED_BY,
    apply_medical_entity_review_gating,
    build_medical_entity_extraction_record,
    extract_medical_entities_with_llm,
    extraction_for_asr_record,
    extraction_records_by_key,
    read_medical_entity_extractions_jsonl,
    resolve_llm_api_config,
    write_medical_entity_extractions_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_JSONL = (
    PROJECT_ROOT
    / "outputs/primock57/t028_nemo_asr_confidence/primock57_asr_confidence_limit2.jsonl"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t038_medical_entity_review"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_asr_confidence_medical_entities.jsonl"
DEFAULT_ENTITY_CACHE_JSONL = DEFAULT_OUTPUT_DIR / "primock57_medical_entities_llm.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t038_medical_entity_review_run.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


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
        "--entity-cache-jsonl",
        type=Path,
        default=DEFAULT_ENTITY_CACHE_JSONL,
        help="医学实体抽取缓存 JSONL；存在时默认复用，缺失记录才调用 LLM。",
    )
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=(
            "项目级 .env 文件，默认读取 project/.env；支持 API_KEY/BASE_URL/API_URL/"
            "MODEL_ID 或 PARATERA_* 命名。传空字符串可禁用。"
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"LLM base URL；默认从 .env 读取，缺省为 {DEFAULT_PARATERA_BASE_URL}",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"LLM model；默认从 .env 读取，缺省为 {DEFAULT_PARATERA_MODEL}",
    )
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument(
        "--max-llm-retries",
        type=int,
        default=3,
        help="单条实体抽取遇到响应格式或瞬时请求错误时的最大尝试次数。",
    )
    parser.add_argument(
        "--llm-workers",
        type=int,
        default=1,
        help="并发 LLM 请求数；默认 1，建议全量任务使用 4。",
    )
    parser.add_argument(
        "--force-refresh-entities",
        action="store_true",
        help="忽略已有实体缓存，重新调用 LLM。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 条 ASR record，便于 smoke test。",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> tuple[list[ASRConfidenceRecord], dict[str, Any]]:
    input_jsonl = resolve_project_path(args.input_jsonl)
    output_jsonl = resolve_project_path(args.output_jsonl)
    entity_cache_jsonl = resolve_project_path(args.entity_cache_jsonl)
    env_file = resolve_optional_env_file(args.env_file)

    records = read_asr_confidence_jsonl(input_jsonl)
    if args.max_llm_retries <= 0:
        raise ValueError("--max-llm-retries 必须大于 0")
    if args.llm_workers <= 0:
        raise ValueError("--llm-workers 必须大于 0")
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit 必须大于 0")
        records = records[: args.limit]

    cached_extractions = (
        read_medical_entity_extractions_jsonl(entity_cache_jsonl)
        if entity_cache_jsonl.exists() and not args.force_refresh_entities
        else []
    )
    cached_by_key = extraction_records_by_key(cached_extractions)

    output_records: list[ASRConfidenceRecord] = []
    extraction_records = []
    cache_hits = sum(
        extraction_for_asr_record(record, cached_by_key) is not None
        for record in records
    )
    llm_calls = 0
    resolved_base_url = args.base_url
    resolved_model = args.model

    missing_records = [
        record
        for record in records
        if extraction_for_asr_record(record, cached_by_key) is None
    ]
    new_extractions = []
    if missing_records:
        llm_config = resolve_llm_api_config(
            api_key_env=args.api_key_env,
            dotenv_path=env_file,
            base_url=args.base_url,
            model_name=args.model,
        )
        resolved_base_url = llm_config.base_url
        resolved_model = llm_config.model_name

        def extract_one(record: ASRConfidenceRecord) -> Any:
            last_error: Exception | None = None
            for attempt in range(1, args.max_llm_retries + 1):
                try:
                    entities = extract_medical_entities_with_llm(
                        record.asr_transcript,
                        api_key=llm_config.api_key,
                        base_url=llm_config.base_url,
                        model_name=llm_config.model_name,
                        timeout_sec=args.timeout_sec,
                    )
                    break
                except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt >= args.max_llm_retries:
                        raise
                    time.sleep(min(float(attempt), 2.0))
            else:  # pragma: no cover - 循环要么 break，要么在最后一次抛出
                raise RuntimeError("LLM 医学实体抽取重试结束但未返回结果") from last_error
            return build_medical_entity_extraction_record(
                record,
                entities=entities,
                model_name=llm_config.model_name,
                base_url=llm_config.base_url,
                metadata={"generated_by": T038_GENERATED_BY},
            )

        first_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=args.llm_workers) as executor:
            futures = [executor.submit(extract_one, record) for record in missing_records]
            for future in as_completed(futures):
                try:
                    new_extractions.append(future.result())
                    llm_calls += 1
                    # 外部 API 全量任务逐条落盘，复跑时只处理尚未缓存的 record。
                    write_medical_entity_extractions_jsonl(
                        [*cached_extractions, *new_extractions],
                        entity_cache_jsonl,
                    )
                except Exception as exc:  # noqa: BLE001 - 完成其余 future 后统一抛出
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    cached_by_key = extraction_records_by_key(
        [*cached_extractions, *new_extractions]
    )
    for record in records:
        extraction = extraction_for_asr_record(record, cached_by_key)
        if extraction is None:  # pragma: no cover - 缺失记录应已在上面生成
            raise RuntimeError(f"医学实体缓存缺少 record：{record.sample_id}")
        extraction_records.append(extraction)
        output_records.append(
            apply_medical_entity_review_gating(
                record,
                extraction.entities,
                generated_by=T038_GENERATED_BY,
            )
        )

    # 全缓存复跑时没有新 API 配置可回填；运行记录应沿用缓存中实际使用的
    # 模型和服务地址，不能误写为代码默认值。
    if resolved_model is None:
        resolved_model = next(
            (item.model_name for item in extraction_records if item.model_name),
            None,
        )
    if resolved_base_url is None:
        resolved_base_url = next(
            (item.base_url for item in extraction_records if item.base_url),
            None,
        )

    write_medical_entity_extractions_jsonl(extraction_records, entity_cache_jsonl)
    write_asr_confidence_jsonl(output_records, output_jsonl)
    summary = build_run_summary(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        entity_cache_jsonl=entity_cache_jsonl,
        records=output_records,
        extraction_records=extraction_records,
        cache_hits=cache_hits,
        llm_calls=llm_calls,
        env_file=env_file,
        resolved_base_url=resolved_base_url,
        resolved_model=resolved_model,
        args=args,
    )
    return output_records, summary


def resolve_optional_env_file(path_value: str | Path | None) -> Path | None:
    if path_value is None:
        return None
    if str(path_value).strip() == "":
        return None
    return resolve_project_path(path_value)


def build_run_summary(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    entity_cache_jsonl: Path,
    records: list[ASRConfidenceRecord],
    extraction_records: list[Any],
    cache_hits: int,
    llm_calls: int,
    env_file: Path | None,
    resolved_base_url: str | None,
    resolved_model: str | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    span_levels = Counter(
        span.confidence_level.value
        for record in records
        for span in record.uncertain_spans
    )
    matched_entities = sum(
        int(
            record.metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY, {}).get(
                "matched_entity_count",
                0,
            )
        )
        for record in records
    )
    review_spans = sum(len(record.uncertain_spans) for record in records)
    medical_words = sum(
        1
        for record in records
        for word in record.asr_words
        if word.metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY, {}).get(
            "is_medical_entity"
        )
    )
    return {
        "task_id": "T038",
        "status": "ok",
        "generated_by": T038_GENERATED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "asr_confidence_jsonl": path_for_record(input_jsonl),
            "records_read": len(records),
        },
        "outputs": {
            "medical_entity_asr_confidence_jsonl": path_for_record(output_jsonl),
            "medical_entity_cache_jsonl": path_for_record(entity_cache_jsonl),
        },
        "parameters": {
            "env_file": path_for_record(env_file),
            "base_url": resolved_base_url or args.base_url or DEFAULT_PARATERA_BASE_URL,
            "model": resolved_model or args.model or DEFAULT_PARATERA_MODEL,
            "api_key_env": args.api_key_env,
            "timeout_sec": args.timeout_sec,
            "max_llm_retries": args.max_llm_retries,
            "llm_workers": args.llm_workers,
            "force_refresh_entities": args.force_refresh_entities,
            "limit": args.limit,
        },
        "validation": {
            "entity_extraction_records": len(extraction_records),
            "cache_hits": cache_hits,
            "llm_calls": llm_calls,
            "input_entity_mentions": sum(
                len(record.entities) for record in extraction_records
            ),
            "matched_entity_mentions": matched_entities,
            "medical_words_colored": medical_words,
            "medical_entity_review_spans": review_spans,
            "span_confidence_levels": dict(span_levels),
            "non_medical_words_display": "neutral_black",
            "no_inline_reference_text": all(
                not record.reference_text_included for record in records
            ),
            "research_use_only": all(record.research_use_only for record in records),
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
        output_records, summary = run(args)
        write_run_config(summary, run_config_path)
        print("T038 医学实体优先 ASR 审阅范围生成完成。")
        print(f"- records: {len(output_records)}")
        print(f"- output_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- entity_cache_jsonl: {resolve_project_path(args.entity_cache_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T038",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T038 医学实体优先 ASR 审阅范围生成失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
