"""Independent source metadata for editor handoff, without timeline conversion."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from fractions import Fraction

from .ffmpeg import run_command


@dataclass(frozen=True)
class HandoffMediaInfo:
    path: str
    status: str
    fps: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    timecode: str | None = None
    audio_streams: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _integer(value: object, name: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid {name}; re-probe the source for integer metadata.")
    return value


def _frame_rate(value: object, name: str) -> Fraction:
    message = f"Invalid {name}; re-probe the source for a positive rational frame rate."
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+/[0-9]+", value) is None:
        raise ValueError(message)
    try:
        numerator, denominator = (int(part) for part in value.split("/"))
        if numerator <= 0 or denominator <= 0:
            raise ValueError(message)
        return Fraction(numerator, denominator)
    except ValueError:
        raise ValueError(message) from None


def _tags(container: dict, name: str) -> dict:
    tags = container.get("tags", {})
    if not isinstance(tags, dict):
        raise ValueError(f"Invalid {name}.tags; re-probe the source for tag metadata.")
    return tags


def _timecode_tag(container: dict, name: str) -> str | None:
    value = _tags(container, name).get("timecode")
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9][:;][0-9]{2}", value):
            return value
    raise ValueError("Invalid timecode tag; verify the source timecode metadata before handoff.")


def _is_timecode_stream(stream: dict) -> bool:
    return stream.get("codec_tag_string") == "tmcd" or stream.get("codec_name") == "tmcd"


def _duration(video: dict, warnings: list[str]) -> float | None:
    value = video.get("duration")
    if value in (None, "", "N/A") and video.get("duration_ts") is not None:
        ticks = _integer(video["duration_ts"], "video.duration_ts", minimum=0)
        timebase = _frame_rate(video.get("time_base"), "video.time_base")
        value = ticks * timebase
    if value in (None, "", "N/A"):
        warnings.append("Video stream duration is unavailable; container duration does not establish video extent.")
        return None
    message = "Invalid duration; re-probe the source for finite, nonnegative seconds."
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Fraction)):
        raise ValueError(message)
    try:
        duration = float(value)
    except (ValueError, OverflowError):
        raise ValueError(message) from None
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(message)
    return duration


def _audio_info(stream: dict, warnings: list[str]) -> dict:
    index = _integer(stream.get("index"), "audio.index", minimum=0)
    channels = _integer(stream.get("channels"), "audio.channels")
    rate = stream.get("sample_rate")
    if rate in (None, "", "N/A"):
        rate = None
        warnings.append("Audio sample_rate is unavailable; verify audio metadata before handoff.")
    else:
        if isinstance(rate, str) and re.fullmatch(r"[0-9]+", rate):
            try:
                rate = int(rate)
            except ValueError:
                raise ValueError("Invalid audio.sample_rate; re-probe audio metadata.") from None
        rate = _integer(rate, "audio.sample_rate")
    codec = stream.get("codec_name")
    if codec in (None, "", "N/A", "unknown"):
        codec = None
        warnings.append("Audio codec is unknown; verify editor codec support before handoff.")
    elif not isinstance(codec, str):
        raise ValueError("Invalid audio.codec_name; re-probe audio codec metadata.")
    return {"index": index, "channels": channels, "sample_rate": rate, "codec": codec}


def _parse_media(path: str, data: object) -> HandoffMediaInfo:
    if not isinstance(data, dict):
        raise ValueError("Invalid ffprobe JSON object; re-probe the source.")
    streams = data.get("streams")
    fmt = data.get("format", {})
    if not isinstance(streams, list) or any(not isinstance(stream, dict) for stream in streams):
        raise ValueError("Invalid ffprobe streams metadata; re-probe the source.")
    if not isinstance(fmt, dict):
        raise ValueError("Invalid ffprobe format metadata; re-probe the source.")

    video = None
    for stream in streams:
        if stream.get("codec_type") != "video" or _is_timecode_stream(stream):
            continue
        disposition = stream.get("disposition", {})
        if not isinstance(disposition, dict):
            raise ValueError("Invalid video.disposition; re-probe video stream metadata.")
        attached_pic = disposition.get("attached_pic", 0)
        if type(attached_pic) is not int or attached_pic not in (0, 1):
            raise ValueError("Invalid video.disposition.attached_pic; re-probe video metadata.")
        if not attached_pic:
            video = stream
            break
    if video is None:
        raise ValueError("No real video stream found; select a source containing video frames.")

    warnings: list[str] = []
    fps = video.get("r_frame_rate")
    rational = _frame_rate(fps, "video.r_frame_rate")
    width = _integer(video.get("width"), "video.width")
    height = _integer(video.get("height"), "video.height")
    average = video.get("avg_frame_rate")
    if average in (None, "", "N/A", "0/0"):
        warnings.append("Video avg_frame_rate is unavailable; verify source frame timing before handoff.")
    elif _frame_rate(average, "video.avg_frame_rate") != rational:
        warnings.append(
            "r_frame_rate and avg_frame_rate differ: potential variable-rate source; "
            "verify frame timing before handoff."
        )

    duration = _duration(video, warnings)
    timecode = _timecode_tag(video, "video")
    if timecode is None:
        timecode = _timecode_tag(fmt, "format")
    if timecode is None:
        for stream in streams:
            if stream.get("codec_type") == "data" or _is_timecode_stream(stream):
                timecode = _timecode_tag(stream, "data")
                if timecode is not None:
                    break
    if timecode is None:
        warnings.append("Source timecode is unavailable; confirm the editor source timecode before handoff.")

    audio_streams: list[dict] = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "audio":
            audio_streams.append(_audio_info(stream, warnings))
        elif kind == "data" and not _is_timecode_stream(stream):
            warnings.append("Unsupported or unknown data stream metadata; inspect editor handling separately.")
        elif kind not in ("video", "data"):
            warnings.append("Unsupported or unknown stream metadata; inspect editor handling separately.")

    return HandoffMediaInfo(
        path=path, status="ok", fps=fps, duration=duration, width=width, height=height,
        timecode=timecode, audio_streams=audio_streams, warnings=warnings,
    )


def probe_handoff_media(path: str, timeout: int = 60) -> HandoffMediaInfo:
    """Probe local metadata within a positive timeout; never certify CFR or resolve timecode.

    Invalid required fields discard all partial metadata. Missing optional metadata
    stays unknown, with warnings. Diagnostics never include tool output or paths.
    """
    if type(timeout) is not int or timeout <= 0:
        return HandoffMediaInfo(
            path=path, status="error", warnings=["Use a positive integer timeout to bound ffprobe."],
        )
    try:
        exists = os.path.isfile(path)
    except (OSError, TypeError, ValueError):
        return HandoffMediaInfo(
            path=path, status="error", warnings=["Cannot inspect source file; verify its local availability."],
        )
    if not exists:
        return HandoffMediaInfo(
            path=path, status="missing",
            warnings=["Source file is missing or not a regular file; verify its local availability."],
        )

    args = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    try:
        result = run_command(args, timeout=timeout)
    except TimeoutError:
        warning = "ffprobe timed out; verify local source availability or increase the bounded timeout."
    except FileNotFoundError:
        warning = "ffprobe is unavailable; install FFmpeg and ensure ffprobe is on PATH."
    except PermissionError:
        warning = "ffprobe could not run; verify executable and source file permissions."
    except OSError:
        warning = "ffprobe could not run; verify installation and local source access."
    else:
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
            except (ValueError, TypeError, RecursionError):
                warning = "ffprobe returned invalid JSON; verify the installation and re-probe the source."
            else:
                try:
                    return _parse_media(path, data)
                except ValueError as exc:
                    warning = str(exc)
        elif result.returncode == 127:
            warning = "ffprobe is unavailable; install FFmpeg and ensure ffprobe is on PATH."
        else:
            warning = "ffprobe failed; verify source readability, file integrity, and FFmpeg format support."
    return HandoffMediaInfo(path=path, status="error", warnings=[warning])
