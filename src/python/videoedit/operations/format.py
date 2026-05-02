"""
Format video operation - Resize, crop, and pad videos.

Supports common aspect ratios and resolutions for different platforms.
"""
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class FormatVideo(BaseOperation):
    """
    Format video for specific output requirements.

    Can resize, crop, pad, or scale videos to match target dimensions.
    Common presets for Reels (9:16), YouTube (16:9), and Square (1:1).
    """

    name = "format_video"
    description = "Resize, crop, or pad video"
    inputs = ["video"]
    outputs = ["video"]

    # Common format presets
    PRESETS = {
        "reel": {"aspect_ratio": "9:16", "resolution": "1080x1920"},
        "youtube": {"aspect_ratio": "16:9", "resolution": "1920x1080"},
        "square": {"aspect_ratio": "1:1", "resolution": "1080x1080"},
        "tiktok": {"aspect_ratio": "9:16", "resolution": "1080x1920"},
        "vertical": {"aspect_ratio": "9:16", "resolution": "1080x1920"},
        "horizontal": {"aspect_ratio": "16:9", "resolution": "1920x1080"},
    }

    def __init__(
        self,
        aspect_ratio: str = "16:9",
        resolution: str = "",
        crop: str = "center",  # center, top, bottom
        scale: str = "fit",  # fit, fill, stretch
        codec: str = "libx264",
        preset: str = "medium",
        crf: int = 23
    ):
        """
        Initialize format operation.

        Args:
            aspect_ratio: Target aspect ratio (e.g., "16:9", "9:16", "1:1")
            resolution: Target resolution (e.g., "1920x1080", "1080x1920")
            crop: How to crop when aspect differs
            scale: How to scale when size differs
            codec: Video codec
            preset: FFmpeg preset
            crf: Quality factor
        """
        super().__init__()
        self.aspect_ratio = aspect_ratio
        self.resolution = resolution
        self.crop = crop
        self.scale = scale
        self.codec = codec
        self.preset = preset
        self.crf = crf

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute format operation."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get target dimensions
        width, height = self._parse_resolution(self.aspect_ratio, self.resolution)
        if not width or not height:
            return OperationResult(
                success=False,
                error=f"Could not determine target dimensions from {self.resolution}"
            )

        # Build filter chain
        filters = self._build_filters(input_path, width, height)

        # Output file
        output_file = output_dir / f"{input_path.stem}_formatted.mp4"

        # Run FFmpeg
        cmd = [
            "ffmpeg", "-i", str(input_path),
            "-vf", filters,
            "-c:v", self.codec,
            "-preset", self.preset,
            "-crf", str(self.crf),
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_file)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0 or not output_file.exists():
            return OperationResult(
                success=False,
                error=f"FFmpeg failed: {result.stderr}"
            )

        return OperationResult(
            success=True,
            output_path=output_file,
            data={
                "output_file": str(output_file),
                "width": width,
                "height": height,
                "aspect_ratio": self.aspect_ratio
            }
        )

    def _parse_resolution(self, aspect_ratio: str, resolution: str) -> tuple[int, int]:
        """Parse resolution string or compute from aspect ratio."""
        if resolution:
            parts = resolution.split("x")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])

        # Compute from preset
        if aspect_ratio in self.PRESETS:
            preset = self.PRESETS[aspect_ratio]
            res = preset["resolution"]
            parts = res.split("x")
            return int(parts[0]), int(parts[1])

        # Parse aspect ratio like "16:9"
        if ":" in aspect_ratio:
            ar_parts = aspect_ratio.split(":")
            if len(ar_parts) == 2:
                w_ratio, h_ratio = int(ar_parts[0]), int(ar_parts[1])
                # Default to 1080 height for horizontal, width for vertical
                if w_ratio > h_ratio:
                    return 1920, 1080
                else:
                    return 1080, 1920

        return 0, 0

    def _build_filters(self, input_path: Path, target_width: int, target_height: int) -> str:
        """Build FFmpeg filter chain."""
        filters = []

        ar_parts = self.aspect_ratio.split(":")
        if len(ar_parts) == 2:
            ar_num, ar_den = int(ar_parts[0]), int(ar_parts[1])
        else:
            ar_num, ar_den = 16, 9

        # For vertical (9:16), center crop the video
        if ar_num < ar_den:
            # Crop to vertical from center
            filters.append(f"crop=ih*{ar_num}/{ar_den}:ih:(iw-ih*{ar_num}/{ar_den})/2:0")
            filters.append(f"scale={target_width}:{target_height}")
        else:
            # For horizontal (16:9), scale to fit then pad
            filters.append(f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease")
            filters.append(f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2")

        return ",".join(filters)


def main():
    """CLI for testing format."""
    import argparse

    parser = argparse.ArgumentParser(description="Format video")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--aspect-ratio", "-a", default="16:9",
                       choices=["16:9", "9:16", "1:1", "reel", "youtube", "square", "tiktok"])
    parser.add_argument("--resolution", "-r", help="Target resolution (e.g., 1920x1080)")
    parser.add_argument("--output", "-o", help="Output file")

    args = parser.parse_args()

    op = FormatVideo(
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution or ""
    )

    output_dir = Path(args.output).parent if args.output else Path.cwd()
    output_name = args.output or f"{args.input}_formatted.mp4"

    result = op.execute(
        input_path=Path(args.input),
        output_dir=output_dir,
        context={}
    )

    if result.success:
        print(f"Formatted: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
