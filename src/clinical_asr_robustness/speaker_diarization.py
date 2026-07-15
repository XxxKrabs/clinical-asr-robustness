"""说话人分离结果 schema、RTTM 导出与 ASR 字词映射。

本模块不依赖 NeMo / torch。GPU 推理由命令行脚本负责；这里仅处理稳定的
``start end speaker`` 输出、审计记录和时间重叠映射，便于在普通测试环境复核。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness.asr_confidence import (
    CLINICAL_USE_WARNING,
    ASRConfidenceRecord,
    ASRWord,
)

SPEAKER_DIARIZATION_RECORD_VERSION = "speaker_diarization_record/v1"
SORTFORMER_MAPPING_SOURCE = "nvidia_sortformer_time_overlap/v1"
SAME_SPEAKER_GAP_BRIDGE_SOURCE = "same_speaker_short_gap_bridge/v1"
DEFAULT_BRIDGEABLE_MAPPING_STATUSES = frozenset(
    {"no_overlap", "insufficient_overlap"}
)


class SpeakerDiarizationSegment(BaseModel):
    """一个声学说话人的活动区间；允许不同说话人的区间重叠。"""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(gt=0.0)
    speaker_label: str = Field(min_length=1)
    source: str = "nvidia_sortformer"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_interval(self) -> SpeakerDiarizationSegment:
        if self.end_sec <= self.start_sec:
            raise ValueError("diarization segment 的 end_sec 必须大于 start_sec")
        if any(character.isspace() for character in self.speaker_label):
            raise ValueError("speaker_label 不能包含空白字符")
        return self


class SpeakerDiarizationModelInfo(BaseModel):
    """可追溯的说话人分离模型信息。"""

    model_config = ConfigDict(extra="forbid")

    provider: str = "nvidia"
    model_name: str
    model_path: str
    model_class: str = "nemo.collections.asr.models.SortformerEncLabelModel"
    model_version: str | None = None
    checkpoint_sha256: str
    license: str | None = None
    max_num_speakers: int = Field(default=4, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpeakerDiarizationRecord(BaseModel):
    """一整例音频的说话人分离记录，不包含转写或病例正文。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SPEAKER_DIARIZATION_RECORD_VERSION
    record_id: str
    dataset: str
    split: str | None = None
    consultation_id: str
    audio_filepath: str
    source_audio_filepath: str | None = None
    duration_sec: float = Field(gt=0.0)
    generated_at_utc: datetime | None = None
    segments: list[SpeakerDiarizationSegment] = Field(default_factory=list)
    speaker_labels: list[str] = Field(default_factory=list)
    model: SpeakerDiarizationModelInfo
    inference: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @model_validator(mode="after")
    def validate_record(self) -> SpeakerDiarizationRecord:
        expected_labels = sorted({segment.speaker_label for segment in self.segments})
        if self.speaker_labels != expected_labels:
            raise ValueError("speaker_labels 必须等于 segments 中去重、排序后的标签")
        segment_ids = [segment.segment_id for segment in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("segments 中存在重复 segment_id")
        if any(segment.end_sec > self.duration_sec + 0.1 for segment in self.segments):
            raise ValueError("diarization segment 超出音频时长")
        return self


class SpeakerMappingDecision(BaseModel):
    """一个 ASR 字词与声学 speaker 时间区间的映射证据。"""

    model_config = ConfigDict(extra="forbid")

    speaker_label: str | None = None
    status: str
    best_overlap_sec: float = Field(default=0.0, ge=0.0)
    overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_overlap_sec: dict[str, float] = Field(default_factory=dict)


def parse_sortformer_output_lines(lines: Iterable[str]) -> list[SpeakerDiarizationSegment]:
    """解析 NeMo Sortformer 的 ``start end speaker`` 输出。"""

    raw_segments: list[tuple[float, float, str]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = str(raw_line).strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Sortformer 输出第 {line_number} 行不是三列：{line!r}")
        try:
            start_sec = float(parts[0])
            end_sec = float(parts[1])
        except ValueError as exc:
            raise ValueError(f"Sortformer 输出第 {line_number} 行时间无效：{line!r}") from exc
        raw_segments.append((start_sec, end_sec, parts[2]))

    ordered = sorted(raw_segments, key=lambda item: (item[0], item[1], item[2]))
    return [
        SpeakerDiarizationSegment(
            segment_id=f"diar_seg_{index:05d}",
            start_sec=start_sec,
            end_sec=end_sec,
            speaker_label=speaker_label,
        )
        for index, (start_sec, end_sec, speaker_label) in enumerate(ordered, start=1)
    ]


def diarization_segments_to_rttm(
    recording_id: str,
    segments: Sequence[SpeakerDiarizationSegment],
) -> list[str]:
    """把声学区间转换为标准 RTTM 行。"""

    if not recording_id or any(character.isspace() for character in recording_id):
        raise ValueError("RTTM recording_id 不能为空或包含空白字符")
    return [
        "SPEAKER "
        f"{recording_id} 1 {segment.start_sec:.3f} "
        f"{segment.end_sec - segment.start_sec:.3f} <NA> <NA> "
        f"{segment.speaker_label} <NA> <NA>"
        for segment in segments
    ]


def map_interval_to_speaker(
    start_sec: float | None,
    end_sec: float | None,
    segments: Sequence[SpeakerDiarizationSegment],
    *,
    min_overlap_ratio: float = 0.10,
    ambiguity_ratio: float = 0.90,
) -> SpeakerMappingDecision:
    """按最大时间重叠映射 speaker；重叠说话接近并列时保守地留空。"""

    if not 0.0 <= min_overlap_ratio <= 1.0:
        raise ValueError("min_overlap_ratio 必须位于 [0, 1]")
    if not 0.0 <= ambiguity_ratio <= 1.0:
        raise ValueError("ambiguity_ratio 必须位于 [0, 1]")
    if start_sec is None or end_sec is None:
        return SpeakerMappingDecision(status="missing_timestamp")
    if end_sec < start_sec:
        raise ValueError("ASR interval 的 end_sec 不能小于 start_sec")

    if end_sec == start_sec:
        active_labels = sorted(
            {
                segment.speaker_label
                for segment in segments
                if segment.start_sec <= start_sec < segment.end_sec
            }
        )
        if len(active_labels) == 1:
            return SpeakerMappingDecision(
                speaker_label=active_labels[0],
                status="mapped_point_containment",
                best_overlap_sec=0.0,
                overlap_ratio=1.0,
                candidate_overlap_sec={active_labels[0]: 0.0},
            )
        if active_labels:
            return SpeakerMappingDecision(
                status="ambiguous_overlap",
                candidate_overlap_sec={label: 0.0 for label in active_labels},
            )
        return SpeakerMappingDecision(status="no_overlap")

    overlap_by_speaker: dict[str, float] = defaultdict(float)
    for segment in segments:
        overlap = max(0.0, min(end_sec, segment.end_sec) - max(start_sec, segment.start_sec))
        if overlap > 0.0:
            overlap_by_speaker[segment.speaker_label] += overlap
    if not overlap_by_speaker:
        return SpeakerMappingDecision(status="no_overlap")

    ranked = sorted(overlap_by_speaker.items(), key=lambda item: (-item[1], item[0]))
    best_label, best_overlap = ranked[0]
    word_duration = end_sec - start_sec
    overlap_ratio = min(1.0, best_overlap / word_duration)
    candidates = {label: round(overlap, 6) for label, overlap in ranked}
    if overlap_ratio < min_overlap_ratio:
        return SpeakerMappingDecision(
            status="insufficient_overlap",
            best_overlap_sec=best_overlap,
            overlap_ratio=overlap_ratio,
            candidate_overlap_sec=candidates,
        )
    if len(ranked) > 1 and ranked[1][1] >= best_overlap * ambiguity_ratio:
        return SpeakerMappingDecision(
            status="ambiguous_overlap",
            best_overlap_sec=best_overlap,
            overlap_ratio=overlap_ratio,
            candidate_overlap_sec=candidates,
        )
    return SpeakerMappingDecision(
        speaker_label=best_label,
        status="mapped_max_overlap",
        best_overlap_sec=best_overlap,
        overlap_ratio=overlap_ratio,
        candidate_overlap_sec=candidates,
    )


def apply_diarization_to_asr_record(
    record: ASRConfidenceRecord,
    diarization: SpeakerDiarizationRecord,
    *,
    min_overlap_ratio: float = 0.10,
    ambiguity_ratio: float = 0.90,
    overwrite_existing: bool = False,
) -> ASRConfidenceRecord:
    """把一个整例 diarization 结果映射到一条 ASR 窗口记录。"""

    if record.dataset != diarization.dataset:
        raise ValueError("ASR 与 diarization 的 dataset 不一致")
    if str(record.consultation_id or record.sample_id) != diarization.consultation_id:
        raise ValueError("ASR 与 diarization 的 consultation_id 不一致")

    mapped = record.model_copy(deep=True)
    timestamp_offset_sec, timestamp_reference = _mapping_timestamp_offset(mapped)
    status_counts: dict[str, int] = defaultdict(int)
    speaker_counts: dict[str, int] = defaultdict(int)

    for word in mapped.asr_words:
        if word.speaker_label and not overwrite_existing:
            status_counts["preserved_existing"] += 1
            speaker_counts[word.speaker_label] += 1
            continue
        start_sec = None if word.start_sec is None else word.start_sec + timestamp_offset_sec
        end_sec = None if word.end_sec is None else word.end_sec + timestamp_offset_sec
        decision = map_interval_to_speaker(
            start_sec,
            end_sec,
            diarization.segments,
            min_overlap_ratio=min_overlap_ratio,
            ambiguity_ratio=ambiguity_ratio,
        )
        word.speaker_label = decision.speaker_label
        word.metadata = {
            **word.metadata,
            "diarization": {
                "source": SORTFORMER_MAPPING_SOURCE,
                "diarization_record_id": diarization.record_id,
                "speaker_label": decision.speaker_label,
                "resolved_speaker_label": decision.speaker_label,
                "speaker_label_source": (
                    SORTFORMER_MAPPING_SOURCE if decision.speaker_label else None
                ),
                "mapping_status": decision.status,
                "best_overlap_sec": round(decision.best_overlap_sec, 6),
                "overlap_ratio": round(decision.overlap_ratio, 6),
                "candidate_overlap_sec": decision.candidate_overlap_sec,
                "timestamp_offset_sec": timestamp_offset_sec,
                "acoustic_speaker_only": True,
                "speaker_role": None,
            },
        }
        status_counts[decision.status] += 1
        if decision.speaker_label:
            speaker_counts[decision.speaker_label] += 1

    for segment in mapped.asr_segments:
        segment_words = mapped.asr_words[segment.start_word_index : segment.end_word_index]
        labels = [word.speaker_label for word in segment_words if word.speaker_label]
        if labels and len(labels) == len(segment_words) and len(set(labels)) == 1:
            segment.speaker_label = labels[0]
        elif labels:
            segment.speaker_label = "mixed"
        else:
            segment.speaker_label = None
        segment.metadata = {
            **segment.metadata,
            "diarization": {
                "source": SORTFORMER_MAPPING_SOURCE,
                "speaker_label_counts": dict(sorted(_count_values(labels).items())),
                "mapped_word_count": len(labels),
                "total_word_count": len(segment_words),
                "acoustic_speaker_only": True,
            },
        }

    total_words = len(mapped.asr_words)
    mapped_words = sum(speaker_counts.values())
    coverage = mapped_words / total_words if total_words else 0.0
    mapping_status = "complete" if total_words and mapped_words == total_words else "partial"
    if not mapped_words:
        mapping_status = "missing"
    mapped.metadata = {
        **mapped.metadata,
        "diarization": {
            "schema_version": SPEAKER_DIARIZATION_RECORD_VERSION,
            "source": SORTFORMER_MAPPING_SOURCE,
            "diarization_record_id": diarization.record_id,
            "model_name": diarization.model.model_name,
            "model_version": diarization.model.model_version,
            "checkpoint_sha256": diarization.model.checkpoint_sha256,
            "timestamp_reference": timestamp_reference,
            "timestamp_offset_sec": timestamp_offset_sec,
            "mapping_status": mapping_status,
            "mapped_word_count": mapped_words,
            "total_word_count": total_words,
            "mapping_coverage": coverage,
            "mapping_status_counts": dict(sorted(status_counts.items())),
            "speaker_word_counts": dict(sorted(speaker_counts.items())),
            "min_overlap_ratio": min_overlap_ratio,
            "ambiguity_ratio": ambiguity_ratio,
            "acoustic_speaker_only": True,
            "speaker_roles_assigned": False,
            "reference_used": False,
        },
    }
    return ASRConfidenceRecord.model_validate(mapped.model_dump(mode="json"))


def map_diarization_to_asr_records(
    records: Iterable[ASRConfidenceRecord],
    diarization_records: Iterable[SpeakerDiarizationRecord],
    *,
    min_overlap_ratio: float = 0.10,
    ambiguity_ratio: float = 0.90,
    overwrite_existing: bool = False,
    max_same_speaker_bridge_gap_sec: float | None = 1.5,
) -> list[ASRConfidenceRecord]:
    """按 ``dataset + consultation_id`` 批量映射并桥接同人短空洞。

    桥接只处理前后声学标签相同、持续时间不超过阈值，且原始状态为
    ``no_overlap`` / ``insufficient_overlap`` 的未映射字词。重叠歧义、说话人
    交界和长静音始终保留为未知；原始声学判断保存在 word metadata 中。
    """

    if (
        max_same_speaker_bridge_gap_sec is not None
        and max_same_speaker_bridge_gap_sec < 0
    ):
        raise ValueError("max_same_speaker_bridge_gap_sec 不能小于 0")

    diarization_by_key: dict[tuple[str, str], SpeakerDiarizationRecord] = {}
    for diarization in diarization_records:
        key = (diarization.dataset, diarization.consultation_id)
        if key in diarization_by_key:
            raise ValueError(f"同一病例存在多条 diarization 记录：{key}")
        diarization_by_key[key] = diarization

    mapped_records: list[ASRConfidenceRecord] = []
    for record in records:
        consultation_id = str(record.consultation_id or record.sample_id)
        key = (record.dataset, consultation_id)
        diarization = diarization_by_key.get(key)
        if diarization is None:
            mapped_records.append(record.model_copy(deep=True))
            continue
        mapped_records.append(
            apply_diarization_to_asr_record(
                record,
                diarization,
                min_overlap_ratio=min_overlap_ratio,
                ambiguity_ratio=ambiguity_ratio,
                overwrite_existing=overwrite_existing,
            )
        )
    if max_same_speaker_bridge_gap_sec is None:
        return mapped_records
    return bridge_same_speaker_short_gaps(
        mapped_records,
        max_gap_sec=max_same_speaker_bridge_gap_sec,
    )


def bridge_same_speaker_short_gaps(
    records: Iterable[ASRConfidenceRecord],
    *,
    max_gap_sec: float = 1.5,
    bridgeable_mapping_statuses: frozenset[str] = DEFAULT_BRIDGEABLE_MAPPING_STATUSES,
) -> list[ASRConfidenceRecord]:
    """保守回填被 VAD/时间映射短空洞切开的同一说话人字词。

    这里得到的是可审计的上下文推断标签，不会改写 ``speaker_label`` 字段中
    保存的原始声学映射证据，也不会桥接 ``ambiguous_overlap``。
    """

    if max_gap_sec < 0:
        raise ValueError("max_gap_sec 不能小于 0")

    bridged_records = [record.model_copy(deep=True) for record in records]
    groups: dict[tuple[str, str, str], list[ASRConfidenceRecord]] = defaultdict(list)
    for record in bridged_records:
        diarization_metadata = record.metadata.get("diarization")
        if not isinstance(diarization_metadata, dict):
            continue
        consultation_id = str(record.consultation_id or record.sample_id)
        diarization_record_id = str(
            diarization_metadata.get("diarization_record_id") or ""
        )
        groups[(record.dataset, consultation_id, diarization_record_id)].append(record)

    for group_records in groups.values():
        word_refs = _speaker_word_references(group_records)
        position = 0
        while position < len(word_refs):
            if _meaningful_word_speaker(word_refs[position][1]) is not None:
                position += 1
                continue
            run_start = position
            while (
                position < len(word_refs)
                and _meaningful_word_speaker(word_refs[position][1]) is None
            ):
                position += 1
            run_end = position
            if run_start == 0 or run_end == len(word_refs):
                continue

            previous_ref = word_refs[run_start - 1]
            next_ref = word_refs[run_end]
            previous_label = _meaningful_word_speaker(previous_ref[1])
            next_label = _meaningful_word_speaker(next_ref[1])
            if previous_label is None or previous_label != next_label:
                continue

            unknown_refs = word_refs[run_start:run_end]
            if not all(
                _word_mapping_status(word) in bridgeable_mapping_statuses
                for _, word, _, _ in unknown_refs
            ):
                continue
            previous_end_sec = previous_ref[3]
            next_start_sec = next_ref[2]
            if previous_end_sec is None or next_start_sec is None:
                continue
            raw_gap_sec = next_start_sec - previous_end_sec
            if raw_gap_sec < -0.05 or raw_gap_sec > max_gap_sec:
                continue
            bridge_gap_sec = max(0.0, raw_gap_sec)
            for _, word, _, _ in unknown_refs:
                evidence = word.metadata.get("diarization")
                if not isinstance(evidence, dict):
                    continue
                word.speaker_label = previous_label
                word.metadata = {
                    **word.metadata,
                    "diarization": {
                        **evidence,
                        "resolved_speaker_label": previous_label,
                        "speaker_label_source": SAME_SPEAKER_GAP_BRIDGE_SOURCE,
                        "smoothing_status": "bridged_same_speaker_context",
                        "smoothing": {
                            "source": SAME_SPEAKER_GAP_BRIDGE_SOURCE,
                            "max_gap_sec": max_gap_sec,
                            "observed_gap_sec": round(bridge_gap_sec, 6),
                            "run_word_count": len(unknown_refs),
                            "flanking_speaker_label": previous_label,
                            "original_mapping_status": evidence.get("mapping_status"),
                            "ambiguous_overlap_bridged": False,
                        },
                    },
                }

        _refresh_resolved_speaker_metadata(
            group_records,
            max_gap_sec=max_gap_sec,
            bridgeable_mapping_statuses=bridgeable_mapping_statuses,
        )

    return [
        ASRConfidenceRecord.model_validate(record.model_dump(mode="json"))
        for record in bridged_records
    ]


def _speaker_word_references(
    records: Sequence[ASRConfidenceRecord],
) -> list[tuple[ASRConfidenceRecord, ASRWord, float | None, float | None]]:
    references: list[
        tuple[ASRConfidenceRecord, ASRWord, float | None, float | None]
    ] = []
    for record in records:
        timestamp_offset_sec, _ = _mapping_timestamp_offset(record)
        for word in record.asr_words:
            start_sec = (
                None if word.start_sec is None else word.start_sec + timestamp_offset_sec
            )
            end_sec = None if word.end_sec is None else word.end_sec + timestamp_offset_sec
            references.append((record, word, start_sec, end_sec))
    return sorted(
        references,
        key=lambda item: (
            item[2] if item[2] is not None else float("inf"),
            item[3] if item[3] is not None else float("inf"),
            item[0].record_id,
            item[1].word_index,
        ),
    )


def _meaningful_word_speaker(word: ASRWord) -> str | None:
    label = str(word.speaker_label or "").strip()
    if not label or label.casefold() in {"mixed", "unknown", "speaker_unknown"}:
        return None
    return label


def _word_mapping_status(word: ASRWord) -> str | None:
    evidence = word.metadata.get("diarization")
    if not isinstance(evidence, dict):
        return None
    status = str(evidence.get("mapping_status") or "").strip()
    return status or None


def _refresh_resolved_speaker_metadata(
    records: Sequence[ASRConfidenceRecord],
    *,
    max_gap_sec: float,
    bridgeable_mapping_statuses: frozenset[str],
) -> None:
    for record in records:
        resolved_speaker_counts: dict[str, int] = defaultdict(int)
        smoothed_word_count = 0
        for word in record.asr_words:
            label = _meaningful_word_speaker(word)
            if label:
                resolved_speaker_counts[label] += 1
            evidence = word.metadata.get("diarization")
            if isinstance(evidence, dict) and evidence.get("smoothing_status"):
                smoothed_word_count += 1

        for segment in record.asr_segments:
            segment_words = record.asr_words[
                segment.start_word_index : segment.end_word_index
            ]
            labels = [
                label
                for word in segment_words
                if (label := _meaningful_word_speaker(word)) is not None
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
                    "smoothed_word_count": sum(
                        bool(
                            isinstance(word.metadata.get("diarization"), dict)
                            and word.metadata["diarization"].get("smoothing_status")
                        )
                        for word in segment_words
                    ),
                },
            }

        total_word_count = len(record.asr_words)
        resolved_word_count = sum(resolved_speaker_counts.values())
        resolved_status = (
            "complete"
            if total_word_count and resolved_word_count == total_word_count
            else "partial"
        )
        if not resolved_word_count:
            resolved_status = "missing"
        existing_record_metadata = record.metadata.get("diarization")
        record_diarization = (
            dict(existing_record_metadata)
            if isinstance(existing_record_metadata, dict)
            else {}
        )
        record.metadata = {
            **record.metadata,
            "diarization": {
                **record_diarization,
                "resolved_status": resolved_status,
                "resolved_word_count": resolved_word_count,
                "resolved_coverage": (
                    resolved_word_count / total_word_count if total_word_count else 0.0
                ),
                "resolved_speaker_word_counts": dict(
                    sorted(resolved_speaker_counts.items())
                ),
                "smoothed_word_count": smoothed_word_count,
                "smoothing": {
                    "source": SAME_SPEAKER_GAP_BRIDGE_SOURCE,
                    "enabled": True,
                    "max_gap_sec": max_gap_sec,
                    "bridgeable_mapping_statuses": sorted(
                        bridgeable_mapping_statuses
                    ),
                    "ambiguous_overlap_bridged": False,
                },
            },
        }


def read_speaker_diarization_jsonl(path: str | Path) -> list[SpeakerDiarizationRecord]:
    """读取 speaker diarization JSONL。"""

    records: list[SpeakerDiarizationRecord] = []
    jsonl_path = Path(path)
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                records.append(SpeakerDiarizationRecord.model_validate_json(line))
            except Exception as exc:
                raise ValueError(
                    f"无法解析 speaker diarization JSONL 第 {line_number} 行：{jsonl_path}"
                ) from exc
    return records


def write_speaker_diarization_jsonl(
    records: Iterable[SpeakerDiarizationRecord],
    path: str | Path,
) -> None:
    """写入 speaker diarization JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _mapping_timestamp_offset(record: ASRConfidenceRecord) -> tuple[float, str]:
    source_manifest = record.metadata.get("source_manifest")
    if not isinstance(source_manifest, dict):
        return 0.0, "record_timestamp_assumed_source_absolute"
    reference = str(source_manifest.get("timestamp_reference") or "")
    if reference == "source_audio_absolute":
        return 0.0, reference
    offset = source_manifest.get("timestamp_offset_sec")
    if offset is None:
        offset = source_manifest.get("source_start_sec")
    return float(offset or 0.0), reference or "asr_input_audio_relative"


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return dict(counts)
