"""Deterministic rough-cut planning helpers."""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any

from .selections import load_selection
from .timecode import seconds_to_hhmmss, timecode_to_seconds


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
) -> dict[str, Any]:
    if sequence not in SEQUENCING_MODES:
        raise ValueError(f"unsupported sequencing mode: {sequence}")
    if format_type not in FORMAT_PRESETS:
        raise ValueError(f"unsupported rough-cut format: {format_type}")
    if render_mode not in RENDER_MODES:
        raise ValueError(f"unsupported render mode: {render_mode}")

    selection = load_selection(selection_json)
    clips = [_planned_clip(clip, index, handles) for index, clip in enumerate(selection.clips, 1)]
    clips = _sequence_clips(clips, sequence)
    if max_clips is not None:
        clips = clips[: max(0, int(max_clips))]
    clips = _apply_target_duration(clips, target_duration)
    total_duration = round(sum(clip["duration"] for clip in clips), 3)
    output = os.fspath(output)
    report_output = os.fspath(report_output or _default_report_path(output))
    payload = {
        "generated": datetime.now().isoformat(),
        "selection": os.fspath(selection_json),
        "preset": preset,
        "sequence": sequence,
        "target_duration": target_duration,
        "format": format_type,
        "format_settings": FORMAT_PRESETS[format_type],
        "handles": float(handles),
        "max_clips": max_clips,
        "render_mode": render_mode,
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
    return {"plan": output, "report": report_output, "clips": len(clips), "duration": total_duration}


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
            "source": clip["source"],
            "start": clip["start"],
            "end": clip["end"],
            "label": clip.get("label") or clip.get("id") or f"clip_{index:03d}",
            "score": clip.get("score", 0),
            "render_mode": plan.get("render_mode", "copy"),
            "video_filter": plan.get("format_settings", {}).get("video_filter"),
        }
        for index, clip in enumerate(plan["clips"], 1)
    ]


def _planned_clip(clip: dict[str, Any], index: int, handles: float) -> dict[str, Any]:
    start = max(0.0, _seconds(clip.get("start_seconds", clip.get("start", 0))) - max(0.0, float(handles)))
    end = max(start, _seconds(clip.get("end_seconds", clip.get("end", start))) + max(0.0, float(handles)))
    duration = round(max(0.0, end - start), 3)
    return {
        "id": clip.get("id") or clip.get("label") or f"clip_{index:03d}",
        "label": clip.get("label") or clip.get("id") or f"clip_{index:03d}",
        "source": clip["source"],
        "start": seconds_to_hhmmss(start),
        "end": seconds_to_hhmmss(end),
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "duration": duration,
        "score": int(clip.get("score", 0) or 0),
        "review_order": int(clip.get("review_order", clip.get("order", index)) or index),
        "source_order": index,
        "labels": list(clip.get("labels", [])),
        "reasons": list(clip.get("reasons", [])),
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


def _apply_target_duration(clips: list[dict[str, Any]], target_duration: float | None) -> list[dict[str, Any]]:
    if target_duration is None:
        return clips
    target = max(0.0, float(target_duration))
    if target <= 0:
        return []
    selected = []
    elapsed = 0.0
    for clip in clips:
        if elapsed >= target:
            break
        remaining = target - elapsed
        if clip["duration"] <= remaining or not selected:
            selected_clip = dict(clip)
            if selected_clip["duration"] > remaining and remaining >= 1.0:
                selected_clip["duration"] = round(remaining, 3)
                selected_clip["end_seconds"] = round(selected_clip["start_seconds"] + remaining, 3)
                selected_clip["end"] = seconds_to_hhmmss(selected_clip["end_seconds"])
            selected.append(selected_clip)
            elapsed += selected_clip["duration"]
            continue
        if remaining >= 1.0:
            selected_clip = dict(clip)
            selected_clip["duration"] = round(remaining, 3)
            selected_clip["end_seconds"] = round(selected_clip["start_seconds"] + remaining, 3)
            selected_clip["end"] = seconds_to_hhmmss(selected_clip["end_seconds"])
            selected.append(selected_clip)
            break
    return selected


def _seconds(value: Any) -> float:
    return timecode_to_seconds(value)


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
