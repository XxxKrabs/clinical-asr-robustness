"""用完整对话语义补全残余 speaker gap，并保留声学证据边界。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinical_asr_robustness.asr_confidence import ASRConfidenceRecord, ASRWord
from clinical_asr_robustness.medical_entity_review import parse_json_object

SEMANTIC_SPEAKER_RESOLUTION_VERSION = "semantic_speaker_resolution/v1"
LLM_SEMANTIC_SPEAKER_SOURCE = "llm_semantic_speaker_resolution/v1"


class SemanticSpeakerWordReference(BaseModel):
    """可稳定回写到 ASR word 的引用。"""

    model_config = ConfigDict(extra="forbid")

    record_id: str | None = None
    sample_id: str
    word_index: int = Field(ge=0)


class SemanticSpeakerGap(BaseModel):
    """一段连续、尚无展示 speaker 的 ASR 字词。"""

    model_config = ConfigDict(extra="forbid")

    gap_id: str
    dataset: str
    consultation_id: str
    word_references: list[SemanticSpeakerWordReference]
    target_text: str
    left_speaker_label: str | None = None
    right_speaker_label: str | None = None
    acoustic_candidate_labels: list[str] = Field(default_factory=list)
    allowed_speaker_labels: list[str] = Field(default_factory=list)
    original_mapping_statuses: list[str] = Field(default_factory=list)


class SemanticSpeakerDecision(BaseModel):
    """LLM 对一个 speaker gap 的结构化判断。"""

    model_config = ConfigDict(extra="forbid")

    gap_id: str
    speaker_label: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: str = Field(min_length=1)


class SemanticSpeakerPrompt(BaseModel):
    """一整例对话的一次 LLM speaker 语义补全请求。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SEMANTIC_SPEAKER_RESOLUTION_VERSION
    prompt_id: str
    dataset: str
    consultation_id: str
    gaps: list[SemanticSpeakerGap]
    messages: list[dict[str, str]]
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class _WordReference:
    record: ASRConfidenceRecord
    word: ASRWord


def build_semantic_speaker_prompts(
    records: Iterable[ASRConfidenceRecord],
) -> list[SemanticSpeakerPrompt]:
    """按完整 consultation 构造一次请求，集中判断其中全部残余 gap。"""

    grouped: dict[tuple[str, str], list[ASRConfidenceRecord]] = defaultdict(list)
    for record in records:
        consultation_id = str(record.consultation_id or record.sample_id)
        grouped[(record.dataset, consultation_id)].append(record)

    prompts: list[SemanticSpeakerPrompt] = []
    for (dataset, consultation_id), group in sorted(grouped.items()):
        word_refs = _ordered_word_references(group)
        known_labels = sorted(
            {
                label
                for word_ref in word_refs
                if (label := _meaningful_speaker_label(word_ref.word.speaker_label))
                is not None
            }
        )
        if not known_labels:
            continue
        gaps = _find_semantic_gaps(
            word_refs,
            dataset=dataset,
            consultation_id=consultation_id,
            known_labels=known_labels,
        )
        if not gaps:
            continue
        prompt_hash = hashlib.sha256(
            f"{dataset}\0{consultation_id}".encode()
        ).hexdigest()[:12]
        conversation = _render_gap_labeled_conversation(word_refs, gaps)
        messages = build_semantic_speaker_messages(
            conversation=conversation,
            gaps=gaps,
            known_labels=known_labels,
        )
        prompts.append(
            SemanticSpeakerPrompt(
                prompt_id=f"semantic_speaker_{prompt_hash}",
                dataset=dataset,
                consultation_id=consultation_id,
                gaps=gaps,
                messages=messages,
                metadata={
                    "context_scope": "complete_consultation_asr",
                    "known_speaker_labels": known_labels,
                    "gap_count": len(gaps),
                    "reference_used": False,
                    "acoustic_identity_only": True,
                },
            )
        )
    return prompts


