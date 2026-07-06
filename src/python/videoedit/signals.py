"""Shared loaders for optional signal artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any

from .models import ObjectHit
from .timecode import timecode_to_seconds


ARTIFACT_KEYS = {
    "visual_objects",
    "ocr_signage",
    "face_person",
    "motorsports_events",
    "topic_clusters",
    "ai_frame_scores",
}

SIGNAL_SCHEMA_VERSION = "videoedit.signal.v1"


@dataclass
class SignalArtifactBundle:
    object_hits: dict[str, list[ObjectHit]] = field(default_factory=dict)
    advanced_hits: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def objects_for(self, source: str) -> list[ObjectHit]:
        return list(_lookup(self.object_hits, source))

    def advanced_for(self, source: str) -> list[dict[str, Any]]:
        return [dict(item) for item in _lookup(self.advanced_hits, source)]


class SourceIndex:
    def __init__(self) -> None:
        self.by_key: dict[str, str] = {}
        self.by_basename: dict[str, set[str]] = {}

    def add(self, source: str) -> str:
        canonical = os.fspath(source)
        for key in _source_keys(canonical):
            self.by_key[key] = canonical
        basename = os.path.basename(_path_key(canonical))
        self.by_basename.setdefault(basename, set()).add(canonical)
        return canonical

    def resolve(self, source: str) -> str:
        for key in _source_keys(source):
            if key in self.by_key:
                return self.by_key[key]
        basename = os.path.basename(_path_key(source))
        matches = self.by_basename.get(basename, set())
        if len(matches) == 1:
            return next(iter(matches))
        return os.fspath(source)


def load_signal_artifacts(config: Any) -> SignalArtifactBundle:
    paths = signal_artifact_paths(config)
    index = SourceIndex()
    raw_objects: dict[str, list[ObjectHit]] = {}
    raw_advanced: dict[str, list[dict[str, Any]]] = {}

    for source, hits in _load_visual_objects(paths.get("visual_objects")).items():
        canonical = index.add(source)
        raw_objects.setdefault(canonical, []).extend(hits)
    for key, path in paths.items():
        if key == "visual_objects":
            continue
        for source, hits in _load_advanced_artifact(key, path).items():
            canonical = index.add(source)
            raw_advanced.setdefault(canonical, []).extend(hits)

    return SignalArtifactBundle(
        object_hits=_expand_index(raw_objects, index),
        advanced_hits=_expand_index(raw_advanced, index),
    )


def signal_artifact_paths(config: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    configured = getattr(config, "signal_artifacts", {}) or {}
    if isinstance(configured, dict):
        for key, value in configured.items():
            normalized = _normalize_key(key)
            if normalized in ARTIFACT_KEYS and value:
                values[normalized] = os.fspath(value)
    visual_objects = getattr(config, "visual_objects_path", None)
    if visual_objects:
        values["visual_objects"] = os.fspath(visual_objects)
    ai_frame_scores = getattr(config, "ai_frame_scores_path", None)
    if ai_frame_scores:
        values["ai_frame_scores"] = os.fspath(ai_frame_scores)
    return values


def validate_signal_artifact(path: str) -> dict[str, Any]:
    path = os.fspath(path)
    data = _read_optional_json(path)
    errors = []
    warnings = []
    if not data:
        return {"path": path, "status": "error", "errors": ["artifact is missing or not valid JSON"], "warnings": []}
    kind = _artifact_kind(data, path)
    if kind == "unknown":
        errors.append("could not infer signal artifact kind")
    schema_version = data.get("schema_version")
    if schema_version and schema_version != SIGNAL_SCHEMA_VERSION:
        warnings.append(f"unexpected schema_version: {schema_version}")
    if not data.get("provider"):
        warnings.append("provider is missing")
    if kind == "visual_objects" and not isinstance(data.get("sources", []), list):
        errors.append("visual_objects artifact requires sources list")
    if kind in {"ocr_signage", "face_person"} and not isinstance(data.get("hits", []), list):
        errors.append(f"{kind} artifact requires hits list")
    if kind == "motorsports_events" and not isinstance(data.get("events", []), list):
        errors.append("motorsports_events artifact requires events list")
    if kind == "topic_clusters" and not isinstance(data.get("topics", []), list):
        errors.append("topic_clusters artifact requires topics list")
    if kind == "ai_frame_scores" and not isinstance(data.get("sources", []), list):
        errors.append("ai_frame_scores artifact requires sources list")
    if "source_summaries" in data and not isinstance(data["source_summaries"], list):
        errors.append("source_summaries must be a list")
    return {
        "path": path,
        "status": "error" if errors else "ok",
        "kind": kind,
        "schema_version": schema_version,
        "provider": data.get("provider"),
        "source_count": data.get("source_count", len(data.get("source_summaries", []))),
        "count": data.get("count"),
        "errors": errors,
        "warnings": warnings + list(data.get("warnings", [])),
    }


def _load_visual_objects(path: str | None) -> dict[str, list[ObjectHit]]:
    data = _read_optional_json(path)
    if not data:
        return {}
    by_source: dict[str, list[ObjectHit]] = {}
    for source_payload in data.get("sources", []):
        source = source_payload.get("source")
        if not source:
            continue
        hits = [_object_hit_from_segment(segment) for segment in source_payload.get("segments", [])]
        hits = [hit for hit in hits if hit.end >= hit.start]
        if hits:
            by_source.setdefault(os.fspath(source), []).extend(hits)
    return by_source


def _artifact_kind(data: dict[str, Any], path: str) -> str:
    explicit = _normalize_key(data.get("artifact_kind", ""))
    if explicit in ARTIFACT_KEYS or explicit == "face_person_presence":
        return "face_person" if explicit == "face_person_presence" else explicit
    if "sources" in data:
        if _normalize_key(data.get("artifact_kind", "")) == "ai_frame_scores":
            return "ai_frame_scores"
        if data.get("schema_version") == "videoedit.ai_frame_scores.v1":
            return "ai_frame_scores"
        return "visual_objects"
    if "events" in data:
        return "motorsports_events"
    if "topics" in data:
        return "topic_clusters"
    provider = _normalize_key(data.get("provider", ""))
    if provider in {"ocr_signage", "tesseract_ocr"}:
        return "ocr_signage"
    if provider in {"face_person_presence", "opencv_face_person"}:
        return "face_person"
    filename = _normalize_key(os.path.basename(path))
    for key in ARTIFACT_KEYS:
        if key in filename:
            return key
    if "face_person" in filename:
        return "face_person"
    return "unknown"


def _load_advanced_artifact(kind: str, path: str | None) -> dict[str, list[dict[str, Any]]]:
    data = _read_optional_json(path)
    if not data:
        return {}
    if kind == "ocr_signage":
        return _ocr_hits(data)
    if kind == "face_person":
        return _face_person_hits(data)
    if kind == "motorsports_events":
        return _motorsports_hits(data)
    if kind == "topic_clusters":
        return _topic_hits(data)
    if kind == "ai_frame_scores":
        return _ai_frame_hits(data)
    return {}


def _ocr_hits(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for hit in data.get("hits", []):
        source = hit.get("source")
        text = str(hit.get("text") or "").strip()
        if not source or not text:
            continue
        rows.setdefault(os.fspath(source), []).append(
            {
                "kind": "ocr_signage",
                "start": 0.0,
                "end": 0.0,
                "source_wide": True,
                "text": text,
                "frame": hit.get("frame"),
            }
        )
    return rows


def _face_person_hits(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for hit in data.get("hits", []):
        source = hit.get("source")
        if not source:
            continue
        rows.setdefault(os.fspath(source), []).append(
            {
                "kind": "face_person",
                "start": 0.0,
                "end": 0.0,
                "source_wide": True,
                "face_count": int(hit.get("face_count", 0) or 0),
                "person_count": int(hit.get("person_count", 0) or 0),
                "frame": hit.get("frame"),
            }
        )
    return rows


def _motorsports_hits(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for event in data.get("events", []):
        source = event.get("source")
        if not source:
            continue
        rows.setdefault(os.fspath(source), []).append(
            {
                "kind": "motorsports_event",
                "start": _hit_seconds(event, "start", "start_seconds"),
                "end": _hit_seconds(event, "end", "end_seconds"),
                "event_type": event.get("event_type"),
                "confidence": event.get("confidence"),
                "evidence": list(event.get("evidence", [])),
            }
        )
    return rows


def _topic_hits(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for cluster in data.get("topics", []):
        topic = cluster.get("topic")
        for hit in cluster.get("hits", []):
            source = hit.get("source")
            if not source:
                continue
            rows.setdefault(os.fspath(source), []).append(
                {
                    "kind": "topic_cluster",
                    "start": _hit_seconds(hit, "start", "start_seconds"),
                    "end": _hit_seconds(hit, "end", "end_seconds"),
                    "topic": topic,
                    "keywords": list(hit.get("keywords", [])),
                    "text": hit.get("text", ""),
                }
            )
    return rows


def _ai_frame_hits(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    profile = data.get("profile", {}) if isinstance(data.get("profile"), dict) else {}
    for source_payload in data.get("sources", []):
        source = source_payload.get("source")
        if not source:
            continue
        for frame in source_payload.get("frames", []):
            timestamp = float(frame.get("time_seconds", 0.0) or 0.0)
            labels = list(frame.get("labels", []))
            rows.setdefault(os.fspath(source), []).append(
                {
                    "kind": "ai_frame_score",
                    "start": max(0.0, timestamp - 0.5),
                    "end": timestamp + 0.5,
                    "time_seconds": timestamp,
                    "time": frame.get("time"),
                    "profile": profile.get("id"),
                    "top_score": float(frame.get("top_score", 0.0) or 0.0),
                    "top_label": frame.get("top_label"),
                    "labels": labels,
                    "prompt_scores": list(frame.get("prompt_scores", [])),
                    "explanation": frame.get("explanation", ""),
                    "frame": frame.get("frame"),
                }
            )
    return rows


def _object_hit_from_segment(segment: dict[str, Any]) -> ObjectHit:
    start = float(segment.get("start_seconds", segment.get("start", 0.0)))
    end = float(segment.get("end_seconds", segment.get("end", start)))
    return ObjectHit(
        start=start,
        end=end,
        class_name=str(segment.get("class_name") or segment.get("label") or "object"),
        class_id=int(segment["class_id"]) if segment.get("class_id") is not None else None,
        count=int(segment.get("detection_count", segment.get("count", 1))),
        confidence=float(segment["average_confidence"]) if segment.get("average_confidence") is not None else None,
    )


def _expand_index(values: dict[str, list[Any]], source_index: SourceIndex) -> dict[str, list[Any]]:
    expanded: dict[str, list[Any]] = {}
    for source, hits in values.items():
        canonical = source_index.resolve(source)
        for key in _source_keys(canonical):
            expanded[key] = hits
        basename = os.path.basename(_path_key(canonical))
        matches = source_index.by_basename.get(basename, set())
        if len(matches) == 1:
            expanded[basename] = hits
    return expanded


def _lookup(values: dict[str, list[Any]], source: str) -> list[Any]:
    for key in _source_keys(source):
        if key in values:
            return values[key]
    return []


def _hit_seconds(hit: dict[str, Any], formatted_key: str, seconds_key: str) -> float:
    if seconds_key in hit:
        return float(hit[seconds_key])
    return timecode_to_seconds(hit.get(formatted_key, 0))


def _normalize_key(value: str) -> str:
    return str(value).strip().lower().replace("-", "_")


def _source_keys(source: str) -> set[str]:
    source = os.fspath(source)
    keys = {_path_key(source), _path_key(os.path.abspath(source))}
    keys.add(os.path.basename(_path_key(source)))
    return keys


def _path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(value).replace("\\", os.sep)))


def _read_optional_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    path = os.fspath(path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
