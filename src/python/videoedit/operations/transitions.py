"""
Transitions operation - Add crossfade transitions between video clips.

Uses FFmpeg xfade filter to create smooth transitions between clips.
Supports multiple transition types and durations.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult


class AddCrossfades(BaseOperation):
    """
    Add crossfade transitions between video clips.

    Uses FFmpeg's xfade filter which supports various transition
    types including fade, dissolve, wipe, and more.
    """

    name = "add_crossfades"
    description = "Add crossfade transitions between clips"
    inputs = ["video_clips"]
    outputs = ["video"]

    # Available transition types
    TRANSITION_TYPES = [
        "fade",           # Simple fade
        "dissolve",       # Dissolve transition
        "distortion",     # Distortion effect
        "wipeleft",       # Wipe from right to left
        "wiperight",      # Wipe from left to right
        "wipeup",         # Wipe from bottom to top
        "wipedown",       # Wipe from top to bottom
        "slidedown",      # Slide down
        "slideup",        # Slide up
    ]

    def __init__(
        self,
        clips: List[str] | None = None,
        duration: float = 0.5,
        transition: str = "fade",
        output_name: str = "with_transitions.mp4"
    ):
        """
        Initialize crossfades operation.

        Args:
            clips: List of clip file paths (or use from context)
            duration: Transition duration in seconds
            transition: Type of transition (fade, dissolve, etc.)
            output_name: Name for output file
        """
        super().__init__()
        self.clips = clips
        self.duration = duration
        self.transition = transition.lower()
        self.output_name = output_name

        if self.transition not in self.TRANSITION_TYPES:
            self.transition = "fade"

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute crossfade transitions."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get clips
        clips = self._get_clips(context)
        if not clips:
            return OperationResult(
                success=False,
                error="No clips found"
            )

        if len(clips) < 2:
            return OperationResult(
                success=False,
                error=f"Need at least 2 clips for transitions, got {len(clips)}"
            )

        # Validate clips exist
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

        # Build filter complex and execute
        result = self._apply_crossfades(clip_paths, output_file)

        if not result.success:
            return result

        return OperationResult(
            success=True,
            output_path=output_file,
            data={
                "output_file": str(output_file),
                "clip_count": len(clip_paths),
                "transition_count": len(clip_paths) - 1,
                "duration": self.duration,
                "transition": self.transition
            }
        )

    def _get_clips(self, context: Dict[str, Any]) -> List[Path]:
        """Get clips from parameter or context."""
        if self.clips:
            return [Path(c) for c in self.clips]

        # Try to get from context
        clips = []

        if "clips" in context:
            clips = context["clips"]
        elif "segments" in context:
            for seg in context["segments"]:
                if "output_path" in seg:
                    clips.append(seg["output_path"])

        return [Path(c) for c in clips] if clips else []

    def _apply_crossfades(self, clips: List[Path], output_file: Path) -> OperationResult:
        """
        Apply crossfades using FFmpeg xfade filter.

        For N clips, we need N-1 transitions. The filter complex
        chains them together: clip0 + clip1 -> out0, out0 + clip2 -> out1, etc.
        """
        # Get clip durations using ffprobe
        durations = []
        for clip in clips:
            dur = self._get_duration(clip)
            if dur is None:
                return OperationResult(
                    success=False,
                    error=f"Could not get duration for: {clip}"
                )
            durations.append(dur)

        # Build filter complex
        inputs = []
        filter_parts = []
        current_stream = None

        for i, (clip, duration) in enumerate(zip(clips, durations)):
            inputs.extend(["-i", str(clip.absolute())])

            if i == 0:
                # First clip - get its stream, trim by transition duration
                # We need to trim the end by transition duration for the first clip
                # Actually for xfade we need to offset the second clip
                continue
            else:
                # Subsequent clips
                prev_idx = i - 1

                # Calculate offsets for xfade
                # First clip: show from 0 to (duration - transition)
                # Second clip: show from transition to duration
                first_offset = durations[prev_idx] - self.duration
                second_offset = self.duration

                # xfade filter
                if current_stream is None:
                    # First transition: [0:v][1:v]
                    in_a = f"[0:v]"
                    in_b = f"[1:v]"
                else:
                    # Subsequent transitions: use previous output
                    in_a = current_stream
                    in_b = f"[{i}:v]"

                out_name = f"v{i}"
                xfade_filter = (
                    f"{in_a}{in_b}"
                    f"xfade=transition={self.transition}:"
                    f"duration={self.duration}:"
                    f"offset={first_offset}"
                    f"[{out_name}]"
                )
                filter_parts.append(xfade_filter)
                current_stream = f"[{out_name}]"

        # Also need to handle audio - concatenate audio streams
        audio_filter = self._build_audio_filter(len(clips))

        # Build command
        filter_complex = ";".join(filter_parts) + ";" + audio_filter

        cmd = [
            "ffmpeg",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[v{len(clips)-1}]",  # Use last video output
            "-map", "[audioout]",           # Use concatenated audio
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
                error=f"FFmpeg xfade failed: {result.stderr}"
            )

        return OperationResult(success=True)

    def _build_audio_filter(self, num_clips: int) -> str:
        """Build audio concat filter."""
        # Concatenate all audio inputs
        inputs = "".join([f"[{i}:a]" for i in range(num_clips)])
        return f"{inputs}concat=n={num_clips}:v=0:a=1[audioout]"

    def _get_duration(self, video_path: Path) -> float | None:
        """Get video duration using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass

        return None


