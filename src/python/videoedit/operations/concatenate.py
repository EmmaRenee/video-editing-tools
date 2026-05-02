"""
Concatenate videos operation - Combine multiple clips into one.

Uses FFmpeg concat demuxer for fast, lossless video joining.
Supports automatic clip discovery from context or manual list.
"""
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult


class ConcatenateVideos(BaseOperation):
    """
    Concatenate multiple video clips into a single file.

    Uses FFmpeg's concat demuxer which avoids re-encoding for
    same-format videos, resulting in fast, lossless joining.
    """

    name = "concatenate_videos"
    description = "Combine multiple video clips into one"
    inputs = ["video_clips"]
    outputs = ["video"]

    def __init__(
        self,
        clips: List[str] | None = None,
        output_name: str = "concatenated.mp4",
        reencode: bool = False
    ):
        """
        Initialize concatenate operation.

        Args:
            clips: List of clip file paths (or use from context)
            output_name: Name for output file
            reencode: Force re-encoding (useful for mixed formats)
        """
        super().__init__()
        self.clips = clips
        self.output_name = output_name
        self.reencode = reencode

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute concatenation."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get clips to concatenate
        clips = self._get_clips(context)
        if not clips:
            return OperationResult(
                success=False,
                error="No clips found to concatenate"
            )

        if len(clips) < 2:
            return OperationResult(
                success=False,
                error=f"Need at least 2 clips, got {len(clips)}"
            )

        # Validate all clips exist
        clip_paths = []
        for clip in clips:
            clip_path = Path(clip)
            if not clip_path.exists():
                return OperationResult(
                    success=False,
                    error=f"Clip not found: {clip_path}"
                )
            clip_paths.append(clip_path)

        output_file = output_dir / self.output_name

        # Execute concatenation
        if self.reencode:
            result = self._concatenate_with_reencode(clip_paths, output_file)
        else:
            result = self._concatenate_demuxer(clip_paths, output_file)

        if not result.success:
            return result

        # Update context
        return OperationResult(
            success=True,
            output_path=output_file,
            data={
                "output_file": str(output_file),
                "clip_count": len(clip_paths),
                "clips": [str(p) for p in clip_paths]
            }
        )

    def _get_clips(self, context: Dict[str, Any]) -> List[Path]:
        """Get clips from parameter or context."""
        if self.clips:
            return [Path(c) for c in self.clips]

        # Try to get from context
        clips = []

        # Check for extracted clips
        if "clips" in context:
            clips = context["clips"]

        # Check for segments with output paths
        elif "segments" in context:
            for seg in context["segments"]:
                if "output_path" in seg:
                    clips.append(seg["output_path"])

        return [Path(c) for c in clips] if clips else []

    def _concatenate_demuxer(self, clips: List[Path], output_file: Path) -> OperationResult:
        """
        Concatenate using FFmpeg concat demuxer (fast, lossless).

        Creates a temporary file list and uses -f concat.
        """
        # Create concat file list
        fd, concat_file = tempfile.mkstemp(suffix=".txt", text=True)
        os.close(fd)

        try:
            # Write file list
            with open(concat_file, "w") as f:
                for clip in clips:
                    # Use absolute paths to avoid issues
                    f.write(f"file '{clip.absolute()}'\n")

            # Build command
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c", "copy",  # Copy streams, no re-encoding
                "-y",
                str(output_file.absolute())
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0 or not output_file.exists():
                return OperationResult(
                    success=False,
                    error=f"FFmpeg concat failed: {result.stderr}"
                )

            return OperationResult(success=True)

        finally:
            if os.path.exists(concat_file):
                os.unlink(concat_file)

    def _concatenate_with_reencode(self, clips: List[Path], output_file: Path) -> OperationResult:
        """
        Concatenate with re-encoding (slower, handles mixed formats).

        Uses filter_complex to concatenate video and audio streams.
        """
        # Build filter complex
        inputs = []
        filter_parts = []

        for i, clip in enumerate(clips):
            inputs.extend(["-i", str(clip.absolute())])

        # Build concat filter: n inputs -> v1/v1/a1/a1 outputs
        n = len(clips)
        filter_complex = f"{''.join([f'[{i}:v][{i}:a]' for i in range(n)])}concat=n={n}:v=1:a=1[outv][outa]"

        cmd = [
            "ffmpeg",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_file.absolute())
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0 or not output_file.exists():
            return OperationResult(
                success=False,
                error=f"FFmpeg reencode failed: {result.stderr}"
            )

        return OperationResult(success=True)


def main():
    """CLI for testing concatenation."""
    import argparse

    parser = argparse.ArgumentParser(description="Concatenate video clips")
    parser.add_argument("clips", nargs="+", help="Video clips to concatenate")
    parser.add_argument("--output", "-o", default="concatenated.mp4")
    parser.add_argument("--reencode", action="store_true", help="Re-encode during concatenation")

    args = parser.parse_args()

    op = ConcatenateVideos(clips=args.clips, output_name=args.output, reencode=args.reencode)

    result = op.execute(
        input_path=Path(args.clips[0]),
        output_dir=Path(args.output).parent,
        context={}
    )

    if result.success:
        print(f"Concatenated {result.data['clip_count']} clips")
        print(f"Output: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
