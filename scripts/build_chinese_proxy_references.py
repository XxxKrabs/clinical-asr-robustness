"""用多路自动转录和强 LLM 构造中文 pilot 的保守代理参考。

该产物只用于没有人工 reference 时的探索性鲁棒性评估。它不是人工 clean transcript、
不是医生 confirmed transcript，也不能支持正式临床质量结论。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinical_asr_robustness.asr_nbest_candidates import (
    generate_llm_word_candidate_content_with_api,
)
from clinical_asr_robustness.medical_entity_review import (
    DEFAULT_API_KEY_ENV,
    parse_json_object,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_JSONL = Path(
    "data/interim/remote_programming_40/manifests/remote_programming_40_snapshot_files.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/processed/remote_programming_40/t058_proxy_reference")
DEFAULT_CASE_IDS = ("case_0068", "case_0057", "case_0040", "case_0008", "case_0021")
SOURCE_SPECS = (
    ("recommended_speaker_source", "04_推荐的说话人与信息来源转录.txt"),
    ("qwen3_asr_medical_prior", "02_有医疗先验/Qwen3-ASR.txt"),
    ("paraformer_medical_prior", "02_有医疗先验/Paraformer中文.txt"),
)


class ProxyKeyFact(BaseModel):
    """代理参考中用于病例信息保持率的短事实。"""

    model_config = ConfigDict(extra="forbid")

    category: str
    text: str
    polarity: str = "present"
    criticality: str = "routine"
    evidence_terms: list[str] = Field(default_factory=list)


class ProxyReferencePayload(BaseModel):
    """LLM 必须返回的最小代理参考结构。"""

    model_config = ConfigDict(extra="forbid")

    clean_transcript: str = Field(min_length=1)
    key_facts: list[ProxyKeyFact] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-jsonl", type=Path, default=DEFAULT_SNAPSHOT_JSONL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case-id", action="append", dest="case_ids", default=None)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=20_000)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--run-llm", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def source_paths_by_case(
    snapshot_rows: list[dict[str, Any]],
    *,
    case_ids: list[str],
) -> dict[str, list[tuple[str, Path]]]:
    result: dict[str, list[tuple[str, Path]]] = {}
    for case_id in case_ids:
        case_rows = [
            row
            for row in snapshot_rows
            if row.get("asset_group") == "raw_review_package"
            and row.get("case_id") == case_id
            and row.get("extension") == ".txt"
        ]
        selected: list[tuple[str, Path]] = []
        for source_name, suffix in SOURCE_SPECS:
            matches = [
                resolve_project_path(Path(str(row["relative_path"])))
                for row in case_rows
                if str(row.get("relative_path") or "").replace("\\", "/").endswith(suffix)
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"{case_id} 的 {source_name} 应恰好匹配 1 个文件，实际 {len(matches)}"
                )
            selected.append((source_name, matches[0]))
        result[case_id] = selected
    return result


def build_messages(case_id: str, sources: list[dict[str, str]]) -> list[dict[str, str]]:
    source_blocks = []
    for index, source in enumerate(sources, start=1):
        source_blocks.append(
            f"===== 自动转录来源 {index}: {source['source_name']} =====\n{source['text']}"
        )
    system = (
        "你是中文临床 ASR 转录校对研究员。给你的全部文本都是同一段远程神经调控对话的"
        "自动转录，可能有错字、漏字、重复、幻觉、时间标签和说话人误判。请融合多路证据，"
        "生成保守的代理参考转录。不得添加任何来源中没有的医学事实、药名、数值、侧别、"
        "否定或诊疗建议；证据冲突且无法判断时保留最可信原文或写[听不清]。"
        "不要把结果称为人工转录或医生确认。只返回严格 JSON，不要输出 Markdown。"
    )
    user = (
        f"匿名病例：{case_id}\n"
        "请完成以下研究任务：\n"
        "1. clean_transcript：保留完整对话信息，删除纯时间戳和明显系统噪声；可保留匿名"
        "speaker 标签，但不要猜 doctor/patient 角色。\n"
        "2. key_facts：只抽取转录中明确出现的短事实。category 只能优先使用 symptom、"
        "negation、medication、device、parameter、laterality、plan、history、other；"
        "criticality 使用 routine/important/safety_critical；evidence_terms 给出 1–4 个"
        "应在转录中能直接找到的短词或数值单位，供后续文本保持率评估。\n"
        "3. uncertainty_notes：只写简短的不确定类型，不复制长段原文。\n"
        "输出结构："
        '{"clean_transcript":"...","key_facts":[{"category":"symptom",'
        '"text":"...","polarity":"present","criticality":"important",'
        '"evidence_terms":["..."]}],"uncertainty_notes":["..."]}\n\n' + "\n\n".join(source_blocks)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_proxy_payload(content: str) -> ProxyReferencePayload:
    payload = parse_json_object(content)
    return ProxyReferencePayload.model_validate(payload)


def generate_proxy(
    *,
    case_id: str,
    messages: list[dict[str, str]],
    args: argparse.Namespace,
    env_file: Path,
) -> tuple[ProxyReferencePayload, dict[str, Any], str]:
    last_error: Exception | None = None
    active_messages = list(messages)
    for attempt in range(1, args.max_retries + 1):
        try:
            content, metadata = generate_llm_word_candidate_content_with_api(
                active_messages,
                api_key_env=args.api_key_env,
                base_url=args.llm_base_url,
                model_name=args.llm_model,
                dotenv_path=env_file,
                timeout_sec=args.timeout_sec,
                max_tokens=args.max_tokens,
            )
            return parse_proxy_payload(content), metadata, content
        except (RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt >= args.max_retries:
                break
            active_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过 JSON/字段校验。请保留完整 clean_transcript，"
                        "重新输出严格 JSON；不要输出解释或 Markdown。"
                    ),
                },
            ]
            time.sleep(min(float(attempt), 2.0))
    raise RuntimeError(f"{case_id} 代理参考生成失败") from last_error


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_retries <= 0:
        raise ValueError("--max-retries 必须大于 0")
    case_ids = list(dict.fromkeys(args.case_ids or DEFAULT_CASE_IDS))
    snapshot_path = resolve_project_path(args.snapshot_jsonl)
    output_dir = resolve_project_path(args.output_dir)
    env_file = resolve_project_path(args.env_file)
    references_path = output_dir / "proxy_references.jsonl"
    prompts_path = output_dir / "proxy_reference_prompts.jsonl"
    responses_path = output_dir / "proxy_reference_responses.jsonl"
    summary_path = output_dir / "proxy_reference_run.json"
    reference_text_dir = output_dir / "reference_text"

    existing = (
        {str(row.get("consultation_id")): row for row in read_jsonl(references_path)}
        if references_path.exists() and not args.overwrite
        else {}
    )
    sources_by_case = source_paths_by_case(
        read_jsonl(snapshot_path),
        case_ids=case_ids,
    )
    records = dict(existing)
    prompt_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []
    api_request_count = 0
    for case_id in case_ids:
        if case_id in records and not args.overwrite:
            continue
        sources: list[dict[str, str]] = []
        source_metadata: list[dict[str, Any]] = []
        for source_name, path in sources_by_case[case_id]:
            text = path.read_text(encoding="utf-8-sig")
            sources.append({"source_name": source_name, "text": text})
            source_metadata.append(
                {
                    "source_name": source_name,
                    "path": project_relative(path),
                    "char_count": len(text),
                    "sha256": sha256_text(text),
                    "automatic_transcript": True,
                }
            )
        messages = build_messages(case_id, sources)
        prompt_rows.append(
            {
                "consultation_id": case_id,
                "messages": messages,
                "contains_protected_transcript_text": True,
            }
        )
        if not args.run_llm:
            continue
        proxy, model_metadata, raw_response = generate_proxy(
            case_id=case_id,
            messages=messages,
            args=args,
            env_file=env_file,
        )
        api_request_count += 1
        reference_text_dir.mkdir(parents=True, exist_ok=True)
        text_path = reference_text_dir / f"{case_id}.txt"
        text_path.write_text(proxy.clean_transcript.strip() + "\n", encoding="utf-8")
        record = {
            "schema_version": "proxy_reference/v1",
            "dataset": "remote_programming_40",
            "consultation_id": case_id,
            "reference_type": "llm_multi_asr_consensus_proxy",
            "reference_transcript_path": project_relative(text_path),
            "clean_transcript": proxy.clean_transcript,
            "key_facts": [fact.model_dump(mode="json") for fact in proxy.key_facts],
            "uncertainty_notes": proxy.uncertainty_notes,
            "sources": source_metadata,
            "model": model_metadata,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "audio_used": False,
            "human_transcriber_used": False,
            "doctor_confirmed": False,
            "is_gold": False,
            "formal_quality_claim_allowed": False,
            "research_use_only": True,
        }
        records[case_id] = record
        response_rows.append(
            {
                "consultation_id": case_id,
                "raw_response": raw_response,
                "model": model_metadata,
                "contains_protected_transcript_text": True,
            }
        )
        write_jsonl(references_path, [records[key] for key in sorted(records)])
        write_jsonl(responses_path, response_rows)

    write_jsonl(prompts_path, prompt_rows)
    completed = [case_id for case_id in case_ids if case_id in records]
    summary = {
        "task_id": "T063_PROXY_PILOT",
        "status": "completed" if len(completed) == len(case_ids) else "prompts_only",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested_case_count": len(case_ids),
        "completed_case_count": len(completed),
        "case_ids": case_ids,
        "api_request_count": api_request_count,
        "reference_type": "llm_multi_asr_consensus_proxy",
        "source_count_per_case": len(SOURCE_SPECS),
        "audio_used": False,
        "human_transcriber_used": False,
        "doctor_confirmed": False,
        "is_gold": False,
        "formal_quality_claim_allowed": False,
        "limitations": [
            "代理参考来自多路自动转录和 LLM 保守融合，可能继承共同错误。",
            "未回听原音频，不能替代人工 clean/reference。",
            "所有质量数字必须标注 proxy-reference exploratory evaluation。",
        ],
        "outputs": {
            "references_jsonl": project_relative(references_path),
            "reference_text_dir": project_relative(reference_text_dir),
            "prompts_jsonl": project_relative(prompts_path),
            "responses_jsonl": project_relative(responses_path),
        },
    }
    write_json(summary_path, summary)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
