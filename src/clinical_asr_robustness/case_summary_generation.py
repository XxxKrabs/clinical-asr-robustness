"""T041：从 ASR noisy transcript 生成病例摘要的下游任务。

本模块把当前 ASR confidence JSONL 输出接到一个可复现的病例摘要生成任务：

- 默认按 consultation_id 合并 doctor/patient 分声道 ASR transcript；
- 生成结构化病例摘要 prompt；
- 默认 dry-run，仅导出 prompt-ready JSONL，不访问外部模型；
- 可选调用 OpenAI-compatible Chat Completions API 生成病例摘要；
- 聚合 summary 不写入完整 transcript/prompt 正文。

所有生成结果仅用于研究评估，不构成临床建议。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness.asr_confidence import (
    CLINICAL_USE_WARNING,
    ASRConfidenceRecord,
    read_asr_confidence_jsonl,
)
from clinical_asr_robustness.asr_quality_evaluation import (
    path_for_record,
    read_reference_transcript,
    resolve_project_path,
)
from clinical_asr_robustness.confirmed_downstream_evaluation import (
    build_confirmed_index,
    find_confirmed_for_asr_record,
    read_confirmed_transcripts_jsonl,
)
from clinical_asr_robustness.medical_entity_review import (
    DEFAULT_API_KEY_ENV,
    endpoint_for_chat_completions,
    parse_json_object,
    resolve_llm_api_config,
)

CASE_SUMMARY_GENERATION_RECORD_SCHEMA_VERSION = "case_summary_generation_record/v1"
CASE_SUMMARY_GENERATION_SUMMARY_SCHEMA_VERSION = "case_summary_generation_summary/v1"
CASE_SUMMARY_TASK_ID = "T041"
CASE_SUMMARY_PROMPT_VERSION = (
    "case_summary_prompt/v3_input_variant_role_field_weighting"
)

INPUT_VARIANT_NOISY_ASR = "noisy_asr"
INPUT_VARIANT_RAW_ASR_ALIAS = "raw_asr"
INPUT_VARIANT_CONFIRMED_TRANSCRIPT = "confirmed_transcript"
INPUT_VARIANT_REFERENCE_ORACLE = "reference_oracle"
SUPPORTED_INPUT_VARIANTS = (
    INPUT_VARIANT_NOISY_ASR,
    INPUT_VARIANT_RAW_ASR_ALIAS,
    INPUT_VARIANT_CONFIRMED_TRANSCRIPT,
    INPUT_VARIANT_REFERENCE_ORACLE,
)
INPUT_UNIT_CONSULTATION = "consultation"
INPUT_UNIT_RECORD = "record"

STATUS_PROMPT_READY = "prompt_ready"
STATUS_GENERATED = "generated"

DEFAULT_SUMMARY_LANGUAGE = "zh"

EVIDENCE_WEIGHTING_ROLE_BLIND = "role_blind"
EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1 = "field_conditioned_v1"
SUPPORTED_EVIDENCE_WEIGHTING_PROFILES = (
    EVIDENCE_WEIGHTING_ROLE_BLIND,
    EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1,
)
DEFAULT_EVIDENCE_WEIGHTING_PROFILE = EVIDENCE_WEIGHTING_FIELD_CONDITIONED_V1

# 这些数值是摘要证据选择的相对优先级，不是事实真实性概率。
# 其目的在于让模型按字段区分医生与患者话语的用途，避免全局放大医生发言。
FIELD_CONDITIONED_ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "chief_complaint": {"doctor": 0.9, "patient": 1.2},
    "history_of_present_illness": {"doctor": 0.9, "patient": 1.2},
    "symptoms": {"doctor": 0.9, "patient": 1.2},
    "negated_or_absent_symptoms": {"doctor": 0.9, "patient": 1.2},
    "relevant_history": {"doctor": 1.0, "patient": 1.2},
    "medications": {"doctor": 1.2, "patient": 1.0},
    "tests_or_exam_mentioned": {"doctor": 1.3, "patient": 0.9},
    "assessment_mentioned": {"doctor": 1.5, "patient": 0.8},
    "plan_mentioned": {"doctor": 1.5, "patient": 0.8},
}


class CaseSummary(BaseModel):
    """病例摘要生成模型应返回的结构化结果。"""

    model_config = ConfigDict(extra="allow")

    summary_text: str | None = None
    chief_complaint: str | None = None
    history_of_present_illness: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    negated_or_absent_symptoms: list[str] = Field(default_factory=list)
    relevant_history: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    tests_or_exam_mentioned: list[str] = Field(default_factory=list)
    assessment_mentioned: str | None = None
    plan_mentioned: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        """兼容模型返回的轻微字段变体。"""

        if not isinstance(value, dict):
            return value
        aliases = {
            "summary": "summary_text",
            "brief_summary": "summary_text",
            "cc": "chief_complaint",
            "hpi": "history_of_present_illness",
            "negatives": "negated_or_absent_symptoms",
            "past_history": "relevant_history",
            "medication": "medications",
            "exam_or_tests": "tests_or_exam_mentioned",
            "assessment": "assessment_mentioned",
            "plan": "plan_mentioned",
            "uncertainties": "uncertainty_notes",
        }
        normalized = dict(value)
        for source, target in aliases.items():
            if source in normalized and target not in normalized:
                normalized[target] = normalized[source]
        for key in (
            "symptoms",
            "negated_or_absent_symptoms",
            "relevant_history",
            "medications",
            "tests_or_exam_mentioned",
            "plan_mentioned",
            "uncertainty_notes",
        ):
            if key in normalized:
                normalized[key] = _coerce_string_list(normalized[key])
        return normalized


@dataclass(frozen=True)
class CaseSummaryInputBundle:
    """一个病例摘要输入单元，可对应单条 record 或一次 consultation。"""

    bundle_id: str
    dataset: str
    split: str | None
    consultation_id: str | None
    input_unit: str
    input_variant: str
    source_records: tuple[ASRConfidenceRecord, ...]
    input_transcript: str

    @property
    def source_record_ids(self) -> list[str | None]:
        return [record.record_id for record in self.source_records]

    @property
    def source_sample_ids(self) -> list[str]:
        return [record.sample_id for record in self.source_records]

    @property
    def source_channels(self) -> list[str]:
        return [record.source_channel.value for record in self.source_records]


LLMContentGenerator = Callable[[list[dict[str, str]]], str]
TranscriptGetter = Callable[[ASRConfidenceRecord], str]


def build_case_summary_input_bundles(
    records: Iterable[ASRConfidenceRecord],
    *,
    group_by: str = INPUT_UNIT_CONSULTATION,
    input_variant: str = INPUT_VARIANT_NOISY_ASR,
    transcript_getter: TranscriptGetter | None = None,
) -> list[CaseSummaryInputBundle]:
    """把 ASR records 转为病例摘要输入单元。"""

    normalized_variant = normalize_input_variant(input_variant)
    record_list = list(records)
    if group_by == INPUT_UNIT_RECORD:
        return [
            _bundle_from_records(
                [record],
                input_unit=INPUT_UNIT_RECORD,
                input_variant=normalized_variant,
                transcript_getter=transcript_getter,
            )
            for record in record_list
        ]
    if group_by != INPUT_UNIT_CONSULTATION:
        raise ValueError(f"未知 group_by：{group_by}")

    groups: dict[tuple[str, str | None, str], list[ASRConfidenceRecord]] = defaultdict(list)
    for record in record_list:
        consultation_key = record.consultation_id or record.sample_id
        groups[(record.dataset, record.split, consultation_key)].append(record)

    bundles = [
        _bundle_from_records(
            group_records,
            input_unit=INPUT_UNIT_CONSULTATION,
            input_variant=normalized_variant,
            transcript_getter=transcript_getter,
        )
        for group_records in groups.values()
    ]
    return sorted(bundles, key=lambda item: item.bundle_id)


def build_case_summary_messages(
    bundle: CaseSummaryInputBundle,
    *,
    summary_language: str = DEFAULT_SUMMARY_LANGUAGE,
    evidence_weighting_profile: str = DEFAULT_EVIDENCE_WEIGHTING_PROFILE,
) -> list[dict[str, str]]:
    """为病例摘要下游任务构造 Chat Completions messages。"""

    variant_context = input_variant_prompt_context(bundle.input_variant)
    normalized_weighting_profile = normalize_evidence_weighting_profile(
        evidence_weighting_profile
    )
    weighting_instruction = build_evidence_weighting_instruction(
        normalized_weighting_profile,
        summary_language=summary_language,
    )
    language_instruction = (
        "请用中文输出病例摘要。"
        if summary_language == "zh"
        else "Write the case summary in English."
    )
    system_prompt = (
        "你是临床对话信息整理助手，任务是把临床对话 transcript 整理成病例摘要。"
        "这些内容只用于研究评估，不构成临床建议。"
        "你必须严格基于输入文本，不要新增事实、不要给出新的诊疗建议。"
        f"{variant_context['uncertainty_instruction']}"
        "只返回 JSON，不要输出 Markdown。"
    )
    user_prompt = (
        f"{language_instruction}\n\n"
        f"请从下面的 {variant_context['source_label']} 生成结构化病例摘要。"
        "如果某个字段无法从文本判断，请填 null 或空数组。"
        "plan_mentioned 只能记录原文中已经提到的建议/计划，不能自行补充。"
        f"\n\n{weighting_instruction}\n\n"
        "输出 JSON 格式如下：\n"
        "{\n"
        '  "case_summary": {\n'
        '    "summary_text": "一段简短病例摘要或 null",\n'
        '    "chief_complaint": "主诉或 null",\n'
        '    "history_of_present_illness": "现病史摘要或 null",\n'
        '    "symptoms": ["阳性症状"],\n'
        '    "negated_or_absent_symptoms": ["否认或未见症状"],\n'
        '    "relevant_history": ["相关既往史/社会史/生活影响"],\n'
        '    "medications": ["药物或治疗"],\n'
        '    "tests_or_exam_mentioned": ["检查或体格检查信息"],\n'
        '    "assessment_mentioned": "原文中提到的判断/诊断倾向或 null",\n'
        '    "plan_mentioned": ["原文提到的处理/随访计划"],\n'
        '    "uncertainty_notes": ["输入噪声、未解决审阅项或信息不确定说明"]\n'
        "  }\n"
        "}\n\n"
        f"metadata:\n"
        f"- bundle_id: {bundle.bundle_id}\n"
        f"- dataset: {bundle.dataset}\n"
        f"- consultation_id: {bundle.consultation_id or 'NA'}\n"
        f"- input_variant: {bundle.input_variant}\n"
        f"- prompt_version: {CASE_SUMMARY_PROMPT_VERSION}\n"
        f"- evidence_weighting_profile: {normalized_weighting_profile}\n"
        f"- source_channels: {', '.join(bundle.source_channels)}\n\n"
        f"{variant_context['transcript_heading']}:\n"
        f"{bundle.input_transcript}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def coerce_case_summary_payload(payload: Any) -> CaseSummary:
    """把 LLM JSON 输出规整为 CaseSummary。"""

    if isinstance(payload, dict) and "case_summary" in payload:
        payload = payload["case_summary"]
    if not isinstance(payload, dict):
        raise ValueError("病例摘要 LLM 输出必须是 JSON object 或包含 case_summary 的 object")
    return CaseSummary.model_validate(payload)


def generate_case_summary_content_with_llm(
    messages: list[dict[str, str]],
    *,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    timeout_sec: float = 90.0,
    max_tokens: int = 1600,
) -> tuple[str, dict[str, Any]]:
    """调用 OpenAI-compatible Chat Completions API，返回原始文本与模型元数据。"""

    config = resolve_llm_api_config(
        api_key_env=api_key_env,
        base_url=base_url,
        model_name=model_name,
        dotenv_path=dotenv_path,
    )
    payload = {
        "model": config.model_name,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        endpoint_for_chat_completions(config.base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
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
            f"病例摘要 LLM API 请求失败：HTTP {exc.code}；响应片段：{error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"病例摘要 LLM API 请求失败：{exc.reason}") from exc

    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM API 响应缺少 choices[0].message.content") from exc
    return str(content), {
        "model_name": config.model_name,
        "base_url": config.base_url,
        "api_key_env": config.api_key_env,
        "dotenv_path": config.dotenv_path,
    }


def build_generation_record(
    bundle: CaseSummaryInputBundle,
    *,
    run_llm: bool = False,
    llm_content_generator: LLMContentGenerator | None = None,
    summary_language: str = DEFAULT_SUMMARY_LANGUAGE,
    evidence_weighting_profile: str = DEFAULT_EVIDENCE_WEIGHTING_PROFILE,
    include_prompt: bool = True,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    timeout_sec: float = 90.0,
    max_tokens: int = 1600,
) -> dict[str, Any]:
    """生成一条病例摘要任务记录。"""

    evidence_weighting = evidence_weighting_metadata(evidence_weighting_profile)
    messages = build_case_summary_messages(
        bundle,
        summary_language=summary_language,
        evidence_weighting_profile=evidence_weighting_profile,
    )
    source_record_count = len(bundle.source_records)
    uncertain_span_count = sum(len(record.uncertain_spans) for record in bundle.source_records)
    transcript_word_count = len(bundle.input_transcript.split())
    record: dict[str, Any] = {
        "schema_version": CASE_SUMMARY_GENERATION_RECORD_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_TASK_ID,
        "bundle_id": bundle.bundle_id,
        "dataset": bundle.dataset,
        "split": bundle.split,
        "consultation_id": bundle.consultation_id,
        "input_unit": bundle.input_unit,
        "input_variant": bundle.input_variant,
        "source_record_count": source_record_count,
        "source_record_ids": bundle.source_record_ids,
        "source_sample_ids": bundle.source_sample_ids,
        "source_channels": bundle.source_channels,
        "input_transcript": bundle.input_transcript,
        "input_transcript_word_count": transcript_word_count,
        "input_transcript_char_count": len(bundle.input_transcript),
        "uncertain_span_count": uncertain_span_count,
        "prompt_messages": messages if include_prompt else None,
        "prompt_version": CASE_SUMMARY_PROMPT_VERSION,
        "evidence_weighting": evidence_weighting,
        "summary_language": summary_language,
        "status": STATUS_PROMPT_READY,
        "case_summary": None,
        "raw_model_output": None,
        "model": None,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_and_safety": {
            "record_contains_full_transcript_text": True,
            "record_contains_prompt_text": include_prompt,
            "research_use_only": True,
        },
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
        "notes": (
            "T041/T042b 从指定 input_variant transcript 生成结构化病例摘要；"
            "生成内容只用于研究评估，不构成临床建议。"
        ),
    }

    if not run_llm:
        return record

    if llm_content_generator is not None:
        raw_content = llm_content_generator(messages)
        model_metadata = {"model_name": "stub_llm_content_generator", "base_url": None}
    else:
        raw_content, model_metadata = generate_case_summary_content_with_llm(
            messages,
            api_key_env=api_key_env,
            base_url=base_url,
            model_name=model_name,
            dotenv_path=dotenv_path,
            timeout_sec=timeout_sec,
            max_tokens=max_tokens,
        )
    case_summary = coerce_case_summary_payload(parse_json_object(raw_content))
    record.update(
        {
            "status": STATUS_GENERATED,
            "case_summary": case_summary.model_dump(mode="json"),
            "raw_model_output": raw_content,
            "model": model_metadata,
        }
    )
    return record


def build_generation_records(
    bundles: Iterable[CaseSummaryInputBundle],
    *,
    max_workers: int = 1,
    max_attempts: int = 1,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """批量生成病例摘要任务记录。"""

    bundle_list = list(bundles)
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")
    if max_attempts <= 0:
        raise ValueError("max_attempts 必须大于 0")

    def generate_with_retry(bundle: CaseSummaryInputBundle) -> dict[str, Any]:
        for attempt in range(1, max_attempts + 1):
            try:
                return build_generation_record(bundle, **kwargs)
            except Exception:
                if attempt == max_attempts:
                    raise
        raise AssertionError("unreachable")

    if max_workers == 1 or len(bundle_list) <= 1:
        return [generate_with_retry(bundle) for bundle in bundle_list]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(generate_with_retry, bundle_list))


def build_summary(
    generation_records: list[dict[str, Any]],
    *,
    asr_input_jsonl: Path,
    confirmed_input_jsonl: Path | None = None,
    output_records_jsonl: Path,
    project_root: Path,
    group_by: str,
    run_llm: bool,
    summary_language: str,
    evidence_weighting_profile: str = DEFAULT_EVIDENCE_WEIGHTING_PROFILE,
    input_variants: Sequence[str] = (INPUT_VARIANT_NOISY_ASR,),
    skipped_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成不包含 transcript 正文的聚合 summary。"""

    status_counts = Counter(record["status"] for record in generation_records)
    input_unit_counts = Counter(record["input_unit"] for record in generation_records)
    input_variant_counts = Counter(record["input_variant"] for record in generation_records)
    status_counts_by_input_variant: dict[str, dict[str, int]] = {}
    channel_counts: Counter[str] = Counter()
    source_record_counts_by_input_variant: Counter[str] = Counter()
    source_record_total = 0
    transcript_word_counts: list[int] = []
    uncertain_span_total = 0
    for record in generation_records:
        channel_counts.update(record["source_channels"])
        source_record_total += record["source_record_count"]
        source_record_counts_by_input_variant[record["input_variant"]] += record[
            "source_record_count"
        ]
        transcript_word_counts.append(record["input_transcript_word_count"])
        uncertain_span_total += record["uncertain_span_count"]
        variant = record["input_variant"]
        if variant not in status_counts_by_input_variant:
            status_counts_by_input_variant[variant] = {}
        status_counts_by_input_variant[variant][record["status"]] = (
            status_counts_by_input_variant[variant].get(record["status"], 0) + 1
        )

    normalized_variants = [normalize_input_variant(variant) for variant in input_variants]
    skipped = skipped_records or []

    input_files: dict[str, str | None] = {
        "asr_input_jsonl": path_for_record(asr_input_jsonl, project_root),
    }
    if confirmed_input_jsonl is not None:
        input_files["confirmed_input_jsonl"] = path_for_record(
            confirmed_input_jsonl,
            project_root,
        )

    return {
        "schema_version": CASE_SUMMARY_GENERATION_SUMMARY_SCHEMA_VERSION,
        "task_id": CASE_SUMMARY_TASK_ID,
        "t042_subtask": "T042b_input_variant_aligned_generation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "primock57",
        "input_files": input_files,
        "output_files": {
            "records_jsonl": path_for_record(output_records_jsonl, project_root),
        },
        "record_count": len(generation_records),
        "source_record_count": source_record_total,
        "group_by": group_by,
        "input_variants_requested": normalized_variants,
        "input_variant_counts": dict(input_variant_counts),
        "source_record_counts_by_input_variant": dict(
            source_record_counts_by_input_variant
        ),
        "input_unit_counts": dict(input_unit_counts),
        "status_counts": dict(status_counts),
        "status_counts_by_input_variant": status_counts_by_input_variant,
        "source_channel_counts": dict(channel_counts),
        "prompt_version": CASE_SUMMARY_PROMPT_VERSION,
        "evidence_weighting": evidence_weighting_metadata(
            evidence_weighting_profile
        ),
        "summary_language": summary_language,
        "run_llm": run_llm,
        "transcript_word_count": {
            "total": sum(transcript_word_counts),
            "min": min(transcript_word_counts) if transcript_word_counts else None,
            "max": max(transcript_word_counts) if transcript_word_counts else None,
        },
        "uncertain_span_count": uncertain_span_total,
        "records_skipped": len(skipped),
        "skipped_records": skipped,
        "privacy_and_safety": {
            "records_jsonl_contains_full_transcript_text": True,
            "summary_contains_full_transcript_text": False,
            "research_use_only": True,
        },
        "notes": (
            "T041/T042b 默认按 consultation_id 合并分声道 transcript；"
            "doctor/patient 仍是声道级拼接，不代表精确 turn-level 对齐。"
            "三类 input_variant 使用同一病例摘要 schema 与 prompt_version，便于后续事实级评估。"
        ),
    }


