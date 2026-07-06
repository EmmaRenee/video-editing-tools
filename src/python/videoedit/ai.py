"""Project-agnostic AI scoring helpers.

The AI layer stays optional and artifact-driven. Nothing in the deterministic
rating path changes unless a caller explicitly supplies one of these artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import json
import os
import re
from typing import Any, Protocol

from .ffmpeg import has_command, probe_media, run_command_check, scan_video_files
from .timecode import seconds_to_hhmmss, timecode_to_seconds


AI_FRAME_SCHEMA_VERSION = "videoedit.ai_frame_scores.v1"
AI_MISSED_SCHEMA_VERSION = "videoedit.ai_missed_moments.v1"
AI_REVIEW_SCHEMA_VERSION = "videoedit.missed_review.v1"


@dataclass(frozen=True)
class AIPrompt:
    id: str
    label: str
    text: str
    intent: str


@dataclass(frozen=True)
class AIProfile:
    id: str
    name: str
    description: str
    output_types: tuple[str, ...]
    prompts: tuple[AIPrompt, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "output_types": list(self.output_types),
            "labels": sorted({prompt.label for prompt in self.prompts}),
            "prompts": [
                {
                    "id": prompt.id,
                    "label": prompt.label,
                    "text": prompt.text,
                    "intent": prompt.intent,
                }
                for prompt in self.prompts
            ],
        }


class FrameScoreEncoder(Protocol):
    provider_name: str
    model_name: str

    def score_images(self, image_paths: list[str], prompts: list[str]) -> list[list[float]]:
        """Return scores as rows of image x prompt floats."""


PROFILES: dict[str, AIProfile] = {
    "general_broll": AIProfile(
        id="general_broll",
        name="General B-roll",
        description="Broad visual interest for usable supporting footage.",
        output_types=("review", "broll", "roughcut"),
        prompts=(
            AIPrompt("establishing", "ai_broll_candidate", "a clean establishing shot with useful visual context", "context"),
            AIPrompt("detail_motion", "ai_broll_candidate", "a close detail shot with clear movement and texture", "texture"),
            AIPrompt("human_action", "ai_broll_candidate", "a person doing a visible task with hands or tools", "action"),
            AIPrompt("strong_opener", "ai_reel_opener", "a visually striking opening shot for a short reel", "opener"),
        ),
    ),
    "garage_shop": AIProfile(
        id="garage_shop",
        name="Garage Shop",
        description="Shop, build, repair, fabrication, and vehicle-detail moments.",
        output_types=("broll", "social_reel", "educational"),
        prompts=(
            AIPrompt("hands_tools", "ai_garage_work", "hands using tools on a vehicle or mechanical part", "work"),
            AIPrompt("vehicle_detail", "ai_garage_work", "a clear close-up of a vehicle part, engine bay, wheel, or body panel", "detail"),
            AIPrompt("shop_motion", "ai_broll_candidate", "active work happening in a garage, workshop, or service bay", "motion"),
            AIPrompt("shop_opener", "ai_reel_opener", "a strong garage or vehicle shot that could open a short edit", "opener"),
        ),
    ),
    "motorsports": AIProfile(
        id="motorsports",
        name="Motorsports",
        description="Vehicle action, track context, pits, and high-energy race moments.",
        output_types=("broll", "reel", "event_recap"),
        prompts=(
            AIPrompt("track_action", "ai_vehicle_action", "race vehicles moving quickly on track", "action"),
            AIPrompt("passing_battle", "ai_vehicle_action", "vehicles close together in a pass, battle, start, or restart", "event"),
            AIPrompt("pit_activity", "ai_broll_candidate", "pit lane, paddock, crew, or race preparation activity", "context"),
            AIPrompt("race_opener", "ai_reel_opener", "a dramatic motorsports shot suitable for a reel opener", "opener"),
        ),
    ),
    "interview": AIProfile(
        id="interview",
        name="Interview",
        description="Human talking-head and expressive soundbite moments.",
        output_types=("review", "documentary", "youtube"),
        prompts=(
            AIPrompt("talking_head", "ai_interview_moment", "a clear interview shot of a person speaking to camera or interviewer", "soundbite"),
            AIPrompt("expressive_face", "ai_interview_moment", "an expressive face or gesture during a conversation", "emotion"),
            AIPrompt("two_person", "ai_interview_moment", "two people talking in an interview or conversation setup", "dialogue"),
            AIPrompt("interview_broll", "ai_broll_candidate", "contextual b-roll that supports an interview story", "context"),
        ),
    ),
    "event_recap": AIProfile(
        id="event_recap",
        name="Event Recap",
        description="Arrival, crowd, action, signage, and recap-friendly sequences.",
        output_types=("reel", "youtube", "social_reel"),
        prompts=(
            AIPrompt("arrival", "ai_reel_opener", "arrival, entrance, venue, crowd, or first-look event shot", "opener"),
            AIPrompt("event_action", "ai_broll_candidate", "people actively participating in an event", "action"),
            AIPrompt("event_detail", "ai_broll_candidate", "event detail, signage, branded object, or atmosphere shot", "detail"),
            AIPrompt("highlight", "ai_reel_opener", "high-energy event highlight suitable for a recap", "highlight"),
        ),
    ),
    "social_reel": AIProfile(
        id="social_reel",
        name="Social Reel",
        description="Fast, readable, visually punchy short-form moments.",
        output_types=("reel", "shorts", "social"),
        prompts=(
            AIPrompt("hook", "ai_reel_opener", "a strong hook frame with immediate visual impact", "opener"),
            AIPrompt("action", "ai_broll_candidate", "a concise action moment that reads quickly on mobile", "action"),
            AIPrompt("vehicle_mobile", "ai_vehicle_action", "a dynamic vehicle shot that works in a short social reel", "vehicle"),
            AIPrompt("human_mobile", "ai_interview_moment", "a clear human reaction or speaking moment for short-form video", "human"),
        ),
    ),
    "documentary": AIProfile(
        id="documentary",
        name="Documentary",
        description="Story, context, process, and human-centered editorial footage.",
        output_types=("documentary", "youtube", "roughcut"),
        prompts=(
            AIPrompt("story_context", "ai_broll_candidate", "contextual footage that explains a place, process, or subject", "context"),
            AIPrompt("human_story", "ai_interview_moment", "a person in a meaningful story or documentary moment", "story"),
            AIPrompt("process_detail", "ai_broll_candidate", "a detailed process shot that shows how something works", "process"),
            AIPrompt("doc_opener", "ai_reel_opener", "a cinematic documentary opening image", "opener"),
        ),
    ),
}


def list_ai_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "labels": sorted({prompt.label for prompt in profile.prompts}),
            "prompt_count": len(profile.prompts),
            "output_types": list(profile.output_types),
        }
        for profile in sorted(PROFILES.values(), key=lambda item: item.id)
    ]


def get_ai_profile(profile_id: str) -> AIProfile:
    normalized = str(profile_id).strip().lower().replace("-", "_")
    if normalized not in PROFILES:
        available = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown AI profile: {profile_id}. Available profiles: {available}")
    return PROFILES[normalized]


def show_ai_profile(profile_id: str) -> dict[str, Any]:
    return get_ai_profile(profile_id).to_dict()


def score_frames(
    input_path: str,
    output: str,
    profile_id: str = "general_broll",
    sample_interval: float = 10.0,
    max_frames_per_file: int = 8,
    min_score: float = 0.22,
    cache: bool = True,
    model: str = "ViT-B-32",
    pretrained: str = "laion2b_s34b_b79k",
    timeout: int = 180,
    encoder: FrameScoreEncoder | None = None,
    frame_sampler: Any | None = None,
    media_probe: Any | None = None,
) -> dict[str, Any]:
    """Score sampled video frames against an AI profile prompt bank."""

    profile = get_ai_profile(profile_id)
    output = os.fspath(output)
    existing = _read_optional_json(output) if cache else {}
    existing_sources = {
        row.get("source"): row
        for row in existing.get("sources", [])
        if isinstance(row, dict) and row.get("source")
    }
    files = _input_files(input_path)
    output_dir = os.path.dirname(output) or "."
    frames_dir = os.path.join(output_dir, "ai_frames")
    os.makedirs(frames_dir, exist_ok=True)
    warnings: list[str] = []
    sources: list[dict[str, Any]] = []
    prompt_texts = [prompt.text for prompt in profile.prompts]

    if encoder is None:
        try:
            encoder = OpenCLIPEncoder(model=model, pretrained=pretrained)
        except ImportError as exc:
            payload = _unavailable_payload(input_path, profile, str(exc))
            _write_json(output, payload)
            return {"output": output, "status": "unavailable", "count": 0, "error": payload["error"]}

    probe = media_probe or probe_media
    sampler = frame_sampler or _sample_frame
    for source in files:
        signature = _source_signature(source, profile.id, sample_interval, max_frames_per_file, min_score, model, pretrained)
        cached = existing_sources.get(source)
        if cached and cached.get("signature") == signature:
            sources.append(cached)
            continue

        asset = probe(source, timeout=min(timeout, 60))
        duration = float(getattr(asset, "duration", 0.0) or 0.0)
        timestamps = sample_timestamps(duration, sample_interval, max_frames_per_file)
        frame_paths = []
        frame_rows = []
        source_hash = hashlib.sha1(os.fspath(source).encode("utf-8")).hexdigest()[:8]
        source_stem = f"{_safe_slug(os.path.splitext(os.path.basename(source))[0])}_{source_hash}"
        for timestamp in timestamps:
            frame_name = f"{source_stem}_{int(round(timestamp * 1000)):010d}.jpg"
            frame_path = os.path.join(frames_dir, frame_name)
            try:
                sampler(source, timestamp, frame_path, timeout=timeout)
            except Exception as exc:
                warnings.append(f"frame sampling failed for {source} at {timestamp:.3f}s: {exc}")
                continue
            frame_paths.append(frame_path)
            frame_rows.append({"time_seconds": round(timestamp, 3), "frame": os.path.relpath(frame_path, output_dir)})

        if not frame_paths:
            sources.append(
                {
                    "source": source,
                    "signature": signature,
                    "duration": duration,
                    "frames": [],
                    "labels": [],
                    "top_score": 0.0,
                    "warnings": ["no frames sampled"],
                }
            )
            continue

        score_rows = encoder.score_images(frame_paths, prompt_texts)
        scored_frames = []
        for frame, scores in zip(frame_rows, score_rows):
            scored_frames.append(_frame_payload(frame, scores, profile, min_score))
        labels = sorted({label for frame in scored_frames for label in frame.get("labels", [])})
        sources.append(
            {
                "source": source,
                "signature": signature,
                "duration": duration,
                "frame_count": len(scored_frames),
                "labels": labels,
                "top_score": round(max((frame.get("top_score", 0.0) for frame in scored_frames), default=0.0), 4),
                "frames": scored_frames,
                "warnings": [],
            }
        )

    payload = {
        "schema_version": AI_FRAME_SCHEMA_VERSION,
        "artifact_kind": "ai_frame_scores",
        "generated": datetime.now().isoformat(),
        "input": os.fspath(input_path),
        "profile": profile.to_dict(),
        "provider": "openclip",
        "provider_metadata": {
            "name": getattr(encoder, "provider_name", "openclip"),
            "model": getattr(encoder, "model_name", model),
            "pretrained": pretrained,
            "artifact_kind": "ai_frame_scores",
        },
        "settings": {
            "sample_interval": float(sample_interval),
            "max_frames_per_file": int(max_frames_per_file),
            "min_score": float(min_score),
            "cache": bool(cache),
        },
        "status": "ok",
        "source_count": len(sources),
        "frame_count": sum(len(row.get("frames", [])) for row in sources),
        "source_summaries": _source_summaries(sources),
        "sources": sources,
        "warnings": warnings,
    }
    _write_json(output, payload)
    return {"output": output, "status": "ok", "sources": len(sources), "frames": payload["frame_count"], "warnings": warnings}


def find_missed_moments(
    ratings_json: str,
    ai_frame_scores_json: str,
    output: str,
    min_score: float = 0.35,
    window_pre_roll: float = 2.0,
    window_post_roll: float = 4.0,
    merge_gap: float = 5.0,
) -> dict[str, Any]:
    ratings = _read_json(ratings_json)
    scores = _read_json(ai_frame_scores_json)
    candidates = list(ratings.get("candidates", []))
    positive = [candidate for candidate in candidates if str(candidate.get("action")) in {"select", "review", "broll"}]
    moments = []

    for source_payload in scores.get("sources", []):
        source = source_payload.get("source")
        if not source:
            continue
        rows = []
        for frame in source_payload.get("frames", []):
            top_score = float(frame.get("top_score", 0.0) or 0.0)
            labels = list(frame.get("labels", []))
            if top_score < min_score or not labels:
                continue
            timestamp = float(frame.get("time_seconds", 0.0) or 0.0)
            if _overlaps_existing_positive(source, timestamp, positive):
                continue
            rows.append(
                {
                    "source": source,
                    "start_seconds": max(0.0, timestamp - window_pre_roll),
                    "end_seconds": timestamp + window_post_roll,
                    "confidence": top_score,
                    "labels": labels,
                    "prompt_matches": frame.get("prompt_scores", [])[:4],
                    "frame": frame.get("frame"),
                    "reason": frame.get("explanation") or "AI frame score above threshold",
                    "existing_candidate": _nearest_candidate(source, timestamp, candidates),
                }
            )
        moments.extend(_merge_missed_rows(rows, merge_gap))

    moments.sort(key=lambda item: (-item["confidence"], item["source"], item["start_seconds"]))
    for index, moment in enumerate(moments, 1):
        moment["id"] = f"missed_{index:04d}"
        moment["start"] = seconds_to_hhmmss(moment["start_seconds"])
        moment["end"] = seconds_to_hhmmss(moment["end_seconds"])

    payload = {
        "schema_version": AI_MISSED_SCHEMA_VERSION,
        "artifact_kind": "ai_missed_moments",
        "generated": datetime.now().isoformat(),
        "ratings": os.fspath(ratings_json),
        "ai_frame_scores": os.fspath(ai_frame_scores_json),
        "settings": {
            "min_score": float(min_score),
            "window_pre_roll": float(window_pre_roll),
            "window_post_roll": float(window_post_roll),
            "merge_gap": float(merge_gap),
        },
        "count": len(moments),
        "moments": moments,
    }
    _write_json(output, payload)
    return {"output": os.fspath(output), "count": len(moments)}


def generate_missed_review(missed_json: str, output_dir: str) -> dict[str, Any]:
    data = _read_json(missed_json)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    decisions = {
        "schema_version": AI_REVIEW_SCHEMA_VERSION,
        "generated": datetime.now().isoformat(),
        "ratings": data.get("ratings"),
        "missed_moments": os.fspath(missed_json),
        "decisions": [_missed_decision_template(moment, index) for index, moment in enumerate(data.get("moments", []), 1)],
    }
    decisions_path = os.path.join(output_dir, "missed_review_decisions.json")
    html_path = os.path.join(output_dir, "missed_review.html")
    _write_json(decisions_path, decisions)
    _write_missed_review_html(html_path, data, decisions)
    return {"html": html_path, "decisions": decisions_path, "count": len(decisions["decisions"])}


class OpenCLIPEncoder:
    provider_name = "openclip"

    def __init__(self, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k") -> None:
        try:
            import open_clip
            from PIL import Image
            import torch
        except ImportError as exc:
            raise ImportError(
                "OpenCLIP frame scoring requires open_clip_torch, torch, and Pillow. "
                "Install with: python -m pip install -e './src/python[ai]'"
            ) from exc
        self.open_clip = open_clip
        self.Image = Image
        self.torch = torch
        self.device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model, pretrained=pretrained)
        self.model = self.model.to(self.device).eval()
        self.tokenizer = open_clip.get_tokenizer(model)
        self.model_name = model

    def score_images(self, image_paths: list[str], prompts: list[str]) -> list[list[float]]:
        torch = self.torch
        images = [self.preprocess(self.Image.open(path).convert("RGB")) for path in image_paths]
        batch = torch.stack(images).to(self.device)
        tokens = self.tokenizer(prompts).to(self.device)
        with torch.no_grad():
            image_features = self.model.encode_image(batch)
            text_features = self.model.encode_text(tokens)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            probabilities = (100.0 * image_features @ text_features.T).softmax(dim=-1)
        return probabilities.cpu().tolist()


def sample_timestamps(duration: float, sample_interval: float, max_frames: int) -> list[float]:
    duration = max(0.0, float(duration or 0.0))
    max_frames = max(1, int(max_frames))
    interval = max(0.5, float(sample_interval or 10.0))
    if duration <= 0:
        return [0.0]
    timestamps = []
    timestamp = min(duration / 2.0, interval / 2.0)
    while timestamp < duration and len(timestamps) < max_frames:
        timestamps.append(round(timestamp, 3))
        timestamp += interval
    return timestamps or [round(duration / 2.0, 3)]


def _frame_payload(frame: dict[str, Any], scores: list[float], profile: AIProfile, min_score: float) -> dict[str, Any]:
    prompt_scores = []
    for prompt, score in zip(profile.prompts, scores):
        prompt_scores.append(
            {
                "id": prompt.id,
                "label": prompt.label,
                "prompt": prompt.text,
                "intent": prompt.intent,
                "score": round(float(score), 4),
            }
        )
    prompt_scores.sort(key=lambda item: (-item["score"], item["id"]))
    labels = sorted({item["label"] for item in prompt_scores if item["score"] >= min_score})
    if not labels and prompt_scores:
        labels = [prompt_scores[0]["label"]]
    top = prompt_scores[0] if prompt_scores else {"score": 0.0, "label": "ai_frame_score", "prompt": ""}
    return {
        "time": seconds_to_hhmmss(frame["time_seconds"]),
        "time_seconds": frame["time_seconds"],
        "frame": frame["frame"],
        "top_score": top["score"],
        "top_label": top["label"],
        "labels": labels,
        "prompt_scores": prompt_scores,
        "explanation": f"{top['label']} from prompt: {top['prompt']}" if top.get("prompt") else "AI frame score",
    }


def _merge_missed_rows(rows: list[dict[str, Any]], merge_gap: float) -> list[dict[str, Any]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda item: item["start_seconds"])
    merged = [dict(ordered[0])]
    for row in ordered[1:]:
        current = merged[-1]
        if row["start_seconds"] <= current["end_seconds"] + merge_gap:
            current["end_seconds"] = max(current["end_seconds"], row["end_seconds"])
            current["confidence"] = max(float(current["confidence"]), float(row["confidence"]))
            current["labels"] = sorted(set(current.get("labels", [])) | set(row.get("labels", [])))
            current["prompt_matches"] = _merge_prompt_matches(current.get("prompt_matches", []), row.get("prompt_matches", []))
            current["reason"] = "; ".join(sorted({current.get("reason", ""), row.get("reason", "")})).strip("; ")
            if not current.get("existing_candidate"):
                current["existing_candidate"] = row.get("existing_candidate")
            continue
        merged.append(dict(row))
    return merged


def _merge_prompt_matches(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in left + right:
        key = str(item.get("id") or item.get("prompt") or item.get("label"))
        if key not in rows or float(item.get("score", 0.0) or 0.0) > float(rows[key].get("score", 0.0) or 0.0):
            rows[key] = dict(item)
    return sorted(rows.values(), key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("id"))))[:6]


def _overlaps_existing_positive(source: str, timestamp: float, candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        if os.fspath(candidate.get("source", "")) != os.fspath(source):
            continue
        if _clip_seconds(candidate, "start", "start_seconds") <= timestamp <= _clip_seconds(candidate, "end", "end_seconds"):
            return True
    return False


def _nearest_candidate(source: str, timestamp: float, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    same_source = [candidate for candidate in candidates if os.fspath(candidate.get("source", "")) == os.fspath(source)]
    if not same_source:
        return None
    nearest = sorted(
        same_source,
        key=lambda candidate: (
            _time_gap(timestamp, _clip_seconds(candidate, "start", "start_seconds"), _clip_seconds(candidate, "end", "end_seconds")),
            -int(candidate.get("score", 0) or 0),
        ),
    )[0]
    return {
        "id": nearest.get("id") or nearest.get("label"),
        "action": nearest.get("action"),
        "score": nearest.get("score", 0),
        "start": nearest.get("start") or seconds_to_hhmmss(_clip_seconds(nearest, "start", "start_seconds")),
        "end": nearest.get("end") or seconds_to_hhmmss(_clip_seconds(nearest, "end", "end_seconds")),
        "labels": list(nearest.get("labels", [])),
    }


def _time_gap(timestamp: float, start: float, end: float) -> float:
    if start <= timestamp <= end:
        return 0.0
    return min(abs(timestamp - start), abs(timestamp - end))


def _missed_decision_template(moment: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": moment.get("id") or f"missed_{index:04d}",
        "decision": "review",
        "order": index,
        "note": "",
        "source": moment.get("source"),
        "start": moment.get("start"),
        "end": moment.get("end"),
        "start_seconds": moment.get("start_seconds"),
        "end_seconds": moment.get("end_seconds"),
        "score": moment.get("confidence"),
        "labels": list(moment.get("labels", [])),
        "reasons": [moment.get("reason", "AI-discovered missed moment")],
        "missed_moment": True,
    }


def _write_missed_review_html(path: str, data: dict[str, Any], decisions: dict[str, Any]) -> None:
    cards = []
    decision_rows = {row["id"]: row for row in decisions.get("decisions", [])}
    for moment in data.get("moments", []):
        row = decision_rows.get(moment["id"], {})
        labels = ", ".join(moment.get("labels", []))
        prompts = ", ".join(
            f"{item.get('label')} {item.get('score')}"
            for item in moment.get("prompt_matches", [])[:4]
        )
        cards.append(
            '<article class="moment"'
            f' data-id="{html.escape(moment["id"], quote=True)}"'
            f' data-source="{html.escape(str(moment.get("source", "")), quote=True)}"'
            f' data-score="{html.escape(str(moment.get("confidence", 0)), quote=True)}"'
            f' data-labels="{html.escape(labels, quote=True)}"'
            f' data-start="{html.escape(str(moment.get("start", "")), quote=True)}"'
            f' data-end="{html.escape(str(moment.get("end", "")), quote=True)}">'
            f'<h2>{html.escape(moment["id"])}</h2>'
            f'<p class="source">{html.escape(os.path.basename(str(moment.get("source", ""))))}<br>{html.escape(moment.get("start", ""))} - {html.escape(moment.get("end", ""))}</p>'
            f'<p class="score">Confidence {html.escape(str(moment.get("confidence", 0)))}</p>'
            f'<p class="labels">{html.escape(labels)}</p>'
            f'<p>{html.escape(moment.get("reason", ""))}</p>'
            f'<p>{html.escape(prompts)}</p>'
            '<div class="review-controls">'
            '<label>Decision'
            f'<select class="decision">{_missed_decision_options(row.get("decision", "review"))}</select>'
            '</label>'
            '<label>Order'
            f'<input class="order" type="number" min="1" value="{html.escape(str(row.get("order", "")), quote=True)}">'
            '</label>'
            '<label>Note<textarea class="note" rows="2"></textarea></label>'
            '</div>'
            "</article>"
        )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Videoedit Missed Moment Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #1f2933; background: #f7f9fb; }}
    header {{ position: sticky; top: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; border-bottom: 1px solid #d9e2ec; background: rgba(255,255,255,0.96); }}
    h1 {{ font-size: 18px; margin: 0; }}
    .toolbar, .filters {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    .filters {{ padding: 12px 20px; background: #fff; border-bottom: 1px solid #d9e2ec; }}
    button, select, input, textarea {{ border: 1px solid #bcccdc; border-radius: 5px; padding: 7px; font: inherit; background: #fff; color: #102a43; }}
    button {{ cursor: pointer; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; padding: 16px; }}
    .moment {{ border: 1px solid #d9e2ec; border-radius: 6px; background: #fff; padding: 12px; }}
    .moment[data-state="select"], .moment[data-state="review"], .moment[data-state="broll"] {{ border-color: #51a36d; }}
    .moment[data-state="reject"], .moment[data-state="ignore"] {{ opacity: 0.66; }}
    h2 {{ font-size: 14px; margin: 0 0 6px; }}
    p {{ font-size: 12px; line-height: 1.35; margin: 6px 0; }}
    label {{ display: grid; gap: 4px; font-size: 11px; color: #52606d; }}
    .review-controls {{ display: grid; grid-template-columns: 1fr 74px; gap: 8px; margin-top: 10px; }}
    textarea {{ grid-column: 1 / -1; resize: vertical; min-height: 54px; }}
  </style>
</head>
<body data-ratings="{html.escape(str(data.get("ratings", "")), quote=True)}" data-missed="{html.escape(str(data.get("ai_frame_scores", "")), quote=True)}">
  <header>
    <div>
      <h1>Missed Moment Review</h1>
      <p>{len(data.get("moments", []))} AI-discovered moments. These are review-only and are not auto-approved.</p>
    </div>
    <div class="toolbar">
      <span id="visibleCount"></span>
      <select id="bulkDecision"><option value="select">Select</option><option value="review">Review</option><option value="broll">B-roll</option><option value="reject">Reject</option><option value="ignore">Ignore</option></select>
      <button type="button" onclick="applyBulkDecision()">Apply to visible</button>
      <button type="button" onclick="downloadDecisions()">Download decisions JSON</button>
      <button type="button" onclick="copyDecisions()">Copy JSON</button>
    </div>
  </header>
  <section class="filters">
    <label>Search<input id="searchFilter" type="search"></label>
    <label>Decision<select id="decisionFilter"><option value="">All decisions</option><option value="select">Select</option><option value="review">Review</option><option value="broll">B-roll</option><option value="reject">Reject</option><option value="ignore">Ignore</option></select></label>
    <label>Label<select id="labelFilter"><option value="">All labels</option></select></label>
    <label>Sort<select id="sortMode"><option value="order">Order</option><option value="score-desc">Confidence high-low</option><option value="source">Source</option></select></label>
    <button type="button" onclick="clearFilters()">Clear filters</button>
  </section>
  <section class="grid" id="grid">{''.join(cards)}</section>
  <script>
    const storageKey = "videoedit-missed-review:" + document.body.dataset.missed;
    function cards() {{ return Array.from(document.querySelectorAll(".moment")); }}
    function visibleCards() {{ return cards().filter((card) => !card.hidden); }}
    function collectDecisions() {{
      return {{
        schema_version: "{AI_REVIEW_SCHEMA_VERSION}",
        generated: new Date().toISOString(),
        ratings: document.body.dataset.ratings,
        missed_moments: document.body.dataset.missed,
        decisions: cards().map((card, index) => ({{
          id: card.dataset.id,
          decision: card.querySelector(".decision").value,
          order: Number(card.querySelector(".order").value || index + 1),
          note: card.querySelector(".note").value,
          source: card.dataset.source,
          start: card.dataset.start,
          end: card.dataset.end,
          score: Number(card.dataset.score || 0),
          labels: (card.dataset.labels || "").split(",").map((value) => value.trim()).filter(Boolean),
          missed_moment: true
        }}))
      }};
    }}
    function saveState() {{
      localStorage.setItem(storageKey, JSON.stringify(collectDecisions()));
      updateCounts();
    }}
    function restoreState() {{
      const saved = localStorage.getItem(storageKey);
      if (!saved) {{ updateCounts(); return; }}
      try {{
        const byId = Object.fromEntries(JSON.parse(saved).decisions.map((item) => [item.id, item]));
        cards().forEach((card) => {{
          const item = byId[card.dataset.id];
          if (!item) return;
          card.querySelector(".decision").value = item.decision || "review";
          card.querySelector(".order").value = item.order || "";
          card.querySelector(".note").value = item.note || "";
        }});
      }} catch (error) {{ console.warn(error); }}
      updateCounts();
    }}
    function updateCounts() {{
      cards().forEach((card) => {{ card.dataset.state = card.querySelector(".decision").value; }});
      document.getElementById("visibleCount").textContent = visibleCards().length + " visible / " + cards().length + " total";
    }}
    function populateFilters() {{
      const labels = new Set();
      cards().forEach((card) => (card.dataset.labels || "").split(",").map((value) => value.trim()).filter(Boolean).forEach((value) => labels.add(value)));
      const select = document.getElementById("labelFilter");
      Array.from(labels).sort().forEach((label) => {{
        const option = document.createElement("option");
        option.value = label;
        option.textContent = label;
        select.appendChild(option);
      }});
    }}
    function preserveScroll(callback) {{
      const first = visibleCards()[0];
      const anchor = first ? {{ id: first.dataset.id, top: first.getBoundingClientRect().top }} : null;
      callback();
      if (anchor) {{
        const after = document.querySelector(`[data-id="${{anchor.id}}"]`);
        if (after) window.scrollBy(0, after.getBoundingClientRect().top - anchor.top);
      }}
    }}
    function applyFilters() {{
      preserveScroll(() => {{
        const query = document.getElementById("searchFilter").value.toLowerCase();
        const decision = document.getElementById("decisionFilter").value;
        const label = document.getElementById("labelFilter").value;
        cards().forEach((card) => {{
          const labels = (card.dataset.labels || "").split(",").map((value) => value.trim());
          card.hidden = !((!query || card.textContent.toLowerCase().includes(query)) && (!decision || card.querySelector(".decision").value === decision) && (!label || labels.includes(label)));
        }});
        const mode = document.getElementById("sortMode").value;
        cards().sort((a, b) => {{
          if (mode === "score-desc") return Number(b.dataset.score || 0) - Number(a.dataset.score || 0);
          if (mode === "source") return (a.dataset.source || "").localeCompare(b.dataset.source || "");
          return Number(a.querySelector(".order").value || 999999) - Number(b.querySelector(".order").value || 999999);
        }}).forEach((card) => document.getElementById("grid").appendChild(card));
        updateCounts();
      }});
    }}
    function clearFilters() {{
      document.getElementById("searchFilter").value = "";
      document.getElementById("decisionFilter").value = "";
      document.getElementById("labelFilter").value = "";
      applyFilters();
    }}
    function applyBulkDecision() {{
      const value = document.getElementById("bulkDecision").value;
      preserveScroll(() => {{
        visibleCards().forEach((card) => {{ card.querySelector(".decision").value = value; }});
        saveState();
        applyFilters();
      }});
    }}
    function downloadDecisions() {{
      const blob = new Blob([JSON.stringify(collectDecisions(), null, 2)], {{type: "application/json"}});
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "missed_review_decisions.json";
      link.click();
      URL.revokeObjectURL(link.href);
    }}
    async function copyDecisions() {{ await navigator.clipboard.writeText(JSON.stringify(collectDecisions(), null, 2)); }}
    cards().forEach((card) => card.querySelectorAll(".decision, .order, .note").forEach((control) => {{
      control.addEventListener("change", saveState);
      control.addEventListener("input", saveState);
    }}));
    ["searchFilter", "decisionFilter", "labelFilter", "sortMode"].forEach((id) => {{
      document.getElementById(id).addEventListener("input", applyFilters);
      document.getElementById(id).addEventListener("change", applyFilters);
    }});
    populateFilters();
    restoreState();
  </script>
</body>
</html>
"""
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(document)


