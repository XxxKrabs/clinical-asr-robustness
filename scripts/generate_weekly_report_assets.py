"""Generate static assets for weekly practice reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CANVAS_W = 1800
CANVAS_H = 1280
MARGIN = 70
DEJAVU_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/mnt/c/Windows/Fonts/msyhbd.ttc" if bold else "/mnt/c/Windows/Fonts/msyh.ttc",
        "/mnt/c/Windows/Fonts/simhei.ttf",
        DEJAVU_BOLD if bold else DEJAVU_REGULAR,
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    line_gap: int = 8,
) -> None:
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    sizes = [text_size(draw, line, font) for line in lines]
    total_h = sum(h for _, h in sizes) + line_gap * (len(lines) - 1)
    y = y0 + ((y1 - y0) - total_h) / 2
    for line, (w, h) in zip(lines, sizes, strict=True):
        x = x0 + ((x1 - x0) - w) / 2
        draw.text((x, y), line, font=font, fill=fill)
        y += h + line_gap


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    radius: int = 18,
    width: int = 3,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str,
) -> None:
    draw.line([start, end], fill=fill, width=5)
    x, y = end
    draw.polygon([(x, y), (x - 18, y - 10), (x - 18, y + 10)], fill=fill)


def percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * part / total


def draw_bar(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    width: int,
    height: int,
    label: str,
    value: int,
    max_value: int,
    color: str,
    font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
) -> None:
    x, y = origin
    draw.text((x, y - 42), label, fill="#233142", font=font)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=12, fill="#eef3f7")
    filled = int(width * (value / max_value)) if max_value else 0
    if filled > 0:
        draw.rounded_rectangle((x, y, x + filled, y + height), radius=12, fill=color)
    draw.text((x + 14, y + 12), f"{value}", fill="#16202a", font=small_font)


def build_summary(project_root: Path) -> dict[str, Any]:
    t028 = read_json(
        project_root
        / "outputs/primock57/t028_nemo_asr_confidence/t028_nemo_asr_confidence_limit2_run.json"
    )
    t029 = read_json(
        project_root
        / "outputs/primock57/t029_asr_nbest_candidates/t029_asr_nbest_candidates_limit2_run.json"
    )
    t030 = read_json(
        project_root / "outputs/primock57/t030_review_samples/t030_review_samples_run.json"
    )
    t036 = read_json(
        project_root / "outputs/primock57/t036_doctor_review_demo/t036_doctor_review_demo_run.json"
    )
    t037 = read_json(
        project_root / "outputs/primock57/t037_nemo_asr_nbest/t037_nemo_asr_nbest_limit2_run.json"
    )
    word_levels = t028["confidence_distribution"]["word_confidence_levels"]
    total_words = t028["confidence_distribution"]["word_confidence"]["count"]
    return {
        "records": t028["validation"]["records_written"],
        "total_words": total_words,
        "green_words": word_levels.get("green", 0),
        "yellow_words": word_levels.get("yellow", 0),
        "red_words": word_levels.get("red", 0),
        "mean_confidence": t028["confidence_distribution"]["word_confidence"]["mean"],
        "uncertain_spans": t030["validation"]["total_uncertain_spans"],
        "spans_with_candidates": t030["validation"]["spans_with_candidates"],
        "sequence_alternatives": t029["validation"]["sequence_alternatives"],
        "span_alternatives": t029["validation"]["span_alternatives"],
        "feedback_actions": len(t036["validation"]["supports_actions"]),
        "total_beams": t037["validation"]["total_beams"],
        "external_paths": len(t037["runtime"]["external_speech_main_paths"]),
        "device": t037["runtime"]["cuda_device"],
    }


def render(summary: dict[str, Any], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), "#fbfcfd")
    draw = ImageDraw.Draw(image)

    title_font = find_font(46, bold=True)
    subtitle_font = find_font(24)
    box_font = find_font(22, bold=True)
    small_font = find_font(22)
    tiny_font = find_font(18)
    metric_font = find_font(30, bold=True)

    draw.text((MARGIN, 46), "Week 1 ASR Confidence Review Demo", font=title_font, fill="#17212b")
    draw.text(
        (MARGIN, 104),
        "PriMock57 limit=2, research demo only; no inline reference transcript "
        "or patient identity.",
        font=subtitle_font,
        fill="#51606f",
    )

    boxes = [
        ("Audio\nmanifest", "#e8f1fb", "#2d6a9f"),
        ("NeMo ASR\nconfidence", "#eaf7ef", "#2d7d46"),
        ("n-best\ncandidates", "#fff6dd", "#b87b00"),
        ("Review\nsample", "#fff0ec", "#bf4d3c"),
        ("Feedback ->\nconfirmed text", "#edf0ff", "#5867c3"),
    ]
    box_w = 275
    box_h = 130
    y = 190
    gap = 60
    x = MARGIN
    for idx, (label, fill, outline) in enumerate(boxes):
        rounded_box(draw, (x, y, x + box_w, y + box_h), fill, outline)
        draw_centered(draw, (x, y, x + box_w, y + box_h), label, box_font, "#182533")
        if idx < len(boxes) - 1:
            draw_arrow(
                draw,
                (x + box_w + 12, y + box_h // 2),
                (x + box_w + gap - 12, y + box_h // 2),
                "#768493",
            )
        x += box_w + gap

    panel_y = 390
    rounded_box(
        draw,
        (MARGIN, panel_y, CANVAS_W - MARGIN, panel_y + 430),
        "#ffffff",
        "#d7dee7",
        radius=24,
        width=2,
    )
    draw.text(
        (MARGIN + 34, panel_y + 28),
        "Confidence and Review Statistics",
        font=metric_font,
        fill="#17212b",
    )

    max_words = max(summary["green_words"], summary["yellow_words"], summary["red_words"], 1)
    bar_x = MARGIN + 40
    bar_y = panel_y + 120
    draw_bar(
        draw,
        (bar_x, bar_y),
        620,
        56,
        "Green words",
        summary["green_words"],
        max_words,
        "#4caf70",
        small_font,
        small_font,
    )
    draw_bar(
        draw,
        (bar_x, bar_y + 112),
        620,
        56,
        "Yellow words",
        summary["yellow_words"],
        max_words,
        "#f1c04f",
        small_font,
        small_font,
    )
    draw_bar(
        draw,
        (bar_x, bar_y + 224),
        620,
        56,
        "Red words",
        summary["red_words"],
        max_words,
        "#d85b50",
        small_font,
        small_font,
    )

    metric_cards = [
        ("ASR records", str(summary["records"])),
        ("Total words", str(summary["total_words"])),
        ("Mean conf.", f"{summary['mean_confidence']:.3f}"),
        ("Yellow spans", str(summary["uncertain_spans"])),
        ("Seq. n-best", str(summary["sequence_alternatives"])),
        ("Spans w/ cand.", str(summary["spans_with_candidates"])),
    ]
    card_w = 230
    card_h = 96
    start_x = MARGIN + 760
    start_y = panel_y + 100
    for i, (label, value) in enumerate(metric_cards):
        cx = start_x + (i % 3) * (card_w + 35)
        cy = start_y + (i // 3) * (card_h + 54)
        rounded_box(
            draw,
            (cx, cy, cx + card_w, cy + card_h),
            "#f6f8fb",
            "#e0e6ee",
            radius=18,
            width=2,
        )
        draw.text((cx + 18, cy + 16), label, font=tiny_font, fill="#5c6a78")
        draw.text((cx + 18, cy + 42), value, font=metric_font, fill="#17212b")

    bottom_y = 865
    rounded_box(
        draw,
        (MARGIN, bottom_y, CANVAS_W - MARGIN, bottom_y + 310),
        "#f8fafc",
        "#d7dee7",
        radius=24,
        width=2,
    )
    green_share = percent(summary["green_words"], summary["total_words"])
    yellow_share = percent(summary["yellow_words"], summary["total_words"])
    notes = [
        f"Green share: {green_share:.1f}%; yellow share: {yellow_share:.1f}%.",
        f"Beam decoding produced {summary['total_beams']} sequence alternatives; "
        "span candidates are mapped by sequence-level diff.",
        f"The interactive review demo supports {summary['feedback_actions']} actions: "
        "accept, choose, edit, reject, or unable to judge.",
        f"External Speech-main paths detected: {summary['external_paths']}; "
        f"runtime device: {summary['device']}.",
    ]
    draw.text(
        (MARGIN + 34, bottom_y + 28),
        "What this result shows",
        font=metric_font,
        fill="#17212b",
    )
    yy = bottom_y + 86
    for note in notes:
        draw.ellipse((MARGIN + 42, yy + 8, MARGIN + 54, yy + 20), fill="#3973b7")
        draw.text((MARGIN + 70, yy), note, font=small_font, fill="#263442")
        yy += 42

    image.save(output_png)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-png",
        type=Path,
        default=Path("outputs/reports/week1_asr_confidence_review_summary.png"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    summary = build_summary(project_root)
    output_png = args.output_png
    if not output_png.is_absolute():
        output_png = project_root / output_png
    render(summary, output_png)
    print(output_png)


if __name__ == "__main__":
    main()
