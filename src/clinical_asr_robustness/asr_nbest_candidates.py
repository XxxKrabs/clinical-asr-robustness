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
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceRecord,
)

T029_GENERATED_BY = "T029"
SEQUENCE_ALIGNMENT_METHOD = "sequence_nbest"
SPAN_ALIGNMENT_METHOD = "sequence_nbest_diff"
DEFAULT_NBEST_SOURCE = "nemo_beam"


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


def attach_nbest_candidates_to_record(
    record: ASRConfidenceRecord,
    nbest_items: Any | None = None,
    *,
    max_sequence_alternatives: int = 5,
    max_span_alternatives: int = 3,
    default_source: str = DEFAULT_NBEST_SOURCE,
    include_unchanged_span_candidates: bool = False,
) -> ASRConfidenceRecord:
    """给一条 ASR confidence record 追加 sequence/span alternatives。

    `nbest_items` 若为空，会尝试复用 record 内已有的 `scope="sequence"`
    alternatives；这样可以先写 sequence-level n-best，再在后续批处理中补 span
    候选。
    """

    if max_sequence_alternatives <= 0:
        raise ValueError("max_sequence_alternatives 必须大于 0")
    if max_span_alternatives <= 0:
        raise ValueError("max_span_alternatives 必须大于 0")

    existing_to_keep = [
        alternative
        for alternative in record.asr_alternatives
        if alternative.metadata.get("generated_by") != T029_GENERATED_BY
    ]
    used_ids = {alternative.alternative_id for alternative in existing_to_keep}

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

    for span in record.uncertain_spans:
        kept_alternative_ids = [
            alternative_id
            for alternative_id in span.alternative_ids
            if alternative_id in {alternative.alternative_id for alternative in existing_to_keep}
        ]
        span_alternative_ids = list(kept_alternative_ids)
        seen_span_texts = {normalize_candidate_text(span.text)}

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

        span_metadata = dict(span.metadata)
        span_metadata["t029"] = {
            "alignment_method": SPAN_ALIGNMENT_METHOD,
            "sequence_alternatives_considered": len(sequence_alternatives),
            "span_alternatives_added": len(span_alternative_ids) - len(kept_alternative_ids),
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

    payload = record.model_dump(mode="json")
    payload["asr_alternatives"] = [
        alternative.model_dump(mode="json") for alternative in alternatives
    ]
    payload["uncertain_spans"] = [span.model_dump(mode="json") for span in updated_spans]
    payload["metadata"] = metadata
    return ASRConfidenceRecord.model_validate(payload)


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
