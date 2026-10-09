"""Selection JSON loading and compatibility normalization."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .timecode import frame_rate, seconds_to_timestamp, timecode_to_seconds


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
    raw_fps = fps if fps is not None else data.get("fps", default_fps)
    rate = frame_rate(raw_fps)
    resolved_fps = float(raw_fps) if "/" not in str(raw_fps) else float(rate)
    normalized = [_normalize_clip(clip, source, index, path, resolved_fps) for index, clip in enumerate(clips, 1)]
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


def _normalize_clip(clip: dict[str, Any], default_source: str | None, index: int, path: str,
                    fps: float = 30.0) -> dict[str, Any]:
    if not isinstance(clip, dict):
        raise ValueError(f"clip {index} in {path} must be an object")
    source = clip.get("source") or default_source
    if not source or source == "mixed":
        raise ValueError(f"clip {index} in {path} is missing source")
    try:
        source_fps = clip.get("source_fps", fps)
        frame_rate(source_fps)
        start = clip_seconds(clip, "start", source_fps)
        end = clip_seconds(clip, "end", source_fps)
        if start < 0 or end < 0:
            raise ValueError("times must be non-negative")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"clip {index} in {path}: {exc}") from exc
    if end <= start:
        raise ValueError(f"clip {index} in {path} has non-positive duration")
    normalized = dict(clip)
    normalized["source"] = source
    normalized["start"] = seconds_to_timestamp(start)
    normalized["end"] = seconds_to_timestamp(end)
    normalized["start_seconds"] = start
    normalized["end_seconds"] = end
    normalized.setdefault("label", clip.get("id") or f"clip_{index:03d}")
    return normalized


def clip_seconds(clip: dict[str, Any], key: str, fps: float = 30.0) -> float:
    """Prefer numeric bounds; legacy display timestamps may be truncated."""
    seconds_key = f"{key}_seconds"
    if seconds_key in clip:
        return timecode_to_seconds(clip[seconds_key], fps=fps)
    if key in clip and clip[key] not in (None, ""):
        return timecode_to_seconds(clip[key], fps=fps)
    raise ValueError(f"clip is missing {key}")
