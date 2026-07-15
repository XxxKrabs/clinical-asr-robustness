"""汇总中文 40 例工程覆盖，并生成 CSV/Markdown/HTML/SVG 展示报告。

本报告只使用音频时长、匿名 case id、ASR/置信度/n-best/diarization/审阅工程统计；不读取
reference 正文，也不把工程覆盖写成准确率。代理质量指标继续引用固定 5 例报告。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import read_asr_confidence_jsonl
from clinical_asr_robustness.svg_charts import (
    write_grouped_bar_svg,
    write_stacked_bar_svg,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path("outputs/remote_programming_40/t061_all40")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(
            "data/interim/remote_programming_40/manifests/"
            "remote_programming_40_asr_manifest.jsonl"
        ),
    )
    parser.add_argument(
        "--window-manifest",
        type=Path,
        default=Path(
            "data/interim/remote_programming_40/manifests/"
            "remote_programming_40_t061_all40_windows.jsonl"
        ),
    )
    parser.add_argument("--asr-jsonl", type=Path, default=DEFAULT_ROOT / "asr_confidence.jsonl")
    parser.add_argument(
        "--asr-run-json",
        type=Path,
        default=DEFAULT_ROOT / "asr_confidence_run.json",
    )
    parser.add_argument("--nbest-jsonl", type=Path, default=DEFAULT_ROOT / "asr_nbest.jsonl")
    parser.add_argument(
        "--nbest-run-json",
        type=Path,
        default=DEFAULT_ROOT / "asr_nbest_run.json",
    )
    parser.add_argument(
        "--diarization-jsonl",
        type=Path,
        default=DEFAULT_ROOT / "sortformer_diarization.jsonl",
    )
    parser.add_argument(
        "--diarization-run-json",
        type=Path,
        default=DEFAULT_ROOT / "sortformer_diarization_run.json",
    )
    parser.add_argument(
        "--diarized-asr-jsonl",
        type=Path,
        default=DEFAULT_ROOT / "asr_confidence_diarized.jsonl",
    )
    parser.add_argument(
        "--medical-run-json",
        type=Path,
        default=DEFAULT_ROOT / "medical_entities_run.json",
    )
    parser.add_argument(
        "--candidates-run-json",
        type=Path,
        default=DEFAULT_ROOT / "candidates_run.json",
    )
    parser.add_argument(
        "--review-run-json",
        type=Path,
        default=DEFAULT_ROOT / "review_run.json",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT / "report")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
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


def read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def case_id_from_values(*values: Any) -> str | None:
    for value in values:
        text = str(value or "")
        if text.startswith("case_"):
            return text
        for part in text.split(":"):
            if part.startswith("case_"):
                return part
    return None


def source_cases(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        case_id = case_id_from_values(row.get("consultation_id"), row.get("sample_id"))
        if not case_id:
            raise ValueError("source manifest 存在无法解析匿名 case id 的记录")
        result[case_id] = {
            "case_id": case_id,
            "source_duration_sec": float(row.get("duration_sec") or row.get("duration") or 0.0),
        }
    return result


def window_counts(path: Path) -> tuple[Counter[str], Counter[str]]:
    counts: Counter[str] = Counter()
    durations_ms: Counter[str] = Counter()
    for row in read_jsonl(path):
        case_id = case_id_from_values(row.get("consultation_id"), row.get("sample_id"))
        if not case_id:
            continue
        counts[case_id] += 1
        durations_ms[case_id] += round(
            1000 * float(row.get("duration_sec") or row.get("duration") or 0.0)
        )
    return counts, durations_ms


def asr_metrics(path: Path) -> dict[str, dict[str, Any]]:
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    confidence_sum: Counter[str] = Counter()
    records = read_asr_confidence_jsonl(path)
    for record in records:
        case_id = case_id_from_values(record.consultation_id, record.sample_id)
        if not case_id:
            continue
        totals[case_id]["records"] += 1
        totals[case_id]["duration_ms"] += round(1000 * float(record.duration_sec))
        totals[case_id]["empty_records"] += int(not record.asr_words)
        previous_start = -1.0
        for word in record.asr_words:
            totals[case_id]["words"] += 1
            totals[case_id][f"risk_{word.confidence_level.value}"] += 1
            confidence_sum[case_id] += float(word.confidence)
            if word.start_sec is None or word.end_sec is None:
                totals[case_id]["missing_word_timestamps"] += 1
            elif float(word.start_sec) + 1e-9 < previous_start:
                totals[case_id]["timestamp_order_violations"] += 1
            if word.start_sec is not None:
                previous_start = float(word.start_sec)
    return {
        case_id: {
            **dict(counts),
            "mean_word_confidence": (
                confidence_sum[case_id] / counts["words"] if counts["words"] else None
            ),
        }
        for case_id, counts in totals.items()
    }


def nbest_metrics(path: Path) -> dict[str, Counter[str]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in read_jsonl(path):
        case_id = case_id_from_values(row.get("consultation_id"), row.get("sample_id"))
        if not case_id:
            continue
        beams = row.get("beams") or row.get("nbest") or []
        result[case_id]["records"] += 1
        result[case_id]["beams"] += len(beams)
        result[case_id]["records_with_multiple_beams"] += int(len(beams) > 1)
    return result


def diarization_metrics(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        case_id = case_id_from_values(row.get("consultation_id"), row.get("sample_id"))
        if not case_id:
            continue
        runtime = row.get("runtime") or {}
        result[case_id] = {
            "detected_speakers": len(row.get("speaker_labels") or []),
            "diarization_segments": len(row.get("segments") or []),
            "diarization_rtf": runtime.get("real_time_factor"),
        }
    return result


def speaker_mapping_metrics(path: Path) -> dict[str, dict[str, Any]]:
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for record in read_asr_confidence_jsonl(path):
        case_id = case_id_from_values(record.consultation_id, record.sample_id)
        if not case_id:
            continue
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
            "total": counts["total"],
            "acoustic_coverage": (
                counts["acoustic"] / counts["total"] if counts["total"] else None
            ),
            "resolved_coverage": (
                counts["resolved"] / counts["total"] if counts["total"] else None
            ),
            "ambiguous_words": counts["ambiguous"],
        }
        for case_id, counts in totals.items()
    }


def safe_mean(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None


def build_case_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    source = source_cases(resolve_project_path(args.source_manifest))
    windows, window_duration_ms = window_counts(resolve_project_path(args.window_manifest))
    asr = asr_metrics(resolve_project_path(args.asr_jsonl))
    nbest = nbest_metrics(resolve_project_path(args.nbest_jsonl))
    diarization = diarization_metrics(resolve_project_path(args.diarization_jsonl))
    mapping = speaker_mapping_metrics(resolve_project_path(args.diarized_asr_jsonl))
    rows: list[dict[str, Any]] = []
    for case_id in sorted(source):
        asr_case = asr.get(case_id, {})
        nbest_case = nbest.get(case_id, Counter())
        diar_case = diarization.get(case_id, {})
        mapping_case = mapping.get(case_id, {})
        word_count = int(asr_case.get("words") or 0)
        rows.append(
            {
                **source[case_id],
                "window_count": int(windows[case_id]),
                "window_duration_sec": window_duration_ms[case_id] / 1000,
                "asr_record_count": int(asr_case.get("records") or 0),
                "asr_word_count": word_count,
                "empty_asr_record_count": int(asr_case.get("empty_records") or 0),
                "timestamp_order_violation_count": int(
                    asr_case.get("timestamp_order_violations") or 0
                ),
                "missing_word_timestamp_count": int(
                    asr_case.get("missing_word_timestamps") or 0
                ),
                "mean_word_confidence": asr_case.get("mean_word_confidence"),
                "green_words": int(asr_case.get("risk_green") or 0),
                "yellow_words": int(asr_case.get("risk_yellow") or 0),
                "red_words": int(asr_case.get("risk_red") or 0),
                "nbest_record_count": int(nbest_case["records"]),
                "nbest_beam_count": int(nbest_case["beams"]),
                "nbest_multiple_record_count": int(
                    nbest_case["records_with_multiple_beams"]
                ),
                "detected_speakers": diar_case.get("detected_speakers"),
                "diarization_segments": diar_case.get("diarization_segments"),
                "diarization_rtf": diar_case.get("diarization_rtf"),
                "acoustic_speaker_mapping_coverage": mapping_case.get("acoustic_coverage"),
                "resolved_speaker_mapping_coverage": mapping_case.get("resolved_coverage"),
                "ambiguous_overlap_word_count": mapping_case.get("ambiguous_words"),
            }
        )
    return rows


def run_stage_details(args: argparse.Namespace) -> dict[str, Any]:
    paths = {
        "confidence": resolve_project_path(args.asr_run_json),
        "nbest": resolve_project_path(args.nbest_run_json),
        "diarization": resolve_project_path(args.diarization_run_json),
        "medical_entities": resolve_project_path(args.medical_run_json),
        "candidates": resolve_project_path(args.candidates_run_json),
        "review": resolve_project_path(args.review_run_json),
    }
    return {name: read_json_optional(path) for name, path in paths.items()}


def build_aggregate(rows: list[dict[str, Any]], runs: dict[str, Any]) -> dict[str, Any]:
    risk_counts = {
        level: sum(int(row[f"{level}_words"]) for row in rows)
        for level in ("green", "yellow", "red")
    }
    total_words = sum(risk_counts.values())
    asr_run = runs.get("confidence") or {}
    nbest_run = runs.get("nbest") or {}
    diar_run = runs.get("diarization") or {}
    medical_validation = (runs.get("medical_entities") or {}).get("validation") or {}
    candidate_validation = (runs.get("candidates") or {}).get("validation") or {}
    review_validation = (runs.get("review") or {}).get("validation") or {}
    return {
        "source_case_count": len(rows),
        "source_duration_min": sum(float(row["source_duration_sec"]) for row in rows) / 60,
        "preprocessed_case_count": sum(int(row["window_count"] > 0) for row in rows),
        "window_count": sum(int(row["window_count"]) for row in rows),
        "asr_case_count": sum(int(row["asr_record_count"] > 0) for row in rows),
        "asr_record_count": sum(int(row["asr_record_count"]) for row in rows),
        "asr_word_count": total_words,
        "empty_asr_record_count": sum(int(row["empty_asr_record_count"]) for row in rows),
        "timestamp_order_violation_count": sum(
            int(row["timestamp_order_violation_count"]) for row in rows
        ),
        "missing_word_timestamp_count": sum(
            int(row["missing_word_timestamp_count"]) for row in rows
        ),
        "risk_word_counts": risk_counts,
        "risk_word_fractions": {
            level: count / total_words if total_words else None
            for level, count in risk_counts.items()
        },
        "mean_word_confidence_macro": safe_mean(
            [row["mean_word_confidence"] for row in rows]
        ),
        "nbest_case_count": sum(int(row["nbest_record_count"] > 0) for row in rows),
        "nbest_record_count": sum(int(row["nbest_record_count"]) for row in rows),
        "nbest_beam_count": sum(int(row["nbest_beam_count"]) for row in rows),
        "nbest_multiple_record_count": sum(
            int(row["nbest_multiple_record_count"]) for row in rows
        ),
        "diarization_case_count": sum(row["detected_speakers"] is not None for row in rows),
        "macro_acoustic_speaker_mapping_coverage": safe_mean(
            [row["acoustic_speaker_mapping_coverage"] for row in rows]
        ),
        "macro_resolved_speaker_mapping_coverage": safe_mean(
            [row["resolved_speaker_mapping_coverage"] for row in rows]
        ),
        "asr_runtime": (asr_run.get("runtime") or {}),
        "nbest_runtime": (nbest_run.get("runtime") or {}),
        "diarization_run": {
            "selected_record_count": diar_run.get("selected_record_count"),
            "successful_record_count": diar_run.get("successful_record_count"),
            "failure_count": diar_run.get("failure_count"),
            "restore_elapsed_sec": diar_run.get("restore_elapsed_sec"),
        },
        "medical_entity_records": medical_validation.get("entity_extraction_records"),
        "medical_entity_review_spans": medical_validation.get(
            "medical_entity_review_spans"
        ),
        "candidate_total_uncertain_spans": candidate_validation.get("total_uncertain_spans"),
        "candidate_spans_with_alternatives": candidate_validation.get(
            "spans_with_alternatives"
        ),
        "review_conversation_count": review_validation.get("conversation_count"),
        "review_speaker_turn_count": review_validation.get("speaker_turn_count"),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_case_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pct(value: Any) -> str:
    return "NA" if value is None else f"{float(value) * 100:.1f}%"


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    aggregate = payload["aggregate"]
    lines = [
        "# 中文 40 例 ASR 工程运行总览",
        "",
        "> 本报告只描述工程覆盖、运行成本与风险信号，不使用人工 reference，",
        "> 不代表 ASR、说话人或病例摘要准确率。研究输出，不构成临床建议。",
        "",
        "## 总览",
        "",
        f"- 40 例源音频总时长：{aggregate['source_duration_min']:.2f} 分钟；",
        (
            f"- 预处理/ASR/n-best/diarization 病例覆盖："
            f"{aggregate['preprocessed_case_count']}/{aggregate['asr_case_count']}/"
            f"{aggregate['nbest_case_count']}/{aggregate['diarization_case_count']}；"
        ),
        (
            f"- ASR 窗口：{aggregate['asr_record_count']}；ASR 单元："
            f"{aggregate['asr_word_count']}；空窗口：{aggregate['empty_asr_record_count']}；"
        ),
        (
            "- green/yellow/red："
            f"{aggregate['risk_word_counts']['green']}/"
            f"{aggregate['risk_word_counts']['yellow']}/"
            f"{aggregate['risk_word_counts']['red']}；"
        ),
        (
            "- speaker 原始/桥接后映射覆盖："
            f"{pct(aggregate['macro_acoustic_speaker_mapping_coverage'])}/"
            f"{pct(aggregate['macro_resolved_speaker_mapping_coverage'])}。"
        ),
        "",
        "## 逐例工程表",
        "",
        (
            "| case | min | windows | words | empty | green | yellow | red | beams | "
            "speakers | acoustic map | resolved map |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["case_records"]:
        lines.append(
            "| {case_id} | {minutes:.1f} | {window_count} | {asr_word_count} | "
            "{empty_asr_record_count} | {green_words} | {yellow_words} | {red_words} | "
            "{nbest_beam_count} | {detected_speakers} | {acoustic} | {resolved} |".format(
                minutes=float(row["source_duration_sec"]) / 60,
                acoustic=pct(row["acoustic_speaker_mapping_coverage"]),
                resolved=pct(row["resolved_speaker_mapping_coverage"]),
                **row,
            )
        )
    lines.extend(
        [
            "",
            "## 口径边界",
            "",
            "- confidence 与 acoustic beam 均来自 Hybrid 模型的 auxiliary CTC 分支。",
            "- speaker map 是时间映射覆盖率，没有人工 RTTM 时不报告 DER/JER。",
            "- 风险颜色仍是 `demo_quantile_v0`，5 例 proxy 校准结果单独展示。",
            "- 自动 QA feedback/confirmed 只验证回放链路，不代表医生听音确认。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_figures(
    output_dir: Path,
    rows: list[dict[str, Any]],
    aggregate: dict[str, Any],
) -> list[Path]:
    labels = [row["case_id"].replace("case_", "") for row in rows]
    duration_path = output_dir / "figure_1_all40_duration.svg"
    write_grouped_bar_svg(
        duration_path,
        labels=labels,
        series=[("audio minutes", [row["source_duration_sec"] / 60 for row in rows], "#4C78A8")],
        title="40-case audio duration coverage",
        y_label="Minutes",
        width=1600,
        height=560,
        rotate_labels=True,
        show_values=False,
    )
    stage_path = output_dir / "figure_2_all40_stage_coverage.svg"
    stage_labels = ["preprocess", "ASR confidence", "5-best", "diarization", "review page"]
    stage_values = [
        aggregate["preprocessed_case_count"],
        aggregate["asr_case_count"],
        aggregate["nbest_case_count"],
        aggregate["diarization_case_count"],
        aggregate.get("review_conversation_count") or 0,
    ]
    write_grouped_bar_svg(
        stage_path,
        labels=stage_labels,
        series=[("completed cases", stage_values, "#59A14F")],
        title="Pipeline stage coverage",
        y_label="Anonymous cases",
        y_max=40,
    )
    risk_path = output_dir / "figure_3_all40_risk_distribution.svg"
    risk_series = []
    for level, color in (("green", "#2E8B57"), ("yellow", "#E3B341"), ("red", "#D94F4F")):
        values = []
        for row in rows:
            total = row["green_words"] + row["yellow_words"] + row["red_words"]
            values.append(row[f"{level}_words"] / total if total else 0.0)
        risk_series.append((level, values, color))
    write_stacked_bar_svg(
        risk_path,
        labels=labels,
        series=risk_series,
        title="Per-case ASR confidence risk composition",
        y_label="Share of ASR review units",
    )
    mapping_path = output_dir / "figure_4_all40_speaker_mapping.svg"
    write_grouped_bar_svg(
        mapping_path,
        labels=labels,
        series=[
            (
                "acoustic",
                [row["acoustic_speaker_mapping_coverage"] or 0.0 for row in rows],
                "#4C78A8",
            ),
            (
                "resolved display",
                [row["resolved_speaker_mapping_coverage"] or 0.0 for row in rows],
                "#72B7B2",
            ),
        ],
        title="ASR word-to-speaker time mapping coverage",
        y_label="Coverage (not accuracy)",
        y_max=1.0,
        width=1600,
        height=560,
        rotate_labels=True,
        show_values=False,
    )
    beam_path = output_dir / "figure_5_all40_nbest_beams.svg"
    write_grouped_bar_svg(
        beam_path,
        labels=labels,
        series=[
            (
                "mean beams/window",
                [
                    row["nbest_beam_count"] / row["nbest_record_count"]
                    if row["nbest_record_count"]
                    else 0.0
                    for row in rows
                ],
                "#B279A2",
            )
        ],
        title="Acoustic n-best availability by case",
        y_label="Mean unique beams per ASR window",
        y_max=5.0,
        width=1600,
        height=560,
        rotate_labels=True,
        show_values=False,
    )
    return [duration_path, stage_path, risk_path, mapping_path, beam_path]


def write_html(path: Path, payload: dict[str, Any], figures: list[Path]) -> None:
    aggregate = payload["aggregate"]
    cards = [
        ("病例覆盖", f"{aggregate['asr_case_count']}/40"),
        ("音频时长", f"{aggregate['source_duration_min']:.1f} min"),
        ("ASR 窗口", str(aggregate["asr_record_count"])),
        ("ASR 单元", str(aggregate["asr_word_count"])),
        ("空 ASR 窗口", str(aggregate["empty_asr_record_count"])),
        ("n-best beams", str(aggregate["nbest_beam_count"])),
        ("diarization", f"{aggregate['diarization_case_count']}/40"),
        ("speaker map", pct(aggregate["macro_acoustic_speaker_mapping_coverage"])),
    ]
    card_html = "".join(
        f'<div class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
    )
    rows_html = []
    for row in payload["case_records"]:
        values = [
            row["case_id"],
            f'{row["source_duration_sec"] / 60:.1f}',
            str(row["window_count"]),
            str(row["asr_word_count"]),
            str(row["empty_asr_record_count"]),
            f'{row["green_words"]}/{row["yellow_words"]}/{row["red_words"]}',
            str(row["nbest_beam_count"]),
            str(row["detected_speakers"] if row["detected_speakers"] is not None else "NA"),
            pct(row["acoustic_speaker_mapping_coverage"]),
            pct(row["resolved_speaker_mapping_coverage"]),
        ]
        cells = "".join(f"<td>{escape(value)}</td>" for value in values)
        rows_html.append(f"<tr>{cells}</tr>")
    figures_html = "".join(
        f'<figure><img src="{escape(figure.name)}" alt="{escape(figure.stem)}">'
        f"<figcaption>{escape(figure.stem)}</figcaption></figure>"
        for figure in figures
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>中文 40 例 ASR 工程运行总览</title>
<style>
body{{
  margin:0;background:#f5f7fa;color:#172b4d;
  font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif
}}
main{{max-width:1500px;margin:auto;padding:30px 22px 60px}}h1,h2{{color:#183153}}
.warning{{background:#fff7ed;border-left:5px solid #d97706;padding:12px 16px}}
.cards{{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:12px;margin:22px 0
}}
.card,figure,.table{{
  background:white;border:1px solid #d9e2ec;border-radius:12px;
  box-shadow:0 4px 14px #16324f0d
}}
.card{{padding:16px}}.card span{{display:block;color:#5b6b7c}}.card strong{{font-size:24px}}
.table{{overflow:auto}}table{{border-collapse:collapse;width:100%}}
th,td{{
  padding:9px 11px;border-bottom:1px solid #e3e8ee;
  text-align:right;white-space:nowrap
}}
th:first-child,td:first-child{{text-align:left}}th{{background:#edf2f7}}
.figures{{display:grid;grid-template-columns:1fr;gap:18px}}figure{{margin:0;padding:12px}}img{{display:block;width:100%;height:auto}}figcaption{{text-align:center;color:#5b6b7c}}
</style></head><body><main>
<h1>中文 40 例 ASR 工程运行总览</h1>
<p class="warning"><strong>工程覆盖不等于准确率。</strong>
本页没有人工 reference；speaker map 是时间映射覆盖率。代理质量结果来自固定 5 例，
所有病例整理均为研究输出，不构成临床建议。</p>
<section class="cards">{card_html}</section>
<p><a href="../../t058_pilot5/report/pilot5_report.html">
查看固定 5 例代理参考鲁棒性报告</a></p>
<h2>逐例工程表</h2><div class="table"><table><thead><tr>
<th>case</th><th>min</th><th>windows</th><th>words</th><th>empty</th>
<th>G/Y/R</th><th>beams</th><th>speakers</th><th>acoustic map</th>
<th>resolved map</th></tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>
<h2>图表</h2><section class="figures">{figures_html}</section>
</main></body></html>"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    rows = build_case_rows(args)
    runs = run_stage_details(args)
    aggregate = build_aggregate(rows, runs)
    payload = {
        "task_id": "T061_ALL40_ENGINEERING_REPORT",
        "schema_version": "chinese_all40_engineering_report/v1",
        "status": "completed" if aggregate["asr_case_count"] == 40 else "partial",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_records": rows,
        "aggregate": aggregate,
        "runs_present": {name: run is not None for name, run in runs.items()},
        "quality_claim_allowed": False,
        "reference_used": False,
        "research_use_only": True,
        "limitations": [
            "工程覆盖不等于 ASR 或 speaker 准确率。",
            "风险颜色仍是未校准 demo_quantile_v0。",
            "正式质量结论只使用独立人工 reference 或明确标源的 5 例 proxy。",
        ],
    }
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "all40_engineering_summary.json"
    csv_path = output_dir / "all40_case_metrics.csv"
    markdown_path = output_dir / "all40_results.md"
    html_path = output_dir / "all40_report.html"
    figures = build_figures(output_dir, rows, aggregate)
    write_case_csv(csv_path, rows)
    write_markdown(markdown_path, payload)
    write_html(html_path, payload, figures)
    payload["outputs"] = {
        "summary_json": project_relative(json_path),
        "case_metrics_csv": project_relative(csv_path),
        "results_markdown": project_relative(markdown_path),
        "report_html": project_relative(html_path),
        "figures": [project_relative(path) for path in figures],
    }
    write_json(json_path, payload)
    print(
        json.dumps(
            {"status": payload["status"], "outputs": payload["outputs"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
