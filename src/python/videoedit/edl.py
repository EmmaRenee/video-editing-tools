"""DaVinci/FFmpeg handoff artifact generation."""

from __future__ import annotations

import os
import re
import shlex
import time
from pathlib import Path
import xml.etree.ElementTree as ET

from .handoff import HandoffTimeline, build_handoff_timeline, drop_timecode, xml_rate
from .manifests import RunManifest, fingerprint
from .selections import clip_seconds, load_selection
from .timecode import frames_to_timecode, seconds_to_frames, seconds_to_timestamp


def _single_line(value: str) -> str:
    return " ".join(str(value).splitlines())


def generate_edl(clips: list[dict], source_file: str, fps: float = 30.0,
                 *, timeline: HandoffTimeline | None = None) -> str:
    timeline = timeline or build_handoff_timeline(clips, source_file, fps)
    if not timeline.edl_supported:
        reasons = ", ".join(value for value in timeline.limitations if value.startswith("edl_unsupported_"))
        raise ValueError(f"CMX EDL unsupported ({reasons.replace('_', '-')}); use XML")
    drop = bool(timeline.clips and timeline.clips[0].source.drop_frame)
    tc = drop_timecode if drop else frames_to_timecode
    lines = ["TITLE: Video Editing Export", f"FCM: {'DROP FRAME' if drop else 'NON-DROP FRAME'}", ""]
    for clip in timeline.clips:
        offset = clip.source.timecode_frames
        lines.append(f"{clip.event:03d}  {clip.source.reel:8} V     C        "
                     f"{tc(offset + clip.source_in, timeline.rate)} {tc(offset + clip.source_out, timeline.rate)} "
                     f"{tc(clip.record_in, timeline.rate)} {tc(clip.record_out, timeline.rate)}")
        lines.extend([f"* FROM CLIP NAME: {_single_line(Path(clip.source.path).name)}",
                      f"* FROM FILE: {_single_line(clip.source.path)}",
                      f"* COMMENT: {_single_line(clip.label)}", ""])
    return "\n".join(lines)


def _text(parent, name, value):
    node = ET.SubElement(parent, name)
    node.text = str(value)
    return node


def _rate(parent, rate):
    timebase, ntsc = xml_rate(rate)
    node = ET.SubElement(parent, "rate")
    _text(node, "timebase", timebase)
    _text(node, "ntsc", "TRUE" if ntsc else "FALSE")


