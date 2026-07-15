"""把全量 review samples 拆成一例一页，并生成轻量索引。

单文件嵌入 40 例会过大；该入口复用同一 T036 交互 HTML，为每个匿名 consultation 生成独立
页面，保留 localStorage 与反馈 JSONL 下载能力。页面仍是研究工具，不提供临床建议。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from clinical_asr_robustness.review_workflow import (
    ReviewSample,
    build_review_html,
    read_review_samples_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--index-html", type=Path, required=True)
    parser.add_argument("--run-summary-json", type=Path, required=True)
    parser.add_argument("--title", default="中文 40 例 ASR 置信度交互审阅")
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sample_case_id(sample: ReviewSample) -> str:
    if sample.consultation_id:
        return sample.consultation_id
    for part in sample.sample_id.split(":"):
        if part.startswith("case_"):
            return part
    raise ValueError(f"无法从 review sample 解析匿名 case id：{sample.sample_id}")


def consultation_duration_min(samples: list[ReviewSample]) -> float:
    starts: list[float] = []
    ends: list[float] = []
    for sample in samples:
        source_metadata = sample.metadata.get("source_record_metadata")
        if not isinstance(source_metadata, dict):
            continue
        source_manifest = source_metadata.get("source_manifest")
        if not isinstance(source_manifest, dict):
            continue
        if source_manifest.get("source_start_sec") is not None:
            starts.append(float(source_manifest["source_start_sec"]))
        if source_manifest.get("source_end_sec") is not None:
            ends.append(float(source_manifest["source_end_sec"]))
    if starts and ends:
        return max(0.0, max(ends) - min(starts)) / 60
    return max((float(sample.duration_sec or 0.0) for sample in samples), default=0.0) / 60


def build_index_html(
    *,
    title: str,
    case_rows: list[dict[str, Any]],
) -> str:
    rows = []
    for row in case_rows:
        cells = [
            f'<td><a href="pages/{escape(row["filename"])}">'
            f'{escape(row["case_id"])}</a></td>',
            f'<td>{row["window_count"]}</td>',
            f'<td>{row["span_count"]}</td>',
            f'<td>{row["candidate_span_count"]}</td>',
            f'<td>{row["duration_min"]:.1f}</td>',
        ]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{
  margin:0;background:#f5f7fa;color:#172b4d;
  font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif
}}
main{{max-width:1000px;margin:auto;padding:30px 20px 60px}}h1{{color:#183153}}
.warning{{background:#fff7ed;border-left:5px solid #d97706;padding:12px 16px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #d9e2ec}}
th,td{{padding:10px 12px;border-bottom:1px solid #e3e8ee;text-align:right}}
th:first-child,td:first-child{{text-align:left}}th{{background:#edf2f7}}a{{color:#1358a2}}
</style></head><body><main>
<h1>{escape(title)}</h1>
<p class="warning">每页一例，反馈保存在该页浏览器 localStorage 并可下载 JSONL。
未听音频的自动 QA 或 LLM 结果不代表医生确认；研究输出不构成临床建议。</p>
<table><thead><tr><th>case</th><th>windows</th><th>review spans</th>
<th>spans with candidates</th><th>minutes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""


def main() -> None:
    args = parse_args()
    review_path = resolve_project_path(args.review_jsonl)
    output_dir = resolve_project_path(args.output_dir)
    index_path = resolve_project_path(args.index_html)
    run_path = resolve_project_path(args.run_summary_json)
    samples = read_review_samples_jsonl(review_path)
    groups: dict[str, list[ReviewSample]] = defaultdict(list)
    for sample in samples:
        groups[sample_case_id(sample)].append(sample)
    output_dir.mkdir(parents=True, exist_ok=True)
    case_rows: list[dict[str, Any]] = []
    for case_id, case_samples in sorted(groups.items()):
        filename = f"{case_id}.html"
        page_path = output_dir / filename
        page_path.write_text(
            build_review_html(
                case_samples,
                title=f"{args.title} · {case_id}",
                interactive=True,
                html_output_path=page_path,
                project_root=PROJECT_ROOT,
            ),
            encoding="utf-8",
            newline="\n",
        )
        spans = [span for sample in case_samples for span in sample.uncertain_spans]
        case_rows.append(
            {
                "case_id": case_id,
                "filename": filename,
                "window_count": len(case_samples),
                "span_count": len(spans),
                "candidate_span_count": sum(bool(span.alternatives) for span in spans),
                "duration_min": consultation_duration_min(case_samples),
                "page_bytes": page_path.stat().st_size,
            }
        )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        build_index_html(title=args.title, case_rows=case_rows),
        encoding="utf-8",
        newline="\n",
    )
    summary = {
        "task_id": "T061_SPLIT_REVIEW_PAGES",
        "schema_version": "split_doctor_review_pages_run/v1",
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {"review_jsonl": project_relative(review_path)},
        "outputs": {
            "index_html": project_relative(index_path),
            "pages_dir": project_relative(output_dir),
        },
        "case_count": len(case_rows),
        "sample_count": len(samples),
        "span_count": sum(row["span_count"] for row in case_rows),
        "candidate_span_count": sum(row["candidate_span_count"] for row in case_rows),
        "max_page_bytes": max((row["page_bytes"] for row in case_rows), default=0),
        "case_records": case_rows,
        "interactive_html": True,
        "human_reviewed": False,
        "research_use_only": True,
    }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
