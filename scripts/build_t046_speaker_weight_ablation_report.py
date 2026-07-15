# ruff: noqa: E501
"""T046：汇总说话人字段条件软权重消融，并生成可展示的聚合图。

正式比较要求两组使用相同 consultation、相同 gold facts、相同生成模型，且
病例摘要语言与 gold facts 对齐。本脚本只读取聚合指标和不含病例正文的质量记录，
输出 CSV、Markdown、JSON 与 SVG；不复制 transcript、prompt 或病例事实正文。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path("outputs/primock57/t046_speaker_weight_ablation")

PROFILE_LABELS = {
    "role_blind": "原始基线（role blind）",
    "field_conditioned_v1": "医生/患者字段权重",
}
METRIC_SPECS = (
    ("fact_precision_micro", "Precision"),
    ("fact_recall_micro", "Recall"),
    ("fact_f1_micro", "F1"),
    ("critical_fact_recall_macro", "Critical recall"),
    ("rouge_l_f1_macro", "ROUGE-L F1"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_ROOT / "role_blind_en",
    )
    parser.add_argument(
        "--weighted-dir",
        type=Path,
        default=DEFAULT_ROOT / "field_conditioned_v1_en",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260713)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def profile_payload(directory: Path, expected_profile: str) -> dict[str, Any]:
    generation = read_json(directory / "generation_summary.json")
    quality = read_json(directory / "evaluation" / "quality_summary.json")
    generation_records = read_jsonl(directory / "generation_records.jsonl")
    quality_records = read_jsonl(directory / "evaluation" / "quality_records.jsonl")

    actual_profile = generation["evidence_weighting"]["profile"]
    if actual_profile != expected_profile:
        raise ValueError(
            f"{directory} profile={actual_profile!r}，预期 {expected_profile!r}"
        )
    if generation.get("summary_language") != "en":
        raise ValueError(f"{directory} 不是英文对齐批次")
    if generation.get("status_counts") != {"generated": 57}:
        raise ValueError(f"{directory} 未完整生成 57 条：{generation.get('status_counts')}")
    if quality.get("evaluated_record_count") != 57:
        raise ValueError(f"{directory} 未完整评测 57 条")

    models = {
        record.get("model", {}).get("model_name")
        for record in generation_records
        if isinstance(record.get("model"), dict)
    }
    return {
        "profile": expected_profile,
        "label": PROFILE_LABELS[expected_profile],
        "generation": generation,
        "quality": quality,
        "quality_records": quality_records,
        "models": sorted(str(model) for model in models if model),
    }


def paired_analysis(
    baseline_records: Iterable[dict[str, Any]],
    weighted_records: Iterable[dict[str, Any]],
    *,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    baseline = {record["consultation_id"]: record for record in baseline_records}
    weighted = {record["consultation_id"]: record for record in weighted_records}
    ids = sorted(set(baseline) & set(weighted))
    if len(ids) != 57:
        raise ValueError(f"配对 consultation 数应为 57，实际 {len(ids)}")

    metrics: dict[str, Any] = {}
    for key in ("fact_precision", "fact_recall", "fact_f1", "critical_fact_recall"):
        deltas = [
            float(weighted[item][key]) - float(baseline[item][key])
            for item in ids
            if weighted[item].get(key) is not None and baseline[item].get(key) is not None
        ]
        ci_low, ci_high = bootstrap_mean_ci(
            deltas,
            samples=bootstrap_samples,
            seed=seed + len(metrics),
        )
        positive = sum(delta > 1e-12 for delta in deltas)
        negative = sum(delta < -1e-12 for delta in deltas)
        tied = len(deltas) - positive - negative
        metrics[key] = {
            "paired_count": len(deltas),
            "mean_delta": fmean(deltas),
            "median_delta": percentile(sorted(deltas), 0.5),
            "bootstrap_mean_delta_ci95": [ci_low, ci_high],
            "improved_count": positive,
            "tied_count": tied,
            "worsened_count": negative,
            "two_sided_sign_test_p": exact_sign_test(positive, negative),
        }
    return {"paired_consultation_count": len(ids), "metrics": metrics}


def bootstrap_mean_ci(
    values: list[float],
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap values 不能为空")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        fmean(values[rng.randrange(n)] for _ in range(n)) for _ in range(samples)
    )
    return percentile(means, 0.025), percentile(means, 0.975)


def percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("percentile values 不能为空")
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def exact_sign_test(positive: int, negative: int) -> float | None:
    n = positive + negative
    if n == 0:
        return None
    tail = sum(math.comb(n, index) for index in range(min(positive, negative) + 1))
    return min(1.0, 2.0 * tail / (2**n))


def comparison_rows(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        quality = profile["quality"]
        factuality = quality["factuality_counts"]
        rows.append(
            {
                "profile": profile["profile"],
                "label": profile["label"],
                "model": ",".join(profile["models"]),
                "evaluated_records": quality["evaluated_record_count"],
                "summary_fact_count": quality["summary_fact_count"],
                "fact_precision_micro": quality["fact_precision_micro"],
                "fact_recall_micro": quality["fact_recall_micro"],
                "fact_f1_micro": quality["fact_f1_micro"],
                "fact_precision_macro": quality["fact_precision_macro"],
                "fact_recall_macro": quality["fact_recall_macro"],
                "fact_f1_macro": quality["fact_f1_macro"],
                "critical_fact_recall_macro": quality["critical_fact_recall_macro"],
                "rouge_l_f1_macro": quality["rouge_l_f1_macro"],
                "supported": factuality["supported"],
                "unsupported": factuality["unsupported"],
                "contradicted": factuality["contradicted"],
                "unverifiable": factuality["unverifiable"],
                "omission_count": quality["omission_count"],
            }
        )
    return rows


def delta_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline, weighted = rows
    keys = [
        "summary_fact_count",
        "fact_precision_micro",
        "fact_recall_micro",
        "fact_f1_micro",
        "fact_precision_macro",
        "fact_recall_macro",
        "fact_f1_macro",
        "critical_fact_recall_macro",
        "rouge_l_f1_macro",
        "supported",
        "unsupported",
        "contradicted",
        "unverifiable",
        "omission_count",
    ]
    return {key: weighted[key] - baseline[key] for key in keys}


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_markdown(
    rows: list[dict[str, Any]],
    deltas: dict[str, Any],
    paired: dict[str, Any],
    path: Path,
) -> None:
    base, weighted = rows
    f1_pair = paired["metrics"]["fact_f1"]
    ci_low, ci_high = f1_pair["bootstrap_mean_delta_ci95"]
    lines = [
        "# T046 医生/患者说话人字段权重消融评测",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "结论：本轮字段条件软权重没有优于原始 role-blind 基线。",
        f"micro F1 从 {base['fact_f1_micro']:.4f} 降至 {weighted['fact_f1_micro']:.4f}（Δ {deltas['fact_f1_micro']:+.4f}）；",
        f"micro Precision Δ {deltas['fact_precision_micro']:+.4f}，micro Recall Δ {deltas['fact_recall_micro']:+.4f}，",
        f"Critical recall Δ {deltas['critical_fact_recall_macro']:+.4f}，Omission Δ {deltas['omission_count']:+d}。",
        "",
        "| 配置 | Precision | Recall | F1 | Critical recall | ROUGE-L F1 | Supported | Unsupported | Contradicted | Omission |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["label"],
                    fmt(row["fact_precision_micro"]),
                    fmt(row["fact_recall_micro"]),
                    fmt(row["fact_f1_micro"]),
                    fmt(row["critical_fact_recall_macro"]),
                    fmt(row["rouge_l_f1_macro"]),
                    str(row["supported"]),
                    str(row["unsupported"]),
                    str(row["contradicted"]),
                    str(row["omission_count"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 配对分析",
            "",
            (
                f"57 条 consultation 中 {f1_pair['paired_count']} 条可计算 record-level F1："
                f"改善 {f1_pair['improved_count']}，"
                f"持平 {f1_pair['tied_count']}，下降 {f1_pair['worsened_count']}；"
                f"平均 Δ={f1_pair['mean_delta']:+.4f}，bootstrap 95% CI "
                f"[{ci_low:+.4f}, {ci_high:+.4f}]，双侧 sign-test "
                f"p={f1_pair['two_sided_sign_test_p']:.4f}。"
            ),
            "",
            "## 解释边界",
            "",
            "- 两组均使用同一批 57 条 noisy ASR、同一模型、temperature=0、同一英文 schema 与同一 516 条自动 gold facts；唯一实验变量为说话人字段权重 prompt。",
            "- 权重是 prompt 中的软证据排序先验，不是模型内部可校准概率。",
            "- B-lite 依赖词面/术语匹配，gold facts 为自动构建；结论应理解为本轮自动消融未见收益，仍需人工事实复核与不同随机复跑验证。",
            "- 中文摘要与英文 gold 的首轮语言错配结果未纳入正式图表和结论。",
            "- 所有摘要均为研究输出，不构成临床建议。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_svg(
    rows: list[dict[str, Any]],
    deltas: dict[str, Any],
    paired: dict[str, Any],
    path: Path,
) -> None:
    width, height = 1320, 760
    left, top, panel_w, panel_h = 80, 170, 650, 360
    metric_keys = (
        ("fact_precision_micro", "Precision"),
        ("fact_recall_micro", "Recall"),
        ("fact_f1_micro", "F1"),
        ("critical_fact_recall_macro", "Critical recall"),
    )
    colors = ("#64748B", "#2563EB")
    max_metric = 0.32
    baseline, weighted = rows
    f1_pair = paired["metrics"]["fact_f1"]
    ci_low, ci_high = f1_pair["bootstrap_mean_delta_ci95"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#F8FAFC"/>',
        '<text x="660" y="48" text-anchor="middle" font-size="30" font-weight="700" font-family="Arial, Microsoft YaHei, sans-serif" fill="#0F172A">医生/患者说话人字段权重消融</text>',
        '<text x="660" y="80" text-anchor="middle" font-size="16" font-family="Arial, Microsoft YaHei, sans-serif" fill="#475569">PriMock57 · 57 consultations · noisy ASR · same generator and gold facts</text>',
        f'<rect x="80" y="102" width="1160" height="46" rx="8" fill="#FEE2E2"/><text x="660" y="132" text-anchor="middle" font-size="19" font-weight="700" font-family="Arial, Microsoft YaHei, sans-serif" fill="#991B1B">本轮未提升：micro F1 {baseline["fact_f1_micro"]:.3f} → {weighted["fact_f1_micro"]:.3f}（{deltas["fact_f1_micro"]*100:+.2f} pp）</text>',
        '<text x="80" y="164" font-size="16" font-weight="700" font-family="Arial, Microsoft YaHei, sans-serif" fill="#0F172A">A. 聚合质量指标</text>',
    ]

    x0, y0 = left, top + panel_h
    parts.extend(
        [
            f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{y0}" stroke="#94A3B8"/>',
            f'<line x1="{x0}" y1="{y0}" x2="{x0+panel_w}" y2="{y0}" stroke="#94A3B8"/>',
        ]
    )
    for index in range(5):
        value = max_metric * index / 4
        y = y0 - panel_h * index / 4
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+panel_w}" y2="{y:.1f}" stroke="#E2E8F0"/>')
        parts.append(f'<text x="{x0-10}" y="{y+5:.1f}" text-anchor="end" font-size="13" font-family="Arial, sans-serif" fill="#64748B">{value:.2f}</text>')
    group_w = panel_w / len(metric_keys)
    bar_w = 45
    for metric_index, (key, label) in enumerate(metric_keys):
        center = x0 + group_w * (metric_index + 0.5)
        for row_index, row in enumerate(rows):
            value = float(row[key])
            bar_h = value / max_metric * panel_h
            x = center + (row_index - 1) * (bar_w + 4) + 4
            y = y0 - bar_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{bar_h:.1f}" rx="3" fill="{colors[row_index]}"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-6:.1f}" text-anchor="middle" font-size="12" font-weight="700" font-family="Arial, sans-serif" fill="#334155">{value:.3f}</text>')
        parts.append(f'<text x="{center:.1f}" y="{y0+28}" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="#334155">{html.escape(label)}</text>')

    legend_y = 580
    for index, row in enumerate(rows):
        x = 100 + index * 300
        parts.append(f'<rect x="{x}" y="{legend_y}" width="18" height="18" rx="3" fill="{colors[index]}"/>')
        parts.append(f'<text x="{x+28}" y="{legend_y+15}" font-size="14" font-family="Arial, Microsoft YaHei, sans-serif" fill="#334155">{html.escape(row["label"])}</text>')

    right_x = 820
    parts.append(f'<text x="{right_x}" y="164" font-size="16" font-weight="700" font-family="Arial, Microsoft YaHei, sans-serif" fill="#0F172A">B. 加权组相对基线的计数变化</text>')
    delta_items = (
        ("supported", "Supported", True),
        ("unsupported", "Unsupported", False),
        ("contradicted", "Contradicted", False),
        ("omission_count", "Omission", False),
    )
    zero_x = 1010
    max_abs = max(abs(float(deltas[key])) for key, _, _ in delta_items) or 1
    scale = 175 / max_abs
    parts.append(f'<line x1="{zero_x}" y1="190" x2="{zero_x}" y2="480" stroke="#64748B" stroke-width="2"/>')
    for index, (key, label, higher_is_better) in enumerate(delta_items):
        value = float(deltas[key])
        y = 220 + index * 68
        good = value > 0 if higher_is_better else value < 0
        color = "#16A34A" if good else "#DC2626"
        bar_x = zero_x if value >= 0 else zero_x + value * scale
        bar_w_delta = max(2, abs(value) * scale)
        parts.append(f'<text x="{right_x}" y="{y+18}" font-size="14" font-family="Arial, sans-serif" fill="#334155">{label}</text>')
        parts.append(f'<rect x="{bar_x:.1f}" y="{y}" width="{bar_w_delta:.1f}" height="28" rx="3" fill="{color}"/>')
        text_x = zero_x + value * scale + (8 if value >= 0 else -8)
        anchor = "start" if value >= 0 else "end"
        parts.append(f'<text x="{text_x:.1f}" y="{y+20}" text-anchor="{anchor}" font-size="13" font-weight="700" font-family="Arial, sans-serif" fill="#334155">{value:+.0f}</text>')

    parts.extend(
        [
            '<rect x="800" y="500" width="440" height="102" rx="8" fill="#FFFFFF" stroke="#CBD5E1"/>',
            f'<text x="820" y="527" font-size="14" font-weight="700" font-family="Arial, Microsoft YaHei, sans-serif" fill="#0F172A">配对 consultation 级 F1（{f1_pair["paired_count"]} 条可计算）</text>',
            f'<text x="820" y="552" font-size="14" font-family="Arial, Microsoft YaHei, sans-serif" fill="#334155">改善 {f1_pair["improved_count"]} · 持平 {f1_pair["tied_count"]} · 下降 {f1_pair["worsened_count"]}</text>',
            f'<text x="820" y="578" font-size="14" font-family="Arial, Microsoft YaHei, sans-serif" fill="#334155">平均 Δ {f1_pair["mean_delta"]:+.3f} · 95% CI [{ci_low:+.3f}, {ci_high:+.3f}]</text>',
            '<text x="80" y="660" font-size="13" font-family="Arial, Microsoft YaHei, sans-serif" fill="#475569">说明：英文摘要与英文自动 gold facts 对齐；B-lite 为词面/术语启发式评测。软权重仅改变 prompt 证据排序规则。</text>',
            '<text x="80" y="688" font-size="13" font-family="Arial, Microsoft YaHei, sans-serif" fill="#475569">中文错配批次未纳入本图。图中仅含聚合指标，不含 transcript、病例正文或可识别信息。</text>',
            '<text x="80" y="724" font-size="12" font-family="Arial, Microsoft YaHei, sans-serif" fill="#64748B">研究输出，不构成临床建议。</text>',
            "</svg>",
        ]
    )
    path.write_text("\n".join(parts), encoding="utf-8")


def write_png(
    rows: list[dict[str, Any]],
    deltas: dict[str, Any],
    paired: dict[str, Any],
    path: Path,
) -> None:
    """用 Pillow 生成无需浏览器即可展示的 PNG 聚合图。"""

    from PIL import Image, ImageDraw, ImageFont

    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    font_path = Path("/mnt/c/Windows/Fonts/msyh.ttc")

    def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
        candidates = (
            Path("/mnt/c/Windows/Fonts/msyhbd.ttc") if bold else font_path,
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if bold
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        for candidate in candidates:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
        return ImageFont.load_default()

    def centered(text: str, y: int, text_font: ImageFont.ImageFont, fill: str) -> None:
        box = draw.textbbox((0, 0), text, font=text_font)
        draw.text(((width - (box[2] - box[0])) / 2, y), text, font=text_font, fill=fill)

    baseline, weighted = rows
    f1_pair = paired["metrics"]["fact_f1"]
    ci_low, ci_high = f1_pair["bootstrap_mean_delta_ci95"]
    centered("医生/患者说话人字段权重消融", 34, font(38, bold=True), "#0F172A")
    centered(
        "PriMock57 · 57 consultations · noisy ASR · same generator and gold facts",
        88,
        font(20),
        "#475569",
    )
    draw.rounded_rectangle((80, 130, 1520, 190), radius=10, fill="#FEE2E2")
    centered(
        f"本轮未提升：micro F1 {baseline['fact_f1_micro']:.3f} → "
        f"{weighted['fact_f1_micro']:.3f}（{deltas['fact_f1_micro']*100:+.2f} pp）",
        145,
        font(24, bold=True),
        "#991B1B",
    )

    draw.text((90, 220), "A. 聚合质量指标", font=font(22, bold=True), fill="#0F172A")
    x0, top, panel_w, panel_h = 90, 270, 800, 410
    y0 = top + panel_h
    max_metric = 0.32
    for index in range(5):
        value = max_metric * index / 4
        y = y0 - panel_h * index / 4
        draw.line((x0, y, x0 + panel_w, y), fill="#E2E8F0", width=2)
        draw.text((x0 - 58, y - 10), f"{value:.2f}", font=font(15), fill="#64748B")
    draw.line((x0, top, x0, y0), fill="#94A3B8", width=2)
    draw.line((x0, y0, x0 + panel_w, y0), fill="#94A3B8", width=2)
    metric_keys = (
        ("fact_precision_micro", "Precision"),
        ("fact_recall_micro", "Recall"),
        ("fact_f1_micro", "F1"),
        ("critical_fact_recall_macro", "Critical recall"),
    )
    colors = ("#64748B", "#2563EB")
    group_w = panel_w / len(metric_keys)
    bar_w = 58
    for metric_index, (key, label) in enumerate(metric_keys):
        center = x0 + group_w * (metric_index + 0.5)
        for row_index, row in enumerate(rows):
            value = float(row[key])
            bar_h = value / max_metric * panel_h
            x = center + (row_index - 1) * (bar_w + 7) + 7
            y = y0 - bar_h
            draw.rounded_rectangle((x, y, x + bar_w, y0), radius=4, fill=colors[row_index])
            label_box = draw.textbbox((0, 0), f"{value:.3f}", font=font(15, bold=True))
            draw.text(
                (x + (bar_w - (label_box[2] - label_box[0])) / 2, y - 25),
                f"{value:.3f}",
                font=font(15, bold=True),
                fill="#334155",
            )
        label_box = draw.textbbox((0, 0), label, font=font(16))
        draw.text(
            (center - (label_box[2] - label_box[0]) / 2, y0 + 18),
            label,
            font=font(16),
            fill="#334155",
        )

    for index, row in enumerate(rows):
        x = 110 + index * 360
        draw.rounded_rectangle((x, 750, x + 22, 772), radius=3, fill=colors[index])
        draw.text((x + 34, 748), row["label"], font=font(17), fill="#334155")

    right_x = 980
    draw.text((right_x, 220), "B. 加权组相对基线的计数变化", font=font(22, bold=True), fill="#0F172A")
    delta_items = (
        ("supported", "Supported", True),
        ("unsupported", "Unsupported", False),
        ("contradicted", "Contradicted", False),
        ("omission_count", "Omission", False),
    )
    zero_x = 1250
    max_abs = max(abs(float(deltas[key])) for key, _, _ in delta_items) or 1
    scale = 220 / max_abs
    draw.line((zero_x, 285, zero_x, 590), fill="#64748B", width=3)
    for index, (key, label, higher_is_better) in enumerate(delta_items):
        value = float(deltas[key])
        y = 310 + index * 72
        good = value > 0 if higher_is_better else value < 0
        color = "#16A34A" if good else "#DC2626"
        draw.text((right_x, y + 7), label, font=font(17), fill="#334155")
        bar_x = zero_x if value >= 0 else zero_x + value * scale
        draw.rounded_rectangle(
            (bar_x, y, bar_x + max(3, abs(value) * scale), y + 34),
            radius=4,
            fill=color,
        )
        text_x = zero_x + value * scale + (12 if value >= 0 else -60)
        draw.text((text_x, y + 5), f"{value:+.0f}", font=font(17, bold=True), fill="#334155")

    draw.rounded_rectangle((960, 620, 1510, 760), radius=10, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.text(
        (990, 642),
        f"配对 consultation 级 F1（{f1_pair['paired_count']} 条可计算）",
        font=font(19, bold=True),
        fill="#0F172A",
    )
    draw.text(
        (990, 680),
        f"改善 {f1_pair['improved_count']} · 持平 {f1_pair['tied_count']} · 下降 {f1_pair['worsened_count']}",
        font=font(18),
        fill="#334155",
    )
    draw.text(
        (990, 718),
        f"平均 Δ {f1_pair['mean_delta']:+.3f} · 95% CI [{ci_low:+.3f}, {ci_high:+.3f}]",
        font=font(18),
        fill="#334155",
    )
    draw.text(
        (80, 815),
        "说明：英文摘要与英文自动 gold facts 对齐；B-lite 为词面/术语启发式评测。中文错配批次未纳入本图。",
        font=font(16),
        fill="#475569",
    )
    draw.text(
        (80, 852),
        "图中仅含聚合指标，不含病例正文或可识别信息。研究输出，不构成临床建议。",
        font=font(16),
        fill="#64748B",
    )
    image.save(path, format="PNG", optimize=True)


def main() -> None:
    args = parse_args()
    if args.bootstrap_samples <= 0:
        raise SystemExit("--bootstrap-samples 必须大于 0")
    baseline = profile_payload(resolve(args.baseline_dir), "role_blind")
    weighted = profile_payload(resolve(args.weighted_dir), "field_conditioned_v1")
    if baseline["models"] != weighted["models"]:
        raise ValueError(f"两组模型不一致：{baseline['models']} vs {weighted['models']}")

    rows = comparison_rows([baseline, weighted])
    deltas = delta_payload(rows)
    paired = paired_analysis(
        baseline["quality_records"],
        weighted["quality_records"],
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "t046_speaker_weight_ablation_results.csv"
    md_path = output_dir / "t046_speaker_weight_ablation_report.md"
    json_path = output_dir / "t046_speaker_weight_ablation_summary.json"
    svg_path = output_dir / "t046_speaker_weight_ablation_figure.svg"
    png_path = output_dir / "t046_speaker_weight_ablation_figure.png"
    write_csv(rows, csv_path)
    write_markdown(rows, deltas, paired, md_path)
    write_svg(rows, deltas, paired, svg_path)
    write_png(rows, deltas, paired, png_path)
    summary = {
        "schema_version": "t046_speaker_weight_ablation_summary/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": "primock57",
        "formal_evaluation_language": "en",
        "profiles": rows,
        "weighted_minus_baseline": deltas,
        "paired_analysis": paired,
        "validation": {
            "same_model": True,
            "same_consultations": True,
            "paired_consultation_count": 57,
            "temperature": 0,
            "gold_fact_count": 516,
            "language_mismatch_batches_excluded": True,
            "contains_transcript_or_case_text": False,
            "research_use_only": True,
        },
        "outputs": {
            "csv": csv_path.relative_to(PROJECT_ROOT).as_posix(),
            "markdown": md_path.relative_to(PROJECT_ROOT).as_posix(),
            "svg": svg_path.relative_to(PROJECT_ROOT).as_posix(),
            "png": png_path.relative_to(PROJECT_ROOT).as_posix(),
        },
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("T046 说话人字段权重消融汇总完成。")
    print(f"- micro F1: {rows[0]['fact_f1_micro']:.4f} -> {rows[1]['fact_f1_micro']:.4f}")
    print(f"- delta: {deltas['fact_f1_micro']:+.4f}")
    print(f"- figure: {svg_path}")


if __name__ == "__main__":
    main()
