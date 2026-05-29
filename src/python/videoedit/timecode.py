"""Time formatting helpers."""

from __future__ import annotations


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_to_timecode(seconds: float, fps: float = 30.0) -> str:
    seconds = max(0.0, float(seconds or 0))
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    frames = int(round((seconds - whole) * fps)) % max(1, int(round(fps)))
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def timecode_to_seconds(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 4:
        hours, minutes, seconds, _frames = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return float(value)


def clamp_window(start: float, end: float, duration: float) -> tuple[float, float]:
    duration = max(0.0, float(duration or 0))
    start = max(0.0, min(float(start), duration))
    end = max(start, min(float(end), duration))
    return start, end
