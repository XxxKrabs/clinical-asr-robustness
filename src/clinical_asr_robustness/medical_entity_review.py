"""医学实体优先的 ASR 置信度审阅 gating。

本模块把“每个低/中置信度词组都进入医生审阅”改成：

1. 先用 LLM 从 ASR transcript 中抽取医学实体/术语；
2. 只保留医学实体覆盖范围内的低/中/未知置信度 span 作为 `uncertain_spans`；
3. 所有非医学词在审阅界面按普通黑字显示；医学实体词才显示绿/黄/红。

注意：`UncertainSpan` schema 当前不允许 green，因此高置信度医学实体只通过
word metadata 控制绿色显示，不进入候选生成/反馈回放列表。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness.asr_confidence import (
    AlternativeScope,
    ASRConfidenceRecord,
    ASRWord,
    ConfidenceLevel,
    UncertainSpan,
    confidence_level_for_score,
)

MEDICAL_ENTITY_REVIEW_SCHEMA_VERSION = "medical_entity_review/v1"
MEDICAL_ENTITY_EXTRACTION_SCHEMA_VERSION = "medical_entity_extraction/v1"
T038_GENERATED_BY = "T038"

DEFAULT_PARATERA_BASE_URL = "https://llmapi.paratera.com"
DEFAULT_PARATERA_MODEL = "Qwen3-Next-80B-A3B-Instruct"
DEFAULT_API_KEY_ENV = "PARATERA_API_KEY"
DEFAULT_DOTENV_FILENAME = ".env"
MEDICAL_ENTITY_REVIEW_METADATA_KEY = "medical_entity_review"
MEDICAL_ENTITY_TRIGGER_REASON = "medical_entity_low_or_medium_confidence"
LLM_EXTRACTION_SOURCE = "llm_medical_entity_extraction"
KEYWORD_FALLBACK_SOURCE = "keyword_medical_entity_fallback"

API_KEY_ENV_KEYS = ("PARATERA_API_KEY", "API_KEY", "OPENAI_API_KEY")
BASE_URL_ENV_KEYS = ("PARATERA_BASE_URL", "BASE_URL", "API_URL", "OPENAI_BASE_URL")
MODEL_ENV_KEYS = ("PARATERA_MODEL", "MODEL", "MODEL_ID", "OPENAI_MODEL")

_ENTITY_TYPES = {
    "disease",
    "diagnosis",
    "symptom",
    "sign",
    "medication",
    "drug",
    "dosage",
    "procedure",
    "surgery",
    "lab_test",
    "imaging",
    "anatomy",
    "device",
    "medical_abbreviation",
    "clinical_attribute",
    "other_medical_term",
}

_ENTITY_BOUNDARY_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "any",
    "are",
    "be",
    "been",
    "being",
    "can",
    "could",
    "did",
    "do",
    "does",
    "else",
    "for",
    "going",
    "got",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "kind",
    "mean",
    "mentioned",
    "mentioning",
    "my",
    "not",
    "noticed",
    "of",
    "on",
    "or",
    "other",
    "our",
    "she",
    "some",
    "talk",
    "talking",
    "that",
    "the",
    "their",
    "there",
    "theres",
    "this",
    "to",
    "towil",
    "was",
    "were",
    "what",
    "with",
    "would",
    "you",
    "youre",
    "your",
    "youware",
    "youwere",
}

_NON_MEDICAL_ENTITY_WORDS = _ENTITY_BOUNDARY_WORDS | {
    "food",
    "go",
    "just",
    "like",
    "okay",
    "ok",
    "please",
    "right",
    "say",
    "saying",
    "so",
    "then",
    "thing",
    "things",
    "think",
    "well",
}

_ENTITY_SPLIT_WORDS = {"and", "or"}

_KEYWORD_FALLBACK_PHRASES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("tummy", "pain"), "symptom", "tummy pain"),
    (("loose", "stools"), "symptom", "loose stools"),
    (("loose", "stool"), "symptom", "loose stool"),
)

_KEYWORD_FALLBACK_TOKENS: dict[str, tuple[str, str]] = {
    "asthma": ("disease", "asthma"),
    "blood": ("symptom", "blood"),
    "diarrhea": ("symptom", "diarrhea"),
    "diarrheea": ("symptom", "diarrheea"),
    "diarrhoea": ("symptom", "diarrhoea"),
    "fever": ("symptom", "fever"),
    "feverish": ("symptom", "feverish"),
    "fluid": ("clinical_attribute", "fluid"),
    "fluids": ("clinical_attribute", "fluids"),
    "inhaler": ("device", "inhaler"),
    "inhalers": ("device", "inhalers"),
    "loose": ("clinical_attribute", "loose"),
    "medication": ("medication", "medication"),
    "medications": ("medication", "medications"),
    "medicine": ("medication", "medicine"),
    "medicines": ("medication", "medicines"),
    "meds": ("medication", "meds"),
    "pain": ("symptom", "pain"),
    "shaky": ("symptom", "shaky"),
    "stool": ("symptom", "stool"),
    "stools": ("symptom", "stools"),
    "sweating": ("symptom", "sweating"),
    "symptom": ("clinical_attribute", "symptom"),
    "symptoms": ("clinical_attribute", "symptoms"),
    "temperature": ("symptom", "temperature"),
    "tummy": ("anatomy", "tummy"),
    "vomit": ("symptom", "vomit"),
    "vomiting": ("symptom", "vomiting"),
    "weak": ("symptom", "weak"),
}


class MedicalEntityMention(BaseModel):
    """ASR transcript 中的一个医学实体 mention。"""

    model_config = ConfigDict(extra="forbid")

    entity_id: str | None = None
    text: str = Field(min_length=1)
    entity_type: str = "other_medical_term"
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    start_word_index: int | None = Field(default=None, ge=0)
    end_word_index: int | None = Field(default=None, ge=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str = LLM_EXTRACTION_SOURCE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_offsets(self) -> MedicalEntityMention:
        self.text = " ".join(self.text.split())
        self.entity_type = normalize_entity_type(self.entity_type)
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError("end_char 必须大于 start_char")
        if self.start_word_index is not None and self.end_word_index is not None:
            if self.end_word_index <= self.start_word_index:
                raise ValueError("end_word_index 必须大于 start_word_index")
        return self


class MedicalEntityExtractionRecord(BaseModel):
    """一条 ASR record 对应的医学实体抽取结果。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = MEDICAL_ENTITY_EXTRACTION_SCHEMA_VERSION
    record_id: str | None = None
    sample_id: str
    dataset: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    extracted_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    entities: list[MedicalEntityMention] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True