def build_semantic_speaker_messages(
    *,
    conversation: str,
    gaps: Sequence[SemanticSpeakerGap],
    known_labels: Sequence[str],
) -> list[dict[str, str]]:
    """构造严格 JSON 输出的中文 speaker 语义判定提示。"""

    gap_specs = [
        {
            "gap_id": gap.gap_id,
            "target_text": gap.target_text,
            "left_speaker_label": gap.left_speaker_label,
            "right_speaker_label": gap.right_speaker_label,
            "acoustic_candidate_labels": gap.acoustic_candidate_labels,
            "allowed_speaker_labels": gap.allowed_speaker_labels,
            "original_mapping_statuses": gap.original_mapping_statuses,
        }
        for gap in gaps
    ]
    payload = {
        "task": "resolve_unknown_acoustic_speaker_gaps_from_semantic_context",
        "known_speaker_labels": list(known_labels),
        "conversation_with_gap_markers": conversation,
        "gaps": gap_specs,
        "rules": [
            "speaker_0 等只是任意声学身份，不代表医生或患者角色",
            "结合句法连续、问答衔接、称谓、第一人称指代和轮次结构判断",
            "不得修改 ASR 文字，不得创建新的 speaker 标签",
            "每个 gap 必须且只能返回一个 allowed_speaker_labels 中的标签",
            "证据弱时仍选择最可能标签，但 confidence 应低，并使用 uncertain_best_guess",
            "不要输出病例解释、诊疗建议或自由文本理由",
        ],
        "output_schema": {
            "decisions": [
                {
                    "gap_id": "string",
                    "speaker_label": "one allowed label",
                    "confidence": "number from 0 to 1",
                    "reason_code": (
                        "same_sentence_continuation | turn_taking | question_answer | "
                        "address_or_pronoun | discourse_semantics | uncertain_best_guess"
                    ),
                }
            ]
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是临床 ASR 研究中的说话人语义续接器。只输出严格 JSON。"
                "你不是声纹模型，必须把判断标为语义推断，并逐个覆盖所有 gap。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_semantic_speaker_decisions(
    content: str,
    *,
    prompt: SemanticSpeakerPrompt,
    require_all: bool = True,
) -> list[SemanticSpeakerDecision]:
    """解析并校验 LLM 决策；不接受越界 speaker 或重复 gap。"""

    payload = parse_json_object(content)
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise ValueError("LLM speaker 输出必须是包含 decisions 数组的 JSON 对象")

    gap_by_id = {gap.gap_id: gap for gap in prompt.gaps}
    decisions: list[SemanticSpeakerDecision] = []
    seen_gap_ids: set[str] = set()
    for raw_decision in payload["decisions"]:
        decision = SemanticSpeakerDecision.model_validate(raw_decision)
        gap = gap_by_id.get(decision.gap_id)
        if gap is None:
            raise ValueError(f"LLM 返回未知 gap_id：{decision.gap_id}")
        if decision.gap_id in seen_gap_ids:
            raise ValueError(f"LLM 重复返回 gap_id：{decision.gap_id}")
        if decision.speaker_label not in gap.allowed_speaker_labels:
            raise ValueError(
                f"gap {decision.gap_id} 返回了不允许的 speaker："
                f"{decision.speaker_label}"
            )
        seen_gap_ids.add(decision.gap_id)
        decisions.append(decision)

    if require_all:
        missing = sorted(set(gap_by_id) - seen_gap_ids)
        if missing:
            raise ValueError(f"LLM 未覆盖全部 speaker gaps：{missing}")
    decision_by_id = {decision.gap_id: decision for decision in decisions}
    return [
        decision_by_id[gap.gap_id]
        for gap in prompt.gaps
        if gap.gap_id in decision_by_id
    ]


def apply_semantic_speaker_decisions(
    records: Iterable[ASRConfidenceRecord],
    *,
    prompt: SemanticSpeakerPrompt,
    decisions: Sequence[SemanticSpeakerDecision],
    min_confidence: float = 0.80,
    force_resolve_all: bool = False,
    llm_metadata: dict[str, Any] | None = None,
) -> list[ASRConfidenceRecord]:
    """应用语义决策；force 模式也保留 confidence 与原始声学空值。"""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence 必须位于 [0, 1]")
    copied = [record.model_copy(deep=True) for record in records]
    record_by_key = {
        (record.sample_id, record.record_id): record
        for record in copied
        if record.dataset == prompt.dataset
        and str(record.consultation_id or record.sample_id) == prompt.consultation_id
    }
    gap_by_id = {gap.gap_id: gap for gap in prompt.gaps}
    decision_by_id = {decision.gap_id: decision for decision in decisions}
    if force_resolve_all:
        missing = sorted(set(gap_by_id) - set(decision_by_id))
        if missing:
            raise ValueError(f"force_resolve_all 缺少 gap 决策：{missing}")

    applied_count = 0
    for gap_id, decision in decision_by_id.items():
        gap = gap_by_id.get(gap_id)
        if gap is None:
            raise ValueError(f"决策引用未知 gap：{gap_id}")
        if decision.speaker_label not in gap.allowed_speaker_labels:
            raise ValueError(f"决策 speaker 不在允许集合：{gap_id}")
        should_apply = force_resolve_all or decision.confidence >= min_confidence
        if not should_apply:
            continue
        for reference in gap.word_references:
            record = record_by_key.get((reference.sample_id, reference.record_id))
            if record is None:
                raise ValueError(f"无法定位 speaker gap record：{reference.sample_id}")
            word = record.asr_words[reference.word_index]
            if _meaningful_speaker_label(word.speaker_label) is not None:
                raise ValueError(f"speaker gap 回写目标已存在标签：{gap_id}")
            evidence = word.metadata.get("diarization")
            diarization = dict(evidence) if isinstance(evidence, dict) else {}
            word.speaker_label = decision.speaker_label
            word.metadata = {
                **word.metadata,
                "diarization": {
                    **diarization,
                    "resolved_speaker_label": decision.speaker_label,
                    "speaker_label_source": LLM_SEMANTIC_SPEAKER_SOURCE,
                    "semantic_resolution": {
                        "schema_version": SEMANTIC_SPEAKER_RESOLUTION_VERSION,
                        "source": LLM_SEMANTIC_SPEAKER_SOURCE,
                        "prompt_id": prompt.prompt_id,
                        "gap_id": gap_id,
                        "confidence": decision.confidence,
                        "reason_code": decision.reason_code,
                        "application_mode": (
                            "forced_all" if force_resolve_all else "confidence_gated"
                        ),
                        "min_confidence": min_confidence,
                        "original_mapping_status": diarization.get("mapping_status"),
                        "acoustic_speaker_label_preserved": diarization.get(
                            "speaker_label"
                        ),
                        "reference_used": False,
                        "llm": dict(llm_metadata or {}),
                    },
                },
            }
            applied_count += 1

    _refresh_semantic_resolution_metadata(
        copied,
        prompt=prompt,
        applied_word_count=applied_count,
        force_resolve_all=force_resolve_all,
        min_confidence=min_confidence,
    )
    return [
        ASRConfidenceRecord.model_validate(record.model_dump(mode="json"))
        for record in copied
    ]


def _find_semantic_gaps(
    word_refs: Sequence[_WordReference],
    *,
    dataset: str,
    consultation_id: str,
    known_labels: Sequence[str],
) -> list[SemanticSpeakerGap]:
    prefix = hashlib.sha256(f"{dataset}\0{consultation_id}".encode()).hexdigest()[:10]
    gaps: list[SemanticSpeakerGap] = []
    position = 0
    while position < len(word_refs):
        if _meaningful_speaker_label(word_refs[position].word.speaker_label) is not None:
            position += 1
            continue
        run_start = position
        while (
            position < len(word_refs)
            and _meaningful_speaker_label(word_refs[position].word.speaker_label) is None
        ):
            position += 1
        run_refs = word_refs[run_start:position]
        left_label = (
            _meaningful_speaker_label(word_refs[run_start - 1].word.speaker_label)
            if run_start > 0
            else None
        )
        right_label = (
            _meaningful_speaker_label(word_refs[position].word.speaker_label)
            if position < len(word_refs)
            else None
        )
        candidate_scores: dict[str, float] = defaultdict(float)
        statuses: set[str] = set()
        for word_ref in run_refs:
            evidence = word_ref.word.metadata.get("diarization")
            if not isinstance(evidence, dict):
                continue
            status = str(evidence.get("mapping_status") or "").strip()
            if status:
                statuses.add(status)
            candidates = evidence.get("candidate_overlap_sec")
            if isinstance(candidates, dict):
                for label, score in candidates.items():
                    if str(label) in known_labels:
                        candidate_scores[str(label)] += float(score or 0.0)
        acoustic_candidates = [
            label
            for label, _ in sorted(
                candidate_scores.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        gap_id = f"semantic_gap_{prefix}_{len(gaps) + 1:04d}"
        gaps.append(
            SemanticSpeakerGap(
                gap_id=gap_id,
                dataset=dataset,
                consultation_id=consultation_id,
                word_references=[
                    SemanticSpeakerWordReference(
                        record_id=word_ref.record.record_id,
                        sample_id=word_ref.record.sample_id,
                        word_index=word_ref.word.word_index,
                    )
                    for word_ref in run_refs
                ],
                target_text=_join_word_references(run_refs),
                left_speaker_label=left_label,
                right_speaker_label=right_label,
                acoustic_candidate_labels=acoustic_candidates,
                allowed_speaker_labels=list(known_labels),
                original_mapping_statuses=sorted(statuses or {"missing_evidence"}),
            )
        )
    return gaps


def _render_gap_labeled_conversation(
    word_refs: Sequence[_WordReference],
    gaps: Sequence[SemanticSpeakerGap],
) -> str:
    gap_by_word = {
        (reference.sample_id, reference.record_id, reference.word_index): gap.gap_id
        for gap in gaps
        for reference in gap.word_references
    }
    runs: list[tuple[str, list[_WordReference]]] = []
    for word_ref in word_refs:
        key = (
            word_ref.record.sample_id,
            word_ref.record.record_id,
            word_ref.word.word_index,
        )
        identity = gap_by_word.get(key) or str(word_ref.word.speaker_label)
        if runs and runs[-1][0] == identity:
            runs[-1][1].append(word_ref)
        else:
            runs.append((identity, [word_ref]))
    return "\n".join(
        f"[{identity}] {_join_word_references(run_refs)}" for identity, run_refs in runs
    )


def _ordered_word_references(
    records: Sequence[ASRConfidenceRecord],
) -> list[_WordReference]:
    ordered_records = sorted(
        records,
        key=lambda record: (_record_start_sec(record), record.sample_id),
    )
    return [
        _WordReference(record=record, word=word)
        for record in ordered_records
        for word in record.asr_words
    ]


def _record_start_sec(record: ASRConfidenceRecord) -> float:
    offset = _timestamp_offset_sec(record)
    starts = [word.start_sec + offset for word in record.asr_words if word.start_sec is not None]
    return min(starts) if starts else float("inf")


def _timestamp_offset_sec(record: ASRConfidenceRecord) -> float:
    source_manifest = record.metadata.get("source_manifest")
    if not isinstance(source_manifest, dict):
        return 0.0
    if source_manifest.get("timestamp_reference") == "source_audio_absolute":
        return 0.0
    return float(
        source_manifest.get("timestamp_offset_sec")
        or source_manifest.get("source_start_sec")
        or 0.0
    )


def _join_word_references(word_refs: Sequence[_WordReference]) -> str:
    if not word_refs:
        return ""
    pieces = [word_refs[0].word.text]
    for previous, current in zip(word_refs[:-1], word_refs[1:], strict=True):
        separator = current.word.metadata.get("separator_before")
        if not isinstance(separator, str):
            previous_ascii = previous.word.text[-1:].isascii() and previous.word.text[-1:].isalnum()
            current_ascii = current.word.text[:1].isascii() and current.word.text[:1].isalnum()
            separator = " " if previous_ascii and current_ascii else ""
        pieces.extend([separator, current.word.text])
    return "".join(pieces)


def _meaningful_speaker_label(value: str | None) -> str | None:
    label = str(value or "").strip()
    if not label or label.casefold() in {"mixed", "unknown", "speaker_unknown", "none"}:
        return None
    return label


def _refresh_semantic_resolution_metadata(
    records: Sequence[ASRConfidenceRecord],
    *,
    prompt: SemanticSpeakerPrompt,
    applied_word_count: int,
    force_resolve_all: bool,
    min_confidence: float,
) -> None:
    for record in records:
        if record.dataset != prompt.dataset or str(
            record.consultation_id or record.sample_id
        ) != prompt.consultation_id:
            continue
        semantic_word_count = 0
        resolved_counts: dict[str, int] = defaultdict(int)
        for word in record.asr_words:
            label = _meaningful_speaker_label(word.speaker_label)
            if label:
                resolved_counts[label] += 1
            diarization = word.metadata.get("diarization")
            if isinstance(diarization, dict) and diarization.get("semantic_resolution"):
                semantic_word_count += 1

        for segment in record.asr_segments:
            segment_words = record.asr_words[
                segment.start_word_index : segment.end_word_index
            ]
            labels = [
                label
                for word in segment_words
                if (label := _meaningful_speaker_label(word.speaker_label)) is not None
            ]
            if labels and len(labels) == len(segment_words) and len(set(labels)) == 1:
                segment.speaker_label = labels[0]
            elif labels:
                segment.speaker_label = "mixed"
            else:
                segment.speaker_label = None
            existing = segment.metadata.get("diarization")
            segment_diarization = dict(existing) if isinstance(existing, dict) else {}
            segment.metadata = {
                **segment.metadata,
                "diarization": {
                    **segment_diarization,
                    "resolved_speaker_label_counts": dict(
                        sorted(_count_values(labels).items())
                    ),
                    "resolved_word_count": len(labels),
                    "semantic_resolved_word_count": sum(
                        bool(
                            isinstance(word.metadata.get("diarization"), dict)
                            and word.metadata["diarization"].get("semantic_resolution")
                        )
                        for word in segment_words
                    ),
                },
            }

        total_word_count = len(record.asr_words)
        resolved_word_count = sum(resolved_counts.values())
        existing = record.metadata.get("diarization")
        record_diarization = dict(existing) if isinstance(existing, dict) else {}
        record.metadata = {
            **record.metadata,
            "diarization": {
                **record_diarization,
                "resolved_status": (
                    "complete"
                    if total_word_count and resolved_word_count == total_word_count
                    else "partial" if resolved_word_count else "missing"
                ),
                "resolved_word_count": resolved_word_count,
                "resolved_coverage": (
                    resolved_word_count / total_word_count if total_word_count else 0.0
                ),
                "resolved_speaker_word_counts": dict(sorted(resolved_counts.items())),
                "semantic_resolved_word_count": semantic_word_count,
                "semantic_resolution": {
                    "schema_version": SEMANTIC_SPEAKER_RESOLUTION_VERSION,
                    "source": LLM_SEMANTIC_SPEAKER_SOURCE,
                    "prompt_id": prompt.prompt_id,
                    "prompt_gap_count": len(prompt.gaps),
                    "consultation_applied_word_count": applied_word_count,
                    "application_mode": (
                        "forced_all" if force_resolve_all else "confidence_gated"
                    ),
                    "min_confidence": min_confidence,
                    "acoustic_evidence_preserved": True,
                    "reference_used": False,
                },
            },
        }


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return dict(counts)
