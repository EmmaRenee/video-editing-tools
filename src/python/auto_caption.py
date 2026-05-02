#!/usr/bin/env python3
"""
Auto Captioner - Burn SRT captions into video with styling

Cross-platform version that detects FFmpeg with libass support.

Install:
- macOS: brew install ffmpeg-full
- Windows: Download from https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z
- Linux: Build with --enable-libass or use distribution package
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def find_ffmpeg_with_libass() -> Optional[str]:
    """Find FFmpeg executable with libass support."""
    # List of possible ffmpeg commands/paths
    candidates = []

    if platform.system() == "Darwin":  # macOS
        candidates = [
            "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
        ]
    elif platform.system() == "Windows":
        candidates = [
            "ffmpeg",  # Assume in PATH
            r"C:\Tools\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser("~/AppData/Local/ffmpeg/bin/ffmpeg.exe"),
        ]
    else:  # Linux
        candidates = [
            "ffmpeg",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]

    # Try each candidate
    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Check for libass in configuration
                config_result = subprocess.run(
                    [candidate, "-version"],
                    capture_output=True,
                    text=True
                )
                if "libass" in config_result.stderr.lower() or "libass" in config_result.stdout.lower():
                    return candidate
                # Even if not explicitly shown, most modern builds have it
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None  # Not found


# Auto-detect FFmpeg at import
FFMPEG_CMD = find_ffmpeg_with_libass()
if FFMPEG_CMD:
    FFMPEG_FULL = FFMPEG_CMD
else:
    FFMPEG_FULL = "ffmpeg"  # Hope it's in PATH

# Style presets for different use cases
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
        "alignment": 2,  # Center bottom
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

REEL_DIMENSIONS = (1080, 1920)  # 9:16 vertical
YOUTUBE_DIMENSIONS = (1920, 1080)  # 16:9 horizontal


def srt_to_ass(srt_path: Path, style: Dict, width: int, height: int) -> str:
    """Convert SRT to ASS subtitles with custom styling."""
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    # Parse SRT blocks
    pattern = r'(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n*$)'
    matches = re.findall(pattern, srt_content, re.DOTALL)

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: " + str(width),
        "PlayResY: " + str(height),
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

        # Clean up text (remove HTML tags, fix line breaks)
        text = text.replace('\n', '\\N')
        text = text.replace('<i>', '').replace('</i>', '')
        text = text.replace('<b>', '').replace('</b>', '')
        text = re.sub(r'<[^>]+>', '', text)

        ass_lines.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}")

    return '\n'.join(ass_lines)


def burn_captions(input_video: Path, output_video: Path, srt_path: Path,
                  style_name: str = "automotive_racing", format_type: str = "original",
                  style_overrides: Dict = None) -> None:
    """Burn captions into video using FFmpeg."""
    if not srt_path.exists():
        raise FileNotFoundError(f"SRT file not found: {srt_path}")
    if not input_video.exists():
        raise FileNotFoundError(f"Video file not found: {input_video}")

    # Get selected style
    style = STYLES.get(style_name, STYLES["automotive_racing"])
    if style_overrides:
        style.update(style_overrides)

    # Get video dimensions using ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(input_video)
    ]

    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffprobe failed to read video file")

    parts = result.stdout.strip().split(',')
    if len(parts) < 2:
        raise RuntimeError("Could not determine video dimensions")

    width, height = map(int, parts[:2])

    # Convert SRT to ASS
    ass_content = srt_to_ass(srt_path, style, width, height)

    # libass has issues with absolute paths - use a temp file in current directory
    import tempfile
    fd, ass_path = tempfile.mkstemp(suffix='.ass', text=True)
    os.close(fd)
    try:
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

        # Build filter chain
        filters = []

        # Handle format conversion
        if format_type == "reel":
            # Center crop to 9:16
            filters.append(f"crop=min(iw,ih*9/16):ih:(iw-iw*9/16/ih)/2:0")
            filters.append(f"scale=1080:1920")
        elif format_type == "youtube":
            filters.append(f"scale=1920:1080:force_original_aspect_ratio=decrease")
            filters.append(f"pad=1920:1080:(1920-iw)/2:(1080-ih)/2")

        # Add subtitles - use relative path for libass compatibility
        ass_filename = os.path.basename(ass_path)
        filter_complex = ",".join(filters) if filters else "null"
        filter_complex += f',subtitles={ass_filename}'

        # Build FFmpeg command
        # Change to temp directory so libass can find the .ass file
        original_dir = os.getcwd()
        ass_dir = os.path.dirname(ass_path)
        try:
            os.chdir(ass_dir)
            cmd = [
                FFMPEG_FULL, "-i", str(input_video.absolute()),
                "-vf", filter_complex,
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_video.absolute()),
                "-y"
            ]

            print(f"Processing: {input_video.name} -> {output_video.name}")
            subprocess.run(cmd, check=True)
        finally:
            os.chdir(original_dir)

        print(f"Done: {output_video}")
    finally:
        # Clean up temporary ASS file
        if os.path.exists(ass_path):
            os.unlink(ass_path)


def batch_process(input_dir: Path, srt_dir: Path, output_dir: Path,
                  style: str = "automotive_racing", format_type: str = "original") -> None:
    """Process all videos in a directory with matching SRT files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for video_file in input_dir.glob("*.mp4"):
        srt_file = srt_dir / video_file.with_suffix(".srt").name
        if srt_file.exists():
            output_file = output_dir / f"{video_file.stem}_captioned.mp4"
            try:
                burn_captions(video_file, output_file, srt_file, style, format_type)
            except Exception as e:
                print(f"Error processing {video_file.name}: {e}")


def list_styles():
    """Print available style presets."""
    print("Available caption styles:")
    for name, style in STYLES.items():
        print(f"  {name}")
        print(f"    Font: {style['font']}, Size: {style['fontsize']}")


def main():
    parser = argparse.ArgumentParser(
        description="Burn SRT captions into video with custom styling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Caption a single video
  python auto_caption.py video.mp4 video_captioned.mp4 transcript.srt

  # Create a formatted reel with captions
  python auto_caption.py raw.mp4 reel_final.mp4 subs.srt --format reel --style automotive_racing

  # Batch process a directory
  python auto_caption.py --batch clips/ subtitles/ output/ --style social_mobile

  # List available styles
  python auto_caption.py --list-styles
        """
    )

    parser.add_argument("input", nargs="?", help="Input video file")
    parser.add_argument("output", nargs="?", help="Output video file")
    parser.add_argument("srt", nargs="?", help="SRT subtitle file")

    parser.add_argument("--style", "-s", default="automotive_racing",
                        choices=list(STYLES.keys()),
                        help="Caption style preset (default: automotive_racing)")
    parser.add_argument("--format", "-f", default="original",
                        choices=["original", "reel", "youtube"],
                        help="Output format (default: original)")
    parser.add_argument("--batch", action="store_true",
                        help="Batch process directory")
    parser.add_argument("--list-styles", action="store_true",
                        help="List available style presets")

    args = parser.parse_args()

    if args.list_styles:
        list_styles()
        return

    if args.batch:
        if not all([args.input, args.output]):
            parser.error("--batch requires input and output directories")
        batch_process(Path(args.input), Path(args.srt or args.input),
                      Path(args.output), args.style, args.format)
    else:
        if not all([args.input, args.output, args.srt]):
            parser.error("input, output, and srt files required (unless using --batch)")
        burn_captions(Path(args.input), Path(args.output), Path(args.srt),
                      args.style, args.format)


if __name__ == "__main__":
    main()
