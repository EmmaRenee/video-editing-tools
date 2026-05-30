"""Selection JSON loading and compatibility normalization."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .timecode import seconds_to_hhmmss, timecode_to_seconds


@dataclass
class SelectionDocument:
    path: str
    project: str | None
    source: str | None
    clips: list[dict[str, Any]]
    fps: float


def load_selection(path: str, fps: float | None = None, default_fps: float = 30.0) -> SelectionDocument:
    path = os.fspath(path)
    with open(path, encoding="utf-8") as handle:
        data = json.loads(handle.read())
    if not isinstance(data, dict):
        raise ValueError(f"selection must be a JSON object: {path}")
    source = data.get("source")
    clips = data.get("clips", [])
    if not isinstance(clips, list):
        raise ValueError(f"selection clips must be a list: {path}")
    resolved_fps = float(fps if fps is not None else data.get("fps", default_fps))
    normalized = [_normalize_clip(clip, source, index, path) for index, clip in enumerate(clips, 1)]
    return SelectionDocument(
        path=path,
        project=data.get("project") or data.get("name"),
        source=source,
        clips=normalized,
        fps=resolved_fps,
    )


def load_selection_data(path: str, fps: float | None = None, default_fps: float = 30.0) -> dict[str, Any]:
    document = load_selection(path, fps=fps, default_fps=default_fps)
    return {
        "project": document.project,
        "source": document.source,
        "clips": document.clips,
        "fps": document.fps,
    }


def _normalize_clip(clip: dict[str, Any], default_source: str | None, index: int, path: str) -> dict[str, Any]:
    if not isinstance(clip, dict):
        raise ValueError(f"clip {index} in {path} must be an object")
    source = clip.get("source") or default_source
    if not source or source == "mixed":
        raise ValueError(f"clip {index} in {path} is missing source")
    start = _clip_time(clip, "start", "start_seconds")
    end = _clip_time(clip, "end", "end_seconds")
    if timecode_to_seconds(end) <= timecode_to_seconds(start):
        raise ValueError(f"clip {index} in {path} has non-positive duration")
    normalized = dict(clip)
    normalized["source"] = source
    normalized["start"] = start
    normalized["end"] = end
    normalized.setdefault("label", clip.get("id") or f"clip_{index:03d}")
    return normalized


def _clip_time(clip: dict[str, Any], formatted_key: str, seconds_key: str) -> str:
    if formatted_key in clip and clip[formatted_key] not in (None, ""):
        return str(clip[formatted_key])
    if seconds_key in clip:
        return seconds_to_hhmmss(float(clip[seconds_key]))
    raise ValueError(f"clip is missing {formatted_key}")
