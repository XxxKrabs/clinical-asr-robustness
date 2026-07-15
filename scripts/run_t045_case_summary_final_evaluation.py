"""T045：全量三文本病例摘要生成与质量评测离线验收。

本脚本用于在没有外部 LLM/API、且全量 doctor selector 尚未完成时，先产出
T045 的可复现最终评测表：

- 从 PriMock57 doctor/patient TextGrid 构建 consultation-level clean/reference；
- 使用同一 deterministic keyword case-summary baseline 生成三种输入变体摘要；
- 从 clean/reference 自动抽取短 gold key facts；
- 调用既有 T042 source-aware B-lite 评测链路；
- 输出最终聚合 CSV/Markdown 表与 SVG 图。

重要边界：

- ``doctor_llm_repair`` 在本脚本中默认是 no-change simulated baseline，
  即不读取 clean/reference、不做真实医生选择，只把 noisy ASR 原样作为 repair 占位；
- 该 baseline 只用于打通 57 条全量三文本评测闭环，不能写成真实医生审阅结果；
- 聚合 summary、最终表和图不写完整 transcript；包含 transcript 的 JSONL 仍只放在
  data/processed/ 或 outputs/ 下游产物中，默认不提交 Git。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clinical_asr_robustness.asr_confidence import CLINICAL_USE_WARNING  # noqa: E402
from clinical_asr_robustness.case_summary_evaluation import (  # noqa: E402
    DEFAULT_FACT_CONTRADICTION_THRESHOLD,
    DEFAULT_FACT_SUPPORT_THRESHOLD,
    run_case_summary_quality_evaluation,
    run_gold_key_facts_validation,
    write_gold_key_facts_jsonl,
)
from clinical_asr_robustness.case_summary_generation import (  # noqa: E402
    CASE_SUMMARY_PROMPT_VERSION,
)

TASK_ID = "T045"
DATASET = "primock57"
INPUT_UNIT = "consultation"
SUMMARY_MODEL_NAME = "deterministic_keyword_case_summary_baseline/v1"
GOLD_EXTRACTOR_NAME = "deterministic_clean_reference_keyword_gold/v1"
T045_RUN_SCHEMA_VERSION = "t045_case_summary_final_evaluation_run/v1"
CLEAN_REFERENCE_SCHEMA_VERSION = "t045_clean_reference_consultation/v1"
REPAIR_BASELINE_SCHEMA_VERSION = "t045_doctor_llm_repair_no_change_baseline/v1"
CASE_SUMMARY_RECORD_SCHEMA_VERSION = "case_summary_generation_record/v1"
CASE_SUMMARY_GENERATION_SUMMARY_SCHEMA_VERSION = "t045_case_summary_generation_summary/v1"
FINAL_TABLE_SCHEMA_VERSION = "t045_case_summary_final_table/v1"

INPUT_VARIANTS = ("noisy_asr", "doctor_llm_repair", "clean_reference")
RESULT_TABLE_COLUMNS = (
    "input_variant",
    "record_count",
    "evaluated_record_count",
    "summary_fact_count",
    "gold_fact_count",
    "fact_precision_macro",
    "fact_recall_macro",
    "fact_f1_macro",
    "critical_fact_recall_macro",
    "rouge_l_f1_macro",
    "omission_count",
    "supported",
    "unsupported",
    "contradicted",
    "unverifiable",
    "uncertainty_required_records",
    "uncertainty_missing_records",
    "uncertainty_loose_coverage_rate",
    "high_risk_error_total",
    "review_action_total",
    "review_changed_span_count",
    "delta_fact_f1_vs_noisy",
    "delta_fact_recall_vs_noisy",
    "delta_omission_vs_noisy",
)

DEFAULT_NOISY_CONSULTATION_JSONL = (
    PROJECT_ROOT
    / "data/processed/primock57/asr_noisy_transcripts_full/"
    "primock57_noisy_transcripts_consultation.jsonl"
)
DEFAULT_TEXTGRID_DIR = PROJECT_ROOT / "data/external/primock57/transcripts"
DEFAULT_PROCESSED_DIR = (
    PROJECT_ROOT / "data/processed/primock57/t045_case_summary_three_texts"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t045_case_summary_three_texts"

TEXTGRID_VALUE_PATTERN = re.compile(
    r"^\s*(?P<key>xmin|xmax|text)\s*=\s*(?P<value>.*)\s*$"
)
TEXTGRID_TAG_PATTERN = re.compile(r"</?UNSURE>|<UNIN/>|<[^>]+>", flags=re.IGNORECASE)
TEXTGRID_FILENAME_PATTERN = re.compile(
    r"^(?P<consultation_id>day\d+_consultation\d+)_(?P<channel>doctor|patient)\.TextGrid$",
    flags=re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", flags=re.IGNORECASE)

NEGATION_MARKERS = {
    "no",
    "not",
    "none",
    "never",
    "denies",
    "deny",
    "denied",
    "without",
    "negative",
    "haven't",
    "hasn't",
    "didn't",
    "don't",
    "doesn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
}
QUESTION_CUES = {
    "do you",
    "did you",
    "have you",
    "has you",
    "are you",
    "any ",
    "anything",
    "where",
    "when",
    "what",
    "how",
    "can you",
    "would you",
}
DOCTOR_ASSERTION_CUES = {
    "you mentioned",
    "you've had",
    "you have had",
    "you had",
    "you've been",
    "you have been",
    "you started",
    "recap",
    "you've got",
    "you have got",
    "sounds like",
    "seems like",
}


@dataclass(frozen=True)
class Turn:
    consultation_id: str
    turn_index: int
    source_channel: str
    start_sec: float | None
    end_sec: float | None
    text: str


@dataclass(frozen=True)
class FactSpec:
    kind: str
    canonical: str
    patterns: tuple[str, ...]
    field: str | None = None
    polarity: str = "present"
    severity: str = "major"
    error_tags: tuple[str, ...] = ()
    source_channels: tuple[str, ...] = ("doctor", "patient")
    allow_doctor_question: bool = False


SYMPTOM_SPECS: tuple[FactSpec, ...] = (
    FactSpec(
        kind="symptom",
        canonical="diarrhoea",
        patterns=(
            r"\bdiarrh?oe?a\b",
            r"\bdiarrhea\b",
            r"\bloose stools?\b",
            r"\bwatery stools?\b",
            r"\bloose and watery\b",
            r"\bgoing to the toilet\b",
        ),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="abdominal pain",
        patterns=(
            r"\babdominal pain\b",
            r"\btummy pain\b",
            r"\bstomach pain\b",
            r"\blower abdomen\b",
            r"\blower stomach\b",
            r"\babdomen\b",
        ),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="vomiting",
        patterns=(r"\bvomit(?:ed|ing)?\b", r"\bthrow(?:ing)? up\b", r"\bsick\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="fever or high temperature",
        patterns=(r"\bfever(?:ish)?\b", r"\btemperature\b", r"\bfelt hot\b"),
        severity="safety_critical",
        error_tags=("negation_or_polarity", "medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="blood in stool or vomit",
        patterns=(
            r"\bblood in (?:your )?stools?\b",
            r"\bblood in (?:your )?vomit\b",
            r"\bbloody stools?\b",
            r"\bbloody vomit\b",
        ),
        severity="safety_critical",
        error_tags=("negation_or_polarity", "medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="weakness or lethargy",
        patterns=(r"\bweak\b", r"\bletharg(?:ic|y)\b", r"\bshaky\b", r"\btired\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="loss of appetite",
        patterns=(r"\bloss? of appetite\b", r"\bnot eating\b", r"\bappetite\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="chest pain",
        patterns=(r"\bchest pain\b",),
        severity="safety_critical",
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="shortness of breath",
        patterns=(r"\bshort(?:ness)? of breath\b", r"\bbreathless\b"),
        severity="safety_critical",
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="cough",
        patterns=(r"\bcough(?:ing)?\b",),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="headache",
        patterns=(r"\bheadache\b", r"\bhead pain\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="sore throat",
        patterns=(r"\bsore throat\b", r"\bthroat pain\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="rash",
        patterns=(r"\brash\b",),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="dizziness",
        patterns=(r"\bdizz(?:y|iness)\b", r"\blight ?headed\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="urinary symptoms",
        patterns=(
            r"\burin(?:e|ary)\b",
            r"\bpassing water\b",
            r"\bburning when (?:you )?wee\b",
            r"\bpain passing urine\b",
        ),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="symptom",
        canonical="back pain",
        patterns=(r"\bback pain\b", r"\bbackache\b"),
        error_tags=("medical_term", "asr_noise_sensitive"),
    ),
)

OTHER_FACT_SPECS: tuple[FactSpec, ...] = (
    FactSpec(
        kind="history",
        canonical="symptoms for about three days",
        field="history_of_present_illness",
        patterns=(r"\bthree days?\b", r"\b3 days?\b"),
        source_channels=("doctor", "patient"),
        error_tags=("temporality", "asr_noise_sensitive"),
    ),
    FactSpec(
        kind="history",
        canonical="symptoms started after takeaway or eating out",
        field="history_of_present_illness",
        patterns=(r"\btake ?away\b", r"\beating out\b", r"\bchinese restaurant\b"),
        source_channels=("doctor", "patient"),
        error_tags=("temporality", "medical_term"),
    ),
    FactSpec(
        kind="history",
        canonical="asthma history",
        field="relevant_history",
        patterns=(r"\basthma\b",),
        source_channels=("doctor", "patient"),
        error_tags=("medical_term",),
    ),
    FactSpec(
        kind="history",
        canonical="does not smoke",
        field="relevant_history",
        patterns=(r"\bdon't smoke\b", r"\bdo not smoke\b", r"\bno smoking\b"),
        source_channels=("doctor", "patient"),
        polarity="absent",
    ),
    FactSpec(
        kind="history",
        canonical="does not drink alcohol",
        field="relevant_history",
        patterns=(r"\bdon't drink\b", r"\bdo not drink\b", r"\bno alcohol\b"),
        source_channels=("doctor", "patient"),
        polarity="absent",
    ),
    FactSpec(
        kind="history",
        canonical="work or daily activities affected",
        field="relevant_history",
        patterns=(r"\bwork\b", r"\bday to day\b", r"\bdaily activit"),
        source_channels=("doctor", "patient"),
        error_tags=("temporality",),
    ),
    FactSpec(
        kind="medication",
        canonical="inhaler",
        field="medications",
        patterns=(r"\binhaler\b", r"\binhalers\b"),
        source_channels=("doctor", "patient"),
        error_tags=("drug_name", "medical_term"),
    ),
    FactSpec(
        kind="medication",
        canonical="paracetamol",
        field="medications",
        patterns=(r"\bparacetamol\b", r"\bacetaminophen\b"),
        source_channels=("doctor",),
        error_tags=("drug_name", "medication_dose_or_route"),
    ),
    FactSpec(
        kind="medication",
        canonical="antibiotics",
        field="medications",
        patterns=(r"\bantibiotics?\b",),
        source_channels=("doctor", "patient"),
        error_tags=("drug_name", "medical_term"),
    ),
    FactSpec(
        kind="medication",
        canonical="oral rehydration solution",
        field="medications",
        patterns=(r"\bdioralyte\b", r"\bdiaryte\b", r"\brehydration\b"),
        source_channels=("doctor",),
        error_tags=("drug_name", "medication_dose_or_route"),
    ),
    FactSpec(
        kind="test",
        canonical="stool sample or stool test",
        field="tests_or_exam_mentioned",
        patterns=(r"\bstool sample\b", r"\bstool test\b", r"\bsample of (?:your )?stool\b"),
        source_channels=("doctor",),
        error_tags=("test_or_exam", "plan_or_follow_up"),
    ),
    FactSpec(
        kind="test",
        canonical="physical examination mentioned",
        field="tests_or_exam_mentioned",
        patterns=(r"\bexamin(?:e|ation)\b", r"\blistened to\b"),
        source_channels=("doctor",),
        error_tags=("test_or_exam",),
    ),
    FactSpec(
        kind="test",
        canonical="temperature measurement mentioned",
        field="tests_or_exam_mentioned",
        patterns=(r"\bmeasure(?:d)? (?:your )?temperature\b", r"\btemperature\b"),
        source_channels=("doctor", "patient"),
        error_tags=("test_or_exam",),
    ),
    FactSpec(
        kind="assessment",
        canonical="possible gastroenteritis or tummy bug suspected",
        field="assessment_mentioned",
        polarity="uncertain",
        patterns=(r"\bgastroenteritis\b", r"\btummy bug\b", r"\bstomach bug\b"),
        source_channels=("doctor",),
        error_tags=("assessment_or_diagnosis", "medical_term"),
    ),
    FactSpec(
        kind="assessment",
        canonical="possible infection considered",
        field="assessment_mentioned",
        polarity="uncertain",
        patterns=(r"\binfection\b", r"\bvirus(?:es|al)?\b", r"\bbacteria(?:l)?\b"),
        source_channels=("doctor",),
        error_tags=("assessment_or_diagnosis", "medical_term"),
    ),
    FactSpec(
        kind="plan",
        canonical="maintain hydration and fluids",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\bfluid(?:s)?\b", r"\bhydrat(?:ed|ion)\b", r"\bdrink(?:ing)?\b"),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up",),
    ),
    FactSpec(
        kind="plan",
        canonical="conservative management",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\bconservative management\b",),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up",),
    ),
    FactSpec(
        kind="plan",
        canonical="antibiotics not currently needed",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\bno(?:t)? needing antibiotics\b", r"\bdon't think you needing antibiotics\b"),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up", "drug_name"),
    ),
    FactSpec(
        kind="plan",
        canonical="take paracetamol if feverish or weak",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\bparacetamol\b",),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up", "drug_name", "medication_dose_or_route"),
    ),
    FactSpec(
        kind="plan",
        canonical="take time off work and rest",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\btime off\b", r"\brest\b"),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up",),
    ),
    FactSpec(
        kind="plan",
        canonical="return or follow up if symptoms persist",
        field="plan_mentioned",
        polarity="planned",
        patterns=(r"\bcome back\b", r"\bsee you again\b", r"\bfollow ?up\b", r"\bif .*better\b"),
        source_channels=("doctor",),
        error_tags=("plan_or_follow_up",),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--noisy-consultation-jsonl",
        type=Path,
        default=DEFAULT_NOISY_CONSULTATION_JSONL,
        help="全量 consultation-level noisy ASR JSONL。",
    )
    parser.add_argument(
        "--textgrid-dir",
        type=Path,
        default=DEFAULT_TEXTGRID_DIR,
        help="PriMock57 doctor/patient TextGrid 目录。",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help="含 transcript 的中间 JSONL 输出目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="T045 评测输出目录。",
    )
    parser.add_argument(
        "--repair-jsonl",
        type=Path,
        default=None,
        help=(
            "可选：真实 doctor_llm_repair consultation JSONL。提供后直接替换 "
            "no-change baseline 参与 T045 评测。"
        ),
    )
    parser.add_argument(
        "--support-threshold",
        type=float,
        default=DEFAULT_FACT_SUPPORT_THRESHOLD,
        help="T042 B-lite supported 阈值。",
    )
    parser.add_argument(
        "--contradiction-threshold",
        type=float,
        default=DEFAULT_FACT_CONTRADICTION_THRESHOLD,
        help="T042 B-lite contradicted 阈值。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args)
    print("T045 全量三文本病例摘要离线评测完成。")
    print(f"- consultation records: {summary['counts']['consultation_count']}")
    print(f"- summary records: {summary['counts']['summary_record_count']}")
    print(f"- gold facts: {summary['counts']['gold_fact_count']}")
    print(f"- final table: {summary['outputs']['final_results_markdown']}")
    print(f"- final chart: {summary['outputs']['final_results_svg']}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    noisy_path = resolve_project_path(args.noisy_consultation_jsonl)
    textgrid_dir = resolve_project_path(args.textgrid_dir)
    processed_dir = resolve_project_path(args.processed_dir)
    output_dir = resolve_project_path(args.output_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_reference_jsonl = (
        processed_dir / "primock57_t045_clean_reference_consultation.jsonl"
    )
    clean_reference_summary_json = (
        output_dir / "primock57_t045_clean_reference_summary.json"
    )
    provided_repair_jsonl = (
        resolve_project_path(args.repair_jsonl) if args.repair_jsonl is not None else None
    )
    repair_jsonl = provided_repair_jsonl or (
        processed_dir / "primock57_t045_doctor_llm_repair_no_change_baseline.jsonl"
    )
    case_summary_records_jsonl = (
        output_dir / "primock57_t045_case_summary_generation_records.jsonl"
    )
    case_summary_generation_summary_json = (
        output_dir / "primock57_t045_case_summary_generation_summary.json"
    )
    gold_key_facts_jsonl = (
        processed_dir / "primock57_t045_gold_key_facts.keyword_baseline.jsonl"
    )
    gold_summary_json = output_dir / "primock57_t045_gold_key_facts_summary.json"
    quality_records_jsonl = (
        output_dir / "primock57_t045_case_summary_quality_records.jsonl"
    )
    fact_evaluations_jsonl = (
        output_dir / "primock57_t045_case_summary_fact_evaluations.jsonl"
    )
    quality_summary_json = (
        output_dir / "primock57_t045_case_summary_quality_summary.json"
    )
    final_results_csv = output_dir / "primock57_t045_case_summary_final_results.csv"
    final_results_markdown = output_dir / "primock57_t045_case_summary_final_results.md"
    final_results_svg = output_dir / "primock57_t045_case_summary_final_results.svg"
    final_run_json = output_dir / "t045_case_summary_final_evaluation_run.json"

    noisy_records = read_jsonl(noisy_path)
    clean_records = build_clean_reference_records(noisy_records, textgrid_dir)
    write_jsonl(clean_records, clean_reference_jsonl)
    write_json(
        build_clean_reference_summary(clean_records, clean_reference_jsonl),
        clean_reference_summary_json,
    )

    if provided_repair_jsonl is None:
        repair_records = build_no_change_repair_records(noisy_records)
        write_jsonl(repair_records, repair_jsonl)
    else:
        repair_records = read_jsonl(repair_jsonl)
        validate_repair_records(noisy_records, repair_records, repair_jsonl)
    repair_mode = infer_repair_mode(repair_records)
    repair_uses_clean_reference = any(
        bool(record.get("uses_clean_reference")) for record in repair_records
    )

    case_summary_records, gold_facts = build_case_summary_records_and_gold(
        noisy_records=noisy_records,
        clean_records=clean_records,
        repair_records=repair_records,
    )
    write_jsonl(case_summary_records, case_summary_records_jsonl)
    write_json(
        build_case_summary_generation_summary(
            case_summary_records=case_summary_records,
            noisy_path=noisy_path,
            clean_reference_jsonl=clean_reference_jsonl,
            repair_jsonl=repair_jsonl,
            records_jsonl=case_summary_records_jsonl,
            repair_mode=repair_mode,
        ),
        case_summary_generation_summary_json,
    )
    write_gold_key_facts_jsonl(gold_facts, gold_key_facts_jsonl)
    run_gold_key_facts_validation(
        input_jsonl=gold_key_facts_jsonl,
        output_summary_json=gold_summary_json,
        project_root=PROJECT_ROOT,
    )

    quality_summary = run_case_summary_quality_evaluation(
        summary_records_jsonl=case_summary_records_jsonl,
        gold_key_facts_jsonl=gold_key_facts_jsonl,
        output_records_jsonl=quality_records_jsonl,
        output_fact_evaluations_jsonl=fact_evaluations_jsonl,
        output_summary_json=quality_summary_json,
        project_root=PROJECT_ROOT,
        support_threshold=args.support_threshold,
        contradiction_threshold=args.contradiction_threshold,
        include_fact_text=False,
    )

    table_rows = build_final_result_rows(quality_summary)
    attach_repair_review_cost_to_rows(table_rows, repair_records)
    write_csv(table_rows, final_results_csv)
    write_markdown_table(table_rows, final_results_markdown, repair_mode=repair_mode)
    write_svg_chart(table_rows, final_results_svg, repair_mode=repair_mode)

    run_summary = {
        "schema_version": T045_RUN_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": DATASET,
        "input_variants": list(INPUT_VARIANTS),
        "method": {
            "case_summary_model": SUMMARY_MODEL_NAME,
            "gold_extractor": GOLD_EXTRACTOR_NAME,
            "run_mode": "offline_deterministic_no_external_llm",
            "doctor_llm_repair_mode": repair_mode,
            "doctor_llm_repair_uses_clean_reference": repair_uses_clean_reference,
            "same_summary_schema_for_all_variants": True,
            "same_summary_model_for_all_variants": True,
            "support_threshold": args.support_threshold,
            "contradiction_threshold": args.contradiction_threshold,
        },
        "inputs": {
            "noisy_consultation_jsonl": path_for_record(noisy_path),
            "textgrid_dir": path_for_record(textgrid_dir),
        },
        "outputs": {
            "clean_reference_jsonl": path_for_record(clean_reference_jsonl),
            "clean_reference_summary_json": path_for_record(clean_reference_summary_json),
            "doctor_llm_repair_jsonl": path_for_record(repair_jsonl),
            "case_summary_records_jsonl": path_for_record(case_summary_records_jsonl),
            "case_summary_generation_summary_json": path_for_record(
                case_summary_generation_summary_json
            ),
            "gold_key_facts_jsonl": path_for_record(gold_key_facts_jsonl),
            "gold_key_facts_summary_json": path_for_record(gold_summary_json),
            "quality_records_jsonl": path_for_record(quality_records_jsonl),
            "fact_evaluations_jsonl": path_for_record(fact_evaluations_jsonl),
            "quality_summary_json": path_for_record(quality_summary_json),
            "final_results_csv": path_for_record(final_results_csv),
            "final_results_markdown": path_for_record(final_results_markdown),
            "final_results_svg": path_for_record(final_results_svg),
            "run_summary_json": path_for_record(final_run_json),
        },
        "counts": {
            "consultation_count": len(noisy_records),
            "clean_reference_record_count": len(clean_records),
            "repair_record_count": len(repair_records),
            "summary_record_count": len(case_summary_records),
            "gold_fact_count": len(gold_facts),
            "quality_evaluated_record_count": quality_summary.get(
                "evaluated_record_count"
            ),
            "quality_skipped_record_count": quality_summary.get("skipped_record_count"),
        },
        "final_result_rows": table_rows,
        "privacy_and_safety": {
            "final_table_contains_full_transcript_text": False,
            "final_chart_contains_full_transcript_text": False,
            "aggregate_summaries_contain_full_transcript_text": False,
            "research_use_only": True,
            "clinical_use_warning": CLINICAL_USE_WARNING,
        },
        "limitations": [
            (
                "本次为离线 deterministic keyword baseline，不是外部 LLM 真实病例摘要生成。"
            ),
            (
                "doctor_llm_repair 是模拟医生/LLM selector 输出，未代表真实医生审阅。"
            ),
            (
                "gold facts 由 clean/reference 自动抽取，适合管线验收和相对比较；"
                "论文级结论仍需人工 gold facts 与真实摘要生成模型复核。"
            ),
        ],
    }
    write_json(run_summary, final_run_json)
    return run_summary


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def path_for_record(path_value: str | Path | None) -> str | None:
    if path_value is None:
        return None
    path = resolve_project_path(path_value)
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 第 {line_number} 行无法解析：{path}") from exc
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def write_json(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def unquote_textgrid_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.replace('""', '"')


def clean_textgrid_utterance(text: str) -> str:
    without_tags = TEXTGRID_TAG_PATTERN.sub(" ", text)
    return " ".join(without_tags.split())


def parse_textgrid_turns(
    path: Path,
    *,
    consultation_id: str,
    source_channel: str,
) -> list[Turn]:
    turns: list[Turn] = []
    current: dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            match = TEXTGRID_VALUE_PATTERN.match(line)
            if match is None:
                continue
            key = match.group("key")
            raw_value = match.group("value")
            if key in {"xmin", "xmax"}:
                try:
                    current[key] = float(raw_value.strip())
                except ValueError:
                    current[key] = None
                continue
            text = clean_textgrid_utterance(unquote_textgrid_value(raw_value))
            if text:
                turns.append(
                    Turn(
                        consultation_id=consultation_id,
                        turn_index=len(turns),
                        source_channel=source_channel,
                        start_sec=current.get("xmin"),
                        end_sec=current.get("xmax"),
                        text=text,
                    )
                )
            current = {}
    return turns


def discover_textgrid_paths(textgrid_dir: Path) -> dict[str, dict[str, Path]]:
    pairs: dict[str, dict[str, Path]] = defaultdict(dict)
    for path in sorted(textgrid_dir.glob("*.TextGrid")):
        match = TEXTGRID_FILENAME_PATTERN.match(path.name)
        if match is None:
            continue
        pairs[match.group("consultation_id")][match.group("channel").lower()] = path
    return {key: dict(value) for key, value in pairs.items()}


def build_clean_reference_records(
    noisy_records: list[dict[str, Any]],
    textgrid_dir: Path,
) -> list[dict[str, Any]]:
    textgrid_paths = discover_textgrid_paths(textgrid_dir)
    clean_records: list[dict[str, Any]] = []
    for noisy_record in noisy_records:
        consultation_id = str(noisy_record["consultation_id"])
        channel_paths = textgrid_paths.get(consultation_id, {})
        missing_channels = [
            channel for channel in ("doctor", "patient") if channel not in channel_paths
        ]
        if missing_channels:
            raise FileNotFoundError(
                f"{consultation_id} 缺少 TextGrid channel：{', '.join(missing_channels)}"
            )

        turns = []
        for channel in ("doctor", "patient"):
            turns.extend(
                parse_textgrid_turns(
                    channel_paths[channel],
                    consultation_id=consultation_id,
                    source_channel=channel,
                )
            )
        merged_turns = sorted(
            turns,
            key=lambda item: (
                item.start_sec if item.start_sec is not None else 1_000_000.0,
                0 if item.source_channel == "doctor" else 1,
                item.turn_index,
            ),
        )
        indexed_turns = [
            Turn(
                consultation_id=turn.consultation_id,
                turn_index=index,
                source_channel=turn.source_channel,
                start_sec=turn.start_sec,
                end_sec=turn.end_sec,
                text=turn.text,
            )
            for index, turn in enumerate(merged_turns)
        ]
        clean_transcript = format_turns_as_transcript(indexed_turns)
        clean_records.append(
            {
                "schema_version": CLEAN_REFERENCE_SCHEMA_VERSION,
                "task_id": TASK_ID,
                "dataset": DATASET,
                "split": noisy_record.get("split"),
                "sample_id": noisy_record.get("sample_id"),
                "consultation_id": consultation_id,
                "input_unit": INPUT_UNIT,
                "input_variant": "clean_reference",
                "clean_reference_transcript": clean_transcript,
                "speaker_turns": [turn_to_record(turn) for turn in indexed_turns],
                "channel_textgrid_paths": {
                    channel: path_for_record(channel_paths[channel])
                    for channel in ("doctor", "patient")
                },
                "turn_count": len(indexed_turns),
                "word_count": len(clean_transcript.split()),
                "tag_policy": {
                    "unsure_tag_policy": "remove_tag_keep_inner_text",
                    "unin_tag_policy": "remove_unintelligible_marker",
                    "other_angle_tag_policy": "remove_tag_text",
                },
                "privacy_and_safety": {
                    "record_contains_full_transcript_text": True,
                    "reference_is_noisy": False,
                    "research_use_only": True,
                },
                "clinical_use_warning": CLINICAL_USE_WARNING,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    return clean_records


def build_clean_reference_summary(
    clean_records: list[dict[str, Any]],
    clean_reference_jsonl: Path,
) -> dict[str, Any]:
    turn_counts = [int(record["turn_count"]) for record in clean_records]
    word_counts = [int(record["word_count"]) for record in clean_records]
    return {
        "schema_version": "t045_clean_reference_summary/v1",
        "task_id": TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": DATASET,
        "input_variant": "clean_reference",
        "output_files": {
            "clean_reference_jsonl": path_for_record(clean_reference_jsonl),
        },
        "record_count": len(clean_records),
        "turn_count": {
            "total": sum(turn_counts),
            "min": min(turn_counts) if turn_counts else None,
            "max": max(turn_counts) if turn_counts else None,
        },
        "word_count": {
            "total": sum(word_counts),
            "min": min(word_counts) if word_counts else None,
            "max": max(word_counts) if word_counts else None,
        },
        "tag_policy": {
            "unsure_tag_policy": "remove_tag_keep_inner_text",
            "unin_tag_policy": "remove_unintelligible_marker",
            "other_angle_tag_policy": "remove_tag_text",
        },
        "privacy_and_safety": {
            "summary_contains_full_transcript_text": False,
            "records_jsonl_contains_full_transcript_text": True,
            "research_use_only": True,
        },
    }


def build_no_change_repair_records(noisy_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repair_records: list[dict[str, Any]] = []
    for noisy_record in noisy_records:
        consultation_id = str(noisy_record["consultation_id"])
        transcript = str(noisy_record.get("noisy_transcript") or "")
        turns = noisy_turns(noisy_record)
        repair_records.append(
            {
                "schema_version": REPAIR_BASELINE_SCHEMA_VERSION,
                "task_id": TASK_ID,
                "dataset": DATASET,
                "split": noisy_record.get("split"),
                "sample_id": noisy_record.get("sample_id"),
                "consultation_id": consultation_id,
                "input_unit": INPUT_UNIT,
                "input_variant": "doctor_llm_repair",
                "doctor_llm_repair_transcript": transcript,
                "speaker_turns": [turn_to_record(turn) for turn in turns],
                "source_noisy_sample_id": noisy_record.get("sample_id"),
                "source_asr": noisy_record.get("source_asr"),
                "repair_mode": "no_change_simulated_baseline",
                "doctor_selector_status": "not_run",
                "uses_clean_reference": False,
                "feedback_log_available": False,
                "review_cost": {
                    "review_span_count": 0,
                    "changed_span_count": 0,
                    "action_summary": {},
                },
                "privacy_and_safety": {
                    "record_contains_full_transcript_text": True,
                    "research_use_only": True,
                },
                "clinical_use_warning": CLINICAL_USE_WARNING,
                "notes": (
                    "No-change baseline for T045 full-run acceptance. This is not "
                    "a real doctor selector or human-confirmed transcript."
                ),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    return repair_records


def validate_repair_records(
    noisy_records: list[dict[str, Any]],
    repair_records: list[dict[str, Any]],
    repair_jsonl: Path,
) -> None:
    """校验外部传入的 real repair JSONL 覆盖同一批 consultation。"""

    noisy_ids = {str(record["consultation_id"]) for record in noisy_records}
    repair_ids = {str(record.get("consultation_id") or "") for record in repair_records}
    missing = sorted(noisy_ids - repair_ids)
    extra = sorted(repair_ids - noisy_ids)
    if missing or extra:
        raise ValueError(
            f"repair JSONL 与 noisy consultation 不对齐：{repair_jsonl}; "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )
    for record in repair_records:
        transcript = (
            record.get("doctor_llm_repair_transcript")
            or record.get("confirmed_transcript")
            or ""
        )
        if not str(transcript).strip():
            raise ValueError(
                "repair JSONL 存在空 doctor_llm_repair_transcript/confirmed_transcript: "
                f"{record.get('consultation_id')}"
            )


def infer_repair_mode(repair_records: list[dict[str, Any]]) -> str:
    modes = Counter(str(record.get("repair_mode") or "unknown") for record in repair_records)
    if len(modes) == 1:
        return next(iter(modes))
    return "mixed:" + ",".join(f"{mode}={count}" for mode, count in sorted(modes.items()))


def build_case_summary_records_and_gold(
    *,
    noisy_records: list[dict[str, Any]],
    clean_records: list[dict[str, Any]],
    repair_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clean_by_id = {str(record["consultation_id"]): record for record in clean_records}
    repair_by_id = {str(record["consultation_id"]): record for record in repair_records}
    generation_records: list[dict[str, Any]] = []
    gold_facts: list[dict[str, Any]] = []

    for noisy_record in sorted(noisy_records, key=lambda record: str(record["consultation_id"])):
        consultation_id = str(noisy_record["consultation_id"])
        clean_record = clean_by_id[consultation_id]
        repair_record = repair_by_id[consultation_id]

        variant_sources = {
            "noisy_asr": {
                "transcript": str(noisy_record.get("noisy_transcript") or ""),
                "turns": noisy_turns(noisy_record),
                "uncertain_span_count": int(
                    noisy_record.get("quality_checks", {}).get(
                        "uncertain_span_count",
                        noisy_record.get("asr_confidence_summary", {}).get(
                            "uncertain_span_count",
                            0,
                        ),
                    )
                    or 0
                ),
                "source_record_ids": [],
                "source_sample_ids": list(
                    noisy_record.get("source_asr", {}).get("channel_sample_ids") or []
                ),
                "source_channels": sorted(
                    noisy_record.get("channels", {}).keys()
                    if isinstance(noisy_record.get("channels"), dict)
                    else ["doctor", "patient"]
                ),
                "extra": {
                    "asr_confidence": noisy_record.get("asr_confidence"),
                    "asr_confidence_level": noisy_record.get("confidence_level"),
                },
            },
            "doctor_llm_repair": {
                "transcript": str(
                    repair_record.get("doctor_llm_repair_transcript")
                    or repair_record.get("confirmed_transcript")
                    or ""
                ),
                "turns": record_turns(repair_record),
                "uncertain_span_count": int(
                    noisy_record.get("quality_checks", {}).get("uncertain_span_count", 0)
                    or 0
                ),
                "source_record_ids": [],
                "source_sample_ids": list(
                    noisy_record.get("source_asr", {}).get("channel_sample_ids") or []
                ),
                "source_channels": sorted(
                    noisy_record.get("channels", {}).keys()
                    if isinstance(noisy_record.get("channels"), dict)
                    else ["doctor", "patient"]
                ),
                "extra": {
                    "repair_mode": repair_record.get("repair_mode"),
                    "review_cost": repair_record.get("review_cost"),
                },
            },
            "clean_reference": {
                "transcript": str(clean_record.get("clean_reference_transcript") or ""),
                "turns": record_turns(clean_record),
                "uncertain_span_count": 0,
                "source_record_ids": [],
                "source_sample_ids": [
                    f"primock57:{consultation_id}:doctor",
                    f"primock57:{consultation_id}:patient",
                ],
                "source_channels": ["doctor", "patient"],
                "extra": {
                    "reference_textgrid_paths": clean_record.get("channel_textgrid_paths"),
                },
            },
        }

        clean_extraction = extract_case_summary_facts(
            variant_sources["clean_reference"]["turns"],
            consultation_id=consultation_id,
        )
        gold_facts.extend(
            build_gold_facts_for_consultation(
                consultation_id=consultation_id,
                split=noisy_record.get("split"),
                extracted_facts=clean_extraction["facts"],
            )
        )

        for variant in INPUT_VARIANTS:
            source = variant_sources[variant]
            extraction = extract_case_summary_facts(
                source["turns"],
                consultation_id=consultation_id,
            )
            generation_records.append(
                build_generation_record(
                    consultation_id=consultation_id,
                    split=noisy_record.get("split"),
                    input_variant=variant,
                    transcript=str(source["transcript"]),
                    extraction=extraction,
                    uncertain_span_count=int(source["uncertain_span_count"]),
                    source_record_ids=source["source_record_ids"],
                    source_sample_ids=source["source_sample_ids"],
                    source_channels=source["source_channels"],
                    extra_metadata=source["extra"],
                )
            )

    return generation_records, gold_facts


def noisy_turns(noisy_record: dict[str, Any]) -> list[Turn]:
    turns: list[Turn] = []
    raw_turns = noisy_record.get("speaker_turns")
    if isinstance(raw_turns, list):
        for index, item in enumerate(raw_turns):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            turns.append(
                Turn(
                    consultation_id=str(noisy_record.get("consultation_id") or ""),
                    turn_index=int(item.get("turn_index") or index),
                    source_channel=str(
                        item.get("source_channel")
                        or item.get("speaker_label")
                        or "unknown"
                    ).lower(),
                    start_sec=_optional_float(item.get("start_sec")),
                    end_sec=_optional_float(item.get("end_sec")),
                    text=text,
                )
            )
    if turns:
        return sorted(
            turns,
            key=lambda turn: (
                turn.start_sec if turn.start_sec is not None else 1_000_000.0,
                turn.turn_index,
            ),
        )

    transcript = str(noisy_record.get("noisy_transcript") or "").strip()
    if not transcript:
        return []
    output: list[Turn] = []
    for line in transcript.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            speaker, text = stripped.split(":", 1)
            source_channel = speaker.strip().lower()
            text = text.strip()
        else:
            source_channel = "mixed"
            text = stripped
        if text:
            output.append(
                Turn(
                    consultation_id=str(noisy_record.get("consultation_id") or ""),
                    turn_index=len(output),
                    source_channel=source_channel,
                    start_sec=None,
                    end_sec=None,
                    text=text,
                )
            )
    return output


def record_turns(record: dict[str, Any]) -> list[Turn]:
    turns: list[Turn] = []
    for index, item in enumerate(record.get("speaker_turns") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        turns.append(
            Turn(
                consultation_id=str(record.get("consultation_id") or ""),
                turn_index=int(item.get("turn_index") or index),
                source_channel=str(
                    item.get("source_channel")
                    or item.get("speaker_label")
                    or "unknown"
                ).lower(),
                start_sec=_optional_float(item.get("start_sec")),
                end_sec=_optional_float(item.get("end_sec")),
                text=text,
            )
        )
    return turns


def turn_to_record(turn: Turn) -> dict[str, Any]:
    return {
        "turn_index": turn.turn_index,
        "source_channel": turn.source_channel,
        "speaker_label": turn.source_channel,
        "start_sec": turn.start_sec,
        "end_sec": turn.end_sec,
        "text": turn.text,
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_turns_as_transcript(turns: list[Turn]) -> str:
    blocks = []
    for turn in turns:
        speaker = turn.source_channel.upper()
        blocks.append(f"{speaker}: {turn.text}")
    return "\n".join(blocks)


def extract_case_summary_facts(
    turns: list[Turn],
    *,
    consultation_id: str,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for turn in turns:
        normalized_text = normalize_text(turn.text)
        for spec in SYMPTOM_SPECS:
            match = first_pattern_match(spec.patterns, normalized_text)
            if match is None:
                continue
            if should_skip_symptom_match(turn, normalized_text, match):
                continue
            negated = has_negation_near(normalized_text, match.start())
            field = "negated_or_absent_symptoms" if negated else "symptoms"
            polarity = "absent" if negated else "present"
            label_prefix = "negated symptom" if negated else "symptom"
            label = f"{label_prefix}: {spec.canonical}"
            error_tags = set(spec.error_tags)
            if negated:
                error_tags.add("negation_or_polarity")
            add_fact(
                facts,
                seen_keys,
                consultation_id=consultation_id,
                field=field,
                label=label,
                normalized_terms=[spec.canonical],
                polarity=polarity,
                severity=spec.severity,
                source_channel=turn.source_channel,
                turn=turn,
                error_tags=sorted(error_tags),
            )

        for spec in OTHER_FACT_SPECS:
            if turn.source_channel not in spec.source_channels:
                continue
            match = first_pattern_match(spec.patterns, normalized_text)
            if match is None:
                continue
            if (
                turn.source_channel == "doctor"
                and spec.kind in {"history", "medication", "test"}
                and not spec.allow_doctor_question
                and is_doctor_question_context(normalized_text, match.start())
                and not has_assertion_cue(normalized_text)
            ):
                continue
            add_fact(
                facts,
                seen_keys,
                consultation_id=consultation_id,
                field=spec.field or "history_of_present_illness",
                label=(
                    f"{field_label_prefix(spec.field or 'history_of_present_illness')}: "
                    f"{spec.canonical}"
                ),
                normalized_terms=[spec.canonical],
                polarity=spec.polarity,
                severity=spec.severity,
                source_channel=turn.source_channel,
                turn=turn,
                error_tags=list(spec.error_tags),
            )

    facts = drop_negated_symptom_duplicates(facts)
    facts = sorted(
        facts,
        key=lambda item: (
            field_sort_order(str(item["field"])),
            str(item["label"]),
            int(item.get("turn_index") or 0),
        ),
    )
    return {
        "consultation_id": consultation_id,
        "facts": facts,
        "case_summary": facts_to_case_summary(facts),
    }


def drop_negated_symptom_duplicates(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一 canonical symptom 同时出现阳性和阴性时，保留阳性事实。

    PriMock57 对话中常见“现在无 X，但开始时有 X”或医生问句/复述导致同一术语
    同时被抽到 present/absent。T045 离线验收更关注病例摘要事实保留，不把这种
    自动抽取歧义扩成自相矛盾的 gold/summary 双标签。
    """

    present_symptom_terms = {
        symptom_term_from_label(str(fact.get("label") or ""))
        for fact in facts
        if fact.get("field") == "symptoms"
    }
    present_symptom_terms.discard("")
    if not present_symptom_terms:
        return facts
    output = []
    for fact in facts:
        if fact.get("field") == "negated_or_absent_symptoms":
            term = symptom_term_from_label(str(fact.get("label") or ""))
            if term in present_symptom_terms:
                continue
        output.append(fact)
    return output


