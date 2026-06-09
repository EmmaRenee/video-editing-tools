"""Pipeline presets."""

from __future__ import annotations


PRESETS = {
    "simple": {
        "name": "simple",
        "description": "FFmpeg-only highlight detection and rating",
        "requires_modules": ["core.rating"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {"transcript_mode": "off", "max_candidates": 50},
            }
        ],
    },
    "reel": {
        "name": "reel",
        "description": "Rate footage and identify high-energy reel candidates",
        "requires_modules": ["core.rating", "core.handoff"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "transcript_mode": "auto",
                    "max_candidates": 40,
                    "window_pre_roll": 3,
                    "window_post_roll": 9,
                },
            },
            {"name": "edl", "operation": "generate_edl", "params": {"output": "${output}/edl"}},
        ],
    },
    "roughcut": {
        "name": "roughcut",
        "description": "Rate footage, create review assets, approve defaults, plan a rough cut, export handoff, and assemble",
        "requires_modules": ["core.rating", "core.review", "core.handoff"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "transcript_mode": "auto",
                    "max_candidates": 50,
                    "min_review_score": 0,
                    "window_pre_roll": 3,
                    "window_post_roll": 12,
                },
            },
            {
                "name": "review",
                "operation": "generate_review_assets",
                "input": "rate.ratings",
                "params": {
                    "output": "${output}/review",
                    "max_items": 50,
                    "proxy": False,
                },
            },
            {
                "name": "approve",
                "operation": "approve_candidates",
                "input": "rate.ratings",
                "params": {
                    "output": "${output}/approved.json",
                    "decisions": "review.decisions",
                },
            },
            {
                "name": "edl",
                "operation": "generate_edl",
                "input": "approve.approved",
                "params": {"output": "${output}/edl"},
            },
            {
                "name": "plan",
                "operation": "plan_roughcut",
                "input": "approve.approved",
                "params": {
                    "output": "${output}/roughcut_plan.json",
                    "sequence": "review_order",
                    "format": "original",
                    "render_mode": "copy",
                },
            },
            {
                "name": "assemble",
                "operation": "assemble_rough_cut",
                "input": "approve.approved",
                "params": {"output": "${output}/rough_cut.mp4"},
            },
        ],
    },
    "youtube": {
        "name": "youtube",
        "description": "Rate footage and prepare longer highlight selections",
        "requires_modules": ["core.rating", "core.handoff"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "transcript_mode": "auto",
                    "max_candidates": 75,
                    "window_pre_roll": 5,
                    "window_post_roll": 20,
                },
            },
            {"name": "edl", "operation": "generate_edl", "params": {"output": "${output}/edl"}},
        ],
    },
    "documentary": {
        "name": "documentary",
        "description": "Transcript-forward documentary rough selection",
        "requires_modules": ["core.rating", "core.handoff"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "transcript_mode": "auto",
                    "max_candidates": 100,
                    "window_pre_roll": 8,
                    "window_post_roll": 30,
                },
            },
            {
                "name": "transcript_highlights",
                "operation": "detect_highlights_transcript",
                "input": "rate.ratings",
                "params": {"label": "transcript_hit"},
            },
            {
                "name": "edl",
                "operation": "generate_edl",
                "input": "transcript_highlights.selections",
                "params": {"output": "${output}/edl"},
            },
        ],
    },
    "motorsports": {
        "name": "motorsports",
        "description": "Racing footage rating with motorsports event and topic artifacts",
        "requires_modules": ["core.rating", "advanced.motorsports", "content.reports", "core.review", "core.handoff"],
        "steps": [
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "transcript_mode": "auto",
                    "max_candidates": 75,
                    "window_pre_roll": 4,
                    "window_post_roll": 14,
                },
            },
            {
                "name": "events",
                "operation": "detect_motorsports_events",
                "input": "rate.ratings",
                "params": {"output": "${output}/motorsports_events.json"},
            },
            {
                "name": "topics",
                "operation": "cluster_transcript_topics",
                "input": "rate.ratings",
                "params": {"output": "${output}/topic_clusters.json"},
            },
            {
                "name": "review",
                "operation": "generate_review_assets",
                "input": "rate.ratings",
                "params": {
                    "output": "${output}/review",
                    "max_items": 75,
                    "proxy": False,
                },
            },
            {"name": "edl", "operation": "generate_edl", "params": {"output": "${output}/edl"}},
        ],
    },
    "vision_reel": {
        "name": "vision_reel",
        "description": "Run optional vision providers, then rate reel candidates with fused signal artifacts",
        "requires_modules": ["core.rating", "advanced.vision", "core.review", "core.handoff"],
        "steps": [
            {
                "name": "objects",
                "operation": "detect_visual_objects",
                "params": {
                    "output": "${output}/signals/visual_objects.json",
                    "model": "yolo26n.pt",
                    "max_detections": 5000,
                },
            },
            {
                "name": "ocr",
                "operation": "detect_ocr_signage",
                "params": {
                    "output": "${output}/signals/ocr_signage.json",
                    "sample_interval": 10,
                    "max_frames_per_file": 6,
                },
            },
            {
                "name": "faces",
                "operation": "detect_face_person_presence",
                "params": {
                    "output": "${output}/signals/face_person_presence.json",
                    "sample_interval": 10,
                    "max_frames_per_file": 6,
                },
            },
            {
                "name": "rate",
                "operation": "rate_footage",
                "params": {
                    "output": "${output}/rate",
                    "transcript_mode": "auto",
                    "max_candidates": 60,
                    "visual_objects": "objects.output",
                    "ocr_signage": "ocr.output",
                    "face_person": "faces.output",
                },
            },
            {
                "name": "review",
                "operation": "generate_review_assets",
                "input": "rate.ratings",
                "params": {
                    "output": "${output}/review",
                    "max_items": 60,
                    "proxy": False,
                },
            },
            {
                "name": "approve",
                "operation": "approve_candidates",
                "input": "rate.ratings",
                "params": {
                    "output": "${output}/approved.json",
                    "decisions": "review.decisions",
                },
            },
            {"name": "edl", "operation": "generate_edl", "input": "approve.approved", "params": {"output": "${output}/edl"}},
        ],
    },
}
