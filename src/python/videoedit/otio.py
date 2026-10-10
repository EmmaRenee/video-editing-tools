"""Optional, source-aware OpenTimelineIO export without a shoot database."""

from __future__ import annotations

from fractions import Fraction
import importlib
import os
from pathlib import Path
import tempfile
import time

from .handoff import HandoffTimeline, _source_path, build_handoff_timeline
from .manifests import RunManifest, fingerprint
from .provenance import library_version
from .selections import load_selection
from .timecode import seconds_to_frames

OTIO_SCHEMA = "videoedit.otio.v1"
OTIO_INSTALL = 'Install OTIO support: python -m pip install "videoedit[editor]"'


def _require_otio():
    try:
        return importlib.import_module("opentimelineio")
    except ImportError as error:
        raise RuntimeError(OTIO_INSTALL) from error


def _details(timeline: HandoffTimeline) -> dict:
    limitations = [code for code in timeline.limitations if not code.startswith("edl_")]
    rows, cursor = [], Fraction(0)
    for clip in timeline.clips:
        duration = Fraction(clip.source_out - clip.source_in, 1) / clip.source.rate
        delta = duration - Fraction(clip.record_out - clip.record_in, 1) / timeline.rate
        if delta and "native_duration_differs_from_quantized_record" not in limitations:
            limitations.append("native_duration_differs_from_quantized_record")
        rows.append({"event": clip.event, "start_seconds": float(cursor),
                     "duration_seconds": float(duration), "record_quantization_delta_seconds": float(delta)})
        cursor += duration
    return {"schema_version": OTIO_SCHEMA, "timeline_rate": str(timeline.rate),
            "duration_seconds": float(cursor), "placements": rows,
            "limitations": limitations, "editor_verified": False,
            "rounding": "native_source_frames_without_implicit_retime",
            "provider": {"name": "opentimelineio", "version": library_version("opentimelineio")}}


def generate_otio(timeline: HandoffTimeline, *, name: str = "Videoedit Generated Edit") -> str:
    """Serialize cut-only native media-time ranges and explicit supported audio."""
    otio = _require_otio()
    rt, tr = otio.opentime.RationalTime, otio.opentime.TimeRange
    result = otio.schema.Timeline(name=name, global_start_time=rt(0, float(timeline.rate)),
                                  metadata={"videoedit": _details(timeline)})
    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    audio = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    has_audio = False
    for clip in timeline.clips:
        source, info = clip.source, clip.source.info
        rate = float(source.rate)
        duration = rt(clip.source_out - clip.source_in, rate)
        source_range = tr(rt(source.timecode_frames + clip.source_in, rate), duration)
        available = (tr(rt(source.timecode_frames, rate), rt(seconds_to_frames(info.duration, source.rate), rate))
                     if info.duration is not None else None)
        metadata = {"event": clip.event, "reel": source.reel, "source_rate": str(source.rate),
                    "source_timecode": source.timecode, "source_timecode_frames": source.timecode_frames,
                    "source_offset_in_frames": clip.source_in, "source_offset_out_frames": clip.source_out}

        def media_reference():
            return otio.schema.ExternalReference(target_url=Path(source.path).as_uri(), available_range=available,
                                                  metadata={"videoedit": metadata})

        video.append(otio.schema.Clip(name=clip.label, media_reference=media_reference(),
                                      source_range=source_range, metadata={"videoedit": metadata}))
        streams = info.audio_streams
        channels = streams[0].get("channels") if len(streams) == 1 else None
        if channels in {1, 2}:
            has_audio = True
            audio.append(otio.schema.Clip(name=clip.label, media_reference=media_reference(),
                                          source_range=source_range,
                                          metadata={"videoedit": {**metadata, "audio_channels": channels,
                                                                   "audio_sample_rate": streams[0].get("sample_rate")}}))
        else:
            audio.append(otio.schema.Gap(duration=duration))
    result.tracks.append(video)
    if has_audio:
        result.tracks.append(audio)
    return otio.adapters.write_to_string(result, "otio_json")


def _atomic_write(path: Path, payload: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def export_otio_file(selection_path: str, output: str, fps: float | None = None,
                     manifest_paths: str = "absolute") -> dict:
    """Export selection-compatible JSON (including rough-cut plans) to .otio."""
    selection_path, path = os.fspath(selection_path), Path(output)
    if path.suffix.lower() != ".otio":
        raise ValueError("OTIO output must have a .otio extension")
    manifest_path = path.with_name(path.stem + "_otio_handoff.json")
    destinations = {path.resolve(), manifest_path.resolve()}
    if Path(selection_path).resolve() in destinations:
        raise ValueError("OTIO output and manifest must not overwrite the selection input")
    selection = load_selection(selection_path, fps=fps)
    base_dir = str(Path(selection_path).resolve().parent)
    for clip in selection.clips:
        if Path(_source_path(clip.get("source") or selection.source, base_dir)) in destinations:
            raise ValueError("OTIO output and manifest must not overwrite source media")
    path.parent.mkdir(parents=True, exist_ok=True)
    with RunManifest(str(manifest_path), "generate_otio", inputs=[selection_path],
                     config={"fps_override": fps}, path_mode=manifest_paths) as manifest:
        _require_otio()
        timeline = build_handoff_timeline(selection.clips, selection.source or "mixed", selection.fps,
                                          base_dir=base_dir,
                                          original_clips=selection.raw_clips, require_record_frame=False)
        details = _details(timeline)
        manifest.data["inputs"].extend(fingerprint(source, content=False)
                                       for source in sorted({clip.source.path for clip in timeline.clips}))
        manifest.data["handoff"] = timeline.to_dict()
        manifest.data["otio"] = details
        manifest.data["warnings"].extend(details["limitations"])
        manifest.data["partial"] = bool(details["limitations"])
        before = time.monotonic()
        _atomic_write(path, generate_otio(timeline, name=selection.project or "Videoedit Generated Edit"))
        result = {"output": str(path), "clips": len(timeline.clips),
                  "duration_seconds": details["duration_seconds"], "warnings": details["limitations"]}
        manifest.record_step("handoff", "generate_otio", {"fps": selection.fps}, result,
                             time.monotonic() - before)
    return {**result, "run_manifest": str(manifest_path)}
