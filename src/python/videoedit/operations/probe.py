"""
Probe operation - extract media metadata for a single file.

Wraps the shoot scanner's ffprobe/EXIF logic so single-file YAML
pipelines can start with a metadata step, sharing one implementation
with shoot-level ingest.
"""
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class ProbeMedia(BaseOperation):
    """Probe a media file's metadata (duration, dims, fps, codecs, camera)."""

    name = "probe_media"
    description = "Extract media metadata via ffprobe/EXIF"
    inputs = ["video", "audio", "photo"]
    outputs = ["media_info"]

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        from ..shoot.scanner import classify, probe_av, probe_photo

        media_type = classify(input_path)
        if media_type is None:
            return OperationResult(
                success=False,
                error=f"Unrecognized media extension: {input_path.suffix}")

        try:
            if media_type == "photo":
                info = probe_photo(input_path)
            else:
                info = probe_av(input_path)
        except Exception as e:
            return OperationResult(success=False, error=str(e))

        info["media_type"] = media_type
        info["size_bytes"] = input_path.stat().st_size
        return OperationResult(success=True, data={"media_info": info})
