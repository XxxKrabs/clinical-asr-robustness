"""评估中文 5 例 pilot，并生成可展示 CSV/Markdown/SVG 图表。

质量指标使用明确标源的 LLM 多路转录代理参考，只能作为探索性鲁棒性结果；工程运行、
时长、RTF、显存和 speaker 映射覆盖不依赖该代理参考。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl
from clinical_asr_robustness.chinese_pilot_evaluation import (
    case_summary_pair_metrics,
    confidence_risk_metrics,
    critical_information_metrics,
    flatten_asr_words,
    proxy_fact_textual_recall,
    safe_mean,
    transcript_error_rates,
)
from clinical_asr_robustness.svg_charts import write_grouped_bar_svg, write_line_svg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_IDS = ("case_0068", "case_0057", "case_0040", "case_0008", "case_0021")
DEFAULT_OUTPUT_DIR = Path("outputs/remote_programming_40/t058_pilot5/report")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asr-jsonl",
        type=Path,
        default=Path("outputs/remote_programming_40/t058_pilot5/asr_confidence.jsonl"),
    )
    parser.add_argument(
        "--proxy-reference-jsonl",
        type=Path,
        default=Path(
            "data/processed/remote_programming_40/t058_proxy_reference/proxy_references.jsonl"
        ),
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path(
            "data/interim/remote_programming_40/manifests/remote_programming_40_asr_manifest.jsonl"
        ),
    )
    parser.add_argument(
        "--lexicon-json",
        type=Path,
        default=Path("configs/medical_candidate_lexicon.remote_programming_40.json"),
    )
    parser.add_argument("--asr-run-json", type=Path, default=None)
    parser.add_argument("--nbest-run-json", type=Path, default=None)
    parser.add_argument("--diarization-jsonl", type=Path, default=None)
    parser.add_argument("--diarized-asr-jsonl", type=Path, default=None)
    parser.add_argument("--case-summary-records-jsonl", type=Path, default=None)
    parser.add_argument("--case-id", action="append", dest="case_ids", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def resolve_project_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def read_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_terms_by_category(path: Path) -> dict[str, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    terms = payload.get("terms") or {}
    return {
        str(category): [str(term) for term in values]
        for category, values in terms.items()
        if isinstance(values, list)
    }


def load_case_metadata(manifest_path: Path, case_ids: list[str]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(manifest_path):
        case_id = str(row.get("consultation_id") or "")
        if case_id in case_ids:
            metadata[case_id] = {
                "duration_sec": float(row.get("duration_sec") or row.get("duration") or 0.0),
                "sample_id": row.get("sample_id"),
            }
    raw_root = PROJECT_ROOT / "data/raw/remote_programming_40"
    csv_paths = sorted(raw_root.rglob("*.csv"))
    if csv_paths:
        with csv_paths[0].open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                digits = "".join(char for char in str(row.get("病例编号") or "") if char.isdigit())
                if not digits:
                    continue
                case_id = f"case_{int(digits):04d}"
                if case_id in metadata:
                    metadata[case_id]["expected_speaker_k"] = int(row["推荐说话人数K"])
                    metadata[case_id]["package_high_confidence_char_ratio"] = (
                        int(row["高置信文本字符数"]) / int(row["证据文本字符数_代理值"])
                        if int(row["证据文本字符数_代理值"])
                        else None
                    )
                    metadata[case_id]["package_review_medical_span_count"] = int(
                        row["待核医疗片段数"]
                    )
    missing = sorted(set(case_ids) - set(metadata))
    if missing:
        raise ValueError(f"dataset manifest 缺少 pilot case：{missing}")
    return metadata


def diarization_by_case(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        case_id = str(row.get("consultation_id") or "")
        segments = row.get("segments") or []
        durations: Counter[str] = Counter()
        for segment in segments:
            durations[str(segment.get("speaker_label") or "unknown")] += max(
                0.0,
                float(segment.get("end_sec") or 0.0) - float(segment.get("start_sec") or 0.0),
            )
        runtime = row.get("runtime") or {}
        result[case_id] = {
            "detected_speaker_count": len(row.get("speaker_labels") or []),
            "segment_count": len(segments),
            "diarization_rtf": runtime.get("real_time_factor"),
            "diarization_peak_reserved_mib": (
                float(runtime["cuda_peak_memory_reserved_bytes"]) / (1024**2)
                if runtime.get("cuda_peak_memory_reserved_bytes") is not None
                else None
            ),
            "very_short_speaker_count": sum(value < 1.0 for value in durations.values()),
        }
    return result


def speaker_mapping_by_case(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    records = read_asr_confidence_jsonl(path)
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        case_id = str(record.consultation_id or record.sample_id)
        for word in record.asr_words:
            totals[case_id]["total"] += 1
            evidence = word.metadata.get("diarization")
            if isinstance(evidence, dict) and evidence.get("speaker_label"):
                totals[case_id]["acoustic"] += 1
            if word.speaker_label:
                totals[case_id]["resolved"] += 1
            if isinstance(evidence, dict) and evidence.get("mapping_status") == "ambiguous_overlap":
                totals[case_id]["ambiguous"] += 1
    return {
        case_id: {
            "speaker_mapping_total_word_count": counts["total"],
            "acoustic_mapping_coverage": (
                counts["acoustic"] / counts["total"] if counts["total"] else None
            ),
            "resolved_mapping_coverage": (
                counts["resolved"] / counts["total"] if counts["total"] else None
            ),
            "ambiguous_overlap_word_count": counts["ambiguous"],
        }
        for case_id, counts in totals.items()
    }


def summary_pairs(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in read_jsonl(path):
        if row.get("status") != "generated" or not isinstance(row.get("case_summary"), dict):
            continue
        case_id = str(row.get("consultation_id") or "")
        grouped[case_id][str(row.get("input_variant") or "")] = row["case_summary"]
    result: dict[str, dict[str, Any]] = {}
    for case_id, variants in grouped.items():
        noisy = variants.get("noisy_asr")
        reference = variants.get("reference_oracle")
        if noisy is not None and reference is not None:
            result[case_id] = case_summary_pair_metrics(reference, noisy)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_ids = list(dict.fromkeys(args.case_ids or DEFAULT_CASE_IDS))
    asr_path = resolve_project_path(args.asr_jsonl)
    proxy_path = resolve_project_path(args.proxy_reference_jsonl)
    manifest_path = resolve_project_path(args.dataset_manifest)
    lexicon_path = resolve_project_path(args.lexicon_json)
    output_dir = resolve_project_path(args.output_dir)
    assert asr_path and proxy_path and manifest_path and lexicon_path and output_dir

    asr_records = read_asr_confidence_jsonl(asr_path)
    grouped_asr: dict[str, list[Any]] = defaultdict(list)
    for record in asr_records:
        case_id = str(record.consultation_id or record.sample_id)
        if case_id in case_ids:
            grouped_asr[case_id].append(record)
    proxies = {
        str(row.get("consultation_id")): row
        for row in read_jsonl(proxy_path)
        if str(row.get("consultation_id")) in case_ids
    }
    missing_asr = sorted(set(case_ids) - set(grouped_asr))
    missing_proxy = sorted(set(case_ids) - set(proxies))
    if missing_asr or missing_proxy:
        raise ValueError(f"缺少 ASR={missing_asr} 或 proxy={missing_proxy}")

    metadata = load_case_metadata(manifest_path, case_ids)
    terms_by_category = load_terms_by_category(lexicon_path)
    diarization = diarization_by_case(resolve_project_path(args.diarization_jsonl))
    mapping = speaker_mapping_by_case(resolve_project_path(args.diarized_asr_jsonl))
    downstream = summary_pairs(resolve_project_path(args.case_summary_records_jsonl))

    case_records: list[dict[str, Any]] = []
    for case_id in case_ids:
        records = grouped_asr[case_id]
        raw_text, _, _ = flatten_asr_words(records)
        proxy = proxies[case_id]
        reference_text = str(proxy["clean_transcript"])
        error_rates = transcript_error_rates(reference_text, raw_text)
        critical = critical_information_metrics(
            reference_text,
            raw_text,
            terms_by_category=terms_by_category,
        )
        fact_recall = proxy_fact_textual_recall(proxy.get("key_facts") or [], raw_text)
        risk = confidence_risk_metrics(records, reference_text=reference_text)
        counts: Counter[str] = Counter(
            word.confidence_level.value for record in records for word in record.asr_words
        )
        total_words = sum(counts.values())
        record = {
            "case_id": case_id,
            **metadata[case_id],
            "asr_window_count": len(records),
            "asr_word_count": total_words,
            "risk_level_word_counts": dict(sorted(counts.items())),
            "risk_level_word_fractions": {
                level: count / total_words if total_words else 0.0
                for level, count in sorted(counts.items())
            },
            "proxy_reference": {
                "reference_type": proxy.get("reference_type"),
                "audio_used": proxy.get("audio_used"),
                "human_transcriber_used": proxy.get("human_transcriber_used"),
                "is_gold": proxy.get("is_gold"),
                "key_fact_count": len(proxy.get("key_facts") or []),
                "uncertainty_note_count": len(proxy.get("uncertainty_notes") or []),
            },
            "transcript_quality": error_rates,
            "critical_information": critical,
            "proxy_fact_recoverability": fact_recall,
            "confidence_risk": risk,
            "diarization": diarization.get(case_id),
            "speaker_mapping": mapping.get(case_id),
            "downstream_case_summary_robustness": downstream.get(case_id),
        }
        case_records.append(record)

    aggregate = build_aggregate(case_records)
    asr_run = read_json_if_exists(resolve_project_path(args.asr_run_json))
    nbest_run = read_json_if_exists(resolve_project_path(args.nbest_run_json))
    summary = {
        "task_id": "T058_T064_T066_PROXY_PILOT",
        "schema_version": "chinese_pilot_robustness_report/v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(case_records),
        "case_ids": case_ids,
        "evaluation_scope": "exploratory_proxy_reference",
        "formal_quality_claim_allowed": False,
        "proxy_reference_type": "llm_multi_asr_consensus_proxy",
        "case_records": case_records,
        "aggregate": aggregate,
        "engineering_runs": summarize_runs(asr_run, nbest_run),
        "limitations": [
            "代理参考未使用原音频，可能继承多路 ASR 的共同错误。",
            "CER、校准和病例信息保持率不是人工 reference 上的正式质量结果。",
            "confidence risk capture 不把 deletion 归因给任何颜色。",
            "病例摘要稳定性比较同一模型的 noisy/proxy 输入，不等同人工 gold factuality。",
        ],
        "research_use_only": True,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "pilot5_robustness_summary.json"
    csv_path = output_dir / "pilot5_case_metrics.csv"
    markdown_path = output_dir / "pilot5_results.md"
    write_json(summary_path, summary)
    write_case_csv(csv_path, case_records)
    write_markdown(markdown_path, summary)
    figure_paths = build_figures(output_dir, case_records)
    html_path = output_dir / "pilot5_report.html"
    write_html_report(html_path, summary, figure_paths)
    summary["outputs"] = {
        "summary_json": project_relative(summary_path),
        "case_metrics_csv": project_relative(csv_path),
        "results_markdown": project_relative(markdown_path),
        "report_html": project_relative(html_path),
        "figures": [project_relative(path) for path in figure_paths],
    }
    write_json(summary_path, summary)
    return summary


def build_aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_words = sum(record["asr_word_count"] for record in records)
    level_counts: Counter[str] = Counter()
    error_chars_by_level: Counter[str] = Counter()
    chars_by_level: Counter[str] = Counter()
    for record in records:
        level_counts.update(record["risk_level_word_counts"])
        for level, values in record["confidence_risk"]["risk_by_level"].items():
            chars_by_level[level] += int(values["char_count"])
            error_chars_by_level[level] += int(values["detectable_error_char_count"])
    downstream_records = [
        record["downstream_case_summary_robustness"]
        for record in records
        if record["downstream_case_summary_robustness"] is not None
    ]
    return {
        "total_duration_min": sum(record["duration_sec"] for record in records) / 60,
        "total_asr_window_count": sum(record["asr_window_count"] for record in records),
        "total_asr_word_count": total_words,
        "risk_level_word_counts": dict(sorted(level_counts.items())),
        "risk_level_word_fractions": {
            level: count / total_words if total_words else 0.0
            for level, count in sorted(level_counts.items())
        },
        "macro_proxy_cer": safe_mean(record["transcript_quality"]["cer"] for record in records),
        "macro_mixed_token_error_rate": safe_mean(
            record["transcript_quality"]["mixed_token_error_rate"] for record in records
        ),
        "macro_critical_information_preservation_score": safe_mean(
            record["critical_information"]["critical_information_preservation_score"]
            for record in records
        ),
        "macro_proxy_fact_textual_recall": safe_mean(
            record["proxy_fact_recoverability"]["proxy_fact_textual_recall"] for record in records
        ),
        "macro_critical_proxy_fact_textual_recall": safe_mean(
            record["proxy_fact_recoverability"]["critical_proxy_fact_textual_recall"]
            for record in records
        ),
        "macro_detectable_error_recall_at_yellow_red": safe_mean(
            record["confidence_risk"]["detectable_error_recall"] for record in records
        ),
        "macro_reviewed_char_fraction": safe_mean(
            record["confidence_risk"]["reviewed_char_fraction"] for record in records
        ),
        "macro_proxy_word_ece": safe_mean(
            record["confidence_risk"]["calibration_on_proxy_word_correctness"]["ece"]
            for record in records
        ),
        "detectable_error_rate_by_level_micro": {
            level: (
                error_chars_by_level[level] / chars_by_level[level]
                if chars_by_level[level]
                else None
            )
            for level in ("green", "yellow", "red", "unknown")
        },
        "diarization_case_count": sum(record["diarization"] is not None for record in records),
        "macro_acoustic_speaker_mapping_coverage": safe_mean(
            record["speaker_mapping"]["acoustic_mapping_coverage"]
            if record["speaker_mapping"] is not None
            else None
            for record in records
        ),
        "downstream_case_count": len(downstream_records),
        "macro_downstream_fact_f1": safe_mean(record["fact_f1"] for record in downstream_records),
        "macro_downstream_critical_fact_recall": safe_mean(
            record["critical_fact_recall"] for record in downstream_records
        ),
    }


def summarize_runs(
    asr_run: dict[str, Any] | None,
    nbest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, run in (("confidence", asr_run), ("nbest", nbest_run)):
        if run is None:
            result[name] = None
            continue
        runtime = run.get("runtime") or {}
        validation = run.get("validation") or {}
        result[name] = {
            "status": run.get("status", "ok"),
            "record_count": (
                validation.get("records_written")
                or run.get("record_count")
                or run.get("records_written")
            ),
            "input_audio_duration_sec": (
                runtime.get("total_audio_duration_sec")
                or runtime.get("input_audio_duration_sec")
            ),
            "transcribe_elapsed_sec": runtime.get("transcribe_elapsed_sec"),
            "real_time_factor": runtime.get("real_time_factor"),
            "restore_elapsed_sec": runtime.get("restore_elapsed_sec"),
            "cuda_peak_memory_allocated_bytes": runtime.get("cuda_peak_memory_allocated_bytes"),
            "total_beams": validation.get("total_beams"),
            "records_with_multiple_beams": validation.get("records_with_multiple_beams"),
            "all_selected_records_exported": validation.get("all_selected_records_exported"),
            "timestamp_monotonic": validation.get("timestamps_monotonic"),
        }
    return result


def write_case_csv(path: Path, records: list[dict[str, Any]]) -> None:
    rows = []
    for record in records:
        rows.append(
            {
                "case_id": record["case_id"],
                "duration_min": record["duration_sec"] / 60,
                "expected_speaker_k": record.get("expected_speaker_k"),
                "asr_windows": record["asr_window_count"],
                "asr_words": record["asr_word_count"],
                "proxy_cer": record["transcript_quality"]["cer"],
                "mixed_token_error_rate": record["transcript_quality"]["mixed_token_error_rate"],
                "critical_information_preservation_score": record["critical_information"][
                    "critical_information_preservation_score"
                ],
                "proxy_fact_textual_recall": record["proxy_fact_recoverability"][
                    "proxy_fact_textual_recall"
                ],
                "critical_proxy_fact_textual_recall": record["proxy_fact_recoverability"][
                    "critical_proxy_fact_textual_recall"
                ],
                "reviewed_char_fraction": record["confidence_risk"]["reviewed_char_fraction"],
                "detectable_error_recall_yellow_red": record["confidence_risk"][
                    "detectable_error_recall"
                ],
                "proxy_word_ece": record["confidence_risk"][
                    "calibration_on_proxy_word_correctness"
                ]["ece"],
                "detected_speaker_count": (
                    record["diarization"]["detected_speaker_count"]
                    if record["diarization"] is not None
                    else None
                ),
                "acoustic_speaker_mapping_coverage": (
                    record["speaker_mapping"]["acoustic_mapping_coverage"]
                    if record["speaker_mapping"] is not None
                    else None
                ),
                "downstream_summary_fact_f1": (
                    record["downstream_case_summary_robustness"]["fact_f1"]
                    if record["downstream_case_summary_robustness"] is not None
                    else None
                ),
                "downstream_critical_fact_recall": (
                    record["downstream_case_summary_robustness"]["critical_fact_recall"]
                    if record["downstream_case_summary_robustness"] is not None
                    else None
                ),
                "reference_type": "llm_multi_asr_consensus_proxy",
                "formal_quality_claim_allowed": False,
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "NA"
    number = float(value)
    return f"{number * 100:.1f}%" if percent else f"{number:.4f}"


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    aggregate = summary["aggregate"]

    def metric_row(label: str, key: str, explanation: str, *, percent: bool = False) -> str:
        value = fmt(aggregate[key], percent=percent)
        return f"| {label} | {value} | {explanation} |"

    lines = [
        "# 中文 5 例 ASR 代理参考鲁棒性 pilot",
        "",
        "> 研究输出，不构成临床建议。以下质量指标基于 LLM 多路自动转录代理参考，",
        "> 不是人工 clean/reference，也不能用于正式临床质量结论。",
        "",
        "## 工程覆盖",
        "",
        (
            f"- 病例：{summary['case_count']} 例；音频总时长："
            f"{aggregate['total_duration_min']:.2f} 分钟；"
        ),
        (
            f"- ASR 短窗：{aggregate['total_asr_window_count']}；"
            f"ASR 单元：{aggregate['total_asr_word_count']}；"
        ),
        f"- 已完成 diarization：{aggregate['diarization_case_count']}/{summary['case_count']} 例。",
        "",
        "## 聚合结果",
        "",
        "| 指标 | 数值 | 解释 |",
        "|---|---:|---|",
        metric_row("Proxy CER", "macro_proxy_cer", "越低越好；仅代理参考", percent=True),
        metric_row(
            "CIPS",
            "macro_critical_information_preservation_score",
            "医学词/否定/参数/侧别保持率加权",
            percent=True,
        ),
        metric_row(
            "代理事实文本召回",
            "macro_proxy_fact_textual_recall",
            "代理事实 evidence terms 在 raw ASR 中可找回比例",
            percent=True,
        ),
        metric_row(
            "黄+红可检测错误召回",
            "macro_detectable_error_recall_at_yellow_red",
            "review 风险捕获能力",
            percent=True,
        ),
        metric_row(
            "审阅字符比例",
            "macro_reviewed_char_fraction",
            "review 成本代理",
            percent=True,
        ),
        metric_row(
            "Proxy word ECE",
            "macro_proxy_word_ece",
            "未校准 confidence 的代理校准误差",
        ),
        metric_row(
            "Speaker 声学映射覆盖",
            "macro_acoustic_speaker_mapping_coverage",
            "无人工 RTTM，不代表 DER/JER",
            percent=True,
        ),
        metric_row(
            "病例摘要事实 F1",
            "macro_downstream_fact_f1",
            "同一 LLM noisy vs proxy 输入稳定性",
            percent=True,
        ),
        "",
        "## 逐例结果",
        "",
        (
            "| case | min | K | CER | CIPS | fact recall | review load | "
            "error recall | speaker map | summary F1 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in summary["case_records"]:
        mapping = record["speaker_mapping"]
        downstream = record["downstream_case_summary_robustness"]
        lines.append(
            "| {case} | {minutes:.1f} | {k} | {cer} | {cips} | {facts} | {load} | "
            "{capture} | {mapping} | {summary_f1} |".format(
                case=record["case_id"],
                minutes=record["duration_sec"] / 60,
                k=record.get("expected_speaker_k", "NA"),
                cer=fmt(record["transcript_quality"]["cer"], percent=True),
                cips=fmt(
                    record["critical_information"]["critical_information_preservation_score"],
                    percent=True,
                ),
                facts=fmt(
                    record["proxy_fact_recoverability"]["proxy_fact_textual_recall"],
                    percent=True,
                ),
                load=fmt(
                    record["confidence_risk"]["reviewed_char_fraction"],
                    percent=True,
                ),
                capture=fmt(
                    record["confidence_risk"]["detectable_error_recall"],
                    percent=True,
                ),
                mapping=fmt(
                    mapping["acoustic_mapping_coverage"] if mapping else None,
                    percent=True,
                ),
                summary_f1=fmt(downstream["fact_f1"] if downstream else None, percent=True),
            )
        )
    lines.extend(
        [
            "",
            "## 指标边界",
            "",
            (
                "- CIPS 是本项目自定义的病例信息鲁棒性指标：医学术语 0.35、否定 0.20、"
                "带单位参数 0.25、侧别 0.20；若某分量在代理参考中不存在，"
                "则重归一化其余权重。"
            ),
            (
                "- 颜色错误召回只包含能映射到 ASR hypothesis 字符的替换/插入；"
                "漏字 deletion 无可着色字符。"
            ),
            (
                "- 代理参考没有听音频，病例摘要比较也没有独立人工 gold；"
                "正式论文结论必须换成人工 reference/医生确认子集。"
            ),
            "- 所有病例摘要均为研究输出，不构成临床建议。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html_report(
    path: Path,
    summary: dict[str, Any],
    figure_paths: list[Path],
) -> None:
    """生成不依赖外部脚本或样式的本地展示报告。"""

    aggregate = summary["aggregate"]
    metric_rows = [
        ("Proxy CER", fmt(aggregate["macro_proxy_cer"], percent=True)),
        (
            "CIPS",
            fmt(aggregate["macro_critical_information_preservation_score"], percent=True),
        ),
        (
            "代理事实文本召回",
            fmt(aggregate["macro_proxy_fact_textual_recall"], percent=True),
        ),
        (
            "黄+红可检测错误召回",
            fmt(aggregate["macro_detectable_error_recall_at_yellow_red"], percent=True),
        ),
        ("审阅字符比例", fmt(aggregate["macro_reviewed_char_fraction"], percent=True)),
        ("Proxy word ECE", fmt(aggregate["macro_proxy_word_ece"])),
        (
            "声学 speaker 映射覆盖",
            fmt(aggregate["macro_acoustic_speaker_mapping_coverage"], percent=True),
        ),
        ("病例摘要事实 F1", fmt(aggregate["macro_downstream_fact_f1"], percent=True)),
    ]
    metric_cards = "".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in metric_rows
    )
    case_rows = []
    for record in summary["case_records"]:
        downstream = record["downstream_case_summary_robustness"]
        mapping = record["speaker_mapping"]
        values = [
            record["case_id"],
            f'{record["duration_sec"] / 60:.1f}',
            str(record.get("expected_speaker_k", "NA")),
            fmt(record["transcript_quality"]["cer"], percent=True),
            fmt(
                record["critical_information"]["critical_information_preservation_score"],
                percent=True,
            ),
            fmt(
                record["proxy_fact_recoverability"]["proxy_fact_textual_recall"],
                percent=True,
            ),
            fmt(record["confidence_risk"]["reviewed_char_fraction"], percent=True),
            fmt(record["confidence_risk"]["detectable_error_recall"], percent=True),
            fmt(mapping["acoustic_mapping_coverage"] if mapping else None, percent=True),
            fmt(downstream["fact_f1"] if downstream else None, percent=True),
        ]
        cells = "".join(f"<td>{escape(value)}</td>" for value in values)
        case_rows.append(f"<tr>{cells}</tr>")
    figure_cards = "".join(
        (
            '<figure><img src="{src}" alt="{alt}" loading="lazy">'
            '<figcaption>{alt}</figcaption></figure>'
        ).format(src=escape(figure_path.name), alt=escape(figure_path.stem.replace("_", " ")))
        for figure_path in figure_paths
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>中文 5 例 ASR 代理参考鲁棒性 pilot</title>
  <style>
    :root {{ color-scheme: light; --ink:#183153; --muted:#5b6b7c; --line:#d9e2ec; }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif;
      color:#172b4d; background:#f5f7fa;
    }}
    main {{ max-width:1180px; margin:auto; padding:32px 24px 64px; }}
    h1,h2 {{ color:var(--ink); }}
    .warning {{ border-left:5px solid #d97706; padding:12px 16px; background:#fff7ed; }}
    .metrics {{
      display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
      gap:12px; margin:22px 0;
    }}
    .metric,figure,.table-wrap {{
      background:white; border:1px solid var(--line); border-radius:12px;
      box-shadow:0 4px 14px #16324f0d;
    }}
    .metric {{ padding:16px; }}
    .metric span {{ display:block; color:var(--muted); }}
    .metric strong {{ font-size:25px; color:var(--ink); }}
    .table-wrap {{ overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{
      padding:10px 12px; border-bottom:1px solid var(--line);
      text-align:right; white-space:nowrap;
    }}
    th:first-child,td:first-child {{ text-align:left; }}
    th {{ background:#edf2f7; }}
    .figures {{
      display:grid; grid-template-columns:repeat(auto-fit,minmax(440px,1fr)); gap:16px;
    }}
    figure {{ margin:0; padding:12px; }}
    img {{ display:block; width:100%; height:auto; }}
    figcaption {{ color:var(--muted); text-align:center; margin-top:6px; }}
    footer {{ color:var(--muted); margin-top:26px; }}
    @media (max-width:600px) {{
      main {{ padding:20px 12px 40px; }}
      .figures {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body><main>
  <h1>中文 5 例 ASR 代理参考鲁棒性 pilot</h1>
  <p class="warning"><strong>研究输出，不构成临床建议。</strong>
    质量指标使用未听音频的 LLM 多路自动转录代理参考，不是人工 clean/reference，
    也不能用于正式质量结论。</p>
  <p>工程覆盖：{summary['case_count']} 例，
    {aggregate['total_duration_min']:.2f} 分钟，
    {aggregate['total_asr_window_count']} 个 ASR 窗口，
    {aggregate['total_asr_word_count']} 个审阅单元，
    diarization {aggregate['diarization_case_count']}/{summary['case_count']}。</p>
  <section class="metrics">{metric_cards}</section>
  <h2>逐例指标</h2>
  <div class="table-wrap"><table><thead><tr>
    <th>case</th><th>min</th><th>K</th><th>CER</th><th>CIPS</th>
    <th>fact recall</th><th>review load</th><th>error recall</th>
    <th>speaker map</th><th>summary F1</th>
  </tr></thead><tbody>{''.join(case_rows)}</tbody></table></div>
  <h2>图表</h2>
  <section class="figures">{figure_cards}</section>
  <footer>CIPS 为本项目自定义病例关键信息保持指标；颜色错误召回不包含无法着色的
    deletion。正式结论必须换用独立人工 reference、真实人工 confirmed transcript 与下游
    gold facts。</footer>
</main></body></html>
"""
    path.write_text(html, encoding="utf-8")


