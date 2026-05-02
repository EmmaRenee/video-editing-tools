"""
EDL generation operation - Create DaVinci Resolve edit decision lists.

Generates EDL files from segment data for importing into DaVinci Resolve.
Includes transcript data as comments for reference.
"""
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class GenerateEdl(BaseOperation):
    """
    Generate EDL (Edit Decision List) for DaVinci Resolve.

    Takes segment timestamps and creates a standard EDL file that can
    be imported into DaVinci Resolve, Premiere, or other NLEs.
    """

    name = "generate_edl"
    description = "Create EDL for DaVinci Resolve"
    inputs = ["segments", "video"]
    outputs = ["edl"]

    # EDL standard frame rates
    FRAME_RATES = [24, 25, 30, 60]

    def __init__(
        self,
        fps: int = 30,
        reel_name: str = "CLIP",
        include_transcript: bool = True
    ):
        """
        Initialize EDL generation operation.

        Args:
            fps: Frames per second for timecode
            reel_name: Reel name to use in EDL
            include_transcript: Include transcript as comments
        """
        super().__init__()
        self.fps = fps
        self.reel_name = reel_name
        self.include_transcript = include_transcript

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute EDL generation."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get segments
        segments = self._get_segments(context)
        if not segments:
            return OperationResult(
                success=False,
                error="No segments found in context"
            )

        # Get transcript for comments
        transcript = self._get_transcript(context)

        # Generate EDL content
        edl_content = self._generate_edl(segments, transcript)

        # Write EDL file
        edl_file = output_dir / f"{self.name}.edl"
        edl_file.write_text(edl_content)

        return OperationResult(
            success=True,
            output_path=edl_file,
            data={
                "edl_file": str(edl_file),
                "events": len(segments),
                "fps": self.fps
            }
        )

    def _get_segments(self, context: Dict[str, Any]) -> list:
        """Get segments from context."""
        return context.get("segments", [])

    def _get_transcript(self, context: Dict[str, Any]) -> list:
        """Get transcript segments for comments."""
        if self.include_transcript:
            return context.get("transcript_segments", [])
        return []

    def _generate_edl(self, segments: list, transcript: list) -> str:
        """Generate EDL file content."""
        lines = []

        # EDL header
        lines.append("TITLE: Video Edit Pipeline")
        lines.append(f"FCM: NON-DROP FRAME")
        lines.append("")

        # Generate event for each segment
        for i, seg in enumerate(segments, 1):
            start_tc = self._seconds_to_tc(seg["start"])
            end_tc = self._seconds_to_tc(seg["end"])

            # EDL event format:
            # 001  001  V     C        01:00:00:00 01:00:05:00 01:00:00:00 01:00:05:00
            event_num = f"{i:03d}"
            reel = self.reel_name[:8]  # EDL limits reel name to 8 chars

            # Standard cut (C) transition
            lines.append(f"{event_num:3}  {reel:8}  V     C        {start_tc} {end_tc} {start_tc} {end_tc}")

            # Add transcript as comment if available
            if self.include_transcript and transcript:
                comment = self._find_transcript_comment(seg, transcript)
                if comment:
                    # Clip with comment
                    lines.append(f"* {comment[:60]}")

            lines.append("")

        return "\n".join(lines)

    def _seconds_to_tc(self, seconds: float) -> str:
        """Convert seconds to timecode (HH:MM:SS:FF)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        frames = int((seconds % 1) * self.fps)

        return f"{hours:02}:{minutes:02}:{secs:02}:{frames:02}"

    def _find_transcript_comment(self, segment: dict, transcript: list) -> str:
        """Find relevant transcript text for this segment."""
        seg_start = segment["start"]
        seg_end = segment["end"]

        for trans in transcript:
            trans_start = trans.get("start", 0)
            trans_end = trans.get("end", 0)

            # Check for overlap
            if not (trans_end < seg_start or trans_start > seg_end):
                return trans.get("text", "")

        return ""


def main():
    """CLI for testing EDL generation."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Generate EDL from segments")
    parser.add_argument("--segments", required=True, help="JSON file with segments")
    parser.add_argument("--transcript", help="JSON file with transcript")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", "-o", default="output.edl")

    args = parser.parse_args()

    op = GenerateEdl(fps=args.fps)

    context = {}
    with open(args.segments) as f:
        context["segments"] = json.load(f).get("segments", [])

    if args.transcript:
        with open(args.transcript) as f:
            context["transcript_segments"] = json.load(f).get("segments", [])

    result = op.execute(
        input_path=Path("dummy"),
        output_dir=Path(args.output).parent,
        context=context
    )

    if result.success:
        print(f"Generated EDL: {result.output_path}")
        print(f"Events: {result.data['events']}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