@dataclass(frozen=True)
class WordCharSpan:
    """一个 ASR word 在 transcript 中的字符范围。"""

    word_index: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class ResolvedEntityGroup:
    """合并重叠实体后的审阅范围。"""

    start_word_index: int
    end_word_index: int
    entity_ids: tuple[str, ...]


@dataclass(frozen=True)
class LLMAPIConfig:
    """LLM API 调用配置。

    `api_key` 设置为 `repr=False`，避免测试失败或日志打印时泄露密钥。
    """

    api_key: str = field(repr=False)
    base_url: str
    model_name: str
    api_key_env: str = DEFAULT_API_KEY_ENV
    dotenv_path: str | None = None


def normalize_entity_type(value: str | None) -> str:
    """规整 LLM 返回的 entity type；未知类型保留为 `other_medical_term`。"""

    if not value:
        return "other_medical_term"
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip().casefold()).strip("_")
    return normalized if normalized in _ENTITY_TYPES else "other_medical_term"


def endpoint_for_chat_completions(base_url: str) -> str:
    """把 OpenAI-compatible base URL 转成 chat completions endpoint。"""

    stripped = base_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        return stripped
    if stripped.endswith("/v1"):
        return f"{stripped}/chat/completions"
    return f"{stripped}/v1/chat/completions"


def read_project_env_file(path: str | Path | None) -> dict[str, str]:
    """读取项目级 `.env` 文件。

    这是一个刻意很小的 parser，只支持常见的 `KEY=value` / `export KEY=value`
    形式。它返回字典，不写入 `os.environ`，避免把本项目 key 混入其他项目。
    """

    if path is None:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    with env_path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[len("export ") :].strip()
            if "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue
            values[key] = _parse_dotenv_value(raw_value)
    return values


def resolve_llm_api_config(
    *,
    api_key: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    dotenv_values: dict[str, str] | None = None,
    use_os_environ: bool = True,
) -> LLMAPIConfig:
    """按“显式参数 → 项目 `.env` → 系统环境变量 → 默认值”解析 LLM 配置。"""

    env_values = dotenv_values
    if env_values is None:
        env_values = read_project_env_file(dotenv_path)

    active_api_key = (
        api_key
        or _first_config_value(env_values, (api_key_env, *API_KEY_ENV_KEYS))
        or (
            _first_config_value(os.environ, (api_key_env, *API_KEY_ENV_KEYS))
            if use_os_environ
            else None
        )
    )
    if not active_api_key:
        env_hint = f" 或项目 .env 中的 {api_key_env}/API_KEY"
        raise RuntimeError(f"缺少 API key。请设置{env_hint}，不要把密钥写入 Git。")

    active_base_url = (
        base_url
        or _first_config_value(env_values, BASE_URL_ENV_KEYS)
        or (_first_config_value(os.environ, BASE_URL_ENV_KEYS) if use_os_environ else None)
        or DEFAULT_PARATERA_BASE_URL
    )
    active_model = (
        model_name
        or _first_config_value(env_values, MODEL_ENV_KEYS)
        or (_first_config_value(os.environ, MODEL_ENV_KEYS) if use_os_environ else None)
        or DEFAULT_PARATERA_MODEL
    )
    return LLMAPIConfig(
        api_key=active_api_key,
        base_url=active_base_url,
        model_name=active_model,
        api_key_env=api_key_env,
        dotenv_path=str(dotenv_path) if dotenv_path is not None else None,
    )


