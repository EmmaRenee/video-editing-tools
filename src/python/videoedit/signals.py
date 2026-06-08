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
}


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
    return values


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
