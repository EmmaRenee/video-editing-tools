"""Composable operations used by the pipeline runner."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from .advanced import (
    cluster_transcript_topics,
    detect_face_person_presence,
    detect_motorsports_events,
    detect_ocr_signage,
    detect_visual_objects,
)
from .ai import find_missed_moments, generate_missed_review, score_frames
from .calibration import evaluate_ratings, tune_scoring
from .captions import burn_captions
from .config import AnalysisConfig
from .content import generate_content_map, generate_quote_mining, plan_content_series
from .diagnostics import resolve_command
from .edl import export_selection_file
from .ffmpeg import run_command_check
from .inventory import build_inventory, write_inventory_outputs
from .modules import all_modules, is_module_enabled, load_module_config, module_for_operation, operation_enabled
from .rating import run_rating
from .review import assemble, create_approval_file, generate_review_assets
from .roughcut import plan_roughcut
from .scaffold import scaffold_project
from .selections import load_selection
from .timecode import seconds_to_hhmmss, timecode_to_seconds


OperationFunc = Callable[[dict[str, Any], dict[str, Any]], Any]

SIGNAL_ARTIFACT_ALIASES = {
    "visual_objects": "visual_objects",
    "visual_objects_path": "visual_objects",
    "ocr_signage": "ocr_signage",
    "face_person": "face_person",
    "face_person_presence": "face_person",
    "motorsports_events": "motorsports_events",
    "topic_clusters": "topic_clusters",
    "ai_frame_scores": "ai_frame_scores",
    "ai_frame_scores_path": "ai_frame_scores",
}


@dataclass
class Operation:
    name: str
    description: str
    func: OperationFunc
    module: str = "core.pipeline"


class OperationRegistry:
    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}

    def register(self, name: str, description: str, func: OperationFunc, module: str | None = None) -> None:
        self._operations[name] = Operation(
            name=name,
            description=description,
            func=func,
            module=module or module_for_operation(name),
        )

    def get(self, name: str) -> Operation:
        if name not in self._operations:
            raise KeyError(f"Unknown operation: {name}")
        return self._operations[name]

    def list(self) -> list[Operation]:
        return [self._operations[key] for key in sorted(self._operations)]


def default_registry(enabled_only: bool = True, cwd: str | None = None) -> OperationRegistry:
    registry = OperationRegistry()
    _register(registry, enabled_only, cwd, "inventory", "Scan footage and write inventory artifacts", op_inventory)
    _register(registry, enabled_only, cwd, "analyze_signals", "Analyze footage signals and write ratings artifacts", op_rate_footage)
    _register(registry, enabled_only, cwd, "rate_footage", "Inventory, score, and rank candidate clips", op_rate_footage)
    _register(registry, enabled_only, cwd, "detect_highlights_audio", "Filter rating candidates with audio labels", op_filter_audio_candidates)
    _register(
        registry,
        enabled_only,
        cwd,
        "detect_highlights_transcript",
        "Filter rating candidates with transcript labels",
        op_filter_transcript_candidates,
    )
    _register(registry, enabled_only, cwd, "transcribe_whisper", "Run Whisper transcription for a single video or folder", op_transcribe_whisper)
    _register(registry, enabled_only, cwd, "evaluate_ratings", "Evaluate ratings against human annotation JSON", op_evaluate_ratings)
    _register(registry, enabled_only, cwd, "calibrate_scoring", "Tune scoring config candidates against annotations", op_calibrate_scoring)
    _register(registry, enabled_only, cwd, "extract_segments", "Extract clips from selection JSON files", op_extract_segments)
    _register(registry, enabled_only, cwd, "generate_edl", "Generate EDL/XML/M3U from selection JSON files", op_generate_edl)
    _register(registry, enabled_only, cwd, "generate_review_assets", "Generate thumbnails and an HTML contact sheet", op_review_assets)
    _register(registry, enabled_only, cwd, "approve_candidates", "Create approved.json from rating candidates", op_approve_candidates)
    _register(registry, enabled_only, cwd, "plan_roughcut", "Plan a deterministic rough cut from approved selections", op_plan_roughcut)
    _register(registry, enabled_only, cwd, "assemble_rough_cut", "Assemble a rough cut from approved selections", op_assemble)
    _register(registry, enabled_only, cwd, "format_video", "Format a video with an FFmpeg video filter", op_format_video)
    _register(registry, enabled_only, cwd, "burn_captions", "Burn subtitles into a video with FFmpeg", op_burn_captions)
    _register(registry, enabled_only, cwd, "normalize_audio", "Normalize audio to target loudness", op_normalize_audio)
    _register(registry, enabled_only, cwd, "concatenate_videos", "Concatenate extracted clips with FFmpeg", op_concatenate_videos)
    _register(registry, enabled_only, cwd, "detect_ocr_signage", "Optionally detect OCR/signage text from sampled frames", op_detect_ocr)
    _register(registry, enabled_only, cwd, "detect_visual_objects", "Optionally run an external object detector", op_detect_objects)
    _register(registry, enabled_only, cwd, "score_ai_frames", "Score sampled frames against AI profile prompts", op_score_ai_frames)
    _register(registry, enabled_only, cwd, "detect_face_person_presence", "Optionally detect face/person presence from sampled frames", op_face_person)
    _register(registry, enabled_only, cwd, "detect_motorsports_events", "Infer motorsports event moments from ratings", op_motorsports_events)
    _register(registry, enabled_only, cwd, "cluster_transcript_topics", "Cluster transcript hits into editing topics", op_transcript_topics)
    _register(registry, enabled_only, cwd, "find_ai_missed_moments", "Find AI-scored missed moment candidates", op_find_ai_missed_moments)
    _register(registry, enabled_only, cwd, "generate_missed_review", "Generate review HTML for AI missed moments", op_generate_missed_review)
    _register(registry, enabled_only, cwd, "plan_content_series", "Plan reusable content-series clips from ratings", op_plan_content_series)
    _register(registry, enabled_only, cwd, "generate_content_map", "Generate a ranked editorial content map", op_generate_content_map)
    _register(registry, enabled_only, cwd, "quote_mining", "Generate transcript-forward quote-mining report", op_quote_mining)
    _register(registry, enabled_only, cwd, "scaffold_project", "Create a video project folder scaffold", op_scaffold_project)
    module_config = load_module_config(cwd)
    for module in all_modules(cwd).values():
        if enabled_only and not is_module_enabled(module, module_config):
            continue
        for operation in module.operations:
            registry.register(operation.name, operation.description, operation.func, module=module.id)
    return registry


def _register(
    registry: OperationRegistry,
    enabled_only: bool,
    cwd: str | None,
    name: str,
    description: str,
    func: OperationFunc,
) -> None:
    if enabled_only and not operation_enabled(name, cwd):
        return
    registry.register(name, description, func)


def op_inventory(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output_dir = os.fspath(params.get("output") or context["output"])
    items = build_inventory(input_path)
    write_inventory_outputs(items, os.path.join(output_dir, "inventory"))
    artifact = os.path.join(output_dir, "inventory.json")
    context["inventory"] = artifact
    return {"inventory": artifact, "count": len(items)}


def op_rate_footage(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output_dir = os.fspath(params.get("output") or context["output"])
    config_data = params.get("config") if isinstance(params.get("config"), dict) else params
    config_data = dict(config_data)
    _merge_signal_artifact_aliases(config_data)
    config = AnalysisConfig.from_mapping(config_data)
    report = run_rating(input_path, output_dir, config=config)
    context["ratings"] = os.path.join(output_dir, "ratings.json")
    context["selections"] = os.path.join(output_dir, "selections")
    return {"ratings": context["ratings"], "candidates": len(report.candidates)}


def _merge_signal_artifact_aliases(config_data: dict[str, Any]) -> None:
    artifacts = dict(config_data.get("signal_artifacts") or {})
    present: dict[str, list[str]] = {}
    for param_key, artifact_key in SIGNAL_ARTIFACT_ALIASES.items():
        if config_data.get(param_key):
            present.setdefault(artifact_key, []).append(param_key)

    conflicts = {artifact_key: keys for artifact_key, keys in present.items() if len(keys) > 1}
    if conflicts:
        details = "; ".join(
            f"{artifact_key}: {', '.join(keys)}"
            for artifact_key, keys in sorted(conflicts.items())
        )
        raise ValueError(f"conflicting signal artifact aliases: {details}")

    for artifact_key, keys in present.items():
        artifacts[artifact_key] = config_data[keys[0]]

    if artifacts:
        config_data["signal_artifacts"] = artifacts
        if artifacts.get("visual_objects"):
            config_data["visual_objects_path"] = artifacts["visual_objects"]
        if artifacts.get("ai_frame_scores"):
            config_data["ai_frame_scores_path"] = artifacts["ai_frame_scores"]


def op_filter_candidates(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    label = params.get("label", "audio_spike")
    output = _filter_output(
        params.get("output") or os.path.join(os.path.dirname(ratings_path), "filtered_candidates.json"),
        label,
    )
    with open(ratings_path, encoding="utf-8") as handle:
        data = json.loads(handle.read())
    candidates = [item for item in data.get("candidates", []) if label in item.get("labels", [])]
    selections_dir = os.fspath(
        params.get("selections_output")
        or params.get("selection_output")
        or os.path.join(os.path.dirname(output) or ".", f"{_safe_slug(label)}_selections")
    )
    selection_paths = _write_candidate_selections(candidates, selections_dir)
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"label": label, "candidates": candidates, "selections": selections_dir}, indent=2))
    context["filtered_candidates"] = output
    context["filtered_selections"] = selections_dir
    return {"output": output, "selections": selections_dir, "files": selection_paths, "count": len(candidates)}


def op_filter_audio_candidates(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    operation_params = dict(params)
    operation_params.setdefault("label", "audio_spike")
    return op_filter_candidates(context, operation_params)


def op_filter_transcript_candidates(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    operation_params = dict(params)
    operation_params.setdefault("label", "transcript_hit")
    return op_filter_candidates(context, operation_params)


def op_transcribe_whisper(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    whisper = resolve_command("whisper")
    if not whisper:
        raise RuntimeError("whisper command not found")
    input_path = os.fspath(params.get("input") or context["input"])
    output_dir = os.fspath(params.get("output") or context["output"])
    model = params.get("model", "small")
    os.makedirs(output_dir, exist_ok=True)
    files = [input_path] if os.path.isfile(input_path) else sorted(
        glob.glob(os.path.join(input_path, "**", "*.mp4"), recursive=True)
    )
    for file_path in files:
        run_command_check(
            [whisper, file_path, "--model", model, "--output_format", "srt", "--output_dir", output_dir],
        )
    return {"output": output_dir, "count": len(files)}


def op_evaluate_ratings(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    annotations = os.fspath(params["annotations"])
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "calibration"))
    result = evaluate_ratings(ratings_path, annotations, output_dir)
    context["calibration_report"] = result["report"]
    return result


def op_calibrate_scoring(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    annotations = os.fspath(params["annotations"])
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "calibration"))
    result = tune_scoring(ratings_path, annotations, output_dir)
    context["calibration_report"] = result["report"]
    context["proposed_config"] = result["proposed_config"]
    return result


def op_generate_edl(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection_glob = params.get("input") or context.get("selections")
    output_dir = os.fspath(params.get("output") or context["output"])
    fps = float(params["fps"]) if "fps" in params and params["fps"] is not None else None
    selection_paths = _selection_paths(selection_glob)
    written = []
    for path in selection_paths:
        written.extend(export_selection_file(path, output_dir, fps=fps))
    return {"output": output_dir, "files": written}


def op_review_assets(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output_dir = os.fspath(params.get("output") or context["output"])
    result = generate_review_assets(
        ratings_path,
        output_dir,
        max_items=int(params.get("max_items", 100)),
        proxies=bool(params.get("proxy") or params.get("proxies", False)),
        thumbnail_width=int(params.get("thumbnail_width", 360)),
        calibration_json=params.get("calibration") or params.get("calibration_json") or context.get("calibration_report"),
    )
    context["review_assets"] = result["manifest"]
    context["review_decisions"] = result["decisions"]
    return result


def op_approve_candidates(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output = os.fspath(params.get("output") or os.path.join(context["output"], "approved.json"))
    actions = params.get("actions")
    if isinstance(actions, str):
        actions = [item.strip() for item in actions.split(",") if item.strip()]
    ids = params.get("ids")
    if isinstance(ids, str):
        ids = [item.strip() for item in ids.split(",") if item.strip()]
    create_approval_file(
        ratings_path,
        output,
        actions=actions,
        min_score=params.get("min_score"),
        ids=ids,
        decisions_json=params.get("decisions") or params.get("decisions_json") or context.get("review_decisions"),
    )
    context["approved"] = output
    return {"approved": output}


def op_assemble(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection = os.fspath(params.get("input") or params.get("selection") or context.get("approved"))
    output = os.fspath(params.get("output") or os.path.join(context["output"], "rough_cut.mp4"))
    return {"output": assemble(selection, output, plan_json=params.get("plan") or context.get("roughcut_plan"))}


def op_plan_roughcut(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection = os.fspath(params.get("input") or params.get("selection") or context.get("approved"))
    output = os.fspath(params.get("output") or os.path.join(context["output"], "roughcut_plan.json"))
    result = plan_roughcut(
        selection,
        output,
        preset=params.get("preset", "reel"),
        sequence=params.get("sequence", "review_order"),
        target_duration=params.get("target_duration"),
        format_type=params.get("format", params.get("format_type", "original")),
        handles=float(params.get("handles", 0.0)),
        max_clips=params.get("max_clips"),
        render_mode=params.get("render_mode", "copy"),
        report_output=params.get("report_output"),
    )
    context["roughcut_plan"] = result["plan"]
    return result


def op_extract_segments(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection_paths = _selection_paths(params.get("input") or context.get("selections"))
    output_dir = os.fspath(params.get("output") or context["output"])
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for selection_path in selection_paths:
        selection = load_selection(selection_path)
        for index, clip in enumerate(selection.clips, 1):
            source = clip["source"]
            label = _safe_slug(clip.get("label") or clip.get("id") or f"clip_{index:03d}")
            source_stem = _safe_slug(os.path.splitext(os.path.basename(source))[0])
            output = os.path.join(output_dir, f"{source_stem}_{label}.mp4")
            run_command_check(
                ["ffmpeg", "-i", source, "-ss", clip["start"], "-to", clip["end"], "-c", "copy", output, "-y"],
            )
            written.append(output)
    return {"output": output_dir, "files": written}


def op_plan_content_series(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "series"))
    result = plan_content_series(
        ratings_path,
        output_dir,
        template=params.get("template", "team_tuesday"),
        max_clips=int(params.get("max_clips", 5)),
    )
    context["series_plan"] = result["plan"]
    context["series_selections"] = result["selections"]
    return result


def op_generate_content_map(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "reports"))
    result = generate_content_map(ratings_path, output_dir)
    context["content_map"] = result["json"]
    return result


def op_quote_mining(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "reports"))
    result = generate_quote_mining(ratings_path, output_dir)
    context["quote_mining"] = result["markdown"]
    return result


def op_scaffold_project(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    result = scaffold_project(
        params["name"],
        os.fspath(params.get("output") or context.get("output") or "."),
        project_type=params.get("type", params.get("project_type", "reel")),
        source=params.get("source"),
        team_config=params.get("team_config"),
    )
    return result


def op_format_video(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params["input"])
    output = os.fspath(params["output"])
    filter_expr = params.get("filter") or params.get("vf") or "scale=-2:1080"
    run_command_check(["ffmpeg", "-i", input_path, "-vf", filter_expr, "-c:a", "copy", output, "-y"])
    return {"output": output}


def op_burn_captions(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    output = burn_captions(
        params["input"],
        params["subtitles"],
        params["output"],
        style=params.get("style", "automotive_racing"),
        format_type=params.get("format", params.get("format_type", "original")),
    )
    return {"output": output}


def op_normalize_audio(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    run_command_check(
        [
            "ffmpeg",
            "-i",
            params["input"],
            "-af",
            params.get("filter", "loudnorm=I=-16:TP=-1.5:LRA=11"),
            "-c:v",
            "copy",
            params["output"],
            "-y",
        ]
    )
    return {"output": params["output"]}


def op_concatenate_videos(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_list = os.fspath(params["input"])
    output = os.fspath(params["output"])
    run_command_check(["ffmpeg", "-f", "concat", "-safe", "0", "-i", input_list, "-c", "copy", output, "-y"])
    return {"output": output}


def op_detect_ocr(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output = _json_output(params.get("output") or context["output"], "ocr_signage.json")
    result = detect_ocr_signage(
        input_path,
        output,
        sample_interval=float(params.get("sample_interval", 10.0)),
        max_frames_per_file=int(params.get("max_frames_per_file", 6)),
        timeout=int(params.get("timeout", 180)),
    )
    context["ocr_signage"] = output
    return result


def op_detect_objects(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output = _json_output(params.get("output") or context["output"], "visual_objects.json")
    result = detect_visual_objects(
        input_path,
        output,
        command=params.get("command"),
        model=params.get("model"),
        confidence=float(params["confidence"]) if params.get("confidence") is not None else None,
        max_detections=int(params.get("max_detections", 5000)),
        segment_merge_gap=float(params.get("segment_merge_gap", 1.0)),
        timeout=int(params.get("timeout", 180)),
    )
    context["visual_objects"] = output
    return result


def op_score_ai_frames(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output = _json_output(params.get("output") or context["output"], "ai_frame_scores.json")
    result = score_frames(
        input_path,
        output,
        profile_id=params.get("profile", "general_broll"),
        sample_interval=float(params.get("sample_interval", 10.0)),
        max_frames_per_file=int(params.get("max_frames_per_file", 8)),
        min_score=float(params.get("min_score", 0.22)),
        cache=bool(params.get("cache", True)),
        model=params.get("model", "ViT-B-32"),
        pretrained=params.get("pretrained", "laion2b_s34b_b79k"),
        timeout=int(params.get("timeout", 180)),
    )
    context["ai_frame_scores"] = output
    return result


def op_face_person(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params.get("input") or context["input"])
    output = _json_output(params.get("output") or context["output"], "face_person_presence.json")
    result = detect_face_person_presence(
        input_path,
        output,
        sample_interval=float(params.get("sample_interval", 10.0)),
        max_frames_per_file=int(params.get("max_frames_per_file", 6)),
        timeout=int(params.get("timeout", 180)),
    )
    context["face_person_presence"] = output
    return result


def op_motorsports_events(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output = _json_output(params.get("output") or context["output"], "motorsports_events.json")
    result = detect_motorsports_events(
        ratings_path,
        output,
        min_confidence=float(params.get("min_confidence", 0.2)),
    )
    context["motorsports_events"] = output
    return result


def op_transcript_topics(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    output = _json_output(params.get("output") or context["output"], "topic_clusters.json")
    result = cluster_transcript_topics(ratings_path, output)
    context["topic_clusters"] = output
    return result


def op_find_ai_missed_moments(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    ratings_path = os.fspath(params.get("input") or params.get("ratings") or context.get("ratings", "ratings.json"))
    ai_scores_value = params.get("ai_frame_scores") or context.get("ai_frame_scores")
    if not ai_scores_value:
        raise ValueError("find_ai_missed_moments requires ai_frame_scores artifact")
    ai_scores = os.fspath(ai_scores_value)
    output = _json_output(params.get("output") or context["output"], "ai_missed_moments.json")
    result = find_missed_moments(
        ratings_path,
        ai_scores,
        output,
        min_score=float(params.get("min_score", 0.35)),
        window_pre_roll=float(params.get("window_pre_roll", 2.0)),
        window_post_roll=float(params.get("window_post_roll", 4.0)),
        merge_gap=float(params.get("merge_gap", 5.0)),
    )
    context["ai_missed_moments"] = output
    return result


def op_generate_missed_review(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    missed_path = os.fspath(params.get("input") or params.get("missed_moments") or context.get("ai_missed_moments"))
    output_dir = os.fspath(params.get("output") or os.path.join(context["output"], "missed_review"))
    result = generate_missed_review(missed_path, output_dir)
    context["missed_review_decisions"] = result["decisions"]
    return result


def _json_output(value: Any, default_name: str) -> str:
    output = os.fspath(value)
    if os.path.splitext(output)[1].lower() == ".json":
        return output
    return os.path.join(output, default_name)


def _filter_output(value: Any, label: str) -> str:
    output = os.fspath(value)
    if os.path.splitext(output)[1].lower() == ".json":
        return output
    return os.path.join(output, f"{_safe_slug(label)}_candidates.json")


def _write_candidate_selections(candidates: list[dict[str, Any]], output_dir: str) -> list[str]:
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        source = candidate.get("source")
        if not source:
            continue
        grouped.setdefault(os.fspath(source), []).append(candidate)

    paths: list[str] = []
    for source, clips in grouped.items():
        safe_name = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        path = os.path.join(output_dir, f"{safe_name}_selections.json")
        payload = {
            "source": source,
            "clips": [
                {
                    "source": clip.get("source"),
                    "start": _clip_timecode(clip, "start", "start_seconds"),
                    "end": _clip_timecode(clip, "end", "end_seconds"),
                    "label": clip.get("id") or clip.get("label") or f"clip_{index:03d}",
                    "score": clip.get("score", 0),
                    "action": clip.get("action", "review"),
                    "reasons": list(clip.get("reasons", [])),
                }
                for index, clip in enumerate(sorted(clips, key=lambda item: _clip_seconds(item)), 1)
            ],
        }
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2))
        paths.append(path)
    return paths


def _clip_timecode(clip: dict[str, Any], formatted_key: str, seconds_key: str) -> str:
    value = clip.get(formatted_key)
    if isinstance(value, str) and value:
        return value
    if seconds_key in clip:
        return seconds_to_hhmmss(float(clip[seconds_key]))
    return "00:00:00"


def _clip_seconds(clip: dict[str, Any]) -> float:
    if "start_seconds" in clip:
        return float(clip["start_seconds"])
    return timecode_to_seconds(clip.get("start", 0))


def _clip_source(clip: dict[str, Any], default_source: str | None, index: int) -> str:
    source = clip.get("source") or default_source
    if not source or source == "mixed":
        raise ValueError(f"clip {index} is missing source")
    return os.fspath(source)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"


def _selection_paths(value: Any) -> list[str]:
    if not value:
        return []
    path = os.fspath(value)
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.json")))
    if any(char in str(value) for char in "*?[]"):
        return sorted(glob.glob(str(value)))
    return [path]
