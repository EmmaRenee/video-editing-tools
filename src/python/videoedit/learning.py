"""Review-decision datasets and small local learned scoring."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
import re
from typing import Any

from .models import CandidateClip


REVIEW_DATASET_SCHEMA_VERSION = "videoedit.review_dataset.v1"
LEARNED_SCORER_SCHEMA_VERSION = "videoedit.learned_scorer.v1"
POSITIVE_DECISIONS = {"approve", "approved", "promote", "select", "review", "broll", "yes", "y"}
NEGATIVE_DECISIONS = {"reject", "rejected", "cut", "demote", "skip", "no", "n"}
IGNORE_DECISIONS = {"ignore"}


def build_review_dataset(
    inputs: list[str],
    output: str,
    include_source_paths: bool = False,
    project_profile: str | None = None,
) -> dict[str, Any]:
    """Build portable JSONL training records from review decisions."""

    output = os.fspath(output)
    records = []
    for decision_path in inputs:
        decision_path = os.fspath(decision_path)
        decisions = _read_json(decision_path)
        ratings_path = _resolve_ratings_path(decisions, decision_path)
        ratings = _read_json(ratings_path)
        candidates = _candidate_map(ratings)
        project = _project_payload(decisions, ratings, decision_path, project_profile)
        for decision in _decision_rows(decisions):
            clip_id = str(decision.get("id") or "").strip()
            candidate = candidates.get(clip_id)
            if not candidate:
                continue
            label = _label_payload(decision, candidate)
            if label.get("target") is None:
                continue
            records.append(
                _dataset_record(
                    candidate,
                    decision,
                    label,
                    project,
                    ratings_path,
                    decision_path,
                    include_source_paths=include_source_paths,
                )
            )
    _write_jsonl(output, records)
    return {"output": output, "records": len(records), "schema_version": REVIEW_DATASET_SCHEMA_VERSION}


def train_local_scorer(dataset_jsonl: str, output: str) -> dict[str, Any]:
    """Train a tiny inspectable linear scorer from review dataset JSONL."""

    records = [record for record in _read_jsonl(dataset_jsonl) if isinstance(record.get("label"), dict)]
    train_rows = [record for record in records if record.get("label", {}).get("target") in {0, 1}]
    if not train_rows:
        raise ValueError("training dataset has no labeled select/reject records")
    feature_names = sorted({name for record in train_rows for name in record.get("features", {}) if _is_number(record["features"].get(name))})
    positives = [record for record in train_rows if int(record["label"]["target"]) == 1]
    negatives = [record for record in train_rows if int(record["label"]["target"]) == 0]
    stats = {}
    weights = {}
    for name in feature_names:
        pos_mean = _mean([float(record["features"].get(name, 0.0) or 0.0) for record in positives])
        neg_mean = _mean([float(record["features"].get(name, 0.0) or 0.0) for record in negatives])
        all_values = [float(record["features"].get(name, 0.0) or 0.0) for record in train_rows]
        feature_min = min(all_values) if all_values else 0.0
        feature_max = max(all_values) if all_values else 0.0
        scale = max(1.0, feature_max - feature_min)
        weight = round((pos_mean - neg_mean) / scale, 6)
        if weight:
            weights[name] = weight
        stats[name] = {
            "positive_mean": round(pos_mean, 6),
            "negative_mean": round(neg_mean, 6),
            "min": round(feature_min, 6),
            "max": round(feature_max, 6),
            "scale": round(scale, 6),
        }
    pos_raw = _mean([_raw_score(record.get("features", {}), weights) for record in positives])
    neg_raw = _mean([_raw_score(record.get("features", {}), weights) for record in negatives])
    threshold = round((pos_raw + neg_raw) / 2.0, 6)
    model = {
        "schema_version": LEARNED_SCORER_SCHEMA_VERSION,
        "generated": datetime.now().isoformat(),
        "training": {
            "dataset": os.fspath(dataset_jsonl),
            "records": len(train_rows),
            "positives": len(positives),
            "negatives": len(negatives),
        },
        "model_type": "linear_feature_delta",
        "feature_stats": stats,
        "weights": weights,
        "intercept": 0.0,
        "threshold": threshold,
        "positive_actions": sorted(POSITIVE_DECISIONS),
        "negative_actions": sorted(NEGATIVE_DECISIONS),
        "training_metrics": _training_metrics(train_rows, weights, threshold),
    }
    _write_json(output, model)
    return {"output": os.fspath(output), "records": len(train_rows), "features": len(weights), "metrics": model["training_metrics"]}


def load_learned_scorer(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    model = _read_json(path)
    if model.get("schema_version") != LEARNED_SCORER_SCHEMA_VERSION:
        raise ValueError(f"unsupported learned scorer schema: {model.get('schema_version')}")
    return model


def score_candidate_with_model(candidate: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    features = candidate_features(candidate)
    weights = {str(key): float(value) for key, value in model.get("weights", {}).items() if _is_number(value)}
    raw = float(model.get("intercept", 0.0) or 0.0) + _raw_score(features, weights)
    threshold = float(model.get("threshold", 0.0) or 0.0)
    probability = _sigmoid(raw - threshold)
    learned_score = round(probability * 100.0, 2)
    row = dict(candidate)
    signals = dict(row.get("signals", {}))
    signals["learned_score"] = learned_score
    signals["learned_raw_score"] = round(raw, 6)
    row["signals"] = signals
    labels = list(row.get("labels", []))
    labels.append("learned_positive" if learned_score >= 50.0 else "learned_negative")
    row["labels"] = sorted(set(labels))
    reasons = list(row.get("reasons", []))
    reasons.append(f"learned scorer score {learned_score}")
    row["reasons"] = reasons
    return row


def apply_learned_scorer_to_candidates(
    candidates: list[CandidateClip],
    model: dict[str, Any],
    config: Any,
) -> list[CandidateClip]:
    rows = []
    for clip in candidates:
        row = score_candidate_with_model(clip.to_dict(), model)
        learned_score = float(row.get("signals", {}).get("learned_score", 0.0) or 0.0)
        blended_score = int(round((int(clip.score) + learned_score) / 2.0))
        row["score"] = max(0, min(100, blended_score))
        row["action"] = _action_for_score(row["score"], config)
        rows.append(CandidateClip.from_dict(row))
    return rows


def candidate_features(candidate: dict[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {
        "deterministic_score": float(candidate.get("score", 0.0) or 0.0),
        "duration_seconds": float(candidate.get("duration", _duration(candidate)) or 0.0),
    }
    for key, value in dict(candidate.get("signals", {})).items():
        if _is_number(value):
            features[_safe_feature_name(key)] = float(value)
    for label in candidate.get("labels", []) or []:
        features[f"label_{_safe_feature_name(label)}"] = 1.0
    for explanation in candidate.get("ai_explanations", []) or []:
        if _is_number(explanation.get("score")):
            features["ai_clip_judge_score"] = max(features.get("ai_clip_judge_score", 0.0), float(explanation["score"]))
        action = str(explanation.get("suggested_action") or "").strip()
        if action:
            features[f"ai_suggested_{_safe_feature_name(action)}"] = 1.0
        for label in explanation.get("labels", []) or []:
            features[f"ai_label_{_safe_feature_name(label)}"] = 1.0
    return {key: round(value, 6) for key, value in sorted(features.items())}


def _dataset_record(
    candidate: dict[str, Any],
    decision: dict[str, Any],
    label: dict[str, Any],
    project: dict[str, Any],
    ratings_path: str,
    decisions_path: str,
    include_source_paths: bool,
) -> dict[str, Any]:
    source = os.fspath(decision.get("source") or candidate.get("source") or "")
    clip = {
        "id": candidate.get("id") or decision.get("id"),
        "source_id": hashlib.sha1(source.encode("utf-8")).hexdigest()[:16] if source else None,
        "source_name": os.path.basename(source) if source else None,
        "start": candidate.get("start"),
        "end": candidate.get("end"),
        "start_seconds": candidate.get("start_seconds"),
        "end_seconds": candidate.get("end_seconds"),
    }
    if include_source_paths:
        clip["source_path"] = source
    return {
        "schema_version": REVIEW_DATASET_SCHEMA_VERSION,
        "generated": datetime.now().isoformat(),
        "project": project,
        "artifacts": {
            "ratings": os.path.basename(os.fspath(ratings_path)),
            "review_decisions": os.path.basename(os.fspath(decisions_path)),
        },
        "clip": clip,
        "features": candidate_features(candidate),
        "label": label,
        "decision": {
            "decision": decision.get("decision") or decision.get("rating"),
            "order": decision.get("order"),
            "note": decision.get("note") or decision.get("notes") or "",
        },
        "metadata": {
            "action": candidate.get("action"),
            "labels": list(candidate.get("labels", [])),
        },
    }


def _label_payload(decision: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    value = str(decision.get("decision") or decision.get("rating") or candidate.get("action") or "").strip().lower()
    if value in POSITIVE_DECISIONS:
        return {"rating": value, "target": 1}
    if value in NEGATIVE_DECISIONS:
        return {"rating": value, "target": 0}
    if value in IGNORE_DECISIONS:
        return {"rating": value, "target": None}
    raise ValueError(f"unsupported review decision for dataset: {value}")


def _project_payload(
    decisions: dict[str, Any],
    ratings: dict[str, Any],
    decision_path: str,
    project_profile: str | None,
) -> dict[str, Any]:
    name = str(decisions.get("project") or ratings.get("project") or os.path.basename(os.path.dirname(decision_path)) or "videoedit_project")
    profile = project_profile or decisions.get("project_profile") or ratings.get("project_profile") or ratings.get("config", {}).get("profile") or "default"
    return {
        "name": name,
        "id": _safe_feature_name(name),
        "profile": str(profile),
    }


def _resolve_ratings_path(decisions: dict[str, Any], decision_path: str) -> str:
    value = decisions.get("ratings")
    if not value:
        value = os.path.join(os.path.dirname(os.fspath(decision_path)), "..", "ratings.json")
    value = os.fspath(value)
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(os.path.dirname(os.fspath(decision_path)), value))


def _decision_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = data.get("decisions", data)
    if isinstance(decisions, dict):
        return [
            {"id": str(key), **(value if isinstance(value, dict) else {"decision": value})}
            for key, value in decisions.items()
        ]
    if isinstance(decisions, list):
        return [dict(item) for item in decisions if isinstance(item, dict)]
    raise ValueError("review decisions must be a list or mapping")


def _candidate_map(ratings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for candidate in ratings.get("candidates", []):
        clip_id = candidate.get("id") or candidate.get("label")
        if clip_id:
            rows[str(clip_id)] = dict(candidate)
    return rows


def _training_metrics(records: list[dict[str, Any]], weights: dict[str, float], threshold: float) -> dict[str, Any]:
    correct = 0
    for record in records:
        raw = _raw_score(record.get("features", {}), weights)
        predicted = 1 if raw >= threshold else 0
        if predicted == int(record["label"]["target"]):
            correct += 1
    return {
        "accuracy": round(correct / max(1, len(records)), 4),
        "records": len(records),
    }


def _raw_score(features: dict[str, Any], weights: dict[str, float]) -> float:
    return sum(float(features.get(name, 0.0) or 0.0) * float(weight) for name, weight in weights.items())


def _sigmoid(value: float) -> float:
    if value >= 50:
        return 1.0
    if value <= -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _duration(candidate: dict[str, Any]) -> float:
    if candidate.get("duration") is not None:
        return float(candidate.get("duration") or 0.0)
    start = float(candidate.get("start_seconds", 0.0) or 0.0)
    end = float(candidate.get("end_seconds", start) or start)
    return max(0.0, end - start)


def _action_for_score(score: int, config: Any) -> str:
    if score >= int(getattr(config, "min_select_score", 85)):
        return "select"
    if score >= int(getattr(config, "min_review_score", 70)):
        return "review"
    if score >= int(getattr(config, "min_broll_score", 55)):
        return "broll"
    return "cut"


def _safe_feature_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value).strip().lower()).strip("_") or "value"


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _read_json(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
