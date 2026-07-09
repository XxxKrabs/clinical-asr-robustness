"""批量导出 NeMo entropy confidence ASR JSONL（T028）。

默认输入为 T025 生成的 PriMock57 channel-level manifest，默认输出到
`outputs/primock57/t028_nemo_asr_confidence/`。输出目录默认不纳入 Git。

脚本只保存 ASR 输出、置信度、时间戳、配置和文件指针；不会读取或内联
TextGrid reference 正文、notes 正文或真实患者信息。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinical_asr_robustness.asr_confidence import (
    ASRConfidenceConfig,
    ASRDecodingConfig,
    ASRModelInfo,
    ConfidenceThresholds,
    write_asr_confidence_jsonl,
)
from clinical_asr_robustness.ctc_word_confidence import (
    compute_ctc_word_confidence,
    frame_scores_from_hypothesis,
    normalize_frame_scores,
    save_ctc_frame_distribution_artifact,
    word_confidence_metadata,
)
from clinical_asr_robustness.nemo_confidence_export import (
    build_asr_confidence_record,
    configure_ctc_greedy_confidence,
    flatten_transcription_results,
    summarize_confidence_values,
    to_jsonable,
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
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--run-config-json", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument("--sample-id", action="append", dest="sample_ids", default=None)
    parser.add_argument("--record-index", action="append", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--transcribe-chunk-size", type=int, default=1)
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
        choices=["nemo_word_confidence", "ctc_frame_distribution"],
        default="nemo_word_confidence",
        help=(
            "词级置信度来源。默认沿用 NeMo word_confidence；"
            "ctc_frame_distribution 会从 Hypothesis 中保存的 frame log_probs/posterior "
            "按 CTC entropy pipeline 重新聚合到 word。"
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
    parser.add_argument("--green-min", type=float, default=0.80)
    parser.add_argument("--yellow-min", type=float, default=0.50)
    parser.add_argument("--segment-max-words", type=int, default=40)
    parser.add_argument("--segment-max-gap-sec", type=float, default=1.5)
    parser.add_argument(
        "--allow-nemo-outside-project",
        action="store_true",
        help="默认要求 nemo 来自 project/third_party/speech_main；仅调试时放宽。",
    )
    return parser.parse_args()


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

    model = ASRModel.restore_from(restore_path=str(model_path), map_location="cpu")
    model.to(device)
    model.eval()
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
    for record_chunk, audio_chunk in zip(
        chunked(selected_records, args.transcribe_chunk_size),
        chunked(audio_paths, args.transcribe_chunk_size),
        strict=True,
    ):
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
                        raise RuntimeError(
                            "CTC frame distribution 未能对齐出任何 word confidence；"
                            "请检查 token_texts/blank_id 与 transcript word 对齐。"
                        )
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

            output_records.append(
                build_asr_confidence_record(
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
            )
            processed += 1
            print(f"[{processed}/{len(selected_records)}] {manifest_record.get('sample_id')}")

    write_asr_confidence_jsonl(output_records, output_jsonl)
    word_confidence_summary = summarize_confidence_values(
        word.confidence for record in output_records for word in record.asr_words
    )

    run_summary = {
        "task_id": "T028",
        "status": "ok",
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
            },
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


def resolve_ctc_blank_id(model: Any, frame_scores: Any) -> int:
    """尽量从 NeMo CTC 模型解析 blank id；失败时退回 vocab 最后一维。"""

    decoding = getattr(model, "decoding", None)
    for owner in (decoding, getattr(decoding, "decoding", None), getattr(model, "decoder", None)):
        if owner is None:
            continue
        for attr in ("blank_id", "_blank_id", "blank_index", "_blank_index"):
            value = getattr(owner, attr, None)
            if value is not None:
                return int(value)
    decoder = getattr(model, "decoder", None)
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
    decoding = getattr(model, "decoding", None)
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

    vocabulary = getattr(getattr(model, "decoder", None), "vocabulary", None)
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