def _missed_decision_options(selected: str) -> str:
    options = [
        ("select", "Select"),
        ("review", "Review"),
        ("broll", "B-roll"),
        ("reject", "Reject"),
        ("ignore", "Ignore"),
    ]
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in options
    )


def _sample_frame(source: str, timestamp: float, output: str, timeout: int = 180) -> None:
    if not has_command("ffmpeg"):
        raise RuntimeError("ffmpeg is required for AI frame sampling")
    run_command_check(
        [
            "ffmpeg",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            source,
            "-frames:v",
            "1",
            "-vf",
            "scale=336:-2",
            "-q:v",
            "3",
            output,
            "-y",
        ],
        timeout=timeout,
    )


def _input_files(input_path: str) -> list[str]:
    input_path = os.fspath(input_path)
    if os.path.isfile(input_path):
        return [input_path]
    return scan_video_files(input_path)


def _source_signature(
    source: str,
    profile: str,
    sample_interval: float,
    max_frames: int,
    min_score: float,
    model: str,
    pretrained: str,
) -> dict[str, Any]:
    try:
        stat = os.stat(os.fspath(source))
        file_sig = {"size": stat.st_size, "mtime": stat.st_mtime}
    except OSError:
        file_sig = {"missing": os.fspath(source)}
    file_sig.update(
        {
            "profile": profile,
            "sample_interval": float(sample_interval),
            "max_frames_per_file": int(max_frames),
            "min_score": float(min_score),
            "model": model,
            "pretrained": pretrained,
        }
    )
    return file_sig


def _source_summaries(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for source in sources:
        rows.append(
            {
                "source": source.get("source"),
                "frame_count": len(source.get("frames", [])),
                "labels": list(source.get("labels", [])),
                "top_score": source.get("top_score", 0.0),
            }
        )
    return rows


def _unavailable_payload(input_path: str, profile: AIProfile, error: str) -> dict[str, Any]:
    return {
        "schema_version": AI_FRAME_SCHEMA_VERSION,
        "artifact_kind": "ai_frame_scores",
        "generated": datetime.now().isoformat(),
        "input": os.fspath(input_path),
        "profile": profile.to_dict(),
        "provider": "openclip",
        "status": "unavailable",
        "error": error,
        "sources": [],
        "warnings": [error],
    }


def _clip_seconds(clip: dict[str, Any], formatted_key: str, seconds_key: str) -> float:
    if seconds_key in clip:
        return float(clip[seconds_key])
    return timecode_to_seconds(clip.get(formatted_key, 0))


def _read_json(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _read_optional_json(path: str) -> dict[str, Any]:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"