def symptom_term_from_label(label: str) -> str:
    if ":" not in label:
        return label.strip().casefold()
    return label.split(":", 1)[1].strip().casefold()


def add_fact(
    facts: list[dict[str, Any]],
    seen_keys: set[tuple[str, str, str]],
    *,
    consultation_id: str,
    field: str,
    label: str,
    normalized_terms: list[str],
    polarity: str,
    severity: str,
    source_channel: str,
    turn: Turn,
    error_tags: list[str],
) -> None:
    key = (field, label, polarity)
    if key in seen_keys:
        return
    seen_keys.add(key)
    facts.append(
        {
            "consultation_id": consultation_id,
            "field": field,
            "label": label,
            "normalized_terms": normalized_terms,
            "polarity": polarity,
            "severity": severity,
            "source_channel": source_channel
            if source_channel in {"doctor", "patient", "mixed", "unknown"}
            else "unknown",
            "turn_index": turn.turn_index,
            "start_sec": turn.start_sec,
            "end_sec": turn.end_sec,
            "cue": f"keyword_match:{field}",
            "error_tags": error_tags,
        }
    )


def normalize_text(text: str) -> str:
    lowered = text.casefold()
    lowered = lowered.replace("’", "'").replace("`", "'")
    return " ".join(lowered.split())


