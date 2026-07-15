"""批量导出 NeMo entropy confidence ASR JSONL（T028）。

默认输入为 T025 生成的 PriMock57 channel-level manifest，默认输出到
`outputs/primock57/t028_nemo_asr_confidence/`。输出目录默认不纳入 Git。

脚本只保存 ASR 输出、置信度、时间戳、配置和文件指针；不会读取或内联
TextGrid reference 正文、notes 正文或真实患者信息。
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import re
import sys
import tempfile
import time
import traceback
import wave
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    DEFAULT_GREEN_MIN,
    DEFAULT_YELLOW_MIN,
    AlignmentDiagnostics,
    ASRConfidenceConfig,
    ASRConfidenceRecord,
    ASRDecodingConfig,
    ASRModelInfo,
    ConfidenceLevel,
    ConfidenceThresholds,
    confidence_level_for_score,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.ctc_word_confidence import (
    compute_ctc_word_confidence,
    frame_scores_from_hypothesis,
    normalize_frame_scores,
    save_ctc_frame_distribution_artifact,
    word_confidence_metadata,
)
from clinical_asr_robustness.dataset_profiles import resolve_dataset_profile
from clinical_asr_robustness.nemo_confidence_export import (
    aggregate_confidences,
    apply_demo_quantile_risk_levels,
    build_asr_confidence_record,
    build_segments_from_words,
    build_uncertain_spans_from_words,
    configure_ctc_greedy_confidence,
    flatten_transcription_results,
    summarize_confidence_values,
    to_jsonable,
    transcript_units_for_hypothesis,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data/interim/primock57/manifests/primock57_nemo_asr_input_manifest.jsonl"
)
DEFAULT_MODEL = (
    PROJECT_ROOT / "data/external/asr_models/nemo/stt_en_fastconformer_ctc_large.nemo"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs/primock57/t028_nemo_asr_confidence"
DEFAULT_OUTPUT_JSONL = DEFAULT_OUTPUT_DIR / "primock57_asr_confidence.jsonl"
DEFAULT_RUN_CONFIG = DEFAULT_OUTPUT_DIR / "t028_nemo_asr_confidence_run.json"
INTERNAL_NEMO_ROOT = PROJECT_ROOT / "third_party/speech_main"


def is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path.is_relative_to。"""

    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def path_for_record(path: Path, project_root: Path = PROJECT_ROOT) -> str:
    """输出相对 project root 的 POSIX 风格路径；无法相对化时保留绝对路径。"""

    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(path_value: str | Path) -> Path:
    """将 manifest/CLI 中的相对路径解析到 project root。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL manifest。"""

    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在：{path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"manifest 第 {line_number} 行不是合法 JSON：{path}") from exc
    if not records:
        raise ValueError(f"manifest 为空：{path}")
    return records


