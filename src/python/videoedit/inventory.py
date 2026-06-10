"""Inventory scanner and report writers."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from .ffmpeg import probe_media, scan_video_files
from .models import MediaAsset
from .timecode import seconds_to_hhmmss


logger = logging.getLogger(__name__)


def build_inventory(directory: str, timeout: int = 60) -> list[MediaAsset]:
    items: list[MediaAsset] = []
    for path in scan_video_files(directory):
        try:
            items.append(probe_media(path, timeout=timeout))
        except Exception as exc:
            logger.warning("Skipping media probe failure for %s: %s", path, exc)
    return items


def inventory_payload(items: list[MediaAsset]) -> dict:
    return {
        "generated": datetime.now().isoformat(),
        "count": len(items),
        "total_duration": sum(item.duration or 0 for item in items),
        "videos": [item.to_dict() for item in items],
    }


def write_inventory_outputs(items: list[MediaAsset], output_base: str) -> None:
    output_base = os.fspath(output_base)
    parent = os.path.dirname(output_base)
    if parent:
        os.makedirs(parent, exist_ok=True)
    write_inventory_json(items, _with_suffix(output_base, ".json"))
    write_inventory_csv(items, _with_suffix(output_base, ".csv"))
    write_inventory_markdown(items, _with_suffix(output_base, ".md"))


def write_inventory_json(items: list[MediaAsset], output: str) -> None:
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(inventory_payload(items), indent=2))


def write_inventory_csv(items: list[MediaAsset], output: str) -> None:
    with open(os.fspath(output), "w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "filename",
            "duration",
            "resolution",
            "codec",
            "fps",
            "size_mb",
            "has_audio",
            "status",
            "filepath",
        ]
        handle.write(_csv_row(fieldnames) + "\n")
        for item in items:
            handle.write(
                _csv_row(
                    [
                        item.filename,
                        seconds_to_hhmmss(item.duration),
                        item.resolution,
                        item.codec or "N/A",
                        item.fps or "N/A",
                        item.size_mb,
                        item.has_audio,
                        item.status,
                        item.filepath,
                    ]
                )
                + "\n"
            )


def write_inventory_markdown(items: list[MediaAsset], output: str) -> None:
    total_duration = sum(item.duration or 0 for item in items)
    total_size = sum(item.size_mb or 0 for item in items)
    lines = [
        "# Footage Inventory",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        "",
        f"- **Files:** {len(items)}",
        f"- **Total Duration:** {seconds_to_hhmmss(total_duration)}",
        f"- **Total Size:** {round(total_size / 1024, 2)} GB",
        "",
        "## Files",
        "",
        "| Filename | Duration | Resolution | Codec | FPS | Size | Status |",
        "|----------|----------|------------|-------|-----|------|--------|",
    ]
    for item in items[:200]:
        lines.append(
            f"| {item.filename[:60]} | {seconds_to_hhmmss(item.duration)} | {item.resolution} | "
            f"{item.codec or 'N/A'} | {item.fps or 'N/A'} | {item.size_mb} MB | {item.status} |"
        )
    if len(items) > 200:
        lines.append("")
        lines.append(f"*... and {len(items) - 200} more files*")
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _with_suffix(path: str, suffix: str) -> str:
    return os.path.splitext(os.fspath(path))[0] + suffix


def _csv_row(values: list[object]) -> str:
    cells = []
    for value in values:
        text = "" if value is None else str(value)
        if any(char in text for char in [",", '"', "\n", "\r"]):
            text = '"' + text.replace('"', '""') + '"'
        cells.append(text)
    return ",".join(cells)
