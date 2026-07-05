"""
Resolve timeline builder - assemble a rough cut from a timeline spec.

Spec format (validated by shoot.schemas.validate_timeline_spec):
{
  "timeline_name": "...", "fps": 29.97,
  "tracks": [{"index": 1, "clips": [
      {"asset_id": 3, "in_s": 12.5, "out_s": 31.0,
       "marker": {"color": "Blue", "note": "trim tail"}}]}]
}

Frame math derives from EACH CLIP'S OWN fps, not the timeline fps —
mixed 23.976/29.97/59.94 shoots are the norm and startFrame/endFrame
in AppendToTimeline are source-clip frames.
"""
from pathlib import Path
from typing import Any, Dict, List

from ..shoot.db import ShootDB


def build_timeline(project, db: ShootDB, spec: Dict[str, Any],
                   path_to_item: Dict[str, Any]) -> Any:
    """
    Create the timeline in Resolve and append clips track by track.

    path_to_item: {abs_path: mediaPoolItem} from project.import_shoot_media.
    Returns the created Resolve timeline object.
    """
    media_pool = project.GetMediaPool()

    name = spec["timeline_name"]
    existing = [project.GetTimelineByIndex(i + 1).GetName()
                for i in range(int(project.GetTimelineCount()))]
    if name in existing:
        suffix = 2
        while f"{name} v{suffix}" in existing:
            suffix += 1
        name = f"{name} v{suffix}"

    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline is None:
        raise RuntimeError(f"Could not create timeline '{name}'")
    project.SetCurrentTimeline(name)

    timeline_fps = float(spec.get("fps", 30))
    markers: List[Dict] = []
    record_cursor_s = {t["index"]: 0.0 for t in spec["tracks"]}

    for track in sorted(spec["tracks"], key=lambda t: t["index"]):
        clip_infos = []
        for clip in track["clips"]:
            asset = db.get_asset(clip["asset_id"])
            if asset is None:
                raise ValueError(f"Unknown asset_id {clip['asset_id']} in spec")
            item = path_to_item.get(asset["abs_path"])
            if item is None:
                raise ValueError(
                    f"Asset not imported to media pool: {asset['rel_path']}")

            # source frames in the CLIP's frame rate
            clip_fps = asset["fps"] or timeline_fps
            start_frame = round(clip["in_s"] * clip_fps)
            end_frame = max(round(clip["out_s"] * clip_fps) - 1, start_frame)

            clip_infos.append({
                "mediaPoolItem": item,
                "startFrame": start_frame,
                "endFrame": end_frame,
                "trackIndex": track["index"],
            })

            if clip.get("marker"):
                markers.append({
                    "frame": round(record_cursor_s[track["index"]] * timeline_fps),
                    "color": clip["marker"].get("color", "Blue"),
                    "note": clip["marker"]["note"],
                })
            record_cursor_s[track["index"]] += clip["out_s"] - clip["in_s"]

        if clip_infos:
            appended = media_pool.AppendToTimeline(clip_infos)
            if not appended:
                raise RuntimeError(
                    f"AppendToTimeline failed for track {track['index']} "
                    f"({len(clip_infos)} clips)")

    for marker in markers:
        timeline.AddMarker(marker["frame"], marker["color"],
                           marker["note"][:60], marker["note"], 1)

    return timeline
