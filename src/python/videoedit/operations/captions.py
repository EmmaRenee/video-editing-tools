"""
Burn captions operation - Render subtitles into video.

Wraps the existing auto_caption.py functionality as a pipeline operation.
Supports multiple caption styles and formats.
"""
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class BurnCaptions(BaseOperation):
    """
    Burn SRT captions into video with styling.

    Uses FFmpeg with libass to render subtitles directly into video.
    Supports preset styles for different use cases.
    """

    name = "burn_captions"
    description = "Burn subtitles into video"
    inputs = ["video", "srt"]
    outputs = ["video"]

    # Caption style presets (from auto_caption.py)
    STYLES = {
        "automotive_racing": {
            "font": "Arial",
            "fontsize": 24,
            "fontcolor": "white",
            "borderstyle": 4,
            "bordercolor": "black",
            "borderw": 3,
            "shadowcolor": "black",
            "shadowx": 2,
            "shadowy": 2,
            "alignment": 2,
            "marginv": 50,
        },
        "clean_tech": {
            "font": "SF Pro Display",
            "fontsize": 22,
            "fontcolor": "white@0.95",
            "borderstyle": 1,
            "bordercolor": "black@0.5",
            "borderw": 2,
            "shadowcolor": "black",
            "shadowx": 1,
            "shadowy": 1,
            "alignment": 2,
            "marginv": 60,
        },
        "social_mobile": {
            "font": "Arial",
            "fontsize": 28,
            "fontcolor": "yellow",
            "borderstyle": 4,
            "bordercolor": "black",
            "borderw": 4,
            "shadowcolor": "black",
            "shadowx": 3,
            "shadowy": 3,
            "alignment": 2,
            "marginv": 80,
        },
        "vin_wiki": {
            "font": "Georgia",
            "fontsize": 26,
            "fontcolor": "white",
            "borderstyle": 3,
            "bordercolor": "#333333",
            "borderw": 3,
            "shadowcolor": "black",
            "shadowx": 2,
            "shadowy": 2,
            "alignment": 2,
            "marginv": 70,
        },
        "minimal": {
            "font": "Arial",
            "fontsize": 20,
            "fontcolor": "white",
            "borderstyle": 1,
            "bordercolor": "black",
            "borderw": 2,
            "shadowcolor": "black",
            "shadowx": 1,
            "shadowy": 1,
            "alignment": 2,
            "marginv": 50,
        }
    }

    def __init__(
        self,
        srt_file: str | None = None,
        style: str = "automotive_racing",
        style_overrides: Dict[str, Any] | None = None
    ):
        """
        Initialize burn captions operation.

        Args:
            srt_file: Path to SRT subtitle file (or use from context)
            style: Preset style name
            style_overrides: Override specific style parameters
        """
        super().__init__()
        self.srt_file = srt_file
        self.style_name = style
        self.style_overrides = style_overrides or {}

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute caption burning."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get SRT file
        srt_path = self._get_srt_path(context)
        if not srt_path or not srt_path.exists():
            return OperationResult(
                success=False,
                error=f"SRT file not found: {srt_path}"
            )

        # Get style
        style = self.STYLES.get(self.style_name, self.STYLES["automotive_racing"])
        style.update(self.style_overrides)

        # Output file
        output_file = output_dir / f"{input_path.stem}_captioned.mp4"

        # Use auto_caption module if available
        try:
            from ..auto_caption import burn_captions
            burn_captions(input_path, output_file, srt_path, self.style_name, "original", self.style_overrides)
            return OperationResult(
                success=True,
                output_path=output_file,
                data={"output_file": str(output_file)}
            )
        except ImportError:
            # Fallback to direct FFmpeg
            return self._burn_with_ffmpeg(input_path, output_file, srt_path, style)

    def _get_srt_path(self, context: Dict[str, Any]) -> Path | None:
        """Get SRT file path from parameter or context."""
        if self.srt_file:
            return Path(self.srt_file)

        # Check context for transcript file
        for key in ["transcript_file", "srt_file", "srt"]:
            if key in context:
                return Path(context[key])

        # Check for srt in context data
        if "srt" in context:
            return Path(context["srt"])

        return None

    def _burn_with_ffmpeg(self, input_path: Path, output_file: Path, srt_path: Path, style: Dict) -> OperationResult:
        """Burn captions using FFmpeg directly."""
        import tempfile
        import os

        # Convert SRT to ASS for better styling
        ass_content = self._srt_to_ass(srt_path, style)
        width, height = self._get_video_dimensions(input_path)

        # Write ASS to temp file (libass has issues with absolute paths)
        fd, ass_path = tempfile.mkstemp(suffix=".ass", text=True)
        os.close(fd)

        try:
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)

            # Build filter
            ass_filename = os.path.basename(ass_path)
            filter_complex = f"subtitles={ass_filename}"

            # Change to temp directory for libass
            original_dir = os.getcwd()
            ass_dir = os.path.dirname(ass_path)

            try:
                os.chdir(ass_dir)
                cmd = [
                    "ffmpeg",
                    "-i", str(input_path.absolute()),
                    "-vf", filter_complex,
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
                        error=f"FFmpeg failed: {result.stderr}"
                    )

                return OperationResult(
                    success=True,
                    output_path=output_file,
                    data={"output_file": str(output_file)}
                )
            finally:
                os.chdir(original_dir)
        finally:
            if os.path.exists(ass_path):
                os.unlink(ass_path)

    def _srt_to_ass(self, srt_path: Path, style: Dict) -> str:
        """Convert SRT to ASS format with styling."""
        import re

        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()

        # Parse SRT
        pattern = r"(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n*$)"
        matches = re.findall(pattern, srt_content, re.DOTALL)

        # Get video dimensions (default to 1920x1080)
        width, height = 1920, 1080

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{style['font']},{style['fontsize']},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,{style['borderstyle']},{style['borderw']},{style.get('shadowx',1)},2,0,0,{style['marginv']},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        for match in matches:
            idx, h1, m1, s1, ms1, h2, m2, s2, ms2, text = match
            start_time = f"{int(h1)}:{int(m1)}:{int(s1)}.{int(ms1)//10:02d}"
            end_time = f"{int(h2)}:{int(m2)}:{int(s2)}.{int(ms2)//10:02d}"

            text = text.replace("\n", "\\N")
            text = re.sub(r"<[^>]+>", "", text)

            ass_lines.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}")

        return "\n".join(ass_lines)

    def _get_video_dimensions(self, video_path: Path) -> tuple[int, int]:
        """Get video width and height using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])

        return 1920, 1080


def main():
    """CLI for testing caption burning."""
    import argparse

    parser = argparse.ArgumentParser(description="Burn captions into video")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--srt", required=True, help="SRT subtitle file")
    parser.add_argument("--style", default="automotive_racing", choices=list(BurnCaptions.STYLES.keys()))
    parser.add_argument("--output", "-o", help="Output file")

    args = parser.parse_args()

    op = BurnCaptions(
        srt_file=args.srt,
        style=args.style
    )

    output_dir = Path(args.output).parent if args.output else Path.cwd()
    output_name = args.output or f"{args.input}_captioned.mp4"

    result = op.execute(
        input_path=Path(args.input),
        output_dir=output_dir,
        context={}
    )

    if result.success:
        print(f"Captioned: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
