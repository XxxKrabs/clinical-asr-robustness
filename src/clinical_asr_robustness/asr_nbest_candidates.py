"""ASR sequence-level n-best 到 uncertain span 候选的抽取工具。

本模块对应 T029。它刻意不依赖 NeMo / torch：上游只要能提供
sequence-level beam/n-best 文本，本模块就能把它们写入项目统一的
`ASRConfidenceRecord.asr_alternatives`，并用序列差分把候选裁剪到连续
中/低置信度 `uncertain_spans`。
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceRecord,
    ASRWord,
    ConfidenceLevel,
)
from clinical_asr_robustness.medical_entity_review import (
    DEFAULT_API_KEY_ENV,
    endpoint_for_chat_completions,
    parse_json_object,
    resolve_llm_api_config,
)

T029_GENERATED_BY = "T029"
T039_GENERATED_BY = "T039"
T044_GENERATED_BY = "T044"
SEQUENCE_ALIGNMENT_METHOD = "sequence_nbest"
SPAN_ALIGNMENT_METHOD = "sequence_nbest_diff"
DEFAULT_NBEST_SOURCE = "nemo_beam"
MEDICAL_LEXICON_AUX_SOURCE = "medical_lexicon_aux_candidate"
MEDICAL_LEXICON_ALIGNMENT_METHOD = "medical_lexicon_fuzzy_match"
LLM_WORD_AUX_SOURCE = "llm_word_candidate"
LLM_WORD_ALIGNMENT_METHOD = "llm_target_word_context_lexicon"
MEDICAL_ENTITY_REVIEW_METADATA_KEY = "medical_entity_review"
MEDICAL_ENTITY_TRIGGER_REASON = "medical_entity_low_or_medium_confidence"
DEFAULT_AUX_MIN_SIMILARITY = 0.55
DEFAULT_LLM_WORD_CONTEXT_WINDOW = 5
DEFAULT_LLM_WORD_CANDIDATES = 3
DEFAULT_LLM_WORD_LEXICON_TERMS = 24

LLMWordCandidateGenerator = Callable[
    [list[dict[str, str]]],
    str | tuple[str, dict[str, Any]],
]

DEFAULT_MEDICAL_CANDIDATE_LEXICON: dict[str, tuple[str, ...]] = {
    "_global": (
        "abdominal pain",
        "asthma",
        "back ache",
        "back pain",
        "blood",
        "blood in stool",
        "chest pain",
        "cough",
        "diarrhea",
        "diarrhoea",
        "fever",
        "feverish",
        "feeling sick",
        "feeling weak",
        "fluid",
        "fluids",
        "inhaler",
        "inhalers",
        "loose stool",
        "loose stools",
        "medication",
        "medications",
        "nausea",
        "pain",
        "shaky",
        "shortness of breath",
        "stomach pain",
        "stool",
        "stools",
        "sweating",
        "temperature",
        "tummy",
        "tummy pain",
        "vomit",
        "vomiting",
        "weak",
    ),
    "symptom": (
        "abdominal pain",
        "blood",
        "blood in stool",
        "chest pain",
        "cough",
        "diarrhea",
        "diarrhoea",
        "fever",
        "feverish",
        "feeling sick",
        "feeling weak",
        "loose stool",
        "loose stools",
        "nausea",
        "pain",
        "shaky",
        "shortness of breath",
        "stomach pain",
        "sweating",
        "temperature",
        "tummy pain",
        "vomit",
        "vomiting",
        "weak",
    ),
    "sign": (
        "blood",
        "fever",
        "feverish",
        "shaky",
        "sweating",
        "temperature",
        "weak",
    ),
    "disease": (
        "asthma",
        "back pain",
        "diabetes",
        "flu",
        "gastroenteritis",
        "infection",
    ),
    "diagnosis": (
        "asthma",
        "back pain",
        "diabetes",
        "flu",
        "gastroenteritis",
        "infection",
    ),
    "medication": (
        "inhaler",
        "inhalers",
        "medication",
        "medications",
        "medicine",
        "medicines",
        "paracetamol",
        "salbutamol",
    ),
    "drug": (
        "inhaler",
        "inhalers",
        "medication",
        "medications",
        "medicine",
        "medicines",
        "paracetamol",
        "salbutamol",
    ),
    "device": ("inhaler", "inhalers"),
    "anatomy": ("abdomen", "chest", "stomach", "tummy"),
    "clinical_attribute": (
        "blood",
        "fluid",
        "fluids",
        "loose",
        "symptom",
        "symptoms",
        "temperature",
    ),
    "lab_test": ("blood test", "stool test", "urine test"),
    "imaging": ("ct", "mri", "ultrasound", "x ray", "x-ray"),
}


@dataclass
class SequenceNBestItem:
    """一条 sequence-level n-best/beam 候选。"""

    text: str
    rank: int
    score: float | None = None
    confidence: float | None = None
    source: str = DEFAULT_NBEST_SOURCE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpanAlignmentResult:
    """sequence 候选对齐到一个 uncertain span 后的裁剪结果。"""

    text: str
    alt_start_word_index: int
    alt_end_word_index: int
    changed: bool
    opcodes: tuple[tuple[str, int, int, int, int], ...]


@dataclass(frozen=True)
class MedicalLexiconCandidate:
    """词表/模糊匹配生成的医学实体辅助候选。"""

    text: str
    score: float
    source: str = MEDICAL_LEXICON_AUX_SOURCE
    entity_types: tuple[str, ...] = ()
    lexicon_categories: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMWordCandidatePrompt:
    """One prompt-ready request for a yellow/red target word."""

    task_id: str
    record_id: str | None
    sample_id: str
    span_id: str
    target_word_index: int
    target_word_text: str
    target_confidence: float | None
    target_confidence_level: str
    context: dict[str, Any]
    medical_lexicon_terms: tuple[str, ...]
    messages: tuple[dict[str, str], ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_candidate_text(text: str) -> str:
    """用于去重的轻量文本规范化。"""

    return " ".join(text.split()).casefold()


def align_sequence_candidate_to_span(
    *,
    base_words: list[str],
    candidate_words: list[str],
    span_start_word_index: int,
    span_end_word_index: int,
) -> SpanAlignmentResult | None:
    """把一个 sequence-level 候选裁剪成某个 base span 的候选文本。

    这里使用 `difflib.SequenceMatcher` 做词级 diff。策略偏保守：

    - equal 区间只截取与 span 重叠的部分；
    - replace/delete 只要和 span 相交，就认为这个 n-best 在该 span 有变化；
    - insert 若发生在 span 内部或边界，也纳入该 span 的候选；
    - 最终取所有命中的 candidate word 范围的最小闭包，保留局部上下文。
    """

    if span_start_word_index < 0 or span_end_word_index > len(base_words):
        raise ValueError("span 词范围越界")
    if span_end_word_index <= span_start_word_index:
        raise ValueError("span_end_word_index 必须大于 span_start_word_index")

    matcher = SequenceMatcher(
        None,
        base_words,
        candidate_words,
        autojunk=False,
    )
    candidate_ranges: list[tuple[int, int]] = []
    included_opcodes: list[tuple[str, int, int, int, int]] = []
    changed = False

    for tag, base_start, base_end, alt_start, alt_end in matcher.get_opcodes():
        if tag == "equal":
            overlap_start = max(base_start, span_start_word_index)
            overlap_end = min(base_end, span_end_word_index)
            if overlap_start < overlap_end:
                offset_start = overlap_start - base_start
                offset_end = overlap_end - base_start
                candidate_ranges.append((alt_start + offset_start, alt_start + offset_end))
                included_opcodes.append((tag, overlap_start, overlap_end, alt_start, alt_end))
            continue

        if tag == "insert":
            if span_start_word_index <= base_start <= span_end_word_index:
                changed = True
                if alt_start < alt_end:
                    candidate_ranges.append((alt_start, alt_end))
                    included_opcodes.append((tag, base_start, base_end, alt_start, alt_end))
            continue

        # replace / delete
        if _ranges_overlap(base_start, base_end, span_start_word_index, span_end_word_index):
            changed = True
            if alt_start < alt_end:
                candidate_ranges.append((alt_start, alt_end))
            included_opcodes.append((tag, base_start, base_end, alt_start, alt_end))

    if not candidate_ranges:
        return None

    candidate_start = min(start for start, _ in candidate_ranges)
    candidate_end = max(end for _, end in candidate_ranges)
    candidate_text = " ".join(candidate_words[candidate_start:candidate_end]).strip()
    if not candidate_text:
        return None

    base_span_text = " ".join(base_words[span_start_word_index:span_end_word_index])
    changed = changed or (
        normalize_candidate_text(candidate_text) != normalize_candidate_text(base_span_text)
    )

    return SpanAlignmentResult(
        text=candidate_text,
        alt_start_word_index=candidate_start,
        alt_end_word_index=candidate_end,
        changed=changed,
        opcodes=tuple(included_opcodes),
    )


def coerce_sequence_nbest_items(
    raw_items: Any,
    *,
    default_source: str = DEFAULT_NBEST_SOURCE,
    max_items: int | None = None,
) -> list[SequenceNBestItem]:
    """把常见 n-best 表达规整成 `SequenceNBestItem` 列表。

    支持的输入包括：

    - `["text 1", "text 2"]`
    - `[{"rank": 1, "text": "...", "score": -0.1}, ...]`
    - NeMo `beams` 风格的 `[("text", score), ...]`
    - NeMo `NBestHypotheses` 风格对象的 `n_best_hypotheses` 属性
    - 单个 Hypothesis 风格对象（含 `.text` / `.score`）
    """

    if raw_items is None:
        return []

    if isinstance(raw_items, dict):
        nested = _candidate_list_from_mapping(raw_items)
        if nested is not None:
            raw_items = nested
        else:
            raw_items = [raw_items]
    elif hasattr(raw_items, "n_best_hypotheses"):
        raw_items = raw_items.n_best_hypotheses
    elif isinstance(raw_items, ASRAlternative):
        raw_items = [raw_items]
    elif isinstance(raw_items, tuple) and raw_items and isinstance(raw_items[0], str):
        raw_items = [raw_items]
    elif hasattr(raw_items, "text"):
        raw_items = [raw_items]
    elif isinstance(raw_items, str) or not _is_non_string_iterable(raw_items):
        raw_items = [raw_items]

    items: list[SequenceNBestItem] = []
    for fallback_rank, item in enumerate(raw_items or [], start=1):
        coerced = _coerce_one_nbest_item(
            item,
            fallback_rank=fallback_rank,
            default_source=default_source,
        )
        if coerced is not None:
            items.append(coerced)

    return normalize_sequence_nbest_items(items, max_items=max_items)


def normalize_sequence_nbest_items(
    items: Iterable[SequenceNBestItem],
    *,
    max_items: int | None = None,
) -> list[SequenceNBestItem]:
    """按 rank 排序、去重，并把输出 rank 规整为 1..N。"""

    if max_items is not None and max_items <= 0:
        raise ValueError("max_items 必须大于 0")

    normalized: list[SequenceNBestItem] = []
    seen_texts: set[str] = set()
    sorted_items = sorted(enumerate(items), key=lambda pair: (pair[1].rank, pair[0]))
    for _, item in sorted_items:
        text = " ".join(item.text.split())
        if not text:
            continue
        normalized_text = normalize_candidate_text(text)
        if normalized_text in seen_texts:
            continue
        seen_texts.add(normalized_text)
        metadata = dict(item.metadata)
        metadata.setdefault("original_rank", item.rank)
        normalized.append(
            replace(
                item,
                text=text,
                rank=len(normalized) + 1,
                metadata=metadata,
            )
        )
        if max_items is not None and len(normalized) >= max_items:
            break
    return normalized



def build_llm_word_candidate_prompt_records(
    record: ASRConfidenceRecord,
    *,
    medical_candidate_lexicon: dict[str, Iterable[str]] | None = None,
    context_window_words: int = DEFAULT_LLM_WORD_CONTEXT_WINDOW,
    max_lexicon_terms: int = DEFAULT_LLM_WORD_LEXICON_TERMS,
) -> list[LLMWordCandidatePrompt]:
    """Build prompt-ready LLM candidate requests for yellow/red words only."""

    if context_window_words < 0:
        raise ValueError("context_window_words must be greater than or equal to 0")
    if max_lexicon_terms <= 0:
        raise ValueError("max_lexicon_terms must be greater than 0")

    lexicon = normalize_medical_candidate_lexicon(medical_candidate_lexicon)
    prompts: list[LLMWordCandidatePrompt] = []
    for span in record.uncertain_spans:
        entity_types = entity_types_for_span(record, span)
        for word in llm_candidate_target_words_for_span(record, span):
            context = build_word_candidate_context(
                record,
                target_word_index=word.word_index,
                context_window_words=context_window_words,
            )
            lexicon_terms = medical_lexicon_reference_terms_for_word(
                word.text,
                entity_types=entity_types,
                lexicon=lexicon,
                max_terms=max_lexicon_terms,
            )
            messages = build_llm_word_candidate_messages(
                target_word=word,
                span_text=span.text,
                context=context,
                medical_lexicon_terms=lexicon_terms,
            )
            level = _confidence_level_value(word.confidence_level)
            prompts.append(
                LLMWordCandidatePrompt(
                    task_id=_safe_id(
                        f"llm_word_candidate_{record.sample_id}_{span.span_id}_{word.word_index}"
                    ),
                    record_id=record.record_id,
                    sample_id=record.sample_id,
                    span_id=span.span_id,
                    target_word_index=word.word_index,
                    target_word_text=word.text,
                    target_confidence=word.confidence,
                    target_confidence_level=level,
                    context=context,
                    medical_lexicon_terms=tuple(lexicon_terms),
                    messages=tuple(messages),
                    metadata={
                        "generated_by": T044_GENERATED_BY,
                        "source": LLM_WORD_AUX_SOURCE,
                        "alignment_method": LLM_WORD_ALIGNMENT_METHOD,
                        "candidate_scope": "word",
                        "entity_types": list(entity_types),
                        "reference_used": False,
                        "research_use_only": True,
                    },
                )
            )
    return prompts


def llm_candidate_target_words_for_span(record: ASRConfidenceRecord, span: Any) -> list[ASRWord]:
    """Return only yellow/red words inside a review span."""

    target_levels = {ConfidenceLevel.YELLOW, ConfidenceLevel.RED}
    words: list[ASRWord] = []
    for word in record.asr_words[span.start_word_index : span.end_word_index]:
        if word.confidence_level in target_levels:
            words.append(word)
    return words


def build_word_candidate_context(
    record: ASRConfidenceRecord,
    *,
    target_word_index: int,
    context_window_words: int = DEFAULT_LLM_WORD_CONTEXT_WINDOW,
) -> dict[str, Any]:
    """Build a small local context window around one ASR word."""

    if target_word_index < 0 or target_word_index >= len(record.asr_words):
        raise ValueError("target_word_index is out of range")
    if context_window_words < 0:
        raise ValueError("context_window_words must be greater than or equal to 0")

    words = record.asr_words
    target_word = words[target_word_index]
    left_start = max(0, target_word_index - context_window_words)
    right_end = min(len(words), target_word_index + context_window_words + 1)
    left_words = words[left_start:target_word_index]
    right_words = words[target_word_index + 1 : right_end]
    window_words = words[left_start:right_end]
    return {
        "left_text": " ".join(word.text for word in left_words),
        "target_text": target_word.text,
        "right_text": " ".join(word.text for word in right_words),
        "window_text": " ".join(word.text for word in window_words),
        "target_word_index": target_word.word_index,
        "window_start_word_index": left_start,
        "window_end_word_index": right_end,
    }


def medical_lexicon_reference_terms_for_word(
    target_text: str,
    *,
    entity_types: Iterable[str],
    lexicon: dict[str, Iterable[str]],
    max_terms: int = DEFAULT_LLM_WORD_LEXICON_TERMS,
) -> list[str]:
    """Select a compact medical lexicon slice as LLM reference context."""

    if max_terms <= 0:
        raise ValueError("max_terms must be greater than 0")

    categories = ["_global", *(normalize_lexicon_category(item) for item in entity_types)]
    term_categories: dict[str, set[str]] = {}
    for category in categories:
        for term in lexicon.get(category, ()):
            clean = " ".join(str(term).split())
            if not clean:
                continue
            term_categories.setdefault(clean, set()).add(category)

    scored_terms = []
    for term, categories_for_term in term_categories.items():
        score = candidate_similarity(target_text, term)
        entity_category_hit = any(category != "_global" for category in categories_for_term)
        scored_terms.append(
            (score, not entity_category_hit, len(term.split()), term.casefold(), term)
        )

    scored_terms.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return [item[-1] for item in scored_terms[:max_terms]]


def build_llm_word_candidate_messages(
    *,
    target_word: ASRWord,
    span_text: str,
    context: dict[str, Any],
    medical_lexicon_terms: Iterable[str],
) -> list[dict[str, str]]:
    """Build the LLM prompt for one yellow/red ASR word."""

    payload = {
        "task": "generate_candidate_replacements_for_one_uncertain_asr_word",
        "target_word": {
            "word_index": target_word.word_index,
            "text": target_word.text,
            "confidence": target_word.confidence,
            "confidence_level": _confidence_level_value(target_word.confidence_level),
        },
        "review_span_text": span_text,
        "local_context": context,
        "medical_lexicon_reference": list(medical_lexicon_terms),
        "requirements": [
            "Return about 3 candidate replacement words or short medical terms.",
            "Use the target word, local context, and medical lexicon as references.",
            "Do not rewrite the whole transcript.",
            "Do not provide medical advice; this is only ASR review support.",
            "Return strict JSON only: {\"candidates\": [\"...\", \"...\"]}.",
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You generate candidate replacements for uncertain ASR words in "
                "clinical conversation transcripts. Return strict JSON only."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def generate_llm_word_candidate_content_with_api(
    messages: list[dict[str, str]],
    *,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    base_url: str | None = None,
    model_name: str | None = None,
    dotenv_path: str | Path | None = None,
    timeout_sec: float = 60.0,
    max_tokens: int = 500,
) -> tuple[str, dict[str, Any]]:
    """Call an OpenAI-compatible Chat Completions API for word candidates."""

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
            f"LLM word candidate API request failed: HTTP {exc.code}; response: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM word candidate API request failed: {exc.reason}") from exc

    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM API response is missing choices[0].message.content") from exc
    return str(content), {
        "model_name": config.model_name,
        "base_url": config.base_url,
        "api_key_env": config.api_key_env,
        "dotenv_path": config.dotenv_path,
    }


def parse_llm_word_candidate_response(
    content: str,
    *,
    target_word_text: str,
    max_candidates: int = DEFAULT_LLM_WORD_CANDIDATES,
    seen_texts: set[str] | None = None,
) -> list[str]:
    """Parse and deduplicate LLM candidate words from JSON output."""

    if max_candidates <= 0:
        raise ValueError("max_candidates must be greater than 0")

    payload = parse_json_object(content)
    if isinstance(payload, dict):
        raw_candidates = (
            payload.get("candidates")
            or payload.get("candidate_words")
            or payload.get("alternatives")
            or []
        )
    elif isinstance(payload, list):
        raw_candidates = payload
    else:
        raise ValueError("LLM word candidate output must be a JSON object or list")

    if not isinstance(raw_candidates, list):
        raise ValueError("LLM word candidate output candidates must be a list")

    seen = set(seen_texts or set())
    seen.add(normalize_candidate_text(target_word_text))
    candidates: list[str] = []
    for item in raw_candidates:
        if isinstance(item, dict):
            text = _first_present_string(item, "text", "candidate", "word", "replacement")
        else:
            text = str(item)
        if not text:
            continue
        clean = " ".join(text.split())
        if not clean:
            continue
        key = normalize_candidate_text(clean)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(clean)
        if len(candidates) >= max_candidates:
            break
    return candidates


def llm_prompt_to_json_record(prompt: LLMWordCandidatePrompt) -> dict[str, Any]:
    """Serialize a prompt-ready LLM word candidate task to JSON."""

    return {
        "task_id": prompt.task_id,
        "record_id": prompt.record_id,
        "sample_id": prompt.sample_id,
        "span_id": prompt.span_id,
        "target_word_index": prompt.target_word_index,
        "target_word_text": prompt.target_word_text,
        "target_confidence": prompt.target_confidence,
        "target_confidence_level": prompt.target_confidence_level,
        "context": prompt.context,
        "medical_lexicon_terms": list(prompt.medical_lexicon_terms),
        "messages": list(prompt.messages),
        "metadata": prompt.metadata,
    }


def _confidence_level_value(level: Any) -> str:
    return str(getattr(level, "value", level))


def attach_nbest_candidates_to_record(
    record: ASRConfidenceRecord,
    nbest_items: Any | None = None,
    *,
    max_sequence_alternatives: int = 5,
    max_span_alternatives: int = 3,
    default_source: str = DEFAULT_NBEST_SOURCE,
    include_unchanged_span_candidates: bool = False,
    enable_auxiliary_medical_candidates: bool = False,
    medical_candidate_lexicon: dict[str, Iterable[str]] | None = None,
    max_auxiliary_span_alternatives: int | None = None,
    aux_min_similarity: float = DEFAULT_AUX_MIN_SIMILARITY,
    enable_llm_word_candidates: bool = False,
    llm_word_candidate_generator: LLMWordCandidateGenerator | None = None,
    max_llm_word_candidates: int = DEFAULT_LLM_WORD_CANDIDATES,
    llm_word_context_window: int = DEFAULT_LLM_WORD_CONTEXT_WINDOW,
    max_llm_lexicon_terms: int = DEFAULT_LLM_WORD_LEXICON_TERMS,
) -> ASRConfidenceRecord:
    """Attach sequence/span alternatives to one ASR confidence record.

    T029 keeps ASR-native sequence n-best candidates and derives span candidates
    with word-level diff. When T039 auxiliary candidates are enabled, this
    function only adds lexicon/fuzzy fallback candidates to medical entity
    spans that have no ASR-native span candidate, and marks their source
    explicitly.
    """

    if max_sequence_alternatives <= 0:
        raise ValueError("max_sequence_alternatives must be greater than 0")
    if max_span_alternatives <= 0:
        raise ValueError("max_span_alternatives must be greater than 0")
    if max_auxiliary_span_alternatives is not None and max_auxiliary_span_alternatives <= 0:
        raise ValueError("max_auxiliary_span_alternatives must be greater than 0")
    if not 0.0 <= aux_min_similarity <= 1.0:
        raise ValueError("aux_min_similarity must be between 0 and 1")
    if max_llm_word_candidates <= 0:
        raise ValueError("max_llm_word_candidates must be greater than 0")
    if llm_word_context_window < 0:
        raise ValueError("llm_word_context_window must be greater than or equal to 0")
    if max_llm_lexicon_terms <= 0:
        raise ValueError("max_llm_lexicon_terms must be greater than 0")

    existing_to_keep = [
        alternative
        for alternative in record.asr_alternatives
        if alternative.metadata.get("generated_by")
        not in {T029_GENERATED_BY, T039_GENERATED_BY, T044_GENERATED_BY}
    ]
    used_ids = {alternative.alternative_id for alternative in existing_to_keep}
    existing_to_keep_ids = {alternative.alternative_id for alternative in existing_to_keep}
    normalized_medical_lexicon = normalize_medical_candidate_lexicon(
        medical_candidate_lexicon
    )
    aux_limit = max_auxiliary_span_alternatives or max_span_alternatives
    llm_prompts_by_span: dict[str, list[LLMWordCandidatePrompt]] = {}
    if enable_llm_word_candidates:
        for prompt in build_llm_word_candidate_prompt_records(
            record,
            medical_candidate_lexicon=normalized_medical_lexicon,
            context_window_words=llm_word_context_window,
            max_lexicon_terms=max_llm_lexicon_terms,
        ):
            llm_prompts_by_span.setdefault(prompt.span_id, []).append(prompt)

    sequence_items = coerce_sequence_nbest_items(
        nbest_items,
        default_source=default_source,
        max_items=max_sequence_alternatives,
    )
    if not sequence_items:
        sequence_items = _sequence_items_from_existing_alternatives(
            record.asr_alternatives,
            max_items=max_sequence_alternatives,
        )

    alternatives = list(existing_to_keep)
    sequence_alternatives: list[ASRAlternative] = []
    for item in sequence_items:
        alternative_id = _unique_id(f"alt_seq_rank_{item.rank:03d}", used_ids)
        alternative = ASRAlternative(
            alternative_id=alternative_id,
            scope=AlternativeScope.SEQUENCE,
            rank=item.rank,
            text=item.text,
            score=item.score,
            confidence=item.confidence,
            source=item.source,
            alignment_method=SEQUENCE_ALIGNMENT_METHOD,
            metadata={
                **item.metadata,
                "generated_by": T029_GENERATED_BY,
                "candidate_type": "sequence_nbest",
            },
        )
        alternatives.append(alternative)
        sequence_alternatives.append(alternative)

    base_words = record.asr_transcript.split()
    updated_spans = []
    span_alternative_count = 0
    auxiliary_span_alternative_count = 0
    medical_spans_seen = 0
    medical_spans_with_asr_span_candidates = 0
    medical_spans_with_auxiliary_candidates = 0
    llm_eligible_word_count = 0
    llm_api_call_count = 0
    llm_words_with_candidates = 0
    llm_word_alternative_count = 0

    for span in record.uncertain_spans:
        kept_alternative_ids = [
            alternative_id
            for alternative_id in span.alternative_ids
            if alternative_id in existing_to_keep_ids
        ]
        span_alternative_ids = list(kept_alternative_ids)
        seen_span_texts = {normalize_candidate_text(span.text)}
        is_medical_span = is_medical_entity_review_span(record, span)
        if is_medical_span:
            medical_spans_seen += 1

        for sequence_alternative in sequence_alternatives:
            if len(span_alternative_ids) - len(kept_alternative_ids) >= max_span_alternatives:
                break

            alignment = align_sequence_candidate_to_span(
                base_words=base_words,
                candidate_words=sequence_alternative.text.split(),
                span_start_word_index=span.start_word_index,
                span_end_word_index=span.end_word_index,
            )
            if alignment is None:
                continue
            normalized_text = normalize_candidate_text(alignment.text)
            if not include_unchanged_span_candidates and not alignment.changed:
                continue
            if normalized_text in seen_span_texts:
                continue

            seen_span_texts.add(normalized_text)
            rank = len(span_alternative_ids) - len(kept_alternative_ids) + 1
            alternative_id = _unique_id(
                f"alt_{span.span_id}_rank_{rank:03d}",
                used_ids,
            )
            alternatives.append(
                ASRAlternative(
                    alternative_id=alternative_id,
                    scope=AlternativeScope.SPAN,
                    rank=rank,
                    text=alignment.text,
                    span_id=span.span_id,
                    start_word_index=span.start_word_index,
                    end_word_index=span.end_word_index,
                    score=sequence_alternative.score,
                    confidence=sequence_alternative.confidence,
                    source=sequence_alternative.source,
                    alignment_method=SPAN_ALIGNMENT_METHOD,
                    metadata={
                        "generated_by": T029_GENERATED_BY,
                        "candidate_type": "span_from_sequence_nbest",
                        "sequence_alternative_id": sequence_alternative.alternative_id,
                        "sequence_rank": sequence_alternative.rank,
                        "base_span_text": span.text,
                        "sequence_alt_word_range": [
                            alignment.alt_start_word_index,
                            alignment.alt_end_word_index,
                        ],
                        "diff_opcodes": [list(opcode) for opcode in alignment.opcodes],
                    },
                )
            )
            span_alternative_ids.append(alternative_id)
            span_alternative_count += 1

        asr_span_candidates_added = len(span_alternative_ids) - len(kept_alternative_ids)
        if is_medical_span and asr_span_candidates_added > 0:
            medical_spans_with_asr_span_candidates += 1

        llm_word_candidates_added = 0
        llm_prompt_records = llm_prompts_by_span.get(span.span_id, [])
        llm_eligible_word_count += len(llm_prompt_records)
        if enable_llm_word_candidates and llm_word_candidate_generator is not None:
            for prompt_record in llm_prompt_records:
                raw_response = llm_word_candidate_generator(list(prompt_record.messages))
                llm_api_call_count += 1
                if isinstance(raw_response, tuple):
                    llm_content, llm_response_metadata = raw_response
                else:
                    llm_content = raw_response
                    llm_response_metadata = {}
                candidate_texts = parse_llm_word_candidate_response(
                    llm_content,
                    target_word_text=prompt_record.target_word_text,
                    max_candidates=max_llm_word_candidates,
                    seen_texts=seen_span_texts,
                )
                target_word_candidates_added = 0
                for candidate_text in candidate_texts:
                    rank = len(span_alternative_ids) + 1
                    alternative_id = _unique_id(
                        (
                            f"alt_{span.span_id}_word_{prompt_record.target_word_index}"
                            f"_llm_rank_{rank:03d}"
                        ),
                        used_ids,
                    )
                    alternatives.append(
                        ASRAlternative(
                            alternative_id=alternative_id,
                            scope=AlternativeScope.WORD,
                            rank=rank,
                            text=candidate_text,
                            span_id=span.span_id,
                            start_word_index=prompt_record.target_word_index,
                            end_word_index=prompt_record.target_word_index + 1,
                            score=None,
                            confidence=None,
                            source=LLM_WORD_AUX_SOURCE,
                            alignment_method=LLM_WORD_ALIGNMENT_METHOD,
                            metadata={
                                **prompt_record.metadata,
                                "candidate_type": "llm_word_replacement",
                                "base_span_text": span.text,
                                "target_word_index": prompt_record.target_word_index,
                                "target_word_text": prompt_record.target_word_text,
                                "target_confidence": prompt_record.target_confidence,
                                "target_confidence_level": (
                                    prompt_record.target_confidence_level
                                ),
                                "local_context": prompt_record.context,
                                "medical_lexicon_terms": list(
                                    prompt_record.medical_lexicon_terms
                                ),
                                "llm_response_metadata": llm_response_metadata,
                                "asr_native_candidate": False,
                                "reference_used": False,
                                "note": (
                                    "T044 candidate generated by an LLM for one "
                                    "yellow/red ASR word using local context and a "
                                    "medical lexicon reference; not an ASR-native "
                                    "n-best/top-k hypothesis."
                                ),
                            },
                        )
                    )
                    span_alternative_ids.append(alternative_id)
                    seen_span_texts.add(normalize_candidate_text(candidate_text))
                    target_word_candidates_added += 1
                    llm_word_candidates_added += 1
                    llm_word_alternative_count += 1
                if target_word_candidates_added:
                    llm_words_with_candidates += 1

        auxiliary_candidates_added = 0
        if (
            enable_auxiliary_medical_candidates
            and is_medical_span
            and not span_alternative_ids
        ):
            entity_types = entity_types_for_span(record, span)
            aux_candidates = generate_medical_lexicon_candidates_for_span(
                span.text,
                entity_types=entity_types,
                lexicon=normalized_medical_lexicon,
                max_candidates=aux_limit,
                min_similarity=aux_min_similarity,
                seen_texts=seen_span_texts,
            )
            for candidate in aux_candidates:
                rank = len(span_alternative_ids) + 1
                alternative_id = _unique_id(
                    f"alt_{span.span_id}_aux_rank_{rank:03d}",
                    used_ids,
                )
                alternatives.append(
                    ASRAlternative(
                        alternative_id=alternative_id,
                        scope=AlternativeScope.SPAN,
                        rank=rank,
                        text=candidate.text,
                        span_id=span.span_id,
                        start_word_index=span.start_word_index,
                        end_word_index=span.end_word_index,
                        score=candidate.score,
                        confidence=None,
                        source=candidate.source,
                        alignment_method=MEDICAL_LEXICON_ALIGNMENT_METHOD,
                        metadata={
                            **candidate.metadata,
                            "generated_by": T039_GENERATED_BY,
                            "candidate_type": "auxiliary_medical_lexicon",
                            "base_span_text": span.text,
                            "entity_types": list(candidate.entity_types),
                            "lexicon_categories": list(candidate.lexicon_categories),
                            "similarity": candidate.score,
                            "asr_native_candidate": False,
                            "reference_used": False,
                            "note": (
                                "T039 fallback candidate generated from project "
                                "medical lexicon and fuzzy string matching; not an "
                                "ASR-native n-best/top-k hypothesis."
                            ),
                        },
                    )
                )
                span_alternative_ids.append(alternative_id)
                seen_span_texts.add(normalize_candidate_text(candidate.text))
                auxiliary_candidates_added += 1
                auxiliary_span_alternative_count += 1
            if auxiliary_candidates_added:
                medical_spans_with_auxiliary_candidates += 1

        span_metadata = dict(span.metadata)
        span_metadata["t029"] = {
            "alignment_method": SPAN_ALIGNMENT_METHOD,
            "sequence_alternatives_considered": len(sequence_alternatives),
            "span_alternatives_added": asr_span_candidates_added,
        }
        span_metadata["t039_auxiliary_candidates"] = {
            "enabled": enable_auxiliary_medical_candidates,
            "medical_entity_span": is_medical_span,
            "source": MEDICAL_LEXICON_AUX_SOURCE,
            "alignment_method": MEDICAL_LEXICON_ALIGNMENT_METHOD,
            "auxiliary_alternatives_added": auxiliary_candidates_added,
            "min_similarity": aux_min_similarity,
            "max_auxiliary_span_alternatives": aux_limit,
            "reference_used": False,
        }
        span_metadata["t044_llm_word_candidates"] = {
            "enabled": enable_llm_word_candidates,
            "source": LLM_WORD_AUX_SOURCE,
            "alignment_method": LLM_WORD_ALIGNMENT_METHOD,
            "eligible_yellow_red_words": len(llm_prompt_records),
            "llm_api_calls": (
                len(llm_prompt_records)
                if enable_llm_word_candidates and llm_word_candidate_generator is not None
                else 0
            ),
            "word_alternatives_added": llm_word_candidates_added,
            "max_llm_word_candidates": max_llm_word_candidates,
            "context_window_words": llm_word_context_window,
            "max_lexicon_terms": max_llm_lexicon_terms,
            "reference_used": False,
        }
        updated_spans.append(
            span.model_copy(
                update={
                    "alternative_ids": span_alternative_ids,
                    "metadata": span_metadata,
                }
            )
        )

    metadata = dict(record.metadata)
    metadata["t029_nbest_candidate_extraction"] = {
        "generated_by": T029_GENERATED_BY,
        "sequence_alignment_method": SEQUENCE_ALIGNMENT_METHOD,
        "span_alignment_method": SPAN_ALIGNMENT_METHOD,
        "sequence_alternatives_added": len(sequence_alternatives),
        "span_alternatives_added": span_alternative_count,
        "max_sequence_alternatives": max_sequence_alternatives,
        "max_span_alternatives": max_span_alternatives,
        "include_unchanged_span_candidates": include_unchanged_span_candidates,
        "note": (
            "V0 uses sequence-level n-best hypotheses and word-level diff to derive "
            "span candidates for continuous low/medium-confidence uncertain spans."
        ),
    }
    metadata["t039_auxiliary_candidate_generation"] = {
        "generated_by": T039_GENERATED_BY,
        "enabled": enable_auxiliary_medical_candidates,
        "source": MEDICAL_LEXICON_AUX_SOURCE,
        "alignment_method": MEDICAL_LEXICON_ALIGNMENT_METHOD,
        "medical_entity_spans_seen": medical_spans_seen,
        "medical_entity_spans_with_asr_span_candidates": (
            medical_spans_with_asr_span_candidates
        ),
        "medical_entity_spans_with_auxiliary_candidates": (
            medical_spans_with_auxiliary_candidates
        ),
        "auxiliary_span_alternatives_added": auxiliary_span_alternative_count,
        "max_auxiliary_span_alternatives": aux_limit,
        "min_similarity": aux_min_similarity,
        "lexicon_categories": sorted(normalized_medical_lexicon),
        "reference_used": False,
        "note": (
            "Auxiliary candidates are only added to medical entity review spans "
            "with no span-level ASR candidate; source must not be mixed with "
            "ASR-native n-best/top-k hypotheses."
        ),
    }
    metadata["t044_llm_word_candidate_generation"] = {
        "generated_by": T044_GENERATED_BY,
        "enabled": enable_llm_word_candidates,
        "source": LLM_WORD_AUX_SOURCE,
        "alignment_method": LLM_WORD_ALIGNMENT_METHOD,
        "eligible_yellow_red_words": llm_eligible_word_count,
        "llm_api_calls": llm_api_call_count,
        "words_with_llm_candidates": llm_words_with_candidates,
        "word_alternatives_added": llm_word_alternative_count,
        "max_llm_word_candidates": max_llm_word_candidates,
        "context_window_words": llm_word_context_window,
        "max_lexicon_terms": max_llm_lexicon_terms,
        "reference_used": False,
        "note": (
            "T044 generates candidate replacements only for yellow/red ASR words. "
            "Each LLM prompt includes the target word, a local context window, and "
            "a compact medical lexicon reference. These candidates are auxiliary "
            "and must not be mixed with ASR-native n-best/top-k hypotheses."
        ),
    }

    payload = record.model_dump(mode="json")
    payload["asr_alternatives"] = [
        alternative.model_dump(mode="json") for alternative in alternatives
    ]
    payload["uncertain_spans"] = [span.model_dump(mode="json") for span in updated_spans]
    payload["metadata"] = metadata
    return ASRConfidenceRecord.model_validate(payload)



def normalize_medical_candidate_lexicon(
    lexicon: dict[str, Iterable[str]] | None = None,
    *,
    include_default: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Normalize project medical candidate lexicon by category."""

    merged: dict[str, list[str]] = {}
    if include_default:
        for category, terms in DEFAULT_MEDICAL_CANDIDATE_LEXICON.items():
            merged.setdefault(category, []).extend(terms)
    if lexicon:
        for category, terms in lexicon.items():
            normalized_category = normalize_lexicon_category(category)
            merged.setdefault(normalized_category, []).extend(str(term) for term in terms)

    normalized: dict[str, tuple[str, ...]] = {}
    for category, terms in merged.items():
        seen: set[str] = set()
        clean_terms: list[str] = []
        for term in terms:
            clean = " ".join(str(term).split())
            if not clean:
                continue
            key = normalize_candidate_text(clean)
            if key in seen:
                continue
            seen.add(key)
            clean_terms.append(clean)
        normalized[category] = tuple(sorted(clean_terms, key=lambda item: item.casefold()))
    return normalized



