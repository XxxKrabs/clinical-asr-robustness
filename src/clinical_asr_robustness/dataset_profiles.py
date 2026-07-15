"""中英文 ASR 数据集的轻量配置与自动路由。

项目当前只维护 PriMock57 和真实中文远程程控 40 例两条数据路径。这里集中保存
两者真正不同的参数；ASR、置信度、候选、审阅和反馈仍复用同一套流水线。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRIMOCK57 = "primock57"
REMOTE_PROGRAMMING_40 = "remote_programming_40"


@dataclass(frozen=True)
class DatasetProfile:
    """一个数据集在共享 ASR 主线中的少量差异参数。"""

    dataset_id: str
    aliases: tuple[str, ...]
    language: str
    text_unit_mode: str
    default_manifest: Path
    default_model_path: Path
    output_root: Path
    default_audio_window_sec: float | None
    confidence_policy: str
    word_confidence_source: str
    save_frame_distributions: bool
    llm_candidate_prompt_profile: str
    llm_candidate_context_scope: str
    medical_candidate_lexicon_path: Path
    run_llm_candidates_default: bool

    def output_path(self, task_dir: str, filename: str) -> Path:
        return self.output_root / task_dir / filename


DATASET_PROFILES: dict[str, DatasetProfile] = {
    PRIMOCK57: DatasetProfile(
        dataset_id=PRIMOCK57,
        aliases=("primock", "primock57", "en", "english"),
        language="en",
        text_unit_mode="whitespace",
        default_manifest=Path(
            "data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl"
        ),
        default_model_path=Path(
            "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
        ),
        output_root=Path("outputs/primock57"),
        default_audio_window_sec=120.0,
        confidence_policy="fixed_thresholds",
        word_confidence_source="nemo_word_confidence",
        save_frame_distributions=False,
        llm_candidate_prompt_profile="generic_clinical_asr_v1",
        llm_candidate_context_scope="local_window",
        medical_candidate_lexicon_path=Path(
            "configs/medical_candidate_lexicon.example.json"
        ),
        run_llm_candidates_default=False,
    ),
    REMOTE_PROGRAMMING_40: DatasetProfile(
        dataset_id=REMOTE_PROGRAMMING_40,
        aliases=(
            "remote_programming_40",
            "remote-programming-40",
            "remote40",
            "zh",
            "chinese",
        ),
        language="zh-CN",
        text_unit_mode="auto",
        default_manifest=Path(
            "data/interim/remote_programming_40/manifests/"
            "remote_programming_40_asr_16k_windows.jsonl"
        ),
        default_model_path=Path(
            "data/external/asr_models/nemo/"
            "Parakeet-Hybrid-XL-unified-0.6b_spe7k_zh-en-CN_3.0.nemo"
        ),
        output_root=Path("outputs/remote_programming_40"),
        default_audio_window_sec=30.0,
        confidence_policy="demo_quantile_v0",
        word_confidence_source="ctc_frame_distribution",
        save_frame_distributions=True,
        llm_candidate_prompt_profile="zh_dbs_remote_programming_v1",
        llm_candidate_context_scope="complete_consultation",
        medical_candidate_lexicon_path=Path(
            "configs/medical_candidate_lexicon.remote_programming_40.json"
        ),
        run_llm_candidates_default=True,
    ),
}


def normalize_dataset_id(value: str) -> str:
    normalized = value.strip().casefold().replace(" ", "_")
    for profile in DATASET_PROFILES.values():
        if normalized == profile.dataset_id.casefold():
            return profile.dataset_id
        if normalized in {alias.casefold() for alias in profile.aliases}:
            return profile.dataset_id
    raise ValueError(
        f"未知数据集 {value!r}；当前支持：{', '.join(sorted(DATASET_PROFILES))}"
    )


def dataset_id_from_records(records: Iterable[dict[str, Any]]) -> str | None:
    ids = {
        normalize_dataset_id(str(record["dataset"]))
        for record in records
        if record.get("dataset")
    }
    if not ids:
        return None
    if len(ids) != 1:
        raise ValueError(f"同一个 ASR manifest 不能混用多个数据集：{sorted(ids)}")
    return next(iter(ids))


def dataset_id_from_manifest(path: Path) -> str | None:
    if not path.exists():
        return None
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"manifest 每行必须是 JSON object：{path}")
            records.append(payload)
            if len(records) >= 20:
                break
    return dataset_id_from_records(records)


def infer_dataset_id(
    *,
    dataset: str | None = None,
    manifest_path: Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
) -> str:
    """按显式值、manifest 内容、路径提示依次推断；最终兼容性回退到英文主线。"""

    if dataset and dataset.casefold() != "auto":
        return normalize_dataset_id(dataset)
    if records is not None:
        inferred = dataset_id_from_records(records)
        if inferred:
            return inferred
    if manifest_path is not None:
        inferred = dataset_id_from_manifest(manifest_path)
        if inferred:
            return inferred
        path_hint = manifest_path.as_posix().casefold()
        if "remote_programming_40" in path_hint:
            return REMOTE_PROGRAMMING_40
        if "primock57" in path_hint:
            return PRIMOCK57
    return PRIMOCK57


def resolve_dataset_profile(
    *,
    dataset: str | None = None,
    manifest_path: Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
) -> DatasetProfile:
    return DATASET_PROFILES[
        infer_dataset_id(
            dataset=dataset,
            manifest_path=manifest_path,
            records=records,
        )
    ]
