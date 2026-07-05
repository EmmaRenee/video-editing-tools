"""
Analyze - Tier-1 local analysis over a whole shoot.

Orchestrates the funnel's cheap stage: scenes → VAD/energy →
selective transcription → CLIP embeddings/tags → photo quality →
audio events → photo grouping. Every phase is resumable via the
jobs table; models load once per process (serial lanes).
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import ShootDB
from .runner import ShootRunner, SkipAsset

# Assets below this VAD speech ratio never hit Whisper — the funnel's
# single biggest cost saver on B-roll-heavy shoots.
TRANSCRIBE_SPEECH_RATIO = 0.15

PHASES = ["scenes", "vad", "transcribe", "embed", "quality", "events", "photos"]


def speech_ratio_for(db: ShootDB, asset_id: int) -> Optional[float]:
    row = db.conn.execute(
        "SELECT score FROM audio_features WHERE asset_id = ? AND kind = 'speech_ratio'",
        (asset_id,)).fetchone()
    return row["score"] if row else None


# ----------------------------------------------------------------------
# Per-asset workers (db, asset_dict, context) -> None; raise to fail,
# raise SkipAsset to record a funnel skip.

def scenes_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    from ..operations.scene import detect_scenes
    scenes = detect_scenes(Path(asset["abs_path"]),
                           threshold=context.get("scene_threshold", 27.0))
    db.save_scenes(asset["id"], scenes)


def vad_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    from ..operations.vad import analyze_speech
    result = analyze_speech(Path(asset["abs_path"]))
    db.save_audio_features(asset["id"], "speech", [
        {"start_s": s["start_s"], "end_s": s["end_s"], "label": "speech", "score": 1.0}
        for s in result["speech_segments"]])
    db.save_audio_features(asset["id"], "rms_peak", [
        {**p, "label": "rms_peak"} for p in result["rms_peaks"]])
    db.save_audio_features(asset["id"], "speech_ratio", [
        {"start_s": 0, "end_s": result["duration_s"],
         "label": "speech_ratio", "score": result["speech_ratio"]}])


def transcribe_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    from ..operations.transcribe import TranscribeWhisper

    ratio = speech_ratio_for(db, asset["id"])
    threshold = context.get("speech_ratio_threshold", TRANSCRIBE_SPEECH_RATIO)
    if ratio is not None and ratio < threshold:
        raise SkipAsset(f"speech_ratio {ratio:.2f} < {threshold}")

    op = TranscribeWhisper(model=context.get("whisper_model", "small"),
                           output_format="json", word_timestamps=True)
    out_dir = Path(context["workspace"]) / "transcripts"
    result = op.execute(Path(asset["abs_path"]), out_dir, {})
    if not result.success:
        raise RuntimeError(result.error)
    db.save_transcript(asset["id"],
                       result.data.get("language") or "",
                       context.get("whisper_model", "small"),
                       result.data.get("text", ""),
                       result.data.get("segments", []))


def embed_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    from ..operations.embed import EmbedFrames

    scenes = [{"start": r["start_s"], "end": r["end_s"]}
              for r in db.conn.execute(
                  "SELECT start_s, end_s FROM scenes WHERE asset_id = ? ORDER BY start_s",
                  (asset["id"],))]
    op = EmbedFrames(interval_s=context.get("frame_interval_s", 10.0))
    result = op.execute(
        Path(asset["abs_path"]), Path(context["workspace"]),
        {"duration_s": asset["duration_s"], "scenes": scenes,
         "extra_prompts": context.get("extra_prompts", [])})
    if not result.success:
        raise RuntimeError(result.error)

    from ..operations.quality import measure_image
    db.conn.execute("DELETE FROM frames WHERE asset_id = ?", (asset["id"],))
    for frame in result.data["frames"]:
        metrics = {}
        try:
            metrics = measure_image(frame["thumb_path"])
        except Exception:
            pass
        frame_id = db.save_frame(
            asset["id"], frame["ts_s"], thumb_path=frame["thumb_path"],
            sharpness=metrics.get("sharpness"),
            exposure_low_pct=metrics.get("exposure_low_pct"),
            exposure_high_pct=metrics.get("exposure_high_pct"),
            embedding=frame.get("embedding"))
        for tag in frame.get("tags", []):
            db.conn.execute(
                "INSERT INTO frame_tags (frame_id, label, score, source) "
                "VALUES (?, ?, ?, 'clip_zeroshot')",
                (frame_id, f"{tag['category']}:{tag['prompt']}", tag["score"]))
    db.conn.commit()


def quality_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    from . import photos
    photos.analyze_photo(db, asset, context)


def events_worker(db: ShootDB, asset: Dict[str, Any], context: Dict[str, Any]):
    try:
        from ..operations.events import detect_events
        events = detect_events(Path(asset["abs_path"]))
    except ImportError:
        raise SkipAsset("panns-inference not installed")
    db.save_audio_features(asset["id"], "event", events)


# ----------------------------------------------------------------------

def analyze_shoot(db: ShootDB, shoot_id: int,
                  only: Optional[List[str]] = None,
                  workers: int = 2,
                  whisper_model: str = "small",
                  progress=None) -> Dict[str, Dict[str, int]]:
    """Run all (or selected) analysis phases. Returns per-phase counts."""
    shoot = db.get_shoot(shoot_id)
    config = db.get_config(shoot_id)
    workspace = shoot["workspace_path"]
    context = {
        "workspace": workspace,
        "whisper_model": whisper_model,
        "extra_prompts": config.get("extra_prompts", []),
        "speech_ratio_threshold": config.get("speech_ratio_threshold",
                                             TRANSCRIBE_SPEECH_RATIO),
    }
    runner = ShootRunner(db, shoot_id, progress=progress)
    selected = only or PHASES
    summary: Dict[str, Dict[str, int]] = {}

    if "scenes" in selected:
        summary["scenes"] = runner.run_phase(
            "scenes", scenes_worker, media_type="video", workers=workers,
            context=context)
    if "vad" in selected:
        for mtype in ("video", "audio"):
            counts = runner.run_phase("vad", vad_worker, media_type=mtype,
                                      workers=workers, context=context)
            summary["vad"] = _merge(summary.get("vad"), counts)
    if "transcribe" in selected:
        for mtype in ("video", "audio"):
            counts = runner.run_phase("transcribe", transcribe_worker,
                                      media_type=mtype, workers=1,
                                      context=context)
            summary["transcribe"] = _merge(summary.get("transcribe"), counts)
    if "embed" in selected:
        summary["embed"] = runner.run_phase(
            "embed", embed_worker, media_type="video", workers=1,
            context=context)
    if "quality" in selected:
        quality_context = dict(context)
        try:
            from ..operations.embed import get_encoder
            quality_context["encoder"] = get_encoder()
        except ImportError:
            quality_context["encoder"] = None
        summary["quality"] = runner.run_phase(
            "quality", quality_worker, media_type="photo", workers=1,
            context=quality_context)
    if "events" in selected:
        for mtype in ("video", "audio"):
            counts = runner.run_phase("events", events_worker,
                                      media_type=mtype, workers=1,
                                      context=context)
            summary["events"] = _merge(summary.get("events"), counts)
    if "photos" in selected:
        from . import photos
        summary["photos"] = photos.group_and_rank(db, shoot_id)

    return summary


def _merge(a: Optional[Dict[str, int]], b: Dict[str, int]) -> Dict[str, int]:
    if not a:
        return b
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}
