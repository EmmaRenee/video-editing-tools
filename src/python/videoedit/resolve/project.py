"""
Resolve project setup - bins, media import, metadata from the shoot DB.

Bin tree mirrors the funnel's categories; clip colors and keywords
carry Claude's verdicts into the edit page so the editor can filter
by them immediately.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..shoot.db import ShootDB

BIN_TREE = {
    "A-Roll": ["Interviews"],
    "B-Roll": ["Action", "Atmosphere"],
    "Photos": ["Keepers"],
    "Audio": [],
    "Rejected": [],
}

KIND_TO_BIN = {
    "aroll": ("A-Roll", "Interviews"),
    "broll": ("B-Roll", "Action"),
    "mixed": ("B-Roll", "Atmosphere"),
}

KIND_TO_COLOR = {
    "aroll": "Blue",
    "broll": "Green",
    "mixed": "Teal",
}


def ensure_bins(media_pool) -> Dict[str, Any]:
    """Create the standard bin tree; returns {path_string: folder}."""
    root = media_pool.GetRootFolder()
    existing = {f.GetName(): f for f in root.GetSubFolderList()}
    folders: Dict[str, Any] = {"": root}

    for top, children in BIN_TREE.items():
        folder = existing.get(top) or media_pool.AddSubFolder(root, top)
        folders[top] = folder
        sub_existing = {f.GetName(): f for f in folder.GetSubFolderList()}
        for child in children:
            sub = sub_existing.get(child) or media_pool.AddSubFolder(folder, child)
            folders[f"{top}/{child}"] = sub
    return folders


def import_shoot_media(project, db: ShootDB, shoot_id: int,
                       include_rejected: bool = False) -> Dict[str, Any]:
    """
    Import reviewed media into categorized bins with metadata.

    Returns {abs_path: mediaPoolItem} for timeline building.
    Imports: assets backing Claude-reviewed candidates (into kind bins),
    keeper photos, and standalone audio.
    """
    media_pool = project.GetMediaPool()
    folders = ensure_bins(media_pool)
    path_to_item: Dict[str, Any] = {}

    def import_into(bin_key: str, paths: List[str]) -> List[Any]:
        paths = [p for p in paths if p not in path_to_item]
        if not paths:
            return []
        media_pool.SetCurrentFolder(folders[bin_key])
        items = media_pool.ImportMedia(paths) or []
        for item in items:
            file_path = item.GetClipProperty("File Path")
            if file_path:
                path_to_item[file_path] = item
        return items

    # video assets grouped by their best (Claude) kind
    rows = db.conn.execute("""
        SELECT a.abs_path, c.claude_kind, c.kind_guess, c.claude_notes,
               c.claude_story_beat, c.signals_json, c.status
        FROM candidates c JOIN assets a ON a.id = c.asset_id
        WHERE c.status IN ('claude_reviewed', 'rejected')
        ORDER BY c.claude_rank IS NULL, c.claude_rank""").fetchall()

    per_asset: Dict[str, Dict] = {}
    for row in rows:
        entry = per_asset.setdefault(row["abs_path"], {
            "kinds": set(), "notes": [], "beats": set(), "tags": set(),
            "rejected_only": True})
        if row["status"] == "claude_reviewed":
            entry["rejected_only"] = False
            entry["kinds"].add(row["claude_kind"] or row["kind_guess"] or "broll")
            if row["claude_notes"]:
                entry["notes"].append(row["claude_notes"])
            if row["claude_story_beat"]:
                entry["beats"].add(row["claude_story_beat"])
            signals = json.loads(row["signals_json"] or "{}")
            entry["tags"].update(signals.get("top_tags", []))

    for abs_path, entry in per_asset.items():
        if entry["rejected_only"]:
            if include_rejected:
                import_into("Rejected", [abs_path])
            continue
        kind = ("aroll" if "aroll" in entry["kinds"] else
                next(iter(entry["kinds"]), "broll"))
        top, child = KIND_TO_BIN.get(kind, ("B-Roll", "Action"))
        items = import_into(f"{top}/{child}", [abs_path])
        for item in items:
            item.SetClipColor(KIND_TO_COLOR.get(kind, "Green"))
            if entry["tags"]:
                item.SetMetadata("Keywords", ",".join(sorted(entry["tags"])[:8]))
            if entry["notes"]:
                item.SetMetadata("Comments", " | ".join(entry["notes"])[:250])
            if entry["beats"]:
                item.SetMetadata("Shot", ",".join(sorted(entry["beats"])))

    # keeper photos
    keeper_paths = [r["abs_path"] for r in db.conn.execute("""
        SELECT DISTINCT a.abs_path FROM photo_group_members m
        JOIN assets a ON a.id = m.asset_id
        WHERE (m.claude_keep = 1) OR (m.claude_keep IS NULL AND m.is_keeper_suggested = 1)""")]
    photo_items = import_into("Photos/Keepers", keeper_paths)
    hero_paths = {r["abs_path"] for r in db.conn.execute("""
        SELECT a.abs_path FROM photo_group_members m
        JOIN assets a ON a.id = m.asset_id WHERE m.claude_hero = 1""")}
    for item in photo_items:
        if item.GetClipProperty("File Path") in hero_paths:
            item.SetClipColor("Yellow")

    # standalone audio
    audio_paths = [a["abs_path"] for a in db.list_assets(shoot_id, media_type="audio")
                   if a["status"] == "probed"]
    import_into("Audio", audio_paths)

    return path_to_item
