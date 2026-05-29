"""Transcript discovery and lightweight highlight matching."""

from __future__ import annotations

import os
import re

from .models import TranscriptHit
from .timecode import timecode_to_seconds


TRANSCRIPT_EXTENSIONS = (".srt", ".vtt", ".txt")


def find_transcript(video_path: str, transcript_dir: str | None = None) -> str | None:
    video_path = os.fspath(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    base_without_suffix = os.path.splitext(video_path)[0]
    candidates: list[str] = []
    if transcript_dir:
        base = os.fspath(transcript_dir)
        candidates.extend(os.path.join(base, f"{stem}{ext}") for ext in TRANSCRIPT_EXTENSIONS)
    candidates.extend(f"{base_without_suffix}{ext}" for ext in TRANSCRIPT_EXTENSIONS)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def parse_srt(path: str, keywords: list[str]) -> list[TranscriptHit]:
    with open(os.fspath(path), encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    pattern = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
        r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3}).*?\n"
        r"(?P<text>.*?)(?=\n\s*\n|\Z)",
        re.DOTALL,
    )
    hits: list[TranscriptHit] = []
    lowered_keywords = [item.lower() for item in keywords]
    for match in pattern.finditer(text):
        block_text = re.sub(r"<[^>]+>", "", match.group("text")).replace("\n", " ").strip()
        lowered = block_text.lower()
        matched = [word for word in lowered_keywords if word in lowered]
        if matched:
            hits.append(
                TranscriptHit(
                    start=timecode_to_seconds(match.group("start").replace(",", ".")),
                    end=timecode_to_seconds(match.group("end").replace(",", ".")),
                    text=block_text,
                    keywords=matched,
                )
            )
    return hits


def parse_text_transcript(path: str, keywords: list[str], duration: float) -> list[TranscriptHit]:
    with open(os.fspath(path), encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    lowered = text.lower()
    matched = [word.lower() for word in keywords if word.lower() in lowered]
    if not matched:
        return []
    return [TranscriptHit(start=0.0, end=min(duration, 20.0), text=text[:500], keywords=matched)]


def find_transcript_hits(
    video_path: str,
    duration: float,
    keywords: list[str],
    transcript_dir: str | None = None,
) -> tuple[list[TranscriptHit], str | None]:
    transcript_path = find_transcript(video_path, transcript_dir)
    if not transcript_path:
        return [], None
    if os.path.splitext(transcript_path)[1].lower() in {".srt", ".vtt"}:
        return parse_srt(transcript_path, keywords), str(transcript_path)
    return parse_text_transcript(transcript_path, keywords, duration), str(transcript_path)
