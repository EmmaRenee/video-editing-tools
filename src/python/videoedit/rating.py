"""Footage scoring and clip candidate generation."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Any

from .config import AnalysisConfig
from .ffmpeg import analyze_audio_levels, detect_scene_changes, detect_silence, probe_media, scan_video_files
from .inventory import write_inventory_outputs
from .models import AudioLevel, CandidateClip, MediaAsset, RatingReport, SignalReport
from .reports import write_candidate_csv, write_rating_json, write_review_html, write_review_markdown, write_selection_sets
from .timecode import clamp_window
from .transcript import find_transcript_hits


def run_rating(
    footage_dir: str,
    output_dir: str,
    config: AnalysisConfig | None = None,
) -> RatingReport:
    config = config or AnalysisConfig()
    footage_dir = os.fspath(footage_dir)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    cache = _load_cache(output_dir) if config.cache else {}
    cache_changed = False
    signals: list[SignalReport] = []

    for path in scan_video_files(footage_dir):
        key = os.path.abspath(path)
        signature = _file_signature(path, config)
        cached = cache.get(key)
        if cached and cached.get("signature") == signature:
            signals.append(SignalReport.from_dict(cached["report"]))
            continue
        report = analyze_file(path, config)
        signals.append(report)
        if config.cache:
            cache[key] = {"signature": signature, "report": report.to_dict()}
            cache_changed = True

    if config.cache and cache_changed:
        _write_cache(output_dir, cache)

    candidates = generate_candidates(signals, config)
    candidates = sorted(candidates, key=lambda item: (-item.score, item.source, item.start))[
        : config.max_candidates
    ]
    candidates = [
        CandidateClip(
            id=f"clip_{index:04d}",
            source=clip.source,
            start=clip.start,
            end=clip.end,
            score=clip.score,
            action=clip.action,
            labels=clip.labels,
            reasons=clip.reasons,
            signals=clip.signals,
        )
        for index, clip in enumerate(candidates, 1)
    ]

    inventory = [report.asset for report in signals]
    summary = {
        "files": len(inventory),
        "total_duration": round(sum(item.duration for item in inventory), 3),
        "candidates": len(candidates),
        "select": sum(1 for item in candidates if item.action == "select"),
        "review": sum(1 for item in candidates if item.action == "review"),
        "broll": sum(1 for item in candidates if item.action == "broll"),
        "cut": sum(1 for item in candidates if item.action == "cut"),
    }
    report = RatingReport(
        generated=datetime.now().isoformat(),
        root=footage_dir,
        config=config.to_dict(),
        inventory=inventory,
        signals=signals,
        candidates=candidates,
        summary=summary,
    )

    write_inventory_outputs(inventory, os.path.join(output_dir, "inventory"))
    write_rating_json(report, os.path.join(output_dir, "ratings.json"))
    write_candidate_csv(candidates, os.path.join(output_dir, "candidates.csv"))
    write_review_markdown(report, os.path.join(output_dir, "review.md"))
    write_review_html(report, os.path.join(output_dir, "review.html"))
    write_selection_sets(candidates, os.path.join(output_dir, "selections"))
    return report


def analyze_file(path: str, config: AnalysisConfig) -> SignalReport:
    asset = probe_media(path, timeout=min(config.command_timeout, 60))
    warnings: list[str] = []
    reasons: list[str] = []
    scene_changes: list[float] = []
    silence_intervals = []
    audio_levels: list[AudioLevel] = []
    transcript_hits = []

    if asset.status != "ok":
        warnings.append(asset.error or "metadata probe failed")
    else:
        scene_changes, warning = detect_scene_changes(
            path, threshold=config.scene_threshold, timeout=config.command_timeout
        )
        if warning:
            warnings.append(warning)
        if asset.has_audio:
            silence_intervals, warning = detect_silence(
                path,
                threshold_db=config.silence_threshold_db,
                min_duration=config.min_silence_duration,
                duration=asset.duration,
                timeout=config.command_timeout,
            )
            if warning:
                warnings.append(warning)
            audio_levels, warning = analyze_audio_levels(path, timeout=config.command_timeout)
            if warning:
                warnings.append(warning)
        elif asset.status == "ok":
            warnings.append("no audio stream")

        if config.transcript_mode != "off":
            transcript_hits, transcript_path = find_transcript_hits(
                path,
                duration=asset.duration,
                keywords=config.keywords,
                transcript_dir=config.transcript_dir,
            )
            if transcript_path:
                reasons.append(f"transcript matched: {transcript_path}")
            elif config.transcript_mode == "required":
                warnings.append("transcript required but not found")

    scores = score_signal(asset, scene_changes, silence_intervals, audio_levels, transcript_hits, config)
    reasons.extend(_file_reasons(scores, scene_changes, silence_intervals, audio_levels, transcript_hits))
    return SignalReport(
        asset=asset,
        scene_changes=scene_changes,
        silence_intervals=silence_intervals,
        audio_levels=audio_levels,
        transcript_hits=transcript_hits,
        scores=scores,
        reasons=reasons,
        warnings=warnings,
    )


def score_signal(
    asset: MediaAsset,
    scene_changes: list[float],
    silence_intervals: list[Any],
    audio_levels: list[AudioLevel],
    transcript_hits: list[Any],
    config: AnalysisConfig,
) -> dict[str, float]:
    technical = _technical_score(asset, config.weights["technical"])
    duration_minutes = max(asset.duration / 60.0, 0.1)
    scene_density = len(scene_changes) / duration_minutes
    visual = min(config.weights["visual"], scene_density * 5.0)

    silent_duration = sum(item.duration for item in silence_intervals)
    non_silent_ratio = 1.0
    if asset.duration:
        non_silent_ratio = max(0.0, 1.0 - min(1.0, silent_duration / asset.duration))
    finite_levels = [level.rms_db for level in audio_levels if math.isfinite(level.rms_db)]
    spike_count = len(_audio_spikes(audio_levels, config))
    audio = min(
        config.weights["audio"],
        non_silent_ratio * 15.0 + min(20.0, spike_count * 4.0),
    )
    if not asset.has_audio:
        audio = 0.0

    transcript = min(config.weights["transcript"], len(transcript_hits) * 8.0)
    total = min(100.0, technical + visual + audio + transcript)
    peak_rms = max(finite_levels) if finite_levels else None
    return {
        "technical_score": round(technical, 2),
        "visual_activity_score": round(visual, 2),
        "audio_interest_score": round(audio, 2),
        "transcript_score": round(transcript, 2),
        "total_score": round(total, 2),
        "scene_changes_per_minute": round(scene_density, 2),
        "non_silent_ratio": round(non_silent_ratio, 3),
        "audio_spikes": spike_count,
        "peak_rms_db": round(peak_rms, 2) if peak_rms is not None else None,
    }


def generate_candidates(signals: list[SignalReport], config: AnalysisConfig) -> list[CandidateClip]:
    candidates: list[CandidateClip] = []
    for report in signals:
        if report.asset.status != "ok" or report.asset.duration <= 0:
            continue
        windows = _seed_windows(report, config)
        if not windows:
            windows = [
                {
                    "start": 0.0,
                    "end": min(report.asset.duration, 12.0),
                    "labels": {"low_signal"},
                }
            ]
        merged = _merge_windows(windows, gap=config.merge_gap, duration=report.asset.duration)
        for window in merged:
            start, end = clamp_window(window["start"], window["end"], report.asset.duration)
            if end - start < 1.0:
                continue
            score, labels, reasons, local_scores = _score_window(report, start, end, window["labels"], config)
            action = _action_for_score(score, config)
            candidates.append(
                CandidateClip(
                    id="clip_pending",
                    source=report.asset.filepath,
                    start=start,
                    end=end,
                    score=score,
                    action=action,
                    labels=sorted(labels),
                    reasons=reasons,
                    signals=local_scores,
                )
            )
    return candidates


def _seed_windows(report: SignalReport, config: AnalysisConfig) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for timestamp in report.scene_changes:
        windows.append(_window(timestamp, "scene_change", config))
    for level in _audio_spikes(report.audio_levels, config):
        windows.append(_window(level.time, "audio_spike", config))
    for hit in report.transcript_hits:
        start = max(0.0, hit.start - config.window_pre_roll)
        end = hit.end + config.window_post_roll
        windows.append({"start": start, "end": end, "labels": {"transcript_hit"}})
    return windows


def _window(timestamp: float, label: str, config: AnalysisConfig) -> dict[str, Any]:
    return {
        "start": timestamp - config.window_pre_roll,
        "end": timestamp + config.window_post_roll,
        "labels": {label},
    }


def _merge_windows(windows: list[dict[str, Any]], gap: float, duration: float) -> list[dict[str, Any]]:
    if not windows:
        return []
    normalized = []
    for item in windows:
        start, end = clamp_window(item["start"], item["end"], duration)
        normalized.append({"start": start, "end": end, "labels": set(item.get("labels", set()))})
    normalized.sort(key=lambda item: item["start"])
    merged = [normalized[0]]
    for item in normalized[1:]:
        current = merged[-1]
        if item["start"] <= current["end"] + gap:
            current["end"] = max(current["end"], item["end"])
            current["labels"].update(item["labels"])
        else:
            merged.append(item)
    return merged


def _score_window(
    report: SignalReport,
    start: float,
    end: float,
    seed_labels: set[str],
    config: AnalysisConfig,
) -> tuple[int, set[str], list[str], dict[str, float | int | None]]:
    labels = set(seed_labels)
    reasons: list[str] = []
    technical = report.scores.get("technical_score", 0.0)

    scene_count = sum(1 for value in report.scene_changes if start <= value <= end)
    visual = min(config.weights["visual"], scene_count * 8.0)
    if scene_count:
        labels.add("scene_cluster" if scene_count > 1 else "scene_change")
        reasons.append(f"{scene_count} scene change{'s' if scene_count != 1 else ''} in window")

    levels = [level for level in report.audio_levels if start <= level.time <= end]
    finite_levels = [level.rms_db for level in levels if math.isfinite(level.rms_db)]
    peak = max(finite_levels) if finite_levels else None
    audio = 0.0
    if peak is not None:
        if peak >= -18:
            audio = 30.0
        elif peak >= -25:
            audio = 22.0
        elif peak >= -35:
            audio = 14.0
        else:
            audio = 6.0
        labels.add("audio_spike" if peak >= config.audio_spike_floor_db else "audio_present")
        reasons.append(f"audio peak {peak:.1f} dB RMS")

    silence_overlap = _silence_overlap(report, start, end)
    silence_ratio = silence_overlap / max(0.1, end - start)
    if silence_ratio > 0.6:
        audio = max(0.0, audio - 10.0)
        labels.add("mostly_silent")
        reasons.append("mostly silent window")

    hits = [hit for hit in report.transcript_hits if start <= hit.start <= end or start <= hit.end <= end]
    transcript = min(config.weights["transcript"], len(hits) * 10.0)
    if hits:
        labels.add("transcript_hit")
        words = sorted({word for hit in hits for word in hit.keywords})
        reasons.append(f"transcript keywords: {', '.join(words[:6])}")

    if "low_signal" in labels:
        reasons.append("fallback candidate; no strong highlight signal found")

    score = int(round(min(100.0, technical + visual + audio + transcript)))
    return (
        score,
        labels,
        reasons,
        {
            "technical_score": round(technical, 2),
            "visual_activity_score": round(visual, 2),
            "audio_interest_score": round(audio, 2),
            "transcript_score": round(transcript, 2),
            "scene_changes": scene_count,
            "peak_rms_db": round(peak, 2) if peak is not None else None,
            "silence_ratio": round(silence_ratio, 3),
        },
    )


def _technical_score(asset: MediaAsset, max_score: int) -> float:
    if asset.status != "ok":
        return 0.0
    score = 5.0
    if asset.width and asset.height:
        pixels = asset.width * asset.height
        if pixels >= 3840 * 2160:
            score += 6.0
        elif pixels >= 1920 * 1080:
            score += 5.0
        elif pixels >= 1280 * 720:
            score += 3.0
        else:
            score += 1.0
    if asset.fps:
        if asset.fps >= 59:
            score += 4.0
        elif asset.fps >= 29:
            score += 3.0
        else:
            score += 1.0
    if 3 <= asset.duration <= 3600:
        score += 4.0
    elif asset.duration > 0:
        score += 2.0
    if asset.codec:
        score += 1.0
    return min(float(max_score), score)


def _audio_spikes(levels: list[AudioLevel], config: AnalysisConfig) -> list[AudioLevel]:
    finite = [level for level in levels if math.isfinite(level.rms_db)]
    if not finite:
        return []
    values = sorted(level.rms_db for level in finite)
    index = int((len(values) - 1) * (config.audio_spike_percentile / 100.0))
    threshold = max(config.audio_spike_floor_db, values[index])
    return [level for level in finite if level.rms_db >= threshold]


def _silence_overlap(report: SignalReport, start: float, end: float) -> float:
    total = 0.0
    for interval in report.silence_intervals:
        overlap_start = max(start, interval.start)
        overlap_end = min(end, interval.end)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return total


def _action_for_score(score: int, config: AnalysisConfig) -> str:
    if score >= config.min_select_score:
        return "select"
    if score >= config.min_review_score:
        return "review"
    if score >= config.min_broll_score:
        return "broll"
    return "cut"


def _file_reasons(
    scores: dict[str, float],
    scenes: list[float],
    silences: list[Any],
    audio_levels: list[AudioLevel],
    transcript_hits: list[Any],
) -> list[str]:
    reasons = []
    if scenes:
        reasons.append(f"{len(scenes)} scene changes detected")
    if silences:
        reasons.append(f"{len(silences)} silence intervals detected")
    if scores.get("audio_spikes"):
        reasons.append(f"{scores['audio_spikes']} audio spikes detected")
    if transcript_hits:
        reasons.append(f"{len(transcript_hits)} transcript highlight hits")
    if not reasons:
        reasons.append("no strong highlight signals detected")
    return reasons


def _file_signature(path: str, config: AnalysisConfig) -> dict[str, Any]:
    stat = os.stat(os.fspath(path))
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "scene_threshold": config.scene_threshold,
        "silence_threshold_db": config.silence_threshold_db,
        "min_silence_duration": config.min_silence_duration,
        "transcript_mode": config.transcript_mode,
        "keywords": config.keywords,
    }


def _cache_path(output_dir: str) -> str:
    return os.path.join(os.fspath(output_dir), ".cache", "analysis-cache.json")


def _load_cache(output_dir: str) -> dict[str, Any]:
    path = _cache_path(output_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.loads(handle.read())
    except json.JSONDecodeError:
        return {}


def _write_cache(output_dir: str, cache: dict[str, Any]) -> None:
    path = _cache_path(output_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(cache, indent=2))
