"""
videoedit - AI-first video editing pipeline system

Provides a Python API and CLI for building and running video processing pipelines.
Designed for Claude to use directly, with optional TUI for humans.

Usage:
    from videoedit import Pipeline, Runner

    pipeline = Pipeline()
    pipeline.add("transcribe_whisper", model="small")
    pipeline.add("detect_highlights_audio", threshold=-25)

    runner = Runner(pipeline)
    result = runner.run("footage.mp4")
"""

from .pipeline import Pipeline, Step, Runner

__version__ = "0.2.0"

__all__ = ["Pipeline", "Step", "Runner"]
