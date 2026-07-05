"""
Candidates - fuse per-scene signals into ranked clip candidates.

The scene is the candidate unit. For each scene we aggregate:
- speech overlap (VAD)              → A-roll signal
- transcript word density           → A-roll signal
- CLIP tag categories               → A-roll ("talking to camera") or
                                      B-roll (action/atmosphere), junk penalty
- embedding drift between frames    → motion proxy (B-roll)
- RMS energy peaks                  → excitement (B-roll)
- frame sharpness                   → quality gate for both

Scores are mechanical and only decide WHO gets in front of Claude;
Claude's eye on the contact sheets makes the actual call. Re-running
wipes unreviewed candidates but never touches Claude-reviewed ones.
"""
import json
from typing import Any, Dict, List, Optional

from .db import ShootDB

MAX_AROLL_S = 60.0   # merged A-roll candidates cap
MAX_BROLL_S = 25.0
MIN_CANDIDATE_S = 2.0


def _overlap(a_start, a_end, b_start, b_end) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _scene_signals(db: ShootDB, asset: Dict, scene: Dict,
                   transcript_segments: List[Dict],
                   speech_segments: List[Dict],
                   rms_peaks: List[Dict]) -> Dict[str, Any]:
    import numpy as np
    from ..operations.embed import unpack_embedding

    start, end = scene["start_s"], scene["end_s"]
    duration = max(end - start, 0.01)

    speech_s = sum(_overlap(start, end, s["start_s"], s["end_s"])
                   for s in speech_segments)
    words = sum(len(t.get("text", "").split()) for t in transcript_segments
                if _overlap(start, end, t["start"], t["end"]) > 0)
    peaks = sum(1 for p in rms_peaks
                if _overlap(start, end, p["start_s"], p["end_s"]) > 0)

    frames = db.conn.execute(
        "SELECT id, ts_s, sharpness, embedding FROM frames "
        "WHERE asset_id = ? AND ts_s >= ? AND ts_s < ? ORDER BY ts_s",
        (asset["id"], start, end)).fetchall()

    tag_scores: Dict[str, float] = {}
    tag_prompts: Dict[str, float] = {}
    for frame in frames:
        for tag in db.conn.execute(
                "SELECT label, score FROM frame_tags WHERE frame_id = ?",
                (frame["id"],)):
            category, _, prompt = tag["label"].partition(":")
            tag_scores[category] = max(tag_scores.get(category, 0.0), tag["score"])
            tag_prompts[prompt] = max(tag_prompts.get(prompt, 0.0), tag["score"])

    motion = 0.0
    embeddings = [unpack_embedding(f["embedding"]) for f in frames if f["embedding"]]
    if len(embeddings) >= 2:
        drifts = [1.0 - float(np.dot(embeddings[i], embeddings[i + 1]))
                  for i in range(len(embeddings) - 1)]
        motion = sum(drifts) / len(drifts)

    sharpness_values = [f["sharpness"] for f in frames if f["sharpness"] is not None]
    sharpness = sum(sharpness_values) / len(sharpness_values) if sharpness_values else None

    top_tags = sorted(tag_prompts.items(), key=lambda kv: -kv[1])[:3]
    return {
        "speech_ratio": round(speech_s / duration, 3),
        "word_density": round(words / duration, 2),   # words/sec
        "rms_peak_windows": peaks,
        "motion": round(motion, 4),
        "sharpness_avg": round(sharpness, 1) if sharpness is not None else None,
        "tags": {k: round(v, 3) for k, v in tag_scores.items()},
        "top_tags": [prompt for prompt, _ in top_tags],
    }


def _score(signals: Dict[str, Any]) -> Dict[str, float]:
    """A-roll and B-roll scores in 0..~1 from fused signals."""
    tags = signals["tags"]
    junk = tags.get("junk", 0.0)

    aroll = signals["speech_ratio"] * (
        0.5 + min(signals["word_density"] / 3.0, 1.0) * 0.5)
    aroll *= 1.0 + tags.get("aroll", 0.0)

    energy = min(signals["rms_peak_windows"] / 6.0, 1.0)
    visual = max(tags.get("action", 0.0), tags.get("atmosphere", 0.0) * 0.6,
                 tags.get("custom", 0.0))
    broll = 0.4 * min(signals["motion"] / 0.15, 1.0) + 0.3 * energy + 0.3 * visual

    penalty = 1.0 - min(junk, 0.6)
    return {"aroll": round(aroll * penalty, 4), "broll": round(broll * penalty, 4)}


