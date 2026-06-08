"""Calibration and scoring evaluation for ratings artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import json
import os
from typing import Any

from .config import AnalysisConfig
from .models import CandidateClip, SignalReport
from .rating import generate_candidates
from .timecode import seconds_to_hhmmss, timecode_to_seconds


POSITIVE_RATINGS = {"select", "review", "broll"}
NEGATIVE_RATINGS = {"reject", "cut"}
IGNORE_RATINGS = {"ignore"}
SUPPORTED_RATINGS = POSITIVE_RATINGS | NEGATIVE_RATINGS | IGNORE_RATINGS
PREDICTED_POSITIVE_ACTIONS = {"select", "review", "broll"}
RECALL_AT = (5, 10, 25, 50)


@dataclass
class AnnotationClip:
    id: str
    source: str
    canonical_source: str
    start: float
    end: float
    rating: str
    tags: list[str]
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "canonical_source": self.canonical_source,
            "start": seconds_to_hhmmss(self.start),
            "end": seconds_to_hhmmss(self.end),
            "start_seconds": self.start,
            "end_seconds": self.end,
            "duration": self.duration,
            "rating": self.rating,
            "tags": self.tags,
            "notes": self.notes,
        }


@dataclass
class AnnotationSet:
    project: str
    source_root: str | None
    clips: list[AnnotationClip]


def init_annotation_file(output: str, project: str = "Videoedit Calibration", source_root: str = "footage/") -> str:
    payload = {
        "project": project,
        "source_root": source_root,
        "clips": [
            {
                "source": "race_day/interview.mp4",
                "start": "00:00:30",
                "end": "00:00:45",
                "rating": "select",
                "tags": ["quote", "team_tuesday"],
                "notes": "Strong intro soundbite",
            },
            {
                "source": "race_day/broll.mp4",
                "start": 72.0,
                "end": 85.0,
                "rating": "broll",
                "tags": ["motion_bank"],
                "notes": "Useful shop motion",
            },
        ],
    }
    _write_json(output, payload)
    return os.fspath(output)


def evaluate_ratings(
    ratings_json: str,
    annotations_json: str,
    output_dir: str,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ratings = _read_json(ratings_json)
    annotations = load_annotations(annotations_json, ratings)
    candidate_rows = candidates if candidates is not None else list(ratings.get("candidates", []))
    report = evaluate_candidate_set(ratings, annotations, candidate_rows)
    report["ratings"] = os.fspath(ratings_json)
    report["annotations"] = os.fspath(annotations_json)
    paths = write_calibration_outputs(report, output_dir)
    return {
        "report": paths["json"],
        "markdown": paths["markdown"],
        "missed": paths["missed"],
        "false_positives": paths["false_positives"],
        "metrics": report["metrics"],
    }


def tune_scoring(ratings_json: str, annotations_json: str, output_dir: str) -> dict[str, Any]:
    ratings = _read_json(ratings_json)
    annotations = load_annotations(annotations_json, ratings)
    os.makedirs(os.fspath(output_dir), exist_ok=True)

    baseline = evaluate_candidate_set(ratings, annotations, list(ratings.get("candidates", [])))
    baseline["ratings"] = os.fspath(ratings_json)
    baseline["annotations"] = os.fspath(annotations_json)
    report_paths = write_calibration_outputs(baseline, output_dir)

    candidates = []
    for index, config in enumerate(_config_sweep(ratings), 1):
        generated = generate_config_candidates(ratings, config)
        evaluation = evaluate_candidate_set(ratings, annotations, generated)
        metrics = evaluation["metrics"]
        candidates.append(
            {
                "rank": 0,
                "name": f"config_{index:03d}",
                "config": config.to_dict(),
                "metrics": metrics,
                "candidate_count": len(generated),
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["metrics"]["f1"],
            -item["metrics"]["recall"],
            -item["metrics"]["precision"],
            item["candidate_count"],
        )
    )
    for index, item in enumerate(candidates, 1):
        item["rank"] = index

    config_candidates_path = os.path.join(os.fspath(output_dir), "config_candidates.csv")
    proposed_config_path = os.path.join(os.fspath(output_dir), "proposed_config.json")
    _write_config_candidates_csv(candidates, config_candidates_path)
    if candidates:
        _write_json(proposed_config_path, candidates[0]["config"])
    else:
        _write_json(proposed_config_path, _base_config_from_ratings(ratings).to_dict())

    return {
        "report": report_paths["json"],
        "markdown": report_paths["markdown"],
        "missed": report_paths["missed"],
        "false_positives": report_paths["false_positives"],
        "config_candidates": config_candidates_path,
        "proposed_config": proposed_config_path,
        "best": candidates[0] if candidates else None,
        "metrics": baseline["metrics"],
    }


def load_annotations(path: str, ratings: dict[str, Any] | None = None) -> AnnotationSet:
    data = _read_json(path)
    source_index = _SourceIndex(ratings or {}, annotation_path=path, source_root=data.get("source_root"))
    clips = []
    for index, item in enumerate(data.get("clips", []), 1):
        rating = str(item.get("rating", "review")).strip().lower()
        if rating not in SUPPORTED_RATINGS:
            raise ValueError(f"unsupported annotation rating at clip {index}: {rating}")
        source = str(item.get("source", "")).strip()
        if not source:
            raise ValueError(f"annotation clip {index} is missing source")
        start = _seconds(item.get("start", 0))
        end = _seconds(item.get("end", 0))
        if end <= start:
            raise ValueError(f"annotation clip {index} end must be after start")
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        clips.append(
            AnnotationClip(
                id=str(item.get("id") or item.get("label") or f"annotation_{index:04d}"),
                source=source,
                canonical_source=source_index.resolve(source),
                start=start,
                end=end,
                rating=rating,
                tags=[str(tag) for tag in tags],
                notes=str(item.get("notes", "")),
            )
        )
    return AnnotationSet(
        project=str(data.get("project", "Videoedit Calibration")),
        source_root=data.get("source_root"),
        clips=clips,
    )


def evaluate_candidate_set(
    ratings: dict[str, Any],
    annotations: AnnotationSet,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    source_index = _SourceIndex(ratings)
    candidate_rows = [_candidate_info(candidate, index, source_index) for index, candidate in enumerate(candidates, 1)]
    positives = [clip for clip in annotations.clips if clip.rating in POSITIVE_RATINGS]
    negatives = [clip for clip in annotations.clips if clip.rating in NEGATIVE_RATINGS]
    ignored = [clip for clip in annotations.clips if clip.rating in IGNORE_RATINGS]
    predicted = [row for row in candidate_rows if row["action"] in PREDICTED_POSITIVE_ACTIONS]

    used_candidates: set[int] = set()
    matches = []
    missed = []
    for annotation in positives:
        match = _best_candidate(annotation, predicted, used_candidates)
        if match:
            used_candidates.add(match["index"])
            matches.append(_match_payload(annotation, match))
        else:
            missed.append(_miss_payload(annotation, _nearest_candidate(annotation, candidate_rows)))

    false_positives = []
    for candidate in predicted:
        if candidate["index"] in used_candidates:
            continue
        if _overlaps_any(candidate, ignored):
            continue
        false_positives.append(_false_positive_payload(candidate, _nearest_annotation(candidate, annotations.clips)))

    confusion = _confusion_matrix(candidate_rows, annotations.clips)
    metrics = _metrics(matches, missed, false_positives, positives, candidate_rows)

    return {
        "generated": datetime.now().isoformat(),
        "project": annotations.project,
        "source_root": annotations.source_root,
        "summary": {
            "annotations": len(annotations.clips),
            "positive_annotations": len(positives),
            "negative_annotations": len(negatives),
            "ignored_annotations": len(ignored),
            "candidates": len(candidate_rows),
            "predicted_positive_candidates": len(predicted),
        },
        "metrics": metrics,
        "matches": matches,
        "missed_moments": missed,
        "false_positives": false_positives,
        "score_action_confusion": confusion,
        "annotations": [clip.to_dict() for clip in annotations.clips],
    }


def generate_config_candidates(ratings: dict[str, Any], config: AnalysisConfig) -> list[dict[str, Any]]:
    signals = [SignalReport.from_dict(item) for item in ratings.get("signals", [])]
    generated = generate_candidates(signals, config)
    generated = sorted(generated, key=lambda item: (-item.score, item.source, item.start))[: config.max_candidates]
    reranked = [
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
        for index, clip in enumerate(generated, 1)
    ]
    return [clip.to_dict() for clip in reranked]


def write_calibration_outputs(report: dict[str, Any], output_dir: str) -> dict[str, str]:
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    paths = {
        "json": os.path.join(output_dir, "calibration_report.json"),
        "markdown": os.path.join(output_dir, "calibration_report.md"),
        "missed": os.path.join(output_dir, "missed_moments.csv"),
        "false_positives": os.path.join(output_dir, "false_positives.csv"),
    }
    _write_json(paths["json"], report)
    _write_markdown_report(report, paths["markdown"])
    _write_missed_csv(report.get("missed_moments", []), paths["missed"])
    _write_false_positive_csv(report.get("false_positives", []), paths["false_positives"])
    return paths


def _metrics(
    matches: list[dict[str, Any]],
    missed: list[dict[str, Any]],
    false_positives: list[dict[str, Any]],
    positives: list[AnnotationClip],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    true_positive_count = len(matches)
    false_positive_count = len(false_positives)
    positive_count = len(positives)
    precision = _safe_ratio(true_positive_count, true_positive_count + false_positive_count)
    recall = _safe_ratio(true_positive_count, positive_count)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    recall_at = {}
    for limit in RECALL_AT:
        top = [candidate for candidate in candidates[:limit] if candidate["action"] in PREDICTED_POSITIVE_ACTIONS]
        matched_annotations = set()
        for annotation in positives:
            if _best_candidate(annotation, top, set()):
                matched_annotations.add(annotation.id)
        recall_at[str(limit)] = round(_safe_ratio(len(matched_annotations), positive_count), 4)

    tags: dict[str, dict[str, int]] = {}
    matched_annotation_ids = {item["annotation"]["id"] for item in matches}
    for annotation in positives:
        for tag in annotation.tags or ["untagged"]:
            tags.setdefault(tag, {"total": 0, "matched": 0})
            tags[tag]["total"] += 1
            if annotation.id in matched_annotation_ids:
                tags[tag]["matched"] += 1
    recall_by_tag = {
        tag: {
            "total": row["total"],
            "matched": row["matched"],
            "recall": round(_safe_ratio(row["matched"], row["total"]), 4),
        }
        for tag, row in sorted(tags.items())
    }
    return {
        "true_positives": true_positive_count,
        "false_positives": false_positive_count,
        "missed": len(missed),
        "positive_annotations": positive_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "recall_at": recall_at,
        "recall_by_tag": recall_by_tag,
    }


def _config_sweep(ratings: dict[str, Any]) -> list[AnalysisConfig]:
    base = _base_config_from_ratings(ratings)
    weight_profiles = [
        ("base", dict(base.weights)),
        ("balanced", {"technical": 20, "visual": 30, "audio": 30, "transcript": 20}),
        ("audio", {"technical": 15, "visual": 25, "audio": 40, "transcript": 20}),
        ("visual", {"technical": 15, "visual": 35, "audio": 30, "transcript": 20}),
        ("transcript", {"technical": 15, "visual": 20, "audio": 25, "transcript": 40}),
    ]
    threshold_profiles = [
        ("base", base.min_select_score, base.min_review_score, base.min_broll_score),
        ("loose", 80, 62, 45),
        ("review", 85, 65, 50),
        ("strict", 90, 75, 60),
    ]
    window_profiles = [
        ("base", base.window_pre_roll, base.window_post_roll, base.merge_gap),
        ("short", 2.0, 6.0, 2.0),
        ("long", 4.0, 12.0, 6.0),
    ]
    audio_profiles = [
        ("base", base.audio_spike_percentile, base.audio_spike_floor_db),
        ("sensitive", 75.0, -40.0),
        ("strict", 90.0, -30.0),
    ]
    max_candidates = sorted({base.max_candidates, 50, 75, 100})

    configs: list[AnalysisConfig] = []
    seen: set[str] = set()
    for _weight_name, weights in weight_profiles:
        for _threshold_name, select_score, review_score, broll_score in threshold_profiles:
            for _window_name, pre_roll, post_roll, merge_gap in window_profiles:
                for _audio_name, spike_percentile, spike_floor in audio_profiles:
                    for max_candidate_count in max_candidates:
                        config = AnalysisConfig.from_mapping(base.to_dict())
                        config.weights = dict(weights)
                        config.min_select_score = int(select_score)
                        config.min_review_score = int(review_score)
                        config.min_broll_score = int(broll_score)
                        config.window_pre_roll = float(pre_roll)
                        config.window_post_roll = float(post_roll)
                        config.merge_gap = float(merge_gap)
                        config.audio_spike_percentile = float(spike_percentile)
                        config.audio_spike_floor_db = float(spike_floor)
                        config.max_candidates = int(max_candidate_count)
                        key = json.dumps(config.to_dict(), sort_keys=True)
                        if key not in seen:
                            configs.append(config)
                            seen.add(key)
    return configs


def _base_config_from_ratings(ratings: dict[str, Any]) -> AnalysisConfig:
    config = AnalysisConfig.from_mapping(ratings.get("config", {}))
    defaults = AnalysisConfig()
    weights = dict(defaults.weights)
    weights.update(config.weights or {})
    config.weights = weights
    return config


def _candidate_info(candidate: dict[str, Any], index: int, source_index: "_SourceIndex") -> dict[str, Any]:
    source = str(candidate.get("source", ""))
    return {
        "index": index,
        "id": str(candidate.get("id") or candidate.get("label") or f"candidate_{index:04d}"),
        "source": source,
        "canonical_source": source_index.resolve(source),
        "start": _clip_seconds(candidate, "start", "start_seconds"),
        "end": _clip_seconds(candidate, "end", "end_seconds"),
        "score": int(candidate.get("score", 0)),
        "action": str(candidate.get("action", "review")).lower(),
        "labels": list(candidate.get("labels", [])),
        "reasons": list(candidate.get("reasons", [])),
        "signals": dict(candidate.get("signals", {})),
    }


def _best_candidate(
    annotation: AnnotationClip,
    candidates: list[dict[str, Any]],
    used_candidates: set[int],
) -> dict[str, Any] | None:
    matches = [
        candidate
        for candidate in candidates
        if candidate["index"] not in used_candidates
        and candidate["canonical_source"] == annotation.canonical_source
        and _overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"]) > 0
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda candidate: (
            -_overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"]),
            -candidate["score"],
            candidate["index"],
        ),
    )[0]


def _nearest_candidate(annotation: AnnotationClip, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    same_source = [candidate for candidate in candidates if candidate["canonical_source"] == annotation.canonical_source]
    if not same_source:
        return None
    return sorted(
        same_source,
        key=lambda candidate: (
            _time_gap(annotation.start, annotation.end, candidate["start"], candidate["end"]),
            -candidate["score"],
            candidate["index"],
        ),
    )[0]


def _nearest_annotation(candidate: dict[str, Any], annotations: list[AnnotationClip]) -> AnnotationClip | None:
    same_source = [clip for clip in annotations if clip.canonical_source == candidate["canonical_source"]]
    if not same_source:
        return None
    return sorted(
        same_source,
        key=lambda clip: (
            _time_gap(clip.start, clip.end, candidate["start"], candidate["end"]),
            -_overlap_seconds(clip.start, clip.end, candidate["start"], candidate["end"]),
        ),
    )[0]


def _overlaps_any(candidate: dict[str, Any], annotations: list[AnnotationClip]) -> bool:
    return any(
        annotation.canonical_source == candidate["canonical_source"]
        and _overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"]) > 0
        for annotation in annotations
    )


def _confusion_matrix(candidates: list[dict[str, Any]], annotations: list[AnnotationClip]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        annotation = _nearest_overlapping_annotation(candidate, annotations)
        actual = annotation.rating if annotation else "unmatched"
        predicted = candidate["action"]
        matrix.setdefault(predicted, {})
        matrix[predicted][actual] = matrix[predicted].get(actual, 0) + 1
    return matrix


def _nearest_overlapping_annotation(candidate: dict[str, Any], annotations: list[AnnotationClip]) -> AnnotationClip | None:
    overlaps = [
        annotation
        for annotation in annotations
        if annotation.canonical_source == candidate["canonical_source"]
        and _overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"]) > 0
    ]
    if not overlaps:
        return None
    return sorted(
        overlaps,
        key=lambda annotation: -_overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"]),
    )[0]


def _match_payload(annotation: AnnotationClip, candidate: dict[str, Any]) -> dict[str, Any]:
    overlap = _overlap_seconds(annotation.start, annotation.end, candidate["start"], candidate["end"])
    return {
        "annotation": annotation.to_dict(),
        "candidate": _candidate_payload(candidate),
        "overlap_seconds": round(overlap, 3),
        "overlap_ratio": round(_safe_ratio(overlap, annotation.duration), 4),
    }


def _miss_payload(annotation: AnnotationClip, nearest: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "annotation": annotation.to_dict(),
        "nearest_candidate": _candidate_payload(nearest) if nearest else None,
        "nearest_gap_seconds": round(_time_gap(annotation.start, annotation.end, nearest["start"], nearest["end"]), 3)
        if nearest
        else None,
    }


def _false_positive_payload(candidate: dict[str, Any], nearest: AnnotationClip | None) -> dict[str, Any]:
    payload = {
        "candidate": _candidate_payload(candidate),
        "nearest_annotation": nearest.to_dict() if nearest else None,
        "nearest_gap_seconds": round(_time_gap(nearest.start, nearest.end, candidate["start"], candidate["end"]), 3)
        if nearest
        else None,
    }
    if nearest:
        payload["nearest_overlap_seconds"] = round(
            _overlap_seconds(nearest.start, nearest.end, candidate["start"], candidate["end"]),
            3,
        )
    return payload


def _candidate_payload(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "id": candidate["id"],
        "source": candidate["source"],
        "canonical_source": candidate["canonical_source"],
        "start": seconds_to_hhmmss(candidate["start"]),
        "end": seconds_to_hhmmss(candidate["end"]),
        "start_seconds": candidate["start"],
        "end_seconds": candidate["end"],
        "score": candidate["score"],
        "action": candidate["action"],
        "labels": candidate["labels"],
        "reasons": candidate["reasons"],
    }


def _write_markdown_report(report: dict[str, Any], output: str) -> None:
    metrics = report["metrics"]
    lines = [
        "# Calibration Report",
        "",
        f"**Generated:** {report['generated']}",
        f"**Project:** {report['project']}",
        "",
        "## Metrics",
        "",
        f"- Precision: {metrics['precision']}",
        f"- Recall: {metrics['recall']}",
        f"- F1: {metrics['f1']}",
        f"- True positives: {metrics['true_positives']}",
        f"- False positives: {metrics['false_positives']}",
        f"- Missed moments: {metrics['missed']}",
        "",
        "## Recall By Tag",
        "",
        "| Tag | Matched | Total | Recall |",
        "|-----|---------|-------|--------|",
    ]
    for tag, row in metrics.get("recall_by_tag", {}).items():
        lines.append(f"| {tag} | {row['matched']} | {row['total']} | {row['recall']} |")
    lines.extend(["", "## Missed Moments", ""])
    for item in report.get("missed_moments", [])[:50]:
        annotation = item["annotation"]
        lines.append(
            f"- `{annotation['id']}` {os.path.basename(annotation['source'])} "
            f"{annotation['start']} - {annotation['end']} ({annotation['rating']})"
        )
    lines.extend(["", "## False Positives", ""])
    for item in report.get("false_positives", [])[:50]:
        candidate = item["candidate"]
        lines.append(
            f"- `{candidate['id']}` score {candidate['score']} {os.path.basename(candidate['source'])} "
            f"{candidate['start']} - {candidate['end']}"
        )
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _write_missed_csv(rows: list[dict[str, Any]], output: str) -> None:
    fieldnames = [
        "id",
        "source",
        "start",
        "end",
        "rating",
        "tags",
        "notes",
        "nearest_candidate",
        "nearest_gap_seconds",
    ]
    with open(os.fspath(output), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            annotation = row["annotation"]
            nearest = row.get("nearest_candidate") or {}
            writer.writerow(
                {
                    "id": annotation["id"],
                    "source": annotation["source"],
                    "start": annotation["start"],
                    "end": annotation["end"],
                    "rating": annotation["rating"],
                    "tags": ", ".join(annotation.get("tags", [])),
                    "notes": annotation.get("notes", ""),
                    "nearest_candidate": nearest.get("id", ""),
                    "nearest_gap_seconds": row.get("nearest_gap_seconds", ""),
                }
            )


def _write_false_positive_csv(rows: list[dict[str, Any]], output: str) -> None:
    fieldnames = [
        "id",
        "source",
        "start",
        "end",
        "score",
        "action",
        "labels",
        "reasons",
        "nearest_annotation",
        "nearest_rating",
        "nearest_gap_seconds",
    ]
    with open(os.fspath(output), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            candidate = row["candidate"]
            nearest = row.get("nearest_annotation") or {}
            writer.writerow(
                {
                    "id": candidate["id"],
                    "source": candidate["source"],
                    "start": candidate["start"],
                    "end": candidate["end"],
                    "score": candidate["score"],
                    "action": candidate["action"],
                    "labels": ", ".join(candidate.get("labels", [])),
                    "reasons": " | ".join(candidate.get("reasons", [])),
                    "nearest_annotation": nearest.get("id", ""),
                    "nearest_rating": nearest.get("rating", ""),
                    "nearest_gap_seconds": row.get("nearest_gap_seconds", ""),
                }
            )


def _write_config_candidates_csv(rows: list[dict[str, Any]], output: str) -> None:
    fieldnames = [
        "rank",
        "name",
        "f1",
        "precision",
        "recall",
        "true_positives",
        "false_positives",
        "missed",
        "candidate_count",
        "min_select_score",
        "min_review_score",
        "min_broll_score",
        "max_candidates",
        "weights",
        "config_json",
    ]
    with open(os.fspath(output), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            config = row["config"]
            metrics = row["metrics"]
            writer.writerow(
                {
                    "rank": row["rank"],
                    "name": row["name"],
                    "f1": metrics["f1"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "true_positives": metrics["true_positives"],
                    "false_positives": metrics["false_positives"],
                    "missed": metrics["missed"],
                    "candidate_count": row["candidate_count"],
                    "min_select_score": config["min_select_score"],
                    "min_review_score": config["min_review_score"],
                    "min_broll_score": config["min_broll_score"],
                    "max_candidates": config["max_candidates"],
                    "weights": json.dumps(config["weights"], sort_keys=True),
                    "config_json": json.dumps(config, sort_keys=True),
                }
            )


def _clip_seconds(clip: dict[str, Any], formatted_key: str, seconds_key: str) -> float:
    if seconds_key in clip:
        return float(clip[seconds_key])
    return _seconds(clip.get(formatted_key, 0))


def _seconds(value: Any) -> float:
    return timecode_to_seconds(value)


def _overlap_seconds(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _time_gap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    if _overlap_seconds(start_a, end_a, start_b, end_b) > 0:
        return 0.0
    if end_a <= start_b:
        return start_b - end_a
    return start_a - end_b


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else float(numerator) / float(denominator)


def _read_json(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")


class _SourceIndex:
    def __init__(
        self,
        ratings: dict[str, Any],
        annotation_path: str | None = None,
        source_root: str | None = None,
    ) -> None:
        self.ratings_root = ratings.get("root")
        self.annotation_dir = os.path.dirname(os.path.abspath(os.fspath(annotation_path))) if annotation_path else None
        self.source_root = source_root
        self.by_key: dict[str, str] = {}
        self.by_basename: dict[str, set[str]] = {}
        for source in self._rating_sources(ratings):
            self.add(source)

    def add(self, source: str) -> None:
        if not source:
            return
        canonical = os.fspath(source)
        for key in self._source_keys(source):
            self.by_key[key] = canonical
        basename = os.path.basename(_path_key(source))
        self.by_basename.setdefault(basename, set()).add(canonical)

    def resolve(self, source: str) -> str:
        for candidate in self._annotation_candidates(source):
            for key in self._source_keys(candidate):
                if key in self.by_key:
                    return self.by_key[key]
        basename = os.path.basename(_path_key(source))
        basename_matches = self.by_basename.get(basename, set())
        if len(basename_matches) == 1:
            return next(iter(basename_matches))
        return os.fspath(source)

    def _rating_sources(self, ratings: dict[str, Any]) -> list[str]:
        sources = []
        for candidate in ratings.get("candidates", []):
            if candidate.get("source"):
                sources.append(os.fspath(candidate["source"]))
        for signal in ratings.get("signals", []):
            asset = signal.get("asset", {})
            if asset.get("filepath"):
                sources.append(os.fspath(asset["filepath"]))
        return sorted(set(sources))

    def _annotation_candidates(self, source: str) -> list[str]:
        candidates = [os.fspath(source)]
        for root in [self.source_root, self.ratings_root]:
            if root:
                candidates.append(os.path.join(os.fspath(root), os.fspath(source)))
        if self.annotation_dir and self.source_root:
            candidates.append(os.path.join(self.annotation_dir, os.fspath(self.source_root), os.fspath(source)))
        return candidates

    def _source_keys(self, source: str) -> set[str]:
        keys = {_path_key(source)}
        if os.path.isabs(os.fspath(source)):
            keys.add(_path_key(os.path.abspath(os.fspath(source))))
        else:
            keys.add(_path_key(os.path.abspath(os.fspath(source))))
            if self.ratings_root:
                keys.add(_path_key(os.path.join(os.fspath(self.ratings_root), os.fspath(source))))
        if self.ratings_root and os.path.isabs(os.fspath(source)):
            try:
                keys.add(_path_key(os.path.relpath(os.fspath(source), os.fspath(self.ratings_root))))
            except ValueError:
                pass
        return keys


def _path_key(value: str) -> str:
    normalized = os.path.normpath(os.fspath(value).replace("\\", os.sep))
    return os.path.normcase(normalized)