def load_medical_candidate_lexicon(
    path: str | Path,
    *,
    include_default: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Load a JSON medical candidate lexicon and merge it with defaults."""

    lexicon_path = Path(path)
    with lexicon_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("medical candidate lexicon JSON must be an object")
    raw_terms = payload.get("terms", payload)
    if not isinstance(raw_terms, dict):
        raise ValueError("medical candidate lexicon JSON terms must be an object")
    coerced = {
        str(category): coerce_lexicon_terms(terms)
        for category, terms in raw_terms.items()
    }
    return normalize_medical_candidate_lexicon(
        coerced,
        include_default=include_default,
    )



def coerce_lexicon_terms(raw_terms: Any) -> list[str]:
    """Coerce string lists or `{text/term, aliases}` lexicon items."""

    if raw_terms is None:
        return []
    if isinstance(raw_terms, str):
        return [raw_terms]
    if not _is_non_string_iterable(raw_terms):
        return [str(raw_terms)]

    terms: list[str] = []
    for item in raw_terms:
        if isinstance(item, str):
            terms.append(item)
            continue
        if isinstance(item, dict):
            primary = _first_present_string(item, "text", "term", "canonical")
            if primary:
                terms.append(primary)
            aliases = item.get("aliases")
            if _is_non_string_iterable(aliases):
                terms.extend(str(alias) for alias in aliases)
            continue
        terms.append(str(item))
    return terms



def is_medical_entity_review_span(record: ASRConfidenceRecord, span: Any) -> bool:
    """Return whether a span belongs to T038 medical entity review scope."""

    if span.trigger_reason == MEDICAL_ENTITY_TRIGGER_REASON:
        return True
    if span.metadata.get("medical_entity_ids") or span.metadata.get("medical_entities"):
        return True
    for word in record.asr_words[span.start_word_index : span.end_word_index]:
        review_metadata = word.metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY, {})
        if review_metadata.get("is_medical_entity"):
            return True
    return False



def entity_types_for_span(record: ASRConfidenceRecord, span: Any) -> tuple[str, ...]:
    """Extract medical entity types from span metadata and word metadata."""

    entity_types: list[str] = []
    for entity in span.metadata.get("medical_entities") or []:
        if isinstance(entity, dict):
            entity_type = entity.get("entity_type")
            if entity_type:
                entity_types.append(str(entity_type))
    for word in record.asr_words[span.start_word_index : span.end_word_index]:
        review_metadata = word.metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY, {})
        for entity in review_metadata.get("medical_entities") or []:
            if isinstance(entity, dict) and entity.get("entity_type"):
                entity_types.append(str(entity["entity_type"]))
    normalized = []
    seen = set()
    for entity_type in entity_types:
        category = normalize_lexicon_category(entity_type)
        if category not in seen:
            seen.add(category)
            normalized.append(category)
    return tuple(normalized)



def generate_medical_lexicon_candidates_for_span(
    span_text: str,
    *,
    entity_types: Iterable[str],
    lexicon: dict[str, Iterable[str]],
    max_candidates: int,
    min_similarity: float = DEFAULT_AUX_MIN_SIMILARITY,
    seen_texts: set[str] | None = None,
) -> list[MedicalLexiconCandidate]:
    """Generate lexicon/fuzzy fallback candidates for one medical entity span."""

    if max_candidates <= 0:
        raise ValueError("max_candidates must be greater than 0")
    seen = set(seen_texts or set())
    categories = ["_global", *(normalize_lexicon_category(item) for item in entity_types)]
    candidate_categories: dict[str, set[str]] = {}
    for category in categories:
        for term in lexicon.get(category, ()):
            normalized_text = normalize_candidate_text(term)
            if not normalized_text or normalized_text in seen:
                continue
            candidate_categories.setdefault(term, set()).add(category)

    candidates: list[MedicalLexiconCandidate] = []
    normalized_entity_types = tuple(
        dict.fromkeys(normalize_lexicon_category(item) for item in entity_types)
    )
    for term, term_categories in candidate_categories.items():
        score = candidate_similarity(span_text, term)
        if score < min_similarity:
            continue
        candidates.append(
            MedicalLexiconCandidate(
                text=term,
                score=score,
                entity_types=normalized_entity_types,
                lexicon_categories=tuple(sorted(term_categories)),
                metadata={"similarity_method": "char_ratio_token_overlap"},
            )
        )

    return sorted(
        candidates,
        key=lambda item: (-item.score, len(item.text.split()), item.text.casefold()),
    )[:max_candidates]



def candidate_similarity(left: str, right: str) -> float:
    """Combine character similarity and token overlap into a light fuzzy score."""

    left_key = normalize_for_fuzzy_match(left)
    right_key = normalize_for_fuzzy_match(right)
    if not left_key or not right_key:
        return 0.0
    char_ratio = SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    token_overlap = (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens and right_tokens
        else 0.0
    )
    compact_ratio = SequenceMatcher(
        None,
        left_key.replace(" ", ""),
        right_key.replace(" ", ""),
        autojunk=False,
    ).ratio()
    return max(char_ratio, compact_ratio, token_overlap)



def normalize_for_fuzzy_match(value: str) -> str:
    """Normalize text for fuzzy matching while preserving token boundaries."""

    return " ".join(
        match.group(0).casefold()
        for match in re.finditer(r"[a-zA-Z]+|\d+", value)
    )



def normalize_lexicon_category(value: str) -> str:
    """Normalize an entity type or lexicon category into a lookup key."""

    normalized = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value).casefold()).strip("_")
    return normalized or "other_medical_term"


def load_nbest_jsonl(
    path: str | Path,
    *,
    default_source: str = DEFAULT_NBEST_SOURCE,
) -> dict[str, list[SequenceNBestItem]]:
    """读取 sequence n-best JSONL，并按 `record_id:` / `sample_id:` 建索引。

    支持两类 JSONL：

    1. 一行一条记录，候选放在 `nbest` / `alternatives` / `beams` / `hypotheses`；
    2. 一行一个候选，顶层包含 `sample_id` 或 `record_id`、`text`、`rank`。
    """

    nbest_path = Path(path)
    by_key: dict[str, list[SequenceNBestItem]] = {}
    with nbest_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"n-best JSONL 第 {line_number} 行不是合法 JSON：{path}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"n-best JSONL 第 {line_number} 行必须是 JSON object：{path}")

            record_id = payload.get("record_id")
            sample_id = payload.get("sample_id")
            keys = []
            if record_id:
                keys.append(f"record_id:{record_id}")
            if sample_id:
                keys.append(f"sample_id:{sample_id}")
            if not keys:
                raise ValueError(
                    f"n-best JSONL 第 {line_number} 行缺少 record_id 或 sample_id：{path}"
                )

            source = str(payload.get("source") or default_source)
            raw_candidates = _candidate_list_from_mapping(payload) or [payload]
            items = coerce_sequence_nbest_items(raw_candidates, default_source=source)
            for key in keys:
                by_key.setdefault(key, []).extend(items)

    return {
        key: normalize_sequence_nbest_items(items)
        for key, items in by_key.items()
    }


def nbest_items_for_record(
    record: ASRConfidenceRecord,
    nbest_by_key: dict[str, list[SequenceNBestItem]],
) -> list[SequenceNBestItem]:
    """优先按 record_id，其次按 sample_id 查找一条 record 的 n-best。"""

    if record.record_id:
        by_record_id = nbest_by_key.get(f"record_id:{record.record_id}")
        if by_record_id is not None:
            return by_record_id
    return nbest_by_key.get(f"sample_id:{record.sample_id}", [])


def _coerce_one_nbest_item(
    item: Any,
    *,
    fallback_rank: int,
    default_source: str,
) -> SequenceNBestItem | None:
    if isinstance(item, SequenceNBestItem):
        return item

    if isinstance(item, ASRAlternative):
        return SequenceNBestItem(
            text=item.text,
            rank=item.rank,
            score=item.score,
            confidence=item.confidence,
            source=item.source or default_source,
            metadata={"alternative_id": item.alternative_id, **item.metadata},
        )

    if isinstance(item, str):
        text = item
        rank = fallback_rank
        score = None
        confidence = None
        source = default_source
        metadata: dict[str, Any] = {}
    elif isinstance(item, dict):
        text = _first_present_string(
            item,
            "text",
            "pred_text",
            "transcript",
            "hypothesis",
        )
        if text is None:
            return None
        rank = _int_or_default(item.get("rank"), fallback_rank)
        score = _float_or_none(
            item.get("score", item.get("beam_score", item.get("logprob")))
        )
        confidence = _float_or_none(item.get("confidence"))
        source = str(item.get("source") or default_source)
        metadata = {
            key: value
            for key, value in item.items()
            if key
            not in {
                "text",
                "pred_text",
                "transcript",
                "hypothesis",
                "rank",
                "score",
                "beam_score",
                "logprob",
                "confidence",
                "source",
                "record_id",
                "sample_id",
                "nbest",
                "alternatives",
                "beams",
                "hypotheses",
            }
        }
    elif isinstance(item, list | tuple) and item:
        text = str(item[0])
        rank = fallback_rank
        score = _float_or_none(item[1]) if len(item) > 1 else None
        confidence = _float_or_none(item[2]) if len(item) > 2 else None
        source = default_source
        metadata = {"raw_tuple_length": len(item)}
    else:
        text = str(getattr(item, "text", "") or "")
        if not text:
            return None
        rank = fallback_rank
        score = _float_or_none(getattr(item, "score", None))
        confidence = _float_or_none(getattr(item, "confidence", None))
        source = default_source
        metadata = {
            "hypothesis_class": f"{item.__class__.__module__}.{item.__class__.__name__}"
        }

    text = " ".join(text.split())
    if not text:
        return None
    return SequenceNBestItem(
        text=text,
        rank=rank,
        score=score,
        confidence=confidence,
        source=source,
        metadata=metadata,
    )


def _sequence_items_from_existing_alternatives(
    alternatives: list[ASRAlternative],
    *,
    max_items: int,
) -> list[SequenceNBestItem]:
    sequence_alternatives = [
        alternative
        for alternative in alternatives
        if alternative.scope == AlternativeScope.SEQUENCE
    ]
    return coerce_sequence_nbest_items(sequence_alternatives, max_items=max_items)


def _candidate_list_from_mapping(payload: dict[str, Any]) -> Any | None:
    for key in ("nbest", "alternatives", "beams", "hypotheses"):
        value = payload.get(key)
        if value:
            return value
    return None


def _first_present_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _ranges_overlap(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> bool:
    return left_start < right_end and right_start < left_end


def _is_non_string_iterable(value: Any) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, str | bytes | dict)


def _unique_id(base: str, used_ids: set[str]) -> str:
    safe_base = _safe_id(base)
    if safe_base not in used_ids:
        used_ids.add(safe_base)
        return safe_base
    suffix = 2
    while f"{safe_base}_{suffix}" in used_ids:
        suffix += 1
    unique = f"{safe_base}_{suffix}"
    used_ids.add(unique)
    return unique


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "alternative"
