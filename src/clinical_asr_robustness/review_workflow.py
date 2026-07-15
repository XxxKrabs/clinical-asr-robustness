# ruff: noqa: E501
"""ASR 置信度医生审阅 demo 的样本包、反馈日志与确认转写工具。

本模块覆盖 T030/T035/T036 的项目侧通用逻辑：

- T030：把 `ASRConfidenceRecord` 转成绿/黄/红可审阅样本包；
- T035：读取医生/模拟审阅者反馈，并回放生成 `confirmed_transcript`；
- T036：生成静态/轻量 HTML 审阅界面，前端可导出结构化反馈 JSONL。

所有输出均标注为研究 demo，不构成临床建议。
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness._compat import StrEnum
from clinical_asr_robustness.asr_confidence import (
    CLINICAL_USE_WARNING,
    AlternativeScope,
    ASRAlternative,
    ASRConfidenceRecord,
    ASRSegment,
    ConfidenceLevel,
    SourceChannel,
    UncertainSpan,
    join_asr_words,
)
from clinical_asr_robustness.medical_entity_review import (
    MEDICAL_ENTITY_REVIEW_METADATA_KEY,
)

REVIEW_SAMPLE_SCHEMA_VERSION = "asr_review_sample/v1"
REVIEW_CONVERSATION_SCHEMA_VERSION = "asr_review_conversation/v1"
FEEDBACK_ENTRY_SCHEMA_VERSION = "doctor_feedback_entry/v1"
FEEDBACK_LOG_SCHEMA_VERSION = "doctor_feedback_log/v1"
CONFIRMED_TRANSCRIPT_SCHEMA_VERSION = "confirmed_transcript_record/v1"

T030_GENERATED_BY = "T030"
T035_GENERATED_BY = "T035"
T036_GENERATED_BY = "T036"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReviewPriority(StrEnum):
    """审阅优先级。"""

    ROUTINE = "routine"
    SUGGESTED = "suggested"
    REQUIRED = "required"


class ReviewFeedbackAction(StrEnum):
    """医生/模拟审阅者可记录的动作。"""

    ACCEPT_ASR = "accept_asr"
    SELECT_ALTERNATIVE = "select_alternative"
    MANUAL_EDIT = "manual_edit"
    REJECT = "reject"
    UNABLE_TO_JUDGE = "unable_to_judge"


class ConfirmationStatus(StrEnum):
    """confirmed transcript 的整体确认状态。"""

    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"


class ReviewAlternative(BaseModel):
    """面向审阅界面的 span 候选。"""

    model_config = ConfigDict(extra="forbid")

    alternative_id: str
    scope: AlternativeScope
    rank: int = Field(ge=1)
    text: str = Field(min_length=1)
    span_id: str | None = None
    score: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str = "asr_nbest"
    alignment_method: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewWord(BaseModel):
    """一个可高亮显示的 ASR word。"""

    model_config = ConfigDict(extra="forbid")

    word_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    span_ids: list[str] = Field(default_factory=list)
    review_required: bool = False
    review_priority: ReviewPriority = ReviewPriority.ROUTINE
    speaker_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewSpan(BaseModel):
    """一个需要重点审阅的连续中/低置信度 span。"""

    model_config = ConfigDict(extra="forbid")

    span_id: str
    text: str = Field(min_length=1)
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    review_priority: ReviewPriority
    trigger_reason: str = "low_or_medium_confidence"
    alternatives: list[ReviewAlternative] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> ReviewSpan:
        if self.end_word_index <= self.start_word_index:
            raise ValueError("end_word_index 必须大于 start_word_index")
        return self


class ReviewSegment(BaseModel):
    """面向 HTML 展示的片段摘要。"""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    text: str
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    source: str = "derived_from_words"
    speaker_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewSample(BaseModel):
    """一条可供医生审阅 UI 使用的 ASR review sample。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REVIEW_SAMPLE_SCHEMA_VERSION
    record_id: str | None = None
    sample_id: str
    dataset: str
    split: str | None = None
    consultation_id: str | None = None
    source_channel: SourceChannel = SourceChannel.UNKNOWN
    audio_filepath: str | None = None
    duration_sec: float | None = Field(default=None, ge=0.0)
    asr_transcript: str
    asr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    words: list[ReviewWord] = Field(default_factory=list)
    uncertain_spans: list[ReviewSpan] = Field(default_factory=list)
    segments: list[ReviewSegment] = Field(default_factory=list)
    review_policy: dict[str, Any] = Field(default_factory=dict)
    generated_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    generated_from_schema_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @model_validator(mode="after")
    def validate_sample(self) -> ReviewSample:
        word_count = len(self.words)
        for span in self.uncertain_spans:
            if span.end_word_index > word_count:
                raise ValueError(f"review span 词范围越界：{span.span_id}")
        return self


class ReviewTurnSlice(BaseModel):
    """一个 speaker turn 在某条推理窗口记录中的词区间。"""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    record_id: str | None = None
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_slice(self) -> ReviewTurnSlice:
        if self.end_word_index <= self.start_word_index:
            raise ValueError("end_word_index 必须大于 start_word_index")
        return self


class ReviewSpeakerTurn(BaseModel):
    """病例级审阅包中的一段连续说话人发言。"""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    speaker_label: str
    speaker_role: str | None = None
    speaker_label_source: str
    text: str
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    word_count: int = Field(ge=0)
    slices: list[ReviewTurnSlice] = Field(default_factory=list)
    review_span_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewConversation(BaseModel):
    """一整例对话的审阅单元；内部可保留多个 ASR 推理窗口。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REVIEW_CONVERSATION_SCHEMA_VERSION
    conversation_id: str
    dataset: str
    split: str | None = None
    consultation_id: str
    source_channel: SourceChannel = SourceChannel.MIXED
    audio_filepath: str | None = None
    duration_sec: float | None = Field(default=None, ge=0.0)
    sample_ids: list[str] = Field(default_factory=list)
    speaker_turns: list[ReviewSpeakerTurn] = Field(default_factory=list)
    conversation_transcript: str
    review_samples: list[ReviewSample] = Field(default_factory=list)
    diarization_status: str = "missing"
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING


class DoctorFeedbackEntry(BaseModel):
    """一条医生/模拟审阅者对 span 的反馈。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = FEEDBACK_ENTRY_SCHEMA_VERSION
    feedback_id: str | None = None
    record_id: str | None = None
    sample_id: str | None = None
    span_id: str
    action: ReviewFeedbackAction
    selected_alternative_id: str | None = None
    manual_text: str | None = None
    original_text: str | None = None
    reviewer_id: str | None = "demo_reviewer"
    reviewer_role: str = "research_demo_reviewer"
    created_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: str = "manual_or_html_demo"
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @model_validator(mode="after")
    def validate_action_payload(self) -> DoctorFeedbackEntry:
        if not self.record_id and not self.sample_id:
            raise ValueError("反馈 entry 必须至少包含 record_id 或 sample_id")
        if self.action == ReviewFeedbackAction.SELECT_ALTERNATIVE:
            if not self.selected_alternative_id:
                raise ValueError("select_alternative 动作必须包含 selected_alternative_id")
        if self.action == ReviewFeedbackAction.MANUAL_EDIT:
            if self.manual_text is None or not self.manual_text.strip():
                raise ValueError("manual_edit 动作必须包含非空 manual_text")
            self.manual_text = self.manual_text.strip()
        return self


class DoctorFeedbackLog(BaseModel):
    """反馈日志包装对象；JSONL 中也允许一行一个 entry。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = FEEDBACK_LOG_SCHEMA_VERSION
    log_id: str | None = None
    generated_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reviewer_id: str | None = "demo_reviewer"
    reviewer_role: str = "research_demo_reviewer"
    entries: list[DoctorFeedbackEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING


class ConfirmedSpan(BaseModel):
    """某个 span 在回放反馈后的确认结果。"""

    model_config = ConfigDict(extra="forbid")

    span_id: str
    action: ReviewFeedbackAction | None = None
    original_text: str
    confirmed_text: str
    selected_alternative_id: str | None = None
    selected_alternative_text: str | None = None
    resolved: bool = False
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmedTranscriptRecord(BaseModel):
    """根据反馈日志回放生成的一条 confirmed transcript 记录。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIRMED_TRANSCRIPT_SCHEMA_VERSION
    record_id: str | None = None
    sample_id: str
    dataset: str
    split: str | None = None
    consultation_id: str | None = None
    source_channel: SourceChannel = SourceChannel.UNKNOWN
    asr_transcript: str
    confirmed_transcript: str
    confirmation_status: ConfirmationStatus
    applied_spans: list[ConfirmedSpan] = Field(default_factory=list)
    missing_feedback_span_ids: list[str] = Field(default_factory=list)
    unresolved_span_ids: list[str] = Field(default_factory=list)
    action_summary: dict[str, int] = Field(default_factory=dict)
    generated_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING


def review_priority_for_level(level: ConfidenceLevel) -> ReviewPriority:
    """把颜色等级映射到审阅优先级。"""

    if level == ConfidenceLevel.RED:
        return ReviewPriority.REQUIRED
    if level in {ConfidenceLevel.YELLOW, ConfidenceLevel.UNKNOWN}:
        return ReviewPriority.SUGGESTED
    return ReviewPriority.ROUTINE


def review_required_for_word(
    word_level: ConfidenceLevel,
    *,
    span_ids: list[str],
    medical_entity_gating_enabled: bool,
) -> bool:
    """判断一个词是否需要医生审阅。

    医学实体 gating 开启后，只有落在医学实体 review span 内的词才需要审阅；
    非医学词即使 ASR 置信度偏低，也只作为黑字上下文显示。
    """

    if span_ids:
        return True
    if medical_entity_gating_enabled:
        return False
    return word_level in {
        ConfidenceLevel.YELLOW,
        ConfidenceLevel.RED,
        ConfidenceLevel.UNKNOWN,
    }


def review_priority_for_word(
    word_level: ConfidenceLevel,
    *,
    span_ids: list[str],
    medical_entity_gating_enabled: bool,
) -> ReviewPriority:
    """返回词级审阅优先级。"""

    if span_ids or not medical_entity_gating_enabled:
        return review_priority_for_level(word_level)
    return ReviewPriority.ROUTINE


def build_review_sample(record: ASRConfidenceRecord) -> ReviewSample:
    """把一条 ASR confidence record 转成审阅样本。"""

    medical_review_policy = record.metadata.get(MEDICAL_ENTITY_REVIEW_METADATA_KEY)
    medical_entity_gating_enabled = isinstance(medical_review_policy, dict)
    span_ids_by_word: dict[int, list[str]] = {}
    for span in record.uncertain_spans:
        for word_index in range(span.start_word_index, span.end_word_index):
            span_ids_by_word.setdefault(word_index, []).append(span.span_id)

    words = [
        ReviewWord(
            word_index=word.word_index,
            text=word.text,
            start_sec=word.start_sec,
            end_sec=word.end_sec,
            confidence=word.confidence,
            confidence_level=word.confidence_level,
            char_start=word.char_start,
            char_end=word.char_end,
            span_ids=span_ids_by_word.get(word.word_index, []),
            review_required=review_required_for_word(
                word.confidence_level,
                span_ids=span_ids_by_word.get(word.word_index, []),
                medical_entity_gating_enabled=medical_entity_gating_enabled,
            ),
            review_priority=review_priority_for_word(
                word.confidence_level,
                span_ids=span_ids_by_word.get(word.word_index, []),
                medical_entity_gating_enabled=medical_entity_gating_enabled,
            ),
            speaker_label=word.speaker_label,
            metadata=word.metadata,
        )
        for word in record.asr_words
    ]

    review_spans = [
        _build_review_span(record, span)
        for span in record.uncertain_spans
    ]
    segments = [_build_review_segment(segment) for segment in record.asr_segments]
    thresholds = record.confidence.thresholds

    return ReviewSample(
        record_id=record.record_id,
        sample_id=record.sample_id,
        dataset=record.dataset,
        split=record.split,
        consultation_id=record.consultation_id,
        source_channel=record.source_channel,
        audio_filepath=record.audio_filepath,
        duration_sec=record.duration_sec,
        asr_transcript=record.asr_transcript,
        asr_confidence=record.asr_confidence,
        confidence_level=record.confidence_level,
        words=words,
        uncertain_spans=review_spans,
        segments=segments,
        review_policy={
            "generated_by": T030_GENERATED_BY,
            "color_levels": {
                "green": f"confidence >= {thresholds.green_min}",
                "yellow": (
                    f"{thresholds.yellow_min} <= confidence < {thresholds.green_min}"
                ),
                "red": f"confidence < {thresholds.yellow_min}",
                "unknown": "missing confidence",
            },
            "actions": [action.value for action in ReviewFeedbackAction],
            "target_scope": (
                "llm_identified_medical_entities_only"
                if medical_entity_gating_enabled
                else "all_low_medium_unknown_confidence_words"
            ),
            "note": (
                (
                    "Only LLM-identified medical entity words keep green/yellow/red "
                    "display; non-medical words are neutral black context. "
                    "Only non-green medical entity spans are primary review targets. "
                )
                if medical_entity_gating_enabled
                else (
                    "Green words are shown for context; yellow/red/unknown spans are "
                    "the primary review targets. "
                )
            )
            + (
                "Feedback is research data only."
            ),
        },
        generated_from_schema_version=record.schema_version,
        metadata={
            "source_record_metadata": record.metadata,
            "asr_model": record.model.model_dump(mode="json"),
            "asr_decoding": record.decoding.model_dump(mode="json"),
            "confidence_config": record.confidence.model_dump(mode="json"),
        },
    )


