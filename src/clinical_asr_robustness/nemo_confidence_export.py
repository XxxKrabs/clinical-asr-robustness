"""NeMo Hypothesis 到项目 ASR confidence schema 的适配工具。

本模块服务于 T028：把 NeMo entropy confidence 转写结果转换为
`ASRConfidenceRecord`。模块本身不在顶层 import NeMo / torch，方便单元测试在
无 GPU、无 NeMo 的环境中运行；真正的 NeMo 调用由
`scripts/export_nemo_asr_confidence.py` 完成。
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    AlignmentDiagnostics,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ASRSegment,
    ASRWord,
    ConfidenceLevel,
    ConfidenceThresholds,
    SourceChannel,
    UncertainSpan,
    confidence_level_for_score,
    join_asr_words,
)

DEFAULT_ALIGNMENT_NOTES = (
    "ASR units are anchored to transcript text/character offsets; extra NeMo timestamp/confidence "
    "items are recorded in dropped_extra_* instead of creating synthetic words."
)


def to_jsonable(value: Any) -> Any:
    """递归转换 numpy / torch 标量和张量，确保可写 JSON。"""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return to_jsonable(value.tolist())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def flatten_transcription_results(transcription_result: Any) -> list[Any]:
    """把 NeMo `transcribe()` 的多种返回形状规整为 Hypothesis 列表。"""

    result = transcription_result
    if isinstance(result, tuple):
        result = result[0]

    if not isinstance(result, list):
        return [result]

    hypotheses: list[Any] = []
    for item in result:
        if isinstance(item, list):
            if not item:
                raise TypeError("NeMo transcribe 返回了空 hypothesis 列表")
            hypotheses.append(item[0])
        else:
            hypotheses.append(item)
    return hypotheses


def configure_ctc_greedy_confidence(
    model: Any,
    *,
    method_name: str = "entropy",
    entropy_type: str = "tsallis",
    alpha: float = 0.33,
    entropy_norm: str = "lin",
    aggregation: str = "mean",
) -> dict[str, Any]:
    """打开 CTC greedy timestamps 与 NeMo word confidence。

    该函数延迟 import `omegaconf`，避免普通单元测试需要安装 NeMo 依赖。
    """

    from omegaconf import OmegaConf, open_dict

    hybrid_ctc = hasattr(model, "ctc_decoding") and hasattr(model.cfg, "aux_ctc")
    decoding_cfg = copy.deepcopy(
        model.cfg.aux_ctc.decoding if hybrid_ctc else model.cfg.decoding
    )
    method_cfg: dict[str, Any] = {"name": method_name}
    if method_name == "entropy":
        method_cfg.update(
            {
                "entropy_type": entropy_type,
                "alpha": alpha,
                "entropy_norm": entropy_norm,
            }
        )
    elif method_name == "max_prob":
        method_cfg["alpha"] = alpha
    else:
        raise ValueError(f"不支持的 NeMo confidence method：{method_name}")

    with open_dict(decoding_cfg):
        decoding_cfg.strategy = "greedy"
        decoding_cfg.compute_timestamps = True
        decoding_cfg.ctc_timestamp_type = "all"
        decoding_cfg.confidence_cfg = OmegaConf.merge(
            decoding_cfg.get("confidence_cfg", {}),
            {
                "preserve_frame_confidence": True,
                "preserve_token_confidence": True,
                "preserve_word_confidence": True,
                "exclude_blank": True,
                "aggregation": aggregation,
                "method_cfg": method_cfg,
            },
        )

    if hybrid_ctc:
        model.change_decoding_strategy(decoding_cfg, decoder_type="ctc", verbose=False)
    else:
        model.change_decoding_strategy(decoding_cfg, verbose=False)
    result = json.loads(json.dumps(OmegaConf.to_container(decoding_cfg, resolve=True)))
    result["project_decoder_type"] = "hybrid_aux_ctc" if hybrid_ctc else "ctc"
    return result


def aggregate_confidences(values: Iterable[Any], method: str = "mean") -> float | None:
    """聚合一组置信度；空值、NaN 和无穷值会被忽略。"""

    valid_values = [_float_or_none(value) for value in values]
    valid = [value for value in valid_values if value is not None]
    if not valid:
        return None

    if method == "mean":
        return sum(valid) / len(valid)
    if method == "min":
        return min(valid)
    if method == "max":
        return max(valid)
    if method == "prod":
        product = 1.0
        for value in valid:
            product *= value
        return product
    raise ValueError(f"不支持的置信度聚合方式：{method}")


def summarize_confidence_values(values: Iterable[Any]) -> dict[str, Any]:
    """返回一组 0~1 confidence 的基础分布统计，便于发现尺度异常。"""

    valid_values = [_float_or_none(value) for value in values]
    valid = sorted(value for value in valid_values if value is not None)
    if not valid:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p05": None,
            "p95": None,
            "p99": None,
        }

    return {
        "count": len(valid),
        "min": valid[0],
        "max": valid[-1],
        "mean": sum(valid) / len(valid),
        "median": _quantile_sorted(valid, 0.50),
        "p05": _quantile_sorted(valid, 0.05),
        "p95": _quantile_sorted(valid, 0.95),
        "p99": _quantile_sorted(valid, 0.99),
    }


def build_asr_confidence_record(
    *,
    manifest_record: dict[str, Any],
    hypothesis: Any,
    model_info: ASRModelInfo | dict[str, Any],
    decoding_config: ASRDecodingConfig | dict[str, Any],
    confidence_config: ASRConfidenceConfig | dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    record_id_prefix: str = "nemo_entropy",
    generated_at_utc: datetime | None = None,
    segment_max_words: int = 40,
    segment_max_gap_sec: float = 1.5,
    segment_confidence_aggregation: str = "mean",
    word_confidences_override: Iterable[Any] | None = None,
    word_confidence_source: str | None = None,
    word_confidence_metadata_by_index: list[dict[str, Any]] | None = None,
) -> ASRConfidenceRecord:
    """将一条 NeMo Hypothesis 转成项目侧 `ASRConfidenceRecord`。"""

    model = _coerce_model_info(model_info)
    decoding = _coerce_decoding_config(decoding_config)
    confidence = _coerce_confidence_config(confidence_config)
    thresholds = confidence.thresholds

    transcript = str(getattr(hypothesis, "text", "") or "")
    asr_words, alignment = build_words_and_alignment(
        transcript=transcript,
        hypothesis=hypothesis,
        thresholds=thresholds,
        text_unit_mode=str(manifest_record.get("text_unit_mode") or "whitespace"),
        word_confidences_override=word_confidences_override,
        word_confidence_source=word_confidence_source,
        word_confidence_metadata_by_index=word_confidence_metadata_by_index,
    )
    source_start_sec = _float_or_none(manifest_record.get("source_start_sec"))
    timestamp_offset_sec = source_start_sec or 0.0
    if timestamp_offset_sec:
        for word in asr_words:
            if word.start_sec is not None:
                word.start_sec += timestamp_offset_sec
            if word.end_sec is not None:
                word.end_sec += timestamp_offset_sec
    asr_confidence = aggregate_confidences(
        (word.confidence for word in asr_words),
        method="mean",
    )
    segments = build_segments_from_words(
        asr_words,
        max_words=segment_max_words,
        max_gap_sec=segment_max_gap_sec,
        confidence_aggregation=segment_confidence_aggregation,
        thresholds=thresholds,
        speaker_label=manifest_record.get("source_channel"),
    )
    uncertain_spans = build_uncertain_spans_from_words(asr_words, thresholds=thresholds)

    sample_id = str(manifest_record.get("sample_id") or "unknown_sample")
    source_channel = _source_channel_from_value(manifest_record.get("source_channel"))
    metadata = {
        "nemo": {
            "hypothesis_class": (
                f"{hypothesis.__class__.__module__}.{hypothesis.__class__.__name__}"
            ),
            "score": _float_or_none(getattr(hypothesis, "score", None)),
            "timestamp_keys": _timestamp_keys(hypothesis),
            "word_timestamp_count": len(_timestamp_items(hypothesis, "word")),
            "segment_timestamp_count": len(_timestamp_items(hypothesis, "segment")),
            "token_confidence_count": len(_sequence_to_list(
                getattr(hypothesis, "token_confidence", None)
            )),
            "frame_confidence_count": len(_sequence_to_list(
                getattr(hypothesis, "frame_confidence", None)
            )),
            "project_word_confidence_source": word_confidence_source
            or "nemo.word_confidence",
        },
        "segment_derivation": {
            "source": "asr_words",
            "max_words": segment_max_words,
            "max_gap_sec": segment_max_gap_sec,
            "confidence_aggregation": segment_confidence_aggregation,
        },
        "source_manifest": {
            "sample_id": sample_id,
            "parent_sample_id": manifest_record.get("parent_sample_id"),
            "unit_id": manifest_record.get("unit_id"),
            "consultation_sample_id": manifest_record.get("consultation_sample_id"),
            "asr_input_audio_filepath": (
                manifest_record.get("audio_filepath")
                or manifest_record.get("audio_path")
            ),
            "source_audio_filepath": manifest_record.get("source_audio_filepath"),
            "source_audio_sha256": manifest_record.get("source_audio_sha256"),
            "source_duration_sec": _float_or_none(
                manifest_record.get("source_duration_sec")
            ),
            "source_start_sec": source_start_sec,
            "source_end_sec": _float_or_none(manifest_record.get("source_end_sec")),
            "timestamp_reference": (
                "source_audio_absolute"
                if manifest_record.get("source_audio_filepath")
                else "asr_input_audio_relative"
            ),
            "timestamp_offset_sec": timestamp_offset_sec,
            "text_is_placeholder": manifest_record.get("text_is_placeholder"),
            "reference_text_included": manifest_record.get("reference_text_included", False),
        },
    }

    review_audio_filepath = (
        manifest_record.get("source_audio_filepath")
        or manifest_record.get("audio_filepath")
        or manifest_record.get("audio_path")
    )
    review_duration_sec = _float_or_none(manifest_record.get("source_duration_sec"))
    if review_duration_sec is None:
        review_duration_sec = _float_or_none(
            manifest_record.get("duration", manifest_record.get("duration_sec"))
        )

    return ASRConfidenceRecord(
        record_id=f"{record_id_prefix}_{_safe_id(sample_id)}",
        sample_id=sample_id,
        dataset=str(manifest_record.get("dataset") or "unknown"),
        split=manifest_record.get("split"),
        consultation_id=manifest_record.get("consultation_id"),
        source_channel=source_channel,
        audio_filepath=review_audio_filepath,
        duration_sec=review_duration_sec,
        reference_textgrid_path=manifest_record.get("reference_textgrid_path"),
        reference_transcript_path=manifest_record.get("reference_transcript_path"),
        reference_text_included=bool(manifest_record.get("reference_text_included", False)),
        generated_at_utc=generated_at_utc or datetime.now(timezone.utc),
        asr_transcript=transcript,
        asr_confidence=asr_confidence,
        confidence_level=confidence_level_for_score(asr_confidence, thresholds),
        asr_words=asr_words,
        asr_segments=segments,
        uncertain_spans=uncertain_spans,
        model=model,
        decoding=decoding,
        confidence=confidence,
        alignment=alignment,
        runtime=runtime or {},
        metadata=metadata,
    )


def build_words_and_alignment(
    *,
    transcript: str,
    hypothesis: Any,
    thresholds: ConfidenceThresholds | None = None,
    word_confidences_override: Iterable[Any] | None = None,
    word_confidence_source: str | None = None,
    word_confidence_metadata_by_index: list[dict[str, Any]] | None = None,
    text_unit_mode: str = "whitespace",
) -> tuple[list[ASRWord], AlignmentDiagnostics]:
    """以 transcript 文本单元为锚点对齐 timestamp/confidence。"""

    active_thresholds = thresholds or ConfidenceThresholds()
    word_timestamps = _timestamp_items(hypothesis, "word")
    words, char_offsets, active_text_unit_mode = _transcript_units_and_offsets(
        transcript,
        word_timestamps=word_timestamps,
        mode=text_unit_mode,
    )
    if word_confidences_override is None:
        word_confidences = _sequence_to_list(getattr(hypothesis, "word_confidence", None))
        active_confidence_source = word_confidence_source or "nemo.word_confidence"
    else:
        word_confidences = _sequence_to_list(list(word_confidences_override))
        active_confidence_source = (
            word_confidence_source or "ctc_frame_distribution.word_confidence"
        )
    metadata_by_index = word_confidence_metadata_by_index or []

    asr_words: list[ASRWord] = []
    missing_timestamp_indices: list[int] = []
    missing_confidence_indices: list[int] = []
    paired_word_count = 0

    for index, word in enumerate(words):
        timestamp = word_timestamps[index] if index < len(word_timestamps) else None
        start_sec = _timestamp_value(timestamp, "start", "start_sec", "start_time")
        end_sec = _timestamp_value(timestamp, "end", "end_sec", "end_time")
        confidence = (
            _float_or_none(word_confidences[index])
            if index < len(word_confidences)
            else None
        )
        char_start, char_end = char_offsets[index]
        previous_char_end = char_offsets[index - 1][1] if index > 0 else 0
        separator_before = (
            transcript[previous_char_end:char_start]
            if previous_char_end is not None and char_start is not None
            else None
        )

        if start_sec is None or end_sec is None:
            missing_timestamp_indices.append(index)
        if confidence is None:
            missing_confidence_indices.append(index)
        if start_sec is not None and end_sec is not None and confidence is not None:
            paired_word_count += 1

        asr_words.append(
            ASRWord(
                word_index=index,
                text=word,
                start_sec=start_sec,
                end_sec=end_sec,
                confidence=confidence,
                confidence_level=confidence_level_for_score(confidence, active_thresholds),
                timestamp_source="nemo.timestamp.word" if timestamp is not None else None,
                confidence_source=(
                    active_confidence_source if index < len(word_confidences) else None
                ),
                char_start=char_start,
                char_end=char_end,
                metadata={
                    **_word_metadata(timestamp),
                    **(
                        {"separator_before": separator_before}
                        if separator_before is not None
                        else {}
                    ),
                    **(
                        metadata_by_index[index]
                        if index < len(metadata_by_index)
                        and isinstance(metadata_by_index[index], dict)
                        else {}
                    ),
                },
            )
        )

    dropped_extra_timestamps = [
        {
            "raw_index": raw_index,
            "raw_value": to_jsonable(raw_value),
            "reason": "timestamp_without_output_word",
        }
        for raw_index, raw_value in enumerate(word_timestamps[len(words) :], start=len(words))
    ]
    dropped_extra_confidences = [
        {
            "raw_index": raw_index,
            "raw_value": to_jsonable(raw_value),
            "reason": "confidence_without_output_word",
        }
        for raw_index, raw_value in enumerate(word_confidences[len(words) :], start=len(words))
    ]

    alignment = AlignmentDiagnostics(
        transcript_word_count=len(words),
        word_timestamp_count=len(word_timestamps),
        word_confidence_count=len(word_confidences),
        asr_word_count=len(asr_words),
        paired_word_count=paired_word_count,
        missing_timestamp_word_indices=missing_timestamp_indices,
        missing_confidence_word_indices=missing_confidence_indices,
        dropped_extra_word_timestamps=dropped_extra_timestamps,
        dropped_extra_word_confidences=dropped_extra_confidences,
        notes=DEFAULT_ALIGNMENT_NOTES,
        metadata={
            "timestamp_source": "nemo.timestamp.word",
            "confidence_source": active_confidence_source,
            "confidence_override_used": word_confidences_override is not None,
            "text_unit_mode_requested": text_unit_mode,
            "text_unit_mode_active": active_text_unit_mode,
            "language_agnostic_char_offsets": True,
        },
    )
    return asr_words, alignment


def transcript_units_for_hypothesis(
    transcript: str,
    hypothesis: Any,
    *,
    mode: str = "whitespace",
) -> list[str]:
    """返回与 schema adapter 相同的语言感知文本单元，供 CTC 聚合复用。"""

    units, _, _ = _transcript_units_and_offsets(
        transcript,
        word_timestamps=_timestamp_items(hypothesis, "word"),
        mode=mode,
    )
    return units


def build_segments_from_words(
    words: list[ASRWord],
    *,
    max_words: int = 40,
    max_gap_sec: float = 1.5,
    confidence_aggregation: str = "mean",
    thresholds: ConfidenceThresholds | None = None,
    speaker_label: str | None = None,
) -> list[ASRSegment]:
    """从连续 ASR words 派生界面友好的 segment。"""

    if max_words <= 0:
        raise ValueError("max_words 必须大于 0")
    if not words:
        return []

    segments: list[ASRSegment] = []
    start_index = 0
    for index in range(1, len(words) + 1):
        should_close = index == len(words)
        if not should_close:
            current_count = index - start_index
            gap = _time_gap(words[index - 1], words[index])
            should_close = current_count >= max_words or (
                gap is not None and gap > max_gap_sec
            )
        if should_close:
            segment_words = words[start_index:index]
            confidence = aggregate_confidences(
                (word.confidence for word in segment_words),
                method=confidence_aggregation,
            )
            start_sec, end_sec = _time_range_for_words(segment_words)
            segments.append(
                ASRSegment(
                    segment_id=f"seg_{len(segments) + 1:03d}",
                    text=join_asr_words(segment_words),
                    start_word_index=start_index,
                    end_word_index=index,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    confidence=confidence,
                    confidence_level=confidence_level_for_score(confidence, thresholds),
                    confidence_aggregation=confidence_aggregation,
                    source="derived_from_asr_words",
                    speaker_label=speaker_label,
                    metadata={"word_count": len(segment_words)},
                )
            )
            start_index = index

    return segments


def build_uncertain_spans_from_words(
    words: list[ASRWord],
    *,
    thresholds: ConfidenceThresholds | None = None,
    include_unknown: bool = True,
) -> list[UncertainSpan]:
    """把连续中/低/未知置信度词合并为待审阅 span。"""

    spans: list[UncertainSpan] = []
    start_index: int | None = None

    def close_span(end_index: int) -> None:
        nonlocal start_index
        if start_index is None:
            return
        span_words = words[start_index:end_index]
        confidences = [word.confidence for word in span_words if word.confidence is not None]
        mean_confidence = aggregate_confidences(confidences, method="mean")
        min_confidence = aggregate_confidences(confidences, method="min")
        start_sec, end_sec = _time_range_for_words(span_words)
        spans.append(
            UncertainSpan(
                span_id=f"span_{len(spans) + 1:03d}",
                text=join_asr_words(span_words),
                start_word_index=start_index,
                end_word_index=end_index,
                start_sec=start_sec,
                end_sec=end_sec,
                mean_confidence=mean_confidence,
                min_confidence=min_confidence,
                confidence_level=_span_confidence_level(
                    min_confidence=min_confidence,
                    mean_confidence=mean_confidence,
                    thresholds=thresholds,
                    words=span_words,
                ),
                trigger_reason=_span_trigger_reason(span_words),
                metadata={"word_count": len(span_words)},
            )
        )
        start_index = None

    for index, word in enumerate(words):
        risky = word.confidence_level in {ConfidenceLevel.YELLOW, ConfidenceLevel.RED}
        risky = risky or (include_unknown and word.confidence_level == ConfidenceLevel.UNKNOWN)
        if risky and start_index is None:
            start_index = index
        elif not risky:
            close_span(index)
    close_span(len(words))
    return spans


def reclassify_confidence_record(
    record: ASRConfidenceRecord,
    thresholds: ConfidenceThresholds,
) -> ASRConfidenceRecord:
    """不重跑 ASR，按新阈值重算 record/word/segment/span 风险等级。

    该函数面向尚未附加 n-best 候选的 T028 原始记录。阈值改变会重建
    ``uncertain_spans``；若记录已有绑定旧 span id 的候选，直接拒绝处理，避免
    候选与新 span 边界静默错位。
    """

    if record.asr_alternatives:
        raise ValueError("已有 asr_alternatives 的记录不能直接重分级；请从 T028 原始记录重跑")

    updated = record.model_copy(deep=True)
    previous_thresholds = updated.confidence.thresholds.model_dump(mode="json")
    updated.confidence.thresholds = thresholds.model_copy(deep=True)
    updated.confidence_level = confidence_level_for_score(
        updated.asr_confidence,
        thresholds,
    )
    for word in updated.asr_words:
        word.confidence_level = confidence_level_for_score(word.confidence, thresholds)
    for segment in updated.asr_segments:
        segment.confidence_level = confidence_level_for_score(segment.confidence, thresholds)
    updated.uncertain_spans = build_uncertain_spans_from_words(
        updated.asr_words,
        thresholds=thresholds,
    )
    updated.metadata["confidence_threshold_reclassification"] = {
        "previous_thresholds": previous_thresholds,
        "active_thresholds": thresholds.model_dump(mode="json"),
        "method": "offline_threshold_reclassification_without_asr_rerun",
        "calibration_scope": "PriMock57 + NeMo native word_confidence research operating point",
        "clinical_calibration": False,
    }
    return ASRConfidenceRecord.model_validate(updated.model_dump(mode="json"))


def apply_demo_quantile_risk_levels(
    records: Iterable[ASRConfidenceRecord],
    *,
    red_fraction: float = 0.10,
    yellow_fraction: float = 0.20,
) -> list[ASRConfidenceRecord]:
    """按当前运行的 confidence 排名生成未校准 demo 绿/黄/红等级。"""

    if red_fraction <= 0 or yellow_fraction <= 0:
        raise ValueError("demo quantile 的 red/yellow fraction 必须大于 0")
    if red_fraction + yellow_fraction >= 1:
        raise ValueError("demo quantile 的 red + yellow fraction 必须小于 1")
    output = [record.model_copy(deep=True) for record in records]
    ranked = sorted(
        (
            (float(word.confidence), record_index, word.word_index)
            for record_index, record in enumerate(output)
            for word in record.asr_words
            if word.confidence is not None and math.isfinite(float(word.confidence))
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    if not ranked:
        return output

    red_count = min(len(ranked), max(1, math.ceil(len(ranked) * red_fraction)))
    yellow_count = min(
        len(ranked) - red_count,
        max(1, math.ceil(len(ranked) * yellow_fraction)),
    )
    for rank, (_, record_index, word_index) in enumerate(ranked):
        if rank < red_count:
            level = ConfidenceLevel.RED
        elif rank < red_count + yellow_count:
            level = ConfidenceLevel.YELLOW
        else:
            level = ConfidenceLevel.GREEN
        output[record_index].asr_words[word_index].confidence_level = level

    sorted_values = [item[0] for item in ranked]
    yellow_cut = sorted_values[min(red_count, len(sorted_values) - 1)]
    green_cut = sorted_values[
        min(red_count + yellow_count, len(sorted_values) - 1)
    ]
    if green_cut <= yellow_cut:
        if green_cut < 1.0:
            green_cut = math.nextafter(green_cut, 1.0)
        else:
            yellow_cut = math.nextafter(yellow_cut, 0.0)
    thresholds = ConfidenceThresholds(
        green_min=green_cut,
        yellow_min=yellow_cut,
    )

    policy_metadata = {
        "policy": "demo_quantile_v0",
        "calibrated": False,
        "scope": "selected_records_in_current_run",
        "red_fraction_requested": red_fraction,
        "yellow_fraction_requested": yellow_fraction,
        "valid_unit_count": len(ranked),
        "red_unit_count": red_count,
        "yellow_unit_count": yellow_count,
        "green_unit_count": len(ranked) - red_count - yellow_count,
        "rank_assignment": "confidence_ascending_then_record_and_unit_index",
        "quantile_cut_values": {
            "yellow_boundary": sorted_values[min(red_count, len(sorted_values) - 1)],
            "green_boundary": sorted_values[
                min(red_count + yellow_count, len(sorted_values) - 1)
            ],
        },
    }
    for record in output:
        record.confidence.thresholds = thresholds.model_copy(deep=True)
        record.confidence.metadata["risk_level_policy"] = policy_metadata
        record.confidence_level = confidence_level_for_score(
            record.asr_confidence,
            thresholds,
        )
        for segment in record.asr_segments:
            segment_words = record.asr_words[
                segment.start_word_index : segment.end_word_index
            ]
            levels = {word.confidence_level for word in segment_words}
            if ConfidenceLevel.RED in levels:
                segment.confidence_level = ConfidenceLevel.RED
            elif ConfidenceLevel.YELLOW in levels:
                segment.confidence_level = ConfidenceLevel.YELLOW
            elif ConfidenceLevel.UNKNOWN in levels:
                segment.confidence_level = ConfidenceLevel.UNKNOWN
            else:
                segment.confidence_level = ConfidenceLevel.GREEN
        record.uncertain_spans = build_uncertain_spans_from_words(
            record.asr_words,
            thresholds=thresholds,
        )
        record.metadata["risk_level_policy"] = policy_metadata
    return [
        ASRConfidenceRecord.model_validate(record.model_dump(mode="json"))
        for record in output
    ]


def _coerce_model_info(value: ASRModelInfo | dict[str, Any]) -> ASRModelInfo:
    if isinstance(value, ASRModelInfo):
        return value
    return ASRModelInfo.model_validate(value)


def _coerce_decoding_config(value: ASRDecodingConfig | dict[str, Any]) -> ASRDecodingConfig:
    if isinstance(value, ASRDecodingConfig):
        return value
    return ASRDecodingConfig.model_validate(value)


def _coerce_confidence_config(
    value: ASRConfidenceConfig | dict[str, Any] | None,
) -> ASRConfidenceConfig:
    if value is None:
        return ASRConfidenceConfig()
    if isinstance(value, ASRConfidenceConfig):
        return value
    return ASRConfidenceConfig.model_validate(value)


def _source_channel_from_value(value: Any) -> SourceChannel:
    if value is None:
        return SourceChannel.UNKNOWN
    try:
        return SourceChannel(str(value))
    except ValueError:
        return SourceChannel.UNKNOWN


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "unknown"


def _sequence_to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        if isinstance(converted, list):
            return converted
        return [converted]
    if isinstance(value, Iterable) and not isinstance(value, str | bytes | dict):
        return list(value)
    return [value]


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


def _quantile_sorted(values: list[float], q: float) -> float:
    """Nearest-rank-free 线性插值分位数；输入必须已升序。"""

    if not values:
        raise ValueError("values 不能为空")
    if q <= 0:
        return values[0]
    if q >= 1:
        return values[-1]
    position = (len(values) - 1) * q
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    lower = values[lower_index]
    upper = values[upper_index]
    weight = position - lower_index
    return lower + (upper - lower) * weight


def _timestamp_dict(hypothesis: Any) -> dict[str, Any]:
    timestamp = getattr(hypothesis, "timestamp", None)
    return timestamp if isinstance(timestamp, dict) else {}


def _timestamp_keys(hypothesis: Any) -> list[str]:
    return sorted(_timestamp_dict(hypothesis).keys())


def _timestamp_items(hypothesis: Any, key: str) -> list[Any]:
    return _sequence_to_list(_timestamp_dict(hypothesis).get(key))


def _timestamp_value(item: Any, *keys: str) -> float | None:
    if item is None:
        return None
    for key in keys:
        if isinstance(item, dict) and key in item:
            return _float_or_none(item.get(key))
        if hasattr(item, key):
            return _float_or_none(getattr(item, key))
    return None


def _word_metadata(timestamp: Any) -> dict[str, Any]:
    if timestamp is None:
        return {}
    raw_word = None
    if isinstance(timestamp, dict):
        raw_word = timestamp.get("word")
    elif hasattr(timestamp, "word"):
        raw_word = timestamp.word
    if raw_word is None:
        return {}
    return {"nemo_timestamp_word": to_jsonable(raw_word)}


def _timestamp_word_text(timestamp: Any) -> str | None:
    if isinstance(timestamp, dict):
        raw_word = timestamp.get("word")
    else:
        raw_word = getattr(timestamp, "word", None)
    if raw_word is None:
        return None
    text = str(raw_word).strip().lstrip("▁")
    return text or None


def _transcript_units_and_offsets(
    transcript: str,
    *,
    word_timestamps: list[Any],
    mode: str,
) -> tuple[list[str], list[tuple[int | None, int | None]], str]:
    supported_modes = {"auto", "whitespace", "timestamp", "character"}
    if mode not in supported_modes:
        raise ValueError(
            f"不支持的 text_unit_mode：{mode}；可选 {sorted(supported_modes)}"
        )

    whitespace_units = transcript.split()
    timestamp_units = [
        text for item in word_timestamps if (text := _timestamp_word_text(item)) is not None
    ]
    timestamp_offsets = _word_char_offsets(transcript, timestamp_units)
    timestamp_aligned = bool(timestamp_units) and all(
        start is not None and end is not None for start, end in timestamp_offsets
    )

    active_mode = mode
    if mode == "auto":
        if len(whitespace_units) > 1:
            active_mode = "whitespace"
        elif len(timestamp_units) > 1 and timestamp_aligned:
            active_mode = "timestamp"
        elif any("\u3400" <= char <= "\u9fff" for char in transcript):
            active_mode = "character"
        else:
            active_mode = "whitespace"

    if active_mode == "whitespace":
        return whitespace_units, _word_char_offsets(transcript, whitespace_units), active_mode
    if active_mode == "timestamp":
        if not timestamp_aligned:
            raise ValueError("timestamp text units 无法顺序对齐到 asr_transcript")
        return timestamp_units, timestamp_offsets, active_mode

    character_units = [char for char in transcript if not char.isspace()]
    character_offsets = [
        (index, index + 1)
        for index, char in enumerate(transcript)
        if not char.isspace()
    ]
    return character_units, character_offsets, "character"


def _word_char_offsets(text: str, words: list[str]) -> list[tuple[int | None, int | None]]:
    offsets: list[tuple[int | None, int | None]] = []
    search_from = 0
    for word in words:
        start = text.find(word, search_from)
        if start < 0:
            offsets.append((None, None))
            continue
        end = start + len(word)
        offsets.append((start, end))
        search_from = end
    return offsets


def _time_gap(previous_word: ASRWord, current_word: ASRWord) -> float | None:
    if previous_word.end_sec is None or current_word.start_sec is None:
        return None
    return current_word.start_sec - previous_word.end_sec


def _time_range_for_words(words: list[ASRWord]) -> tuple[float | None, float | None]:
    start_sec = next((word.start_sec for word in words if word.start_sec is not None), None)
    end_sec = next((word.end_sec for word in reversed(words) if word.end_sec is not None), None)
    return start_sec, end_sec


def _span_confidence_level(
    *,
    min_confidence: float | None,
    mean_confidence: float | None,
    thresholds: ConfidenceThresholds | None,
    words: list[ASRWord] | None = None,
) -> ConfidenceLevel:
    if words:
        levels = {word.confidence_level for word in words}
        if ConfidenceLevel.RED in levels:
            return ConfidenceLevel.RED
        if ConfidenceLevel.YELLOW in levels:
            return ConfidenceLevel.YELLOW
        if ConfidenceLevel.UNKNOWN in levels:
            return ConfidenceLevel.UNKNOWN
    level = confidence_level_for_score(
        min_confidence if min_confidence is not None else mean_confidence,
        thresholds,
    )
    if level == ConfidenceLevel.GREEN:
        return ConfidenceLevel.YELLOW
    return level


def _span_trigger_reason(words: list[ASRWord]) -> str:
    if any(word.confidence_level == ConfidenceLevel.RED for word in words):
        return "low_confidence"
    if any(word.confidence_level == ConfidenceLevel.YELLOW for word in words):
        return "medium_confidence"
    if any(word.confidence is None for word in words):
        return "missing_confidence"
    return "review_required"
