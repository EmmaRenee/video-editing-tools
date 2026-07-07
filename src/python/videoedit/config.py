"""Configuration for footage analysis and scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .simple_yaml import load_mapping


@dataclass
class AnalysisConfig:
    scene_threshold: float = 0.35
    silence_threshold_db: float = -30.0
    min_silence_duration: float = 1.0
    audio_spike_percentile: float = 85.0
    audio_spike_floor_db: float = -35.0
    window_pre_roll: float = 3.0
    window_post_roll: float = 9.0
    merge_gap: float = 4.0
    max_candidates: int = 50
    min_select_score: int = 85
    min_review_score: int = 70
    min_broll_score: int = 55
    transcript_mode: str = "auto"
    transcript_dir: str | None = None
    visual_objects_path: str | None = None
    ai_frame_scores_path: str | None = None
    ai_clip_judgments_path: str | None = None
    signal_artifacts: dict[str, str] = field(default_factory=dict)
    object_window_pre_roll: float = 1.0
    object_window_post_roll: float = 2.0
    object_interest_classes: list[str] = field(
        default_factory=lambda: [
            "person",
            "car",
            "truck",
            "motorcycle",
            "bicycle",
            "bus",
            "traffic light",
            "stop sign",
        ]
    )
    cache: bool = True
    command_timeout: int = 180
    keywords: list[str] = field(
        default_factory=lambda: [
            "wow",
            "amazing",
            "pass",
            "passed",
            "overtake",
            "incident",
            "crash",
            "spin",
            "fast",
            "lap",
            "start",
            "finish",
            "checkered",
            "problem",
            "issue",
            "win",
            "podium",
        ]
    )
    weights: dict[str, int] = field(
        default_factory=lambda: {
            "technical": 20,
            "visual": 25,
            "audio": 35,
            "transcript": 20,
            "objects": 10,
            "ocr": 8,
            "face_person": 6,
            "motorsports": 12,
            "topics": 10,
            "ai": 10,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_file(cls, path: str | None) -> "AnalysisConfig":
        if not path:
            return cls()
        data = load_mapping(path)
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "AnalysisConfig":
        config = cls()
        if not data:
            return config
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config
