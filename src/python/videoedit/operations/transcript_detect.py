"""
Transcript highlight detection operation.

Finds highlight moments based on transcript analysis using keywords,
patterns, and simple emotion detection.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult


@dataclass
class TextSegment:
    """A segment of text with timing."""
    start: float
    end: float
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text
        }


class DetectHighlightsTranscript(BaseOperation):
    """
    Detect highlights based on transcript analysis.

    Finds segments matching keywords, emotional patterns, or specific phrases.
    Useful for finding key moments in interviews, commentary, etc.
    """

    name = "detect_highlights_transcript"
    description = "Find highlights via transcript analysis"
    inputs = ["srt", "vtt", "transcript"]
    outputs = ["segments_json"]

    # Default keyword categories
    EXCITEMENT_KEYWORDS = [
        "wow", "amazing", "incredible", "unbelievable", "holy",
        "oh my", "no way", "insane", "crazy", "what", "yes",
        "finally", "boom", "banger", "fire", "lit"
    ]

    QUESTION_PATTERNS = [
        r"\bcan you\b", r"\bwill you\b", r"\bhow do\b",
        r"\bwhat is\b", r"\bwhy\b", r"\bwhen\b", r"\bwhere\b"
    ]

    def __init__(
        self,
        keywords: List[str] | None = None,
        min_duration: float = 2.0,
        max_clips: int = 10,
        context_window: float = 3.0,
        use_emotion: bool = True,
        use_questions: bool = False
    ):
        """
        Initialize transcript detection operation.

        Args:
            keywords: List of keywords to search for
            min_duration: Minimum segment length in seconds
            max_clips: Maximum number of clips to return
            context_window: Seconds of context around matches
            use_emotion: Include emotion-based keyword detection
            use_questions: Also detect questions
        """
        super().__init__()
        self.keywords = keywords or (self.EXCITEMENT_KEYWORDS if use_emotion else [])
        self.min_duration = min_duration
        self.max_clips = max_clips
        self.context_window = context_window
        self.use_questions = use_questions

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute transcript detection."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get transcript segments
        segments = self._load_segments(input_path, context)
        if not segments:
            return OperationResult(
                success=False,
                error="No transcript segments found"
            )

        # Find matching segments
        matches = self._find_matches(segments)

        if not matches:
            return OperationResult(
                success=False,
                error=f"No matches found for keywords: {self.keywords[:5]}..."
            )

        # Merge nearby matches and add context
        highlights = self._merge_and_expand(matches)

        # Sort by "intensity" (keyword density) and limit
        highlights = sorted(highlights, key=lambda h: h.get("score", 0), reverse=True)
        highlights = highlights[:self.max_clips]
        highlights = sorted(highlights, key=lambda h: h["start"])

        # Write segments JSON
        segments_file = output_dir / f"{self.name}_segments.json"
        with open(segments_file, "w") as f:
            json.dump({
                "method": "transcript_keywords",
                "keywords": self.keywords,
                "segments": highlights
            }, f, indent=2)

        return OperationResult(
            success=True,
            output_path=segments_file,
            data={
                "segments": highlights,
                "segments_file": str(segments_file),
                "count": len(highlights)
            },
            metadata={
                "method": "transcript_keywords",
                "keywords_searched": len(self.keywords)
            }
        )

    def _load_segments(self, input_path: Path, context: Dict[str, Any]) -> List[TextSegment]:
        """Load transcript segments from file or context."""
        segments = []

        # Try to get from context first
        if "segments" in context:
            # From previous transcript operation
            for seg in context["segments"]:
                segments.append(TextSegment(
                    start=seg.get("start", 0),
                    end=seg.get("end", 0),
                    text=seg.get("text", "")
                ))

        # Try loading from SRT file
        if not segments:
            srt_file = self._find_srt_file(input_path, context)
            if srt_file and srt_file.exists():
                segments = self._parse_srt(srt_file)

        return segments

    def _find_srt_file(self, input_path: Path, context: Dict[str, Any]) -> Path | None:
        """Find SRT file from various sources."""
        # Check context
        for key in ["srt", "srt_file", "transcript_file"]:
            if key in context:
                return Path(context[key])

        # Check for file with same name as input
        srt_path = input_path.with_suffix(".srt")
        if srt_path.exists():
            return srt_path

        return None

    def _parse_srt(self, srt_path: Path) -> List[TextSegment]:
        """Parse SRT file into segments."""
        pattern = r"(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n*$)"

        content = srt_path.read_text(encoding="utf-8")
        matches = re.findall(pattern, content, re.DOTALL)

        segments = []
        for match in matches:
            h1, m1, s1, ms1, h2, m2, s2, ms2, text = match
            start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
            end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000
            segments.append(TextSegment(start=start, end=end, text=text.strip()))

        return segments

    def _find_matches(self, segments: List[TextSegment]) -> List[Dict[str, Any]]:
        """Find segments matching keywords."""
        matches = []

        # Build search patterns
        patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in self.keywords]

        # Add question patterns if enabled
        if self.use_questions:
            patterns.extend([re.compile(p, re.IGNORECASE) for p in self.QUESTION_PATTERNS])

        for seg in segments:
            for pattern in patterns:
                if pattern.search(seg.text):
                    matches.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text,
                        "match": pattern.pattern
                    })
                    break  # Only count each segment once

        return matches

    def _merge_and_expand(self, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge nearby matches and add context window."""
        if not matches:
            return []

        # Sort by time
        matches = sorted(matches, key=lambda m: m["start"])

        merged = []
        current = matches[0].copy()

        for match in matches[1:]:
            # If close enough, merge
            if match["start"] - current["end"] < self.context_window:
                current["end"] = match["end"]
                current["text"] += " " + match["text"]
                current["score"] = current.get("score", 1) + 1
            else:
                # Add context window
                current["start"] = max(0, current["start"] - self.context_window)
                current["end"] += self.context_window
                merged.append(current)
                current = match.copy()
                current["score"] = 1

        # Add last one
        current["start"] = max(0, current["start"] - self.context_window)
        current["end"] += self.context_window
        merged.append(current)

        # Filter by duration
        return [m for m in merged if m["end"] - m["start"] >= self.min_duration]


def main():
    """CLI for testing transcript detection."""
    import argparse

    parser = argparse.ArgumentParser(description="Detect highlights from transcript")
    parser.add_argument("input", help="SRT transcript file")
    parser.add_argument("--keywords", nargs="+", help="Keywords to search for")
    parser.add_argument("--max-clips", type=int, default=10)
    parser.add_argument("--output", "-o", default="segments.json")

    args = parser.parse_args()

    op = DetectHighlightsTranscript(
        keywords=args.keywords,
        max_clips=args.max_clips
    )

    result = op.execute(
        input_path=Path(args.input),
        output_dir=Path(args.output).parent,
        context={}
    )

    if result.success:
        print(f"Found {result.data['count']} segments")
        print(f"Output: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