class SimpleCrossfade(BaseOperation):
    """
    Simple crossfade between two clips.

    Simplified version for just two clips with easier configuration.
    """

    name = "simple_crossfade"
    description = "Crossfade between two clips"
    inputs = ["video_clips"]
    outputs = ["video"]

    def __init__(
        self,
        clip1: str | None = None,
        clip2: str | None = None,
        duration: float = 1.0,
        output_name: str = "crossfaded.mp4"
    ):
        """
        Initialize simple crossfade.

        Args:
            clip1: First clip path
            clip2: Second clip path
            duration: Crossfade duration in seconds
            output_name: Output file name
        """
        super().__init__()
        self.clip1 = clip1
        self.clip2 = clip2
        self.duration = duration
        self.output_name = output_name

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute simple crossfade."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get clips
        clips = self._get_clips(context)
        if len(clips) < 2:
            return OperationResult(
                success=False,
                error="Need at least 2 clips for crossfade"
            )

        clip1_path = Path(self.clip1) if self.clip1 else clips[0]
        clip2_path = Path(self.clip2) if self.clip2 else clips[1]

        if not clip1_path.exists() or not clip2_path.exists():
            return OperationResult(
                success=False,
                error="One or both clips not found"
            )

        output_file = output_dir / self.output_name

        # Get first clip duration
        duration1 = self._get_duration(clip1_path)
        if duration1 is None:
            return OperationResult(
                success=False,
                error=f"Could not get duration for: {clip1_path}"
            )

        # Calculate offset
        offset = duration1 - self.duration

        # Build command
        cmd = [
            "ffmpeg",
            "-i", str(clip1_path.absolute()),
            "-i", str(clip2_path.absolute()),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={self.duration}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={self.duration}[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_file.absolute())
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0 or not output_file.exists():
            return OperationResult(
                success=False,
                error=f"FFmpeg crossfade failed: {result.stderr}"
            )

        return OperationResult(
            success=True,
            output_path=output_file,
            data={
                "output_file": str(output_file),
                "duration": self.duration
            }
        )

    def _get_clips(self, context: Dict[str, Any]) -> List[Path]:
        """Get clips from context."""
        clips = []

        if "clips" in context:
            clips = context["clips"]
        elif "segments" in context:
            for seg in context["segments"]:
                if "output_path" in seg:
                    clips.append(seg["output_path"])

        return [Path(c) for c in clips] if clips else []

    def _get_duration(self, video_path: Path) -> float | None:
        """Get video duration using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass

        return None


def main():
    """CLI for testing transitions."""
    import argparse

    parser = argparse.ArgumentParser(description="Add crossfade transitions")
    parser.add_argument("clips", nargs="+", help="Video clips to transition between")
    parser.add_argument("--duration", type=float, default=0.5, help="Transition duration")
    parser.add_argument("--transition", default="fade",
                        choices=AddCrossfades.TRANSITION_TYPES)
    parser.add_argument("--output", "-o", default="with_transitions.mp4")
    parser.add_argument("--simple", action="store_true", help="Use simple crossfade (2 clips only)")

    args = parser.parse_args()

    if args.simple or len(args.clips) == 2:
        op = SimpleCrossfade(clip1=args.clips[0], clip2=args.clips[1],
                            duration=args.duration, output_name=args.output)
    else:
        op = AddCrossfades(clips=args.clips, duration=args.duration,
                          transition=args.transition, output_name=args.output)

    result = op.execute(
        input_path=Path(args.clips[0]),
        output_dir=Path(args.output).parent,
        context={}
    )

    if result.success:
        print(f"Created video with transitions")
        print(f"Output: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
