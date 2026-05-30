"""Styled caption rendering helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .ffmpeg import probe_media, run_command_check


STYLES: dict[str, dict[str, Any]] = {
    "automotive_racing": {
        "font": "Arial",
        "fontsize": 24,
        "fontcolor": "white",
        "borderstyle": 4,
        "bordercolor": "black",
        "borderw": 3,
        "shadowx": 2,
        "shadowy": 2,
        "alignment": 2,
        "marginv": 50,
    },
    "clean_tech": {
        "font": "SF Pro Display",
        "fontsize": 22,
        "fontcolor": "white",
        "borderstyle": 1,
        "bordercolor": "black",
        "borderw": 2,
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
        "shadowx": 1,
        "shadowy": 1,
        "alignment": 2,
        "marginv": 50,
    },
}

FORMAT_DIMENSIONS = {
    "reel": (1080, 1920),
    "youtube": (1920, 1080),
}


def list_caption_styles() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "font": style["font"],
            "fontsize": style["fontsize"],
            "marginv": style["marginv"],
        }
        for name, style in sorted(STYLES.items())
    ]


def srt_to_ass(srt_path: str | Path, style_name: str = "automotive_racing", width: int = 1920, height: int = 1080) -> str:
    style = dict(STYLES.get(style_name, STYLES["automotive_racing"]))
    content = Path(srt_path).read_text(encoding="utf-8")
    pattern = (
        r"(\d+)\s*\n"
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n"
        r"(.*?)(?=\n\s*\n|\Z)"
    )
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{style['font']},{style['fontsize']},&H00FFFFFF,&H000000FF,"
            f"&H00000000,&H00000000,0,0,0,0,100,100,0,0,{style['borderstyle']},"
            f"{style['borderw']},{style.get('shadowx', 1)},{style.get('alignment', 2)},"
            f"0,0,{style['marginv']},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for match in re.findall(pattern, content, re.DOTALL):
        _idx, h1, m1, s1, ms1, h2, m2, s2, ms2, text = match
        start = f"{int(h1)}:{int(m1):02d}:{int(s1):02d}.{int(ms1) // 10:02d}"
        end = f"{int(h2)}:{int(m2):02d}:{int(s2):02d}.{int(ms2) // 10:02d}"
        clean = _clean_subtitle_text(text)
        ass_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{clean}")
    return "\n".join(ass_lines) + "\n"


def burn_captions(
    input_video: str,
    subtitles: str,
    output: str,
    style: str = "automotive_racing",
    format_type: str = "original",
) -> str:
    input_video = os.fspath(input_video)
    subtitles = os.fspath(subtitles)
    output = os.fspath(output)
    if style not in STYLES:
        raise ValueError(f"unknown caption style: {style}")
    if format_type not in {"original", "reel", "youtube"}:
        raise ValueError(f"unknown caption format: {format_type}")
    if not os.path.exists(subtitles):
        raise FileNotFoundError(f"subtitle file not found: {subtitles}")
    asset = probe_media(input_video)
    width = asset.width or 1920
    height = asset.height or 1080
    filters = _format_filters(format_type)
    with tempfile.TemporaryDirectory(prefix="videoedit-captions-") as tmp:
        subtitle_path = subtitles
        if os.path.splitext(subtitles)[1].lower() == ".srt":
            if format_type in FORMAT_DIMENSIONS:
                width, height = FORMAT_DIMENSIONS[format_type]
            subtitle_path = os.path.join(tmp, "captions.ass")
            with open(subtitle_path, "w", encoding="utf-8") as handle:
                handle.write(srt_to_ass(subtitles, style_name=style, width=width, height=height))
        filters.append(f"subtitles={_escape_filter_path(subtitle_path)}")
        run_command_check(
            [
                "ffmpeg",
                "-i",
                input_video,
                "-vf",
                ",".join(filters),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                output,
                "-y",
            ]
        )
    return output


def _format_filters(format_type: str) -> list[str]:
    if format_type == "reel":
        return ["crop=min(iw\\,ih*9/16):ih:(iw-min(iw\\,ih*9/16))/2:0", "scale=1080:1920"]
    if format_type == "youtube":
        return ["scale=1920:1080:force_original_aspect_ratio=decrease", "pad=1920:1080:(1920-iw)/2:(1080-ih)/2"]
    return []


def _clean_subtitle_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"</?(i|b|u)>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\n", r"\N")
    text = text.replace("{", r"\{").replace("}", r"\}")
    return text


def _escape_filter_path(path: str) -> str:
    value = os.path.abspath(path)
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
