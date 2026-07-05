"""
Review - the export/import contract between the shoot DB and Claude.

Export: bundle top candidates (signals, transcript excerpts, contact
sheet paths) into review_batch.json for Claude to read alongside the
sheet images. Import: validate Claude's verdict JSON and persist it —
raw JSON to claude_reviews (audit trail), decisions denormalized onto
candidates / photo_group_members.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import ShootDB
from .schemas import (validate_clip_review, validate_photo_cull,
                      validate_timeline_spec)


def build_contact_sheets(db: ShootDB, shoot_id: int, top_n: int = 60,
                         candidate_id: Optional[int] = None) -> List[Path]:
    """
    Build review sheets for the top unreviewed candidates (marking them
    shortlisted), or a dense in/out refinement strip for one candidate.
    """
    from ..operations.contact import build_sheet, build_candidate_strip, _timecode

    shoot = db.get_shoot(shoot_id)
    sheet_dir = Path(shoot["workspace_path"]) / "contact_sheets"

    if candidate_id is not None:
        row = db.conn.execute(
            "SELECT c.*, a.abs_path FROM candidates c JOIN assets a ON a.id = c.asset_id "
            "WHERE c.id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        out = sheet_dir / f"candidate_{candidate_id}_strip.jpg"
        return [build_candidate_strip(Path(row["abs_path"]), row["start_s"],
                                      row["end_s"], out)]

    rows = db.conn.execute(
        "SELECT c.*, a.abs_path, a.rel_path FROM candidates c "
        "JOIN assets a ON a.id = c.asset_id "
        "WHERE c.status IN ('unreviewed', 'shortlisted') "
        "ORDER BY c.local_score DESC LIMIT ?", (top_n,)).fetchall()

    tiles = []
    for row in rows:
        mid = (row["start_s"] + row["end_s"]) / 2
        frame = db.conn.execute(
            "SELECT thumb_path FROM frames WHERE asset_id = ? AND thumb_path IS NOT NULL "
            "ORDER BY ABS(ts_s - ?) LIMIT 1", (row["asset_id"], mid)).fetchone()
        if not frame or not frame["thumb_path"] or not Path(frame["thumb_path"]).exists():
            continue
        tiles.append({
            "image": frame["thumb_path"],
            "caption": f"#{row['id']} {row['kind_guess'] or '?'} "
                       f"{_timecode(row['start_s'])}-{_timecode(row['end_s'])}",
            "candidate_id": row["id"],
        })

    if not tiles:
        return []

    base = sheet_dir / f"review_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    sheets = build_sheet(tiles, base, title=f"Shoot: {shoot['name']}")

    per_sheet = 30
    for i, tile in enumerate(tiles):
        sheet_path = str(sheets[min(i // per_sheet, len(sheets) - 1)])
        db.conn.execute(
            "UPDATE candidates SET contact_sheet_path = ?, status = 'shortlisted' "
            "WHERE id = ? AND status = 'unreviewed'",
            (sheet_path, tile["candidate_id"]))
        db.conn.execute(
            "UPDATE candidates SET contact_sheet_path = ? WHERE id = ?",
            (sheet_path, tile["candidate_id"]))
    db.conn.commit()
    return sheets


def export_review_batch(db: ShootDB, shoot_id: int, top_n: int = 60,
                        output: Optional[Path] = None) -> Path:
    """Write review_batch.json for Claude. Excludes already-reviewed clips."""
    shoot = db.get_shoot(shoot_id)
    rows = db.conn.execute(
        "SELECT c.*, a.rel_path, a.fps, a.duration_s FROM candidates c "
        "JOIN assets a ON a.id = c.asset_id "
        "WHERE c.status IN ('unreviewed', 'shortlisted') "
        "ORDER BY c.local_score DESC LIMIT ?", (top_n,)).fetchall()

    batch = {
        "shoot": shoot["name"],
        "config": json.loads(shoot["config_json"]),
        "generated": datetime.now().isoformat(),
        "instructions": "Review the contact sheet images listed under "
                        "sheet_paths, then emit clip-review JSON "
                        "(see SKILL.md schema) and import with "
                        "`videoedit shoot review-import <file>`.",
        "sheet_paths": sorted({r["contact_sheet_path"] for r in rows
                               if r["contact_sheet_path"]}),
        "candidates": [
            {
                "candidate_id": r["id"],
                "source": r["rel_path"],
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "kind_guess": r["kind_guess"],
                "local_score": r["local_score"],
                "signals": json.loads(r["signals_json"] or "{}"),
                "transcript_excerpt": r["transcript_excerpt"],
            }
            for r in rows
        ],
    }
    output = output or Path(shoot["workspace_path"]) / "reviews" / "review_batch.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(batch, indent=2))
    return output


def export_photo_batch(db: ShootDB, shoot_id: int,
                       output: Optional[Path] = None) -> Path:
    """Write photo groups + members + local suggestions for Claude review."""
    from ..operations.contact import build_sheet

    shoot = db.get_shoot(shoot_id)
    sheet_dir = Path(shoot["workspace_path"]) / "contact_sheets"
    groups = []
    for group in db.conn.execute(
            "SELECT * FROM photo_groups WHERE shoot_id = ?", (shoot_id,)):
        members = db.conn.execute(
            "SELECT m.*, a.rel_path, a.abs_path FROM photo_group_members m "
            "JOIN assets a ON a.id = m.asset_id WHERE m.group_id = ? "
            "ORDER BY m.local_rank", (group["id"],)).fetchall()
        tiles = [{"image": m["abs_path"],
                  "caption": f"id={m['asset_id']} r{m['local_rank']}"
                             f"{' KEEP?' if m['is_keeper_suggested'] else ''}"}
                 for m in members]
        sheets = []
        if tiles:
            sheets = build_sheet(tiles, sheet_dir / f"photos_group_{group['id']}.jpg",
                                 cols=5, rows=4, title=group["label"])
        groups.append({
            "group_id": group["id"],
            "label": group["label"],
            "sheet_paths": [str(s) for s in sheets],
            "members": [
                {"asset_id": m["asset_id"], "path": m["rel_path"],
                 "local_rank": m["local_rank"],
                 "dedupe_cluster": m["dedupe_cluster"],
                 "keeper_suggested": bool(m["is_keeper_suggested"])}
                for m in members
            ],
        })

    output = output or Path(shoot["workspace_path"]) / "reviews" / "photo_batch.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(
        {"shoot": shoot["name"], "generated": datetime.now().isoformat(),
         "groups": groups}, indent=2))
    return output


def import_verdicts(db: ShootDB, shoot_id: int, verdict_path: Path,
                    model: str = "") -> Dict[str, int]:
    """
    Import a Claude verdict file (clip review or photo cull — detected
    by shape). Validates first; raises ValueError with all problems.
    """
    data = json.loads(Path(verdict_path).read_text())

    if "reviews" in data:
        errors = validate_clip_review(data)
        if errors:
            raise ValueError("Invalid clip review:\n  " + "\n  ".join(errors))
        return _import_clip_reviews(db, data, model)
    if "groups" in data:
        errors = validate_photo_cull(data)
        if errors:
            raise ValueError("Invalid photo cull:\n  " + "\n  ".join(errors))
        return _import_photo_cull(db, data, model)
    raise ValueError("Unrecognized verdict JSON: expected top-level "
                     "'reviews' (clips) or 'groups' (photos)")


def _import_clip_reviews(db: ShootDB, data: Dict, model: str) -> Dict[str, int]:
    applied = missing = 0
    for review in data["reviews"]:
        cid = review["candidate_id"]
        row = db.conn.execute("SELECT id FROM candidates WHERE id = ?",
                              (cid,)).fetchone()
        if row is None:
            missing += 1
            continue
        db.conn.execute(
            "INSERT INTO claude_reviews (target_kind, target_id, verdict_json, model, created_at) "
            "VALUES ('candidate', ?, ?, ?, ?)",
            (cid, json.dumps(review), model, datetime.now().isoformat()))
        if review["kind"] == "reject":
            db.conn.execute(
                "UPDATE candidates SET status = 'rejected', claude_kind = 'reject', "
                "claude_notes = ? WHERE id = ?",
                (review.get("notes"), cid))
        else:
            db.conn.execute(
                "UPDATE candidates SET status = 'claude_reviewed', claude_rank = ?, "
                "claude_kind = ?, claude_in_s = ?, claude_out_s = ?, "
                "claude_story_beat = ?, claude_notes = ? WHERE id = ?",
                (review.get("rank"), review["kind"], review.get("in_s"),
                 review.get("out_s"), review.get("story_beat"),
                 review.get("notes"), cid))
        applied += 1
    db.conn.commit()
    return {"applied": applied, "missing": missing}


def _import_photo_cull(db: ShootDB, data: Dict, model: str) -> Dict[str, int]:
    applied = missing = 0
    for group in data["groups"]:
        gid = group["group_id"]
        row = db.conn.execute("SELECT id FROM photo_groups WHERE id = ?",
                              (gid,)).fetchone()
        if row is None:
            missing += 1
            continue
        db.conn.execute(
            "INSERT INTO claude_reviews (target_kind, target_id, verdict_json, model, created_at) "
            "VALUES ('photo_group', ?, ?, ?, ?)",
            (gid, json.dumps(group), model, datetime.now().isoformat()))
        for asset_id in group.get("keepers", []):
            db.conn.execute(
                "UPDATE photo_group_members SET claude_keep = 1 "
                "WHERE group_id = ? AND asset_id = ?", (gid, asset_id))
        for asset_id in group.get("rejects", []):
            db.conn.execute(
                "UPDATE photo_group_members SET claude_keep = 0 "
                "WHERE group_id = ? AND asset_id = ?", (gid, asset_id))
        hero = group.get("hero")
        if hero is not None:
            db.conn.execute(
                "UPDATE photo_group_members SET claude_hero = 1 "
                "WHERE group_id = ? AND asset_id = ?", (gid, hero))
        applied += 1
    db.conn.commit()
    return {"applied": applied, "missing": missing}


def save_timeline_spec(db: ShootDB, shoot_id: int, spec_path: Path) -> int:
    """Validate and register a rough-cut spec; returns timeline id."""
    spec = json.loads(Path(spec_path).read_text())
    errors = validate_timeline_spec(spec)
    if errors:
        raise ValueError("Invalid timeline spec:\n  " + "\n  ".join(errors))
    cur = db.conn.execute(
        "INSERT INTO timelines (shoot_id, name, spec_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (shoot_id, spec["timeline_name"], json.dumps(spec),
         datetime.now().isoformat()))
    db.conn.commit()
    return cur.lastrowid
