"""
Photo pipeline - group, cull, and rank the stills from a shoot.

Grouping: capture-time gaps (>10 min starts a new group) within each
camera. Cull: blur/exposure metrics flag technical rejects. Dedupe:
CLIP embeddings cluster near-identical bursts (cosine > 0.96) and
suggest the sharpest of each cluster as keeper. Ranking is local
(mechanical); Claude makes the final call from contact sheets.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import ShootDB

GROUP_GAP_MINUTES = 10
DEDUPE_COSINE = 0.96


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def analyze_photo(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    """
    Per-photo worker for ShootRunner phase 'quality': measures
    blur/exposure and (when the analyze stack is present) a CLIP
    embedding, stored as a frames row at ts 0.
    """
    from ..operations.quality import measure_image

    path = Path(asset["abs_path"])
    metrics = measure_image(path)

    embedding = None
    encoder = context.get("encoder")
    if encoder is not None:
        from PIL import Image
        from ..operations.embed import pack_embedding
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        with Image.open(path) as img:
            img.thumbnail((512, 512))
            embedding = pack_embedding(encoder.encode_images([img])[0])

    db.conn.execute("DELETE FROM frames WHERE asset_id = ?", (asset["id"],))
    db.save_frame(asset["id"], 0.0, thumb_path=None,
                  sharpness=metrics["sharpness"],
                  exposure_low_pct=metrics["exposure_low_pct"],
                  exposure_high_pct=metrics["exposure_high_pct"],
                  embedding=embedding)


def group_and_rank(db: ShootDB, shoot_id: int) -> Dict[str, int]:
    """
    Shoot-level pass: build photo_groups from analyzed photos.

    Idempotent — wipes and rebuilds groups each run (cheap; the
    expensive per-photo analysis lives in the quality phase).
    """
    from ..operations.embed import unpack_embedding

    photos = [dict(p) for p in db.list_assets(shoot_id, media_type="photo")
              if p["status"] == "probed"]
    if not photos:
        return {"groups": 0, "photos": 0}

    # attach analysis
    for photo in photos:
        row = db.conn.execute(
            "SELECT sharpness, exposure_low_pct, exposure_high_pct, embedding "
            "FROM frames WHERE asset_id = ?", (photo["id"],)).fetchone()
        photo["sharpness"] = row["sharpness"] if row else None
        photo["exp_low"] = row["exposure_low_pct"] if row else 0
        photo["exp_high"] = row["exposure_high_pct"] if row else 0
        photo["embedding"] = (unpack_embedding(row["embedding"])
                              if row and row["embedding"] else None)
        photo["dt"] = _parse_ts(photo["capture_ts"]) or datetime.fromtimestamp(
            photo["mtime"] or 0)

    # rebuild groups
    db.conn.execute(
        "DELETE FROM photo_group_members WHERE group_id IN "
        "(SELECT id FROM photo_groups WHERE shoot_id = ?)", (shoot_id,))
    db.conn.execute("DELETE FROM photo_groups WHERE shoot_id = ?", (shoot_id,))

    by_camera: Dict[str, List[Dict]] = {}
    for photo in photos:
        by_camera.setdefault(photo["camera"] or "unknown", []).append(photo)

    n_groups = 0
    for camera, cam_photos in by_camera.items():
        cam_photos.sort(key=lambda p: p["dt"])
        group: List[Dict] = []
        for photo in cam_photos:
            if group and (photo["dt"] - group[-1]["dt"]).total_seconds() > GROUP_GAP_MINUTES * 60:
                _write_group(db, shoot_id, camera, group)
                n_groups += 1
                group = []
            group.append(photo)
        if group:
            _write_group(db, shoot_id, camera, group)
            n_groups += 1

    db.conn.commit()
    return {"groups": n_groups, "photos": len(photos)}


def _write_group(db: ShootDB, shoot_id: int, camera: str, photos: List[Dict]):
    import numpy as np

    cur = db.conn.execute(
        "INSERT INTO photo_groups (shoot_id, method, label, start_ts, end_ts) "
        "VALUES (?, 'time_camera', ?, ?, ?)",
        (shoot_id, f"{camera} {photos[0]['dt']:%Y-%m-%d %H:%M}",
         photos[0]["dt"].isoformat(), photos[-1]["dt"].isoformat()))
    group_id = cur.lastrowid

    # dedupe clusters via greedy cosine linking
    clusters: List[List[Dict]] = []
    for photo in photos:
        placed = False
        if photo["embedding"] is not None:
            for cluster in clusters:
                rep = cluster[0]
                if rep["embedding"] is not None:
                    cos = float(np.dot(photo["embedding"], rep["embedding"]))
                    if cos >= DEDUPE_COSINE:
                        cluster.append(photo)
                        placed = True
                        break
        if not placed:
            clusters.append([photo])

    # rank within group: technical quality, penalizing clipped exposure
    def quality_key(p):
        sharp = p["sharpness"] or 0
        penalty = 1 + (p["exp_low"] or 0) / 50 + (p["exp_high"] or 0) / 50
        return sharp / penalty

    ranked = sorted(photos, key=quality_key, reverse=True)
    ranks = {p["id"]: i + 1 for i, p in enumerate(ranked)}

    for ci, cluster in enumerate(clusters):
        keeper = max(cluster, key=quality_key)
        for photo in cluster:
            db.conn.execute(
                "INSERT INTO photo_group_members "
                "(group_id, asset_id, dedupe_cluster, local_rank, is_keeper_suggested) "
                "VALUES (?, ?, ?, ?, ?)",
                (group_id, photo["id"], ci, ranks[photo["id"]],
                 1 if photo["id"] == keeper["id"] else 0))
