"""Typed artifacts used by the videoedit pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .timecode import seconds_to_hhmmss, timecode_to_seconds


@dataclass
class MediaAsset:
    filename: str
    filepath: str
    size_mb: float = 0.0
    duration: float = 0.0
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    fps: float | None = None
    has_audio: bool = False
    status: str = "ok"
    error: str | None = None

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "N/A"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resolution"] = self.resolution
        data["duration_formatted"] = seconds_to_hhmmss(self.duration)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaAsset":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: data.get(key) for key in allowed if key in data})


@dataclass
class SilenceInterval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "start_tc": seconds_to_hhmmss(self.start),
            "end_tc": seconds_to_hhmmss(self.end),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SilenceInterval":
        return cls(start=float(data["start"]), end=float(data["end"]))


@dataclass
class AudioLevel:
    time: float
    rms_db: float

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "rms_db": self.rms_db, "time_tc": seconds_to_hhmmss(self.time)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudioLevel":
        return cls(time=float(data["time"]), rms_db=float(data["rms_db"]))


@dataclass
class TranscriptHit:
    start: float
    end: float
    text: str
    keywords: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "keywords": self.keywords,
            "start_tc": seconds_to_hhmmss(self.start),
            "end_tc": seconds_to_hhmmss(self.end),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptHit":
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            text=data.get("text", ""),
            keywords=list(data.get("keywords", [])),
        )


@dataclass
class ObjectHit:
    start: float
    end: float
    class_name: str
    class_id: int | None = None
    count: int = 1
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "class_name": self.class_name,
            "class_id": self.class_id,
            "count": self.count,
            "confidence": self.confidence,
            "start_tc": seconds_to_hhmmss(self.start),
            "end_tc": seconds_to_hhmmss(self.end),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectHit":
        return cls(
            start=float(data.get("start_seconds", data.get("start", 0))),
            end=float(data.get("end_seconds", data.get("end", data.get("start", 0)))),
            class_name=str(data.get("class_name") or data.get("label") or "object"),
            class_id=int(data["class_id"]) if data.get("class_id") is not None else None,
            count=int(data.get("count", data.get("detection_count", 1))),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
        )


@dataclass
class SignalReport:
    asset: MediaAsset
    scene_changes: list[float] = field(default_factory=list)
    silence_intervals: list[SilenceInterval] = field(default_factory=list)
    audio_levels: list[AudioLevel] = field(default_factory=list)
    transcript_hits: list[TranscriptHit] = field(default_factory=list)
    object_hits: list[ObjectHit] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset.to_dict(),
            "scene_changes": self.scene_changes,
            "scene_changes_tc": [seconds_to_hhmmss(value) for value in self.scene_changes],
            "silence_intervals": [item.to_dict() for item in self.silence_intervals],
            "audio_levels": [item.to_dict() for item in self.audio_levels],
            "transcript_hits": [item.to_dict() for item in self.transcript_hits],
            "object_hits": [item.to_dict() for item in self.object_hits],
            "scores": self.scores,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalReport":
        return cls(
            asset=MediaAsset.from_dict(data["asset"]),
            scene_changes=[float(value) for value in data.get("scene_changes", [])],
            silence_intervals=[
                SilenceInterval.from_dict(item) for item in data.get("silence_intervals", [])
            ],
            audio_levels=[AudioLevel.from_dict(item) for item in data.get("audio_levels", [])],
            transcript_hits=[
                TranscriptHit.from_dict(item) for item in data.get("transcript_hits", [])
            ],
            object_hits=[ObjectHit.from_dict(item) for item in data.get("object_hits", [])],
            scores=dict(data.get("scores", {})),
            reasons=list(data.get("reasons", [])),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class CandidateClip:
    id: str
    source: str
    start: float
    end: float
    score: int
    action: str
    labels: list[str]
    reasons: list[str]
    signals: dict[str, float | int | None]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "start": seconds_to_hhmmss(self.start),
            "end": seconds_to_hhmmss(self.end),
            "start_seconds": self.start,
            "end_seconds": self.end,
            "duration": self.duration,
            "score": self.score,
            "action": self.action,
            "labels": self.labels,
            "reasons": self.reasons,
            "signals": self.signals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateClip":
        return cls(
            id=data["id"],
            source=data["source"],
            start=_seconds_from_clip(data, "start", "start_seconds"),
            end=_seconds_from_clip(data, "end", "end_seconds"),
            score=int(data["score"]),
            action=data["action"],
            labels=list(data.get("labels", [])),
            reasons=list(data.get("reasons", [])),
            signals=dict(data.get("signals", {})),
        )


@dataclass
class SelectionSet:
    source: str
    clips: list[CandidateClip]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "clips": [
                {
                    "start": clip.to_dict()["start"],
                    "end": clip.to_dict()["end"],
                    "label": clip.id,
                    "score": clip.score,
                    "action": clip.action,
                    "reasons": clip.reasons,
                }
                for clip in self.clips
            ],
        }


@dataclass
class RatingReport:
    generated: str
    root: str
    config: dict[str, Any]
    inventory: list[MediaAsset]
    signals: list[SignalReport]
    candidates: list[CandidateClip]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "root": self.root,
            "config": self.config,
            "summary": self.summary,
            "inventory": [item.to_dict() for item in self.inventory],
            "signals": [item.to_dict() for item in self.signals],
            "candidates": [item.to_dict() for item in self.candidates],
        }


def _seconds_from_clip(data: dict[str, Any], formatted_key: str, seconds_key: str) -> float:
    if seconds_key in data:
        return float(data[seconds_key])
    return timecode_to_seconds(data.get(formatted_key, 0))
