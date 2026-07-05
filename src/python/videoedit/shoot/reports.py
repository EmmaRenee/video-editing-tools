"""
Reports - Inventory and status reports from the shoot database.

Supersedes the standalone inventory.py for shoot workflows: reads
from shoot.db instead of re-probing files, and covers video, audio,
and photos with analysis columns when available.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .db import ShootDB


def format_duration(seconds: float) -> str:
    seconds = seconds or 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def inventory_rows(db: ShootDB, shoot_id: int) -> List[Dict]:
    rows = []
    for a in db.list_assets(shoot_id):
        rows.append({
            "rel_path": a["rel_path"],
            "media_type": a["media_type"],
            "duration": format_duration(a["duration_s"]) if a["duration_s"] else "",
            "resolution": f"{a['width']}x{a['height']}" if a["width"] else "",
            "fps": a["fps"] or "",
            "codec": a["vcodec"] or a["acodec"] or "",
            "camera": a["camera"] or "",
            "capture_ts": a["capture_ts"] or "",
            "size_mb": round((a["size_bytes"] or 0) / (1024 * 1024), 1),
            "status": a["status"],
            "error": a["error"] or "",
        })
    return rows


def write_csv(rows: List[Dict], output: Path):
    if not rows:
        return
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(db: ShootDB, shoot_id: int, rows: List[Dict], output: Path):
    assets = db.list_assets(shoot_id)
    payload = {
        "generated": datetime.now().isoformat(),
        "count": len(rows),
        "total_duration_s": sum(a["duration_s"] or 0 for a in assets),
        "total_size_bytes": sum(a["size_bytes"] or 0 for a in assets),
        "by_type": _type_summary(assets),
        "assets": rows,
    }
    output.write_text(json.dumps(payload, indent=2))


def write_markdown(db: ShootDB, shoot_id: int, rows: List[Dict], output: Path):
    assets = db.list_assets(shoot_id)
    shoot = db.get_shoot(shoot_id)
    by_type = _type_summary(assets)

    lines = [
        f"# Shoot Inventory: {shoot['name']}",
        "",
        f"**Root:** `{shoot['root_path']}`",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        "",
        f"- **Files:** {len(assets)}",
        f"- **Total size:** {round(sum(a['size_bytes'] or 0 for a in assets) / 1024**3, 2)} GB",
        f"- **Total AV duration:** {format_duration(sum(a['duration_s'] or 0 for a in assets))}",
        "",
        "| Type | Count | Size (GB) | Duration |",
        "|------|-------|-----------|----------|",
    ]
    for mtype, s in by_type.items():
        lines.append(f"| {mtype} | {s['count']} | {round(s['size_bytes'] / 1024**3, 2)} "
                     f"| {format_duration(s['duration_s'])} |")

    cameras: Dict[str, int] = {}
    for a in assets:
        if a["camera"]:
            cameras[a["camera"]] = cameras.get(a["camera"], 0) + 1
    if cameras:
        lines += ["", "## Cameras", ""]
        lines += [f"- {cam}: {n} files" for cam, n in
                  sorted(cameras.items(), key=lambda x: -x[1])]

    errors = [a for a in assets if a["status"] == "error"]
    if errors:
        lines += ["", f"## Probe Errors ({len(errors)})", ""]
        lines += [f"- `{a['rel_path']}`: {a['error']}" for a in errors[:20]]

    lines += ["", "## Files", "",
              "| Path | Type | Duration | Resolution | FPS | Camera | Size |",
              "|------|------|----------|------------|-----|--------|------|"]
    for r in rows[:200]:
        lines.append(f"| {r['rel_path'][:60]} | {r['media_type']} | {r['duration']} "
                     f"| {r['resolution']} | {r['fps']} | {r['camera'][:20]} "
                     f"| {r['size_mb']} MB |")
    if len(rows) > 200:
        lines.append(f"\n*... and {len(rows) - 200} more files*")

    output.write_text("\n".join(lines) + "\n")


def _type_summary(assets) -> Dict[str, Dict]:
    summary: Dict[str, Dict] = {}
    for a in assets:
        s = summary.setdefault(a["media_type"],
                               {"count": 0, "size_bytes": 0, "duration_s": 0})
        s["count"] += 1
        s["size_bytes"] += a["size_bytes"] or 0
        s["duration_s"] += a["duration_s"] or 0
    return summary
