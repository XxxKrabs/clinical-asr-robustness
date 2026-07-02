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
import re
from collections import Counter
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
)

REVIEW_SAMPLE_SCHEMA_VERSION = "asr_review_sample/v1"
FEEDBACK_ENTRY_SCHEMA_VERSION = "doctor_feedback_entry/v1"
FEEDBACK_LOG_SCHEMA_VERSION = "doctor_feedback_log/v1"
CONFIRMED_TRANSCRIPT_SCHEMA_VERSION = "confirmed_transcript_record/v1"

T030_GENERATED_BY = "T030"
T035_GENERATED_BY = "T035"
T036_GENERATED_BY = "T036"


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


def build_review_sample(record: ASRConfidenceRecord) -> ReviewSample:
    """把一条 ASR confidence record 转成审阅样本。"""

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
            span_ids=span_ids_by_word.get(word.word_index, []),
            review_required=bool(span_ids_by_word.get(word.word_index))
            or word.confidence_level
            in {ConfidenceLevel.YELLOW, ConfidenceLevel.RED, ConfidenceLevel.UNKNOWN},
            review_priority=review_priority_for_level(word.confidence_level),
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
            "note": (
                "Green words are shown for context; yellow/red/unknown spans are the "
                "primary review targets. Feedback is research data only."
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
    with feedback_path.open("r", encoding="utf-8") as file:
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

    tokens = record.asr_transcript.split()
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
    pieces: list[str] = []
    cursor = 0

    for span in sorted(record.uncertain_spans, key=lambda item: item.start_word_index):
        if span.start_word_index < cursor:
            raise ValueError(
                f"uncertain spans 发生重叠，暂不支持自动回放：{record.sample_id} {span.span_id}"
            )
        pieces.extend(tokens[cursor : span.start_word_index])
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
        pieces.append(confirmed_span.confirmed_text)
        applied_spans.append(confirmed_span)
        cursor = span.end_word_index

    pieces.extend(tokens[cursor:])
    confirmed_transcript = " ".join(piece for piece in pieces if piece.strip())

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
                "select_alternative": "replace span text with selected ASR candidate",
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
) -> str:
    """生成可单文件打开的 HTML。

    `interactive=True` 时，页面可点击 span、选择候选/手动编辑/拒绝/无法判断，
    并把反馈导出为 JSONL。静态 HTML 无后端写文件能力，因此“保存”采用
    localStorage 暂存 + 浏览器下载文件两种方式。
    """

    sample_payload = json.dumps(
        [sample.model_dump(mode="json") for sample in samples],
        ensure_ascii=False,
    ).replace("</", "<\\/")
    interactive_literal = "true" if interactive else "false"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --green: #c8f7c5;
      --green-border: #50a35a;
      --yellow: #fff1a8;
      --yellow-border: #c79600;
      --red: #ffd0d0;
      --red-border: #d33f49;
      --unknown: #e5e7eb;
      --ink: #172033;
      --muted: #5b6475;
      --panel: #ffffff;
      --line: #d8dee9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      margin: 0;
      background: #f5f7fb;
      color: var(--ink);
      line-height: 1.55;
    }}
    header {{
      padding: 20px 28px;
      background: #172033;
      color: white;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 22px; }}
    header p {{ margin: 4px 0; color: #dce3f2; }}
    main {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
      gap: 18px;
      padding: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 4px 16px rgba(23, 32, 51, 0.06);
    }}
    .sample-title {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: baseline;
      margin: 0 0 10px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #f8fafc;
    }}
    .transcript {{
      font-size: 18px;
      line-height: 2.05;
      word-break: break-word;
    }}
    .word {{
      border-radius: 7px;
      padding: 3px 5px;
      margin: 0 1px;
      border: 1px solid transparent;
      white-space: nowrap;
    }}
    .word.green {{ background: var(--green); border-color: var(--green-border); }}
    .word.yellow {{ background: var(--yellow); border-color: var(--yellow-border); }}
    .word.red {{ background: var(--red); border-color: var(--red-border); }}
    .word.unknown {{ background: var(--unknown); border-color: #a0a7b5; }}
    .word.reviewable {{
      cursor: pointer;
      box-shadow: inset 0 -2px rgba(0,0,0,0.12);
    }}
    .word.active {{
      outline: 3px solid #4c6fff;
      outline-offset: 1px;
    }}
    .legend {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 10px 0 14px;
    }}
    .span-list {{
      margin-top: 14px;
      display: grid;
      gap: 8px;
    }}
    .span-row {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      cursor: pointer;
      background: #fbfdff;
    }}
    .span-row:hover {{ border-color: #4c6fff; }}
    .panel-title {{ margin-top: 0; }}
    .muted {{ color: var(--muted); }}
    .control-group {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      margin: 10px 0;
    }}
    label {{ display: block; margin: 8px 0; }}
    select, textarea, input[type="text"] {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      font: inherit;
    }}
    textarea {{ min-height: 80px; }}
    button {{
      border: 0;
      border-radius: 10px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
      background: #4c6fff;
      color: white;
      margin: 4px 4px 4px 0;
    }}
    button.secondary {{ background: #e7ebf5; color: var(--ink); }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    pre, .jsonl-output {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #111827;
      color: #e5e7eb;
      border-radius: 10px;
      padding: 10px;
      max-height: 260px;
      overflow: auto;
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      main {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <p>研究 demo：展示 ASR noisy transcript 的词级/片段级置信度、绿/黄/红风险高亮和候选选择流程。</p>
    <p>所有输出仅用于研究评估，不构成临床建议；请勿填入真实患者隐私或未脱敏病例内容。</p>
  </header>
  <main>
    <section id="samples"></section>
    <aside class="card" id="review-panel">
      <h2 class="panel-title">审阅面板</h2>
      <p class="muted">点击黄色/红色片段后，可查看候选并记录反馈。</p>
    </aside>
  </main>
  <script id="review-data" type="application/json">{sample_payload}</script>
  <script>
    const SAMPLES = JSON.parse(document.getElementById('review-data').textContent);
    const INTERACTIVE = {interactive_literal};
    const FEEDBACK_SCHEMA = "{FEEDBACK_ENTRY_SCHEMA_VERSION}";
    const CLINICAL_WARNING = "{html.escape(CLINICAL_USE_WARNING)}";
    const feedbackState = new Map();
    let activeKey = null;

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[char]));
    }}

    function sampleKey(sample) {{
      return sample.record_id || sample.sample_id;
    }}

    function spanKey(sample, span) {{
      return `${{sampleKey(sample)}}::${{span.span_id}}`;
    }}

    function confidenceText(value) {{
      return value === null || value === undefined ? 'NA' : Number(value).toFixed(3);
    }}

    function renderSamples() {{
      const container = document.getElementById('samples');
      container.innerHTML = SAMPLES.map(sample => {{
        const key = sampleKey(sample);
        const transcript = sample.words.map(word => {{
          const level = word.confidence_level || 'unknown';
          const reviewable = word.span_ids && word.span_ids.length > 0;
          const title = `#${{word.word_index}} confidence=${{confidenceText(word.confidence)}} level=${{level}}`;
          const firstSpan = reviewable ? word.span_ids[0] : '';
          return `<span class="word ${{level}} ${{reviewable ? 'reviewable' : ''}}"
            data-sample-key="${{escapeHtml(key)}}"
            data-span-id="${{escapeHtml(firstSpan)}}"
            title="${{escapeHtml(title)}}">${{escapeHtml(word.text)}}</span>`;
        }}).join(' ');
        const spans = sample.uncertain_spans.map(span => `
          <div class="span-row" data-sample-key="${{escapeHtml(key)}}" data-span-id="${{escapeHtml(span.span_id)}}">
            <strong>${{escapeHtml(span.span_id)}}｜${{escapeHtml(span.text)}}</strong>
            <div class="muted">
              ${{escapeHtml(span.confidence_level)}} · min=${{confidenceText(span.min_confidence)}} ·
              ${{span.alternatives.length}} candidates · ${{escapeHtml(span.trigger_reason)}}
            </div>
          </div>`).join('');
        return `<article class="card sample" data-sample-key="${{escapeHtml(key)}}">
          <h2 class="sample-title">
            <span>${{escapeHtml(sample.sample_id)}}</span>
            <span class="badge">${{escapeHtml(sample.source_channel)}}</span>
            <span class="badge">${{escapeHtml(sample.dataset)}}</span>
            <span class="badge">${{escapeHtml(sample.confidence_level)}}</span>
          </h2>
          <div class="legend">
            <span class="badge"><span class="word green">绿色</span> 高置信</span>
            <span class="badge"><span class="word yellow">黄色</span> 中置信</span>
            <span class="badge"><span class="word red">红色</span> 低置信</span>
            <span class="badge"><span class="word unknown">灰色</span> 缺失</span>
          </div>
          <div class="transcript">${{transcript}}</div>
          <div class="span-list">${{spans || '<p class="muted">无 uncertain span。</p>'}}</div>
        </article>`;
      }}).join('');
      container.querySelectorAll('.reviewable, .span-row').forEach(node => {{
        node.addEventListener('click', () => selectSpan(node.dataset.sampleKey, node.dataset.spanId));
      }});
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
      activeKey = spanKey(sample, span);
      document.querySelectorAll('.word.active').forEach(node => node.classList.remove('active'));
      document.querySelectorAll(`.word[data-sample-key="${{CSS.escape(targetSampleKey)}}"][data-span-id="${{CSS.escape(spanId)}}"]`)
        .forEach(node => node.classList.add('active'));
      renderPanel(sample, span);
    }}

    function getState(sample, span) {{
      const key = spanKey(sample, span);
      if (!feedbackState.has(key)) {{
        feedbackState.set(key, {{
          action: 'accept_asr',
          selected_alternative_id: span.alternatives[0]?.alternative_id || '',
          manual_text: '',
          note: ''
        }});
      }}
      return feedbackState.get(key);
    }}

    function renderPanel(sample, span) {{
      const panel = document.getElementById('review-panel');
      const state = getState(sample, span);
      const alternatives = span.alternatives.map(alt => `
        <option value="${{escapeHtml(alt.alternative_id)}}" ${{state.selected_alternative_id === alt.alternative_id ? 'selected' : ''}}>
          #${{alt.rank}} ${{escapeHtml(alt.text)}} ${{alt.confidence !== null && alt.confidence !== undefined ? `(conf=${{confidenceText(alt.confidence)}})` : ''}}
        </option>`).join('');
      panel.innerHTML = `
        <h2 class="panel-title">审阅：${{escapeHtml(span.text)}}</h2>
        <p class="muted">
          sample=${{escapeHtml(sample.sample_id)}} · span=${{escapeHtml(span.span_id)}} ·
          level=${{escapeHtml(span.confidence_level)}} · min=${{confidenceText(span.min_confidence)}}
        </p>
        <div class="control-group">
          <strong>ASR 原文</strong>
          <p>${{escapeHtml(span.text)}}</p>
          <strong>候选</strong>
          ${{span.alternatives.length ? '<ol>' + span.alternatives.map(alt => `<li>${{escapeHtml(alt.text)}} <span class="muted">(${{escapeHtml(alt.source)}} / rank ${{alt.rank}})</span></li>`).join('') + '</ol>' : '<p class="muted">暂无候选，可选择手动编辑、保留原文或标记无法判断。</p>'}}
        </div>
        ${{INTERACTIVE ? `
        <div class="control-group">
          <label><input type="radio" name="action" value="accept_asr" ${{state.action === 'accept_asr' ? 'checked' : ''}}> 保留 ASR 原文并确认</label>
          <label><input type="radio" name="action" value="select_alternative" ${{state.action === 'select_alternative' ? 'checked' : ''}} ${{span.alternatives.length ? '' : 'disabled'}}> 选择 ASR 候选</label>
          <select id="alternative-select" ${{span.alternatives.length ? '' : 'disabled'}}>${{alternatives}}</select>
          <label><input type="radio" name="action" value="manual_edit" ${{state.action === 'manual_edit' ? 'checked' : ''}}> 手动编辑</label>
          <textarea id="manual-text" placeholder="输入确认后的 span 文本">${{escapeHtml(state.manual_text)}}</textarea>
          <label><input type="radio" name="action" value="reject" ${{state.action === 'reject' ? 'checked' : ''}}> 拒绝候选，暂保留 ASR 原文</label>
          <label><input type="radio" name="action" value="unable_to_judge" ${{state.action === 'unable_to_judge' ? 'checked' : ''}}> 无法判断，暂保留 ASR 原文</label>
          <label>备注<input type="text" id="feedback-note" value="${{escapeHtml(state.note)}}"></label>
          <button id="save-current">记录当前 span</button>
        </div>
        <button id="export-feedback">提交并下载反馈 JSONL</button>
        <button class="secondary" id="copy-feedback">刷新下方 JSONL</button>
        <div id="feedback-preview" class="jsonl-output"></div>
        ` : '<p class="muted">当前为只读 HTML。若需记录反馈，请使用 T036 interactive HTML。</p>'}}
      `;
      if (INTERACTIVE) wirePanelControls(sample, span);
      updateFeedbackPreview();
    }}

    function wirePanelControls(sample, span) {{
      const state = getState(sample, span);
      document.querySelectorAll('input[name="action"]').forEach(input => {{
        input.addEventListener('change', event => {{ state.action = event.target.value; }});
      }});
      const select = document.getElementById('alternative-select');
      if (select) select.addEventListener('change', event => {{ state.selected_alternative_id = event.target.value; }});
      const manual = document.getElementById('manual-text');
      if (manual) manual.addEventListener('input', event => {{ state.manual_text = event.target.value; }});
      const note = document.getElementById('feedback-note');
      if (note) note.addEventListener('input', event => {{ state.note = event.target.value; }});
      document.getElementById('save-current').addEventListener('click', () => {{
        feedbackState.set(spanKey(sample, span), state);
        localStorage.setItem('clinical_asr_review_feedback_jsonl', buildFeedbackJsonl());
        updateFeedbackPreview();
      }});
      document.getElementById('export-feedback').addEventListener('click', downloadFeedbackJsonl);
      document.getElementById('copy-feedback').addEventListener('click', updateFeedbackPreview);
    }}

    function buildFeedbackEntries() {{
      const entries = [];
      for (const sample of SAMPLES) {{
        for (const span of sample.uncertain_spans) {{
          const state = feedbackState.get(spanKey(sample, span));
          if (!state) continue;
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
            source: 't036_html_demo',
            note: state.note || null,
            metadata: {{
              confidence_level: span.confidence_level,
              min_confidence: span.min_confidence,
              candidate_count: span.alternatives.length
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
      localStorage.setItem('clinical_asr_review_feedback_jsonl', jsonl);
      const blob = new Blob([jsonl], {{ type: 'application/x-ndjson;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'doctor_feedback_log.jsonl';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }}

    renderSamples();
    if (SAMPLES.length && SAMPLES[0].uncertain_spans.length) {{
      selectSpan(sampleKey(SAMPLES[0]), SAMPLES[0].uncertain_spans[0].span_id);
    }}
  </script>
</body>
</html>
"""


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
        return ConfirmedSpan(
            span_id=span.span_id,
            action=entry.action,
            original_text=span.text,
            confirmed_text=alternative.text,
            selected_alternative_id=alternative.alternative_id,
            selected_alternative_text=alternative.text,
            resolved=True,
            note=entry.note,
            metadata={"feedback_id": entry.feedback_id},
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


def _empty_if_none(value: Any) -> Any:
    return "" if value is None else value


def safe_filename(value: str) -> str:
    """把 record/sample id 规整为安全文件名片段。"""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "sample"