def build_review_samples(records: Iterable[ASRConfidenceRecord]) -> list[ReviewSample]:
    """批量生成审阅样本。"""

    return [build_review_sample(record) for record in records]


def build_review_conversations(
    samples: Iterable[ReviewSample],
    *,
    max_merge_gap_sec: float = 1.5,
) -> list[ReviewConversation]:
    """把 ASR 推理窗口聚合为 consultation-level 完整对话审阅包。

    推理窗口仍保留在 ``review_samples`` 中，以便反馈能继续按原 ``record_id``
    确定性回放；面向医生或候选生成方的一级样本则变成完整病例对话。
    """

    if max_merge_gap_sec < 0:
        raise ValueError("max_merge_gap_sec 不能小于 0")

    grouped: dict[tuple[str, str], list[ReviewSample]] = defaultdict(list)
    for sample in samples:
        consultation_id = str(sample.consultation_id or sample.sample_id)
        grouped[(sample.dataset, consultation_id)].append(sample)

    conversations: list[ReviewConversation] = []
    for (dataset, consultation_id), group in sorted(grouped.items()):
        ordered = sorted(group, key=_review_sample_time_sort_key)
        turns, labeled_word_count, total_word_count = _build_review_speaker_turns(
            ordered,
            max_merge_gap_sec=max_merge_gap_sec,
        )
        semantic_inferred_word_count = sum(
            1
            for sample in ordered
            for word in sample.words
            if _word_has_semantic_speaker_resolution(word)
        )
        if total_word_count and labeled_word_count == total_word_count:
            diarization_status = (
                "semantic_complete" if semantic_inferred_word_count else "complete"
            )
        elif labeled_word_count:
            diarization_status = "partial"
        else:
            diarization_status = "missing"

        audio_paths = [sample.audio_filepath for sample in ordered if sample.audio_filepath]
        audio_filepath = audio_paths[0] if audio_paths else None
        audio_path_consistent = len(set(audio_paths)) <= 1
        duration_values = [
            sample.duration_sec for sample in ordered if sample.duration_sec is not None
        ]
        duration_sec = max(duration_values) if duration_values else None
        split_values = {sample.split for sample in ordered if sample.split}
        split = next(iter(split_values)) if len(split_values) == 1 else None
        conversation_id = f"{dataset}:{consultation_id}:conversation"
        transcript = "\n".join(
            f"[{turn.speaker_role or turn.speaker_label}] {turn.text}" for turn in turns
        )
        conversations.append(
            ReviewConversation(
                conversation_id=conversation_id,
                dataset=dataset,
                split=split,
                consultation_id=consultation_id,
                audio_filepath=audio_filepath,
                duration_sec=duration_sec,
                sample_ids=[sample.sample_id for sample in ordered],
                speaker_turns=turns,
                conversation_transcript=transcript,
                review_samples=ordered,
                diarization_status=diarization_status,
                metadata={
                    "generated_by": T030_GENERATED_BY,
                    "review_unit": "complete_consultation",
                    "inference_unit": "window_or_channel_record",
                    "inference_window_count": len(ordered),
                    "speaker_turn_count": len(turns),
                    "speaker_labels": sorted(
                        {
                            turn.speaker_label
                            for turn in turns
                            if turn.speaker_label not in {"speaker_unknown", "mixed", "unknown"}
                        }
                    ),
                    "speaker_labeled_word_count": labeled_word_count,
                    "semantic_inferred_word_count": semantic_inferred_word_count,
                    "semantic_labels_are_not_acoustic_ground_truth": bool(
                        semantic_inferred_word_count
                    ),
                    "total_word_count": total_word_count,
                    "audio_path_consistent": audio_path_consistent,
                    "max_merge_gap_sec": max_merge_gap_sec,
                    "reference_used": False,
                    "note": (
                        "完整对话是审阅/候选上下文单位；内部推理窗口只用于 ASR "
                        "运行、时间定位和反馈回放。speaker_unknown 表示尚未接入或无法映射"
                        "说话人分离；semantic_complete 含 LLM 语义推断，不代表声学真值。"
                    ),
                },
            )
        )
    return conversations


