"""
Schemas - validation for the JSON contracts between Claude and the CLI.

Three contracts (documented in SKILL.md):
1. Clip review   — Claude's verdicts on candidate clips
2. Photo cull    — Claude's keep/reject/hero decisions per photo group
3. Timeline spec — the rough cut consumed by `shoot timeline`

Hand-rolled checks (no jsonschema dependency): each validator returns
a list of error strings; empty list = valid.
"""
from typing import Any, Dict, List

CLIP_KINDS = {"aroll", "broll", "reject"}
STORY_BEATS = {"hook", "context", "rising", "climax", "resolution", "color"}
MARKER_COLORS = {"Blue", "Cyan", "Green", "Yellow", "Red", "Pink",
                 "Purple", "Fuchsia", "Rose", "Lavender", "Sky", "Mint",
                 "Lemon", "Sand", "Cocoa", "Cream"}


def _require(obj: Dict, key: str, types, errors: List[str], where: str) -> Any:
    if key not in obj:
        errors.append(f"{where}: missing '{key}'")
        return None
    if not isinstance(obj[key], types):
        type_names = types.__name__ if isinstance(types, type) else \
            "/".join(t.__name__ for t in types)
        errors.append(f"{where}: '{key}' must be {type_names}")
        return None
    return obj[key]


def validate_clip_review(data: Dict[str, Any]) -> List[str]:
    """Validate: {"reviews": [{candidate_id, rank, kind, in_s, out_s,
    story_beat?, tags?, notes?}]}"""
    errors: List[str] = []
    reviews = _require(data, "reviews", list, errors, "root")
    if reviews is None:
        return errors

    for i, review in enumerate(reviews):
        where = f"reviews[{i}]"
        if not isinstance(review, dict):
            errors.append(f"{where}: must be an object")
            continue
        _require(review, "candidate_id", int, errors, where)
        kind = _require(review, "kind", str, errors, where)
        if kind and kind not in CLIP_KINDS:
            errors.append(f"{where}: kind '{kind}' not in {sorted(CLIP_KINDS)}")
        if kind != "reject":
            _require(review, "rank", int, errors, where)
            in_s = _require(review, "in_s", (int, float), errors, where)
            out_s = _require(review, "out_s", (int, float), errors, where)
            if in_s is not None and out_s is not None and out_s <= in_s:
                errors.append(f"{where}: out_s must be > in_s")
        beat = review.get("story_beat")
        if beat is not None and beat not in STORY_BEATS:
            errors.append(f"{where}: story_beat '{beat}' not in {sorted(STORY_BEATS)}")
        if "tags" in review and not isinstance(review["tags"], list):
            errors.append(f"{where}: tags must be a list")
    return errors


def validate_photo_cull(data: Dict[str, Any]) -> List[str]:
    """Validate: {"groups": [{group_id, keepers: [ids], hero?, rejects: [ids],
    notes?}]}"""
    errors: List[str] = []
    groups = _require(data, "groups", list, errors, "root")
    if groups is None:
        return errors

    for i, group in enumerate(groups):
        where = f"groups[{i}]"
        if not isinstance(group, dict):
            errors.append(f"{where}: must be an object")
            continue
        _require(group, "group_id", int, errors, where)
        keepers = _require(group, "keepers", list, errors, where)
        rejects = _require(group, "rejects", list, errors, where)
        for key, ids in (("keepers", keepers), ("rejects", rejects)):
            if ids and not all(isinstance(x, int) for x in ids):
                errors.append(f"{where}: {key} must contain asset ids (ints)")
        hero = group.get("hero")
        if hero is not None:
            if not isinstance(hero, int):
                errors.append(f"{where}: hero must be an asset id (int)")
            elif keepers is not None and hero not in keepers:
                errors.append(f"{where}: hero {hero} must be in keepers")
        if keepers and rejects:
            overlap = set(keepers) & set(rejects)
            if overlap:
                errors.append(f"{where}: assets in both keepers and rejects: {sorted(overlap)}")
    return errors


def validate_timeline_spec(data: Dict[str, Any]) -> List[str]:
    """Validate: {"timeline_name", "fps", "tracks": [{index, clips:
    [{asset_id, in_s, out_s, candidate_id?, marker?}]}]}"""
    errors: List[str] = []
    _require(data, "timeline_name", str, errors, "root")
    fps = _require(data, "fps", (int, float), errors, "root")
    if fps is not None and not (10 <= fps <= 240):
        errors.append(f"root: implausible fps {fps}")
    tracks = _require(data, "tracks", list, errors, "root")
    if tracks is None:
        return errors
    if not tracks:
        errors.append("root: tracks is empty")

    for t, track in enumerate(tracks):
        where = f"tracks[{t}]"
        if not isinstance(track, dict):
            errors.append(f"{where}: must be an object")
            continue
        index = _require(track, "index", int, errors, where)
        if index is not None and index < 1:
            errors.append(f"{where}: track index is 1-based")
        clips = _require(track, "clips", list, errors, where)
        if not clips:
            errors.append(f"{where}: clips is empty")
            continue
        for c, clip in enumerate(clips):
            cwhere = f"{where}.clips[{c}]"
            if not isinstance(clip, dict):
                errors.append(f"{cwhere}: must be an object")
                continue
            _require(clip, "asset_id", int, errors, cwhere)
            in_s = _require(clip, "in_s", (int, float), errors, cwhere)
            out_s = _require(clip, "out_s", (int, float), errors, cwhere)
            if in_s is not None and out_s is not None and out_s <= in_s:
                errors.append(f"{cwhere}: out_s must be > in_s")
            marker = clip.get("marker")
            if marker is not None:
                if not isinstance(marker, dict) or "note" not in marker:
                    errors.append(f"{cwhere}: marker must be an object with 'note'")
                elif marker.get("color") and marker["color"] not in MARKER_COLORS:
                    errors.append(f"{cwhere}: marker color '{marker['color']}' "
                                  f"not a Resolve marker color")
    return errors
