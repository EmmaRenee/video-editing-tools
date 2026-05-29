"""DaVinci/FFmpeg handoff artifact generation."""

from __future__ import annotations

import json
import os
import re

from .timecode import seconds_to_timecode, timecode_to_seconds


def generate_edl(clips: list[dict], source_file: str, fps: float = 30.0) -> str:
    lines = ["TITLE: Video Editing Export", ""]
    timeline_start = 0.0
    for index, clip in enumerate(clips, 1):
        label = clip.get("label", f"Clip_{index:03d}")
        clip_source = clip.get("source") or source_file
        start = timecode_to_seconds(clip["start"])
        end = timecode_to_seconds(clip["end"])
        duration = max(0.0, end - start)
        timeline_end = timeline_start + duration
        lines.append(f"{index:03d}  {label}     C")
        lines.append(
            f"{seconds_to_timecode(start, fps)} {seconds_to_timecode(end, fps)} "
            f"{seconds_to_timecode(timeline_start, fps)} {seconds_to_timecode(timeline_end, fps)}"
        )
        lines.append("")
        lines.append(f"* FROM CLIP NAME: {clip_source}")
        lines.append("")
        timeline_start = timeline_end
    return "\n".join(lines)


def generate_xml(clips: list[dict], source_file: str, fps: float = 30.0) -> str:
    total_frames = 0
    for clip in clips:
        total_frames += int((timecode_to_seconds(clip["end"]) - timecode_to_seconds(clip["start"])) * fps)
    track = []
    timeline_start = 0
    for index, clip in enumerate(clips, 1):
        label = clip.get("label", f"Clip_{index:03d}")
        clip_source = clip.get("source") or source_file
        start = int(timecode_to_seconds(clip["start"]) * fps)
        end = int(timecode_to_seconds(clip["end"]) * fps)
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
    <duration>{total_frames}</duration>
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
        output = os.path.join(clips_dir, f"{label}.mp4")
        lines.append(
            f'ffmpeg -i "{clip_source}" -ss {clip["start"]} -to {clip["end"]} -c copy "{output}" -y'
        )
    return "\n".join(lines) + "\n"


def export_selection_file(selection_path: str, output_dir: str, fps: float = 30.0) -> list[str]:
    selection_path = os.fspath(selection_path)
    output_dir = os.fspath(output_dir)
    with open(selection_path, encoding="utf-8") as handle:
        data = json.loads(handle.read())
    source = data["source"]
    clips = data.get("clips", [])
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(selection_path))[0]
    paths = [
        os.path.join(output_dir, f"{stem}.edl"),
        os.path.join(output_dir, f"{stem}.xml"),
        os.path.join(output_dir, f"{stem}.m3u"),
        os.path.join(output_dir, f"{stem}_extract.sh"),
    ]
    payloads = [
        generate_edl(clips, source, fps=fps),
        generate_xml(clips, source, fps=fps),
        generate_m3u(clips, source),
        generate_extract_script(clips, source, os.path.join(output_dir, f"{stem}_clips")),
    ]
    for path, payload in zip(paths, payloads):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    os.chmod(paths[3], 0o755)
    return paths
