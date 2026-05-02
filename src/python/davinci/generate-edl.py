#!/usr/bin/env python3
"""
generate-edl.py - Convert Claude highlight selections to DaVinci Resolve EDL

Converts JSON output from Claude analysis into EDL/XML files that can be
imported directly into DaVinci Resolve for final editing.

Usage:
    echo '{"source":"video.mp4","clips":[{"start":"00:00:10","end":"00:00:30","label":"overtake"}]}' | python generate-edl.py
    python generate-edl.py highlights.json --output race_reels.edl
"""

import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional


def timecode_to_seconds(tc: str) -> float:
    """Convert HH:MM:SS or HH:MM:SS.mmm to seconds."""
    parts = tc.split(':')
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 4:
        hours, minutes, seconds, frames = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return float(tc)


def seconds_to_timecode(seconds: float, fps: float = 30) -> str:
    """Convert seconds to HH:MM:SS:FF timecode format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    frames = int(round((seconds - int(seconds)) * fps)) % int(fps)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def seconds_to_framerange(seconds: float, fps: float = 30) -> str:
    """Convert seconds to EDL framerange (HH:MM:SS:FF format)."""
    return seconds_to_timecode(seconds, fps)


def generate_edl(clips: List[Dict], source_file: str, fps: float = 30) -> str:
    """
    Generate EDL (Edit Decision List) format.

    EDL format reference:
    - Line 1: Edit number (001)
    - Line 2: Clip name (source file)
    - Line 3: Edit type (C = cut)
    - Line 4: Source IN and OUT timecodes
    - Line 5: Record IN and OUT timecodes (timeline position)
    """
    lines = []
    lines.append("TITLE: Video Editing Export")
    lines.append("")

    timeline_start = 0  # Start position on timeline

    for i, clip in enumerate(clips, 1):
        label = clip.get('label', f'Clip_{i:03d}')
        start_tc = timecode_to_seconds(clip['start'])
        end_tc = timecode_to_seconds(clip['end'])
        duration = end_tc - start_tc

        # Calculate timeline position
        timeline_end = timeline_start + duration

        # Format timecodes
        source_in = seconds_to_framerange(start_tc, fps)
        source_out = seconds_to_framerange(end_tc, fps)
        record_in = seconds_to_framerange(timeline_start, fps)
        record_out = seconds_to_framerange(timeline_end, fps)

        # EDL entry
        lines.append(f"{i:03d}  {label}     C")
        lines.append(f"{source_in} {source_out} {record_in} {record_out}")
        lines.append(f"")
        lines.append(f"* FROM CLIP NAME: {source_file}")
        lines.append("")

        timeline_start = timeline_end

    return "\n".join(lines)


def generate_m3u(clips: List[Dict], source_file: str) -> str:
    """Generate M3U playlist for FFmpeg concatenation."""
    lines = ["#EXTM3U"]

    for clip in clips:
        start = clip['start']
        end = clip['end']
        lines.append(f"#EXTINF:{clip.get('duration', '')},{clip.get('label', '')}")
        lines.append(f"#EXTVLCOPT:start-time={start}")
        lines.append(f"#EXTVLCOPT:stop-time={end}")
        lines.append(source_file)

    return "\n".join(lines)


def generate_ffmpeg_concat(clips: List[Dict], source_file: str, output_dir: Path) -> tuple[str, List[str]]:
    """
    Generate FFmpeg concat list and extraction commands.

    Returns: (concat_content, extraction_commands)
    """
    concat_lines = []
    extraction_commands = []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, clip in enumerate(clips, 1):
        label = clip.get('label', f'clip_{i:03d}')
        safe_label = re.sub(r'[^\w-]', '_', label)
        output_file = output_dir / f"{safe_label}.mp4"

        start = clip['start']
        end = clip['end']

        # Add to concat list
        concat_lines.append(f"file '{output_file.absolute()}'")

        # Generate extraction command
        cmd = f"ffmpeg -i \"{source_file}\" -ss {start} -to {end} -c copy \"{output_file}\""
        extraction_commands.append(cmd)

    return "\n".join(concat_lines), extraction_commands


def generate_xml(clips: List[Dict], source_file: str, fps: float = 30) -> str:
    """
    Generate FCPXML (Final Cut Pro XML) for better DaVinci compatibility.

    FCPXML has better metadata support than EDL.
    """
    timeline_start = 0
    duration_frames = 0

    # Calculate total duration
    for clip in clips:
        start = timecode_to_seconds(clip['start'])
        end = timecode_to_seconds(clip['end'])
        duration_frames += int((end - start) * fps)

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <sequence id="Claude Highlights">
    <name>Claude Generated Edit</name>
    <duration>{duration_frames}</duration>
    <rate>
      <timebase>{int(fps)}</timebase>
      <ntsc>FALSE</ntsc>
    </rate>
    <media>
      <video>
        <format>
          <samplecharacteristics>
            <rate>
              <timebase>{int(fps)}</timebase>
              <ntsc>FALSE</ntsc>
            </rate>
            <width>1920</width>
            <height>1080</height>
          </samplecharacteristics>
        </format>
        <track>
'''

    for i, clip in enumerate(clips, 1):
        label = clip.get('label', f'Clip_{i:03d}')
        start = timecode_to_seconds(clip['start'])
        end = timecode_to_seconds(clip['end'])
        clip_start_frame = int(start * fps)
        clip_duration_frames = int((end - start) * fps)

        xml += f'''          <generatoritem>
            <name>{label}</name>
            <duration>{clip_duration_frames}</duration>
            <start>{timeline_start}</start>
            <enabled>TRUE</enabled>
            <source>
              <path>{source_file}</path>
            </source>
            <rate>
              <timebase>{int(fps)}</timebase>
            </rate>
            <in>{clip_start_frame}</in>
            <out>{clip_start_frame + clip_duration_frames}</out>
          </generatoritem>
'''
        timeline_start += clip_duration_frames

    xml += '''        </track>
      </video>
    </media>
  </sequence>
</xmeml>'''

    return xml


def main():
    parser = argparse.ArgumentParser(description='Generate EDL/XML from Claude highlight JSON')
    parser.add_argument('input', nargs='?', type=Path, help='JSON input file (or stdin)')
    parser.add_argument('--output', '-o', type=Path, help='Output file (default: stdout)')
    parser.add_argument('--format', '-f', choices=['edl', 'xml', 'm3u', 'ffmpeg', 'all'],
                        default='all', help='Output format')
    parser.add_argument('--fps', type=float, default=30, help='Frame rate for timecode (default: 30)')
    parser.add_argument('--extract', action='store_true',
                        help='Extract clips with FFmpeg (requires ffmpeg concat format)')

    args = parser.parse_args()

    # Read input JSON
    if args.input and args.input.exists():
        data = json.loads(args.input.read_text())
    elif not sys.stdin.isatty():
        data = json.loads(sys.stdin.read())
    else:
        # Interactive prompt
        print("Enter JSON (press Ctrl+D when done):")
        data = json.loads(sys.stdin.read())

    if not data:
        print("Error: No input data provided", file=sys.stderr)
        sys.exit(1)

    # Support both direct list and wrapped object
    clips = data if isinstance(data, list) else data.get('clips', [])
    source_file = data.get('source', 'source.mp4') if isinstance(data, dict) else 'source.mp4'

    if not clips:
        print("Error: No clips found in input", file=sys.stderr)
        sys.exit(1)

    # Determine output directory
    if args.output:
        output_dir = args.output.parent
        base_name = args.output.stem
    else:
        output_dir = Path('.')
        base_name = 'highlights'

    # Generate outputs
    if args.format in ['edl', 'all']:
        edl_content = generate_edl(clips, source_file, args.fps)
        edl_path = output_dir / f"{base_name}.edl"
        edl_path.write_text(edl_content)
        print(f"EDL written to: {edl_path}")

    if args.format in ['xml', 'all']:
        xml_content = generate_xml(clips, source_file, args.fps)
        xml_path = output_dir / f"{base_name}.xml"
        xml_path.write_text(xml_content)
        print(f"XML written to: {xml_path}")

    if args.format in ['m3u', 'all']:
        m3u_content = generate_m3u(clips, source_file)
        m3u_path = output_dir / f"{base_name}.m3u"
        m3u_path.write_text(m3u_content)
        print(f"M3U written to: {m3u_path}")

    if args.format in ['ffmpeg', 'all'] or args.extract:
        clips_dir = output_dir / 'clips'
        concat_content, commands = generate_ffmpeg_concat(clips, source_file, clips_dir)

        concat_path = output_dir / 'concat.txt'
        concat_path.write_text(concat_content)
        print(f"Concat list written to: {concat_path}")

        # Write extraction script
        script_path = output_dir / 'extract_clips.sh'
        script_path.write_text('#!/bin/bash\n' + '\n'.join(commands) + '\n')
        script_path.chmod(0o755)
        print(f"Extraction script written to: {script_path}")

        # Also print the final ffmpeg concat command
        print(f"\nTo concatenate clips:")
        print(f"ffmpeg -f concat -safe 0 -i {concat_path} -c copy {base_name}_assembled.mp4")

        if args.extract:
            print("\nExtracting clips...")
            for cmd in commands:
                os.system(cmd)
            print(f"Clips extracted to: {clips_dir}/")


if __name__ == '__main__':
    main()