def run_case_summary_generation(
    *,
    asr_input_jsonl: str | Path,
    output_records_jsonl: str | Path,
    output_summary_json: str | Path,
    project_root: str | Path,
    input_variants: Sequence[str] = (INPUT_VARIANT_NOISY_ASR,),
    confirmed_input_jsonl: str | Path | None = None,
    group_by: str = INPUT_UNIT_CONSULTATION,
    run_llm: bool = False,
    limit: int | None = None,
    summary_language: str = DEFAULT_SUMMARY_LANGUAGE,
    evidence_weighting_profile: str = DEFAULT_EVIDENCE_WEIGHTING_PROFILE,
    include_prompt: bool = True,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    timeout_sec: float = 90.0,
    max_tokens: int = 1600,
    max_workers: int = 1,
    max_attempts: int = 1,
    llm_content_generator: LLMContentGenerator | None = None,
) -> dict[str, Any]:
    """执行 T041 病例摘要生成任务并写出 records / summary。"""

    root = Path(project_root)
    asr_path = resolve_project_path(asr_input_jsonl, root)
    records_path = resolve_project_path(output_records_jsonl, root)
    summary_path = resolve_project_path(output_summary_json, root)
    active_dotenv_path = (
        resolve_project_path(dotenv_path, root) if dotenv_path is not None else None
    )
    active_input_variants = list(
        dict.fromkeys(normalize_input_variant(variant) for variant in input_variants)
    )
    confirmed_path = (
        resolve_project_path(confirmed_input_jsonl, root)
        if confirmed_input_jsonl is not None
        else None
    )

    asr_records = read_asr_confidence_jsonl(asr_path)
    if limit is not None:
        asr_records = asr_records[:limit]

    confirmed_index = None
    if INPUT_VARIANT_CONFIRMED_TRANSCRIPT in active_input_variants:
        if confirmed_path is None:
            raise ValueError(
                "input_variants 包含 confirmed_transcript 时必须提供 confirmed_input_jsonl"
            )
        confirmed_index = build_confirmed_index(
            read_confirmed_transcripts_jsonl(confirmed_path)
        )

    generation_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    for input_variant in active_input_variants:
        transcript_by_key, variant_skipped = _transcripts_for_input_variant(
            asr_records,
            input_variant=input_variant,
            project_root=root,
            confirmed_index=confirmed_index,
        )
        skipped_records.extend(variant_skipped)
        selected_records = [
            record for record in asr_records if _record_key(record) in transcript_by_key
        ]
        bundles = build_case_summary_input_bundles(
            selected_records,
            group_by=group_by,
            input_variant=input_variant,
            transcript_getter=lambda record, mapping=transcript_by_key: mapping[
                _record_key(record)
            ],
        )
        generation_records.extend(
            build_generation_records(
                bundles,
                run_llm=run_llm,
                llm_content_generator=llm_content_generator,
                summary_language=summary_language,
                evidence_weighting_profile=evidence_weighting_profile,
                include_prompt=include_prompt,
                api_key_env=api_key_env,
                base_url=base_url,
                model_name=model_name,
                dotenv_path=active_dotenv_path,
                timeout_sec=timeout_sec,
                max_tokens=max_tokens,
                max_workers=max_workers,
                max_attempts=max_attempts,
            )
        )

    write_jsonl(generation_records, records_path)
    summary = build_summary(
        generation_records,
        asr_input_jsonl=asr_path,
        confirmed_input_jsonl=confirmed_path,
        output_records_jsonl=records_path,
        project_root=root,
        group_by=group_by,
        run_llm=run_llm,
        summary_language=summary_language,
        evidence_weighting_profile=evidence_weighting_profile,
        input_variants=active_input_variants,
        skipped_records=skipped_records,
    )
    write_json(summary, summary_path)
    return summary


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    """写入 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: str | Path) -> None:
    """写入 JSON。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _bundle_from_records(
    records: list[ASRConfidenceRecord],
    *,
    input_unit: str,
    input_variant: str,
    transcript_getter: TranscriptGetter | None = None,
) -> CaseSummaryInputBundle:
    if not records:
        raise ValueError("病例摘要输入 bundle 至少需要一条 ASR record")
    ordered_records = sorted(
        records,
        key=lambda record: (
            record.consultation_id or "",
            record.source_channel.value,
            record.sample_id,
        ),
    )
    first = ordered_records[0]
    consultation_id = first.consultation_id
    if input_unit == INPUT_UNIT_CONSULTATION:
        bundle_core = consultation_id or first.sample_id
    else:
        bundle_core = first.record_id or first.sample_id
    bundle_id = f"{first.dataset}:{bundle_core}:{input_variant}:{input_unit}"
    active_transcript_getter = transcript_getter or (lambda record: record.asr_transcript)
    transcript_blocks = []
    seen_reference_pointers: set[str] = set()
    for record in ordered_records:
        if (
            input_unit == INPUT_UNIT_CONSULTATION
            and input_variant == INPUT_VARIANT_REFERENCE_ORACLE
        ):
            reference_pointer = _reference_pointer_for_record(record)
            if reference_pointer and reference_pointer in seen_reference_pointers:
                continue
            if reference_pointer:
                seen_reference_pointers.add(reference_pointer)
        transcript = active_transcript_getter(record).strip()
        if transcript:
            transcript_blocks.append(_format_transcript_block(record, transcript))
    return CaseSummaryInputBundle(
        bundle_id=bundle_id,
        dataset=first.dataset,
        split=first.split,
        consultation_id=consultation_id,
        input_unit=input_unit,
        input_variant=input_variant,
        source_records=tuple(ordered_records),
        input_transcript="\n\n".join(transcript_blocks),
    )


