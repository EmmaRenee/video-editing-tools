"""
OTIO export - timeline spec → OpenTimelineIO file.

The durable fallback: Resolve 17+ imports .otio natively (File →
Import → Timeline), and unlike the legacy EDL path it handles
multiple source files and per-clip frame rates. Always written
before any Resolve API push.
"""
from pathlib import Path
from typing import Any, Dict

from ..shoot.db import ShootDB


def export_otio(db: ShootDB, spec: Dict[str, Any], output: Path) -> Path:
    import opentimelineio as otio

    timeline_fps = float(spec.get("fps", 30))
    timeline = otio.schema.Timeline(name=spec["timeline_name"])

    for track_spec in sorted(spec["tracks"], key=lambda t: t["index"]):
        track = otio.schema.Track(
            name=f"V{track_spec['index']}",
            kind=otio.schema.TrackKind.Video)

        for clip_spec in track_spec["clips"]:
            asset = db.get_asset(clip_spec["asset_id"])
            if asset is None:
                raise ValueError(f"Unknown asset_id {clip_spec['asset_id']}")
            clip_fps = asset["fps"] or timeline_fps

            media_ref = otio.schema.ExternalReference(
                target_url=Path(asset["abs_path"]).as_uri(),
                available_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, clip_fps),
                    duration=otio.opentime.RationalTime(
                        round((asset["duration_s"] or clip_spec["out_s"]) * clip_fps),
                        clip_fps)))

            source_range = otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(
                    round(clip_spec["in_s"] * clip_fps), clip_fps),
                duration=otio.opentime.RationalTime(
                    round((clip_spec["out_s"] - clip_spec["in_s"]) * clip_fps),
                    clip_fps))

            clip = otio.schema.Clip(
                name=f"{Path(asset['rel_path']).stem}",
                media_reference=media_ref,
                source_range=source_range)

            marker_spec = clip_spec.get("marker")
            if marker_spec:
                clip.markers.append(otio.schema.Marker(
                    name=marker_spec["note"][:60],
                    color=_otio_color(marker_spec.get("color", "Blue")),
                    marked_range=otio.opentime.TimeRange(
                        start_time=source_range.start_time,
                        duration=otio.opentime.RationalTime(1, clip_fps))))

            track.append(clip)
        timeline.tracks.append(track)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(timeline, str(output))
    return output


def _otio_color(resolve_color: str) -> str:
    """Map Resolve marker colors onto OTIO's fixed marker color set."""
    mapping = {
        "Blue": "BLUE", "Cyan": "CYAN", "Green": "GREEN", "Yellow": "YELLOW",
        "Red": "RED", "Pink": "PINK", "Purple": "PURPLE", "Fuchsia": "MAGENTA",
        "Rose": "PINK", "Lavender": "PURPLE", "Sky": "CYAN", "Mint": "GREEN",
        "Lemon": "YELLOW", "Sand": "ORANGE", "Cocoa": "ORANGE", "Cream": "WHITE",
    }
    return mapping.get(resolve_color, "BLUE")
