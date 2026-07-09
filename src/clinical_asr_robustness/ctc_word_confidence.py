"""CTC posterior/log-probability 到词级 ASR confidence 的轻量实现。

本模块服务于 T043：只复用“frame-level CTC posterior / entropy →
token confidence → word confidence”的流水线，不训练模型、不替换现有
NeMo FastConformer-CTC 主干。

设计重点：

- 输入可以是 frame-level logits、log_probs 或 posterior；
- 先在每帧上计算 max-prob 或 entropy-based confidence；
- 按 CTC greedy collapse 把非 blank 帧聚合到 token；
- 再按 SentencePiece/BPE 词边界把 token 聚合到 word；
- 可把帧级分布与聚合诊断保存为 `.npz` artifact，便于后续复算。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

CTC_FRAME_ARTIFACT_VERSION = "ctc_frame_distribution/v1"
SUPPORTED_FRAME_SCORE_TYPES = {"logits", "log_probs", "posterior"}
SUPPORTED_CONFIDENCE_METHODS = {"entropy", "max_prob"}
SUPPORTED_ENTROPY_TYPES = {"gibbs", "tsallis", "renyi"}
SUPPORTED_ENTROPY_NORMS = {"lin", "exp"}
SUPPORTED_AGGREGATIONS = {"mean", "min", "max", "prod"}


@dataclass(frozen=True)
class CTCTokenSpan:
    """CTC collapse 后的一个输出 token 覆盖的帧范围。"""

    token_index: int
    token_id: int
    start_frame: int
    end_frame: int
    token_text: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class CTCWordConfidenceResult:
    """从帧级分布聚合出的 token/word confidence 结果。"""

    frame_confidence: list[float]
    frame_token_ids: list[int]
    token_spans: list[CTCTokenSpan]
    word_confidences: list[float | None]
    word_token_spans: list[tuple[int, int] | None]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CTCFrameDistributionArtifact:
    """`.npz` 帧级分布 artifact 的读取结果。"""

    frame_values: np.ndarray
    value_type: str
    metadata: dict[str, Any]


def compute_ctc_word_confidence(
    frame_scores: Any,
    *,
    score_type: str,
    blank_id: int,
    transcript: str,
    token_texts_by_id: Mapping[int, str] | Sequence[str] | None = None,
    method_name: str = "entropy",
    entropy_type: str = "tsallis",
    alpha: float = 0.33,
    entropy_norm: str = "lin",
    token_aggregation: str = "mean",
    word_aggregation: str = "mean",
) -> CTCWordConfidenceResult:
    """从 CTC 帧级分布计算 word-level confidence。

    Args:
        frame_scores: `[T, V]` 数组，按 `score_type` 解释为 logits、log_probs
            或 posterior。
        score_type: `logits`、`log_probs` 或 `posterior`。
        blank_id: CTC blank token id。
        transcript: ASR 输出文本；仅用 `split()` 后的 word 数作为锚点。
        token_texts_by_id: 可选 token id → token string 映射。FastConformer-CTC
            BPE 通常使用 SentencePiece 的 `▁` 作为词边界；有该映射时可把
            CTC token span 聚合到 word。
        method_name: `entropy` 或 `max_prob`。
        entropy_type: `gibbs`、`tsallis` 或 `renyi`。
        alpha: entropy / max_prob 的 alpha 参数。
        entropy_norm: `lin` 或 `exp`。
        token_aggregation: 同一 CTC token 多帧 confidence 的聚合方式。
        word_aggregation: 一个 word 内多 token confidence 的聚合方式。
    """

    probabilities, log_probabilities = normalize_frame_scores(frame_scores, score_type)
    _validate_blank_id(blank_id, probabilities.shape[1])
    frame_confidence = frame_confidence_from_probabilities(
        probabilities,
        log_probabilities=log_probabilities,
        method_name=method_name,
        entropy_type=entropy_type,
        alpha=alpha,
        entropy_norm=entropy_norm,
    )
    frame_token_ids = probabilities.argmax(axis=1).astype(int).tolist()
    token_spans = collapse_ctc_token_spans(
        frame_token_ids,
        blank_id=blank_id,
        frame_confidence=frame_confidence,
        token_texts_by_id=token_texts_by_id,
        aggregation=token_aggregation,
    )
    transcript_words = transcript.split()
    word_token_spans = derive_word_token_spans(
        transcript_words=transcript_words,
        token_texts=[span.token_text for span in token_spans],
    )
    word_confidences = aggregate_token_confidence_to_words(
        [span.confidence for span in token_spans],
        word_token_spans=word_token_spans,
        word_count=len(transcript_words),
        aggregation=word_aggregation,
    )
    metadata = {
        "frame_count": int(probabilities.shape[0]),
        "vocab_size": int(probabilities.shape[1]),
        "blank_id": int(blank_id),
        "score_type": score_type,
        "method_name": method_name,
        "entropy_type": entropy_type if method_name == "entropy" else None,
        "alpha": alpha,
        "entropy_norm": entropy_norm if method_name == "entropy" else None,
        "token_aggregation": token_aggregation,
        "word_aggregation": word_aggregation,
        "transcript_word_count": len(transcript_words),
        "emitted_token_count": len(token_spans),
        "word_alignment_status": (
            "aligned"
            if len(word_token_spans) == len(transcript_words)
            and all(span is not None for span in word_token_spans)
            else "token_word_count_mismatch"
        ),
    }
    return CTCWordConfidenceResult(
        frame_confidence=[float(value) for value in frame_confidence],
        frame_token_ids=frame_token_ids,
        token_spans=token_spans,
        word_confidences=word_confidences,
        word_token_spans=word_token_spans,
        metadata=metadata,
    )


def normalize_frame_scores(frame_scores: Any, score_type: str) -> tuple[np.ndarray, np.ndarray]:
    """把 logits/log_probs/posterior 规整成 `(posterior, log_posterior)`。"""

    if score_type not in SUPPORTED_FRAME_SCORE_TYPES:
        raise ValueError(f"不支持的 frame score 类型：{score_type}")
    scores = np.asarray(_to_numpy(frame_scores), dtype=np.float64)
    if scores.ndim != 2:
        raise ValueError(f"frame_scores 必须是二维 [T, V] 数组，实际 shape={scores.shape}")
    if scores.shape[0] == 0 or scores.shape[1] < 2:
        raise ValueError("frame_scores 至少需要 1 帧和 2 个 vocabulary 维度")

    if score_type == "posterior":
        probabilities = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
        probabilities = np.clip(probabilities, 0.0, None)
        row_sums = probabilities.sum(axis=1, keepdims=True)
        if np.any(row_sums <= 0):
            raise ValueError("posterior 存在总概率 <= 0 的帧")
        probabilities = probabilities / row_sums
        log_probabilities = np.log(np.clip(probabilities, 1e-30, 1.0))
        return probabilities, log_probabilities

    if score_type == "log_probs":
        log_probabilities = np.nan_to_num(scores, nan=-np.inf, posinf=0.0, neginf=-np.inf)
        probabilities = np.exp(log_probabilities)
        row_sums = probabilities.sum(axis=1, keepdims=True)
        if np.any(row_sums <= 0):
            raise ValueError("log_probs 无法转换为有效 posterior")
        probabilities = probabilities / row_sums
        log_probabilities = np.log(np.clip(probabilities, 1e-30, 1.0))
        return probabilities, log_probabilities

    shifted = scores - np.max(scores, axis=1, keepdims=True)
    exp_scores = np.exp(np.nan_to_num(shifted, nan=-np.inf, posinf=0.0, neginf=-np.inf))
    row_sums = exp_scores.sum(axis=1, keepdims=True)
    if np.any(row_sums <= 0):
        raise ValueError("logits 无法转换为有效 posterior")
    probabilities = exp_scores / row_sums
    log_probabilities = np.log(np.clip(probabilities, 1e-30, 1.0))
    return probabilities, log_probabilities


def frame_confidence_from_probabilities(
    probabilities: np.ndarray,
    *,
    log_probabilities: np.ndarray | None = None,
    method_name: str = "entropy",
    entropy_type: str = "tsallis",
    alpha: float = 0.33,
    entropy_norm: str = "lin",
) -> np.ndarray:
    """按 NeMo/论文同类公式计算每帧 confidence。"""

    if method_name not in SUPPORTED_CONFIDENCE_METHODS:
        raise ValueError(f"不支持的 confidence method：{method_name}")
    if alpha <= 0:
        raise ValueError("alpha 必须大于 0")
    if method_name == "entropy":
        if entropy_type not in SUPPORTED_ENTROPY_TYPES:
            raise ValueError(f"不支持的 entropy type：{entropy_type}")
        if entropy_norm not in SUPPORTED_ENTROPY_NORMS:
            raise ValueError(f"不支持的 entropy norm：{entropy_norm}")

    probabilities = np.asarray(probabilities, dtype=np.float64)
    if log_probabilities is None:
        log_probabilities = np.log(np.clip(probabilities, 1e-30, 1.0))
    vocab_size = probabilities.shape[1]

    if method_name == "max_prob":
        max_prob = probabilities.max(axis=1)
        if alpha == 1.0:
            confidence = (max_prob * vocab_size - 1.0) / (vocab_size - 1.0)
        else:
            confidence = (
                np.power(max_prob, alpha) * math.pow(vocab_size, alpha) - 1.0
            ) / (math.pow(vocab_size, alpha) - 1.0)
        return np.clip(confidence, 0.0, 1.0)

    if entropy_type == "gibbs":
        confidence = _gibbs_entropy_confidence(
            probabilities,
            log_probabilities,
            vocab_size=vocab_size,
            alpha=alpha,
            norm=entropy_norm,
        )
    elif entropy_type == "tsallis":
        confidence = _tsallis_entropy_confidence(
            probabilities,
            log_probabilities,
            vocab_size=vocab_size,
            alpha=alpha,
            norm=entropy_norm,
        )
    else:
        confidence = _renyi_entropy_confidence(
            probabilities,
            log_probabilities,
            vocab_size=vocab_size,
            alpha=alpha,
            norm=entropy_norm,
        )
    return np.clip(np.nan_to_num(confidence, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)


def collapse_ctc_token_spans(
    frame_token_ids: Sequence[int],
    *,
    blank_id: int,
    frame_confidence: Sequence[float],
    token_texts_by_id: Mapping[int, str] | Sequence[str] | None = None,
    aggregation: str = "mean",
) -> list[CTCTokenSpan]:
    """按 CTC greedy 规则把帧级 token id collapse 成输出 token span。"""

    if len(frame_token_ids) != len(frame_confidence):
        raise ValueError("frame_token_ids 与 frame_confidence 长度必须一致")
    token_spans: list[CTCTokenSpan] = []
    active_token_id: int | None = None
    active_start: int | None = None

    def close_active(end_frame: int) -> None:
        nonlocal active_token_id, active_start
        if active_token_id is None or active_start is None:
            return
        token_confidence = aggregate_confidences(
            frame_confidence[active_start:end_frame],
            aggregation,
        )
        token_spans.append(
            CTCTokenSpan(
                token_index=len(token_spans),
                token_id=int(active_token_id),
                start_frame=active_start,
                end_frame=end_frame,
                token_text=token_text_for_id(token_texts_by_id, int(active_token_id)),
                confidence=token_confidence,
            )
        )
        active_token_id = None
        active_start = None

    for frame_index, raw_token_id in enumerate(frame_token_ids):
        token_id = int(raw_token_id)
        if token_id == blank_id:
            close_active(frame_index)
            continue
        if active_token_id is None:
            active_token_id = token_id
            active_start = frame_index
            continue
        if token_id != active_token_id:
            close_active(frame_index)
            active_token_id = token_id
            active_start = frame_index
    close_active(len(frame_token_ids))
    return token_spans


def derive_word_token_spans(
    *,
    transcript_words: Sequence[str],
    token_texts: Sequence[str | None],
) -> list[tuple[int, int] | None]:
    """用 SentencePiece/BPE 词边界把 token 范围映射到 transcript words。

    目前优先支持 NeMo FastConformer-CTC BPE 常见的 SentencePiece `▁` 词边界
    和 GPT/BPE 风格的 `Ġ`/前导空格。若无法得到与 transcript word 数量一致的
    span，则返回同等 word 数的 `None`，调用方可保留词但标记 confidence 缺失。
    """

    word_count = len(transcript_words)
    if word_count == 0:
        return []
    if not token_texts:
        return [None] * word_count

    boundaries: list[int] = [0]
    for index, token_text in enumerate(token_texts):
        if index == 0:
            continue
        text = token_text or ""
        if text.startswith(("▁", "Ġ", " ")):
            boundaries.append(index)
    boundaries.append(len(token_texts))
    spans = [
        (boundaries[index], boundaries[index + 1])
        for index in range(len(boundaries) - 1)
        if boundaries[index] < boundaries[index + 1]
    ]

    if len(spans) == word_count:
        return spans
    if len(token_texts) == word_count:
        return [(index, index + 1) for index in range(word_count)]
    return [None] * word_count


def aggregate_token_confidence_to_words(
    token_confidences: Sequence[float | None],
    *,
    word_token_spans: Sequence[tuple[int, int] | None],
    word_count: int,
    aggregation: str = "mean",
) -> list[float | None]:
    """按 word → token span 聚合 token confidence。"""

    if len(word_token_spans) != word_count:
        return [None] * word_count

    word_confidences: list[float | None] = []
    for span in word_token_spans:
        if span is None:
            word_confidences.append(None)
            continue
        start, end = span
        if start < 0 or end > len(token_confidences) or end <= start:
            word_confidences.append(None)
            continue
        word_confidences.append(aggregate_confidences(token_confidences[start:end], aggregation))
    return word_confidences


def aggregate_confidences(values: Sequence[float | None], method: str = "mean") -> float | None:
    """聚合 confidence 序列，忽略 None / NaN / inf。"""

    if method not in SUPPORTED_AGGREGATIONS:
        raise ValueError(f"不支持的聚合方式：{method}")
    valid = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            valid.append(number)
    if not valid:
        return None
    if method == "mean":
        return sum(valid) / len(valid)
    if method == "min":
        return min(valid)
    if method == "max":
        return max(valid)
    product = 1.0
    for value in valid:
        product *= value
    return product


def save_ctc_frame_distribution_artifact(
    path: str | Path,
    *,
    frame_values: Any,
    value_type: str,
    result: CTCWordConfidenceResult,
    transcript: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """保存帧级 logits/log_probs/posterior 与 word 聚合结果。"""

    if value_type not in SUPPORTED_FRAME_SCORE_TYPES:
        raise ValueError(f"不支持的 artifact value_type：{value_type}")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_array = np.asarray(_to_numpy(frame_values), dtype=np.float32)
    token_ids = np.asarray([span.token_id for span in result.token_spans], dtype=np.int64)
    token_start_frames = np.asarray(
        [span.start_frame for span in result.token_spans],
        dtype=np.int64,
    )
    token_end_frames = np.asarray(
        [span.end_frame for span in result.token_spans],
        dtype=np.int64,
    )
    token_confidences = _float_array_with_nan(
        [span.confidence for span in result.token_spans]
    )
    word_confidences = _float_array_with_nan(result.word_confidences)
    word_token_spans = np.asarray(
        [
            [-1, -1] if span is None else [span[0], span[1]]
            for span in result.word_token_spans
        ],
        dtype=np.int64,
    )
    artifact_metadata = {
        "schema_version": CTC_FRAME_ARTIFACT_VERSION,
        "value_type": value_type,
        "transcript": transcript,
        "token_texts": [span.token_text for span in result.token_spans],
        "result_metadata": result.metadata,
        **(metadata or {}),
    }
    np.savez_compressed(
        output_path,
        frame_values=frame_array,
        frame_confidence=np.asarray(result.frame_confidence, dtype=np.float32),
        frame_token_ids=np.asarray(result.frame_token_ids, dtype=np.int64),
        token_ids=token_ids,
        token_start_frames=token_start_frames,
        token_end_frames=token_end_frames,
        token_confidences=token_confidences,
        word_confidences=word_confidences,
        word_token_spans=word_token_spans,
        metadata_json=np.asarray(json.dumps(artifact_metadata, ensure_ascii=False)),
    )


def read_ctc_frame_distribution_artifact(path: str | Path) -> CTCFrameDistributionArtifact:
    """读取 `.npz` 帧级分布 artifact。"""

    artifact_path = Path(path)
    with np.load(artifact_path, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata_json"].item()))
        value_type = str(metadata.get("value_type") or "")
        if metadata.get("schema_version") != CTC_FRAME_ARTIFACT_VERSION:
            raise ValueError(f"不支持的 artifact schema：{metadata.get('schema_version')}")
        if value_type not in SUPPORTED_FRAME_SCORE_TYPES:
            raise ValueError(f"不支持的 artifact value_type：{value_type}")
        return CTCFrameDistributionArtifact(
            frame_values=np.asarray(data["frame_values"]),
            value_type=value_type,
            metadata=metadata,
        )


def word_confidence_metadata(
    result: CTCWordConfidenceResult,
    *,
    artifact_path: str | None = None,
) -> list[dict[str, Any]]:
    """为 `ASRWord.metadata` 生成每词 CTC confidence 诊断。"""

    metadata_by_word: list[dict[str, Any]] = []
    for word_index, word_span in enumerate(result.word_token_spans):
        payload: dict[str, Any] = {
            "source": "ctc_frame_distribution",
            "word_token_span": list(word_span) if word_span is not None else None,
            "word_confidence": result.word_confidences[word_index]
            if word_index < len(result.word_confidences)
            else None,
        }
        if word_span is not None:
            start, end = word_span
            payload["tokens"] = [
                {
                    "token_index": span.token_index,
                    "token_id": span.token_id,
                    "token_text": span.token_text,
                    "start_frame": span.start_frame,
                    "end_frame": span.end_frame,
                    "confidence": span.confidence,
                }
                for span in result.token_spans[start:end]
            ]
        if artifact_path:
            payload["artifact_path"] = artifact_path
        metadata_by_word.append({"ctc_word_confidence": payload})
    return metadata_by_word


def frame_scores_from_hypothesis(hypothesis: Any) -> Any | None:
    """从 NeMo Hypothesis 中取 transcribe 保存的帧级 log_probs/logits。"""

    value = getattr(hypothesis, "y_sequence", None)
    if value is None:
        return None
    array = _to_numpy(value)
    if np.asarray(array).ndim == 2:
        return array
    return None


def token_text_for_id(
    token_texts_by_id: Mapping[int, str] | Sequence[str] | None,
    token_id: int,
) -> str | None:
    """从 mapping/list 中取 token string。"""

    if token_texts_by_id is None:
        return None
    if isinstance(token_texts_by_id, Mapping):
        value = token_texts_by_id.get(token_id)
        return None if value is None else str(value)
    if 0 <= token_id < len(token_texts_by_id):
        return str(token_texts_by_id[token_id])
    return None


def _gibbs_entropy_confidence(
    probabilities: np.ndarray,
    log_probabilities: np.ndarray,
    *,
    vocab_size: int,
    alpha: float,
    norm: str,
) -> np.ndarray:
    if alpha == 1.0:
        neg_entropy = (probabilities * log_probabilities).sum(axis=1)
        if norm == "lin":
            return 1.0 + neg_entropy / math.log(vocab_size)
        return (np.exp(neg_entropy) * vocab_size - 1.0) / (vocab_size - 1.0)

    neg_entropy_alpha = (np.power(probabilities, alpha) * log_probabilities).sum(axis=1)
    if norm == "lin":
        return 1.0 + neg_entropy_alpha / math.log(vocab_size) / math.pow(
            vocab_size,
            1.0 - alpha,
        )
    exp_neg_max_entropy = math.pow(vocab_size, -alpha * math.pow(vocab_size, 1.0 - alpha))
    return (np.exp(neg_entropy_alpha * alpha) - exp_neg_max_entropy) / (
        1.0 - exp_neg_max_entropy
    )


def _tsallis_entropy_confidence(
    probabilities: np.ndarray,
    log_probabilities: np.ndarray,
    *,
    vocab_size: int,
    alpha: float,
    norm: str,
) -> np.ndarray:
    if alpha == 1.0:
        return _gibbs_entropy_confidence(
            probabilities,
            log_probabilities,
            vocab_size=vocab_size,
            alpha=alpha,
            norm=norm,
        )

    sum_p_alpha = np.power(probabilities, alpha).sum(axis=1)
    if norm == "lin":
        return 1.0 + (1.0 - sum_p_alpha) / (math.pow(vocab_size, 1.0 - alpha) - 1.0)
    exp_neg_max_entropy = math.exp(
        (1.0 - math.pow(vocab_size, 1.0 - alpha)) / (1.0 - alpha)
    )
    return (
        np.exp((1.0 - sum_p_alpha) / (1.0 - alpha)) - exp_neg_max_entropy
    ) / (1.0 - exp_neg_max_entropy)


def _renyi_entropy_confidence(
    probabilities: np.ndarray,
    log_probabilities: np.ndarray,
    *,
    vocab_size: int,
    alpha: float,
    norm: str,
) -> np.ndarray:
    if alpha == 1.0:
        return _gibbs_entropy_confidence(
            probabilities,
            log_probabilities,
            vocab_size=vocab_size,
            alpha=alpha,
            norm=norm,
        )

    sum_p_alpha = np.power(probabilities, alpha).sum(axis=1)
    if norm == "lin":
        return 1.0 + np.log2(sum_p_alpha) / (alpha - 1.0) / math.log(vocab_size, 2)
    return (np.power(sum_p_alpha, 1.0 / (alpha - 1.0)) * vocab_size - 1.0) / (
        vocab_size - 1.0
    )


def _to_numpy(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return value


def _float_array_with_nan(values: Sequence[float | None]) -> np.ndarray:
    return np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=np.float32,
    )


def _validate_blank_id(blank_id: int, vocab_size: int) -> None:
    if blank_id < 0 or blank_id >= vocab_size:
        raise ValueError(f"blank_id 越界：{blank_id}，vocab_size={vocab_size}")
