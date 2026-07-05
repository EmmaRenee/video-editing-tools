"""
Embed operation - OpenCLIP frame embeddings + zero-shot tagging.

One model load per process; images batched through MPS (Apple
Silicon) when available, CPU otherwise. Embeddings are stored
float16-packed in the shoot DB and reused for zero-shot tags,
near-duplicate detection, and contact-sheet diversity.
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseOperation, OperationResult

DEFAULT_MODEL = "ViT-B-32"
DEFAULT_PRETRAINED = "laion2b_s34b_b79k"

_ENCODER = None


def get_device() -> str:
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class ClipEncoder:
    """Lazy-loaded OpenCLIP model shared across a process."""

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 pretrained: str = DEFAULT_PRETRAINED):
        import open_clip
        import torch
        self.torch = torch
        self.device = get_device()
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained)
        self.model = self.model.to(self.device).eval()
        self.tokenizer = open_clip.get_tokenizer(model_name)
        self.model_name = model_name

    def encode_images(self, images: List) -> "Any":
        """PIL images → L2-normalized float32 numpy array [n, dim]."""
        import numpy as np
        torch = self.torch
        batch = torch.stack([self.preprocess(img.convert("RGB")) for img in images])
        with torch.no_grad():
            feats = self.model.encode_image(batch.to(self.device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)

    def encode_texts(self, prompts: List[str]) -> "Any":
        import numpy as np
        torch = self.torch
        tokens = self.tokenizer(prompts)
        with torch.no_grad():
            feats = self.model.encode_text(tokens.to(self.device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)


def get_encoder(model_name: str = DEFAULT_MODEL,
                pretrained: str = DEFAULT_PRETRAINED) -> ClipEncoder:
    global _ENCODER
    if _ENCODER is None or _ENCODER.model_name != model_name:
        _ENCODER = ClipEncoder(model_name, pretrained)
    return _ENCODER


def pack_embedding(vec) -> bytes:
    import numpy as np
    return np.asarray(vec, dtype=np.float16).tobytes()


def unpack_embedding(blob: bytes):
    import numpy as np
    return np.frombuffer(blob, dtype=np.float16).astype(np.float32)


def extract_frame(video: Path, ts_s: float, out_path: Path, width: int = 320):
    """Grab one thumbnail at ts_s (fast keyframe seek)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{ts_s:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4",
         str(out_path)],
        check=True, capture_output=True, timeout=120)


def sample_timestamps(duration_s: float,
                      scenes: Optional[List[Tuple[float, float]]] = None,
                      interval_s: float = 10.0) -> List[float]:
    """Scene midpoints plus a regular grid, deduped to >=1s spacing."""
    stamps = [round((s + e) / 2, 3) for s, e in (scenes or [])]
    t = interval_s / 2
    while t < duration_s:
        stamps.append(round(t, 3))
        t += interval_s
    stamps.sort()
    deduped: List[float] = []
    for ts in stamps:
        if not deduped or ts - deduped[-1] >= 1.0:
            deduped.append(ts)
    return deduped or ([duration_s / 2] if duration_s else [])


def tag_frames(embeddings, prompt_pairs: List[Tuple[str, str]],
               encoder: ClipEncoder, top_k: int = 3,
               min_prob: float = 0.12) -> List[List[Tuple[str, str, float]]]:
    """
    Zero-shot tag each embedding against the prompt bank.

    Returns per-frame [(category, prompt, prob), ...] for the top_k
    prompts above min_prob (softmax over the whole bank at T=100,
    standard CLIP zero-shot scaling).
    """
    import numpy as np
    text_feats = encoder.encode_texts([p for _, p in prompt_pairs])
    logits = 100.0 * embeddings @ text_feats.T
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = exp / exp.sum(axis=1, keepdims=True)

    results = []
    for row in probs:
        order = row.argsort()[::-1][:top_k]
        results.append([(prompt_pairs[i][0], prompt_pairs[i][1], float(row[i]))
                        for i in order if row[i] >= min_prob])
    return results


class EmbedFrames(BaseOperation):
    """Extract frames, embed with OpenCLIP, and zero-shot tag them."""

    name = "embed_frames"
    description = "CLIP frame embeddings + zero-shot tags"
    inputs = ["video"]
    outputs = ["frames"]

    def __init__(self, interval_s: float = 10.0, model: str = DEFAULT_MODEL,
                 pretrained: str = DEFAULT_PRETRAINED, thumb_width: int = 320):
        super().__init__()
        self.interval_s = interval_s
        self.model = model
        self.pretrained = pretrained
        self.thumb_width = thumb_width

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        from PIL import Image
        from ..shoot.prompts import flatten_prompts

        try:
            encoder = get_encoder(self.model, self.pretrained)
        except ImportError:
            return OperationResult(
                success=False,
                error="open_clip/torch not installed — pip install 'videoedit[analyze]'")

        duration = context.get("duration_s") or 0
        scenes = [(s["start"], s["end"]) for s in context.get("scenes", [])]
        stamps = sample_timestamps(duration, scenes, self.interval_s)

        thumb_dir = Path(output_dir) / "thumbs" / input_path.stem
        frames = []
        images = []
        for ts in stamps:
            thumb = thumb_dir / f"{ts:010.3f}.jpg"
            try:
                extract_frame(input_path, ts, thumb, self.thumb_width)
                images.append(Image.open(thumb))
                frames.append({"ts_s": ts, "thumb_path": str(thumb)})
            except Exception:
                continue

        if not images:
            return OperationResult(success=False, error="No frames extracted")

        embeddings = encoder.encode_images(images)
        tags = tag_frames(embeddings, flatten_prompts(
            context.get("extra_prompts")), encoder)

        for frame, emb, frame_tags in zip(frames, embeddings, tags):
            frame["embedding"] = pack_embedding(emb)
            frame["tags"] = [{"category": c, "prompt": p, "score": round(s, 4)}
                             for c, p, s in frame_tags]

        out = Path(output_dir) / f"{input_path.stem}_frames.json"
        out.write_text(json.dumps(
            [{k: v for k, v in f.items() if k != "embedding"} for f in frames],
            indent=2))
        return OperationResult(success=True, output_path=out,
                               data={"frames": frames})