def write_review_conversations_jsonl(
    conversations: Iterable[ReviewConversation],
    path: str | Path,
) -> None:
    """写入 consultation-level 完整对话审阅 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for conversation in conversations:
            file.write(json.dumps(conversation.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def read_review_conversations_jsonl(path: str | Path) -> list[ReviewConversation]:
    """读取 consultation-level 完整对话审阅 JSONL。"""

    conversations: list[ReviewConversation] = []
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                conversations.append(ReviewConversation.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"无法解析完整对话审阅 JSONL 第 {line_number} 行：{input_path}"
                ) from exc
    return conversations


def write_review_samples_jsonl(
    samples: Iterable[ReviewSample],
    path: str | Path,
) -> None:
    """写入审阅样本 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for sample in samples:
            file.write(json.dumps(sample.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def read_review_samples_jsonl(path: str | Path) -> list[ReviewSample]:
    """读取审阅样本 JSONL。"""

    samples: list[ReviewSample] = []
    jsonl_path = Path(path)
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                samples.append(ReviewSample.model_validate_json(stripped))
            except Exception as exc:  # noqa: BLE001 - 保留行号便于定位
                raise ValueError(
                    f"无法解析 review samples JSONL 第 {line_number} 行：{jsonl_path}"
                ) from exc
    return samples


def write_review_spans_csv(samples: Iterable[ReviewSample], path: str | Path) -> None:
    """写入 span 级审阅 CSV，便于快速人工浏览或表格导入。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_id",
        "sample_id",
        "dataset",
        "split",
        "consultation_id",
        "source_channel",
        "span_id",
        "span_text",
        "start_word_index",
        "end_word_index",
        "start_sec",
        "end_sec",
        "mean_confidence",
        "min_confidence",
        "confidence_level",
        "review_priority",
        "trigger_reason",
        "candidate_count",
        "alternative_ids",
        "candidate_texts",
        "candidates_json",
        "research_use_only",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            for span in sample.uncertain_spans:
                alternatives_payload = [
                    alternative.model_dump(mode="json")
                    for alternative in span.alternatives
                ]
                writer.writerow(
                    {
                        "record_id": sample.record_id or "",
                        "sample_id": sample.sample_id,
                        "dataset": sample.dataset,
                        "split": sample.split or "",
                        "consultation_id": sample.consultation_id or "",
                        "source_channel": sample.source_channel.value,
                        "span_id": span.span_id,
                        "span_text": span.text,
                        "start_word_index": span.start_word_index,
                        "end_word_index": span.end_word_index,
                        "start_sec": _empty_if_none(span.start_sec),
                        "end_sec": _empty_if_none(span.end_sec),
                        "mean_confidence": _empty_if_none(span.mean_confidence),
                        "min_confidence": _empty_if_none(span.min_confidence),
                        "confidence_level": span.confidence_level.value,
                        "review_priority": span.review_priority.value,
                        "trigger_reason": span.trigger_reason,
                        "candidate_count": len(span.alternatives),
                        "alternative_ids": " | ".join(
                            alternative.alternative_id
                            for alternative in span.alternatives
                        ),
                        "candidate_texts": " | ".join(
                            alternative.text for alternative in span.alternatives
                        ),
                        "candidates_json": json.dumps(
                            alternatives_payload,
                            ensure_ascii=False,
                        ),
                        "research_use_only": sample.research_use_only,
                    }
                )


def read_feedback_entries_jsonl(path: str | Path) -> list[DoctorFeedbackEntry]:
    """读取反馈 JSONL。

    支持三种输入：

    - 一行一个 `DoctorFeedbackEntry`；
    - 一行一个 `DoctorFeedbackLog` wrapper；
    - 一行一个 entry list，便于 HTML 直接导出的 JSON/JSONL 混用。
    """

    feedback_path = Path(path)
    entries: list[DoctorFeedbackEntry] = []
    with feedback_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                entries.extend(_coerce_feedback_payload(payload))
            except Exception as exc:  # noqa: BLE001 - 保留文件与行号便于定位
                raise ValueError(
                    f"无法解析反馈 JSONL 第 {line_number} 行：{feedback_path}"
                ) from exc
    return entries


def write_feedback_entries_jsonl(
    entries: Iterable[DoctorFeedbackEntry],
    path: str | Path,
) -> None:
    """写入一行一个 entry 的反馈 JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for entry in entries:
            file.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def apply_feedback_to_records(
    records: Iterable[ASRConfidenceRecord],
    feedback_entries: Iterable[DoctorFeedbackEntry],
    *,
    require_feedback_for_all_spans: bool = False,
) -> list[ConfirmedTranscriptRecord]:
    """批量回放反馈，生成 confirmed transcript records。"""

    entries = list(feedback_entries)
    return [
        apply_feedback_to_record(
            record,
            _feedback_entries_for_record(record, entries),
            require_feedback_for_all_spans=require_feedback_for_all_spans,
        )
        for record in records
    ]


def apply_feedback_to_record(
    record: ASRConfidenceRecord,
    feedback_entries: Iterable[DoctorFeedbackEntry],
    *,
    require_feedback_for_all_spans: bool = False,
) -> ConfirmedTranscriptRecord:
    """把一条 record 的反馈回放到 `asr_transcript` 上。"""

    entries_by_span: dict[str, DoctorFeedbackEntry] = {}
    for entry in feedback_entries:
        entries_by_span[entry.span_id] = entry

    if not record.uncertain_spans:
        return ConfirmedTranscriptRecord(
            record_id=record.record_id,
            sample_id=record.sample_id,
            dataset=record.dataset,
            split=record.split,
            consultation_id=record.consultation_id,
            source_channel=record.source_channel,
            asr_transcript=record.asr_transcript,
            confirmed_transcript=record.asr_transcript,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            metadata={"generated_by": T035_GENERATED_BY, "source_feedback_entries": 0},
        )

    missing_feedback_span_ids: list[str] = []
    unresolved_span_ids: list[str] = []
    applied_spans: list[ConfirmedSpan] = []
    replacements: list[tuple[int, int, str]] = []
    fallback_pieces: list[str] = []
    fallback_tokens = record.asr_transcript.split()
    char_replay_available = True
    cursor = 0

    for span in sorted(record.uncertain_spans, key=lambda item: item.start_word_index):
        if span.start_word_index < cursor:
            raise ValueError(
                f"uncertain spans 发生重叠，暂不支持自动回放：{record.sample_id} {span.span_id}"
            )
        fallback_pieces.extend(fallback_tokens[cursor : span.start_word_index])
        entry = entries_by_span.get(span.span_id)
        if entry is None:
            missing_feedback_span_ids.append(span.span_id)
            confirmed_span = ConfirmedSpan(
                span_id=span.span_id,
                action=None,
                original_text=span.text,
                confirmed_text=span.text,
                resolved=False,
                note="missing_feedback_keep_asr_text",
            )
        else:
            confirmed_span = _apply_entry_to_span(record, span, entry)
            if not confirmed_span.resolved:
                unresolved_span_ids.append(span.span_id)
        fallback_pieces.append(confirmed_span.confirmed_text)
        char_range = _char_range_for_span(record, span)
        if char_range is None:
            char_replay_available = False
        else:
            replacements.append((*char_range, confirmed_span.confirmed_text))
        applied_spans.append(confirmed_span)
        cursor = span.end_word_index

    fallback_pieces.extend(fallback_tokens[cursor:])
    if char_replay_available:
        confirmed_transcript = record.asr_transcript
        for start_char, end_char, replacement in reversed(replacements):
            confirmed_transcript = (
                confirmed_transcript[:start_char]
                + replacement
                + confirmed_transcript[end_char:]
            )
    else:
        confirmed_transcript = " ".join(
            piece for piece in fallback_pieces if piece.strip()
        )

    if require_feedback_for_all_spans and missing_feedback_span_ids:
        raise ValueError(
            "存在未反馈 span，无法在 require_feedback_for_all_spans=True 时生成确认转写："
            + ", ".join(missing_feedback_span_ids)
        )

    action_counter = Counter(
        span.action.value if span.action is not None else "missing_feedback"
        for span in applied_spans
    )
    confirmation_status = (
        ConfirmationStatus.CONFIRMED
        if not missing_feedback_span_ids and not unresolved_span_ids
        else ConfirmationStatus.NEEDS_REVIEW
    )
    return ConfirmedTranscriptRecord(
        record_id=record.record_id,
        sample_id=record.sample_id,
        dataset=record.dataset,
        split=record.split,
        consultation_id=record.consultation_id,
        source_channel=record.source_channel,
        asr_transcript=record.asr_transcript,
        confirmed_transcript=confirmed_transcript,
        confirmation_status=confirmation_status,
        applied_spans=applied_spans,
        missing_feedback_span_ids=missing_feedback_span_ids,
        unresolved_span_ids=unresolved_span_ids,
        action_summary=dict(action_counter),
        metadata={
            "generated_by": T035_GENERATED_BY,
            "source_feedback_entries": len(entries_by_span),
            "policy": {
                "select_alternative": "replace span text or target word with selected candidate",
                "manual_edit": "replace span text with reviewer-provided text",
                "accept_asr": "keep ASR text and mark span resolved",
                "reject": "keep ASR text but mark span unresolved",
                "unable_to_judge": "keep ASR text but mark span unresolved",
                "missing_feedback": "keep ASR text but mark span unresolved",
            },
        },
    )


def write_confirmed_transcripts_jsonl(
    records: Iterable[ConfirmedTranscriptRecord],
    path: str | Path,
) -> None:
    """写入 confirmed transcript JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


def build_review_html(
    samples: Iterable[ReviewSample],
    *,
    title: str = "ASR 置信度医生审阅 demo",
    interactive: bool = True,
    html_output_path: str | Path | None = None,
    project_root: str | Path = PROJECT_ROOT,
) -> str:
    """生成可单文件打开的 HTML。

    `interactive=True` 时，页面可点击 span、选择候选/手动编辑/拒绝/无法判断，
    并把反馈导出为 JSONL。静态 HTML 无后端写文件能力，因此“保存”采用
    localStorage 暂存 + 浏览器下载文件两种方式。
    """

    payload_records = []
    output_parent = (
        Path(html_output_path).resolve().parent
        if html_output_path is not None
        else None
    )
    active_project_root = Path(project_root).resolve()
    for sample in samples:
        payload = sample.model_dump(mode="json")
        audio_filepath = sample.audio_filepath
        if audio_filepath:
            audio_path = Path(audio_filepath)
            if not audio_path.is_absolute():
                audio_path = active_project_root / audio_path
            if output_parent is not None:
                try:
                    audio_url = Path(
                        os.path.relpath(audio_path.resolve(), output_parent)
                    ).as_posix()
                except ValueError:
                    audio_url = audio_path.resolve().as_uri()
            else:
                audio_url = Path(audio_filepath).as_posix()
            payload["metadata"] = {
                **payload.get("metadata", {}),
                "review_audio_url": audio_url,
                "review_audio_clip_padding_sec": 1.5,
            }
        payload_records.append(payload)

    sample_payload = json.dumps(payload_records, ensure_ascii=False).replace(
        "</", "<\\/"
    )
    interactive_literal = "true" if interactive else "false"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --brand-900: #073f46;
      --brand-800: #075962;
      --brand-700: #08717b;
      --brand-100: #dff4f2;
      --brand-50: #f1faf9;
      --green: #e3f5e8;
      --green-border: #2f8f5b;
      --yellow: #fff3c7;
      --yellow-border: #b27700;
      --red: #ffe4e1;
      --red-border: #c7443d;
      --unknown: #edf0f2;
      --ink: #18333a;
      --muted: #60777d;
      --panel: #ffffff;
      --line: #d7e3e4;
      --soft-shadow: 0 12px 34px rgba(22, 72, 78, 0.09);
      font-family: Inter, "Noto Sans SC", "Microsoft YaHei", -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      min-width: 320px;
      background: #f2f7f7;
      color: var(--ink);
      line-height: 1.6;
    }}
    button, input, select, textarea {{ font: inherit; }}
    button:focus-visible, input:focus-visible, select:focus-visible,
    textarea:focus-visible, [tabindex]:focus-visible {{
      outline: 3px solid rgba(8, 113, 123, 0.28);
      outline-offset: 2px;
    }}
    header {{
      background: linear-gradient(125deg, var(--brand-900), var(--brand-700));
      color: white;
      border-bottom: 4px solid #70c6bf;
    }}
    .header-inner {{
      max-width: 1560px;
      margin: 0 auto;
      padding: 22px clamp(18px, 4vw, 48px) 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .brand-mark {{
      width: 44px;
      height: 44px;
      display: grid;
      place-items: center;
      border-radius: 13px;
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.32);
      font-size: 28px;
      font-weight: 300;
    }}
    header h1 {{ margin: 0; font-size: clamp(20px, 2.2vw, 28px); letter-spacing: 0.01em; }}
    header p {{ margin: 2px 0 0; color: #d7efed; font-size: 14px; }}
    .research-badge {{
      flex: none;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.25);
      color: #f5fffe;
      font-size: 13px;
    }}
    .privacy-strip {{
      padding: 8px 18px;
      background: #fff8df;
      color: #6a5312;
      border-bottom: 1px solid #ead997;
      text-align: center;
      font-size: 13px;
    }}
    .workspace-toolbar {{
      position: sticky;
      top: 0;
      z-index: 30;
      background: rgba(242,247,247,0.96);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--line);
    }}
    .toolbar-inner {{
      max-width: 1560px;
      margin: 0 auto;
      min-height: 74px;
      padding: 10px clamp(18px, 4vw, 48px);
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .conversation-picker {{ position: relative; min-width: min(440px, 58vw); }}
    .conversation-trigger {{
      width: 100%;
      min-height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 9px 14px;
      border: 1px solid #b9d1d3;
      border-radius: 12px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(22,72,78,0.05);
      text-align: left;
    }}
    .conversation-trigger:hover {{ border-color: var(--brand-700); }}
    .trigger-copy {{ min-width: 0; display: grid; }}
    .trigger-label {{ font-size: 12px; color: var(--muted); }}
    .trigger-value {{ font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .chevron {{ color: var(--brand-700); transition: transform 0.18s ease; }}
    .conversation-trigger[aria-expanded="true"] .chevron {{ transform: rotate(180deg); }}
    .conversation-menu {{
      position: absolute;
      top: calc(100% + 8px);
      left: 0;
      width: min(560px, calc(100vw - 36px));
      max-height: min(68vh, 620px);
      display: none;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: white;
      box-shadow: 0 22px 55px rgba(13, 63, 69, 0.2);
    }}
    .conversation-menu.open {{ display: grid; grid-template-rows: auto minmax(0,1fr); }}
    .menu-search-wrap {{ padding: 12px; border-bottom: 1px solid var(--line); }}
    .menu-search {{
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      color: var(--ink);
    }}
    .conversation-list {{ padding: 8px; overflow-y: auto; }}
    .conversation-option {{
      width: 100%;
      display: grid;
      grid-template-columns: 38px minmax(0,1fr) auto;
      align-items: center;
      gap: 10px;
      padding: 10px;
      border: 0;
      border-radius: 10px;
      color: var(--ink);
      background: transparent;
      cursor: pointer;
      text-align: left;
    }}
    .conversation-option:hover {{ background: var(--brand-50); }}
    .conversation-option.active {{ background: var(--brand-100); color: var(--brand-900); }}
    .option-index {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
    .option-title {{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 650; }}
    .option-meta {{ font-size: 12px; color: var(--muted); }}
    .nav-button, .primary-button, .secondary-button, .ghost-button {{
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      cursor: pointer;
      transition: background 0.15s ease, transform 0.15s ease;
    }}
    .nav-button {{ width: 44px; height: 44px; padding: 0; background: white; color: var(--brand-800); border: 1px solid var(--line); font-size: 18px; }}
    .primary-button {{ background: var(--brand-700); color: white; font-weight: 650; }}
    .primary-button:hover {{ background: var(--brand-800); }}
    .secondary-button {{ background: var(--brand-100); color: var(--brand-900); font-weight: 650; }}
    .ghost-button {{ background: #eef3f3; color: var(--ink); }}
    button:active {{ transform: translateY(1px); }}
    button:disabled {{ opacity: 0.46; cursor: not-allowed; transform: none; }}
    .toolbar-stats {{ margin-left: auto; display: flex; align-items: center; gap: 10px; }}
    .progress-copy {{ min-width: 150px; text-align: right; font-size: 13px; color: var(--muted); }}
    .progress-track {{ width: 150px; height: 8px; overflow: hidden; border-radius: 999px; background: #dbe7e8; }}
    .progress-fill {{ width: 0; height: 100%; border-radius: inherit; background: var(--brand-700); transition: width 0.2s ease; }}
    main {{
      max-width: 1560px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(350px, 430px);
      align-items: start;
      gap: 20px;
      padding: 22px clamp(18px, 4vw, 48px) 56px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--soft-shadow);
    }}
    .sample {{ padding: clamp(18px, 3vw, 32px); min-height: 72vh; }}
    .sample-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }}
    .sample-title {{ margin: 0; font-size: clamp(19px, 2vw, 24px); color: var(--brand-900); }}
    .sample-subtitle {{ margin: 5px 0 0; color: var(--muted); font-size: 14px; }}
    .sample-actions {{ flex: none; display: flex; gap: 8px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #f7faf9;
    }}
    .legend {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 20px; }}
    .legend-swatch {{ width: 10px; height: 10px; border-radius: 3px; border: 1px solid; }}
    .legend-swatch.green {{ background: var(--green); border-color: var(--green-border); }}
    .legend-swatch.yellow {{ background: var(--yellow); border-color: var(--yellow-border); }}
    .legend-swatch.red {{ background: var(--red); border-color: var(--red-border); }}
    .legend-swatch.unknown {{ background: var(--unknown); border-color: #8a989b; }}
    .instruction {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 18px;
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--brand-50);
      color: var(--brand-900);
      font-size: 14px;
    }}
    .transcript {{
      font-family: Georgia, "Noto Serif SC", "Songti SC", serif;
      font-size: clamp(17px, 1.45vw, 20px);
      line-height: 2.12;
      word-break: break-word;
      letter-spacing: 0.005em;
    }}
    .conversation-turns {{ display: grid; gap: 12px; }}
    .speaker-turn {{
      display: grid;
      grid-template-columns: minmax(92px, 132px) minmax(0, 1fr);
      gap: 14px;
      padding: 12px 14px;
      border: 1px solid #e2ebeb;
      border-radius: 12px;
      background: #fbfdfd;
    }}
    .speaker-tag {{
      align-self: start;
      padding: 5px 8px;
      border-radius: 8px;
      background: var(--brand-100);
      color: var(--brand-900);
      font-size: 12px;
      font-weight: 800;
      text-align: center;
      overflow-wrap: anywhere;
    }}
    .speaker-tag.unknown {{ background: var(--unknown); color: var(--muted); }}
    .turn-time {{ display: block; margin-top: 3px; color: var(--muted); font-size: 10px; font-weight: 500; }}
    .word {{
      border-radius: 6px;
      padding: 2px 4px;
      margin: 0 1px;
      border: 1px solid transparent;
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
    }}
    .word.green {{ background: var(--green); border-color: transparent; color: #225f42; }}
    .word.yellow {{ background: var(--yellow); border-color: #e7ca71; color: #6b4e08; }}
    .word.red {{ background: var(--red); border-color: #e9a6a1; color: #842b27; }}
    .word.unknown {{ background: var(--unknown); border-color: #b8c1c3; }}
    .word.neutral {{ background: transparent; border-color: transparent; color: var(--ink); }}
    .word.medical-entity {{ font-weight: 700; }}
    .word.reviewable {{ cursor: pointer; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 4px; }}
    .word.reviewable:hover {{ filter: saturate(1.15); box-shadow: 0 2px 8px rgba(24,51,58,0.12); }}
    .word.active {{ outline: 3px solid var(--brand-700); outline-offset: 2px; text-decoration: none; }}
    .word.resolved::after {{ content: "✓"; margin-left: 2px; font: 700 10px/1 sans-serif; color: var(--brand-800); }}
    .audio-cue-button {{
      width: 25px;
      height: 25px;
      margin: 0 4px 0 1px;
      padding: 0;
      display: inline-grid;
      place-items: center;
      vertical-align: middle;
      border: 1px solid #91b8bb;
      border-radius: 50%;
      background: #f4fbfa;
      color: var(--brand-800);
      cursor: pointer;
      font: 700 12px/1 sans-serif;
    }}
    .audio-cue-button:hover, .audio-cue-button.playing {{ background: var(--brand-700); color: white; border-color: var(--brand-700); }}
    .audio-panel {{ margin: 12px 0; padding: 11px 12px; border: 1px solid #b8d6d7; border-radius: 11px; background: #f4fbfa; }}
    .audio-panel-row {{ display: flex; align-items: center; gap: 9px; }}
    .audio-panel-row button {{ flex: none; }}
    .audio-status {{ margin-top: 5px; color: var(--muted); font-size: 12px; }}
    .panel {{
      position: sticky;
      top: 96px;
      max-height: calc(100vh - 118px);
      overflow-y: auto;
      padding: 20px;
      scrollbar-gutter: stable;
    }}
    .panel-empty {{ min-height: 240px; display: grid; place-content: center; text-align: center; color: var(--muted); }}
    .panel-empty-icon {{ width: 52px; height: 52px; margin: 0 auto 10px; display: grid; place-items: center; border-radius: 50%; background: var(--brand-100); color: var(--brand-800); font-size: 24px; }}
    .panel-title {{ margin: 0; color: var(--brand-900); font-size: 20px; }}
    .panel-meta {{ margin: 5px 0 14px; color: var(--muted); font-size: 13px; }}
    .risk-label {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .risk-label.yellow {{ background: var(--yellow); color: #755400; }}
    .risk-label.red {{ background: var(--red); color: #96352f; }}
    .asr-original {{ margin: 12px 0; padding: 12px; border-left: 4px solid var(--brand-700); border-radius: 0 10px 10px 0; background: var(--brand-50); }}
    .section-label {{ margin: 16px 0 8px; font-size: 12px; font-weight: 800; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }}
    .candidate-list, .action-list {{ display: grid; gap: 8px; }}
    .choice-card {{
      position: relative;
      display: grid;
      grid-template-columns: 20px minmax(0,1fr);
      align-items: start;
      gap: 10px;
      margin: 0;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 11px;
      background: white;
      cursor: pointer;
    }}
    .choice-card:hover {{ border-color: #8fb8bb; background: #fbfefe; }}
    .choice-card:has(input:checked) {{ border-color: var(--brand-700); background: var(--brand-50); box-shadow: inset 0 0 0 1px var(--brand-700); }}
    .choice-card input {{ margin-top: 4px; accent-color: var(--brand-700); }}
    .choice-title {{ display: block; font-weight: 700; color: var(--ink); }}
    .choice-help {{ display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }}
    textarea, input[type="text"] {{ width: 100%; padding: 10px 11px; border: 1px solid var(--line); border-radius: 9px; color: var(--ink); background: white; resize: vertical; }}
    textarea {{ min-height: 76px; }}
    .panel-actions {{ position: sticky; bottom: -20px; display: flex; gap: 8px; margin: 18px -20px -20px; padding: 14px 20px; border-top: 1px solid var(--line); background: rgba(255,255,255,0.97); }}
    .panel-actions button:first-child {{ flex: 1; }}
    .span-nav {{ display: flex; gap: 8px; margin-bottom: 12px; }}
    .span-nav button {{ flex: 1; }}
    .muted {{ color: var(--muted); }}
    .no-candidates {{ margin: 8px 0; padding: 10px; border-radius: 9px; background: #f6f8f8; color: var(--muted); font-size: 13px; }}
    .jsonl-output {{ display: none; white-space: pre-wrap; overflow-wrap: anywhere; background: #122a2e; color: #e5f2f1; border-radius: 10px; padding: 10px; max-height: 180px; overflow: auto; font-size: 12px; }}
    .export-bar {{ max-width: 1560px; margin: -34px auto 44px; padding: 0 clamp(18px, 4vw, 48px); display: flex; justify-content: flex-end; gap: 8px; }}
    .toast {{ position: fixed; left: 50%; bottom: 28px; z-index: 80; transform: translate(-50%, 16px); padding: 10px 16px; border-radius: 999px; background: var(--brand-900); color: white; opacity: 0; pointer-events: none; transition: opacity 0.18s ease, transform 0.18s ease; box-shadow: 0 10px 30px rgba(0,0,0,0.18); }}
    .toast.show {{ opacity: 1; transform: translate(-50%, 0); }}
    .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }}
    @media (max-width: 1020px) {{
      .toolbar-stats {{ display: none; }}
      main {{ grid-template-columns: 1fr; }}
      .panel {{ position: fixed; z-index: 50; inset: auto 0 0; top: auto; max-height: min(76vh, 700px); border-radius: 20px 20px 0 0; transform: translateY(calc(100% + 12px)); transition: transform 0.22s ease; box-shadow: 0 -18px 55px rgba(13,63,69,0.2); }}
      .panel.open {{ transform: translateY(0); }}
      .panel-close {{ display: inline-flex !important; }}
      .export-bar {{ margin-top: -34px; }}
    }}
    @media (max-width: 680px) {{
      .header-inner {{ align-items: flex-start; }}
      .research-badge {{ display: none; }}
      .toolbar-inner {{ flex-wrap: wrap; }}
      .conversation-picker {{ order: -1; width: 100%; min-width: 0; }}
      .nav-button {{ flex: 1; height: 38px; }}
      .sample-header {{ display: block; }}
      .sample-actions {{ margin-top: 12px; }}
      .sample {{ padding: 18px; }}
      .transcript {{ font-size: 17px; line-height: 2.2; }}
      .speaker-turn {{ grid-template-columns: 1fr; gap: 8px; }}
      .speaker-tag {{ width: fit-content; text-align: left; }}
      .word {{ padding: 3px 4px; }}
      .export-bar {{ justify-content: stretch; flex-wrap: wrap; }}
      .export-bar button {{ flex: 1; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">＋</div>
        <div>
          <h1>{html.escape(title)}</h1>
          <p>临床语音转写 · 置信度辅助确认工作台</p>
        </div>
      </div>
      <span class="research-badge">研究原型 · Research Prototype</span>
    </div>
  </header>
  <div class="privacy-strip">仅用于研究评估，不构成临床建议；请勿输入真实患者隐私或未脱敏病例内容。</div>
  <nav class="workspace-toolbar" aria-label="对话审阅导航">
    <div class="toolbar-inner">
      <div class="conversation-picker">
        <button class="conversation-trigger" id="conversation-trigger" type="button" aria-expanded="false" aria-controls="conversation-menu">
          <span class="trigger-copy">
            <span class="trigger-label">当前对话</span>
            <span class="trigger-value" id="conversation-current">正在载入…</span>
          </span>
          <span class="chevron" aria-hidden="true">⌄</span>
        </button>
        <div class="conversation-menu" id="conversation-menu">
          <div class="menu-search-wrap">
            <label class="sr-only" for="conversation-search">搜索对话</label>
            <input class="menu-search" id="conversation-search" type="search" placeholder="搜索编号、会诊 ID 或说话人…" autocomplete="off">
          </div>
          <div class="conversation-list" id="conversation-list" role="listbox" aria-label="选择对话"></div>
        </div>
      </div>
      <button class="nav-button" id="previous-conversation" type="button" aria-label="上一段对话" title="上一段对话">←</button>
      <button class="nav-button" id="next-conversation" type="button" aria-label="下一段对话" title="下一段对话">→</button>
      <div class="toolbar-stats" aria-live="polite">
        <div class="progress-copy" id="progress-copy">已确认 0 / 0</div>
        <div class="progress-track" aria-hidden="true"><div class="progress-fill" id="progress-fill"></div></div>
      </div>
    </div>
  </nav>
  <main>
    <section id="samples"></section>
    <aside class="card panel" id="review-panel" aria-live="polite">
      <div class="panel-empty">
        <div class="panel-empty-icon" aria-hidden="true">✓</div>
        <strong>选择需要确认的词</strong>
        <span>点击黄色或红色词后，可选择候选、手动修正或保留原文。</span>
      </div>
    </aside>
  </main>
  <div class="export-bar">
    <button class="secondary-button" id="export-feedback" type="button" {'' if interactive else 'disabled'}>下载反馈 JSONL</button>
    <button class="ghost-button" id="toggle-feedback" type="button" {'' if interactive else 'disabled'}>查看反馈记录</button>
    <div id="feedback-preview" class="jsonl-output"></div>
  </div>
  <audio id="review-audio" preload="metadata"></audio>
  <div class="toast" id="toast" role="status" aria-live="polite"></div>
  <script id="review-data" type="application/json">{sample_payload}</script>
  <script>
    const SAMPLES = JSON.parse(document.getElementById('review-data').textContent);
    const CONVERSATIONS = groupSamplesByConversation(SAMPLES);
    const INTERACTIVE = {interactive_literal};
    const FEEDBACK_SCHEMA = "{FEEDBACK_ENTRY_SCHEMA_VERSION}";
    const CLINICAL_WARNING = "{html.escape(CLINICAL_USE_WARNING)}";
    const STORAGE_KEY = 'clinical_asr_review_state_v2';
    const AUDIO_PADDING_SEC = 1.5;
    const feedbackState = new Map();
    let activeKey = null;
    let activeConversationIndex = 0;
    let toastTimer = null;
    let audioStopAt = null;
    let audioActiveKey = null;
    let audioRequestToken = 0;

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[char]));
    }}

    function sampleKey(sample) {{
      return sample.record_id || sample.sample_id;
    }}

    function sampleStartSec(sample) {{
      const values = [
        ...(sample.words || []).map(word => Number(word.start_sec)),
        ...(sample.segments || []).map(segment => Number(segment.start_sec))
      ].filter(Number.isFinite);
      return values.length ? Math.min(...values) : Number.POSITIVE_INFINITY;
    }}

    function groupSamplesByConversation(samples) {{
      const groups = new Map();
      for (const sample of samples) {{
        const consultationId = sample.consultation_id || sample.sample_id;
        const key = `${{sample.dataset}}::${{consultationId}}`;
        if (!groups.has(key)) groups.set(key, {{ key, consultation_id: consultationId, dataset: sample.dataset, samples: [] }});
        groups.get(key).samples.push(sample);
      }}
      return Array.from(groups.values()).map(group => ({{
        ...group,
        samples: group.samples.sort((left, right) => sampleStartSec(left) - sampleStartSec(right) || left.sample_id.localeCompare(right.sample_id))
      }}));
    }}

    function activeConversation() {{
      return CONVERSATIONS[activeConversationIndex] || null;
    }}

    function spanKey(sample, span) {{
      return `${{sampleKey(sample)}}::${{span.span_id}}`;
    }}

    function confidenceText(value) {{
      return value === null || value === undefined ? 'NA' : Number(value).toFixed(3);
    }}

    function channelText(channel) {{
      return channel === 'doctor' ? '医生声道' : channel === 'patient' ? '患者声道' : (channel || '混合声道');
    }}

    function audioUrlForSample(sample) {{
      const path = sample.metadata?.review_audio_url || sample.audio_filepath;
      if (!path) return '';
      try {{ return new URL(path, document.baseURI).href; }}
      catch (error) {{ console.warn('无法解析音频路径', error); return ''; }}
    }}

    function formatSeconds(value) {{
      return Number.isFinite(Number(value)) ? `${{Number(value).toFixed(2)}} 秒` : '未知时间';
    }}

    function setAudioStatus(message, activeAudioKey = null) {{
      const status = document.getElementById('audio-status');
      if (status) status.textContent = message;
      document.querySelectorAll('.audio-cue-button.playing').forEach(button => button.classList.remove('playing'));
      if (activeAudioKey) {{
        document.querySelectorAll(`[data-audio-key="${{CSS.escape(activeAudioKey)}}"]`).forEach(button => button.classList.add('playing'));
      }}
    }}

    function stopAudioPlayback(message = '') {{
      audioRequestToken += 1;
      const audio = document.getElementById('review-audio');
      audio.pause();
      audioStopAt = null;
      audioActiveKey = null;
      setAudioStatus(message || '点击播放键可回听附近原始音频');
    }}

    function recordAudioPlay(sample, span, clipStart, clipEnd) {{
      const state = getState(sample, span);
      state.audio_play_count = Number(state.audio_play_count || 0) + 1;
      state.last_audio_window = {{ start_sec: clipStart, end_sec: clipEnd }};
      feedbackState.set(spanKey(sample, span), state);
      persistState();
    }}

    function playAudioClip(sample, span, startSec, endSec, label, requestedKey) {{
      const audio = document.getElementById('review-audio');
      const audioUrl = audioUrlForSample(sample);
      const rawStart = Number(startSec);
      const rawEnd = Number(endSec);
      if (!audioUrl || !Number.isFinite(rawStart) || !Number.isFinite(rawEnd)) {{
        showToast('当前词缺少可用音频路径或时间戳');
        setAudioStatus('音频不可用：缺少路径或时间戳');
        return;
      }}
      if (audioActiveKey === requestedKey && !audio.paused) {{
        stopAudioPlayback('已暂停，可再次点击重播');
        return;
      }}

      const requestToken = ++audioRequestToken;
      const clipStart = Math.max(0, rawStart - AUDIO_PADDING_SEC);
      const desiredEnd = Math.max(clipStart + 0.2, rawEnd + AUDIO_PADDING_SEC);
      audio.pause();
      audioStopAt = null;
      audioActiveKey = null;
      setAudioStatus(`正在加载 ${{label}}附近音频…`);

      const beginPlayback = () => {{
        if (requestToken !== audioRequestToken) return;
        const clipEnd = Number.isFinite(audio.duration)
          ? Math.min(desiredEnd, audio.duration)
          : desiredEnd;
        try {{ audio.currentTime = Math.min(clipStart, Math.max(0, clipEnd - 0.05)); }}
        catch (error) {{ console.warn('音频定位失败', error); }}
        audio.play().then(() => {{
          if (requestToken !== audioRequestToken) return;
          audioStopAt = clipEnd;
          audioActiveKey = requestedKey;
          setAudioStatus(`正在播放 ${{label}}：${{formatSeconds(clipStart)}}–${{formatSeconds(clipEnd)}}`, requestedKey);
          recordAudioPlay(sample, span, clipStart, clipEnd);
        }}).catch(error => {{
          console.warn('音频播放失败', error);
          setAudioStatus('播放失败：请确认音频文件路径和浏览器本地文件权限');
          showToast('音频播放失败，请检查本地文件访问权限');
        }});
      }};

      const resolvedUrl = new URL(audioUrl, document.baseURI).href;
      if (audio.src !== resolvedUrl) {{
        audio.src = resolvedUrl;
        audio.load();
      }}
      if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) beginPlayback();
      else audio.addEventListener('loadedmetadata', beginPlayback, {{ once: true }});
    }}

    function conversationTitle(conversation, index) {{
      return `第 ${{index + 1}} 例 · ${{conversation.consultation_id}} · 完整对话`;
    }}

    function renderConversationList(query = '') {{
      const normalized = query.trim().toLowerCase();
      const list = document.getElementById('conversation-list');
      const options = CONVERSATIONS.map((conversation, index) => ({{ conversation, index }})).filter(({{ conversation, index }}) => {{
        const sampleText = conversation.samples.map(sample => `${{sample.sample_id}} ${{sample.source_channel || ''}}`).join(' ');
        const haystack = `${{index + 1}} ${{conversation.consultation_id}} ${{conversation.dataset}} ${{sampleText}}`.toLowerCase();
        return !normalized || haystack.includes(normalized);
      }});
      list.innerHTML = options.map(({{ conversation, index }}) => `
        <button class="conversation-option ${{index === activeConversationIndex ? 'active' : ''}}" type="button" role="option"
          aria-selected="${{index === activeConversationIndex}}" data-conversation-index="${{index}}">
          <span class="option-index">${{String(index + 1).padStart(2, '0')}}</span>
          <span class="option-title">${{escapeHtml(conversation.consultation_id)}}</span>
          <span class="option-meta">完整对话 · ${{conversation.samples.length}} 个推理窗口 · ${{conversation.samples.reduce((sum, sample) => sum + sample.uncertain_spans.length, 0)}} 待审</span>
        </button>`).join('') || '<p class="muted" style="padding:12px">没有匹配的对话。</p>';
      list.querySelectorAll('[data-conversation-index]').forEach(button => {{
        button.addEventListener('click', () => setActiveSample(Number(button.dataset.conversationIndex)));
      }});
    }}

    function openConversationMenu(force) {{
      const trigger = document.getElementById('conversation-trigger');
      const menu = document.getElementById('conversation-menu');
      const shouldOpen = force ?? !menu.classList.contains('open');
      menu.classList.toggle('open', shouldOpen);
      trigger.setAttribute('aria-expanded', String(shouldOpen));
      if (shouldOpen) {{
        renderConversationList(document.getElementById('conversation-search').value);
        window.setTimeout(() => document.getElementById('conversation-search').focus(), 0);
      }}
    }}

    function setActiveSample(index, options = {{}}) {{
      if (!CONVERSATIONS.length) return;
      stopAudioPlayback();
      activeConversationIndex = Math.max(0, Math.min(CONVERSATIONS.length - 1, index));
      activeKey = null;
      openConversationMenu(false);
      renderSample();
      renderConversationList(document.getElementById('conversation-search').value);
      renderPanelEmpty();
      updateProgress();
      if (options.scroll !== false) window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }}

    function separatorBefore(word, index) {{
      if (index === 0) return '';
      const explicit = word.metadata?.separator_before;
      if (typeof explicit === 'string') return explicit;
      return /^[A-Za-z0-9]/.test(word.text || '') ? ' ' : '';
    }}

    function joinWordsForDisplay(words) {{
      return words.map((word, index) => `${{separatorBefore(word, index)}}${{word.text}}`).join('');
    }}

    function speakerIdentity(sample, word) {{
      const diarization = word.metadata?.diarization || {{}};
      const role = word.metadata?.speaker_role || diarization.speaker_role || null;
      const semantic = Boolean(diarization.semantic_resolution);
      const direct = String(word.speaker_label || '').trim();
      if (direct && !['mixed', 'unknown', 'speaker_unknown'].includes(direct.toLowerCase())) return {{ label: direct, role, source: diarization.speaker_label_source || 'word', semantic }};
      const segment = (sample.segments || []).find(item => item.start_word_index <= word.word_index && word.word_index < item.end_word_index);
      const segmentLabel = String(segment?.speaker_label || '').trim();
      if (segmentLabel && !['mixed', 'unknown', 'speaker_unknown'].includes(segmentLabel.toLowerCase())) return {{ label: segmentLabel, role: role || segment?.metadata?.speaker_role || null, source: 'segment' }};
      if (['doctor', 'patient'].includes(sample.source_channel)) return {{ label: sample.source_channel, role: role || sample.source_channel, source: 'source_channel' }};
      return {{ label: 'speaker_unknown', role, source: 'missing' }};
    }}

    function buildSpeakerRuns(sample) {{
      const runs = [];
      for (const word of sample.words || []) {{
        const identity = speakerIdentity(sample, word);
        const identityKey = `${{identity.label}}::${{identity.role || ''}}`;
        let run = runs[runs.length - 1];
        if (!run || run.identityKey !== identityKey) {{
          run = {{ ...identity, identityKey, words: [] }};
          runs.push(run);
        }}
        run.semantic = Boolean(run.semantic || identity.semantic);
        run.words.push(word);
      }}
      if (!runs.length && sample.asr_transcript) runs.push({{ label: 'speaker_unknown', role: null, source: 'missing', identityKey: 'speaker_unknown', words: [] }});
      return runs;
    }}

    function speakerDisplay(identity) {{
      let display = identity.label;
      if (identity.role === 'doctor' || identity.label === 'doctor') display = '医生';
      else if (identity.role === 'patient' || identity.label === 'patient') display = '患者';
      else if (identity.role === 'family_or_caregiver') display = '家属/照护者';
      else if (identity.role === 'staff') display = '工作人员';
      else if (identity.label === 'speaker_unknown') display = '说话人待分离';
      return identity.semantic ? `${{display}}（含语义补全）` : display;
    }}

    function renderReviewWord(sample, word, displayPosition) {{
      const key = sampleKey(sample);
      const level = word.confidence_level || 'unknown';
      const entityMeta = word.metadata?.medical_entity_review || {{}};
      const displayLevel = entityMeta.display_confidence_level || level;
      const isMedical = Boolean(entityMeta.is_medical_entity);
      const reviewable = Boolean(word.span_ids?.length);
      const firstSpan = reviewable ? word.span_ids[0] : '';
      const span = reviewable ? sample.uncertain_spans.find(item => item.span_id === firstSpan) : null;
      const resolved = span ? Boolean(feedbackState.get(spanKey(sample, span))?.reviewed) : false;
      const title = `词 #${{word.word_index}} · 置信度 ${{confidenceText(word.confidence)}} · ${{level}}`;
      const audioKey = `${{key}}::${{firstSpan}}::word-${{word.word_index}}`;
      const canPlayWord = reviewable && span && ['yellow', 'red'].includes(displayLevel)
        && word.start_sec !== null && word.start_sec !== undefined
        && word.end_sec !== null && word.end_sec !== undefined
        && Boolean(audioUrlForSample(sample));
      const audioButton = canPlayWord ? `<button class="audio-cue-button" type="button"
        data-audio-cue="word" data-audio-key="${{escapeHtml(audioKey)}}"
        data-sample-key="${{escapeHtml(key)}}" data-span-id="${{escapeHtml(firstSpan)}}"
        data-word-index="${{word.word_index}}" title="播放“${{escapeHtml(word.text)}}”附近原始音频"
        aria-label="播放词 ${{escapeHtml(word.text)}} 附近原始音频">▶</button>` : '';
      return `${{escapeHtml(separatorBefore(word, displayPosition))}}<span class="word ${{displayLevel}} ${{isMedical ? 'medical-entity' : ''}} ${{reviewable ? 'reviewable' : ''}} ${{resolved ? 'resolved' : ''}}"
        data-sample-key="${{escapeHtml(key)}}" data-span-id="${{escapeHtml(firstSpan)}}"
        ${{reviewable ? 'role="button" tabindex="0"' : ''}} title="${{escapeHtml(title)}}">${{escapeHtml(word.text)}}</span>${{audioButton}}`;
    }}

    function renderSample() {{
      const conversation = activeConversation();
      const container = document.getElementById('samples');
      if (!conversation) {{
        container.innerHTML = '<article class="card sample"><p class="muted">没有可显示的对话数据。</p></article>';
        return;
      }}
      const medicalEntityMode = conversation.samples.some(sample => sample.review_policy?.target_scope === 'llm_identified_medical_entities_only');
      const semanticSpeakerMode = conversation.samples.some(sample => (sample.words || []).some(word => Boolean(word.metadata?.diarization?.semantic_resolution)));
      const legend = medicalEntityMode ? `
          <span class="badge"><span class="legend-swatch green"></span>医疗实体高置信</span>
          <span class="badge"><span class="legend-swatch yellow"></span>医疗实体中置信</span>
          <span class="badge"><span class="legend-swatch red"></span>医疗实体低置信</span>
          <span class="badge"><span class="legend-swatch unknown"></span>置信度缺失</span>
          <span class="badge"><span class="word neutral">普通黑字</span>非重点上下文</span>` : `
          <span class="badge"><span class="legend-swatch green"></span>高置信 ≥ 0.90</span>
          <span class="badge"><span class="legend-swatch yellow"></span>中置信 0.80–0.90</span>
          <span class="badge"><span class="legend-swatch red"></span>低置信 &lt; 0.80</span>
          <span class="badge"><span class="legend-swatch unknown"></span>置信度缺失</span>`;
      const speakerLegend = semanticSpeakerMode ? '<span class="badge">“含语义补全”是 LLM 推断，不是声纹真值</span>' : '';
      const turns = conversation.samples.flatMap(sample => buildSpeakerRuns(sample).map(run => {{
        const start = run.words.find(word => word.start_sec !== null && word.start_sec !== undefined)?.start_sec;
        const end = [...run.words].reverse().find(word => word.end_sec !== null && word.end_sec !== undefined)?.end_sec;
        const transcript = run.words.length
          ? run.words.map((word, position) => renderReviewWord(sample, word, position)).join('')
          : escapeHtml(sample.asr_transcript || '');
        const unknownClass = run.label === 'speaker_unknown' ? 'unknown' : '';
        return `<div class="speaker-turn" data-sample-key="${{escapeHtml(sampleKey(sample))}}">
          <div class="speaker-tag ${{unknownClass}}">${{escapeHtml(speakerDisplay(run))}}<span class="turn-time">${{formatSeconds(start)}}–${{formatSeconds(end)}}</span></div>
          <div class="transcript" aria-label="${{escapeHtml(speakerDisplay(run))}} ASR 转写">${{transcript}}</div>
        </div>`;
      }})).join('');
      const allSpans = conversation.samples.flatMap(sample => sample.uncertain_spans.map(span => ({{ sample, span }})));
      const reviewedHere = allSpans.filter(item => feedbackState.get(spanKey(item.sample, item.span))?.reviewed).length;
      const wordCount = conversation.samples.reduce((sum, sample) => sum + sample.words.length, 0);
      container.innerHTML = `<article class="card sample" data-conversation-key="${{escapeHtml(conversation.key)}}">
        <div class="sample-header">
          <div>
            <h2 class="sample-title">${{escapeHtml(conversation.consultation_id)}}</h2>
            <p class="sample-subtitle">第 ${{activeConversationIndex + 1}} / ${{CONVERSATIONS.length}} 例 · 完整对话 · ${{conversation.samples.length}} 个内部推理窗口 · ${{wordCount}} 个 ASR 单元</p>
          </div>
          <div class="sample-actions">
            <span class="badge">${{reviewedHere}} / ${{allSpans.length}} 已确认</span>
            <button class="secondary-button" id="next-risk" type="button" ${{allSpans.length ? '' : 'disabled'}}>下一个待审词</button>
          </div>
        </div>
        <div class="legend">${{legend}}${{speakerLegend}}</div>
        <div class="instruction"><span aria-hidden="true">●</span><span>${{medicalEntityMode ? '当前按完整病例对话展示；医学实体优先显示置信度，点击黄色或红色实体进行确认。' : '当前按完整病例对话展示；点击带虚线的黄色或红色词进行确认。'}}</span></div>
        <div class="conversation-turns" aria-label="按说话人组织的完整 ASR 对话">${{turns}}</div>
      </article>`;
      container.querySelectorAll('.reviewable').forEach(node => {{
        const activate = () => selectSpan(node.dataset.sampleKey, node.dataset.spanId);
        node.addEventListener('click', activate);
        node.addEventListener('keydown', event => {{
          if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); activate(); }}
        }});
      }});
      container.querySelectorAll('[data-audio-cue="word"]').forEach(button => {{
        button.addEventListener('click', event => {{
          event.preventDefault();
          event.stopPropagation();
          const [targetSample, targetSpan] = findSampleAndSpan(button.dataset.sampleKey, button.dataset.spanId);
          if (!targetSample || !targetSpan) return;
          const word = targetSample.words.find(item => item.word_index === Number(button.dataset.wordIndex));
          if (!word) return;
          selectSpan(button.dataset.sampleKey, button.dataset.spanId);
          playAudioClip(targetSample, targetSpan, word.start_sec, word.end_sec, `词“${{word.text}}”`, button.dataset.audioKey);
        }});
      }});
      document.getElementById('next-risk')?.addEventListener('click', () => jumpToRelativeSpan(1, true));
      document.getElementById('conversation-current').textContent = conversationTitle(conversation, activeConversationIndex);
      document.getElementById('previous-conversation').disabled = activeConversationIndex === 0;
      document.getElementById('next-conversation').disabled = activeConversationIndex === CONVERSATIONS.length - 1;
    }}

    function findSampleAndSpan(targetSampleKey, spanId) {{
      const sample = SAMPLES.find(item => sampleKey(item) === targetSampleKey);
      if (!sample) return [null, null];
      const span = sample.uncertain_spans.find(item => item.span_id === spanId);
      return [sample, span];
    }}

    function selectSpan(targetSampleKey, spanId) {{
      const [sample, span] = findSampleAndSpan(targetSampleKey, spanId);
      if (!sample || !span) return;
      const nextActiveKey = spanKey(sample, span);
      if (activeKey && activeKey !== nextActiveKey) stopAudioPlayback();
      activeKey = nextActiveKey;
      document.querySelectorAll('.word.active').forEach(node => node.classList.remove('active'));
      document.querySelectorAll(`.word[data-sample-key="${{CSS.escape(targetSampleKey)}}"][data-span-id="${{CSS.escape(spanId)}}"]`)
        .forEach(node => node.classList.add('active'));
      renderPanel(sample, span);
      document.getElementById('review-panel').classList.add('open');
    }}

    function jumpToRelativeSpan(direction, unresolvedOnly = false) {{
      const conversation = activeConversation();
      const reviewItems = conversation?.samples.flatMap(sample =>
        sample.uncertain_spans.map(span => ({{ sample, span }}))) || [];
      if (!reviewItems.length) return;
      const currentIndex = activeKey
        ? reviewItems.findIndex(item => spanKey(item.sample, item.span) === activeKey)
        : (direction > 0 ? -1 : 0);
      for (let offset = 1; offset <= reviewItems.length; offset += 1) {{
        const index = (currentIndex + direction * offset + reviewItems.length) % reviewItems.length;
        const {{ sample, span: candidate }} = reviewItems[index];
        if (!unresolvedOnly || !feedbackState.get(spanKey(sample, candidate))?.reviewed) {{
          const node = document.querySelector(`.word[data-sample-key="${{CSS.escape(sampleKey(sample))}}"][data-span-id="${{CSS.escape(candidate.span_id)}}"]`);
          node?.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          selectSpan(sampleKey(sample), candidate.span_id);
          return;
        }}
      }}
      showToast('本例所有风险词都已确认');
    }}

    function getState(sample, span) {{
      const key = spanKey(sample, span);
      if (!feedbackState.has(key)) {{
        feedbackState.set(key, {{
          action: 'accept_asr',
          selected_alternative_id: '',
          manual_text: '',
          note: '',
          reviewed: false,
          audio_play_count: 0,
          last_audio_window: null
        }});
      }}
      const state = feedbackState.get(key);
      const validActions = new Set(['accept_asr', 'select_alternative', 'manual_edit', 'reject', 'unable_to_judge']);
      if (!validActions.has(state.action)) state.action = 'accept_asr';
      if (state.action !== 'select_alternative') state.selected_alternative_id = '';
      if (state.action === 'select_alternative' && !span.alternatives.some(alt => alt.alternative_id === state.selected_alternative_id)) {{
        state.action = 'accept_asr';
        state.selected_alternative_id = '';
      }}
      state.manual_text = state.manual_text || '';
      state.note = state.note || '';
      state.audio_play_count = Number(state.audio_play_count || 0);
      state.last_audio_window = state.last_audio_window || null;
      return state;
    }}

    function renderPanel(sample, span) {{
      const panel = document.getElementById('review-panel');
      const state = getState(sample, span);
      const candidateChoices = span.alternatives.map(alt => `
        <label class="choice-card">
          <input type="radio" name="decision" data-decision-action="select_alternative"
            value="${{escapeHtml(alt.alternative_id)}}" ${{state.action === 'select_alternative' && state.selected_alternative_id === alt.alternative_id ? 'checked' : ''}}>
          <span><span class="choice-title">${{escapeHtml(alt.text)}}</span><span class="choice-help">候选 #${{alt.rank}} · ${{escapeHtml(alt.source)}}${{alt.confidence !== null && alt.confidence !== undefined ? ` · 置信度 ${{confidenceText(alt.confidence)}}` : ''}}</span></span>
        </label>`).join('');
      const context = buildSpanContext(sample, span);
      const spanAudioKey = `${{spanKey(sample, span)}}::span`;
      const spanAudioAvailable = Boolean(audioUrlForSample(sample))
        && span.start_sec !== null && span.start_sec !== undefined
        && span.end_sec !== null && span.end_sec !== undefined;
      panel.innerHTML = `
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:start">
          <div><h2 class="panel-title">确认转写内容</h2><p class="panel-meta">${{escapeHtml(span.span_id)}} · 最低置信度 ${{confidenceText(span.min_confidence)}}</p></div>
          <button class="ghost-button panel-close" id="panel-close" type="button" style="display:none" aria-label="关闭审阅面板">关闭</button>
        </div>
        <div class="span-nav">
          <button class="ghost-button" id="previous-risk" type="button">← 上一个</button>
          <button class="ghost-button" id="next-risk-panel" type="button">下一个 →</button>
        </div>
        <span class="risk-label ${{escapeHtml(span.confidence_level)}}">${{span.confidence_level === 'red' ? '优先确认 · 低置信度' : '建议确认 · 中置信度'}}</span>
        <div class="audio-panel">
          <div class="audio-panel-row">
            <button class="secondary-button" id="play-span-audio" type="button" data-audio-key="${{escapeHtml(spanAudioKey)}}" ${{spanAudioAvailable ? '' : 'disabled'}}>▶ 播放附近原始音频</button>
            <span class="muted" style="font-size:12px">实体前后各 1.5 秒</span>
          </div>
          <div class="audio-status" id="audio-status" aria-live="polite">${{spanAudioAvailable ? `时间戳 ${{formatSeconds(span.start_sec)}}–${{formatSeconds(span.end_sec)}}` : '当前实体缺少音频路径或时间戳'}}</div>
        </div>
        <div class="section-label">局部语境</div>
        <div class="muted" style="font-size:13px">${{escapeHtml(context.left)}} <strong style="color:var(--ink)">[${{escapeHtml(span.text)}}]</strong> ${{escapeHtml(context.right)}}</div>
        <div class="section-label">ASR 原文</div>
        <div class="asr-original"><strong>${{escapeHtml(span.text)}}</strong></div>
        ${{INTERACTIVE ? `
        <div class="section-label">确认方式</div>
        ${{span.alternatives.length ? `<div class="candidate-list">${{candidateChoices}}</div>` : '<div class="no-candidates">当前数据尚无可用候选。仍可保留原文、手动编辑，或标记无法判断。</div>'}}
        <div class="action-list" style="margin-top:8px">
          <label class="choice-card"><input type="radio" name="decision" data-decision-action="accept_asr" value="accept_asr" ${{state.action === 'accept_asr' ? 'checked' : ''}}><span><span class="choice-title">保留 ASR 原文</span><span class="choice-help">确认当前识别结果无需修改</span></span></label>
          <label class="choice-card"><input type="radio" name="decision" data-decision-action="manual_edit" value="manual_edit" ${{state.action === 'manual_edit' ? 'checked' : ''}}><span><span class="choice-title">手动修正</span><span class="choice-help">输入听辨后的准确文本</span></span></label>
          <textarea id="manual-text" placeholder="输入确认后的词或短语">${{escapeHtml(state.manual_text)}}</textarea>
          <label class="choice-card"><input type="radio" name="decision" data-decision-action="reject" value="reject" ${{state.action === 'reject' ? 'checked' : ''}}><span><span class="choice-title">候选均不合适</span><span class="choice-help">暂时保留 ASR 原文并记录拒绝</span></span></label>
          <label class="choice-card"><input type="radio" name="decision" data-decision-action="unable_to_judge" value="unable_to_judge" ${{state.action === 'unable_to_judge' ? 'checked' : ''}}><span><span class="choice-title">无法判断</span><span class="choice-help">音频或语境不足，留待复核</span></span></label>
        </div>
        <div class="section-label">备注（可选）</div>
        <input type="text" id="feedback-note" value="${{escapeHtml(state.note)}}" placeholder="例如：药名需结合处方复核">
        <div class="panel-actions"><button class="primary-button" id="save-current" type="button">保存确认</button><button class="secondary-button" id="save-and-next" type="button">保存并下一个</button></div>
        ` : '<p class="muted">当前为只读 HTML。若需记录反馈，请生成 interactive HTML。</p>'}}
      `;
      if (INTERACTIVE) wirePanelControls(sample, span);
      document.getElementById('play-span-audio').addEventListener('click', () => {{
        playAudioClip(sample, span, span.start_sec, span.end_sec, `实体“${{span.text}}”`, spanAudioKey);
      }});
      document.getElementById('previous-risk').addEventListener('click', () => jumpToRelativeSpan(-1));
      document.getElementById('next-risk-panel').addEventListener('click', () => jumpToRelativeSpan(1));
      document.getElementById('panel-close').addEventListener('click', () => panel.classList.remove('open'));
    }}

    function renderPanelEmpty() {{
      const panel = document.getElementById('review-panel');
      panel.classList.remove('open');
      panel.innerHTML = `<div class="panel-empty"><div class="panel-empty-icon" aria-hidden="true">✓</div><strong>选择需要确认的词</strong><span>点击黄色或红色词后，可选择候选、手动修正或保留原文。</span></div>`;
    }}

    function buildSpanContext(sample, span, radius = 7) {{
      const start = Math.max(0, span.start_word_index - radius);
      const end = Math.min(sample.words.length, span.end_word_index + radius);
      return {{
        left: joinWordsForDisplay(sample.words.slice(start, span.start_word_index)),
        right: joinWordsForDisplay(sample.words.slice(span.end_word_index, end)),
      }};
    }}

    function wirePanelControls(sample, span) {{
      const state = getState(sample, span);
      document.querySelectorAll('input[name="decision"]').forEach(input => {{
        input.addEventListener('change', event => {{
          state.action = event.target.dataset.decisionAction;
          state.selected_alternative_id = state.action === 'select_alternative' ? event.target.value : '';
        }});
      }});
      const manual = document.getElementById('manual-text');
      if (manual) {{
        manual.addEventListener('input', event => {{ state.manual_text = event.target.value; }});
        manual.addEventListener('focus', () => {{
          state.action = 'manual_edit';
          state.selected_alternative_id = '';
          const radio = document.querySelector('input[name="decision"][data-decision-action="manual_edit"]');
          if (radio) radio.checked = true;
        }});
      }}
      const note = document.getElementById('feedback-note');
      if (note) note.addEventListener('input', event => {{ state.note = event.target.value; }});
      document.getElementById('save-current').addEventListener('click', () => saveCurrent(sample, span, false));
      document.getElementById('save-and-next').addEventListener('click', () => saveCurrent(sample, span, true));
    }}

    function saveCurrent(sample, span, moveNext) {{
      const state = getState(sample, span);
      if (state.action === 'manual_edit' && !state.manual_text.trim()) {{ showToast('请先输入手动修正文本'); document.getElementById('manual-text')?.focus(); return; }}
      if (state.action === 'select_alternative' && !state.selected_alternative_id) {{ showToast('请选择一个候选词'); return; }}
      state.reviewed = true;
      feedbackState.set(spanKey(sample, span), state);
      persistState();
      renderSample();
      selectSpan(sampleKey(sample), span.span_id);
      updateProgress();
      updateFeedbackPreview();
      showToast('已保存当前确认');
      if (moveNext) window.setTimeout(() => jumpToRelativeSpan(1, true), 100);
    }}

    function buildFeedbackEntries() {{
      const entries = [];
      for (const sample of SAMPLES) {{
        for (const span of sample.uncertain_spans) {{
          const state = feedbackState.get(spanKey(sample, span));
          if (!state?.reviewed) continue;
          const entry = {{
            schema_version: FEEDBACK_SCHEMA,
            feedback_id: `${{sampleKey(sample)}}::${{span.span_id}}::${{Date.now()}}`,
            record_id: sample.record_id,
            sample_id: sample.sample_id,
            span_id: span.span_id,
            action: state.action,
            selected_alternative_id: state.action === 'select_alternative' ? state.selected_alternative_id : null,
            manual_text: state.action === 'manual_edit' ? state.manual_text.trim() : null,
            original_text: span.text,
            reviewer_id: 'demo_reviewer',
            reviewer_role: 'research_demo_reviewer',
            created_at_utc: new Date().toISOString(),
            source: 'clinical_asr_review_ui_v2',
            note: state.note || null,
            metadata: {{
              confidence_level: span.confidence_level,
              min_confidence: span.min_confidence,
              candidate_count: span.alternatives.length,
              audio_play_count: Number(state.audio_play_count || 0),
              last_audio_window: state.last_audio_window || null,
              audio_clip_padding_sec: AUDIO_PADDING_SEC
            }},
            research_use_only: true,
            clinical_use_warning: CLINICAL_WARNING
          }};
          entries.push(entry);
        }}
      }}
      return entries;
    }}

    function buildFeedbackJsonl() {{
      return buildFeedbackEntries().map(entry => JSON.stringify(entry)).join('\\n') + '\\n';
    }}

    function updateFeedbackPreview() {{
      const preview = document.getElementById('feedback-preview');
      if (preview) preview.textContent = buildFeedbackJsonl();
    }}

    function downloadFeedbackJsonl() {{
      const jsonl = buildFeedbackJsonl();
      if (!buildFeedbackEntries().length) {{ showToast('还没有已保存的确认记录'); return; }}
      const blob = new Blob([jsonl], {{ type: 'application/x-ndjson;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'doctor_feedback_log.jsonl';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast('反馈记录已导出');
    }}

    function persistState() {{
      try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(feedbackState))); }}
      catch (error) {{ console.warn('无法写入本地审阅状态', error); }}
    }}

    function restoreState() {{
      try {{
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
        Object.entries(stored).forEach(([key, value]) => {{ if (value && typeof value === 'object') feedbackState.set(key, value); }});
      }} catch (error) {{ console.warn('无法恢复本地审阅状态', error); }}
    }}

    function updateProgress() {{
      const total = SAMPLES.reduce((sum, sample) => sum + sample.uncertain_spans.length, 0);
      const reviewed = buildFeedbackEntries().length;
      document.getElementById('progress-copy').textContent = `已确认 ${{reviewed}} / ${{total}}`;
      document.getElementById('progress-fill').style.width = `${{total ? (reviewed / total) * 100 : 0}}%`;
    }}

    function showToast(message) {{
      const toast = document.getElementById('toast');
      toast.textContent = message;
      toast.classList.add('show');
      window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => toast.classList.remove('show'), 2200);
    }}

    const reviewAudio = document.getElementById('review-audio');
    reviewAudio.addEventListener('timeupdate', () => {{
      if (audioStopAt !== null && reviewAudio.currentTime >= audioStopAt) {{
        reviewAudio.pause();
        audioStopAt = null;
        audioActiveKey = null;
        setAudioStatus('播放完成，可再次点击重播');
      }}
    }});
    reviewAudio.addEventListener('ended', () => {{
      audioStopAt = null;
      audioActiveKey = null;
      setAudioStatus('播放完成，可再次点击重播');
    }});
    reviewAudio.addEventListener('error', () => {{
      audioStopAt = null;
      audioActiveKey = null;
      setAudioStatus('音频加载失败：请检查文件是否存在及浏览器本地文件权限');
    }});

    document.getElementById('conversation-trigger').addEventListener('click', () => openConversationMenu());
    document.getElementById('conversation-search').addEventListener('input', event => renderConversationList(event.target.value));
    document.getElementById('previous-conversation').addEventListener('click', () => setActiveSample(activeConversationIndex - 1));
    document.getElementById('next-conversation').addEventListener('click', () => setActiveSample(activeConversationIndex + 1));
    document.getElementById('export-feedback').addEventListener('click', downloadFeedbackJsonl);
    document.getElementById('toggle-feedback').addEventListener('click', () => {{
      const preview = document.getElementById('feedback-preview');
      updateFeedbackPreview();
      const visible = preview.style.display === 'block';
      preview.style.display = visible ? 'none' : 'block';
      document.getElementById('toggle-feedback').textContent = visible ? '查看反馈记录' : '收起反馈记录';
    }});
    document.addEventListener('click', event => {{ if (!event.target.closest('.conversation-picker')) openConversationMenu(false); }});
    document.addEventListener('keydown', event => {{
      if (event.key === 'Escape') {{ openConversationMenu(false); document.getElementById('review-panel').classList.remove('open'); stopAudioPlayback(); }}
    }});

    restoreState();
    renderConversationList();
    setActiveSample(0, {{ scroll: false }});
    updateFeedbackPreview();
  </script>
</body>
</html>
"""


def _review_sample_time_sort_key(sample: ReviewSample) -> tuple[float, str]:
    starts = [
        value
        for value in [
            *(word.start_sec for word in sample.words),
            *(segment.start_sec for segment in sample.segments),
        ]
        if value is not None
    ]
    return (min(starts) if starts else float("inf"), sample.sample_id)


def _build_review_speaker_turns(
    samples: list[ReviewSample],
    *,
    max_merge_gap_sec: float,
) -> tuple[list[ReviewSpeakerTurn], int, int]:
    raw_runs: list[dict[str, Any]] = []
    labeled_word_count = 0
    total_word_count = 0

    for sample in samples:
        if not sample.words:
            if sample.asr_transcript.strip():
                raw_runs.append(
                    {
                        "speaker_label": _fallback_sample_speaker(sample),
                        "speaker_role": None,
                        "speaker_label_source": "sample_source_channel_or_missing",
                        "text": sample.asr_transcript,
                        "start_sec": None,
                        "end_sec": None,
                        "word_count": 0,
                        "slices": [],
                        "review_span_ids": [],
                        "audio_filepath": sample.audio_filepath,
                    }
                )
            continue

        run_start = 0
        current_identity = _speaker_identity_for_review_word(sample, sample.words[0])
        for position in range(1, len(sample.words) + 1):
            next_identity = (
                _speaker_identity_for_review_word(sample, sample.words[position])
                if position < len(sample.words)
                else None
            )
            if next_identity == current_identity:
                continue
            run_words = sample.words[run_start:position]
            speaker_label, speaker_role, speaker_source, is_diarized = current_identity
            total_word_count += len(run_words)
            if is_diarized:
                labeled_word_count += len(run_words)
            raw_runs.append(
                {
                    "speaker_label": speaker_label,
                    "speaker_role": speaker_role,
                    "speaker_label_source": speaker_source,
                    "text": _join_review_words(run_words, transcript=sample.asr_transcript),
                    "start_sec": _first_non_none(word.start_sec for word in run_words),
                    "end_sec": _last_non_none(word.end_sec for word in run_words),
                    "word_count": len(run_words),
                    "slices": [
                        ReviewTurnSlice(
                            sample_id=sample.sample_id,
                            record_id=sample.record_id,
                            start_word_index=run_words[0].word_index,
                            end_word_index=run_words[-1].word_index + 1,
                        )
                    ],
                    "review_span_ids": sorted(
                        {
                            span_id
                            for word in run_words
                            for span_id in word.span_ids
                        }
                    ),
                    "audio_filepath": sample.audio_filepath,
                }
            )
            run_start = position
            current_identity = next_identity

    merged: list[dict[str, Any]] = []
    for run in raw_runs:
        previous = merged[-1] if merged else None
        can_merge = bool(
            previous
            and run["speaker_label"] not in {"speaker_unknown", "mixed", "unknown"}
            and previous["speaker_label"] == run["speaker_label"]
            and previous["speaker_role"] == run["speaker_role"]
            and previous["audio_filepath"] == run["audio_filepath"]
            and _time_gap_within(
                previous.get("end_sec"),
                run.get("start_sec"),
                max_merge_gap_sec,
            )
        )
        if not can_merge:
            merged.append(dict(run))
            continue
        previous["text"] = _join_display_text(previous["text"], run["text"])
        previous["end_sec"] = run["end_sec"] or previous["end_sec"]
        previous["word_count"] += run["word_count"]
        previous["slices"] = [*previous["slices"], *run["slices"]]
        previous["review_span_ids"] = sorted(
            {*previous["review_span_ids"], *run["review_span_ids"]}
        )
        if previous["speaker_label_source"] != run["speaker_label_source"]:
            previous["speaker_label_source"] = "multiple_mapped_sources"

    turns = [
        ReviewSpeakerTurn(
            turn_id=f"turn_{index:04d}",
            speaker_label=run["speaker_label"],
            speaker_role=run["speaker_role"],
            speaker_label_source=run["speaker_label_source"],
            text=run["text"],
            start_sec=run["start_sec"],
            end_sec=run["end_sec"],
            word_count=run["word_count"],
            slices=run["slices"],
            review_span_ids=run["review_span_ids"],
            metadata={"reference_used": False},
        )
        for index, run in enumerate(merged)
    ]
    return turns, labeled_word_count, total_word_count


def _speaker_identity_for_review_word(
    sample: ReviewSample,
    word: ReviewWord,
) -> tuple[str, str | None, str, bool]:
    role = _speaker_role_from_metadata(word.metadata)
    direct_label = _meaningful_speaker_label(word.speaker_label)
    if direct_label:
        source = "word.speaker_label"
        diarization = word.metadata.get("diarization")
        if isinstance(diarization, dict):
            recorded_source = str(diarization.get("speaker_label_source") or "").strip()
            if recorded_source:
                source = recorded_source
        return direct_label, role, source, True

    for segment in sample.segments:
        if segment.start_word_index <= word.word_index < segment.end_word_index:
            segment_label = _meaningful_speaker_label(segment.speaker_label)
            if segment_label:
                segment_role = role or _speaker_role_from_metadata(segment.metadata)
                return segment_label, segment_role, "segment.speaker_label", True

    fallback = _fallback_sample_speaker(sample)
    if fallback not in {"speaker_unknown", "mixed", "unknown"}:
        return fallback, role, "sample.source_channel", False
    return "speaker_unknown", role, "diarization_missing", False


def _meaningful_speaker_label(value: str | None) -> str | None:
    label = str(value or "").strip()
    if not label or label.casefold() in {"mixed", "unknown", "speaker_unknown"}:
        return None
    return label


def _word_has_semantic_speaker_resolution(word: ReviewWord) -> bool:
    diarization = word.metadata.get("diarization")
    return bool(
        isinstance(diarization, dict) and diarization.get("semantic_resolution")
    )


def _fallback_sample_speaker(sample: ReviewSample) -> str:
    value = sample.source_channel.value
    return value if value not in {"mixed", "unknown"} else "speaker_unknown"


def _speaker_role_from_metadata(metadata: dict[str, Any]) -> str | None:
    direct = metadata.get("speaker_role")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for key in ("diarization", "speaker_mapping", "source_aware_speaker"):
        nested = metadata.get(key)
        if not isinstance(nested, dict):
            continue
        role = nested.get("speaker_role") or nested.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()
    return None


def _join_review_words(
    words: Iterable[ReviewWord],
    *,
    transcript: str | None = None,
) -> str:
    units = list(words)
    if not units:
        return ""
    if transcript is not None:
        start = units[0].char_start
        end = units[-1].char_end
        if start is not None and end is not None:
            return transcript[start:end]
    text = units[0].text
    for previous, current in zip(units[:-1], units[1:], strict=True):
        separator = current.metadata.get("separator_before")
        if not isinstance(separator, str):
            previous_ascii = previous.text[-1:].isascii() and previous.text[-1:].isalnum()
            current_ascii = current.text[:1].isascii() and current.text[:1].isalnum()
            separator = " " if previous_ascii and current_ascii else ""
        text += separator + current.text
    return text


def _first_non_none(values: Iterable[float | None]) -> float | None:
    return next((value for value in values if value is not None), None)


def _last_non_none(values: Iterable[float | None]) -> float | None:
    return next((value for value in reversed(list(values)) if value is not None), None)


def _time_gap_within(
    previous_end: float | None,
    current_start: float | None,
    max_gap_sec: float,
) -> bool:
    if previous_end is None or current_start is None:
        return False
    return 0 <= current_start - previous_end <= max_gap_sec


def _join_display_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    needs_space = left[-1:].isascii() and left[-1:].isalnum() and right[:1].isascii() and right[:1].isalnum()
    return left + (" " if needs_space else "") + right


def _build_review_span(record: ASRConfidenceRecord, span: UncertainSpan) -> ReviewSpan:
    alternatives = [
        _build_review_alternative(alternative)
        for alternative in record.alternatives_for_span(span.span_id)
    ]
    return ReviewSpan(
        span_id=span.span_id,
        text=span.text,
        start_word_index=span.start_word_index,
        end_word_index=span.end_word_index,
        start_sec=span.start_sec,
        end_sec=span.end_sec,
        mean_confidence=span.mean_confidence,
        min_confidence=span.min_confidence,
        confidence_level=span.confidence_level,
        review_priority=review_priority_for_level(span.confidence_level),
        trigger_reason=span.trigger_reason,
        alternatives=alternatives,
        metadata=span.metadata,
    )


def _build_review_alternative(alternative: ASRAlternative) -> ReviewAlternative:
    return ReviewAlternative(
        alternative_id=alternative.alternative_id,
        scope=alternative.scope,
        rank=alternative.rank,
        text=alternative.text,
        span_id=alternative.span_id,
        score=alternative.score,
        confidence=alternative.confidence,
        source=alternative.source,
        alignment_method=alternative.alignment_method,
        metadata=alternative.metadata,
    )


def _build_review_segment(segment: ASRSegment) -> ReviewSegment:
    return ReviewSegment(
        segment_id=segment.segment_id,
        text=segment.text,
        start_word_index=segment.start_word_index,
        end_word_index=segment.end_word_index,
        start_sec=segment.start_sec,
        end_sec=segment.end_sec,
        confidence=segment.confidence,
        confidence_level=segment.confidence_level,
        source=segment.source,
        speaker_label=segment.speaker_label,
        metadata=segment.metadata,
    )


def _coerce_feedback_payload(payload: Any) -> list[DoctorFeedbackEntry]:
    if isinstance(payload, list):
        return [DoctorFeedbackEntry.model_validate(item) for item in payload]
    if isinstance(payload, dict) and "entries" in payload:
        return DoctorFeedbackLog.model_validate(payload).entries
    return [DoctorFeedbackEntry.model_validate(payload)]


def _feedback_entries_for_record(
    record: ASRConfidenceRecord,
    feedback_entries: list[DoctorFeedbackEntry],
) -> list[DoctorFeedbackEntry]:
    matched = []
    for entry in feedback_entries:
        if entry.record_id and record.record_id and entry.record_id == record.record_id:
            matched.append(entry)
            continue
        if entry.record_id and record.record_id and entry.record_id != record.record_id:
            continue
        if entry.sample_id == record.sample_id:
            matched.append(entry)
    return matched


def _apply_entry_to_span(
    record: ASRConfidenceRecord,
    span: UncertainSpan,
    entry: DoctorFeedbackEntry,
) -> ConfirmedSpan:
    if entry.action == ReviewFeedbackAction.SELECT_ALTERNATIVE:
        alternative = _alternative_by_id(record, entry.selected_alternative_id or "")
        if alternative.span_id is not None and alternative.span_id != span.span_id:
            raise ValueError(
                f"候选 {alternative.alternative_id} 不属于 span {span.span_id}"
            )
        confirmed_text = _confirmed_text_for_selected_alternative(record, span, alternative)
        return ConfirmedSpan(
            span_id=span.span_id,
            action=entry.action,
            original_text=span.text,
            confirmed_text=confirmed_text,
            selected_alternative_id=alternative.alternative_id,
            selected_alternative_text=alternative.text,
            resolved=True,
            note=entry.note,
            metadata={
                "feedback_id": entry.feedback_id,
                "alternative_scope": alternative.scope,
                "alternative_start_word_index": alternative.start_word_index,
                "alternative_end_word_index": alternative.end_word_index,
            },
        )

    if entry.action == ReviewFeedbackAction.MANUAL_EDIT:
        return ConfirmedSpan(
            span_id=span.span_id,
            action=entry.action,
            original_text=span.text,
            confirmed_text=entry.manual_text or span.text,
            resolved=True,
            note=entry.note,
            metadata={"feedback_id": entry.feedback_id},
        )

    if entry.action == ReviewFeedbackAction.ACCEPT_ASR:
        return ConfirmedSpan(
            span_id=span.span_id,
            action=entry.action,
            original_text=span.text,
            confirmed_text=span.text,
            resolved=True,
            note=entry.note,
            metadata={"feedback_id": entry.feedback_id},
        )

    if entry.action in {
        ReviewFeedbackAction.REJECT,
        ReviewFeedbackAction.UNABLE_TO_JUDGE,
    }:
        return ConfirmedSpan(
            span_id=span.span_id,
            action=entry.action,
            original_text=span.text,
            confirmed_text=span.text,
            resolved=False,
            note=entry.note,
            metadata={
                "feedback_id": entry.feedback_id,
                "policy": "keep_original_asr_text_but_mark_unresolved",
            },
        )

    raise ValueError(f"未知反馈动作：{entry.action}")


def _alternative_by_id(record: ASRConfidenceRecord, alternative_id: str) -> ASRAlternative:
    for alternative in record.asr_alternatives:
        if alternative.alternative_id == alternative_id:
            return alternative
    raise ValueError(f"反馈引用了未知 alternative_id：{alternative_id}")


def _confirmed_text_for_selected_alternative(
    record: ASRConfidenceRecord,
    span: UncertainSpan,
    alternative: ASRAlternative,
) -> str:
    if alternative.scope != AlternativeScope.WORD:
        return alternative.text
    if alternative.start_word_index is None or alternative.end_word_index is None:
        raise ValueError("word-level alternative must include start/end_word_index")
    relative_start = alternative.start_word_index - span.start_word_index
    relative_end = alternative.end_word_index - span.start_word_index
    span_units = record.asr_words[span.start_word_index : span.end_word_index]
    target_units = record.asr_words[
        alternative.start_word_index : alternative.end_word_index
    ]
    span_text = join_asr_words(span_units, transcript=record.asr_transcript)
    if span_units and target_units:
        span_start = span_units[0].char_start
        target_start = target_units[0].char_start
        target_end = target_units[-1].char_end
        if (
            span_start is not None
            and target_start is not None
            and target_end is not None
        ):
            relative_start_char = target_start - span_start
            relative_end_char = target_end - span_start
            return (
                span_text[:relative_start_char]
                + alternative.text
                + span_text[relative_end_char:]
            )

    span_words = span.text.split()
    if relative_start < 0 or relative_end > len(span_words) or relative_end <= relative_start:
        raise ValueError(
            f"word-level alternative {alternative.alternative_id} is outside span {span.span_id}"
        )
    replacement_words = alternative.text.split()
    return " ".join(
        [*span_words[:relative_start], *replacement_words, *span_words[relative_end:]]
    )


def _char_range_for_span(
    record: ASRConfidenceRecord,
    span: UncertainSpan,
) -> tuple[int, int] | None:
    words = record.asr_words[span.start_word_index : span.end_word_index]
    if not words:
        return None
    start = words[0].char_start
    end = words[-1].char_end
    if start is None or end is None:
        return None
    return start, end


def _empty_if_none(value: Any) -> Any:
    return "" if value is None else value


def safe_filename(value: str) -> str:
    """把 record/sample id 规整为安全文件名片段。"""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "sample"
