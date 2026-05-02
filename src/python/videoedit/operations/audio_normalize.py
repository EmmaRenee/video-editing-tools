"""
Audio normalization operation - Normalize audio levels using EBU R128.

Uses FFmpeg loudnorm filter for broadcast-standard loudness normalization.
Supports various target levels and loudness standards.
"""
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class NormalizeAudio(BaseOperation):
    """
    Normalize audio to target loudness level.

    Uses FFmpeg's loudnorm filter which implements EBU R128 standard
    for consistent loudness across different content.
    """

    name = "normalize_audio"
    description = "Normalize audio to target loudness"
    inputs = ["video"]
    outputs = ["video"]

    # EBU R128 recommended values
    TARGET_LEVELS = {
        "ebu": -16,      # EBU R128 (Europe)
        "atsc": -24,     # ATSC A/85 (US)
        "podcast": -16,  # Podcast standard
        "youtube": -14,   # YouTube recommended
        "spotify": -14,   # Spotify standard
    }

    def __init__(
        self,
        target_level: float = -16,
        true_peak: float = -1.5,
        lra: float = 11.0,
        preset: str | None = None
    ):
        """
        Initialize audio normalization operation.

        Args:
            target_level: Target integrated loudness in LUFS (default: -16 for EBU)
            true_peak: Maximum true peak in dBTP (default: -1.5)
            lra: Loudness range target in LU (default: 11.0)
            preset: Named preset (ebu, atsc, podcast, youtube, spotify)
        """
        super().__init__()

        if preset:
            preset = preset.lower()
            if preset in self.TARGET_LEVELS:
                target_level = self.TARGET_LEVELS[preset]

        self.target_level = target_level
        self.true_peak = true_peak
        self.lra = lra

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute audio normalization."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"{input_path.stem}_normalized.mp4"

        # Build loudnorm filter
        filter_args = f"I={self.target_level}:TP={self.true_peak}:LRA={self.lra}"
        audio_filter = f"loudnorm={filter_args}"

        cmd = [
            "ffmpeg",
            "-i", str(input_path.absolute()),
            "-af", audio_filter,
            "-c:v", "copy",  # Copy video stream without changes
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-y",
            str(output_file.absolute())
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0 or not output_file.exists():
            return OperationResult(
                success=False,
                error=f"FFmpeg loudnorm failed: {result.stderr}"
            )

        return OperationResult(
            success=True,
            output_path=output_file,
            data={
                "output_file": str(output_file),
                "target_lufs": self.target_level,
                "true_peak": self.true_peak,
                "lra": self.lra
            }
        )


def main():
    """CLI for testing audio normalization."""
    import argparse

    parser = argparse.ArgumentParser(description="Normalize audio loudness")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--output", "-o", help="Output file")
    parser.add_argument("--level", type=float, default=-16, help="Target LUFS (default: -16)")
    parser.add_argument("--preset", choices=list(NormalizeAudio.TARGET_LEVELS.keys()),
                        help="Use a named preset")

    args = parser.parse_args()

    op = NormalizeAudio(target_level=args.level, preset=args.preset)

    output_dir = Path(args.output).parent if args.output else Path.cwd()
    output_name = args.output or f"{args.input}_normalized.mp4"

    result = op.execute(
        input_path=Path(args.input),
        output_dir=output_dir,
        context={}
    )

    if result.success:
        print(f"Normalized audio to {result.data['target_lufs']} LUFS")
        print(f"Output: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