def generate_candidates(db: ShootDB, shoot_id: int) -> Dict[str, int]:
    """Score every scene, merge runs, write candidates. Idempotent for
    unreviewed rows; Claude-reviewed candidates are preserved."""
    db.conn.execute(
        "DELETE FROM candidates WHERE status IN ('unreviewed', 'shortlisted') "
        "AND asset_id IN (SELECT id FROM assets WHERE shoot_id = ?)", (shoot_id,))

    n_scenes = n_candidates = 0
    for asset in db.list_assets(shoot_id, media_type="video"):
        if asset["status"] != "probed":
            continue
        asset = dict(asset)
        scenes = [dict(r) for r in db.conn.execute(
            "SELECT start_s, end_s FROM scenes WHERE asset_id = ? ORDER BY start_s",
            (asset["id"],))]
        if not scenes:
            continue

        transcript_row = db.conn.execute(
            "SELECT segments_json FROM transcripts WHERE asset_id = ?",
            (asset["id"],)).fetchone()
        transcript_segments = (json.loads(transcript_row["segments_json"])
                               if transcript_row else [])
        speech_segments = [dict(r) for r in db.conn.execute(
            "SELECT start_s, end_s FROM audio_features "
            "WHERE asset_id = ? AND kind = 'speech'", (asset["id"],))]
        rms_peaks = [dict(r) for r in db.conn.execute(
            "SELECT start_s, end_s FROM audio_features "
            "WHERE asset_id = ? AND kind = 'rms_peak'", (asset["id"],))]

        scored = []
        for scene in scenes:
            signals = _scene_signals(db, asset, scene, transcript_segments,
                                     speech_segments, rms_peaks)
            scores = _score(signals)
            kind = ("aroll" if scores["aroll"] >= scores["broll"] else "broll")
            scored.append({**scene, "signals": signals, "scores": scores,
                           "kind": kind})
            n_scenes += 1

        for candidate in _merge_runs(scored):
            if candidate["end_s"] - candidate["start_s"] < MIN_CANDIDATE_S:
                continue
            excerpt = _excerpt(transcript_segments,
                               candidate["start_s"], candidate["end_s"])
            db.conn.execute(
                "INSERT INTO candidates (asset_id, start_s, end_s, kind_guess, "
                "local_score, signals_json, transcript_excerpt, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed')",
                (asset["id"], candidate["start_s"], candidate["end_s"],
                 candidate["kind"], candidate["score"],
                 json.dumps(candidate["signals"]), excerpt))
            n_candidates += 1

    db.conn.commit()
    return {"scenes_scored": n_scenes, "candidates": n_candidates}


def _merge_runs(scored: List[Dict]) -> List[Dict]:
    """Merge contiguous same-kind scenes into candidates, capped by kind."""
    candidates: List[Dict] = []
    run: List[Dict] = []

    def flush():
        if not run:
            return
        kind = run[0]["kind"]
        cap = MAX_AROLL_S if kind == "aroll" else MAX_BROLL_S
        start = run[0]["start_s"]
        signals = [s["signals"] for s in run]
        score = max(s["scores"][kind] for s in run)
        end = run[-1]["end_s"]
        # split over-cap runs into cap-sized chunks
        while end - start > cap:
            candidates.append({"start_s": start, "end_s": start + cap,
                               "kind": kind, "score": score,
                               "signals": _combine(signals)})
            start += cap
        candidates.append({"start_s": start, "end_s": end, "kind": kind,
                           "score": score, "signals": _combine(signals)})

    for scene in scored:
        if run and (scene["kind"] != run[-1]["kind"]
                    or scene["start_s"] - run[-1]["end_s"] > 0.5):
            flush()
            run = []
        run.append(scene)
    flush()
    return candidates


def _combine(signal_list: List[Dict]) -> Dict:
    """Representative signals for a merged run (max-pool the drivers)."""
    if len(signal_list) == 1:
        return signal_list[0]
    combined = dict(signal_list[0])
    for signals in signal_list[1:]:
        combined["speech_ratio"] = max(combined["speech_ratio"], signals["speech_ratio"])
        combined["motion"] = max(combined["motion"], signals["motion"])
        combined["rms_peak_windows"] += signals["rms_peak_windows"]
        for prompt in signals["top_tags"]:
            if prompt not in combined["top_tags"] and len(combined["top_tags"]) < 5:
                combined["top_tags"].append(prompt)
    return combined


def _excerpt(segments: List[Dict], start_s: float, end_s: float,
             pad_s: float = 2.0, max_chars: int = 600) -> Optional[str]:
    parts = [seg["text"].strip() for seg in segments
             if _overlap(start_s - pad_s, end_s + pad_s, seg["start"], seg["end"]) > 0]
    if not parts:
        return None
    text = " ".join(parts)
    return text[:max_chars] + ("…" if len(text) > max_chars else "")
