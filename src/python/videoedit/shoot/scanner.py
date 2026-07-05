"""
Scanner - Parallel walk + probe of a shoot directory.

Walks the shoot root, registers every media file in the shoot DB,
then probes metadata in parallel: ffprobe for video/audio, Pillow
EXIF for photos. Idempotent — unchanged files (same size + mtime)
are never re-probed, so rescanning a 300GB shoot after adding one
card is nearly instant.
"""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import ShootDB, quick_hash

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".mts", ".m2ts", ".m4v", ".mxf", ".webm"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".aif", ".aiff", ".ogg"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff",
              ".dng", ".arw", ".cr2", ".cr3", ".nef", ".raf", ".orf"}

# Directories never scanned: workspace, hidden dirs, editor caches
SKIP_DIRS = {".videoedit", ".git", "CacheClip", ".gallery", "Proxy"}

DEFAULT_WORKERS = 4  # NAS-friendly; raise with --workers on local SSDs


def classify(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in PHOTO_EXTS:
        return "photo"
    return None


def walk_media(root: Path) -> List[Path]:
    """Find all media files under root, skipping workspace/hidden dirs."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if classify(path):
            found.append(path)
    return found


def probe_av(path: Path) -> Dict[str, Any]:
    """Extract video/audio metadata via ffprobe (ported from inventory.py)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration,size:format_tags=creation_time,com.apple.quicktime.model:"
        "stream=width,height,codec_type,codec_name,r_frame_rate,channels:"
        "stream_tags=creation_time",
        "-of", "json", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "ffprobe failed")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}
    info: Dict[str, Any] = {}

    if "duration" in fmt:
        info["duration_s"] = round(float(fmt["duration"]), 3)

    capture = tags.get("creation_time")
    camera = tags.get("com.apple.quicktime.model")

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and "width" in stream and "width" not in info:
            info["width"] = stream["width"]
            info["height"] = stream["height"]
            info["vcodec"] = stream.get("codec_name")
            rate = stream.get("r_frame_rate", "")
            if "/" in rate:
                num, den = rate.split("/")
                if int(den):
                    info["fps"] = round(int(num) / int(den), 3)
            capture = capture or (stream.get("tags", {}) or {}).get("creation_time")
        elif stream.get("codec_type") == "audio" and "acodec" not in info:
            info["acodec"] = stream.get("codec_name")
            info["audio_channels"] = stream.get("channels")

    if capture:
        info["capture_ts"] = capture
    if camera:
        info["camera"] = camera
    return info


def probe_photo(path: Path) -> Dict[str, Any]:
    """Extract photo metadata via Pillow EXIF (HEIC via pillow-heif if installed)."""
    from PIL import Image, ExifTags
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    info: Dict[str, Any] = {}
    with Image.open(path) as img:
        info["width"], info["height"] = img.size
        exif = img.getexif()
        if exif:
            by_name = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            make = str(by_name.get("Make", "")).strip()
            model = str(by_name.get("Model", "")).strip()
            if model:
                info["camera"] = f"{make} {model}".strip() if make and make not in model else model
            # DateTimeOriginal lives in the EXIF IFD on modern files
            try:
                ifd = exif.get_ifd(ExifTags.IFD.Exif)
                dt = ifd.get(ExifTags.Base.DateTimeOriginal) or by_name.get("DateTime")
            except Exception:
                dt = by_name.get("DateTime")
            if dt:
                # EXIF format "YYYY:MM:DD HH:MM:SS" → ISO
                dt = str(dt)
                if len(dt) >= 19 and dt[4] == ":" and dt[7] == ":":
                    dt = dt[:10].replace(":", "-") + "T" + dt[11:19]
                info["capture_ts"] = dt
            try:
                lens_ifd = exif.get_ifd(ExifTags.IFD.Exif)
                lens = lens_ifd.get(ExifTags.Base.LensModel)
                if lens:
                    info["lens"] = str(lens)
            except Exception:
                pass
    return info


def probe_asset(db_path: Path, asset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Probe one asset. Runs in a worker thread — opens its own DB handle
    because sqlite3 connections are not shared across threads.
    """
    db = ShootDB(db_path)
    asset_id = asset["id"]
    path = Path(asset["abs_path"])
    try:
        db.start_job(asset["shoot_id"], asset_id, "probe")
        if asset["media_type"] in ("video", "audio"):
            info = probe_av(path)
        else:
            try:
                info = probe_photo(path)
            except Exception:
                # Camera RAW (.arw/.cr3/...) isn't PIL-readable; register the
                # asset with file metadata only rather than failing ingest.
                if path.suffix.lower() in {".dng", ".arw", ".cr2", ".cr3",
                                           ".nef", ".raf", ".orf"}:
                    info = {}
                else:
                    raise
        info["quick_hash"] = quick_hash(path, asset["size_bytes"])
        info["status"] = "probed"
        db.update_asset(asset_id, **info)
        db.finish_job(asset_id, "probe", "done")
        return {"id": asset_id, "ok": True}
    except Exception as e:
        db.update_asset(asset_id, status="error", error=str(e)[:500])
        db.finish_job(asset_id, "probe", "failed", str(e)[:500])
        return {"id": asset_id, "ok": False, "error": str(e)}
    finally:
        db.close()


def scan(db: ShootDB, shoot_id: int, workers: int = DEFAULT_WORKERS,
         on_progress=None) -> Dict[str, int]:
    """
    Full scan: register files, then probe anything new or changed.

    Returns summary counts: found, new_or_changed, probed, failed.
    """
    shoot = db.get_shoot(shoot_id)
    root = Path(shoot["root_path"])

    files = walk_media(root)
    changed = 0
    for path in files:
        stat = path.stat()
        _, was_changed = db.upsert_asset(
            shoot_id, str(path.relative_to(root)), str(path),
            classify(path), stat.st_size, stat.st_mtime)
        if was_changed:
            changed += 1

    pending = db.assets_needing(shoot_id, "probe")
    pending_dicts = [dict(a) for a in pending]

    probed = failed = 0
    if pending_dicts:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(probe_asset, db.db_path, a) for a in pending_dicts]
            for future in as_completed(futures):
                result = future.result()
                if result["ok"]:
                    probed += 1
                else:
                    failed += 1
                if on_progress:
                    on_progress(probed + failed, len(pending_dicts))

    return {"found": len(files), "new_or_changed": changed,
            "probed": probed, "failed": failed}
