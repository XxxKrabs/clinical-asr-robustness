"""基础文本与任务评估指标。"""

from __future__ import annotations

from collections.abc import Iterable

try:
    from jiwer import wer as jiwer_wer
except ModuleNotFoundError:  # pragma: no cover - 依赖安装后优先走 jiwer
    jiwer_wer = None


def _levenshtein_distance(reference_tokens: list[str], hypothesis_tokens: list[str]) -> int:
    """计算 token 级编辑距离，用作 jiwer 不可用时的轻量后备。"""

    previous = list(range(len(hypothesis_tokens) + 1))
    for i, reference_token in enumerate(reference_tokens, start=1):
        current = [i]
        for j, hypothesis_token in enumerate(hypothesis_tokens, start=1):
            substitution_cost = 0 if reference_token == hypothesis_token else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """计算词错误率。

    reference 通常对应 clean transcript，hypothesis 对应 noisy 或 repaired transcript。
    """

    if jiwer_wer is not None:
        return float(jiwer_wer(reference, hypothesis))

    reference_tokens = reference.split()
    hypothesis_tokens = hypothesis.split()
    if not reference_tokens:
        return 0.0 if not hypothesis_tokens else 1.0
    return _levenshtein_distance(reference_tokens, hypothesis_tokens) / len(reference_tokens)


def term_recall(reference_terms: Iterable[str], hypothesis_text: str) -> float:
    """计算参考医学术语在候选文本中的召回率。

    这是一个很轻量的基线指标，适合项目早期做 sanity check。
    后续可以替换为医学实体识别或标准化后的术语匹配。
    """

    terms = [term.strip().lower() for term in reference_terms if term.strip()]
    if not terms:
        return 1.0

    text = hypothesis_text.lower()
    hits = sum(1 for term in terms if term in text)
    return hits / len(terms)


def relative_recovery(clean_score: float, noisy_score: float, repaired_score: float) -> float:
    """计算修复相对于 noisy 到 clean 差距的恢复比例。

    返回值示例：
    - 0.0：修复没有比 noisy 更好；
    - 1.0：修复达到 clean 表现；
    - 大于 1.0：修复超过 clean 基线；
    - 如果 clean_score 与 noisy_score 相等，则返回 0.0，避免除零。
    """

    gap = clean_score - noisy_score
    if gap == 0:
        return 0.0
    return (repaired_score - noisy_score) / gap
