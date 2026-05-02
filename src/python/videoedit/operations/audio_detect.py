"""
Audio highlight detection operation.

Finds moments of high audio energy using FFmpeg audio analysis.
Useful for detecting exciting moments in racing footage, sports, etc.
"""
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseOperation, OperationResult


@dataclass
class AudioSegment:
    """A time segment with audio data."""
    start: float  # seconds
    end: float  # seconds
    peak_db: float  # peak volume in dB
    duration: float  # segment duration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "peak_db": self.peak_db,
            "duration": self.duration
        }


class DetectHighlightsAudio(BaseOperation):
    """
    Detect highlight moments based on audio spike analysis.

    Uses FFmpeg to analyze audio volume and find segments that exceed
    a threshold. Good for detecting exciting moments in unedited footage.
    """

    name = "detect_highlights_audio"
    description = "Find highlights via audio spike detection"
    inputs = ["video"]
    outputs = ["segments_json"]

    def __init__(
        self,
        threshold: float = -25,
        min_duration: float = 1.0,
        max_clips: int = 10,
        window_size: float = 0.5,
        padding: float = 0.0
    ):
        """
        Initialize audio detection operation.

        Args:
            threshold: dB threshold (negative, e.g., -25 = louder than -25dB)
            min_duration: Minimum segment length in seconds
            max_clips: Maximum number of clips to return
            window_size: Analysis window size in seconds
            padding: Padding to add around detected segments
        """
        super().__init__()
        self.threshold = threshold
        self.min_duration = min_duration
        self.max_clips = max_clips
        self.window_size = window_size
        self.padding = padding

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute audio detection."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run FFmpeg audio analysis
        audio_data = self._analyze_audio(input_path)

        if not audio_data:
            return OperationResult(
                success=False,
                error="No audio data found or analysis failed"
            )

        # Find segments above threshold
        segments = self._find_segments(audio_data)

        if not segments:
            return OperationResult(
                success=False,
                error=f"No segments found above threshold {self.threshold}dB"
            )

        # Sort by peak volume and limit
        segments.sort(key=lambda s: s.peak_db, reverse=True)
        segments = segments[:self.max_clips]
        segments.sort(key=lambda s: s.start)  # Re-sort by time

        # Apply padding
        if self.padding > 0:
            for seg in segments:
                seg.start = max(0, seg.start - self.padding)
                seg.end += self.padding

        # Write segments JSON
        segments_file = output_dir / f"{self.name}_segments.json"
        with open(segments_file, "w") as f:
            json.dump({
                "threshold": self.threshold,
                "segments": [s.to_dict() for s in segments]
            }, f, indent=2)

        return OperationResult(
            success=True,
            output_path=segments_file,
            data={
                "segments": [s.to_dict() for s in segments],
                "segments_file": str(segments_file),
                "count": len(segments)
            },
            metadata={
                "method": "audio_spike",
                "threshold": self.threshold,
                "analyzed_duration": audio_data[-1]["time"] if audio_data else 0
            }
        )

    def _analyze_audio(self, input_path: Path) -> List[Dict[str, float]]:
        """
        Analyze audio using FFmpeg astats filter.

        Returns list of {time, dB} samples.
        """
        cmd = [
            "ffmpeg", "-i", str(input_path),
            "-filter_complex", "[0:a]astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode != 0:
            return []

        # Parse FFmpeg output for dB values
        samples = []
        for line in result.stderr.split('\n'):
            # Look for lines like: frame:123 pts:123 pts_time:1.234
            if "pts_time:" in line:
                time_match = re.search(r"pts_time:(\d+\.?\d*)", line)
                if not time_match:
                    continue
                time = float(time_match.group(1))

            # Look for dB value
            if "lavfi.astats.Overall.RMS_level=" in line:
                db_match = re.search(r"=(-?\d+\.?\d*) dB", line)
                if db_match:
                    db = float(db_match.group(1))
                    samples.append({"time": time, "dB": db})

        return samples

    def _find_segments(self, audio_data: List[Dict[str, float]]) -> List[AudioSegment]:
        """Find continuous segments above threshold."""
        if not audio_data:
            return []

        segments = []
        in_segment = False
        segment_start = 0
        peak_db = self.threshold

        for i, sample in enumerate(audio_data):
            above = sample["dB"] > self.threshold

            if above and not in_segment:
                # Start new segment
                in_segment = True
                segment_start = sample["time"]
                peak_db = sample["dB"]

            elif above and in_segment:
                # Continue segment, track peak
                peak_db = max(peak_db, sample["dB"])

            elif not above and in_segment:
                # End segment
                segment_end = audio_data[i - 1]["time"] if i > 0 else sample["time"]
                duration = segment_end - segment_start

                if duration >= self.min_duration:
                    segments.append(AudioSegment(
                        start=segment_start,
                        end=segment_end,
                        peak_db=peak_db,
                        duration=duration
                    ))

                in_segment = False

        # Handle case where video ends while above threshold
        if in_segment and audio_data:
            last = audio_data[-1]
            duration = last["time"] - segment_start
            if duration >= self.min_duration:
                segments.append(AudioSegment(
                    start=segment_start,
                    end=last["time"],
                    peak_db=peak_db,
                    duration=duration
                ))

        return segments


def main():
    """CLI for testing audio detection."""
    import argparse

    parser = argparse.ArgumentParser(description="Detect highlights via audio")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--threshold", type=float, default=-25, help="dB threshold")
    parser.add_argument("--max-clips", type=int, default=10, help="Maximum clips")
    parser.add_argument("--output", "-o", default="segments.json", help="Output JSON")

    args = parser.parse_args()

    op = DetectHighlightsAudio(
        threshold=args.threshold,
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