def _format_transcript_block(record: ASRConfidenceRecord, transcript: str) -> str:
    label = record.source_channel.value
    sample_id = record.sample_id
    return f"[{label} | sample_id={sample_id}]\n{transcript.strip()}"


def normalize_input_variant(input_variant: str) -> str:
    """规范化病例摘要输入 variant 名称。"""

    normalized = input_variant.strip()
    if normalized == INPUT_VARIANT_RAW_ASR_ALIAS:
        return INPUT_VARIANT_NOISY_ASR
    if normalized not in SUPPORTED_INPUT_VARIANTS:
        raise ValueError(f"未知 input_variant：{input_variant}")
    return normalized


def input_variant_prompt_context(input_variant: str) -> dict[str, str]:
    """返回某个 input_variant 对应的 prompt 文案片段。"""

    normalized = normalize_input_variant(input_variant)
    if normalized == INPUT_VARIANT_NOISY_ASR:
        return {
            "source_label": "noisy ASR transcript",
            "transcript_heading": "noisy ASR transcript",
            "uncertainty_instruction": (
                "input_variant=noisy_asr 表示 ASR noisy transcript；"
                "如果 ASR 转写明显噪声较大、低置信线索较多或某项信息不确定，"
                "请写入 uncertainty_notes。"
            ),
        }
    if normalized == INPUT_VARIANT_CONFIRMED_TRANSCRIPT:
        return {
            "source_label": "doctor/researcher-confirmed transcript",
            "transcript_heading": "confirmed transcript",
            "uncertainty_instruction": (
                "input_variant=confirmed_transcript 表示经医生或研究者反馈回放后的转写；"
                "它仍是研究产物，不应被视为临床真实结论。"
                "如果文本中存在未解决、拒绝或无法判断的信息，请写入 uncertainty_notes。"
            ),
        }
    if normalized == INPUT_VARIANT_REFERENCE_ORACLE:
        return {
            "source_label": "clean/reference transcript oracle",
            "transcript_heading": "reference transcript oracle",
            "uncertainty_instruction": (
                "input_variant=reference_oracle 表示 clean/reference transcript 上限输入；"
                "除非原文自身含糊，不要把 ASR 噪声作为不确定性来源。"
            ),
        }
    raise ValueError(f"未知 input_variant：{input_variant}")


