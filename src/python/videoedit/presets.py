"""
Pipeline presets - Pre-configured workflows for common video editing tasks.
"""

PRESETS = {
    "reel": {
        "name": "Instagram Reel from Raw",
        "description": "Extract highlights and format for 9:16 vertical",
        "steps": [
            {
                "name": "transcribe",
                "operation": "transcribe_whisper",
                "params": {"model": "small"}
            },
            {
                "name": "detect_highlights",
                "operation": "detect_highlights_audio",
                "params": {"threshold": -25, "max_clips": 5}
            },
            {
                "name": "extract_clips",
                "operation": "extract_segments",
                "input": "detect_highlights",
                "params": {"padding": 0.5}
            },
            {
                "name": "format_vertical",
                "operation": "format_video",
                "params": {"aspect_ratio": "9:16", "resolution": "1080x1920"}
            },
            {
                "name": "captions",
                "operation": "burn_captions",
                "input": "transcribe",
                "params": {"style": "automotive_racing"}
            }
        ]
    },
    "youtube": {
        "name": "YouTube Highlights",
        "description": "Extract highlights for 16:9 horizontal video",
        "steps": [
            {
                "name": "transcribe",
                "operation": "transcribe_whisper",
                "params": {"model": "base"}
            },
            {
                "name": "detect_highlights",
                "operation": "detect_highlights_audio",
                "params": {"threshold": -20, "max_clips": 10}
            },
            {
                "name": "extract_clips",
                "operation": "extract_segments",
                "input": "detect_highlights",
                "params": {"padding": 1.0}
            },
            {
                "name": "format_horizontal",
                "operation": "format_video",
                "params": {"aspect_ratio": "16:9", "resolution": "1920x1080"}
            }
        ]
    },
    "documentary": {
        "name": "Documentary Rough Cut",
        "description": "Transcribe and extract key moments for long-form content",
        "steps": [
            {
                "name": "transcribe",
                "operation": "transcribe_whisper",
                "params": {"model": "base"}
            },
            {
                "name": "find_moments",
                "operation": "detect_highlights_transcript",
                "params": {"keywords": ["important", "reveal", "finally", "announcement"]}
            },
            {
                "name": "extract_segments",
                "operation": "extract_segments",
                "input": "find_moments",
                "params": {"padding": 2.0}
            },
            {
                "name": "generate_edl",
                "operation": "generate_edl",
                "params": {}
            }
        ]
    },
    "simple": {
        "name": "Simple Clip Extract",
        "description": "Just find audio highlights and extract clips",
        "steps": [
            {
                "name": "detect_highlights",
                "operation": "detect_highlights_audio",
                "params": {"threshold": -25, "max_clips": 5}
            },
            {
                "name": "extract_clips",
                "operation": "extract_segments",
                "input": "detect_highlights",
                "params": {}
            }
        ]
    }
}