def _build_figures_with_matplotlib(
    output_dir: Path,
    records: list[dict[str, Any]],
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"figure.dpi": 160, "font.size": 9})
    case_labels = [record["case_id"].replace("case_", "") for record in records]
    figure_paths: list[Path] = []

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    axes[0].bar(case_labels, [record["duration_sec"] / 60 for record in records], color="#4C78A8")
    axes[0].set(title="Pilot duration coverage", xlabel="Anonymous case", ylabel="Minutes")
    axes[1].bar(
        case_labels,
        [record.get("expected_speaker_k", 0) for record in records],
        color="#72B7B2",
        label="Package expected K",
    )
    detected = [
        record["diarization"]["detected_speaker_count"]
        if record["diarization"] is not None
        else math.nan
        for record in records
    ]
    axes[1].plot(case_labels, detected, color="#E45756", marker="o", label="Sortformer detected")
    axes[1].set(title="Speaker-count engineering coverage", xlabel="Anonymous case", ylabel="Count")
    axes[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    path = output_dir / "figure_1_engineering_coverage.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    x = range(len(records))
    width = 0.25
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(
        [value - width for value in x],
        [record["transcript_quality"]["cer"] for record in records],
        width,
        label="Proxy CER (lower better)",
        color="#E45756",
    )
    ax.bar(
        list(x),
        [
            record["critical_information"]["critical_information_preservation_score"] or 0.0
            for record in records
        ],
        width,
        label="CIPS (higher better)",
        color="#54A24B",
    )
    ax.bar(
        [value + width for value in x],
        [
            record["proxy_fact_recoverability"]["proxy_fact_textual_recall"] or 0.0
            for record in records
        ],
        width,
        label="Proxy fact recall (higher better)",
        color="#F2CF5B",
    )
    ax.set(
        xticks=list(x),
        xticklabels=case_labels,
        ylim=(0, 1.05),
        xlabel="Anonymous case",
        ylabel="Rate",
    )
    ax.set_title("Transcript and critical-information robustness (proxy reference)")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center")
    fig.tight_layout()
    path = output_dir / "figure_2_proxy_robustness_metrics.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    levels = ["green", "yellow", "red"]
    aggregate_chars = Counter()
    aggregate_errors = Counter()
    for record in records:
        for level, values in record["confidence_risk"]["risk_by_level"].items():
            aggregate_chars[level] += int(values["char_count"])
            aggregate_errors[level] += int(values["detectable_error_char_count"])
    rates = [
        aggregate_errors[level] / aggregate_chars[level] if aggregate_chars[level] else 0.0
        for level in levels
    ]
    shares = [
        aggregate_chars[level] / sum(aggregate_chars.values()) if aggregate_chars else 0.0
        for level in levels
    ]
    fig, ax = plt.subplots(figsize=(7, 4))
    positions = range(len(levels))
    ax.bar(
        [value - 0.18 for value in positions],
        rates,
        0.36,
        label="Detectable error rate",
        color="#E45756",
    )
    ax.bar(
        [value + 0.18 for value in positions],
        shares,
        0.36,
        label="Character share",
        color="#4C78A8",
    )
    ax.set(
        xticks=list(positions),
        xticklabels=levels,
        ylim=(0, max([*rates, *shares, 0.1]) * 1.2),
        ylabel="Rate",
    )
    ax.set_title("Risk color stratification on proxy-reference alignment")
    ax.legend(frameon=False)
    fig.tight_layout()
    path = output_dir / "figure_3_risk_color_stratification.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for record, label in zip(records, case_labels, strict=True):
        curve = record["confidence_risk"]["risk_coverage_curve"]
        ax.plot(
            [point["coverage"] for point in curve],
            [point["selective_detectable_error_rate"] for point in curve],
            marker=".",
            linewidth=1.2,
            label=label,
        )
    ax.set(
        xlabel="Retained high-confidence coverage",
        ylabel="Detectable error rate",
        title="Risk-coverage curves (lower is better)",
    )
    ax.legend(title="Case", frameon=False, fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    path = output_dir / "figure_4_risk_coverage.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    downstream_records = [
        record for record in records if record["downstream_case_summary_robustness"] is not None
    ]
    if downstream_records:
        labels = [record["case_id"].replace("case_", "") for record in downstream_records]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(
            [value - 0.18 for value in range(len(labels))],
            [
                record["downstream_case_summary_robustness"]["fact_f1"] or 0.0
                for record in downstream_records
            ],
            0.36,
            label="Fact F1",
            color="#4C78A8",
        )
        ax.bar(
            [value + 0.18 for value in range(len(labels))],
            [
                record["downstream_case_summary_robustness"]["critical_fact_recall"] or 0.0
                for record in downstream_records
            ],
            0.36,
            label="Critical fact recall",
            color="#F58518",
        )
        ax.set(
            xticks=list(range(len(labels))),
            xticklabels=labels,
            ylim=(0, 1.05),
            xlabel="Anonymous case",
            ylabel="Rate",
        )
        ax.set_title("Case-summary robustness: noisy ASR vs proxy reference")
        ax.legend(frameon=False)
        fig.tight_layout()
        path = output_dir / "figure_5_downstream_case_summary_robustness.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        figure_paths.append(path)
    return figure_paths


def build_figures(output_dir: Path, records: list[dict[str, Any]]) -> list[Path]:
    """使用纯标准库 SVG 生成 5 张验收图。"""

    case_labels = [record["case_id"].replace("case_", "") for record in records]
    figure_paths: list[Path] = []
    duration_values = [record["duration_sec"] / 60 for record in records]
    annotations = [
        "K={expected} / detected={detected}".format(
            expected=record.get("expected_speaker_k", "NA"),
            detected=(
                record["diarization"]["detected_speaker_count"]
                if record["diarization"] is not None
                else "NA"
            ),
        )
        for record in records
    ]
    path = output_dir / "figure_1_engineering_coverage.svg"
    write_grouped_bar_svg(
        path,
        labels=case_labels,
        series=[("Duration (min)", duration_values, "#4C78A8")],
        title="Pilot engineering coverage",
        y_label="Minutes",
        annotations=annotations,
    )
    figure_paths.append(path)

    path = output_dir / "figure_2_proxy_robustness_metrics.svg"
    write_grouped_bar_svg(
        path,
        labels=case_labels,
        series=[
            (
                "Proxy CER (lower better)",
                [record["transcript_quality"]["cer"] for record in records],
                "#E45756",
            ),
            (
                "CIPS (higher better)",
                [
                    record["critical_information"]["critical_information_preservation_score"] or 0.0
                    for record in records
                ],
                "#54A24B",
            ),
            (
                "Proxy fact recall",
                [
                    record["proxy_fact_recoverability"]["proxy_fact_textual_recall"] or 0.0
                    for record in records
                ],
                "#F2CF5B",
            ),
        ],
        title="Transcript and critical-information robustness (proxy reference)",
        y_label="Rate",
        y_max=1.0,
    )
    figure_paths.append(path)

    levels = ["green", "yellow", "red"]
    aggregate_chars: Counter[str] = Counter()
    aggregate_errors: Counter[str] = Counter()
    for record in records:
        for level, values in record["confidence_risk"]["risk_by_level"].items():
            aggregate_chars[level] += int(values["char_count"])
            aggregate_errors[level] += int(values["detectable_error_char_count"])
    rates = [
        aggregate_errors[level] / aggregate_chars[level] if aggregate_chars[level] else 0.0
        for level in levels
    ]
    shares = [
        aggregate_chars[level] / sum(aggregate_chars.values()) if aggregate_chars else 0.0
        for level in levels
    ]
    path = output_dir / "figure_3_risk_color_stratification.svg"
    write_grouped_bar_svg(
        path,
        labels=levels,
        series=[
            ("Detectable error rate", rates, "#E45756"),
            ("Character share", shares, "#4C78A8"),
        ],
        title="Risk color stratification on proxy-reference alignment",
        y_label="Rate",
        y_max=max([*rates, *shares, 0.1]) * 1.15,
    )
    figure_paths.append(path)

    colors = ("#4C78A8", "#F58518", "#54A24B", "#E45756", "#B279A2")
    curves: list[tuple[str, list[tuple[float, float]], str]] = []
    for record, label in zip(records, case_labels, strict=True):
        curve = record["confidence_risk"]["risk_coverage_curve"]
        curves.append(
            (
                label,
                [(point["coverage"], point["selective_detectable_error_rate"]) for point in curve],
                colors[len(curves) % len(colors)],
            )
        )
    path = output_dir / "figure_4_risk_coverage.svg"
    write_line_svg(
        path,
        curves=curves,
        title="Risk-coverage curves (lower is better)",
        x_label="Retained high-confidence coverage",
        y_label="Detectable error rate",
    )
    figure_paths.append(path)

    downstream_records = [
        record for record in records if record["downstream_case_summary_robustness"] is not None
    ]
    if downstream_records:
        labels = [record["case_id"].replace("case_", "") for record in downstream_records]
        path = output_dir / "figure_5_downstream_case_summary_robustness.svg"
        write_grouped_bar_svg(
            path,
            labels=labels,
            series=[
                (
                    "Fact F1",
                    [
                        record["downstream_case_summary_robustness"]["fact_f1"] or 0.0
                        for record in downstream_records
                    ],
                    "#4C78A8",
                ),
                (
                    "Critical fact recall",
                    [
                        record["downstream_case_summary_robustness"]["critical_fact_recall"] or 0.0
                        for record in downstream_records
                    ],
                    "#F58518",
                ),
            ],
            title="Case-summary robustness: noisy ASR vs proxy reference",
            y_label="Rate",
            y_max=1.0,
        )
        figure_paths.append(path)
    return figure_paths


def main() -> None:
    summary = run(parse_args())
    print(
        json.dumps(
            {"status": summary["status"], "outputs": summary["outputs"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