def select_manifest_records(
    records: list[dict[str, Any]],
    *,
    sample_ids: list[str] | None,
    record_indices: list[int] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """按 sample_id / index / limit 选择待转写记录。"""

    selected = records
    if sample_ids:
        wanted = set(sample_ids)
        selected = [record for record in selected if record.get("sample_id") in wanted]
        found = {record.get("sample_id") for record in selected}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(f"manifest 中找不到指定 sample_id：{missing}")

    if record_indices:
        indexed: list[dict[str, Any]] = []
        for index in record_indices:
            if index < 0 or index >= len(records):
                raise IndexError(f"record index 越界：{index}，manifest 共 {len(records)} 条")
            indexed.append(records[index])
        selected = indexed

    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit 必须大于 0")
        selected = selected[:limit]

    if not selected:
        raise ValueError("筛选后没有待转写记录")
    return selected


def total_manifest_audio_duration_sec(records: list[dict[str, Any]]) -> float:
    """按实际 ASR 输入记录累计时长，避免审阅侧原始整段时长被重复计算。"""

    total = 0.0
    for record in records:
        value = record.get("duration", record.get("duration_sec"))
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            total += duration
    return total


def find_external_speech_main_paths(paths: list[str | None]) -> list[str]:
    """找出疑似 project 外部 Speech-main 路径。"""

    external_paths: list[str] = []
    for value in paths:
        if not value:
            continue
        normalized = str(value).replace("\\", "/")
        lower = normalized.lower()
        if "speech-main" not in lower and "speech_main" not in lower:
            continue
        path = Path(value)
        if is_relative_to(path, PROJECT_ROOT):
            continue
        external_paths.append(value)
    return sorted(set(external_paths))


def ensure_project_nemo_on_path() -> None:
    """优先从 project 内 `third_party/speech_main` 导入 NeMo。"""

    if INTERNAL_NEMO_ROOT.exists():
        internal_path = str(INTERNAL_NEMO_ROOT)
        if internal_path not in sys.path:
            sys.path.insert(0, internal_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="auto")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--run-config-json", type=Path, default=None)
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument(
        "--precision",
        choices=["auto", "fp32", "fp16", "bf16"],
        default="auto",
        help="推理 autocast 精度；auto 在 CUDA 使用 fp16，在 CPU 使用 fp32。",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--transcribe-chunk-size", type=int, default=1)
    parser.add_argument(
        "--audio-window-sec",
        type=float,
        default=None,
        help=(
            "可选：将单路长音频切成不超过 N 秒的临时 wav 窗口逐段转写，"
            "再把词级时间戳平移合并回原始 channel。用于 8GB 显存下避免长音频 OOM。"
        ),
    )
    parser.add_argument(
        "--audio-window-temp-dir",
        type=Path,
        default=None,
        help="音频窗口临时目录；默认位于 output-jsonl 同级 tmp_audio_windows/。",
    )
    parser.add_argument(
        "--confidence-aggregation",
        choices=["mean", "min", "max", "prod"],
        default="mean",
        help="NeMo frame/token 到 word confidence 的聚合方式。",
    )
    parser.add_argument(
        "--confidence-method",
        choices=["entropy", "max_prob"],
        default="entropy",
        help=(
            "NeMo frame-level confidence 方法。entropy 对应论文的归一化负熵；"
            "max_prob 可作为 sanity-check baseline。"
        ),
    )
    parser.add_argument(
        "--entropy-type",
        choices=["gibbs", "tsallis", "renyi"],
        default="tsallis",
        help="--confidence-method entropy 时使用的 entropy 类型。",
    )
    parser.add_argument(
        "--entropy-norm",
        choices=["lin", "exp"],
        default="lin",
        help="--confidence-method entropy 时把 entropy 映射到 [0,1] 的方式。",
    )
    parser.add_argument(
        "--confidence-alpha",
        type=float,
        default=0.33,
        help="论文 entropy/max_prob confidence 的 alpha/temperature 参数。",
    )
    parser.add_argument(
        "--word-confidence-source",
        choices=["auto", "nemo_word_confidence", "ctc_frame_distribution"],
        default="auto",
        help=(
            "词级置信度来源。auto 按数据集选择：PriMock57 沿用 NeMo "
            "word_confidence，中文 40 例使用辅助 CTC frame distribution；"
            "ctc_frame_distribution 会从 Hypothesis 中保存的 frame log_probs/posterior "
            "按 CTC entropy pipeline 重新聚合到 word。"
        ),
    )
    parser.add_argument(
        "--unaligned-confidence-policy",
        choices=["error", "all_red"],
        default="error",
        help=(
            "CTC frame distribution 无法对齐任何 word 时的策略。error 保持严格失败；"
            "all_red 保留 ASR 文本并把全部可枚举审阅单元置 0/red，同时写入 fallback 审计。"
        ),
    )
    parser.add_argument(
        "--save-frame-distributions",
        action="store_true",
        help="保存每条音频的 CTC frame-level log_probs/posterior artifact，便于离线复算。",
    )
    parser.add_argument(
        "--frame-distribution-kind",
        choices=["log_probs", "posterior"],
        default="log_probs",
        help="保存 artifact 时写入 log_probs 还是 posterior；NeMo CTC forward 默认返回 log_probs。",
    )
    parser.add_argument(
        "--frame-artifact-dir",
        type=Path,
        default=None,
        help="帧级分布 artifact 输出目录；默认位于 output-jsonl 同级 ctc_frame_distributions/。",
    )
    parser.add_argument(
        "--threshold-policy",
        choices=["auto", "fixed_thresholds", "demo_quantile_v0"],
        default="auto",
        help=(
            "auto：PriMock57 保持固定阈值，中文 40 例使用未校准 demo_quantile_v0。"
        ),
    )
    parser.add_argument(
        "--green-min",
        type=float,
        default=DEFAULT_GREEN_MIN,
        help="绿色下界；当前 PriMock57/NeMo word confidence 默认 0.90。",
    )
    parser.add_argument(
        "--yellow-min",
        type=float,
        default=DEFAULT_YELLOW_MIN,
        help="黄色下界（低于此值为红色）；当前默认 0.80。",
    )
    parser.add_argument("--segment-max-words", type=int, default=40)
    parser.add_argument("--segment-max-gap-sec", type=float, default=1.5)
    parser.add_argument(
        "--allow-nemo-outside-project",
        action="store_true",
        help="默认要求 nemo 来自 project/third_party/speech_main；仅调试时放宽。",
    )
    args = parser.parse_args()
    manifest_hint = resolve_project_path(args.manifest) if args.manifest else None
    profile = resolve_dataset_profile(
        dataset=args.dataset,
        manifest_path=manifest_hint,
    )
    args.dataset = profile.dataset_id
    args.dataset_language = profile.language
    args.text_unit_mode = profile.text_unit_mode
    if args.word_confidence_source == "auto":
        args.word_confidence_source = profile.word_confidence_source
    if args.threshold_policy == "auto":
        args.threshold_policy = profile.confidence_policy
    if args.manifest is None:
        args.manifest = profile.default_manifest
    if args.model_path is None:
        args.model_path = profile.default_model_path
    if args.output_jsonl is None:
        args.output_jsonl = profile.output_path(
            "t028_nemo_asr_confidence",
            f"{profile.dataset_id}_asr_confidence.jsonl",
        )
    if args.run_config_json is None:
        args.run_config_json = profile.output_path(
            "t028_nemo_asr_confidence",
            "t028_nemo_asr_confidence_run.json",
        )
    return args


def validate_input_files(records: list[dict[str, Any]], model_path: Path) -> list[Path]:
    """检查模型和待处理音频文件存在。"""

    if not model_path.exists():
        raise FileNotFoundError(f"模型权重不存在：{model_path}")

    audio_paths: list[Path] = []
    for record in records:
        audio_value = record.get("audio_filepath") or record.get("audio_path")
        if not audio_value:
            raise ValueError(f"manifest 记录缺少 audio_filepath/audio_path：{record}")
        audio_path = resolve_project_path(audio_value)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频不存在：{audio_path}")
        audio_paths.append(audio_path)
    return audio_paths


def chunked(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """按固定大小切分列表。"""

    if chunk_size <= 0:
        raise ValueError("--transcribe-chunk-size 必须大于 0")
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def run_export(args: argparse.Namespace) -> tuple[list[Any], dict[str, Any]]:
    """执行批量 ASR confidence 导出。"""

    run_started = time.perf_counter()
    manifest_path = resolve_project_path(args.manifest)
    model_path = resolve_project_path(args.model_path)
    output_jsonl = resolve_project_path(args.output_jsonl)

    manifest_records = load_jsonl_records(manifest_path)
    selected_records = select_manifest_records(
        manifest_records,
        sample_ids=args.sample_ids,
        record_indices=args.record_index,
        limit=args.limit,
    )
    record_datasets = {
        str(record.get("dataset")) for record in selected_records if record.get("dataset")
    }
    if record_datasets and record_datasets != {args.dataset}:
        raise ValueError(
            f"CLI/自动路由数据集 {args.dataset} 与 manifest 不一致：{sorted(record_datasets)}"
        )
    for record in selected_records:
        record.setdefault("text_unit_mode", args.text_unit_mode)
    audio_paths = validate_input_files(selected_records, model_path)

    ensure_project_nemo_on_path()

    import nemo
    import nemo.collections.asr as nemo_asr
    import torch
    from nemo.collections.asr.models import ASRModel
    from nemo.collections.asr.parts.mixins.transcription import TranscribeConfig

    nemo_module_paths = [
        getattr(nemo, "__file__", None),
        getattr(nemo_asr, "__file__", None),
    ]
    external_paths = find_external_speech_main_paths(sys.path + nemo_module_paths)
    nemo_paths_inside_project = [
        path is not None and is_relative_to(Path(path), INTERNAL_NEMO_ROOT)
        for path in nemo_module_paths
    ]
    if external_paths:
        raise RuntimeError(f"检测到 project 外部 Speech-main 路径：{external_paths}")
    if not args.allow_nemo_outside_project and not all(nemo_paths_inside_project):
        raise RuntimeError(
            "nemo 未从 project/third_party/speech_main 导入；"
            f"当前模块路径：{nemo_module_paths}"
        )

    cuda_available = torch.cuda.is_available()
    if args.device == "auto":
        device = "cuda" if cuda_available else "cpu"
    else:
        device = args.device
    if device == "cuda" and not cuda_available:
        raise RuntimeError("指定 --device cuda，但 torch.cuda.is_available() 为 False")
    precision = args.precision
    if precision == "auto":
        precision = "fp16" if device == "cuda" else "fp32"
    if device != "cuda" and precision in {"fp16", "bf16"}:
        raise ValueError("CPU smoke test 当前只支持 fp32 precision")

    restore_started = time.perf_counter()
    model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
    model.to(device)
    model.eval()
    restore_elapsed_sec = time.perf_counter() - restore_started
    decoding_config = configure_ctc_greedy_confidence(
        model,
        method_name=args.confidence_method,
        entropy_type=args.entropy_type,
        alpha=args.confidence_alpha,
        entropy_norm=args.entropy_norm,
        aggregation=args.confidence_aggregation,
    )

    thresholds = ConfidenceThresholds(
        green_min=args.green_min,
        yellow_min=args.yellow_min,
    )
    confidence_source_field = (
        "ctc_frame_distribution.word_confidence"
        if args.word_confidence_source == "ctc_frame_distribution"
        else "word_confidence"
    )
    confidence_config = ASRConfidenceConfig(
        method_name=args.confidence_method,
        entropy_type=args.entropy_type if args.confidence_method == "entropy" else None,
        alpha=args.confidence_alpha,
        entropy_norm=args.entropy_norm if args.confidence_method == "entropy" else None,
        aggregation=args.confidence_aggregation,
        preserve_frame_confidence=True,
        preserve_token_confidence=True,
        preserve_word_confidence=True,
        source_field=confidence_source_field,
        thresholds=thresholds,
        metadata={
            "note": (
                "Values are normalized confidence scores in [0,1]. Thresholds should be "
                "calibrated per model/dataset before clinical-style review."
            ),
            "word_confidence_source": args.word_confidence_source,
            "ctc_frame_pipeline": (
                "frame log_probs/posterior -> frame entropy confidence -> CTC token "
                "aggregation -> word confidence"
            ),
        },
    )
    runtime = {
        "device": device,
        "precision": precision,
        "restore_elapsed_sec": restore_elapsed_sec,
        "torch_version": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
        "nemo_path": nemo_module_paths[0],
        "nemo_asr_path": nemo_module_paths[1],
        "external_speech_main_paths": external_paths,
        "nemo_paths_inside_project": nemo_paths_inside_project,
    }
    model_info = ASRModelInfo(
        provider="nemo",
        model_name=model_path.stem,
        model_path=path_for_record(model_path),
        model_class=f"{model.__class__.__module__}.{model.__class__.__name__}",
        language=args.dataset_language,
        metadata={
            "dataset_route": args.dataset,
            "text_unit_mode": args.text_unit_mode,
            "decoder_type": decoding_config.get("project_decoder_type"),
        },
    )
    decoding = ASRDecodingConfig(
        strategy="greedy",
        batch_size=args.batch_size,
        device=device,
        timestamps_enabled=True,
        return_hypotheses=True,
        config=decoding_config,
        metadata={
            "num_workers": args.num_workers,
            "transcribe_chunk_size": args.transcribe_chunk_size,
        },
    )

    transcribe_config = TranscribeConfig(
        use_lhotse=False,
        batch_size=args.batch_size,
        return_hypotheses=True,
        num_workers=args.num_workers,
        timestamps=True,
        verbose=False,
    )

    generated_at_utc = datetime.now(timezone.utc)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    transcribe_started = time.perf_counter()
    output_records = []
    processed = 0
    frame_artifact_dir = (
        resolve_project_path(args.frame_artifact_dir)
        if args.frame_artifact_dir is not None
        else output_jsonl.parent / "ctc_frame_distributions"
    )
    should_compute_ctc_word_confidence = (
        args.word_confidence_source == "ctc_frame_distribution"
        or args.save_frame_distributions
    )
    ctc_artifacts_saved = 0
    ctc_word_alignment_status_counts: dict[str, int] = {}
    ctc_unaligned_fallbacks: list[dict[str, Any]] = []
    audio_window_summaries: list[dict[str, Any]] = []
    if args.audio_window_sec is not None:
        if args.audio_window_sec <= 0:
            raise ValueError("--audio-window-sec 必须大于 0")
        if should_compute_ctc_word_confidence:
            raise ValueError(
                "--audio-window-sec 当前仅支持 NeMo 原生 word confidence；"
                "请不要同时使用 --word-confidence-source ctc_frame_distribution "
                "或 --save-frame-distributions。"
            )
        audio_window_temp_root = (
            resolve_project_path(args.audio_window_temp_dir)
            if args.audio_window_temp_dir is not None
            else output_jsonl.parent / "tmp_audio_windows"
        )
        audio_window_temp_root.mkdir(parents=True, exist_ok=True)
        for manifest_record, audio_path in zip(selected_records, audio_paths, strict=True):
            output_record, window_summary = transcribe_record_with_audio_windows(
                model=model,
                manifest_record=manifest_record,
                audio_path=audio_path,
                model_info=model_info,
                decoding=decoding,
                confidence_config=confidence_config,
                runtime=runtime,
                generated_at_utc=generated_at_utc,
                transcribe_config=transcribe_config,
                window_sec=args.audio_window_sec,
                temp_root=audio_window_temp_root,
                segment_max_words=args.segment_max_words,
                segment_max_gap_sec=args.segment_max_gap_sec,
                torch_module=torch,
            )
            output_records.append(output_record)
            audio_window_summaries.append(window_summary)
            processed += 1
            print(f"[{processed}/{len(selected_records)}] {manifest_record.get('sample_id')}")
        write_asr_confidence_jsonl(output_records, output_jsonl)
    else:
        for record_chunk, audio_chunk in zip(
            chunked(selected_records, args.transcribe_chunk_size),
            chunked(audio_paths, args.transcribe_chunk_size),
            strict=True,
        ):
            with autocast_context(torch, device=device, precision=precision):
                transcription_result = model.transcribe(
                    audio=[str(path) for path in audio_chunk],
                    override_config=transcribe_config,
                )
            hypotheses = flatten_transcription_results(transcription_result)
            if len(hypotheses) != len(record_chunk):
                raise RuntimeError(
                    "NeMo 返回 hypothesis 数量与输入音频数量不一致："
                    f"{len(hypotheses)} vs {len(record_chunk)}"
                )
            for manifest_record, hypothesis in zip(record_chunk, hypotheses, strict=True):
                word_confidences_override = None
                confidence_metadata_by_word = None
                ctc_artifact_path_for_record = None
                confidence_fallback_metadata = None
                if should_compute_ctc_word_confidence:
                    frame_scores = frame_scores_from_hypothesis(hypothesis)
                    if frame_scores is None:
                        raise RuntimeError(
                            "Hypothesis 中没有二维 frame log_probs/logits；"
                            "请确认 return_hypotheses=True 且当前模型为 CTC。"
                        )
                    blank_id = resolve_ctc_blank_id(model, frame_scores)
                    token_texts_by_id = resolve_token_texts_by_id(model, frame_scores)
                    ctc_result = compute_ctc_word_confidence(
                        frame_scores,
                        score_type="log_probs",
                        blank_id=blank_id,
                        transcript=str(getattr(hypothesis, "text", "") or ""),
                        transcript_units=transcript_units_for_hypothesis(
                            str(getattr(hypothesis, "text", "") or ""),
                            hypothesis,
                            mode=str(manifest_record.get("text_unit_mode") or "whitespace"),
                        ),
                        token_texts_by_id=token_texts_by_id,
                        method_name=args.confidence_method,
                        entropy_type=args.entropy_type,
                        alpha=args.confidence_alpha,
                        entropy_norm=args.entropy_norm,
                        token_aggregation=args.confidence_aggregation,
                        word_aggregation=args.confidence_aggregation,
                    )
                    status = ctc_result.metadata["word_alignment_status"]
                    ctc_word_alignment_status_counts[status] = (
                        ctc_word_alignment_status_counts.get(status, 0) + 1
                    )
                    if args.word_confidence_source == "ctc_frame_distribution":
                        if not any(value is not None for value in ctc_result.word_confidences):
                            if args.unaligned_confidence_policy == "error":
                                raise RuntimeError(
                                    "CTC frame distribution 未能对齐出任何 word confidence；"
                                    "请检查 token_texts/blank_id 与 transcript word 对齐。"
                                )
                            word_confidences_override = [
                                0.0 for _ in ctc_result.word_confidences
                            ]
                            confidence_fallback_metadata = {
                                "policy": "all_red",
                                "reason": (
                                    "no_ctc_word_confidence_aligned"
                                    if ctc_result.word_confidences
                                    else "empty_asr_unit_sequence"
                                ),
                                "original_alignment_status": status,
                                "unit_count": len(word_confidences_override),
                                "human_review_required": True,
                            }
                            ctc_unaligned_fallbacks.append(
                                {
                                    "sample_id": manifest_record.get("sample_id"),
                                    **confidence_fallback_metadata,
                                }
                            )
                        else:
                            word_confidences_override = ctc_result.word_confidences
                    if args.save_frame_distributions:
                        sample_id = str(manifest_record.get("sample_id") or f"record_{processed}")
                        artifact_path = frame_artifact_dir / f"{safe_filename(sample_id)}.npz"
                        frame_values_to_save = frame_scores
                        value_type_to_save = "log_probs"
                        if args.frame_distribution_kind == "posterior":
                            frame_values_to_save = normalize_frame_scores(
                                frame_scores,
                                "log_probs",
                            )[0]
                            value_type_to_save = "posterior"
                        save_ctc_frame_distribution_artifact(
                            artifact_path,
                            frame_values=frame_values_to_save,
                            value_type=value_type_to_save,
                            result=ctc_result,
                            transcript=str(getattr(hypothesis, "text", "") or ""),
                            metadata={
                                "sample_id": sample_id,
                                "model_name": model_path.stem,
                                "generated_at": generated_at_utc.isoformat(timespec="seconds"),
                            },
                        )
                        ctc_artifacts_saved += 1
                        ctc_artifact_path_for_record = path_for_record(artifact_path)
                    if args.word_confidence_source == "ctc_frame_distribution":
                        confidence_metadata_by_word = word_confidence_metadata(
                            ctc_result,
                            artifact_path=ctc_artifact_path_for_record,
                        )
                        if confidence_fallback_metadata is not None:
                            confidence_metadata_by_word = [
                                {
                                    **metadata,
                                    "confidence_fallback": confidence_fallback_metadata,
                                }
                                for metadata in confidence_metadata_by_word
                            ]

                output_record = build_asr_confidence_record(
                    manifest_record=manifest_record,
                    hypothesis=hypothesis,
                    model_info=model_info,
                    decoding_config=decoding,
                    confidence_config=confidence_config,
                    runtime=runtime,
                    generated_at_utc=generated_at_utc,
                    segment_max_words=args.segment_max_words,
                    segment_max_gap_sec=args.segment_max_gap_sec,
                    word_confidences_override=word_confidences_override,
                    word_confidence_source=(
                        "ctc_frame_distribution.word_confidence"
                        if word_confidences_override is not None
                        else None
                    ),
                    word_confidence_metadata_by_index=confidence_metadata_by_word,
                )
                if confidence_fallback_metadata is not None:
                    output_record.metadata["confidence_fallback"] = (
                        confidence_fallback_metadata
                    )
                output_records.append(output_record)
                processed += 1
                print(f"[{processed}/{len(selected_records)}] {manifest_record.get('sample_id')}")
            del transcription_result
            del hypotheses
            if device == "cuda":
                torch.cuda.empty_cache()
            gc.collect()

        write_asr_confidence_jsonl(output_records, output_jsonl)
    transcribe_elapsed_sec = time.perf_counter() - transcribe_started
    total_audio_duration_sec = total_manifest_audio_duration_sec(selected_records)
    runtime.update(
        {
            "transcribe_elapsed_sec": transcribe_elapsed_sec,
            "total_elapsed_sec": time.perf_counter() - run_started,
            "total_audio_duration_sec": total_audio_duration_sec,
            "real_time_factor": (
                transcribe_elapsed_sec / total_audio_duration_sec
                if total_audio_duration_sec > 0
                else None
            ),
            "cuda_peak_memory_allocated_bytes": (
                int(torch.cuda.max_memory_allocated()) if device == "cuda" else None
            ),
            "cuda_peak_memory_reserved_bytes": (
                int(torch.cuda.max_memory_reserved()) if device == "cuda" else None
            ),
        }
    )
    for record in output_records:
        record.runtime.update(runtime)
    if args.threshold_policy == "demo_quantile_v0":
        output_records = apply_demo_quantile_risk_levels(output_records)
    for record in output_records:
        fallback = record.metadata.get("confidence_fallback")
        if not isinstance(fallback, dict) or fallback.get("policy") != "all_red":
            continue
        record.confidence_level = ConfidenceLevel.RED
        for word in record.asr_words:
            word.confidence = 0.0
            word.confidence_level = ConfidenceLevel.RED
        for segment in record.asr_segments:
            segment.confidence = 0.0
            segment.confidence_level = ConfidenceLevel.RED
        record.uncertain_spans = build_uncertain_spans_from_words(
            record.asr_words,
            thresholds=record.confidence.thresholds,
        )
        record.metadata["confidence_fallback"]["risk_override_after_policy"] = "all_red"
    write_asr_confidence_jsonl(output_records, output_jsonl)

    word_confidence_summary = summarize_confidence_values(
        word.confidence for record in output_records for word in record.asr_words
    )

    run_summary = {
        "task_id": "T028",
        "status": "ok",
        "dataset": args.dataset,
        "language": args.dataset_language,
        "threshold_policy": args.threshold_policy,
        "generated_at": generated_at_utc.isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "inputs": {
            "manifest": path_for_record(manifest_path),
            "model_path": path_for_record(model_path),
            "selected_sample_ids": [record.get("sample_id") for record in selected_records],
            "selected_records": len(selected_records),
        },
        "outputs": {
            "asr_confidence_jsonl": path_for_record(output_jsonl),
            "ctc_frame_artifact_dir": (
                path_for_record(frame_artifact_dir) if args.save_frame_distributions else None
            ),
        },
        "model": model_info.model_dump(mode="json"),
        "decoding": decoding.model_dump(mode="json"),
        "confidence": confidence_config.model_dump(mode="json"),
        "confidence_distribution": {
            "word_confidence": word_confidence_summary,
            "word_confidence_levels": _confidence_level_counts(output_records),
            "low_scale_warning": (
                word_confidence_summary["count"] > 0
                and word_confidence_summary["p99"] is not None
                and word_confidence_summary["p99"] < args.yellow_min
            ),
            "ctc_frame_distribution": {
                "computed": should_compute_ctc_word_confidence,
                "word_confidence_source": args.word_confidence_source,
                "frame_distribution_kind": args.frame_distribution_kind,
                "artifacts_saved": ctc_artifacts_saved,
                "word_alignment_status_counts": dict(
                    sorted(ctc_word_alignment_status_counts.items())
                ),
                "unaligned_confidence_policy": args.unaligned_confidence_policy,
                "unaligned_fallback_count": len(ctc_unaligned_fallbacks),
                "unaligned_fallbacks": ctc_unaligned_fallbacks,
            },
        },
        "audio_windowing": {
            "enabled": args.audio_window_sec is not None,
            "window_sec": args.audio_window_sec,
            "windowed_records": sum(
                1 for summary in audio_window_summaries if summary.get("windowed")
            ),
            "total_audio_windows": sum(
                int(summary.get("window_count", 0)) for summary in audio_window_summaries
            ),
            "record_summaries": audio_window_summaries,
        },
        "runtime": runtime,
        "validation": {
            "records_written": len(output_records),
            "no_inline_reference_text": all(
                not record.reference_text_included for record in output_records
            ),
            "all_records_have_words": all(
                record.alignment.asr_word_count > 0 for record in output_records
            ),
            "all_records_have_word_confidence": all(
                record.alignment.word_confidence_count > 0 for record in output_records
            ),
            "nemo_paths_inside_project": all(nemo_paths_inside_project),
            "external_speech_main_paths": external_paths,
        },
    }
    return output_records, run_summary


def transcribe_record_with_audio_windows(
    *,
    model: Any,
    manifest_record: dict[str, Any],
    audio_path: Path,
    model_info: ASRModelInfo,
    decoding: ASRDecodingConfig,
    confidence_config: ASRConfidenceConfig,
    runtime: dict[str, Any],
    generated_at_utc: datetime,
    transcribe_config: Any,
    window_sec: float,
    temp_root: Path,
    segment_max_words: int,
    segment_max_gap_sec: float,
    torch_module: Any,
) -> tuple[ASRConfidenceRecord, dict[str, Any]]:
    """对单路长音频分窗转写，并合并回一条 ASR confidence record。"""

    sample_id = str(manifest_record.get("sample_id") or "unknown_sample")
    duration_value = manifest_record.get("duration", manifest_record.get("duration_sec"))
    try:
        duration_sec = float(duration_value)
    except (TypeError, ValueError):
        duration_sec = None

    if duration_sec is not None and duration_sec <= window_sec:
        record = transcribe_single_record(
            model=model,
            manifest_record=manifest_record,
            audio_path=audio_path,
            model_info=model_info,
            decoding=decoding,
            confidence_config=confidence_config,
            runtime={
                **runtime,
                "audio_windowing": {"enabled": False, "reason": "duration_within_window"},
            },
            generated_at_utc=generated_at_utc,
            transcribe_config=transcribe_config,
            segment_max_words=segment_max_words,
            segment_max_gap_sec=segment_max_gap_sec,
            torch_module=torch_module,
        )
        return record, {
            "sample_id": sample_id,
            "windowed": False,
            "window_count": 1,
            "duration_sec": duration_sec,
        }

    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{safe_filename(sample_id)}_",
        dir=str(temp_root),
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        windows = split_wav_to_windows(
            audio_path,
            output_dir=temp_dir,
            window_sec=window_sec,
        )
        window_records: list[ASRConfidenceRecord] = []
        for window in windows:
            window_manifest = {
                **manifest_record,
                "sample_id": f"{sample_id}:window_{window['window_index']:04d}",
                "audio_filepath": path_for_record(window["path"]),
                "duration": window["duration_sec"],
                "duration_sec": window["duration_sec"],
            }
            window_record = transcribe_single_record(
                model=model,
                manifest_record=window_manifest,
                audio_path=window["path"],
                model_info=model_info,
                decoding=decoding,
                confidence_config=confidence_config,
                runtime={
                    **runtime,
                    "audio_windowing": {
                        "enabled": True,
                        "parent_sample_id": sample_id,
                        "window_index": window["window_index"],
                        "window_start_sec": window["start_sec"],
                        "window_end_sec": window["end_sec"],
                    },
                },
                generated_at_utc=generated_at_utc,
                transcribe_config=transcribe_config,
                segment_max_words=segment_max_words,
                segment_max_gap_sec=segment_max_gap_sec,
                torch_module=torch_module,
            )
            window_records.append(window_record)

    merged_record = merge_window_records(
        manifest_record=manifest_record,
        window_records=window_records,
        window_specs=windows,
        model_info=model_info,
        decoding=decoding,
        confidence_config=confidence_config,
        runtime=runtime,
        generated_at_utc=generated_at_utc,
        segment_max_words=segment_max_words,
        segment_max_gap_sec=segment_max_gap_sec,
        window_sec=window_sec,
    )
    return merged_record, {
        "sample_id": sample_id,
        "windowed": True,
        "window_sec": window_sec,
        "window_count": len(windows),
        "duration_sec": duration_sec,
    }


def transcribe_single_record(
    *,
    model: Any,
    manifest_record: dict[str, Any],
    audio_path: Path,
    model_info: ASRModelInfo,
    decoding: ASRDecodingConfig,
    confidence_config: ASRConfidenceConfig,
    runtime: dict[str, Any],
    generated_at_utc: datetime,
    transcribe_config: Any,
    segment_max_words: int,
    segment_max_gap_sec: float,
    torch_module: Any,
) -> ASRConfidenceRecord:
    """转写单个音频文件并返回项目 ASR confidence record。"""

    with autocast_context(
        torch_module,
        device=str(runtime.get("device") or "cpu"),
        precision=str(runtime.get("precision") or "fp32"),
    ):
        transcription_result = model.transcribe(
            audio=[str(audio_path)],
            override_config=transcribe_config,
        )
    hypotheses = flatten_transcription_results(transcription_result)
    if len(hypotheses) != 1:
        raise RuntimeError(f"NeMo 返回 hypothesis 数量异常：{len(hypotheses)}")
    record = build_asr_confidence_record(
        manifest_record=manifest_record,
        hypothesis=hypotheses[0],
        model_info=model_info,
        decoding_config=decoding,
        confidence_config=confidence_config,
        runtime=runtime,
        generated_at_utc=generated_at_utc,
        segment_max_words=segment_max_words,
        segment_max_gap_sec=segment_max_gap_sec,
    )
    del transcription_result
    del hypotheses
    if torch_module.cuda.is_available():
        torch_module.cuda.empty_cache()
    gc.collect()
    return record


def split_wav_to_windows(
    audio_path: Path,
    *,
    output_dir: Path,
    window_sec: float,
) -> list[dict[str, Any]]:
    """把 wav 切为连续无重叠窗口，返回窗口路径和原始时间偏移。"""

    if window_sec <= 0:
        raise ValueError("window_sec 必须大于 0")
    output_dir.mkdir(parents=True, exist_ok=True)
    windows: list[dict[str, Any]] = []
    with wave.open(str(audio_path), "rb") as reader:
        params = reader.getparams()
        frame_rate = reader.getframerate()
        total_frames = reader.getnframes()
        frames_per_window = max(1, int(round(window_sec * frame_rate)))
        start_frame = 0
        while start_frame < total_frames:
            reader.setpos(start_frame)
            frame_count = min(frames_per_window, total_frames - start_frame)
            audio_bytes = reader.readframes(frame_count)
            window_index = len(windows)
            window_path = output_dir / f"{audio_path.stem}_window_{window_index:04d}.wav"
            with wave.open(str(window_path), "wb") as writer:
                writer.setparams(params)
                writer.writeframes(audio_bytes)
            start_sec = start_frame / frame_rate
            duration_sec = frame_count / frame_rate
            windows.append(
                {
                    "window_index": window_index,
                    "path": window_path,
                    "start_sec": start_sec,
                    "end_sec": start_sec + duration_sec,
                    "duration_sec": duration_sec,
                }
            )
            start_frame += frame_count
    if not windows:
        raise ValueError(f"音频为空，无法分窗：{audio_path}")
    return windows


def merge_window_records(
    *,
    manifest_record: dict[str, Any],
    window_records: list[ASRConfidenceRecord],
    window_specs: list[dict[str, Any]],
    model_info: ASRModelInfo,
    decoding: ASRDecodingConfig,
    confidence_config: ASRConfidenceConfig,
    runtime: dict[str, Any],
    generated_at_utc: datetime,
    segment_max_words: int,
    segment_max_gap_sec: float,
    window_sec: float,
) -> ASRConfidenceRecord:
    """合并窗口级 ASR records，重建词索引、全局时间戳和 span/segment。"""

    if len(window_records) != len(window_specs):
        raise ValueError("window_records 与 window_specs 数量不一致")

    merged_words = []
    window_alignment_summaries: list[dict[str, Any]] = []
    for window_record, window in zip(window_records, window_specs, strict=True):
        offset = float(window["start_sec"])
        window_alignment_summaries.append(
            {
                "window_index": window["window_index"],
                "sample_id": window_record.sample_id,
                "asr_word_count": window_record.alignment.asr_word_count,
                "paired_word_count": window_record.alignment.paired_word_count,
                "word_timestamp_count": window_record.alignment.word_timestamp_count,
                "word_confidence_count": window_record.alignment.word_confidence_count,
            }
        )
        for word in window_record.asr_words:
            metadata = {
                **word.metadata,
                "audio_window": {
                    "window_index": window["window_index"],
                    "window_start_sec": window["start_sec"],
                    "window_end_sec": window["end_sec"],
                    "window_sample_id": window_record.sample_id,
                },
            }
            start_sec = word.start_sec + offset if word.start_sec is not None else None
            end_sec = word.end_sec + offset if word.end_sec is not None else None
            merged_words.append(
                word.model_copy(
                    update={
                        "word_index": len(merged_words),
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "metadata": metadata,
                    }
                )
            )

    transcript_words = [word.text for word in merged_words]
    merged_transcript = " ".join(transcript_words)
    char_offsets = word_char_offsets(merged_transcript, transcript_words)
    merged_words = [
        word.model_copy(
            update={
                "word_index": index,
                "char_start": char_offsets[index][0],
                "char_end": char_offsets[index][1],
            }
        )
        for index, word in enumerate(merged_words)
    ]

    thresholds = confidence_config.thresholds
    asr_confidence = aggregate_confidences(
        (word.confidence for word in merged_words),
        method="mean",
    )
    segments = build_segments_from_words(
        merged_words,
        max_words=segment_max_words,
        max_gap_sec=segment_max_gap_sec,
        confidence_aggregation="mean",
        thresholds=thresholds,
        speaker_label=manifest_record.get("source_channel"),
    )
    uncertain_spans = build_uncertain_spans_from_words(
        merged_words,
        thresholds=thresholds,
    )
    alignment = AlignmentDiagnostics(
        transcript_word_count=len(transcript_words),
        word_timestamp_count=sum(
            record.alignment.word_timestamp_count for record in window_records
        ),
        word_confidence_count=sum(
            record.alignment.word_confidence_count for record in window_records
        ),
        asr_word_count=len(merged_words),
        paired_word_count=sum(
            1
            for word in merged_words
            if word.start_sec is not None
            and word.end_sec is not None
            and word.confidence is not None
        ),
        missing_timestamp_word_indices=[
            index
            for index, word in enumerate(merged_words)
            if word.start_sec is None or word.end_sec is None
        ],
        missing_confidence_word_indices=[
            index for index, word in enumerate(merged_words) if word.confidence is None
        ],
        notes="Merged from fixed-duration ASR audio windows; timestamps shifted to original audio.",
        metadata={
            "audio_windowing_enabled": True,
            "window_sec": window_sec,
            "window_count": len(window_records),
            "per_window_alignment": window_alignment_summaries,
        },
    )
    sample_id = str(manifest_record.get("sample_id") or "unknown_sample")
    return ASRConfidenceRecord(
        record_id=f"nemo_entropy_windowed_{safe_filename(sample_id)}",
        sample_id=sample_id,
        dataset=str(manifest_record.get("dataset") or "unknown"),
        split=manifest_record.get("split"),
        consultation_id=manifest_record.get("consultation_id"),
        source_channel=manifest_record.get("source_channel") or "unknown",
        audio_filepath=manifest_record.get("audio_filepath") or manifest_record.get("audio_path"),
        duration_sec=_float_or_none_for_window_merge(
            manifest_record.get("duration", manifest_record.get("duration_sec"))
        ),
        reference_textgrid_path=manifest_record.get("reference_textgrid_path"),
        reference_transcript_path=manifest_record.get("reference_transcript_path"),
        reference_text_included=bool(manifest_record.get("reference_text_included", False)),
        generated_at_utc=generated_at_utc,
        asr_transcript=merged_transcript,
        asr_confidence=asr_confidence,
        confidence_level=confidence_level_for_score(asr_confidence, thresholds),
        asr_words=merged_words,
        asr_segments=segments,
        uncertain_spans=uncertain_spans,
        model=model_info,
        decoding=decoding,
        confidence=confidence_config,
        alignment=alignment,
        runtime={
            **runtime,
            "audio_windowing": {
                "enabled": True,
                "window_sec": window_sec,
                "window_count": len(window_records),
            },
        },
        metadata={
            "source_manifest": {
                "sample_id": sample_id,
                "consultation_sample_id": manifest_record.get("consultation_sample_id"),
                "text_is_placeholder": manifest_record.get("text_is_placeholder"),
                "reference_text_included": manifest_record.get(
                    "reference_text_included",
                    False,
                ),
            },
            "audio_windowing": {
                "enabled": True,
                "window_sec": window_sec,
                "window_count": len(window_records),
                "window_sample_ids": [record.sample_id for record in window_records],
                "boundary_note": (
                    "Windows are contiguous and non-overlapping; ASR text near window "
                    "boundaries may differ from full-context decoding."
                ),
            },
        },
    )


def word_char_offsets(text: str, words: list[str]) -> list[tuple[int | None, int | None]]:
    """按 merged transcript 重新计算 word char offsets。"""

    offsets: list[tuple[int | None, int | None]] = []
    search_from = 0
    for word in words:
        start = text.find(word, search_from)
        if start < 0:
            offsets.append((None, None))
            continue
        end = start + len(word)
        offsets.append((start, end))
        search_from = end
    return offsets


def _float_or_none_for_window_merge(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def autocast_context(torch_module: Any, *, device: str, precision: str) -> Any:
    if device != "cuda" or precision == "fp32":
        return nullcontext()
    dtype = torch_module.float16 if precision == "fp16" else torch_module.bfloat16
    return torch_module.autocast(device_type="cuda", dtype=dtype)


def resolve_ctc_blank_id(model: Any, frame_scores: Any) -> int:
    """尽量从 NeMo CTC 模型解析 blank id；失败时退回 vocab 最后一维。"""

    decoding = getattr(model, "ctc_decoding", None) or getattr(model, "decoding", None)
    for owner in (
        decoding,
        getattr(decoding, "decoding", None),
        getattr(model, "ctc_decoder", None),
        getattr(model, "decoder", None),
    ):
        if owner is None:
            continue
        for attr in ("blank_id", "_blank_id", "blank_index", "_blank_index"):
            value = getattr(owner, attr, None)
            if value is not None:
                return int(value)
    decoder = getattr(model, "ctc_decoder", None) or getattr(model, "decoder", None)
    value = getattr(decoder, "num_classes_with_blank", None)
    if value is not None:
        return int(value) - 1
    shape = getattr(frame_scores, "shape", None)
    if shape is not None and len(shape) == 2:
        return int(shape[1]) - 1
    raise RuntimeError("无法解析 CTC blank id")


def resolve_token_texts_by_id(model: Any, frame_scores: Any) -> dict[int, str]:
    """为 CTC token id 建立轻量 token string 映射，供 BPE word 边界聚合。"""

    shape = getattr(frame_scores, "shape", None)
    if shape is None or len(shape) != 2:
        return {}
    vocab_size = int(shape[1])
    blank_id = resolve_ctc_blank_id(model, frame_scores)
    decoding = getattr(model, "ctc_decoding", None) or getattr(model, "decoding", None)
    if decoding is not None and hasattr(decoding, "decode_ids_to_tokens"):
        token_texts: dict[int, str] = {}
        for token_id in range(vocab_size):
            if token_id == blank_id:
                token_texts[token_id] = "<blank>"
                continue
            try:
                decoded = decoding.decode_ids_to_tokens([token_id])
                token_texts[token_id] = str(decoded[0]) if decoded else str(token_id)
            except Exception:  # noqa: BLE001 - token 映射只用于诊断/聚合，失败可回退
                token_texts[token_id] = str(token_id)
        return token_texts

    decoder = getattr(model, "ctc_decoder", None) or getattr(model, "decoder", None)
    vocabulary = getattr(decoder, "vocabulary", None)
    if isinstance(vocabulary, list | tuple):
        token_texts = {index: str(token) for index, token in enumerate(vocabulary)}
        token_texts[blank_id] = "<blank>"
        return token_texts
    return {blank_id: "<blank>"}


def safe_filename(value: str) -> str:
    """把 sample_id 转成可用于 artifact 文件名的稳定字符串。"""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "unknown_sample"
def _confidence_level_counts(records: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for word in record.asr_words:
            key = str(word.confidence_level.value)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def write_run_config(record: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(to_jsonable(record), file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    args = parse_args()
    run_config_path = resolve_project_path(args.run_config_json)
    try:
        output_records, run_summary = run_export(args)
        write_run_config(run_summary, run_config_path)
        print("T028 NeMo ASR confidence 导出完成。")
        print(f"- records: {len(output_records)}")
        print(f"- output_jsonl: {resolve_project_path(args.output_jsonl)}")
        print(f"- run_config_json: {run_config_path}")
    except Exception as exc:
        failed_summary = {
            "task_id": "T028",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_root": str(PROJECT_ROOT),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        write_run_config(failed_summary, run_config_path)
        print("T028 NeMo ASR confidence 导出失败。")
        print(f"- error: {exc!r}")
        print(f"- run_config_json: {run_config_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
