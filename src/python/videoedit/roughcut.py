"""Deterministic rough-cut planning helpers."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import time
from typing import Any

from .selections import clip_seconds, load_selection
from .handoff import HandoffClip, build_handoff_timeline
from .manifests import RunManifest, fingerprint
from .timecode import frame_rate, seconds_to_frames, seconds_to_hhmmss, seconds_to_timestamp


FORMAT_PRESETS = {
    "original": {"video_filter": None, "description": "Preserve source format"},
    "reel": {"video_filter": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2", "description": "Vertical 1080x1920"},
    "youtube": {"video_filter": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2", "description": "Horizontal 1920x1080"},
}

SEQUENCING_MODES = {"review_order", "score", "source_order", "diversified"}
RENDER_MODES = {"copy", "render"}


def plan_roughcut(
    selection_json: str,
    output: str,
    preset: str = "reel",
    sequence: str = "review_order",
    target_duration: float | None = None,
    format_type: str = "original",
    handles: float = 0.0,
    max_clips: int | None = None,
    render_mode: str = "copy",
    report_output: str | None = None,
    manifest_paths: str = "absolute",
) -> dict[str, Any]:
    handles = _nonnegative_number(handles, "handles")
    if target_duration is not None:
        target_duration = _nonnegative_number(target_duration, "target_duration")
    if max_clips is not None:
        limit = _nonnegative_number(max_clips, "max_clips")
        if not limit.is_integer():
            raise ValueError("max_clips must be a non-negative integer")
        max_clips = int(limit)
    stem = os.path.splitext(os.fspath(output))[0]
    settings = {"preset": preset, "sequence": sequence, "target_duration": target_duration, "format": format_type,
                "handles": handles, "max_clips": max_clips, "render_mode": render_mode}
    with RunManifest(f"{stem}_run.json", "plan_roughcut", inputs=[selection_json], config=settings,
                     path_mode=manifest_paths) as manifest:
        result = _plan_roughcut(selection_json, output, preset, sequence, target_duration, format_type,
                               handles, max_clips, render_mode, report_output, manifest)
        manifest.record_step("plan", "plan_roughcut", settings, result, time.monotonic() - manifest.started)
    result["run_manifest"] = f"{stem}_run.json"
    return result


def _plan_roughcut(selection_json: str, output: str, preset: str, sequence: str, target_duration: float | None,
                  format_type: str, handles: float, max_clips: int | None, render_mode: str,
                  report_output: str | None, execution: RunManifest) -> dict[str, Any]:
    if sequence not in SEQUENCING_MODES:
        raise ValueError(f"unsupported sequencing mode: {sequence}")
    if format_type not in FORMAT_PRESETS:
        raise ValueError(f"unsupported rough-cut format: {format_type}")
    if render_mode not in RENDER_MODES:
        raise ValueError(f"unsupported render mode: {render_mode}")

    selection = load_selection(selection_json)
    approved = build_handoff_timeline(selection.clips, selection.source or "mixed", selection.fps,
                                      base_dir=str(Path(selection_json).resolve().parent),
                                      original_clips=selection.raw_clips)
    clips = [_planned_clip(clip, index, handles, native)
             for index, (clip, native) in enumerate(zip(selection.clips, approved.clips), 1)]
    clips = _sequence_clips(clips, sequence)
    if max_clips is not None:
        clips = clips[:max_clips]
    clips = _apply_target_duration(clips, target_duration, selection.fps)
    execution.data["inputs"].extend(fingerprint(source, content=False) for source in sorted({clip["source"] for clip in clips}))
    timeline = build_handoff_timeline(clips, "mixed", selection.fps,
                                      media_info={clip.source.path: clip.source.info for clip in approved.clips})
    execution.data["handoff"] = timeline.to_dict(handles)
    execution.data["handoff"].update(render_mode=render_mode, format=format_type,
                                    planning_rounding="none_elapsed_seconds",
                                    handles_clamped_to_duration=any(clip["handles_clamped_to_source"] for clip in clips),
                                    target_policy="trim_tail_elapsed_seconds_reject_zero_frame_spans")
    execution.data["warnings"].extend(timeline.warnings)
    execution.data["partial"] = bool(set(timeline.limitations) - {"edl_audio_not_exported"})
    total_duration = sum(clip["duration"] for clip in clips)
    output = os.fspath(output)
    report_output = os.fspath(report_output or _default_report_path(output))
    payload = {
        "generated": datetime.now().isoformat(),
        "status": "partial" if execution.data["partial"] else "ok",
        "warnings": list(timeline.warnings),
        "selection": os.fspath(selection_json),
        "preset": preset,
        "sequence": sequence,
        "target_duration": target_duration,
        "format": format_type,
        "format_settings": FORMAT_PRESETS[format_type],
        "handles": float(handles),
        "max_clips": max_clips,
        "render_mode": render_mode,
        "fps": selection.fps,
        "summary": {
            "clips": len(clips),
            "duration": total_duration,
            "duration_formatted": seconds_to_hhmmss(total_duration),
            "sources": len({clip["source"] for clip in clips}),
        },
        "clips": clips,
    }
    _write_json(output, payload)
    _write_report(payload, report_output)
    return {"plan": output, "report": report_output, "clips": len(clips), "duration": total_duration,
            "warnings": list(timeline.warnings)}


def load_roughcut_plan(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        data = json.loads(handle.read())
    if "clips" not in data or not isinstance(data["clips"], list):
        raise ValueError("roughcut plan requires clips list")
    return data


def clips_from_plan(path: str) -> list[dict[str, Any]]:
    plan = load_roughcut_plan(path)
    return [
        {
            **clip,
            "source": clip["source"],
            "start": seconds_to_timestamp(clip_seconds(clip, "start", clip.get("source_fps", plan.get("fps", 30)))),
            "end": seconds_to_timestamp(clip_seconds(clip, "end", clip.get("source_fps", plan.get("fps", 30)))),
            "start_seconds": clip_seconds(clip, "start", clip.get("source_fps", plan.get("fps", 30))),
            "end_seconds": clip_seconds(clip, "end", clip.get("source_fps", plan.get("fps", 30))),
            "label": clip.get("label") or clip.get("id") or f"clip_{index:03d}",
            "score": clip.get("score", 0),
            "render_mode": plan.get("render_mode", "copy"),
            "video_filter": plan.get("format_settings", {}).get("video_filter"),
        }
        for index, clip in enumerate(plan["clips"], 1)
    ]


def _planned_clip(clip: dict[str, Any], index: int, handles: float, native: HandoffClip) -> dict[str, Any]:
    requested_start, requested_end = native.start_seconds - handles, native.end_seconds + handles
    start, end = max(0.0, requested_start), requested_end
    extent = native.source.info.duration
    if extent is not None:
        end = min(end, extent)
    planned = {
        **clip,
        "id": clip.get("id") or clip.get("label") or f"clip_{index:03d}",
        "label": clip.get("label") or clip.get("id") or f"clip_{index:03d}",
        "source": native.source.path,
        "source_fps": str(native.source.rate),
        "reel": native.source.reel,
        "start": seconds_to_timestamp(start),
        "end": seconds_to_timestamp(end),
        "start_seconds": start,
        "end_seconds": end,
        "duration": end - start,
        "selection_start_seconds": native.start_seconds,
        "selection_end_seconds": native.end_seconds,
        "source_duration_seconds": extent,
        "handles_clamped_to_source": start > requested_start or end < requested_end,
        "target_trimmed": False,
        "score": int(clip.get("score", 0) or 0),
        "review_order": int(clip.get("review_order", clip.get("order", index)) or index),
        "source_order": index,
        "labels": list(clip.get("labels", [])),
        "reasons": list(clip.get("reasons", [])),
    }
    if native.source.info.timecode or clip.get("source_timecode"):
        planned["source_timecode"] = native.source.timecode
    _update_handles(planned)
    return planned


def _update_handles(clip: dict[str, Any]) -> None:
    start, end = clip["start_seconds"], clip["end_seconds"]
    clip["handles_applied"] = {
        "pre": max(0.0, min(end, clip["selection_start_seconds"]) - start),
        "post": max(0.0, end - max(start, clip["selection_end_seconds"])),
    }


def _sequence_clips(clips: list[dict[str, Any]], sequence: str) -> list[dict[str, Any]]:
    if sequence == "review_order":
        return sorted(clips, key=lambda clip: (clip["review_order"], -clip["score"], clip["source_order"]))
    if sequence == "score":
        return sorted(clips, key=lambda clip: (-clip["score"], clip["review_order"], clip["source_order"]))
    if sequence == "source_order":
        return sorted(clips, key=lambda clip: (clip["source"], clip["start_seconds"], clip["source_order"]))
    groups: dict[str, list[dict[str, Any]]] = {}
    for clip in sorted(clips, key=lambda item: (-item["score"], item["review_order"], item["source_order"])):
        groups.setdefault(clip["source"], []).append(clip)
    ordered = []
    while any(groups.values()):
        for source in sorted(groups):
            if groups[source]:
                ordered.append(groups[source].pop(0))
    return ordered


def _apply_target_duration(clips: list[dict[str, Any]], target_duration: float | None,
                           fps: float) -> list[dict[str, Any]]:
    if target_duration is None:
        return clips
    target = target_duration
    if target <= 0:
        return []
    selected = []
    elapsed = 0.0
    for clip in clips:
        if elapsed >= target:
            break
        remaining = target - elapsed
        selected_clip = dict(clip)
        if selected_clip["duration"] > remaining:
            selected_clip["duration"] = remaining
            selected_clip["end_seconds"] = selected_clip["start_seconds"] + remaining
            selected_clip["end"] = seconds_to_timestamp(selected_clip["end_seconds"])
            selected_clip["target_trimmed"] = True
            _update_handles(selected_clip)
            # Keep valid preceding clips when the final remainder cannot form a frame.
            native_rate = frame_rate(selected_clip["source_fps"])
            span = (seconds_to_frames(selected_clip["end_seconds"], native_rate) -
                    seconds_to_frames(selected_clip["start_seconds"], native_rate))
            if selected and (span <= 0 or seconds_to_frames(Fraction(span, 1) / native_rate, fps) <= 0):
                break
        selected.append(selected_clip)
        elapsed += selected_clip["duration"]
    return selected


def _nonnegative_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a finite non-negative number") from error
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def _default_report_path(output: str) -> str:
    root, _ext = os.path.splitext(os.fspath(output))
    return f"{root}_report.md"


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")


def _write_report(plan: dict[str, Any], output: str) -> None:
    lines = [
        "# Rough-Cut Plan",
        "",
        f"**Generated:** {plan['generated']}",
        f"**Preset:** {plan['preset']}",
        f"**Sequence:** {plan['sequence']}",
        f"**Format:** {plan['format']}",
        f"**Render mode:** {plan['render_mode']}",
        f"**Clips:** {plan['summary']['clips']}",
        f"**Duration:** {plan['summary']['duration_formatted']}",
        "",
        "| Order | Clip | Source | Start | End | Score |",
        "|-------|------|--------|-------|-----|-------|",
    ]
    for index, clip in enumerate(plan.get("clips", []), 1):
        lines.append(
            f"| {index} | {clip['label']} | {os.path.basename(clip['source'])} | "
            f"{clip['start']} | {clip['end']} | {clip['score']} |"
        )
    parent = os.path.dirname(os.fspath(output))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
