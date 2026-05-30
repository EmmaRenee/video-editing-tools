#!/usr/bin/env python3
"""Compatibility wrapper for the packaged videoedit caption tools."""

from __future__ import annotations

import argparse
from pathlib import Path

from videoedit.captions import STYLES, burn_captions, list_caption_styles


def batch_process(input_dir: Path, srt_dir: Path, output_dir: Path, style: str, format_type: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for video_file in sorted(input_dir.glob("*.mp4")):
        srt_file = srt_dir / video_file.with_suffix(".srt").name
        if not srt_file.exists():
            print(f"missing subtitles: {srt_file}")
            continue
        output_file = output_dir / f"{video_file.stem}_captioned.mp4"
        burn_captions(str(video_file), str(srt_file), str(output_file), style=style, format_type=format_type)
        print(f"wrote {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Burn SRT captions into video with videoedit styles")
    parser.add_argument("input", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("srt", nargs="?")
    parser.add_argument("--style", "-s", default="automotive_racing", choices=sorted(STYLES))
    parser.add_argument("--format", "-f", default="original", choices=["original", "reel", "youtube"])
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--list-styles", action="store_true")
    args = parser.parse_args()

    if args.list_styles:
        for item in list_caption_styles():
            print(f"{item['name']:20} {item['font']} {item['fontsize']}px")
        return

    if args.batch:
        if not args.input or not args.output:
            parser.error("--batch requires input and output directories")
        batch_process(Path(args.input), Path(args.srt or args.input), Path(args.output), args.style, args.format)
        return

    if not args.input or not args.output or not args.srt:
        parser.error("input, output, and srt files required unless using --batch")
    burn_captions(args.input, args.srt, args.output, style=args.style, format_type=args.format)


if __name__ == "__main__":
    main()
