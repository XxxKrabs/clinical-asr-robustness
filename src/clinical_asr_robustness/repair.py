"""交互式文本 repair 数据结构与 JSONL 读写工具。

本模块对应 T017：只定义轻量、可演进的 repair 记录结构，不绑定具体
候选生成方法。后续 T018/T006 可以复用这些结构输出规则、词表、LLM
或人工交互模拟的 repair 结果。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_asr_robustness._compat import StrEnum
from clinical_asr_robustness.schema import ErrorTag

REPAIR_RECORD_VERSION = "interactive_repair_record/v1"
CLINICAL_USE_WARNING = "本记录仅用于研究评估，不构成临床建议。"


class RepairDecisionType(StrEnum):
    """repair 阈值决策或医生反馈后的最终决策类型。"""

    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_DOCTOR_REVIEW = "needs_doctor_review"
    DOCTOR_SELECTED = "doctor_selected"
    DOCTOR_EDITED = "doctor_edited"
    DOCTOR_REJECTED = "doctor_rejected"
    NO_CHANGE = "no_change"


class DoctorFeedbackAction(StrEnum):
    """医生或人工核验者对低置信度候选的动作。"""

    SELECT_CANDIDATE = "select_candidate"
    EDIT_TEXT = "edit_text"
    REJECT_ALL = "reject_all"
    ACCEPT_ORIGINAL = "accept_original"
    MARK_UNSURE = "mark_unsure"


class FeedbackSource(StrEnum):
    """反馈来源，用于区分真实医生参与和离线模拟。"""

    REAL_DOCTOR = "real_doctor"
    CLINICAL_REVIEWER = "clinical_reviewer"
    RESEARCHER_SIMULATION = "researcher_simulation"
    UNKNOWN = "unknown"


class RepairSpan(BaseModel):
    """一个可疑待修复片段。

    `start_char` / `end_char` 是相对于 `noisy_transcript` 的字符偏移。
    第一版候选生成若暂时没有稳定对齐结果，可以只填 `span_id` 与
    `original_text`，把偏移留空。
    """

    model_config = ConfigDict(extra="forbid")

    span_id: str
    original_text: str
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    context_before: str | None = None
    context_after: str | None = None
    error_tags: list[ErrorTag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_offsets(self) -> RepairSpan:
        """若提供字符偏移，则结束位置不能早于起始位置。"""

        if self.start_char is not None and self.end_char is not None:
            if self.end_char < self.start_char:
                raise ValueError("end_char 不能小于 start_char")
        return self


class RepairCandidate(BaseModel):
    """一个 span 的候选修复方案。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    span_id: str
    rank: int = Field(ge=1)
    original_text: str
    replacement_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    method_source: str
    method_version: str | None = None
    rationale: str | None = None
    evidence: list[str] = Field(default_factory=list)
    error_tags: list[ErrorTag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DoctorFeedback(BaseModel):
    """医生、医学背景核验者或离线模拟者留下的结构化反馈。"""

    model_config = ConfigDict(extra="forbid")

    action: DoctorFeedbackAction
    feedback_source: FeedbackSource = FeedbackSource.RESEARCHER_SIMULATION
    actor_role: str | None = None
    selected_candidate_id: str | None = None
    edited_text: str | None = None
    comment: str | None = None
    created_at_utc: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_payload(self) -> DoctorFeedback:
        """确保选择和编辑类反馈携带必要字段。"""

        if self.action == DoctorFeedbackAction.SELECT_CANDIDATE and not self.selected_candidate_id:
            raise ValueError("select_candidate 反馈必须填写 selected_candidate_id")
        if self.action == DoctorFeedbackAction.EDIT_TEXT and self.edited_text is None:
            raise ValueError("edit_text 反馈必须填写 edited_text")
        return self


class RepairDecision(BaseModel):
    """对一个 span 的阈值决策和最终采用结果。"""

    model_config = ConfigDict(extra="forbid")

    span_id: str
    decision_type: RepairDecisionType
    final_text: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    selected_candidate_id: str | None = None
    doctor_feedback: DoctorFeedback | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision_payload(self) -> RepairDecision:
        """约束自动采纳和医生决策的最小可追踪信息。"""

        if self.decision_type == RepairDecisionType.AUTO_ACCEPTED:
            if not self.selected_candidate_id:
                raise ValueError("auto_accepted 决策必须记录 selected_candidate_id")

        doctor_decisions = {
            RepairDecisionType.DOCTOR_SELECTED,
            RepairDecisionType.DOCTOR_EDITED,
            RepairDecisionType.DOCTOR_REJECTED,
        }
        if self.decision_type in doctor_decisions and self.doctor_feedback is None:
            raise ValueError(f"{self.decision_type} 决策必须记录 doctor_feedback")

        if self.decision_type == RepairDecisionType.DOCTOR_SELECTED:
            if not self.selected_candidate_id:
                raise ValueError("doctor_selected 决策必须记录 selected_candidate_id")

        return self

    @property
    def requires_doctor_review(self) -> bool:
        """该决策是否属于人工确认路径。"""

        return self.decision_type in {
            RepairDecisionType.NEEDS_DOCTOR_REVIEW,
            RepairDecisionType.DOCTOR_SELECTED,
            RepairDecisionType.DOCTOR_EDITED,
            RepairDecisionType.DOCTOR_REJECTED,
        }


class InteractiveRepairRecord(BaseModel):
    """一条 transcript repair 的可交互记录。

    第一阶段建议一行 JSONL 对应一个 noisy transcript 样本。`repair_candidates`
    保存所有 top-k 候选，`decisions` 保存阈值策略或医生反馈后的采用结果，
    `final_repaired_transcript` 保存合并后的最终文本。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REPAIR_RECORD_VERSION
    repair_id: str
    sample_id: str
    dataset: str
    split: str | None = None
    track: str | None = None
    source_variant: str = "noisy"
    noisy_transcript: str
    spans: list[RepairSpan] = Field(default_factory=list)
    repair_candidates: list[RepairCandidate] = Field(default_factory=list)
    decisions: list[RepairDecision] = Field(default_factory=list)
    final_repaired_transcript: str
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    method_name: str | None = None
    method_version: str | None = None
    interaction_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_use_only: bool = True
    clinical_use_warning: str = CLINICAL_USE_WARNING

    @model_validator(mode="after")
    def validate_references(self) -> InteractiveRepairRecord:
        """检查 span、candidate 和 decision 之间的轻量引用一致性。"""

        span_ids = [span.span_id for span in self.spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("spans 中存在重复 span_id")

        candidate_ids = [candidate.candidate_id for candidate in self.repair_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("repair_candidates 中存在重复 candidate_id")

        known_span_ids = set(span_ids)
        if known_span_ids:
            for candidate in self.repair_candidates:
                if candidate.span_id not in known_span_ids:
                    raise ValueError(f"候选引用了未知 span_id：{candidate.span_id}")
            for decision in self.decisions:
                if decision.span_id not in known_span_ids:
                    raise ValueError(f"决策引用了未知 span_id：{decision.span_id}")

        known_candidate_ids = set(candidate_ids)
        for decision in self.decisions:
            has_unknown_selected_candidate = (
                decision.selected_candidate_id
                and decision.selected_candidate_id not in known_candidate_ids
            )
            if has_unknown_selected_candidate:
                raise ValueError(
                    f"决策引用了未知 selected_candidate_id：{decision.selected_candidate_id}"
                )
            if (
                decision.doctor_feedback is not None
                and decision.doctor_feedback.selected_candidate_id is not None
                and decision.doctor_feedback.selected_candidate_id not in known_candidate_ids
            ):
                raise ValueError(
                    "doctor_feedback 引用了未知 selected_candidate_id："
                    f"{decision.doctor_feedback.selected_candidate_id}"
                )

        return self

    def candidates_for_span(self, span_id: str) -> list[RepairCandidate]:
        """按 rank 返回某个 span 的候选列表。"""

        return sorted(
            [candidate for candidate in self.repair_candidates if candidate.span_id == span_id],
            key=lambda candidate: candidate.rank,
        )

    def decisions_requiring_review(self) -> list[RepairDecision]:
        """返回仍处于或曾经过人工确认路径的决策。"""

        return [decision for decision in self.decisions if decision.requires_doctor_review]


def read_repair_jsonl(path: str | Path) -> list[InteractiveRepairRecord]:
    """读取交互式 repair JSONL。"""

    records: list[InteractiveRepairRecord] = []
    repair_path = Path(path)
    with repair_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(InteractiveRepairRecord.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - 保留文件与行号便于定位
                raise ValueError(
                    f"无法解析 repair JSONL 第 {line_number} 行：{repair_path}"
                ) from exc
    return records


def write_repair_jsonl(records: Iterable[InteractiveRepairRecord], path: str | Path) -> None:
    """写入交互式 repair JSONL。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")
