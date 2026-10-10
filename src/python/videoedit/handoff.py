"""Shared, native-rate timeline normalization for editor handoff writers."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path
import re

from .selections import clip_seconds
from .source_info import HandoffMediaInfo, probe_handoff_media
from .timecode import frame_rate, frames_to_timecode, seconds_to_frames, timecode_to_seconds

HANDOFF_SCHEMA = "videoedit.handoff.v1"
DROP_RATES = {Fraction(30000, 1001), Fraction(60000, 1001)}
CMX_RATES = {Fraction(value) for value in (24, 25, 30, 48, 50, 60)} | {
    Fraction(value, 1001) for value in (24000, 30000, 48000, 60000)}


def _valid_xml_text(value: str) -> bool:
    return all(char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or
               0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF for char in value)


def xml_rate(rate: Fraction) -> tuple[int, bool]:
    if rate.denominator == 1:
        return rate.numerator, False
    nominal = round(rate)
    if nominal in {24, 30, 48, 60, 120} and rate == Fraction(nominal * 1000, 1001):
        return nominal, True
    raise ValueError(f"FCP7 XML cannot represent frame rate {rate}")


def drop_timecode(frames: int, rate: Fraction) -> str:
    nominal = round(rate)
    if rate not in DROP_RATES:
        raise ValueError("drop-frame timecode requires 30000/1001 or 60000/1001")
    dropped = nominal // 15
    ten_minutes = nominal * 600 - dropped * 9
    minute = nominal * 60 - dropped
    blocks, remaining = divmod(frames, ten_minutes)
    labels = frames + dropped * 9 * blocks
    if remaining >= dropped:
        labels += dropped * ((remaining - dropped) // minute)
    return frames_to_timecode(labels, nominal).rsplit(":", 1)[0] + ";" + f"{labels % nominal:02d}"


@dataclass(frozen=True)
class HandoffSource:
    path: str
    reel: str
    file_id: str
    rate: Fraction
    timecode: str
    timecode_frames: int
    drop_frame: bool
    info: HandoffMediaInfo


@dataclass(frozen=True)
class HandoffClip:
    event: int
    label: str
    source: HandoffSource
    start_seconds: float
    end_seconds: float
    source_in: int
    source_out: int
    record_in: int
    record_out: int


@dataclass(frozen=True)
class HandoffTimeline:
    rate: Fraction
    requested_fps: float
    clips: tuple[HandoffClip, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def duration_frames(self) -> int:
        return self.clips[-1].record_out if self.clips else 0

    @property
    def edl_supported(self) -> bool:
        return not any(value.startswith("edl_unsupported_") for value in self.limitations)

    @property
    def edl_drop_frame(self) -> bool:
        return bool(self.clips and self.clips[0].source.drop_frame and self.rate in DROP_RATES)

    def to_dict(self, handles: float = 0.0) -> dict:
        rows = []
        for clip in self.clips:
            source = clip.source
            tc = drop_timecode if source.drop_frame else frames_to_timecode
            record_tc = drop_timecode if self.edl_drop_frame else frames_to_timecode
            rows.append({"source": source.path, "reel": source.reel, "label": clip.label,
                         "file_id": source.file_id, "event": clip.event,
                         "pathurl": Path(source.path).as_uri(), "metadata_status": source.info.status,
                         "source_fps": str(source.rate), "source_timecode": source.timecode,
                         "source_timecode_frames": source.timecode_frames,
                         "duration_seconds": source.info.duration,
                         "width": source.info.width, "height": source.info.height,
                         "audio_streams": source.info.audio_streams,
                         "start_seconds": clip.start_seconds, "end_seconds": clip.end_seconds,
                         "xml_in_frames": clip.source_in, "xml_out_frames": clip.source_out,
                         "record_in_frames": clip.record_in, "record_out_frames": clip.record_out,
                         "edl_in": tc(source.timecode_frames + clip.source_in, source.rate) if self.edl_supported else None,
                         "edl_out": tc(source.timecode_frames + clip.source_out, source.rate) if self.edl_supported else None,
                         "edl_record_in": record_tc(clip.record_in, self.rate) if self.edl_supported else None,
                         "edl_record_out": record_tc(clip.record_out, self.rate) if self.edl_supported else None,
                         "timeline_start_seconds": clip.record_in / float(self.rate)})
        return {"schema_version": HANDOFF_SCHEMA, "timeline_fps": self.requested_fps,
                "timeline_rate": str(self.rate), "duration_frames": self.duration_frames,
                "sources": rows, "handles": handles, "edl_supported": self.edl_supported,
                "rounding": {"edl": "nearest_frame_half_up", "xml": "nearest_frame_half_up"},
                "fps_assumption": "native_source_rates_when_available",
                "editor_verified": False, "warnings": list(self.warnings),
                "omitted_features": list(self.limitations), "limitations": list(self.limitations)}


def _source_path(value: str, base_dir: str | None) -> str:
    if not value or not _valid_xml_text(value) or any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("handoff source must be a local media path without control characters")
    if "://" in value:
        raise ValueError("handoff requires a local media path, not a URL")
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir:
        relative = Path(base_dir) / path
        if path.exists() and relative.exists() and path.resolve() != relative.resolve():
            raise ValueError("ambiguous relative handoff source; provide an absolute path")
        if not path.exists():
            path = relative
    resolved = str(path.resolve())
    if not _valid_xml_text(resolved) or any(char in resolved for char in ("\r", "\n")):
        raise ValueError("handoff resolved source contains characters forbidden in XML or line-based exports")
    return resolved


def build_handoff_timeline(clips: list[dict], source_file: str, fps=30,
                           *, base_dir: str | None = None,
                           original_clips: list[dict] | None = None,
                           media_info: dict[str, HandoffMediaInfo] | None = None,
                           require_record_frame: bool = True) -> HandoffTimeline:
    rate = frame_rate(fps)
    sources, reels = {}, {}
    rows, warnings, limitations = [], [], []

    def warn(code: str, event: int) -> None:
        warnings.append(f"event_{event:03d}: {code}")
        if code not in limitations:
            limitations.append(code)

    cursor = 0
    for event, clip in enumerate(clips, 1):
        path = _source_path(str(clip.get("source") or source_file), base_dir)
        if path not in sources:
            info = media_info[path] if media_info is not None and path in media_info else probe_handoff_media(path)
            source_rate = frame_rate(info.fps or clip.get("source_fps") or fps)
            if not info.fps:
                warn("source_fps_assumed", event)
            if info.status != "ok":
                warn("source_metadata_unavailable", event)
            if info.warnings:
                warn("source_probe_warning", event)
                warnings.extend(f"event_{event:03d}: {message}" for message in info.warnings)
            tc_string = clip.get("source_timecode") or info.timecode
            if clip.get("source_timecode") and info.timecode and clip["source_timecode"] != info.timecode:
                raise ValueError(f"clip {event} source_timecode conflicts with media metadata")
            if not tc_string:
                tc_string = "00:00:00:00"
                warn("source_timecode_assumed_zero", event)
            if not isinstance(tc_string, str) or not re.fullmatch(r"\d{2}:\d{2}:\d{2}[:;]\d{2}", tc_string):
                raise ValueError(f"clip {event} has invalid source_timecode")
            try:
                tc_frames = seconds_to_frames(timecode_to_seconds(tc_string, source_rate), source_rate)
            except ValueError as error:
                raise ValueError(f"clip {event} has invalid source_timecode") from error
            digest = hashlib.sha256(path.encode("utf-8")).hexdigest().upper()
            reel = str(clip.get("reel") or "V" + digest[:7])
            if not re.fullmatch(r"[A-Z0-9_]{1,8}", reel):
                raise ValueError(f"clip {event} reel must contain 1-8 uppercase letters, digits or underscores")
            if reel in reels and reels[reel] != path:
                raise ValueError(f"clip {event} reel collides with a different source")
            reels[reel] = path
            sources[path] = HandoffSource(path, reel, "file-" + digest[:16], source_rate,
                                          str(tc_string), tc_frames, ";" in str(tc_string), info)
        source = sources[path]
        if "source_fps" in clip and frame_rate(clip["source_fps"]) != source.rate:
            raise ValueError(f"clip {event} source_fps conflicts with media metadata")
        if "source_timecode" in clip and clip["source_timecode"] != source.timecode:
            raise ValueError(f"clip {event} source_timecode conflicts with media metadata")
        if "reel" in clip and clip["reel"] != source.reel:
            raise ValueError(f"clip {event} reel conflicts with source metadata")
        if original_clips is not None and source.rate != rate:
            original = original_clips[event - 1]
            ambiguous = "source_fps" not in original and any(
                f"{key}_seconds" not in original and isinstance(original.get(key), str) and
                len(original[key].replace(";", ":").split(":")) == 4 for key in ("start", "end"))
            if ambiguous:
                raise ValueError(f"clip {event} SMPTE bounds require explicit source_fps for mixed-rate media")
        start = clip_seconds(clip, "start", source.rate)
        end = clip_seconds(clip, "end", source.rate)
        if start < 0 or end <= start:
            raise ValueError(f"clip {event} requires non-negative start and positive duration")
        source_in, source_out = seconds_to_frames(start, source.rate), seconds_to_frames(end, source.rate)
        if source_out <= source_in:
            raise ValueError(f"clip {event} does not span a source frame")
        if source.info.duration is not None and end > source.info.duration + 0.5 / float(source.rate):
            raise ValueError(f"clip {event} end exceeds media duration")
        if source.info.duration is not None and source_out > seconds_to_frames(source.info.duration, source.rate):
            raise ValueError(f"clip {event} rounded end exceeds video duration in frames")
        record_duration = seconds_to_frames(Fraction(source_out - source_in, 1) / source.rate, rate)
        if record_duration <= 0 and require_record_frame:
            raise ValueError(f"clip {event} does not span a timeline frame")
        label = str(clip.get("label") or f"Clip_{event:03d}")
        if not _valid_xml_text(label):
            raise ValueError(f"clip {event} label contains characters forbidden in XML")
        rows.append(HandoffClip(event, label, source,
                                start, end, source_in, source_out, cursor, cursor + record_duration))
        cursor += record_duration
        if source.rate != rate:
            warn("edl_unsupported_mixed_rate", event)
        if source.rate not in CMX_RATES or rate not in CMX_RATES:
            warn("edl_unsupported_rate", event)
        if len(source.info.audio_streams) > 1 or any(stream.get("channels") not in {1, 2} for stream in source.info.audio_streams):
            warn("unsupported_audio_layout", event)
        elif source.info.audio_streams:
            warn("edl_audio_not_exported", event)
        if clip.get("transition") or clip.get("transitions"):
            warn("transitions_not_exported", event)
        if clip.get("speed", 1) != 1 or clip.get("retime"):
            warn("retiming_not_exported", event)
        if clip.get("compound") or clip.get("effects"):
            warn("compound_or_effects_not_exported", event)
        source_day = round(source.rate) * 86400 - (round(source.rate) // 15) * 1296 if source.drop_frame else round(source.rate) * 86400
        record_drop = rows[0].source.drop_frame and rate in DROP_RATES
        record_day = round(rate) * 86400 - (round(rate) // 15) * 1296 if record_drop else round(rate) * 86400
        if event > 999 or source.timecode_frames + source_out >= source_day or cursor >= record_day:
            warn("edl_unsupported_event_or_timecode_range", event)
    if len({clip.source.drop_frame for clip in rows}) > 1:
        warn("edl_unsupported_mixed_timecode_modes", 1)
    requested_fps = float(rate) if "/" in str(fps) else float(fps)
    return HandoffTimeline(rate, requested_fps, tuple(rows), tuple(warnings), tuple(limitations))
