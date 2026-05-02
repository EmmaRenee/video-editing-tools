"""
Extract segments operation - Cut video clips from timestamps.

Uses FFmpeg to extract segments from video files based on timestamps.
Can be used standalone or with segment data from detection operations.
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult


class ExtractSegments(BaseOperation):
    """
    Extract video segments from timestamps.

    Takes a list of time segments and extracts each as a separate video file.
    Segments can come from audio detection, transcript analysis, or manual input.
    """

    name = "extract_segments"
    description = "Extract clips from timestamps"
    inputs = ["video", "segments"]
    outputs = ["video_clips"]

    def __init__(
        self,
        segments: List[Dict[str, float]] | None = None,
        segments_file: str | None = None,
        padding: float = 0.0,
        codec: str = "libx264",
        preset: str = "medium",
        crf: int = 23
    ):
        """
        Initialize extract operation.

        Args:
            segments: List of {start, end} dicts (in seconds)
            segments_file: Path to JSON file with segments
            padding: Seconds to add before/after each segment
            codec: Video codec to use
            preset: FFmpeg preset (ultrafast, fast, medium, slow, etc)
            crf: Quality (lower = better, 18-28 typical)
        """
        super().__init__()
        self.segments = segments or []
        self.segments_file = segments_file
        self.padding = padding
        self.codec = codec
        self.preset = preset
        self.crf = crf

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute extraction."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get segments from file, context, or direct input
        segments = self._get_segments(context)

        if not segments:
            return OperationResult(
                success=False,
                error="No segments found"
            )

        # Extract each segment
        clip_files = []
        for i, segment in enumerate(segments):
            start = segment["start"] - self.padding
            end = segment.get("end", segment["start"] + 5) + self.padding
            start = max(0, start)  # Don't go negative

            output_file = output_dir / f"clip_{i+1:03d}.mp4"

            success = self._extract_segment(input_path, output_file, start, end)

            if success:
                clip_files.append(str(output_file))

        if not clip_files:
            return OperationResult(
                success=False,
                error="No clips extracted successfully"
            )

        # Write clip manifest
        manifest_file = output_dir / f"{self.name}_manifest.json"
        with open(manifest_file, "w") as f:
            json.dump({
                "source": str(input_path),
                "clips": clip_files,
                "count": len(clip_files)
            }, f, indent=2)

        return OperationResult(
            success=True,
            output_path=manifest_file,
            data={
                "clips": clip_files,
                "count": len(clip_files),
                "manifest": str(manifest_file)
            }
        )

    def _get_segments(self, context: Dict[str, Any]) -> List[Dict[str, float]]:
        """Get segments from file, context, or direct input."""
        # From segments file
        if self.segments_file:
            path = Path(self.segments_file)
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                    return data.get("segments", [])

        # From context (previous detection step)
        if "segments" in context:
            return context["segments"]

        # From direct input
        return self.segments

    def _extract_segment(self, input_path: Path, output_path: Path, start: float, end: float) -> bool:
        """Extract a single segment using FFmpeg."""
        duration = end - start

        cmd = [
            "ffmpeg", "-ss", str(start),
            "-i", str(input_path),
            "-t", str(duration),
            "-c:v", self.codec,
            "-preset", self.preset,
            "-crf", str(self.crf),
            "-c:a", "aac",
            "-b:a", "128k",
            "-y",
            str(output_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        return result.returncode == 0 and output_path.exists()


def main():
    """CLI for testing extraction."""
    import argparse

    parser = argparse.ArgumentParser(description="Extract video segments")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--segments", help="JSON file with segments")
    parser.add_argument("--start", type=float, help="Start time (seconds)")
    parser.add_argument("--end", type=float, help="End time (seconds)")
    parser.add_argument("--padding", type=float, default=0, help="Padding (seconds)")
    parser.add_argument("--output", "-o", default="output", help="Output directory")

    args = parser.parse_args()

    segments = None
    if args.start is not None:
        end = args.end or (args.start + 5)
        segments = [{"start": args.start, "end": end}]

    op = ExtractSegments(
        segments_file=args.segments,
        segments=segments,
        padding=args.padding
    )

    result = op.execute(
        input_path=Path(args.input),
        output_dir=Path(args.output),
        context={}
    )

    if result.success:
        print(f"Extracted {result.data['count']} clips")
        for clip in result.data['clips']:
            print(f"  → {clip}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