def normalize_evidence_weighting_profile(profile: str) -> str:
    """规范化病例摘要证据加权 profile。"""

    normalized = profile.strip()
    if normalized not in SUPPORTED_EVIDENCE_WEIGHTING_PROFILES:
        raise ValueError(f"未知 evidence_weighting_profile：{profile}")
    return normalized


def evidence_weighting_metadata(profile: str) -> dict[str, Any]:
    """返回可写入 records/summary 的证据加权配置，不含 transcript 正文。"""

    normalized = normalize_evidence_weighting_profile(profile)
    if normalized == EVIDENCE_WEIGHTING_ROLE_BLIND:
        weights = {
            field: {"doctor": 1.0, "patient": 1.0}
            for field in FIELD_CONDITIONED_ROLE_WEIGHTS
        }
        mode = "role_blind_ablation"
    else:
        weights = {
            field: dict(role_weights)
            for field, role_weights in FIELD_CONDITIONED_ROLE_WEIGHTS.items()
        }
        mode = "soft_prompt_role_field_prior"
    return {
        "profile": normalized,
        "mode": mode,
        "field_role_weights": weights,
        "weights_are_relative_priorities_not_probabilities": True,
        "doctor_question_is_not_assertion": True,
        "conflicts_require_attribution_or_uncertainty": True,
        "gold_facts_unchanged": True,
    }


