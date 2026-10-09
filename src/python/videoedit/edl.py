"""DaVinci/FFmpeg handoff artifact generation."""

from __future__ import annotations

import os
import re
import shlex
import time

from .manifests import RunManifest, fingerprint
from .selections import clip_seconds, load_selection
from .timecode import frame_rate, frames_to_timecode, seconds_to_frames, seconds_to_timestamp


def _edl_frame_ranges(clips: list[dict], fps: float):
    cursor = 0
    for index, clip in enumerate(clips, 1):
        start, end = clip_seconds(clip, "start", fps), clip_seconds(clip, "end", fps)
        if start < 0 or end <= start:
            raise ValueError(f"clip {index} requires non-negative start and positive duration")
        source_in, source_out = seconds_to_frames(start, fps), seconds_to_frames(end, fps)
        record_out = cursor + source_out - source_in
        yield index, clip, source_in, source_out, cursor, record_out
        cursor = record_out


def generate_edl(clips: list[dict], source_file: str, fps: float = 30.0) -> str:
    lines = ["TITLE: Video Editing Export", ""]
    for index, clip, source_in, source_out, record_in, record_out in _edl_frame_ranges(clips, fps):
        label = clip.get("label", f"Clip_{index:03d}")
        clip_source = clip.get("source") or source_file
        if source_out <= source_in:
            raise ValueError(f"clip {index} does not span a frame at {fps} fps")
        lines.append(f"{index:03d}  {label}     C")
        lines.append(
            f"{frames_to_timecode(source_in, fps)} {frames_to_timecode(source_out, fps)} "
            f"{frames_to_timecode(record_in, fps)} {frames_to_timecode(record_out, fps)}"
        )
        lines.append("")
        lines.append(f"* FROM CLIP NAME: {clip_source}")
        lines.append("")
    return "\n".join(lines)


def generate_xml(clips: list[dict], source_file: str, fps: float = 30.0) -> str:
    track = []
    timeline_start = 0
    for index, clip in enumerate(clips, 1):
        label = clip.get("label", f"Clip_{index:03d}")
        clip_source = clip.get("source") or source_file
        start = int(clip_seconds(clip, "start", fps) * fps)
        end = int(clip_seconds(clip, "end", fps) * fps)
        duration = max(0, end - start)
        track.append(
            f"""          <generatoritem>
            <name>{label}</name>
            <duration>{duration}</duration>
            <start>{timeline_start}</start>
            <enabled>TRUE</enabled>
            <source><path>{clip_source}</path></source>
            <rate><timebase>{int(fps)}</timebase></rate>
            <in>{start}</in>
            <out>{end}</out>
          </generatoritem>"""
        )
        timeline_start += duration
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <sequence id="Videoedit Highlights">
    <name>Videoedit Generated Edit</name>
    <duration>{timeline_start}</duration>
    <rate><timebase>{int(fps)}</timebase><ntsc>FALSE</ntsc></rate>
    <media><video><track>
{chr(10).join(track)}
    </track></video></media>
  </sequence>
