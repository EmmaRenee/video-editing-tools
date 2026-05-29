"""Composable operations used by the pipeline runner."""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import Any, Callable

from .advanced import (
    cluster_transcript_topics,
    detect_face_person_presence,
    detect_motorsports_events,
    detect_ocr_signage,
    detect_visual_objects,
)
from .config import AnalysisConfig
from .edl import export_selection_file
from .ffmpeg import run_command_check
from .inventory import build_inventory, write_inventory_outputs
from .rating import run_rating
from .review import assemble, create_approval_file, generate_review_assets
from .timecode import seconds_to_hhmmss, timecode_to_seconds


OperationFunc = Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass
class Operation:
    name: str
    description: str
    func: OperationFunc


class OperationRegistry:
    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}

    def register(self, name: str, description: str, func: OperationFunc) -> None:
        self._operations[name] = Operation(name=name, description=description, func=func)

    def get(self, name: str) -> Operation:
        if name not in self._operations:
            raise KeyError(f"Unknown operation: {name}")
        return self._operations[name]

    def list(self) -> list[Operation]:
        return [self._operations[key] for key in sorted(self._operations)]


def default_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register("inventory", "Scan footage and write inventory artifacts", op_inventory)
    registry.register("analyze_signals", "Analyze footage signals and write ratings artifacts", op_rate_footage)
    registry.register("rate_footage", "Inventory, score, and rank candidate clips", op_rate_footage)
    registry.register("detect_highlights_audio", "Filter rating candidates with audio labels", op_filter_audio_candidates)
    registry.register(
        "detect_highlights_transcript",
        "Filter rating candidates with transcript labels",
        op_filter_transcript_candidates,
    )
    registry.register("transcribe_whisper", "Run Whisper transcription for a single video or folder", op_transcribe_whisper)
    registry.register("extract_segments", "Extract clips from selection JSON files", op_extract_segments)
    registry.register("generate_edl", "Generate EDL/XML/M3U from selection JSON files", op_generate_edl)
    registry.register("generate_review_assets", "Generate thumbnails and an HTML contact sheet", op_review_assets)
    registry.register("approve_candidates", "Create approved.json from rating candidates", op_approve_candidates)
    registry.register("assemble_rough_cut", "Assemble a rough cut from approved selections", op_assemble)
    registry.register("format_video", "Format a video with an FFmpeg video filter", op_format_video)
    registry.register("burn_captions", "Burn subtitles into a video with FFmpeg", op_burn_captions)
    registry.register("normalize_audio", "Normalize audio to target loudness", op_normalize_audio)
    registry.register("concatenate_videos", "Concatenate extracted clips with FFmpeg", op_concatenate_videos)
    registry.register("detect_ocr_signage", "Optionally detect OCR/signage text from sampled frames", op_detect_ocr)
    registry.register("detect_visual_objects", "Optionally run an external object detector", op_detect_objects)
    registry.register("detect_face_person_presence", "Optionally detect face/person presence from sampled frames", op_face_person)
    registry.register("detect_motorsports_events", "Infer motorsports event moments from ratings", op_motorsports_events)
    registry.register("cluster_transcript_topics", "Cluster transcript hits into editing topics", op_transcript_topics)
    return registry


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
    config = AnalysisConfig.from_mapping(config_data)
    report = run_rating(input_path, output_dir, config=config)
    context["ratings"] = os.path.join(output_dir, "ratings.json")
    context["selections"] = os.path.join(output_dir, "selections")
    return {"ratings": context["ratings"], "candidates": len(report.candidates)}


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
    whisper = shutil.which("whisper")
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


def op_generate_edl(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection_glob = params.get("input") or context.get("selections")
    output_dir = os.fspath(params.get("output") or context["output"])
    fps = float(params.get("fps", 30))
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
    return {"output": assemble(selection, output)}


def op_extract_segments(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    selection_paths = _selection_paths(params.get("input") or context.get("selections"))
    output_dir = os.fspath(params.get("output") or context["output"])
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for selection_path in selection_paths:
        with open(selection_path, encoding="utf-8") as handle:
            data = json.loads(handle.read())
        default_source = data.get("source")
        for index, clip in enumerate(data.get("clips", []), 1):
            source = _clip_source(clip, default_source, index)
            label = _safe_slug(clip.get("label") or clip.get("id") or f"clip_{index:03d}")
            source_stem = _safe_slug(os.path.splitext(os.path.basename(source))[0])
            output = os.path.join(output_dir, f"{source_stem}_{label}.mp4")
            run_command_check(
                ["ffmpeg", "-i", source, "-ss", clip["start"], "-to", clip["end"], "-c", "copy", output, "-y"],
            )
            written.append(output)
    return {"output": output_dir, "files": written}


def op_format_video(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    input_path = os.fspath(params["input"])
    output = os.fspath(params["output"])
    filter_expr = params.get("filter") or params.get("vf") or "scale=-2:1080"
    run_command_check(["ffmpeg", "-i", input_path, "-vf", filter_expr, "-c:a", "copy", output, "-y"])
    return {"output": output}


def op_burn_captions(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    run_command_check(
        [
            "ffmpeg",
            "-i",
            params["input"],
            "-vf",
            f"subtitles={params['subtitles']}",
            params["output"],
            "-y",
        ]
    )
    return {"output": params["output"]}


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
        timeout=int(params.get("timeout", 180)),
    )
    context["visual_objects"] = output
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