def generate_xml(clips: list[dict], source_file: str, fps: float = 30.0,
                 *, timeline: HandoffTimeline | None = None) -> str:
    timeline = timeline or build_handoff_timeline(clips, source_file, fps)
    root = ET.Element("xmeml", version="4")
    sequence = ET.SubElement(root, "sequence", id="videoedit-sequence")
    _text(sequence, "name", "Videoedit Generated Edit")
    _text(sequence, "duration", timeline.duration_frames)
    _rate(sequence, timeline.rate)
    media = ET.SubElement(sequence, "media")
    video_track = ET.SubElement(ET.SubElement(media, "video"), "track")
    audio_tracks, emitted_files = {}, set()

    def file_element(parent, clip):
        source, info = clip.source, clip.source.info
        node = ET.SubElement(parent, "file", id=source.file_id)
        if source.file_id in emitted_files:
            return
        emitted_files.add(source.file_id)
        _text(node, "name", Path(source.path).name)
        _text(node, "pathurl", Path(source.path).as_uri())
        # Unknown media needs a minimum extent, not an invented probed duration.
        extent = max(item.source_out for item in timeline.clips if item.source.path == source.path)
        _text(node, "duration", seconds_to_frames(info.duration, source.rate) if info.duration is not None else extent)
        _rate(node, source.rate)
        timecode = ET.SubElement(node, "timecode")
        _rate(timecode, source.rate)
        _text(timecode, "string", source.timecode)
        _text(timecode, "frame", source.timecode_frames)
        _text(timecode, "displayformat", "DF" if source.drop_frame else "NDF")
        _text(ET.SubElement(timecode, "reel"), "name", source.reel)
        file_media = ET.SubElement(node, "media")
        video = ET.SubElement(file_media, "video")
        characteristics = ET.SubElement(video, "samplecharacteristics")
        _rate(characteristics, source.rate)
        if info.width is not None and info.height is not None:
            _text(characteristics, "width", info.width)
            _text(characteristics, "height", info.height)
        streams = info.audio_streams
        if len(streams) == 1 and streams[0].get("channels") in {1, 2}:
            audio = ET.SubElement(file_media, "audio")
            _text(audio, "channelcount", streams[0]["channels"])
            if streams[0].get("sample_rate"):
                _text(ET.SubElement(audio, "samplecharacteristics"), "samplerate", streams[0]["sample_rate"])

    def item(parent, clip, item_id, kind, channel=None):
        node = ET.SubElement(parent, "clipitem", id=item_id)
        _text(node, "name", clip.label)
        _text(node, "duration", clip.source_out - clip.source_in)
        _rate(node, clip.source.rate)
        _text(node, "start", clip.record_in)
        _text(node, "end", clip.record_out)
        _text(node, "in", clip.source_in)
        _text(node, "out", clip.source_out)
        _text(node, "enabled", "TRUE")
        file_element(node, clip)
        source_track = ET.SubElement(node, "sourcetrack")
        _text(source_track, "mediatype", kind)
        _text(source_track, "trackindex", channel or 1)
        return node

    audio_media = None
    for clip in timeline.clips:
        video_id = f"clip-{clip.event}-v"
        nodes = [(item(video_track, clip, video_id, "video"), video_id, "video", 1)]
        streams = clip.source.info.audio_streams
        channels = streams[0]["channels"] if len(streams) == 1 and streams[0].get("channels") in {1, 2} else 0
        for channel in range(1, channels + 1):
            if audio_media is None:
                audio_media = ET.SubElement(media, "audio")
            if channel not in audio_tracks:
                audio_tracks[channel] = ET.SubElement(audio_media, "track")
            audio_id = f"clip-{clip.event}-a{channel}"
            nodes.append((item(audio_tracks[channel], clip, audio_id, "audio", channel), audio_id, "audio", channel))
        for node, _, _, _ in nodes:
            for _, target_id, kind, channel in nodes:
                link = ET.SubElement(node, "link")
                _text(link, "linkclipref", target_id)
                _text(link, "mediatype", kind)
                _text(link, "trackindex", channel)
                if kind == "audio" and channels == 2:
                    _text(link, "groupindex", 1)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def generate_m3u(clips: list[dict], source_file: str) -> str:
    lines = ["#EXTM3U"]
    for clip in clips:
        clip_source = clip.get("source") or source_file
        fps = clip.get("source_fps", 30)
        start, end = clip_seconds(clip, "start", fps), clip_seconds(clip, "end", fps)
        lines.append(f"#EXTINF:{end - start},{_single_line(clip.get('label', ''))}")
        lines.append(f"#EXTVLCOPT:start-time={start}")
        lines.append(f"#EXTVLCOPT:stop-time={end}")
        if any(char in str(clip_source) for char in ("\n", "\r", "\x00")):
            raise ValueError("playlist source must not contain control characters")
        lines.append(str(clip_source))
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
        timeline = build_handoff_timeline(clips, source, selection.fps,
                                          base_dir=str(Path(selection_path).resolve().parent),
                                          original_clips=selection.raw_clips)
        manifest.data["inputs"].extend(fingerprint(path, content=False) for path in sorted({clip.source.path for clip in timeline.clips}))
        manifest.data["handoff"] = timeline.to_dict()
        manifest.data["warnings"].extend(timeline.warnings)
        manifest.data["partial"] = bool(set(timeline.limitations) - {"edl_audio_not_exported"})
        before = time.monotonic()
        if timeline.edl_supported:
            edl = generate_edl(clips, source, fps=selection.fps, timeline=timeline)
        else:
            # Preserve the four-file API, but never disguise an unsupported EDL as an edit.
            edl = ("TITLE: Video Editing Export - NOT AN IMPORTABLE EDIT\n"
                   "* NO EDIT EVENTS: CMX cannot represent this timeline safely; use XML.\n" +
                   "".join(f"* {reason}\n" for reason in timeline.limitations if reason.startswith("edl_unsupported_")))
        resolved_clips = [{**clip, "source": item.source.path, "source_fps": str(item.source.rate)}
                          for clip, item in zip(clips, timeline.clips)]
        payloads = [
            edl,
            generate_xml(clips, source, fps=selection.fps, timeline=timeline),
            generate_m3u(resolved_clips, source),
            generate_extract_script(resolved_clips, source, os.path.join(output_dir, f"{stem}_clips")),
        ]
        for path, payload in zip(paths, payloads):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(payload)
        os.chmod(paths[3], 0o755)
        manifest.record_step("handoff", "generate_edl", {"fps": selection.fps},
                             {"files": paths, "warnings": list(timeline.warnings),
                              "edl_supported": timeline.edl_supported}, time.monotonic() - before)
    return paths


def handoff_metadata(clips: list[dict], fps: float, handles: float = 0.0) -> dict:
    return build_handoff_timeline(clips, "mixed", fps).to_dict(handles)