def extract_medical_entities_with_llm(
    transcript: str,
    *,
    api_key: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    dotenv_values: dict[str, str] | None = None,
    timeout_sec: float = 60.0,
) -> list[MedicalEntityMention]:
    """调用 OpenAI-compatible Chat Completions API 抽取医学实体。

    API key 默认从项目 `.env` 或环境变量读取，避免出现在命令行、代码或运行记录中。
    """

    config = resolve_llm_api_config(
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        model_name=model_name,
        dotenv_path=dotenv_path,
        dotenv_values=dotenv_values,
    )

    payload = {
        "model": config.model_name,
        "messages": [
            {
                "role": "system",
                "content": _medical_entity_extraction_system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "请从下面 ASR 转写文本中抽取医学实体。只返回 JSON。\n\n"
                    f"ASR transcript:\n{transcript}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 1600,
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
            f"LLM API 请求失败：HTTP {exc.code}；响应片段：{error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM API 请求失败：{exc.reason}") from exc

    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM API 响应缺少 choices[0].message.content") from exc
    return coerce_medical_entity_mentions(parse_json_object(content))


def coerce_medical_entity_mentions(payload: Any) -> list[MedicalEntityMention]:
    """把 LLM/缓存中的实体 JSON 规整成 `MedicalEntityMention` 列表。"""

    if isinstance(payload, dict):
        raw_entities = payload.get("entities", [])
    elif isinstance(payload, list):
        raw_entities = payload
    else:
        raise ValueError("医学实体抽取结果必须是 JSON object 或 list")

    entities: list[MedicalEntityMention] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            continue
        text = _first_present_string(raw_entity, "text", "mention", "entity")
        if not text:
            continue
        entity_type = _first_present_string(
            raw_entity,
            "entity_type",
            "type",
            "category",
            "label",
        )
        confidence = _float_or_none(
            raw_entity.get("confidence", raw_entity.get("score"))
        )
        entity_payload = {
            "entity_id": _first_present_string(raw_entity, "entity_id", "id"),
            "text": text,
            "entity_type": entity_type or "other_medical_term",
            "start_char": _int_or_none(
                raw_entity.get("start_char", raw_entity.get("char_start"))
            ),
            "end_char": _int_or_none(
                raw_entity.get("end_char", raw_entity.get("char_end"))
            ),
            "start_word_index": _int_or_none(
                raw_entity.get("start_word_index", raw_entity.get("word_start"))
            ),
            "end_word_index": _int_or_none(
                raw_entity.get("end_word_index", raw_entity.get("word_end"))
            ),
            "confidence": confidence,
            "metadata": {
                "raw_entity": {
                    key: value
                    for key, value in raw_entity.items()
                    if key not in {"text", "mention", "entity"}
                }
            },
        }
        try:
            entities.append(MedicalEntityMention.model_validate(entity_payload))
        except ValueError:
            continue
    return entities


def parse_json_object(content: str) -> Any:
    """从 LLM 文本中解析 JSON；兼容 ```json fences。"""

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if not starts:
        raise ValueError("LLM 输出中找不到 JSON object/list")
    start = min(starts)
    end_object = stripped.rfind("}")
    end_list = stripped.rfind("]")
    end = max(end_object, end_list)
    if end <= start:
        raise ValueError("LLM 输出中的 JSON 范围无效")
    return json.loads(stripped[start : end + 1])


def build_medical_entity_extraction_record(
    record: ASRConfidenceRecord,
    *,
    entities: Iterable[MedicalEntityMention],
    model_name: str | None = None,
    base_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> MedicalEntityExtractionRecord:
    """把实体列表包装成可缓存的 JSONL 记录。"""

    return MedicalEntityExtractionRecord(
        record_id=record.record_id,
        sample_id=record.sample_id,
        dataset=record.dataset,
        model_name=model_name,
        base_url=base_url,
        entities=list(entities),
        metadata=metadata or {},
    )


def read_medical_entity_extractions_jsonl(
    path: str | Path,
) -> list[MedicalEntityExtractionRecord]:
    """读取医学实体抽取缓存 JSONL。"""

    records: list[MedicalEntityExtractionRecord] = []
    jsonl_path = Path(path)
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(MedicalEntityExtractionRecord.model_validate_json(stripped))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"无法解析医学实体 JSONL 第 {line_number} 行：{jsonl_path}"
                ) from exc
    return records


def write_medical_entity_extractions_jsonl(
    records: Iterable[MedicalEntityExtractionRecord],
    path: str | Path,
) -> None:
    """写入医学实体抽取缓存 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def extraction_records_by_key(
    records: Iterable[MedicalEntityExtractionRecord],
) -> dict[str, MedicalEntityExtractionRecord]:
    """按 record_id/sample_id 建立缓存索引。"""

    by_key: dict[str, MedicalEntityExtractionRecord] = {}
    for record in records:
        if record.record_id:
            by_key[f"record_id:{record.record_id}"] = record
        by_key[f"sample_id:{record.sample_id}"] = record
    return by_key


def extraction_for_asr_record(
    record: ASRConfidenceRecord,
    by_key: dict[str, MedicalEntityExtractionRecord],
) -> MedicalEntityExtractionRecord | None:
    """优先按 record_id，其次按 sample_id 找实体缓存。"""

    if record.record_id:
        cached = by_key.get(f"record_id:{record.record_id}")
        if cached is not None:
            return cached
    return by_key.get(f"sample_id:{record.sample_id}")


def postprocess_medical_entities_for_review(
    record: ASRConfidenceRecord,
    entities: Iterable[MedicalEntityMention],
) -> tuple[list[MedicalEntityMention], dict[str, int]]:
    """裁剪 LLM 粗 span，并用小型医学关键词表补漏。

    这里不改变任何公开 schema，只在进入 gating 前把实体范围变得更“最小”：

    - 去掉 `do/you/mean/your/what/kind/of/talk/about` 等边界普通词；
    - 丢弃裁剪后只剩普通问句词/上下文词的 mention；
    - 对 `diarrhea/pain/vomiting/...` 等明显医学词做兜底补充。
    """

    input_entities = list(entities)
    cleaned_entities: list[MedicalEntityMention] = []
    stats = {
        "input_entity_count": len(input_entities),
        "trimmed_entity_count": 0,
        "split_entity_count": 0,
        "dropped_nonmedical_entity_count": 0,
        "keyword_fallback_entity_count": 0,
    }

    word_char_spans = word_char_spans_for_record(record)
    for entity in input_entities:
        word_range = resolve_entity_word_range(record, entity)
        if word_range is None:
            stats["dropped_nonmedical_entity_count"] += 1
            continue

        slices = _minimal_medical_word_slices(record, word_range)
        if not slices:
            stats["dropped_nonmedical_entity_count"] += 1
            continue
        if len(slices) > 1:
            stats["split_entity_count"] += len(slices) - 1

        for start_word_index, end_word_index in slices:
            changed = (start_word_index, end_word_index) != word_range
            if changed:
                stats["trimmed_entity_count"] += 1
            cleaned_entities.append(
                _entity_copy_for_word_range(
                    entity,
                    record,
                    word_char_spans,
                    start_word_index,
                    end_word_index,
                    reset_entity_id=changed or len(slices) > 1,
                )
            )

    with_fallback, fallback_count = _add_keyword_fallback_entities(
        record,
        cleaned_entities,
        word_char_spans,
    )
    stats["keyword_fallback_entity_count"] = fallback_count
    stats["postprocessed_entity_count"] = len(with_fallback)
    return with_fallback, stats


def apply_medical_entity_review_gating(
    record: ASRConfidenceRecord,
    entities: Iterable[MedicalEntityMention],
    *,
    generated_by: str = T038_GENERATED_BY,
) -> ASRConfidenceRecord:
    """把一条 ASR confidence record 改造成“医学实体优先审阅”版本。

    返回的新 record 会：

    - 清空原先按全词置信度生成的 `uncertain_spans`；
    - 只为医学实体中非 green 的范围生成新的 `uncertain_spans`；
    - 清除旧 span/word alternatives，保留 sequence alternatives 供 T029 复用；
    - 在 `asr_words[].metadata.medical_entity_review` 中写入界面显示策略。
    """

    input_entities = list(entities)
    review_entities, postprocess_stats = postprocess_medical_entities_for_review(
        record,
        input_entities,
    )
    resolved_entities = resolve_medical_entities(record, review_entities)
    groups = merge_resolved_entity_groups(resolved_entities)
    entity_ids_by_word = _entity_ids_by_word(resolved_entities, len(record.asr_words))
    annotated_words = [
        _annotate_word_for_medical_review(word, entity_ids_by_word.get(word.word_index, []))
        for word in record.asr_words
    ]
    review_spans = _build_medical_review_spans(
        annotated_words,
        groups,
        entities_by_id={entity.entity_id or "": entity for entity in resolved_entities},
        generated_by=generated_by,
        thresholds=record.confidence.thresholds,
    )
    kept_alternatives = [
        alternative
        for alternative in record.asr_alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    ]
    metadata = dict(record.metadata)
    metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY] = {
        "schema_version": MEDICAL_ENTITY_REVIEW_SCHEMA_VERSION,
        "generated_by": generated_by,
        "source": LLM_EXTRACTION_SOURCE,
        "input_entity_count": len(input_entities),
        "postprocessed_entity_count": len(review_entities),
        "keyword_fallback_entity_count": postprocess_stats[
            "keyword_fallback_entity_count"
        ],
        "dropped_nonmedical_entity_count": postprocess_stats[
            "dropped_nonmedical_entity_count"
        ],
        "trimmed_entity_count": postprocess_stats["trimmed_entity_count"],
        "split_entity_count": postprocess_stats["split_entity_count"],
        "matched_entity_count": len(resolved_entities),
        "review_span_count": len(review_spans),
        "medical_words_colored": sorted(entity_ids_by_word),
        "non_medical_words_display": "neutral_black",
        "green_medical_entities_not_in_uncertain_spans": max(
            0,
            len(groups) - len(review_spans),
        ),
        "entities": [
            entity.model_dump(mode="json") for entity in resolved_entities
        ],
        "note": (
            "Only postprocessed LLM or keyword-fallback medical entities keep "
            "green/yellow/red display. "
            "Non-medical words are rendered as neutral black context words; only "
            "non-green medical entity spans are kept for candidate generation."
        ),
    }

    payload = record.model_dump(mode="json")
    payload["asr_words"] = [word.model_dump(mode="json") for word in annotated_words]
    payload["uncertain_spans"] = [span.model_dump(mode="json") for span in review_spans]
    payload["asr_alternatives"] = [
        alternative.model_dump(mode="json") for alternative in kept_alternatives
    ]
    payload["metadata"] = metadata
    return ASRConfidenceRecord.model_validate(payload)


def _minimal_medical_word_slices(
    record: ASRConfidenceRecord,
    word_range: tuple[int, int],
) -> list[tuple[int, int]]:
    start, end = _trim_entity_word_range(record, *word_range)
    if start >= end or _word_range_is_nonmedical_only(record, start, end):
        return []

    slices: list[tuple[int, int]] = []
    slice_start = start
    for word_index in range(start, end):
        token = normalize_text_for_match(record.asr_words[word_index].text)
        if token not in _ENTITY_SPLIT_WORDS:
            continue
        _append_minimal_slice(record, slices, slice_start, word_index)
        slice_start = word_index + 1
    _append_minimal_slice(record, slices, slice_start, end)
    return slices


def _append_minimal_slice(
    record: ASRConfidenceRecord,
    slices: list[tuple[int, int]],
    start: int,
    end: int,
) -> None:
    trimmed_start, trimmed_end = _trim_entity_word_range(record, start, end)
    if trimmed_start >= trimmed_end:
        return
    if _word_range_is_nonmedical_only(record, trimmed_start, trimmed_end):
        return
    slices.append((trimmed_start, trimmed_end))


def _trim_entity_word_range(
    record: ASRConfidenceRecord,
    start: int,
    end: int,
) -> tuple[int, int]:
    word_count = len(record.asr_words)
    start = max(0, min(start, word_count))
    end = max(start, min(end, word_count))
    while start < end and _is_entity_boundary_word(record.asr_words[start].text):
        start += 1
    while start < end and _is_entity_boundary_word(record.asr_words[end - 1].text):
        end -= 1
    return start, end


def _is_entity_boundary_word(value: str) -> bool:
    token = normalize_text_for_match(value)
    return not token or token in _ENTITY_BOUNDARY_WORDS


def _word_range_is_nonmedical_only(
    record: ASRConfidenceRecord,
    start: int,
    end: int,
) -> bool:
    tokens = [
        normalize_text_for_match(word.text)
        for word in record.asr_words[start:end]
        if normalize_text_for_match(word.text)
    ]
    if not tokens:
        return True
    return all(token in _NON_MEDICAL_ENTITY_WORDS for token in tokens)


def _entity_copy_for_word_range(
    entity: MedicalEntityMention,
    record: ASRConfidenceRecord,
    word_char_spans: list[WordCharSpan],
    start_word_index: int,
    end_word_index: int,
    *,
    reset_entity_id: bool,
) -> MedicalEntityMention:
    start_char, end_char = _char_range_for_word_range(
        word_char_spans,
        start_word_index,
        end_word_index,
    )
    metadata = dict(entity.metadata)
    metadata["postprocess"] = {
        "method": "trim_common_boundary_words",
        "original_text": entity.text,
        "original_start_word_index": entity.start_word_index,
        "original_end_word_index": entity.end_word_index,
        "original_start_char": entity.start_char,
        "original_end_char": entity.end_char,
    }
    update: dict[str, Any] = {
        "text": " ".join(
            word.text for word in record.asr_words[start_word_index:end_word_index]
        ),
        "start_char": start_char,
        "end_char": end_char,
        "start_word_index": start_word_index,
        "end_word_index": end_word_index,
        "metadata": metadata,
    }
    if reset_entity_id:
        update["entity_id"] = None
    return entity.model_copy(update=update)


def _add_keyword_fallback_entities(
    record: ASRConfidenceRecord,
    entities: list[MedicalEntityMention],
    word_char_spans: list[WordCharSpan],
) -> tuple[list[MedicalEntityMention], int]:
    output_entities = list(entities)
    fallback_count = 0
    word_tokens = [normalize_text_for_match(word.text) for word in record.asr_words]
    fallback_covered_words: set[int] = set()

    for phrase_tokens, entity_type, canonical in sorted(
        _KEYWORD_FALLBACK_PHRASES,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        width = len(phrase_tokens)
        for start in range(0, len(word_tokens) - width + 1):
            end = start + width
            if tuple(word_tokens[start:end]) != phrase_tokens:
                continue
            if _word_range_covered_by_entities(output_entities, start, end):
                continue
            output_entities.append(
                _keyword_fallback_mention(
                    record,
                    word_char_spans,
                    start,
                    end,
                    entity_type=entity_type,
                    canonical=canonical,
                )
            )
            fallback_count += 1
            fallback_covered_words.update(range(start, end))

    for word_index, token in enumerate(word_tokens):
        if not token or token not in _KEYWORD_FALLBACK_TOKENS:
            continue
        if word_index in fallback_covered_words:
            continue
        if _word_range_covered_by_entities(output_entities, word_index, word_index + 1):
            continue
        entity_type, canonical = _KEYWORD_FALLBACK_TOKENS[token]
        output_entities.append(
            _keyword_fallback_mention(
                record,
                word_char_spans,
                word_index,
                word_index + 1,
                entity_type=entity_type,
                canonical=canonical,
            )
        )
        fallback_count += 1

    return output_entities, fallback_count


def _word_range_covered_by_entities(
    entities: Iterable[MedicalEntityMention],
    start_word_index: int,
    end_word_index: int,
) -> bool:
    for entity in entities:
        if entity.start_word_index is None or entity.end_word_index is None:
            continue
        if (
            entity.start_word_index <= start_word_index
            and end_word_index <= entity.end_word_index
        ):
            return True
    return False


def _keyword_fallback_mention(
    record: ASRConfidenceRecord,
    word_char_spans: list[WordCharSpan],
    start_word_index: int,
    end_word_index: int,
    *,
    entity_type: str,
    canonical: str,
) -> MedicalEntityMention:
    start_char, end_char = _char_range_for_word_range(
        word_char_spans,
        start_word_index,
        end_word_index,
    )
    text = " ".join(
        word.text for word in record.asr_words[start_word_index:end_word_index]
    )
    return MedicalEntityMention(
        entity_id=(
            f"keyword_{start_word_index}_{end_word_index}_"
            f"{safe_entity_id(canonical)}"
        ),
        text=text,
        entity_type=entity_type,
        start_char=start_char,
        end_char=end_char,
        start_word_index=start_word_index,
        end_word_index=end_word_index,
        confidence=1.0,
        source=KEYWORD_FALLBACK_SOURCE,
        metadata={
            "fallback_keyword": canonical,
            "fallback_method": "exact_normalized_keyword",
        },
    )


def _char_range_for_word_range(
    word_char_spans: list[WordCharSpan],
    start_word_index: int,
    end_word_index: int,
) -> tuple[int | None, int | None]:
    if not word_char_spans or start_word_index >= end_word_index:
        return None, None
    if start_word_index < 0 or end_word_index > len(word_char_spans):
        return None, None
    return (
        word_char_spans[start_word_index].start_char,
        word_char_spans[end_word_index - 1].end_char,
    )


def resolve_medical_entities(
    record: ASRConfidenceRecord,
    entities: list[MedicalEntityMention],
) -> list[MedicalEntityMention]:
    """把实体的字符范围/文本 mention 解析为 ASR word 范围。"""

    resolved: list[MedicalEntityMention] = []
    seen: set[tuple[int, int, str]] = set()
    for entity in entities:
        word_range = resolve_entity_word_range(record, entity)
        if word_range is None:
            continue
        start_word_index, end_word_index = word_range
        key = (
            start_word_index,
            end_word_index,
            normalize_text_for_match(entity.text),
        )
        if key in seen:
            continue
        seen.add(key)
        entity_id = entity.entity_id or f"medent_{len(resolved) + 1:03d}"
        resolved.append(
            entity.model_copy(
                update={
                    "entity_id": safe_entity_id(entity_id),
                    "start_word_index": start_word_index,
                    "end_word_index": end_word_index,
                }
            )
        )
    return sorted(
        resolved,
        key=lambda item: (item.start_word_index or 0, item.end_word_index or 0),
    )


def resolve_entity_word_range(
    record: ASRConfidenceRecord,
    entity: MedicalEntityMention,
) -> tuple[int, int] | None:
    """解析单个 entity 对应的 `[start_word_index, end_word_index)`。"""

    word_count = len(record.asr_words)
    if (
        entity.start_word_index is not None
        and entity.end_word_index is not None
        and 0 <= entity.start_word_index < entity.end_word_index <= word_count
    ):
        return entity.start_word_index, entity.end_word_index

    word_char_spans = word_char_spans_for_record(record)
    if entity.start_char is not None and entity.end_char is not None:
        overlapped = [
            word_span.word_index
            for word_span in word_char_spans
            if entity.start_char < word_span.end_char
            and word_span.start_char < entity.end_char
        ]
        if overlapped:
            return min(overlapped), max(overlapped) + 1

    char_range = find_entity_char_range(record.asr_transcript, entity.text)
    if char_range is not None:
        start_char, end_char = char_range
        overlapped = [
            word_span.word_index
            for word_span in word_char_spans
            if start_char < word_span.end_char and word_span.start_char < end_char
        ]
        if overlapped:
            return min(overlapped), max(overlapped) + 1

    token_range = find_entity_token_range(record.asr_words, entity.text)
    if token_range is not None:
        return token_range
    return None


def word_char_spans_for_record(record: ASRConfidenceRecord) -> list[WordCharSpan]:
    """返回 ASR words 在 transcript 中的字符范围。"""

    transcript = record.asr_transcript
    transcript_folded = transcript.casefold()
    spans: list[WordCharSpan] = []
    cursor = 0
    for word in record.asr_words:
        if word.char_start is not None and word.char_end is not None:
            spans.append(
                WordCharSpan(
                    word_index=word.word_index,
                    text=word.text,
                    start_char=word.char_start,
                    end_char=word.char_end,
                )
            )
            cursor = max(cursor, word.char_end)
            continue

        needle = word.text.casefold()
        start = transcript_folded.find(needle, cursor)
        if start < 0:
            start = transcript_folded.find(needle)
        if start < 0:
            start = min(cursor, len(transcript))
        end = min(start + len(word.text), len(transcript))
        spans.append(
            WordCharSpan(
                word_index=word.word_index,
                text=word.text,
                start_char=start,
                end_char=end,
            )
        )
        cursor = end
    return spans


def find_entity_char_range(transcript: str, entity_text: str) -> tuple[int, int] | None:
    """在 transcript 中查找 entity 文本的字符范围。"""

    normalized_entity = " ".join(entity_text.split())
    if not normalized_entity:
        return None
    start = transcript.casefold().find(normalized_entity.casefold())
    if start >= 0:
        return start, start + len(normalized_entity)
    return None


def find_entity_token_range(
    words: list[ASRWord],
    entity_text: str,
) -> tuple[int, int] | None:
    """用轻量 token exact match 查找 entity 的 word 范围。"""

    entity_tokens = [
        normalize_text_for_match(token)
        for token in entity_text.split()
        if normalize_text_for_match(token)
    ]
    if not entity_tokens:
        return None
    word_tokens = [normalize_text_for_match(word.text) for word in words]
    width = len(entity_tokens)
    for start in range(0, len(word_tokens) - width + 1):
        if word_tokens[start : start + width] == entity_tokens:
            return start, start + width
    return None


def merge_resolved_entity_groups(
    entities: Iterable[MedicalEntityMention],
) -> list[ResolvedEntityGroup]:
    """合并重叠实体，避免后续反馈回放时 span 重叠。"""

    sorted_entities = sorted(
        [
            entity
            for entity in entities
            if entity.start_word_index is not None and entity.end_word_index is not None
        ],
        key=lambda item: (item.start_word_index or 0, item.end_word_index or 0),
    )
    groups: list[ResolvedEntityGroup] = []
    active_start: int | None = None
    active_end: int | None = None
    active_ids: list[str] = []

    def close_active_group() -> None:
        nonlocal active_start, active_end, active_ids
        if active_start is None or active_end is None:
            return
        groups.append(
            ResolvedEntityGroup(
                start_word_index=active_start,
                end_word_index=active_end,
                entity_ids=tuple(active_ids),
            )
        )
        active_start = None
        active_end = None
        active_ids = []

    for entity in sorted_entities:
        start = entity.start_word_index or 0
        end = entity.end_word_index or 0
        entity_id = entity.entity_id or ""
        if active_start is None or active_end is None:
            active_start = start
            active_end = end
            active_ids = [entity_id]
            continue
        if start <= active_end:
            active_end = max(active_end, end)
            active_ids.append(entity_id)
        else:
            close_active_group()
            active_start = start
            active_end = end
            active_ids = [entity_id]

    close_active_group()
    return groups


def normalize_text_for_match(value: str) -> str:
    """轻量文本规整，用于匹配和去重。"""

    return re.sub(r"[^0-9a-zA-Z]+", "", value.casefold())


def safe_entity_id(value: str) -> str:
    """生成稳定、安全的实体 ID。"""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "medical_entity"


def _medical_entity_extraction_system_prompt() -> str:
    return (
        "你是医学信息抽取助手。你的任务是从 ASR 转写文本中识别医生在审阅转写时"
        "最需要核对的最小医学实体/医学专有术语。应抽取：疾病/诊断、症状体征、药物"
        "/剂量、检查检验、影像、操作/手术、解剖部位、医疗器械、医学缩写、重要"
        "临床属性。只抽取原文里的最小医学词或医学短语，不要把代词、助动词、连词、"
        "介词、问句模板或上下文动词包进实体。不要抽取普通人名、问候语、寒暄、普通"
        "动词、停用词或与医学无关的词组。尤其不要把 do、you、mean、your、and、"
        "what、kind、of、not、talk、about、going、there's、noticed、any、other "
        "这类普通词标成医学实体。示例：'your stools' 只抽取 'stools'；"
        "'do you mean diarrhea' 只抽取 'diarrhea'；'you mentioned the vomiting' "
        "只抽取 'vomiting'；'what kind of food' 不抽取任何实体。不要纠错、不要改写，"
        "只从原文抽取。返回严格 JSON，格式为："
        '{"entities":[{"text":"原文片段","entity_type":"disease|symptom|medication|'
        'procedure|lab_test|imaging|anatomy|medical_abbreviation|other_medical_term",'
        '"start_char":整数或null,"end_char":整数或null,"confidence":0到1或null}]}。'
        "如果没有医学实体，返回 {\"entities\":[]}。"
    )


def _build_medical_review_spans(
    words: list[ASRWord],
    groups: list[ResolvedEntityGroup],
    *,
    entities_by_id: dict[str, MedicalEntityMention],
    generated_by: str,
    thresholds: Any,
) -> list[UncertainSpan]:
    spans: list[UncertainSpan] = []
    for group in groups:
        span_words = words[group.start_word_index : group.end_word_index]
        confidences = [word.confidence for word in span_words if word.confidence is not None]
        mean_confidence = _aggregate_confidences(confidences, method="mean")
        min_confidence = _aggregate_confidences(confidences, method="min")
        level = confidence_level_for_score(
            min_confidence if min_confidence is not None else mean_confidence,
            thresholds,
        )
        if level == ConfidenceLevel.GREEN:
            continue
        start_sec, end_sec = _time_range_for_words(span_words)
        entities = [
            entities_by_id[entity_id].model_dump(mode="json")
            for entity_id in group.entity_ids
            if entity_id in entities_by_id
        ]
        spans.append(
            UncertainSpan(
                span_id=f"medspan_{len(spans) + 1:03d}",
                text=" ".join(word.text for word in span_words),
                start_word_index=group.start_word_index,
                end_word_index=group.end_word_index,
                start_sec=start_sec,
                end_sec=end_sec,
                mean_confidence=mean_confidence,
                min_confidence=min_confidence,
                confidence_level=level,
                trigger_reason=MEDICAL_ENTITY_TRIGGER_REASON,
                metadata={
                    "generated_by": generated_by,
                    "medical_entity_ids": list(group.entity_ids),
                    "medical_entities": entities,
                    "word_count": len(span_words),
                },
            )
        )
    return spans


def _annotate_word_for_medical_review(
    word: ASRWord,
    entity_ids: list[str],
) -> ASRWord:
    metadata = dict(word.metadata)
    review_metadata = dict(metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY) or {})
    is_medical = bool(entity_ids)
    review_metadata.update(
        {
            "is_medical_entity": is_medical,
            "entity_ids": entity_ids,
            "display_confidence_level": (
                word.confidence_level.value if is_medical else "neutral"
            ),
        }
    )
    metadata[MEDICAL_ENTITY_REVIEW_METADATA_KEY] = review_metadata
    return word.model_copy(update={"metadata": metadata})


def _entity_ids_by_word(
    entities: Iterable[MedicalEntityMention],
    word_count: int,
) -> dict[int, list[str]]:
    entity_ids_by_word: dict[int, list[str]] = {}
    for entity in entities:
        if entity.start_word_index is None or entity.end_word_index is None:
            continue
        entity_id = entity.entity_id or ""
        for word_index in range(entity.start_word_index, entity.end_word_index):
            if 0 <= word_index < word_count:
                entity_ids_by_word.setdefault(word_index, []).append(entity_id)
    return entity_ids_by_word


def _aggregate_confidences(values: list[float], *, method: str) -> float | None:
    if not values:
        return None
    if method == "min":
        return min(values)
    if method == "max":
        return max(values)
    return sum(values) / len(values)


def _time_range_for_words(words: list[ASRWord]) -> tuple[float | None, float | None]:
    starts = [word.start_sec for word in words if word.start_sec is not None]
    ends = [word.end_sec for word in words if word.end_sec is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _first_present_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _first_config_value(
    values: Mapping[str, str],
    keys: Iterable[str],
) -> str | None:
    for key in keys:
        value = values.get(key)
        if value is not None:
            stripped = str(value).strip()
            if stripped:
                return stripped
    return None


def _parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"} and value[-1:] == value[0]:
        value = value[1:-1]
        if raw_value.strip().startswith('"'):
            value = (
                value.replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        return value

    # 支持未加引号的尾部注释：KEY=value # comment
    hash_index = value.find(" #")
    if hash_index >= 0:
        value = value[:hash_index].rstrip()
    return value


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1:
        return None
    return number
