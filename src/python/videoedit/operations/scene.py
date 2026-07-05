"""
Scene detection operation - shot boundaries via PySceneDetect.

Scenes are the candidate-clip unit for the shoot funnel: every
downstream signal (speech ratio, tags, motion) is aggregated per
scene before candidates are scored.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import BaseOperation, OperationResult


def detect_scenes(video_path: Path, threshold: float = 27.0,
                  min_scene_len_s: float = 1.0) -> List[Tuple[float, float]]:
    """Return [(start_s, end_s), ...] shot boundaries for a video."""
    from scenedetect import detect, ContentDetector

    scene_list = detect(str(video_path),
                        ContentDetector(threshold=threshold),
                        show_progress=False)
    scenes = [(s.get_seconds(), e.get_seconds()) for s, e in scene_list
              if e.get_seconds() - s.get_seconds() >= min_scene_len_s]
    if not scenes:
        # Single-shot clip (common for interviews): treat whole file as one scene
        from .probe import ProbeMedia  # noqa: F401  (probe already ran for shoots)
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video_path)],
            capture_output=True, text=True)
        duration = float(json.loads(result.stdout)["format"]["duration"])
        scenes = [(0.0, duration)]
    return scenes


class SceneDetect(BaseOperation):
    """Detect shot boundaries with PySceneDetect ContentDetector."""

    name = "scene_detect"
    description = "Detect shot boundaries (PySceneDetect)"
    inputs = ["video"]
    outputs = ["scenes"]

    def __init__(self, threshold: float = 27.0, min_scene_len_s: float = 1.0):
        super().__init__()
        self.threshold = threshold
        self.min_scene_len_s = min_scene_len_s

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        try:
            scenes = detect_scenes(input_path, self.threshold, self.min_scene_len_s)
        except ImportError:
            return OperationResult(
                success=False,
                error="PySceneDetect not installed — pip install 'videoedit[analyze]'")
        except Exception as e:
            return OperationResult(success=False, error=str(e))

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{input_path.stem}_scenes.json"
        out.write_text(json.dumps(
            [{"start": s, "end": e} for s, e in scenes], indent=2))

        return OperationResult(
            success=True, output_path=out,
            data={"scenes": [{"start": s, "end": e} for s, e in scenes]})