def build_evidence_weighting_instruction(
    profile: str,
    *,
    summary_language: str = DEFAULT_SUMMARY_LANGUAGE,
) -> str:
    """把证据加权配置转换为供病例摘要模型执行的明确规则。"""

    metadata = evidence_weighting_metadata(profile)
    if metadata["profile"] == EVIDENCE_WEIGHTING_ROLE_BLIND:
        if summary_language == "zh":
            return (
                "证据选择采用 role_blind 消融：医生与患者话语具有相同的初始优先级。"
                "仍须区分谁说了什么；医生的提问不等于患者确认，也不等于医生判断。"
            )
        return (
            "Use the role_blind ablation: doctor and patient utterances have the "
            "same initial priority. Still track who said what; a doctor's question "
            "is neither a patient confirmation nor a clinical assessment."
        )

    weights = metadata["field_role_weights"]
    if summary_language == "zh":
        rows = [
            f"- {field}: doctor={values['doctor']:.1f}, patient={values['patient']:.1f}"
            for field, values in weights.items()
        ]
        return (
            "证据选择采用字段条件化的说话人软权重。下列数字仅表示相对排序优先级，"
            "不是事实真实性概率，也不能覆盖原文证据：\n"
            + "\n".join(rows)
            + "\n执行约束：患者主诉、症状、否定症状和病史不得仅因来自患者而被省略；"
            "medications 中患者自述的既往/当前用药优先患者证据，"
            "医生新开药、剂量调整或治疗建议优先医生证据；"
            "医生的提问不算事实陈述；若双方在否定、时间、剂量、检查结果或计划上冲突，"
            "不得静默用高权重一方覆盖另一方，应保留说话人归因并写入 uncertainty_notes。"
        )
    rows = [
        f"- {field}: doctor={values['doctor']:.1f}, patient={values['patient']:.1f}"
        for field, values in weights.items()
    ]
    return (
        "Use field-conditioned soft speaker weights for evidence ranking. These "
        "numbers are relative priorities, not truth probabilities, and cannot "
        "override transcript evidence:\n"
        + "\n".join(rows)
        + "\nDo not omit subjective complaints, symptoms, negations, or history only "
        "because they come from the patient. For medications, prioritize the patient "
        "for reported current/past use and the doctor for prescriptions, dose changes, "
        "or treatment recommendations. A doctor's question is not an assertion. If "
        "speakers conflict on negation, time, dosage, test results, or plans, preserve "
        "attribution and add an uncertainty_notes entry instead of silently overriding."
    )


