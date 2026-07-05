"""
Audio event operation - AudioSet tagging via PANNs (optional extra).

Labels like "Race car, auto racing", "Cheering", "Applause", and
"Engine" are strong B-roll excitement signals for motorsport and
event footage. Degrades to a skip when the extra isn't installed.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult

_TAGGER = None

# AudioSet labels worth persisting for the funnel
INTERESTING = {"speech", "cheering", "applause", "crowd", "engine",
               "race car, auto racing", "vehicle", "motorcycle",
               "car", "music", "laughter", "shout", "siren"}


def detect_events(media_path: Path, window_s: float = 5.0,
                  min_prob: float = 0.3) -> List[Dict[str, Any]]:
    """Run PANNs CNN14 over windowed audio; return labeled segments."""
    global _TAGGER
    import numpy as np
    import librosa  # panns-inference dependency
    from panns_inference import AudioTagging

    if _TAGGER is None:
        _TAGGER = AudioTagging(checkpoint_path=None, device="cpu")

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(media_path),
             "-vn", "-ac", "1", "-ar", "32000", "-c:a", "pcm_s16le",
             str(wav_path)],
            check=True, capture_output=True, timeout=1800)
        audio, _ = librosa.load(str(wav_path), sr=32000, mono=True)

    labels = _TAGGER.labels
    window = int(window_s * 32000)
    events: List[Dict[str, Any]] = []
    for i in range(0, max(len(audio) - window // 2, 1), window):
        chunk = audio[i:i + window]
        if len(chunk) < 32000:  # ignore sub-second tails
            break
        clipwise, _ = _TAGGER.inference(chunk[None, :])
        probs = np.asarray(clipwise[0])
        for idx in probs.argsort()[::-1][:5]:
            label = labels[idx]
            if probs[idx] >= min_prob and label.lower() in INTERESTING:
                events.append({
                    "start_s": round(i / 32000, 2),
                    "end_s": round(min((i + window) / 32000, len(audio) / 32000), 2),
                    "label": label,
                    "score": round(float(probs[idx]), 4),
                })
    return events


class EventsAudio(BaseOperation):
    """Tag audio events (engine, cheering, applause) with PANNs."""

    name = "events_audio"
    description = "Audio event tagging (PANNs, optional)"
    inputs = ["video", "audio"]
    outputs = ["audio_events"]

    def __init__(self, window_s: float = 5.0, min_prob: float = 0.3):
        super().__init__()
        self.window_s = window_s
        self.min_prob = min_prob

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        try:
            events = detect_events(input_path, self.window_s, self.min_prob)
        except ImportError:
            return OperationResult(
                success=True,
                data={"audio_events": [], "skipped": "panns-inference not installed "
                      "(pip install 'videoedit[audio-events]')"})
        except Exception as e:
            return OperationResult(success=False, error=str(e))
        return OperationResult(success=True, data={"audio_events": events})
