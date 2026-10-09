"""Time formatting helpers."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import math
import re


def frame_rate(fps: float | str) -> Fraction:
    """Resolve conventional decimal NTSC aliases to their exact media rates."""
    try:
        if isinstance(fps, bool):
            raise ValueError
        rate = Fraction(str(fps))
        if rate <= 0 or not math.isfinite(float(rate)) or float(rate) == 0:
            raise ValueError
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("fps must be a finite positive number or fraction") from exc
    for nominal in (24, 30, 48, 60, 120):
        exact = Fraction(nominal * 1000, 1001)
        if abs(float(rate) - float(exact)) < 0.0005:
            return exact
    return rate


def seconds_to_timestamp(seconds: float) -> str:
    """Format elapsed time for FFmpeg without dropping fractional seconds."""
    seconds = _finite_seconds(seconds)
    if seconds < 0:
        raise ValueError("timestamp must be non-negative")
    value = Decimal(str(seconds))
    whole = int(value)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    fraction = format(value - whole, "f").partition(".")[2].rstrip("0")
    base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{base}.{fraction}" if fraction else base


def seconds_to_frames(seconds: float, fps: float = 30.0) -> int:
    """Round half up with two float ULPs of tie tolerance, capped at 1e-9 frames."""
    finite = _finite_seconds(seconds)
    exact = Fraction(seconds) if isinstance(seconds, (int, float)) else Fraction(finite)
    value = max(Fraction(0), exact) * frame_rate(fps)
    whole = value.numerator // value.denominator
    if value - whole < Fraction(1, 2):
        gap = Fraction(1, 2) - (value - whole)
        if gap <= Fraction(1, 10 ** 9):
            try:
                tolerance = min(1e-9, 2 * math.ulp(float(value)))
            except OverflowError:
                tolerance = 0.0
            if float(gap) <= tolerance:
                return whole + 1
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def frames_to_timecode(frames: int, fps: float = 30.0) -> str:
    rate = frame_rate(fps)
    nominal = max(1, round(float(rate)))
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
        raise ValueError("frame count must be a non-negative integer")
    seconds, frame = divmod(frames, nominal)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frame:02d}"


def _finite_seconds(value: str | float | int) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError
        return seconds
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("time must be a finite number") from exc


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_to_timecode(seconds: float, fps: float = 30.0) -> str:
    """Return non-drop-frame SMPTE from elapsed seconds at the media rate."""
    return frames_to_timecode(seconds_to_frames(seconds, fps), fps)


def timecode_to_seconds(value: str | float | int, fps: float = 30.0) -> float:
    if isinstance(value, (int, float)):
        return _finite_seconds(value)
    text = str(value).strip()
    smpte = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})([:;])(\d{1,3})", text)
    if smpte:
        hours, minutes, seconds, separator, frames = smpte.groups()
        hours, minutes, seconds, frames = map(int, (hours, minutes, seconds, frames))
        rate = frame_rate(fps)
        nominal = max(1, round(float(rate)))
        if minutes >= 60 or seconds >= 60 or frames >= nominal:
            raise ValueError("invalid SMPTE timecode components")
        count = ((hours * 3600 + minutes * 60 + seconds) * nominal) + frames
        if separator == ";":
            if rate not in (Fraction(30000, 1001), Fraction(60000, 1001)):
                raise ValueError("drop-frame timecode requires 29.97 or 59.94 fps")
            dropped = nominal // 15
            if minutes % 10 and seconds == 0 and frames < dropped:
                raise ValueError("invalid skipped drop-frame timecode label")
            total_minutes = hours * 60 + minutes
            count -= dropped * (total_minutes - total_minutes // 10)
        return float(Fraction(count, 1) / rate)
    if ":" in text or ";" in text:
        elapsed = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)", text)
        if not elapsed:
            raise ValueError("time must be seconds, HH:MM:SS[.fraction], or HH:MM:SS:FF")
        hours, minutes, seconds = elapsed.groups()
        if int(minutes) >= 60 or float(seconds) >= 60:
            raise ValueError("invalid elapsed timestamp components")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return _finite_seconds(text)


def clamp_window(start: float, end: float, duration: float) -> tuple[float, float]:
    duration = max(0.0, float(duration or 0))
    start = max(0.0, min(float(start), duration))
    end = max(start, min(float(end), duration))
    return start, end
