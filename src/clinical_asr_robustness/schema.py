"""项目数据结构定义。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from clinical_asr_robustness._compat import StrEnum


class TranscriptVariant(StrEnum):
    """转写文本版本。"""

    CLEAN = "clean_transcript"
    NOISY = "noisy_transcript"
    REPAIRED = "repaired_transcript"


class ErrorTag(StrEnum):
    """重点分析的 ASR 或对话转写错误类型。"""

    MEDICAL_TERM_ERROR = "medical_term_error"
    DRUG_NAME_ERROR = "drug_name_error"
    NEGATION_OMISSION = "negation_omission"
    SPEAKER_CONFUSION = "speaker_confusion"
    OVERLAP_OR_INTERRUPTION = "overlap_or_interruption"
    DISFLUENCY_OR_FILLER = "disfluency_or_filler"
    CODE_SWITCHING_ERROR = "code_switching_error"


class TranscriptSample(BaseModel):
    """clean / noisy / repaired transcript 对照样本。"""

    sample_id: str
    dataset: str
    split: str | None = None
    clean_transcript: str | None = None
    noisy_transcript: str | None = None
    repaired_transcript: str | None = None
    error_tags: list[ErrorTag] = Field(default_factory=list)
    notes: str | None = None

    def get_variant(self, variant: TranscriptVariant) -> str | None:
        """按版本名读取转写文本。"""

        return getattr(self, variant.value)
