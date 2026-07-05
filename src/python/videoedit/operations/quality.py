"""
Quality operation - blur and exposure metrics for frames and photos.

Laplacian variance for sharpness, histogram clipping for exposure.
Nearly free to compute and works identically for video thumbnails
and still photos, so the photo cull and the video funnel share it.
Uses OpenCV when present (ships with scenedetect[opencv]); falls
back to a pure PIL/numpy implementation.
"""
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


def measure_image(path_or_image) -> Dict[str, float]:
    """
    Compute {sharpness, exposure_low_pct, exposure_high_pct} for an image.

    Accepts a file path or a PIL Image. Sharpness is Laplacian variance
    on the grayscale image (higher = sharper; compare within a shoot,
    not across cameras). Exposure percentages are the fraction of pixels
    crushed (<10) or blown (>245).
    """
    import numpy as np
    from PIL import Image

    if isinstance(path_or_image, (str, Path)):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        img = Image.open(path_or_image)
    else:
        img = path_or_image

    # bound work: metrics are stable at reduced resolution
    if max(img.size) > 1024:
        scale = 1024 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    gray = np.asarray(img.convert("L"), dtype=np.float64)

    try:
        import cv2
        lap = cv2.Laplacian(gray, cv2.CV_64F)
    except ImportError:
        # 4-neighbor Laplacian via shifts
        lap = (-4 * gray
               + np.roll(gray, 1, 0) + np.roll(gray, -1, 0)
               + np.roll(gray, 1, 1) + np.roll(gray, -1, 1))
        lap = lap[1:-1, 1:-1]

    total = gray.size
    return {
        "sharpness": round(float(lap.var()), 2),
        "exposure_low_pct": round(float((gray < 10).sum()) / total * 100, 2),
        "exposure_high_pct": round(float((gray > 245).sum()) / total * 100, 2),
    }


class QualityFrames(BaseOperation):
    """Measure blur/exposure for an image file."""

    name = "quality_frames"
    description = "Blur + exposure metrics (Laplacian/histogram)"
    inputs = ["photo"]
    outputs = ["sharpness", "exposure_low_pct", "exposure_high_pct"]

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        try:
            metrics = measure_image(input_path)
        except Exception as e:
            return OperationResult(success=False, error=str(e))
        return OperationResult(success=True, data=metrics)