def first_pattern_match(patterns: tuple[str, ...], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is not None:
            return match
    return None


def has_negation_near(text: str, match_start: int, *, window_chars: int = 55) -> bool:
    left_context = text[max(0, match_start - window_chars) : match_start]
    tokens = TOKEN_PATTERN.findall(left_context)
    return any(token in NEGATION_MARKERS for token in tokens[-8:])


def is_doctor_question_context(text: str, match_start: int) -> bool:
    left_context = text[max(0, match_start - 90) : match_start]
    return any(cue in left_context for cue in QUESTION_CUES)


def has_assertion_cue(text: str) -> bool:
    return any(cue in text for cue in DOCTOR_ASSERTION_CUES)


def should_skip_symptom_match(
    turn: Turn,
    text: str,
    match: re.Match[str],
) -> bool:
    if turn.source_channel != "doctor":
        return False
    if has_negation_near(text, match.start()):
        return False
    if has_assertion_cue(text):
        return False
    return is_doctor_question_context(text, match.start())


def field_label_prefix(field: str) -> str:
    return {
        "chief_complaint": "chief complaint",
        "history_of_present_illness": "history",
        "symptoms": "symptom",
        "negated_or_absent_symptoms": "negated symptom",
        "relevant_history": "relevant history",
        "medications": "medication or treatment",
        "tests_or_exam_mentioned": "test or exam",
        "assessment_mentioned": "assessment",
        "plan_mentioned": "plan",
    }.get(field, field)


def field_sort_order(field: str) -> int:
    order = {
        "chief_complaint": 0,
        "history_of_present_illness": 1,
        "symptoms": 2,
        "negated_or_absent_symptoms": 3,
        "relevant_history": 4,
        "medications": 5,
        "tests_or_exam_mentioned": 6,
        "assessment_mentioned": 7,
        "plan_mentioned": 8,
    }
    return order.get(field, 99)


def facts_to_case_summary(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, list[str]] = defaultdict(list)
    for fact in facts:
        field = str(fact["field"])
        label = str(fact["label"])
        if label not in by_field[field]:
            by_field[field].append(label)

    symptoms = by_field.get("symptoms", [])
    chief_complaint = ", ".join(symptoms[:2]) if symptoms else None
    history_items = by_field.get("history_of_present_illness", [])
    history_of_present_illness = "; ".join(history_items[:3]) if history_items else None
    assessment_items = by_field.get("assessment_mentioned", [])
    assessment_mentioned = "; ".join(assessment_items[:2]) if assessment_items else None
    return {
        "summary_text": "；".join(
            item
            for item in [
                chief_complaint,
                history_of_present_illness,
                assessment_mentioned,
            ]
            if item
        )
        or None,
        "chief_complaint": chief_complaint,
        "history_of_present_illness": history_of_present_illness,
        "symptoms": symptoms,
        "negated_or_absent_symptoms": by_field.get("negated_or_absent_symptoms", []),
        "relevant_history": by_field.get("relevant_history", []),
        "medications": by_field.get("medications", []),
        "tests_or_exam_mentioned": by_field.get("tests_or_exam_mentioned", []),
        "assessment_mentioned": assessment_mentioned,
        "plan_mentioned": by_field.get("plan_mentioned", []),
        "uncertainty_notes": [],
    }


def build_gold_facts_for_consultation(
    *,
    consultation_id: str,
    split: str | None,
    extracted_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gold_facts: list[dict[str, Any]] = []
    for index, fact in enumerate(extracted_facts, start=1):
        field = str(fact["field"])
        gold_facts.append(
            {
                "schema_version": "gold_key_fact/v1",
                "fact_id": f"{consultation_id}__{field}__{index:03d}",
                "bundle_id": f"{DATASET}:{consultation_id}:gold_key_facts:{INPUT_UNIT}",
                "dataset": DATASET,
                "split": split,
                "consultation_id": consultation_id,
                "field": field,
                "canonical_fact": str(fact["label"]),
                "polarity": fact.get("polarity") or "present",
                "severity": fact.get("severity") or "major",
                "source_channel": fact.get("source_channel") or "unknown",
                "evidence_pointer": {
                    "source_type": "reference_transcript",
                    "sample_id": (
                        f"primock57:{consultation_id}:"
                        f"{fact.get('source_channel') or 'unknown'}"
                    ),
                    "record_id": None,
                    "source_channel": fact.get("source_channel") or "unknown",
                    "turn_index": fact.get("turn_index"),
                    "word_start_index": None,
                    "word_end_index": None,
                    "start_sec": fact.get("start_sec"),
                    "end_sec": fact.get("end_sec"),
                    "cue": fact.get("cue") or f"keyword_match:{field}",
                    "contains_full_transcript_text": False,
                },
                "error_tags": fact.get("error_tags") or [],
                "normalized_terms": fact.get("normalized_terms") or [],
                "annotator_role": "deterministic_keyword_extractor",
                "reviewed": False,
                "notes": (
                    "Automatically extracted from clean/reference for T045 "
                    "offline acceptance."
                ),
                "research_use_only": True,
                "clinical_use_warning": CLINICAL_USE_WARNING,
            }
        )
    return gold_facts


def build_generation_record(
    *,
    consultation_id: str,
    split: str | None,
    input_variant: str,
    transcript: str,
    extraction: dict[str, Any],
    uncertain_span_count: int,
    source_record_ids: list[str | None],
    source_sample_ids: list[str],
    source_channels: list[str],
    extra_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CASE_SUMMARY_RECORD_SCHEMA_VERSION,
        "task_id": "T041",
        "t045_task_id": TASK_ID,
        "bundle_id": f"{DATASET}:{consultation_id}:{input_variant}:{INPUT_UNIT}",
        "dataset": DATASET,
        "split": split,
        "consultation_id": consultation_id,
        "input_unit": INPUT_UNIT,
        "input_variant": input_variant,
        "source_record_count": len(source_sample_ids) or None,
        "source_record_ids": source_record_ids,
        "source_sample_ids": source_sample_ids,
        "source_channels": source_channels,
        "input_transcript_word_count": len(transcript.split()),
        "input_transcript_char_count": len(transcript),
        "input_transcript_sha256": sha256_text(transcript),
        "uncertain_span_count": uncertain_span_count,
        "prompt_messages": None,
        "prompt_version": CASE_SUMMARY_PROMPT_VERSION,
        "summary_language": "en",
        "status": "generated",
        "case_summary": extraction["case_summary"],
        "raw_model_output": None,
        "model": {
            "model_name": SUMMARY_MODEL_NAME,
            "run_mode": "offline_deterministic_no_external_llm",
            "temperature": 0,
        },
        "t045_extracted_fact_count": len(extraction["facts"]),
        "t045_extra_metadata": extra_metadata,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "privacy_and_safety": {
            "record_contains_full_transcript_text": False,
            "record_contains_prompt_text": False,
            "case_summary_contains_short_fact_labels": True,
            "research_use_only": True,
        },
        "research_use_only": True,
        "clinical_use_warning": CLINICAL_USE_WARNING,
        "notes": (
            "T045 offline deterministic case-summary baseline. It uses the same "
            "keyword schema/model across noisy_asr, doctor_llm_repair and "
            "clean_reference, and does not call external LLM APIs."
        ),
    }


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_case_summary_generation_summary(
    *,
    case_summary_records: list[dict[str, Any]],
    noisy_path: Path,
    clean_reference_jsonl: Path,
    repair_jsonl: Path,
    records_jsonl: Path,
    repair_mode: str,
) -> dict[str, Any]:
    input_variant_counts = Counter(record["input_variant"] for record in case_summary_records)
    fact_counts = [
        int(record.get("t045_extracted_fact_count") or 0)
        for record in case_summary_records
    ]
    word_counts = [
        int(record.get("input_transcript_word_count") or 0)
        for record in case_summary_records
    ]
    return {
        "schema_version": CASE_SUMMARY_GENERATION_SUMMARY_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": DATASET,
        "input_files": {
            "noisy_consultation_jsonl": path_for_record(noisy_path),
            "clean_reference_jsonl": path_for_record(clean_reference_jsonl),
            "doctor_llm_repair_jsonl": path_for_record(repair_jsonl),
        },
        "output_files": {
            "case_summary_records_jsonl": path_for_record(records_jsonl),
        },
        "record_count": len(case_summary_records),
        "input_variant_counts": dict(input_variant_counts),
        "status_counts": dict(Counter(record["status"] for record in case_summary_records)),
        "summary_model": SUMMARY_MODEL_NAME,
        "prompt_version": CASE_SUMMARY_PROMPT_VERSION,
        "run_mode": "offline_deterministic_no_external_llm",
        "doctor_llm_repair_mode": repair_mode,
        "input_transcript_word_count": {
            "total": sum(word_counts),
            "min": min(word_counts) if word_counts else None,
            "max": max(word_counts) if word_counts else None,
        },
        "extracted_summary_fact_count": {
            "total": sum(fact_counts),
            "min": min(fact_counts) if fact_counts else None,
            "max": max(fact_counts) if fact_counts else None,
        },
        "privacy_and_safety": {
            "summary_contains_full_transcript_text": False,
            "records_jsonl_contains_full_transcript_text": False,
            "records_jsonl_contains_short_case_summary_fact_labels": True,
            "research_use_only": True,
        },
        "limitations": [
            "This is a deterministic keyword baseline, not a clinical LLM output.",
            (
                "doctor_llm_repair is a simulated selector output; it is not a real "
                "clinician-confirmed transcript."
            ),
        ],
    }


def build_final_result_rows(quality_summary: dict[str, Any]) -> list[dict[str, Any]]:
    by_variant = quality_summary.get("by_input_variant") or {}
    rows: list[dict[str, Any]] = []
    noisy_metrics = by_variant.get("noisy_asr") or {}
    noisy_f1 = _metric(noisy_metrics, "fact_f1_macro")
    noisy_recall = _metric(noisy_metrics, "fact_recall_macro")
    noisy_omission = _metric(noisy_metrics, "omission_count")

    for variant in INPUT_VARIANTS:
        metrics = by_variant.get(variant) or {}
        factuality = metrics.get("factuality_counts") or {}
        uncertainty = metrics.get("uncertainty_note_summary") or {}
        review_cost = metrics.get("review_cost_attribution_summary") or {}
        high_risk = metrics.get("high_risk_error_type_counts") or {}
        current_f1 = _metric(metrics, "fact_f1_macro")
        current_recall = _metric(metrics, "fact_recall_macro")
        current_omission = _metric(metrics, "omission_count")
        action_summary = review_cost.get("action_summary") or {}
        rows.append(
            {
                "input_variant": variant,
                "record_count": int(metrics.get("record_count") or 0),
                "evaluated_record_count": int(metrics.get("evaluated_record_count") or 0),
                "summary_fact_count": int(metrics.get("summary_fact_count") or 0),
                "gold_fact_count": int(metrics.get("gold_fact_count") or 0),
                "fact_precision_macro": current_f1_or_none(
                    metrics.get("fact_precision_macro")
                ),
                "fact_recall_macro": current_f1_or_none(metrics.get("fact_recall_macro")),
                "fact_f1_macro": current_f1_or_none(metrics.get("fact_f1_macro")),
                "critical_fact_recall_macro": current_f1_or_none(
                    metrics.get("critical_fact_recall_macro")
                ),
                "rouge_l_f1_macro": current_f1_or_none(metrics.get("rouge_l_f1_macro")),
                "omission_count": int(metrics.get("omission_count") or 0),
                "supported": int(factuality.get("supported") or 0),
                "unsupported": int(factuality.get("unsupported") or 0),
                "contradicted": int(factuality.get("contradicted") or 0),
                "unverifiable": int(factuality.get("unverifiable") or 0),
                "uncertainty_required_records": int(
                    uncertainty.get("required_record_count") or 0
                ),
                "uncertainty_missing_records": int(
                    uncertainty.get("missing_record_count") or 0
                ),
                "uncertainty_loose_coverage_rate": current_f1_or_none(
                    uncertainty.get("loose_coverage_rate")
                ),
                "high_risk_error_total": sum(int(value) for value in high_risk.values()),
                "review_action_total": sum(int(value) for value in action_summary.values()),
                "review_changed_span_count": int(
                    review_cost.get("changed_span_count") or 0
                ),
                "delta_fact_f1_vs_noisy": delta_or_none(current_f1, noisy_f1),
                "delta_fact_recall_vs_noisy": delta_or_none(current_recall, noisy_recall),
                "delta_omission_vs_noisy": delta_or_none(current_omission, noisy_omission),
            }
        )
    return rows


def attach_repair_review_cost_to_rows(
    rows: list[dict[str, Any]],
    repair_records: list[dict[str, Any]],
) -> None:
    review_action_total = 0
    changed_span_count = 0
    for record in repair_records:
        review_cost = record.get("review_cost")
        if not isinstance(review_cost, dict):
            continue
        action_summary = review_cost.get("action_summary") or {}
        if isinstance(action_summary, dict):
            review_action_total += sum(int(value) for value in action_summary.values())
        changed_span_count += int(review_cost.get("changed_span_count") or 0)
    for row in rows:
        if row.get("input_variant") == "doctor_llm_repair":
            row["review_action_total"] = review_action_total
            row["review_changed_span_count"] = changed_span_count


def _metric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def current_f1_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def delta_or_none(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 6)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(RESULT_TABLE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in RESULT_TABLE_COLUMNS})


def write_markdown_table(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    repair_mode: str,
) -> None:
    headers = [
        "输入变体",
        "样本数",
        "Precision",
        "Recall",
        "F1",
        "Critical recall",
        "ROUGE-L F1",
        "Omission",
        "Unsupported",
        "Contradicted",
        "Uncertainty 缺失",
        "F1 Δ vs noisy",
    ]
    key_map = [
        "input_variant",
        "evaluated_record_count",
        "fact_precision_macro",
        "fact_recall_macro",
        "fact_f1_macro",
        "critical_fact_recall_macro",
        "rouge_l_f1_macro",
        "omission_count",
        "unsupported",
        "contradicted",
        "uncertainty_missing_records",
        "delta_fact_f1_vs_noisy",
    ]
    lines = [
        "# T045 三文本病例摘要最终评测结果表",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        (
            "说明：本表来自离线 deterministic keyword case-summary baseline；"
            f"`doctor_llm_repair` 模式为 `{repair_mode}`，不代表真实医生审阅。"
        ),
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        values = [format_table_value(row.get(key)) for key in key_map]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "隐私/安全：表格不包含完整 transcript、prompt 或病例原文；仅包含聚合指标。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def format_table_value(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_svg_chart(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    repair_mode: str,
) -> None:
    metrics = [
        ("fact_precision_macro", "Precision", "#4C78A8"),
        ("fact_recall_macro", "Recall", "#F58518"),
        ("fact_f1_macro", "F1", "#54A24B"),
    ]
    width = 980
    height = 460
    margin_left = 80
    margin_top = 70
    chart_width = 820
    chart_height = 280
    group_width = chart_width / max(len(rows), 1)
    bar_width = group_width / 5
    y_base = margin_top + chart_height
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            '<text x="490" y="34" text-anchor="middle" font-size="22" '
            'font-family="Arial, sans-serif" font-weight="700">'
            "T045 case-summary evaluation by input variant</text>"
        ),
        (
            '<text x="490" y="56" text-anchor="middle" font-size="13" '
            'font-family="Arial, sans-serif" fill="#555">'
            "Offline deterministic summary baseline; doctor_llm_repair = "
            f"{html.escape(repair_mode)}</text>"
        ),
        (
            f'<line x1="{margin_left}" y1="{y_base}" '
            f'x2="{margin_left + chart_width}" y2="{y_base}" stroke="#333"/>'
        ),
        (
            f'<line x1="{margin_left}" y1="{margin_top}" '
            f'x2="{margin_left}" y2="{y_base}" stroke="#333"/>'
        ),
    ]
    for tick in range(0, 6):
        value = tick / 5
        y = y_base - value * chart_height
        parts.append(

                f'<line x1="{margin_left - 5}" y1="{y:.1f}" '
                f'x2="{margin_left + chart_width}" y2="{y:.1f}" stroke="#ddd"/>'

        )
        parts.append(

                f'<text x="{margin_left - 10}" y="{y + 4:.1f}" '
                'text-anchor="end" font-size="12" '
                f'font-family="Arial, sans-serif">{value:.1f}</text>'

        )

    for row_index, row in enumerate(rows):
        group_x = margin_left + row_index * group_width + group_width * 0.23
        for metric_index, (key, _label, color) in enumerate(metrics):
            raw_value = row.get(key)
            value = 0.0 if raw_value is None else max(0.0, min(1.0, float(raw_value)))
            bar_height = value * chart_height
            x = group_x + metric_index * (bar_width + 5)
            y = y_base - bar_height
            parts.append(

                    f'<rect x="{x:.1f}" y="{y:.1f}" '
                    f'width="{bar_width:.1f}" height="{bar_height:.1f}" '
                    f'fill="{color}"/>'

            )
            parts.append(

                    f'<text x="{x + bar_width / 2:.1f}" y="{y - 4:.1f}" '
                    'text-anchor="middle" font-size="10" '
                    f'font-family="Arial, sans-serif">{value:.2f}</text>'

            )
        label = html.escape(str(row.get("input_variant") or ""))
        parts.append(

                f'<text x="{margin_left + row_index * group_width + group_width / 2:.1f}" '
                f'y="{y_base + 26}" text-anchor="middle" font-size="12" '
                f'font-family="Arial, sans-serif">{label}</text>'

        )

    legend_x = margin_left + 40
    legend_y = height - 48
    for index, (_key, label, color) in enumerate(metrics):
        x = legend_x + index * 170
        parts.append(f'<rect x="{x}" y="{legend_y}" width="14" height="14" fill="{color}"/>')
        parts.append(

                f'<text x="{x + 22}" y="{legend_y + 12}" font-size="13" '
                f'font-family="Arial, sans-serif">{html.escape(label)}</text>'

        )
    parts.append(

            '<text x="80" y="434" font-size="11" '
            'font-family="Arial, sans-serif" fill="#666">'
            "Figure contains aggregate metrics only; no transcript or case text.</text>"

    )
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