def _transcripts_for_input_variant(
    records: Iterable[ASRConfidenceRecord],
    *,
    input_variant: str,
    project_root: Path,
    confirmed_index: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """为某个 input_variant 选择每条 ASR record 对应的 transcript。"""

    normalized = normalize_input_variant(input_variant)
    transcript_by_key: dict[str, str] = {}
    skipped_records: list[dict[str, Any]] = []
    for record in records:
        key = _record_key(record)
        transcript: str | None = None
        skip_reason: str | None = None
        skip_metadata: dict[str, Any] = {}

        if normalized == INPUT_VARIANT_NOISY_ASR:
            transcript = record.asr_transcript
        elif normalized == INPUT_VARIANT_CONFIRMED_TRANSCRIPT:
            confirmed_record = (
                find_confirmed_for_asr_record(record, confirmed_index)
                if confirmed_index is not None
                else None
            )
            if confirmed_record is None:
                skip_reason = "missing_confirmed_transcript"
            else:
                transcript = confirmed_record.confirmed_transcript
        elif normalized == INPUT_VARIANT_REFERENCE_ORACLE:
            reference_pointer = _reference_pointer_for_record(record)
            if reference_pointer is None:
                skip_reason = "missing_reference_pointer"
            else:
                reference_path = resolve_project_path(reference_pointer, project_root)
                skip_metadata["reference_path"] = path_for_record(
                    reference_path,
                    project_root,
                )
                if not reference_path.exists():
                    skip_reason = "reference_file_not_found"
                else:
                    transcript = read_reference_transcript(reference_path)
        else:
            raise ValueError(f"未知 input_variant：{input_variant}")

        if skip_reason is None and (transcript is None or not transcript.strip()):
            skip_reason = "empty_variant_transcript"
        if skip_reason is not None:
            skipped_records.append(
                {
                    "input_variant": normalized,
                    "sample_id": record.sample_id,
                    "record_id": record.record_id,
                    "consultation_id": record.consultation_id,
                    "source_channel": record.source_channel.value,
                    "reason": skip_reason,
                    **skip_metadata,
                }
            )
            continue
        transcript_by_key[key] = transcript or ""
    return transcript_by_key, skipped_records


def _record_key(record: ASRConfidenceRecord) -> str:
    return record.record_id or record.sample_id


def _reference_pointer_for_record(record: ASRConfidenceRecord) -> str | None:
    return record.reference_textgrid_path or record.reference_transcript_path


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        output = []
        for item in value:
            text = str(item).strip()
            if text:
                output.append(text)
        return output
    text = str(value).strip()
    return [text] if text else []
