"""转写差异对齐、错误类型标注与 WER / MC-WER 计算。

本模块服务于项目早期的 T005/T008：给定 reference transcript 与 noisy
transcript，按 token 级 Levenshtein 对齐生成三类错误：

- substitution
- deletion
- insertion

其中 MC-WER 在 V0 中定义为 medical/clinical concept WER：只统计命中医学/临床
关键 token 的编辑错误，分母为 reference 中的医学/临床关键 token 数。这个定义是
轻量、可解释、可替换的；后续可以把 `medical_terms` 换成更完整的医学词表或实体识别器。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from clinical_asr_robustness._compat import StrEnum


class EditType(StrEnum):
    """T005 选定的 token 级错误类型。"""

    SUBSTITUTION = "substitution"
    DELETION = "deletion"
    INSERTION = "insertion"


class AlignmentType(StrEnum):
    """内部对齐操作类型。"""

    EQUAL = "equal"
    SUBSTITUTION = "substitution"
    DELETION = "deletion"
    INSERTION = "insertion"


TOKEN_PATTERN = re.compile(
    r"\[[^\]\s]+\]|[A-Za-z]+(?:[-'][A-Za-z]+)*|\d+(?:[/-]\d+)*(?:\.\d+)?",
    flags=re.UNICODE,
)

DEFAULT_MEDICAL_CONCEPT_TERMS = frozenset(
    {
        "abdomen",
        "abdominal",
        "abnormal",
        "allergist",
        "anemia",
        "anemic",
        "anxiety",
        "appendix",
        "appointment",
        "assessment",
        "asthma",
        "autism",
        "blood",
        "bowel",
        "b12",
        "capsule",
        "cardiac",
        "cbc",
        "chest",
        "chills",
        "colonoscopy",
        "congenital",
        "deficiency",
        "defibrillator",
        "depression",
        "diagnosed",
        "diagnosis",
        "dialysis",
        "dietician",
        "dose",
        "dysphagia",
        "egd",
        "ekg",
        "endoscopy",
        "er",
        "exam",
        "fatigued",
        "ferritin",
        "ferrous",
        "feverish",
        "fibroids",
        "folate",
        "follow-up",
        "geneticist",
        "gi",
        "heart",
        "heartburn",
        "hematocrit",
        "hematologist",
        "hemoglobin",
        "hysterectomy",
        "hypotonia",
        "indigestion",
        "intravenous",
        "iron",
        "kidney",
        "lungs",
        "mg",
        "milligram",
        "neurologist",
        "oxygen",
        "pacemaker",
        "pain",
        "palpation",
        "periods",
        "physical",
        "polyps",
        "recheck",
        "referral",
        "reflux",
        "sedation",
        "sleep",
        "sulfate",
        "supplements",
        "symptoms",
        "syndrome",
        "tablet",
        "tenderness",
        "therapy",
        "transplant",
        "ultrasound",
        "urinary",
        "vitamin",
        "wheezing",
        # 否定和极性词虽然不是医学实体，但在临床信息整理中属于高风险 token。
        "no",
        "not",
        "n't",
        "denies",
        "deny",
        "denied",
        "without",
        "normal",
        "negative",
        "positive",
    }
)

MEDICAL_SUFFIXES = (
    "algia",
    "ectomy",
    "emia",
    "genic",
    "itis",
    "ology",
    "ologist",
    "oma",
    "opathy",
    "oscopy",
    "osis",
    "uria",
)


@dataclass(frozen=True)
class AlignmentToken:
    """可回溯到原文本位置的对齐 token。"""

    text: str
    normalized: str
    index: int
    start_char: int
    end_char: int
    is_medical_concept: bool

    def to_public_dict(self) -> dict[str, Any]:
        """输出供 JSON 记录使用的轻量 token 信息。"""

        return {
            "text": self.text,
            "normalized": self.normalized,
            "token_index": self.index,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "is_medical_concept": self.is_medical_concept,
        }


@dataclass(frozen=True)
class AlignmentOperation:
    """一个 token 级编辑或匹配操作。"""

    operation: AlignmentType
    reference_tokens: tuple[AlignmentToken, ...]
    hypothesis_tokens: tuple[AlignmentToken, ...]


@dataclass(frozen=True)
class EditSpan:
    """连续同类编辑 span，可直接作为后续 repair candidate 的定位依据。"""

    error_type: EditType
    reference_tokens: tuple[AlignmentToken, ...]
    hypothesis_tokens: tuple[AlignmentToken, ...]

    @property
    def medical_concept_hit(self) -> bool:
        return any(
            token.is_medical_concept for token in self.reference_tokens + self.hypothesis_tokens
        )

    @property
    def reference_text(self) -> str:
        return " ".join(token.text for token in self.reference_tokens)

    @property
    def hypothesis_text(self) -> str:
        return " ".join(token.text for token in self.hypothesis_tokens)

    def to_public_dict(self, span_id: str) -> dict[str, Any]:
        """输出供 T005 JSONL 使用的 span 记录。"""

        reference_start = self.reference_tokens[0].index if self.reference_tokens else None
        reference_end = self.reference_tokens[-1].index + 1 if self.reference_tokens else None
        hypothesis_start = self.hypothesis_tokens[0].index if self.hypothesis_tokens else None
        hypothesis_end = self.hypothesis_tokens[-1].index + 1 if self.hypothesis_tokens else None

        return {
            "span_id": span_id,
            "error_type": self.error_type.value,
            "reference_token_start": reference_start,
            "reference_token_end": reference_end,
            "noisy_token_start": hypothesis_start,
            "noisy_token_end": hypothesis_end,
            "reference_text": self.reference_text,
            "noisy_text": self.hypothesis_text,
            "medical_concept_hit": self.medical_concept_hit,
            "reference_tokens": [token.to_public_dict() for token in self.reference_tokens],
            "noisy_tokens": [token.to_public_dict() for token in self.hypothesis_tokens],
            "candidate_source": "reference_alignment",
            "usable_for_repair_candidate": True,
        }


@dataclass(frozen=True)
class ErrorAnalysisResult:
    """单条 transcript pair 的对齐与指标结果。"""

    reference_tokens: tuple[AlignmentToken, ...]
    hypothesis_tokens: tuple[AlignmentToken, ...]
    operations: tuple[AlignmentOperation, ...]
    edit_spans: tuple[EditSpan, ...]
    substitution_count: int
    deletion_count: int
    insertion_count: int
    mc_substitution_count: int
    mc_deletion_count: int
    mc_insertion_count: int

    @property
    def reference_token_count(self) -> int:
        return len(self.reference_tokens)

    @property
    def hypothesis_token_count(self) -> int:
        return len(self.hypothesis_tokens)

    @property
    def error_count(self) -> int:
        return self.substitution_count + self.deletion_count + self.insertion_count

    @property
    def wer(self) -> float:
        if self.reference_token_count == 0:
            return 0.0 if self.hypothesis_token_count == 0 else 1.0
        return self.error_count / self.reference_token_count

    @property
    def mc_reference_token_count(self) -> int:
        return sum(token.is_medical_concept for token in self.reference_tokens)

    @property
    def mc_error_count(self) -> int:
        return self.mc_substitution_count + self.mc_deletion_count + self.mc_insertion_count

    @property
    def mc_wer(self) -> float | None:
        if self.mc_reference_token_count == 0:
            return None
        return self.mc_error_count / self.mc_reference_token_count

    @property
    def error_type_counts(self) -> dict[str, int]:
        return {
            EditType.SUBSTITUTION.value: self.substitution_count,
            EditType.DELETION.value: self.deletion_count,
            EditType.INSERTION.value: self.insertion_count,
        }

    def metrics_dict(self) -> dict[str, int | float | None]:
        """输出不含正文的指标摘要。"""

        return {
            "reference_token_count": self.reference_token_count,
            "noisy_token_count": self.hypothesis_token_count,
            "substitution_count": self.substitution_count,
            "deletion_count": self.deletion_count,
            "insertion_count": self.insertion_count,
            "wer": self.wer,
            "mc_reference_token_count": self.mc_reference_token_count,
            "mc_substitution_count": self.mc_substitution_count,
            "mc_deletion_count": self.mc_deletion_count,
            "mc_insertion_count": self.mc_insertion_count,
            "mc_wer": self.mc_wer,
        }


def normalize_token(token: str) -> str:
    """归一化 token，用于对齐比较。"""

    return token.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def is_medical_concept_token(normalized_token: str, medical_terms: set[str]) -> bool:
    """判断 token 是否属于 V0 MC-WER 的医学/临床关键 token。"""

    if normalized_token.startswith("[") and normalized_token.endswith("]"):
        return False
    if normalized_token in medical_terms:
        return True
    if any(character.isdigit() for character in normalized_token):
        return True
    return any(normalized_token.endswith(suffix) for suffix in MEDICAL_SUFFIXES)


def tokenize_for_alignment(
    text: str,
    medical_terms: set[str] | None = None,
) -> list[AlignmentToken]:
    """把 transcript 切成用于 WER/MC-WER 对齐的 token。"""

    terms = set(DEFAULT_MEDICAL_CONCEPT_TERMS if medical_terms is None else medical_terms)
    tokens: list[AlignmentToken] = []
    for index, match in enumerate(TOKEN_PATTERN.finditer(text)):
        surface = match.group(0)
        normalized = normalize_token(surface)
        tokens.append(
            AlignmentToken(
                text=surface,
                normalized=normalized,
                index=index,
                start_char=match.start(),
                end_char=match.end(),
                is_medical_concept=is_medical_concept_token(normalized, terms),
            )
        )
    return tokens


def _align_tokens_exact(
    reference_tokens: list[AlignmentToken],
    hypothesis_tokens: list[AlignmentToken],
) -> list[AlignmentOperation]:
    """用 Levenshtein 动态规划生成 token 级最小编辑对齐。"""

    reference_len = len(reference_tokens)
    hypothesis_len = len(hypothesis_tokens)
    costs = [[0] * (hypothesis_len + 1) for _ in range(reference_len + 1)]
    backtrace: list[list[AlignmentType | None]] = [
        [None] * (hypothesis_len + 1) for _ in range(reference_len + 1)
    ]

    for i in range(1, reference_len + 1):
        costs[i][0] = i
        backtrace[i][0] = AlignmentType.DELETION
    for j in range(1, hypothesis_len + 1):
        costs[0][j] = j
        backtrace[0][j] = AlignmentType.INSERTION

    for i in range(1, reference_len + 1):
        for j in range(1, hypothesis_len + 1):
            is_equal = reference_tokens[i - 1].normalized == hypothesis_tokens[j - 1].normalized
            diagonal_operation = AlignmentType.EQUAL if is_equal else AlignmentType.SUBSTITUTION
            diagonal_cost = costs[i - 1][j - 1] + (0 if is_equal else 1)
            deletion_cost = costs[i - 1][j] + 1
            insertion_cost = costs[i][j - 1] + 1

            # 同分时优先走 diagonal，使等长替换更符合人工直觉；再选 deletion / insertion。
            best_cost = min(diagonal_cost, deletion_cost, insertion_cost)
            if diagonal_cost == best_cost:
                costs[i][j] = diagonal_cost
                backtrace[i][j] = diagonal_operation
            elif deletion_cost == best_cost:
                costs[i][j] = deletion_cost
                backtrace[i][j] = AlignmentType.DELETION
            else:
                costs[i][j] = insertion_cost
                backtrace[i][j] = AlignmentType.INSERTION

    operations: list[AlignmentOperation] = []
    i = reference_len
    j = hypothesis_len
    while i > 0 or j > 0:
        operation = backtrace[i][j]
        if operation in {AlignmentType.EQUAL, AlignmentType.SUBSTITUTION}:
            operations.append(
                AlignmentOperation(
                    operation=operation,
                    reference_tokens=(reference_tokens[i - 1],),
                    hypothesis_tokens=(hypothesis_tokens[j - 1],),
                )
            )
            i -= 1
            j -= 1
        elif operation == AlignmentType.DELETION:
            operations.append(
                AlignmentOperation(
                    operation=operation,
                    reference_tokens=(reference_tokens[i - 1],),
                    hypothesis_tokens=(),
                )
            )
            i -= 1
        elif operation == AlignmentType.INSERTION:
            operations.append(
                AlignmentOperation(
                    operation=operation,
                    reference_tokens=(),
                    hypothesis_tokens=(hypothesis_tokens[j - 1],),
                )
            )
            j -= 1
        else:  # pragma: no cover - 理论上只会在空矩阵起点出现
            raise RuntimeError("对齐回溯遇到未知状态。")

    operations.reverse()
    return operations


def _align_large_replace_block(
    reference_tokens: list[AlignmentToken],
    hypothesis_tokens: list[AlignmentToken],
) -> list[AlignmentOperation]:
    """对过大的 replace 块做线性后备对齐。

    真实 ACI-Bench 对话很长，如果某个差异块过大，完整 DP 会非常慢。这里把重叠
    部分按 substitution/equal 对齐，再把剩余部分作为 deletion/insertion。该分支只在
    SequenceMatcher 没能把长文本拆成较小差异块时触发。
    """

    operations: list[AlignmentOperation] = []
    shared_length = min(len(reference_tokens), len(hypothesis_tokens))
    for index in range(shared_length):
        operation = (
            AlignmentType.EQUAL
            if reference_tokens[index].normalized == hypothesis_tokens[index].normalized
            else AlignmentType.SUBSTITUTION
        )
        operations.append(
            AlignmentOperation(
                operation=operation,
                reference_tokens=(reference_tokens[index],),
                hypothesis_tokens=(hypothesis_tokens[index],),
            )
        )

    for token in reference_tokens[shared_length:]:
        operations.append(
            AlignmentOperation(
                operation=AlignmentType.DELETION,
                reference_tokens=(token,),
                hypothesis_tokens=(),
            )
        )

    for token in hypothesis_tokens[shared_length:]:
        operations.append(
            AlignmentOperation(
                operation=AlignmentType.INSERTION,
                reference_tokens=(),
                hypothesis_tokens=(token,),
            )
        )

    return operations


def align_tokens(
    reference_tokens: list[AlignmentToken],
    hypothesis_tokens: list[AlignmentToken],
    *,
    exact_product_threshold: int = 40_000,
    replace_block_threshold: int = 250_000,
) -> list[AlignmentOperation]:
    """生成 token 级对齐。

    小样本直接用精确 Levenshtein DP。长对话先用 `SequenceMatcher` 找相同大块，
    再只对 replace 小块运行精确 DP，从而避免 T005 在长对话上超时。
    """

    if len(reference_tokens) * len(hypothesis_tokens) <= exact_product_threshold:
        return _align_tokens_exact(reference_tokens, hypothesis_tokens)

    reference_normalized = [token.normalized for token in reference_tokens]
    hypothesis_normalized = [token.normalized for token in hypothesis_tokens]
    matcher = SequenceMatcher(
        a=reference_normalized,
        b=hypothesis_normalized,
        autojunk=False,
    )

    operations: list[AlignmentOperation] = []
    for tag, ref_start, ref_end, hyp_start, hyp_end in matcher.get_opcodes():
        reference_block = reference_tokens[ref_start:ref_end]
        hypothesis_block = hypothesis_tokens[hyp_start:hyp_end]

        if tag == "equal":
            operations.extend(
                AlignmentOperation(
                    operation=AlignmentType.EQUAL,
                    reference_tokens=(reference_token,),
                    hypothesis_tokens=(hypothesis_token,),
                )
                for reference_token, hypothesis_token in zip(
                    reference_block,
                    hypothesis_block,
                    strict=True,
                )
            )
        elif tag == "delete":
            operations.extend(
                AlignmentOperation(
                    operation=AlignmentType.DELETION,
                    reference_tokens=(token,),
                    hypothesis_tokens=(),
                )
                for token in reference_block
            )
        elif tag == "insert":
            operations.extend(
                AlignmentOperation(
                    operation=AlignmentType.INSERTION,
                    reference_tokens=(),
                    hypothesis_tokens=(token,),
                )
                for token in hypothesis_block
            )
        elif len(reference_block) * len(hypothesis_block) <= replace_block_threshold:
            operations.extend(_align_tokens_exact(reference_block, hypothesis_block))
        else:
            operations.extend(_align_large_replace_block(reference_block, hypothesis_block))

    return operations


def collect_edit_spans(operations: list[AlignmentOperation]) -> list[EditSpan]:
    """把连续同类 token 级编辑合并为 span。"""

    spans: list[EditSpan] = []
    current_type: EditType | None = None
    current_reference: list[AlignmentToken] = []
    current_hypothesis: list[AlignmentToken] = []

    def flush() -> None:
        nonlocal current_type, current_reference, current_hypothesis
        if current_type is not None:
            spans.append(
                EditSpan(
                    error_type=current_type,
                    reference_tokens=tuple(current_reference),
                    hypothesis_tokens=tuple(current_hypothesis),
                )
            )
        current_type = None
        current_reference = []
        current_hypothesis = []

    for operation in operations:
        if operation.operation == AlignmentType.EQUAL:
            flush()
            continue

        edit_type = EditType(operation.operation.value)
        if current_type is not None and edit_type != current_type:
            flush()

        current_type = edit_type
        current_reference.extend(operation.reference_tokens)
        current_hypothesis.extend(operation.hypothesis_tokens)

    flush()
    return spans


def analyze_transcript_pair(
    reference_text: str,
    hypothesis_text: str,
    medical_terms: set[str] | None = None,
) -> ErrorAnalysisResult:
    """对单个 reference/noisy transcript pair 生成错误类型与指标。"""

    reference_tokens = tokenize_for_alignment(reference_text, medical_terms=medical_terms)
    hypothesis_tokens = tokenize_for_alignment(hypothesis_text, medical_terms=medical_terms)
    operations = align_tokens(reference_tokens, hypothesis_tokens)
    spans = collect_edit_spans(operations)

    substitution_count = 0
    deletion_count = 0
    insertion_count = 0
    mc_substitution_count = 0
    mc_deletion_count = 0
    mc_insertion_count = 0

    for operation in operations:
        if operation.operation == AlignmentType.SUBSTITUTION:
            substitution_count += 1
            if any(
                token.is_medical_concept
                for token in operation.reference_tokens + operation.hypothesis_tokens
            ):
                mc_substitution_count += 1
        elif operation.operation == AlignmentType.DELETION:
            deletion_count += 1
            if any(token.is_medical_concept for token in operation.reference_tokens):
                mc_deletion_count += 1
        elif operation.operation == AlignmentType.INSERTION:
            insertion_count += 1
            if any(token.is_medical_concept for token in operation.hypothesis_tokens):
                mc_insertion_count += 1

    return ErrorAnalysisResult(
        reference_tokens=tuple(reference_tokens),
        hypothesis_tokens=tuple(hypothesis_tokens),
        operations=tuple(operations),
        edit_spans=tuple(spans),
        substitution_count=substitution_count,
        deletion_count=deletion_count,
        insertion_count=insertion_count,
        mc_substitution_count=mc_substitution_count,
        mc_deletion_count=mc_deletion_count,
        mc_insertion_count=mc_insertion_count,
    )
