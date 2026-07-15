"""无第三方绘图库依赖的轻量 SVG 图表。"""

from __future__ import annotations

from html import escape
from pathlib import Path


def svg_document(width: int, height: int, content: list[str]) -> str:
    return "\n".join(
        [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}">'
            ),
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#222}'
            ".axis{stroke:#444;stroke-width:1}.grid{stroke:#ddd;stroke-width:1}"
            ".small{font-size:12px}.label{font-size:13px}"
            ".title{font-size:20px;font-weight:600}</style>",
            *content,
            "</svg>",
            "",
        ]
    )


def write_grouped_bar_svg(
    path: Path,
    *,
    labels: list[str],
    series: list[tuple[str, list[float], str]],
    title: str,
    y_label: str,
    y_max: float | None = None,
    annotations: list[str] | None = None,
    width: int = 900,
    height: int = 500,
    rotate_labels: bool = False,
    show_values: bool = True,
) -> None:
    """写一个带图例、数值标签和可选注释的分组柱状图。"""

    left, right, top = 85, 30, 75
    bottom = 125 if rotate_labels else 90
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = y_max or max(
        (value for _, values, _ in series for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1e-9)
    content = [
        (f'<text x="{width / 2}" y="32" text-anchor="middle" class="title">{escape(title)}</text>'),
        (
            f'<text x="18" y="{top + plot_height / 2}" text-anchor="middle" '
            f'transform="rotate(-90 18 {top + plot_height / 2})" class="label">'
            f"{escape(y_label)}</text>"
        ),
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = top + plot_height * (1 - tick / 5)
        content.extend(
            [
                (
                    f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" '
                    f'y2="{y:.1f}" class="grid"/>'
                ),
                (
                    f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" '
                    f'class="small">{value:.2f}</text>'
                ),
            ]
        )
    content.extend(
        [
            (f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis"/>'),
            (
                f'<line x1="{left}" y1="{top + plot_height}" '
                f'x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>'
            ),
        ]
    )
    group_width = plot_width / max(len(labels), 1)
    bar_width = min(46.0, group_width * 0.72 / max(len(series), 1))
    for label_index, label in enumerate(labels):
        center = left + group_width * (label_index + 0.5)
        total_width = bar_width * len(series)
        for series_index, (_, values, color) in enumerate(series):
            value = float(values[label_index])
            bar_height = plot_height * max(0.0, value) / maximum
            x = center - total_width / 2 + series_index * bar_width
            y = top + plot_height - bar_height
            content.extend(
                [
                    (
                        f'<rect x="{x + 1:.1f}" y="{y:.1f}" '
                        f'width="{bar_width - 2:.1f}" height="{bar_height:.1f}" '
                        f'fill="{color}" rx="2"/>'
                    ),
                ]
            )
            if show_values:
                content.append(
                    f'<text x="{x + bar_width / 2:.1f}" '
                    f'y="{max(top + 11, y - 4):.1f}" text-anchor="middle" '
                    f'class="small">{value:.2f}</text>'
                )
        label_y = top + plot_height + 24
        label_transform = (
            f' transform="rotate(45 {center:.1f} {label_y:.1f})"' if rotate_labels else ""
        )
        label_anchor = "start" if rotate_labels else "middle"
        content.append(
            f'<text x="{center:.1f}" y="{label_y:.1f}" '
            f'text-anchor="{label_anchor}"{label_transform} '
            f'class="label">{escape(label)}</text>'
        )
        if annotations:
            content.append(
                f'<text x="{center:.1f}" y="{top + plot_height + 45}" '
                f'text-anchor="middle" class="small">'
                f"{escape(annotations[label_index])}</text>"
            )
    legend_x = left
    for name, _, color in series:
        content.extend(
            [
                f'<rect x="{legend_x}" y="47" width="14" height="14" fill="{color}" rx="2"/>',
                f'<text x="{legend_x + 20}" y="59" class="small">{escape(name)}</text>',
            ]
        )
        legend_x += 20 + max(100, len(name) * 7)
    path.write_text(svg_document(width, height, content), encoding="utf-8")


def write_stacked_bar_svg(
    path: Path,
    *,
    labels: list[str],
    series: list[tuple[str, list[float], str]],
    title: str,
    y_label: str,
    y_max: float = 1.0,
    width: int = 1600,
    height: int = 560,
    rotate_labels: bool = True,
) -> None:
    """写堆叠柱状图；适合展示多病例的风险颜色构成。"""

    left, right, top = 85, 30, 75
    bottom = 125 if rotate_labels else 90
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max(float(y_max), 1e-9)
    content = [
        f'<text x="{width / 2}" y="32" text-anchor="middle" '
        f'class="title">{escape(title)}</text>',
        (
            f'<text x="18" y="{top + plot_height / 2}" text-anchor="middle" '
            f'transform="rotate(-90 18 {top + plot_height / 2})" class="label">'
            f"{escape(y_label)}</text>"
        ),
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = top + plot_height * (1 - tick / 5)
        content.extend(
            [
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" '
                f'y2="{y:.1f}" class="grid"/>',
                f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" '
                f'class="small">{value:.1%}</text>',
            ]
        )
    content.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" '
            f'y2="{top + plot_height}" class="axis"/>',
            f'<line x1="{left}" y1="{top + plot_height}" '
            f'x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>',
        ]
    )
    group_width = plot_width / max(len(labels), 1)
    bar_width = max(3.0, min(30.0, group_width * 0.72))
    for label_index, label in enumerate(labels):
        center = left + group_width * (label_index + 0.5)
        cumulative = 0.0
        for _, values, color in series:
            value = max(0.0, float(values[label_index]))
            bar_height = plot_height * value / maximum
            y = top + plot_height - (cumulative + value) / maximum * plot_height
            content.append(
                f'<rect x="{center - bar_width / 2:.1f}" y="{y:.1f}" '
                f'width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{color}"/>'
            )
            cumulative += value
        label_y = top + plot_height + 24
        label_transform = (
            f' transform="rotate(45 {center:.1f} {label_y:.1f})"' if rotate_labels else ""
        )
        label_anchor = "start" if rotate_labels else "middle"
        content.append(
            f'<text x="{center:.1f}" y="{label_y:.1f}" '
            f'text-anchor="{label_anchor}"{label_transform} '
            f'class="small">{escape(label)}</text>'
        )
    legend_x = left
    for name, _, color in series:
        content.extend(
            [
                f'<rect x="{legend_x}" y="47" width="14" height="14" '
                f'fill="{color}" rx="2"/>',
                f'<text x="{legend_x + 20}" y="59" class="small">{escape(name)}</text>',
            ]
        )
        legend_x += 20 + max(100, len(name) * 7)
    path.write_text(svg_document(width, height, content), encoding="utf-8")


def write_line_svg(
    path: Path,
    *,
    curves: list[tuple[str, list[tuple[float, float]], str]],
    title: str,
    x_label: str,
    y_label: str,
) -> None:
    """写多条 [0,1] coverage 的折线图。"""

    width, height = 900, 520
    left, right, top, bottom = 90, 35, 75, 80
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_max = max((y for _, points, _ in curves for _, y in points), default=1.0)
    y_max = max(y_max * 1.1, 0.05)
    content = [
        (f'<text x="{width / 2}" y="32" text-anchor="middle" class="title">{escape(title)}</text>'),
        (
            f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" '
            f'class="label">{escape(x_label)}</text>'
        ),
        (
            f'<text x="20" y="{top + plot_height / 2}" text-anchor="middle" '
            f'transform="rotate(-90 20 {top + plot_height / 2})" class="label">'
            f"{escape(y_label)}</text>"
        ),
    ]
    for tick in range(6):
        fraction = tick / 5
        x = left + plot_width * fraction
        y = top + plot_height * (1 - fraction)
        content.extend(
            [
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
                f'y2="{top + plot_height}" class="grid"/>',
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" '
                f'y2="{y:.1f}" class="grid"/>',
                f'<text x="{x:.1f}" y="{top + plot_height + 22}" '
                f'text-anchor="middle" class="small">{fraction:.1f}</text>',
                f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" '
                f'class="small">{y_max * fraction:.2f}</text>',
            ]
        )
    for curve_index, (name, points, color) in enumerate(curves):
        coordinates = " ".join(
            f"{left + plot_width * x:.1f},{top + plot_height * (1 - y / y_max):.1f}"
            for x, y in points
        )
        content.append(
            f'<polyline points="{coordinates}" fill="none" stroke="{color}" '
            'stroke-width="2.5" stroke-linejoin="round"/>'
        )
        legend_x = left + curve_index * 120
        content.extend(
            [
                f'<line x1="{legend_x}" y1="52" x2="{legend_x + 22}" '
                f'y2="52" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 28}" y="57" class="small">{escape(name)}</text>',
            ]
        )
    content.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis"/>',
            f'<line x1="{left}" y1="{top + plot_height}" '
            f'x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>',
        ]
    )
    path.write_text(svg_document(width, height, content), encoding="utf-8")
