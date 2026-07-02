"""ASR 置信度输出 JSONL schema 与读写工具。

本模块对应 T027：定义项目侧统一的 ASR confidence record。它面向
“音频 → ASR noisy transcript + word/span/segment confidence → 医生审阅”
主线，不依赖 NeMo `Hypothesis` 的内部对象结构。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness._compat import StrEnum

ASR_CONFIDENCE_RECORD_VERSION = "asr_confidence_record/v1"
CLINICAL_USE_WARNING = "本记录仅用于研究评估，不构成临床建议。"


class SourceChannel(StrEnum):
    """音频或转写对应的说话人/声道来源。"""

    DOCTOR = "doctor"
    PATIENT = "patient"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    """用于审阅界面的绿/黄/红风险等级。"""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class WordAlignmentStatus(StrEnum):
    """ASR word 与 timestamp / confidence 的对齐状态。"""

    ALIGNED = "aligned"
    MISSING_TIMESTAMP = "missing_timestamp"
    MISSING_CONFIDENCE = "missing_confidence"
    MISSING_TIMESTAMP_AND_CONFIDENCE = "missing_timestamp_and_confidence"


class TimestampConfidenceAlignmentPolicy(StrEnum):
    """word timestamp 与 word confidence 数量不一致时的导出策略。"""

    WORD_TEXT_ANCHORED_TRIM_EXTRAS_KEEP_MISSING = (
        "word_text_anchored_trim_extras_keep_missing"
    )


class AlternativeScope(StrEnum):
    """候选文本的作用范围。"""

    SEQUENCE = "sequence"
    SEGMENT = "segment"
    SPAN = "span"
    WORD = "word"


class ConfidenceThresholds(BaseModel):
    """绿/黄/红分级阈值。

    默认规则：
    - green: score >= 0.80
    - yellow: 0.50 <= score < 0.80
    - red: score < 0.50
    """

    model_config = ConfigDict(extra="forbid")

    green_min: float = Field(default=0.80, ge=0.0, le=1.0)
    yellow_min: float = Field(default=0.50, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> ConfidenceThresholds:
        """绿色阈值应高于黄色阈值。"""

        if self.green_min <= self.yellow_min:
            raise ValueError("green_min 必须大于 yellow_min")
        return self


def confidence_level_for_score(
    score: float | None,
    thresholds: ConfidenceThresholds | None = None,
) -> ConfidenceLevel:
    """按阈值把置信度分成绿/黄/红；缺失值返回 unknown。"""

    if score is None:
        return ConfidenceLevel.UNKNOWN
    active_thresholds = thresholds or ConfidenceThresholds()
    if score >= active_thresholds.green_min:
        return ConfidenceLevel.GREEN
    if score >= active_thresholds.yellow_min:
        return ConfidenceLevel.YELLOW
    return ConfidenceLevel.RED


class ASRWord(BaseModel):
    """ASR 输出中的一个词级单元。

    `word_index` 是在 `asr_words` 中的 0-based 位置。正式导出时以
    `asr_transcript.split()` 的词序为锚点，而不是以 timestamp 数量为锚点。
    """

    model_config = ConfigDict(extra="forbid")

    word_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    alignment_status: WordAlignmentStatus = WordAlignmentStatus.ALIGNED
    timestamp_source: str | None = None
    confidence_source: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    speaker_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_offsets_and_status(self) -> ASRWord:
        """检查时间/字符偏移，并自动补齐基础对齐状态与颜色等级。"""

        if self.start_sec is not None and self.end_sec is not None:
            if self.end_sec < self.start_sec:
                raise ValueError("end_sec 不能小于 start_sec")
        if self.char_start is not None and self.char_end is not None:
            if self.char_end < self.char_start:
                raise ValueError("char_end 不能小于 char_start")

        missing_timestamp = self.start_sec is None or self.end_sec is None
        missing_confidence = self.confidence is None
        if missing_timestamp and missing_confidence:
            self.alignment_status = WordAlignmentStatus.MISSING_TIMESTAMP_AND_CONFIDENCE
        elif missing_timestamp:
            self.alignment_status = WordAlignmentStatus.MISSING_TIMESTAMP
        elif missing_confidence:
            self.alignment_status = WordAlignmentStatus.MISSING_CONFIDENCE
        else:
            self.alignment_status = WordAlignmentStatus.ALIGNED

        if self.confidence_level == ConfidenceLevel.UNKNOWN and self.confidence is not None:
            self.confidence_level = confidence_level_for_score(self.confidence)
        return self


class ASRSegment(BaseModel):
    """面向界面展示或 ASR 原生 segment 的片段级单元。

    `start_word_index` / `end_word_index` 使用半开区间 `[start, end)`。
    """

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    text: str = Field(min_length=1)
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    confidence_aggregation: str | None = None
    source: str = "derived_from_words"
    speaker_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_segment(self) -> ASRSegment:
        """检查词范围、时间偏移和颜色等级。"""

        if self.end_word_index <= self.start_word_index:
            raise ValueError("end_word_index 必须大于 start_word_index")
        if self.start_sec is not None and self.end_sec is not None:
            if self.end_sec < self.start_sec:
                raise ValueError("end_sec 不能小于 start_sec")
        if self.confidence_level == ConfidenceLevel.UNKNOWN and self.confidence is not None:
            self.confidence_level = confidence_level_for_score(self.confidence)
        return self


class UncertainSpan(BaseModel):
    """连续中/低置信度词合并后的可审阅 span。

    `start_word_index` / `end_word_index` 使用半开区间 `[start, end)`。
    """

    model_config = ConfigDict(extra="forbid")

    span_id: str
    text: str = Field(min_length=1)
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=1)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    trigger_reason: str = "low_or_medium_confidence"
    alternative_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> UncertainSpan:
        """检查词范围、时间偏移和风险等级。"""

        if self.end_word_index <= self.start_word_index:
            raise ValueError("end_word_index 必须大于 start_word_index")
        if self.start_sec is not None and self.end_sec is not None:
            if self.end_sec < self.start_sec:
                raise ValueError("end_sec 不能小于 start_sec")
        if self.confidence_level == ConfidenceLevel.GREEN:
            raise ValueError("uncertain span 不应标为 green")
        if self.confidence_level == ConfidenceLevel.UNKNOWN:
            confidence = self.min_confidence
            if confidence is None:
                confidence = self.mean_confidence
            self.confidence_level = confidence_level_for_score(confidence)
            if self.confidence_level == ConfidenceLevel.GREEN:
                self.confidence_level = ConfidenceLevel.YELLOW
        return self


class ASRAlternative(BaseModel):
    """ASR n-best / beam 候选。

    V0 中 sequence-level n-best 可直接写成 `scope="sequence"`；T029 将其
    对齐到 uncertain span 后，可写成 `scope="span"` 并填写 `span_id`。
    """

    model_config = ConfigDict(extra="forbid")

    alternative_id: str
    scope: AlternativeScope
    rank: int = Field(ge=1)
    text: str = Field(min_length=1)
    span_id: str | None = None
    start_word_index: int | None = Field(default=None, ge=0)
    end_word_index: int | None = Field(default=None, ge=1)
    score: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str = "asr_nbest"
    alignment_method: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_alternative(self) -> ASRAlternative:
        """检查候选作用范围和词范围。"""

        has_word_range = self.start_word_index is not None or self.end_word_index is not None
        if has_word_range:
            if self.start_word_index is None or self.end_word_index is None:
                raise ValueError("候选若提供词范围，必须同时提供 start/end_word_index")
            if self.end_word_index <= self.start_word_index:
                raise ValueError("end_word_index 必须大于 start_word_index")

        if self.scope != AlternativeScope.SEQUENCE and self.span_id is None and not has_word_range:
            raise ValueError("非 sequence 候选必须填写 span_id 或词范围")
        return self


class ASRModelInfo(BaseModel):
    """ASR 模型和权重来源信息。"""

    model_config = ConfigDict(extra="forbid")

    provider: str = "nemo"
    model_name: str | None = None
    model_path: str | None = None
    model_class: str | None = None
    model_version: str | None = None
    checkpoint_sha256: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ASRDecodingConfig(BaseModel):
    """ASR 解码配置摘要。"""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    beam_size: int | None = Field(default=None, ge=1)
    n_best: int | None = Field(default=None, ge=1)
    batch_size: int | None = Field(default=None, ge=1)
    device: str | None = None
    timestamps_enabled: bool = True
    return_hypotheses: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ASRConfidenceConfig(BaseModel):
    """ASR 置信度方法与导出阈值。"""

    model_config = ConfigDict(extra="forbid")

    method_name: str = "entropy"
    entropy_type: str | None = "tsallis"
    alpha: float | None = Field(default=0.33, ge=0.0)
    entropy_norm: str | None = "lin"
    aggregation: str | None = "mean"
    preserve_frame_confidence: bool = False
    preserve_token_confidence: bool = True
    preserve_word_confidence: bool = True
    exclude_blank: bool = True
    source_field: str = "word_confidence"
    thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlignmentDiagnostics(BaseModel):
    """timestamp/confidence 与 transcript words 的对齐诊断。"""

    model_config = ConfigDict(extra="forbid")

    policy: TimestampConfidenceAlignmentPolicy = (
        TimestampConfidenceAlignmentPolicy.WORD_TEXT_ANCHORED_TRIM_EXTRAS_KEEP_MISSING
    )
    transcript_word_count: int = Field(ge=0)
    word_timestamp_count: int = Field(ge=0)
    word_confidence_count: int = Field(ge=0)
    asr_word_count: int = Field(ge=0)
    paired_word_count: int = Field(ge=0)
    missing_timestamp_word_indices: list[int] = Field(default_factory=list)
    missing_confidence_word_indices: list[int] = Field(default_factory=list)
    dropped_extra_word_timestamps: list[dict[str, Any]] = Field(default_factory=list)
    dropped_extra_word_confidences: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_alignment_counts(self) -> AlignmentDiagnostics:
        """检查对齐计数和缺失索引范围。"""

        if self.paired_word_count > self.asr_word_count:
            raise ValueError("paired_word_count 不能大于 asr_word_count")
        for index in self.missing_timestamp_word_indices:
            if index < 0 or index >= self.asr_word_count:
                raise ValueError(f"missing_timestamp_word_indices 越界：{index}")
        for index in self.missing_confidence_word_indices:
            if index < 0 or index >= self.asr_word_count:
                raise ValueError(f"missing_confidence_word_indices 越界：{index}")
        return self


class ASRConfidenceRecord(BaseModel):
    """一条 ASR confidence JSONL 记录。

    第一版建议“一行 = 一路音频/一个 channel 的 ASR 输出”。后续双路合并后，
    也可以用 `source_channel="mixed"` 保存按时间合并后的 consultation-level 记录。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = ASR_CONFIDENCE_RECORD_VERSION
    record_id: str | None = None
    sample_id: str
    dataset: str
    split: str | None = None
    consultation_id: str | None = None
    source_channel: SourceChannel = SourceChannel.UNKNOWN
    audio_filepath: str | None = None
    duration_sec: float | None = Field(default=None, ge=0.0)
    reference_textgrid_path: str | None = None
    reference_transcript_path: str | None = None
    reference_text_included: bool = False
    generated_at_utc: datetime | None = None
    asr_transcript: str
    asr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    asr_words: list[ASRWord] = Field(default_factory=list)
    asr_segments: list[ASRSegment] = Field(default_factory=list)
    uncertain_spans: list[UncertainSpan] = Field(default_factory=list)
    asr_alternatives: list[ASRAlternative] = Field(default_factory=list)
    model: ASRModelInfo
    decoding: ASRDecodingConfig
    confidence: ASRConfidenceConfig = Field(default_factory=ASRConfidenceConfig)
    alignment: AlignmentDiagnostics
    runtime: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @model_validator(mode="after")
    def validate_record(self) -> ASRConfidenceRecord:
        """检查跨字段引用、词范围和安全约束。"""

        if self.reference_text_included:
            raise ValueError("ASR confidence record 不应内联 reference transcript 正文")

        if self.confidence_level == ConfidenceLevel.UNKNOWN and self.asr_confidence is not None:
            self.confidence_level = confidence_level_for_score(
                self.asr_confidence,
                self.confidence.thresholds,
            )

        transcript_word_count = len(self.asr_transcript.split())
        if self.alignment.transcript_word_count != transcript_word_count:
            raise ValueError(
                "alignment.transcript_word_count 必须等于 asr_transcript.split() 数量"
            )
        if self.alignment.asr_word_count != len(self.asr_words):
            raise ValueError("alignment.asr_word_count 必须等于 asr_words 数量")

        for expected_index, word in enumerate(self.asr_words):
            if word.word_index != expected_index:
                raise ValueError(
                    f"asr_words 必须按 0-based word_index 连续排列："
                    f"期望 {expected_index}，实际 {word.word_index}"
                )

        segment_ids = [segment.segment_id for segment in self.asr_segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("asr_segments 中存在重复 segment_id")

        span_ids = [span.span_id for span in self.uncertain_spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("uncertain_spans 中存在重复 span_id")

        alternative_ids = [alternative.alternative_id for alternative in self.asr_alternatives]
        if len(alternative_ids) != len(set(alternative_ids)):
            raise ValueError("asr_alternatives 中存在重复 alternative_id")

        word_count = len(self.asr_words)
        for segment in self.asr_segments:
            if segment.end_word_index > word_count:
                raise ValueError(f"segment 词范围越界：{segment.segment_id}")
        for span in self.uncertain_spans:
            if span.end_word_index > word_count:
                raise ValueError(f"uncertain span 词范围越界：{span.span_id}")

        known_span_ids = set(span_ids)
        for alternative in self.asr_alternatives:
            if alternative.end_word_index is not None and alternative.end_word_index > word_count:
                raise ValueError(f"alternative 词范围越界：{alternative.alternative_id}")
            if alternative.span_id is not None and alternative.span_id not in known_span_ids:
                raise ValueError(f"alternative 引用了未知 span_id：{alternative.span_id}")

        known_alternative_ids = set(alternative_ids)
        for span in self.uncertain_spans:
            for alternative_id in span.alternative_ids:
                if alternative_id not in known_alternative_ids:
                    raise ValueError(
                        f"uncertain span 引用了未知 alternative_id：{alternative_id}"
                    )
        return self

    def alternatives_for_span(self, span_id: str) -> list[ASRAlternative]:
        """按 rank 返回某个 uncertain span 的候选。"""

        return sorted(
            [
                alternative
                for alternative in self.asr_alternatives
                if alternative.span_id == span_id
            ],
            key=lambda alternative: alternative.rank,
        )

    def words_for_span(self, span: UncertainSpan) -> list[ASRWord]:
        """返回某个 span 覆盖的词。"""

        return self.asr_words[span.start_word_index : span.end_word_index]


def read_asr_confidence_jsonl(path: str | Path) -> list[ASRConfidenceRecord]:
    """读取 ASR confidence JSONL。"""

    records: list[ASRConfidenceRecord] = []
    jsonl_path = Path(path)
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(ASRConfidenceRecord.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - 保留文件与行号便于定位
                message = f"无法解析 ASR confidence JSONL 第 {line_number} 行：{jsonl_path}"
                raise ValueError(message) from exc
    return records


def write_asr_confidence_jsonl(
    records: Iterable[ASRConfidenceRecord],
    path: str | Path,
) -> None:
    """写入 ASR confidence JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")