</xmeml>
"""


def generate_m3u(clips: list[dict], source_file: str) -> str:
    lines = ["#EXTM3U"]
    for clip in clips:
        clip_source = clip.get("source") or source_file
        lines.append(f"#EXTINF:{clip.get('duration', '')},{clip.get('label', '')}")
        lines.append(f"#EXTVLCOPT:start-time={clip['start']}")
        lines.append(f"#EXTVLCOPT:stop-time={clip['end']}")
        lines.append(clip_source)
    return "\n".join(lines)


def generate_extract_script(clips: list[dict], source_file: str, clips_dir: str) -> str:
    lines = ["#!/bin/bash", "set -euo pipefail", ""]
    clips_dir = os.fspath(clips_dir)
    os.makedirs(clips_dir, exist_ok=True)
    for index, clip in enumerate(clips, 1):
        clip_source = clip.get("source") or source_file
        label = re.sub(r"[^\w.-]+", "_", clip.get("label", f"clip_{index:03d}"))
        label = label.strip("._-") or f"clip_{index:03d}"
        output = os.path.join(clips_dir, f"{label}.mp4")
        start_seconds = max(0.0, clip_seconds(clip, "start", clip.get("source_fps", 30)))
        end_seconds = max(0.0, clip_seconds(clip, "end", clip.get("source_fps", 30)))
        if end_seconds <= start_seconds:
            raise ValueError(f"clip {label} end must be after start")
        lines.append(
            "ffmpeg -i "
            f"{shlex.quote(os.fspath(clip_source))} "
            f"-ss {shlex.quote(_time_arg(start_seconds))} "
            f"-to {shlex.quote(_time_arg(end_seconds))} "
            f"-c copy {shlex.quote(output)} -y"
        )
    return "\n".join(lines) + "\n"


def _time_arg(seconds: float) -> str:
    return seconds_to_timestamp(seconds)


def export_selection_file(selection_path: str, output_dir: str, fps: float | None = None,
                          manifest_paths: str = "absolute") -> list[str]:
    selection_path = os.fspath(selection_path)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(selection_path))[0]
    paths = [
        os.path.join(output_dir, f"{stem}.edl"),
        os.path.join(output_dir, f"{stem}.xml"),
        os.path.join(output_dir, f"{stem}.m3u"),
        os.path.join(output_dir, f"{stem}_extract.sh"),
    ]
    with RunManifest(os.path.join(output_dir, f"{stem}_handoff.json"), "generate_edl",
                     inputs=[selection_path], config={"fps_override": fps}, path_mode=manifest_paths) as manifest:
        selection = load_selection(selection_path, fps=fps)
        source = selection.source or "mixed"
        clips = selection.clips
        manifest.data["inputs"].extend(fingerprint(source, content=False) for source in sorted({clip["source"] for clip in clips}))
        manifest.data["handoff"] = handoff_metadata(clips, selection.fps)
        before = time.monotonic()
        payloads = [
            generate_edl(clips, source, fps=selection.fps),
            generate_xml(clips, source, fps=selection.fps),
            generate_m3u(clips, source),
            generate_extract_script(clips, source, os.path.join(output_dir, f"{stem}_clips")),
        ]
        for path, payload in zip(paths, payloads):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(payload)
        os.chmod(paths[3], 0o755)
        manifest.record_step("handoff", "generate_edl", {"fps": selection.fps}, {"files": paths}, time.monotonic() - before)
    return paths


def handoff_metadata(clips: list[dict], fps: float, handles: float = 0.0) -> dict:
    sources = []
    rate = float(frame_rate(fps))
    for index, clip, source_in, source_out, record_in, record_out in _edl_frame_ranges(clips, fps):
        start, end = clip_seconds(clip, "start", fps), clip_seconds(clip, "end", fps)
        sources.append({"source": clip["source"], "reel": clip.get("label") or f"Clip_{index:03d}",
                        "event": index, "start_seconds": start, "end_seconds": end,
                        "edl_in": frames_to_timecode(source_in, fps), "edl_out": frames_to_timecode(source_out, fps),
                        "edl_record_in": frames_to_timecode(record_in, fps),
                        "edl_record_out": frames_to_timecode(record_out, fps),
                        "xml_in_frames": int(start * fps), "xml_out_frames": int(end * fps),
                        "timeline_start_seconds": record_in / rate, "assumed_source_fps": fps})
    return {"timeline_fps": fps, "sources": sources, "handles": handles,
            "rounding": {"edl": "nearest_frame_half_up", "xml": "floor_frames"},
            "fps_assumption": "one_nominal_rate_for_all_sources", "editor_verified": False,
            "omitted_features": ["audio_tracks_not_exported", "source_start_timecode_not_applied", "transitions_not_exported"],
            "limitations": ["legacy_edl_event_columns", "legacy_xml_generatoritems", "mixed_rate_relink_unverified"] +
                           (["fractional_rate_legacy_formatting"] if fps != int(fps) else [])}
