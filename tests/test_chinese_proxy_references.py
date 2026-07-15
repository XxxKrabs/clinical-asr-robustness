from __future__ import annotations

import json
from pathlib import Path

from scripts.build_chinese_proxy_references import (
    parse_proxy_payload,
    source_paths_by_case,
)


def test_parse_proxy_payload_accepts_strict_json() -> None:
    payload = parse_proxy_payload(
        json.dumps(
            {
                "clean_transcript": "患者说手抖。",
                "key_facts": [
                    {
                        "category": "symptom",
                        "text": "手抖",
                        "polarity": "present",
                        "criticality": "important",
                        "evidence_terms": ["手抖"],
                    }
                ],
                "uncertainty_notes": ["药名听辨不确定"],
            },
            ensure_ascii=False,
        )
    )

    assert payload.clean_transcript == "患者说手抖。"
    assert payload.key_facts[0].evidence_terms == ["手抖"]


def test_source_paths_by_case_requires_all_three_sources(tmp_path: Path) -> None:
    source_rows = []
    suffixes = (
        "04_推荐的说话人与信息来源转录.txt",
        "02_有医疗先验/Qwen3-ASR.txt",
        "02_有医疗先验/Paraformer中文.txt",
    )
    for index, suffix in enumerate(suffixes):
        path = tmp_path / f"source_{index}.txt"
        path.write_text("示例", encoding="utf-8")
        source_rows.append(
            {
                "asset_group": "raw_review_package",
                "case_id": "case_0001",
                "extension": ".txt",
                "relative_path": str(path).replace("\\", "/") + "/" + suffix,
            }
        )

    # 测试只关心唯一后缀匹配；返回路径不必在本例中实际打开。
    result = source_paths_by_case(source_rows, case_ids=["case_0001"])

    assert [name for name, _ in result["case_0001"]] == [
        "recommended_speaker_source",
        "qwen3_asr_medical_prior",
        "paraformer_medical_prior",
    ]
