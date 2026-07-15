"""NeMo ASR sequence-level n-best/beam 输出导出工具（T037）。

本模块只负责把 NeMo beam/n-best 的各种返回形状规范成项目侧 JSONL 可写
结构；不在顶层 import NeMo / torch，方便在无 GPU 环境中做单元测试。
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.nemo_confidence_export import to_jsonable

DEFAULT_NBEST_SOURCE = "nemo_beam_batch"
DEFAULT_RECORD_ID_PREFIX = "nemo_entropy"
NBEST_SCHEMA_VERSION = "asr_sequence_nbest/v1"
CLINICAL_USE_WARNING = "本记录仅用于研究评估，不构成临床建议。"


@dataclass(frozen=True)
class NemoBeamCandidate:
    """一条 sequence-level beam/n-best 候选。"""

    text: str
    rank: int
    score: float | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def configure_ctc_beam_nbest(
    model: Any,
    *,
    strategy: str = "beam_batch",
    beam_size: int = 5,
    beam_beta: float = 0.0,
    beam_threshold: float = 20.0,
    ngram_lm_alpha: float = 0.0,
    ngram_lm_model: str | None = None,
    allow_cuda_graphs: bool = True,
) -> dict[str, Any]:
    """配置 CTC beam 解码并要求返回 n-best hypotheses。

    第一版 T037 默认使用 `beam_batch`，因为它可以在没有 KenLM 的情况下生成
    acoustic-only n-best；若显式选择 `beam`/`pyctcdecode` 等策略，仍会把
    参数完整写入配置，便于实验记录追踪。
    """

    if beam_size <= 0:
        raise ValueError("beam_size 必须大于 0")

    from omegaconf import OmegaConf, open_dict

    hybrid_ctc = hasattr(model, "ctc_decoding") and hasattr(model.cfg, "aux_ctc")
    decoding_cfg = copy.deepcopy(
        model.cfg.aux_ctc.decoding if hybrid_ctc else model.cfg.decoding
    )
    with open_dict(decoding_cfg):
        decoding_cfg.strategy = strategy
        decoding_cfg.compute_timestamps = False
        decoding_cfg.preserve_alignments = False
        decoding_cfg.ctc_timestamp_type = "all"

        if "beam" not in decoding_cfg:
            decoding_cfg.beam = OmegaConf.create({})
        decoding_cfg.beam.beam_size = beam_size
        decoding_cfg.beam.return_best_hypothesis = False
        decoding_cfg.beam.compute_timestamps = False
        decoding_cfg.beam.preserve_alignments = False
        decoding_cfg.beam.beam_beta = beam_beta
        decoding_cfg.beam.beam_threshold = beam_threshold
        decoding_cfg.beam.ngram_lm_alpha = ngram_lm_alpha
        decoding_cfg.beam.ngram_lm_model = ngram_lm_model
        decoding_cfg.beam.allow_cuda_graphs = allow_cuda_graphs

        # Beam 路径只用于候选，不混入 greedy entropy confidence。
        if "confidence_cfg" in decoding_cfg:
            confidence_cfg = decoding_cfg.confidence_cfg
            confidence_cfg.preserve_frame_confidence = False
            confidence_cfg.preserve_token_confidence = False
            confidence_cfg.preserve_word_confidence = False

    if hybrid_ctc:
        model.change_decoding_strategy(decoding_cfg, decoder_type="ctc", verbose=False)
    else:
        model.change_decoding_strategy(decoding_cfg, verbose=False)
    result = to_jsonable(OmegaConf.to_container(decoding_cfg, resolve=True))
    result["project_decoder_type"] = "hybrid_aux_ctc" if hybrid_ctc else "ctc"
    return result


def flatten_nbest_transcription_results(transcription_result: Any) -> list[list[Any]]:
    """把 NeMo `transcribe()` 的 n-best 返回规整为每条音频一组 hypotheses。

    支持常见形状：

    - `List[List[Hypothesis]]`
    - `List[NBestHypotheses]`
    - `Tuple[List[List[Hypothesis]], ...]`
    - 退化的 `List[Hypothesis]` / 单个 Hypothesis
    """

    result = transcription_result
    if isinstance(result, tuple):
        if not result:
            return []
        result = result[0]

    if result is None:
        return []

    if _has_nbest_hypotheses(result):
        return [list(result.n_best_hypotheses or [])]

    if _is_beam_tuple(result):
        return [[result]]

    if not isinstance(result, list):
        return [[result]]

    groups: list[list[Any]] = []
    for item in result:
        if _has_nbest_hypotheses(item):
            groups.append(list(item.n_best_hypotheses or []))
        elif _is_beam_tuple(item):
            groups.append([item])
        elif isinstance(item, list):
            groups.append(item)
        else:
            groups.append([item])
    return groups


def extract_beam_candidates(
    hypothesis_group: Any,
    *,
    max_beams: int | None = None,
) -> list[NemoBeamCandidate]:
    """从一组 Hypothesis / tuple / dict 中提取去重后的 beam candidates。"""

    if max_beams is not None and max_beams <= 0:
        raise ValueError("max_beams 必须大于 0")

    raw_items = _coerce_group_to_items(hypothesis_group)
    candidates: list[NemoBeamCandidate] = []
    seen_texts: set[str] = set()
    for fallback_rank, item in enumerate(raw_items, start=1):
        candidate = _coerce_one_candidate(item, fallback_rank=fallback_rank)
        if candidate is None:
            continue
        normalized = normalize_text(candidate.text)
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        candidates.append(
            NemoBeamCandidate(
                text=" ".join(candidate.text.split()),
                rank=len(candidates) + 1,
                score=candidate.score,
                confidence=candidate.confidence,
                metadata={
                    **candidate.metadata,
                    "original_rank": candidate.rank,
                },
            )
        )
        if max_beams is not None and len(candidates) >= max_beams:
            break
    return candidates


def build_nbest_jsonl_record(
    *,
    manifest_record: dict[str, Any],
    hypothesis_group: Any,
    source: str = DEFAULT_NBEST_SOURCE,
    max_beams: int | None = None,
    record_id_prefix: str = DEFAULT_RECORD_ID_PREFIX,
    model_info: dict[str, Any] | None = None,
    decoding_config: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """构造一条可被 T029 直接读取的 sequence n-best JSON object。"""

    sample_id = str(manifest_record.get("sample_id") or "unknown_sample")
    candidates = extract_beam_candidates(hypothesis_group, max_beams=max_beams)
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    review_audio_filepath = (
        manifest_record.get("source_audio_filepath")
        or manifest_record.get("audio_filepath")
        or manifest_record.get("audio_path")
    )
    review_duration_sec = manifest_record.get("source_duration_sec")
    if review_duration_sec is None:
        review_duration_sec = manifest_record.get(
            "duration", manifest_record.get("duration_sec")
        )
    return {
        "schema_version": NBEST_SCHEMA_VERSION,
        "record_id": f"{record_id_prefix}_{safe_id(sample_id)}",
        "sample_id": sample_id,
        "dataset": manifest_record.get("dataset"),
        "split": manifest_record.get("split"),
        "consultation_id": manifest_record.get("consultation_id"),
        "source_channel": manifest_record.get("source_channel"),
        "audio_filepath": review_audio_filepath,
        "duration_sec": review_duration_sec,
        "source": source,
        "generated_at_utc": generated_at.isoformat(),
        "beams": [
            [candidate.text, candidate.score]
            if candidate.confidence is None
            else [candidate.text, candidate.score, candidate.confidence]
            for candidate in candidates
        ],
        "nbest": [
            {
                "rank": candidate.rank,
                "text": candidate.text,
                "score": candidate.score,
                "confidence": candidate.confidence,
                "source": source,
                "metadata": candidate.metadata,
            }
            for candidate in candidates
        ],
        "metadata": {
            "task_id": "T037",
            "model": model_info or {},
            "decoding": decoding_config or {},
            "runtime": runtime or {},
            "beam_count": len(candidates),
            "source_manifest": {
                "parent_sample_id": manifest_record.get("parent_sample_id"),
                "unit_id": manifest_record.get("unit_id"),
                "asr_input_audio_filepath": (
                    manifest_record.get("audio_filepath")
                    or manifest_record.get("audio_path")
                ),
                "source_audio_filepath": manifest_record.get("source_audio_filepath"),
                "source_audio_sha256": manifest_record.get("source_audio_sha256"),
                "source_duration_sec": manifest_record.get("source_duration_sec"),
                "source_start_sec": manifest_record.get("source_start_sec"),
                "source_end_sec": manifest_record.get("source_end_sec"),
                "timestamp_reference": (
                    "source_audio_absolute"
                    if manifest_record.get("source_audio_filepath")
                    else "asr_input_audio_relative"
                ),
            },
            "no_inline_reference_text": not bool(
                manifest_record.get("reference_text_included", False)
            ),
        },
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
    }


def normalize_text(text: str) -> str:
    """用于候选去重的轻量文本规范化。"""

    return " ".join(text.split()).casefold()


def safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "unknown"


def _coerce_group_to_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if _has_nbest_hypotheses(value):
        return list(value.n_best_hypotheses or [])
    if _is_beam_tuple(value):
        return [value]
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _coerce_one_candidate(item: Any, *, fallback_rank: int) -> NemoBeamCandidate | None:
    if item is None:
        return None

    if isinstance(item, str):
        text = item
        score = None
        confidence = None
        metadata: dict[str, Any] = {"candidate_shape": "str"}
    elif isinstance(item, dict):
        text = _first_present_string(item, "text", "pred_text", "transcript", "hypothesis")
        if text is None:
            return None
        score = _float_or_none(item.get("score", item.get("beam_score", item.get("logprob"))))
        confidence = _float_or_none(item.get("confidence"))
        metadata = {
            key: to_jsonable(value)
            for key, value in item.items()
            if key
            not in {
                "text",
                "pred_text",
                "transcript",
                "hypothesis",
                "score",
                "beam_score",
                "logprob",
                "confidence",
                "rank",
            }
        }
        metadata["candidate_shape"] = "dict"
    elif _is_beam_tuple(item):
        text = str(item[0])
        score = _float_or_none(item[1]) if len(item) > 1 else None
        confidence = _float_or_none(item[2]) if len(item) > 2 else None
        metadata = {"candidate_shape": "tuple", "raw_tuple_length": len(item)}
    else:
        text = str(getattr(item, "text", "") or "")
        if not text:
            return None
        score = _float_or_none(getattr(item, "score", None))
        confidence = _float_or_none(getattr(item, "confidence", None))
        metadata = {
            "candidate_shape": "hypothesis",
            "hypothesis_class": f"{item.__class__.__module__}.{item.__class__.__name__}",
        }

    text = " ".join(text.split())
    if not text:
        return None
    rank = _int_or_default(getattr(item, "rank", None), fallback_rank)
    if isinstance(item, dict):
        rank = _int_or_default(item.get("rank"), fallback_rank)
    return NemoBeamCandidate(
        text=text,
        rank=rank,
        score=score,
        confidence=confidence,
        metadata=metadata,
    )


def _has_nbest_hypotheses(value: Any) -> bool:
    return hasattr(value, "n_best_hypotheses")


def _is_beam_tuple(value: Any) -> bool:
    return isinstance(value, list | tuple) and bool(value) and isinstance(value[0], str)


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
    if hasattr(value, "detach"):
        try:
            value = value.detach().cpu()
        except (AttributeError, RuntimeError, TypeError):
            pass
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


def write_nbest_jsonl(records: list[dict[str, Any]], output_path: str | Path) -> None:
    """写出 T037 n-best JSONL。"""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(to_jsonable(record), ensure_ascii=False))
            file.write("\n")
