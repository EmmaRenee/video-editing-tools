"""
VAD operation - speech/no-speech segmentation via Silero VAD.

Per-clip speech ratio is the primary A-roll vs B-roll signal, and it
gates transcription: clips that are mostly silent or engine noise
never hit Whisper. Also computes cheap RMS energy peaks from the same
decoded audio, feeding the B-roll "excitement" score.
"""
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseOperation, OperationResult

_VAD_MODEL = None  # loaded once per process


def _load_vad():
    global _VAD_MODEL
    if _VAD_MODEL is None:
        from silero_vad import load_silero_vad
        _VAD_MODEL = load_silero_vad(onnx=True)
    return _VAD_MODEL


def extract_wav(media_path: Path, out_path: Path, sample_rate: int = 16000):
    """Decode any media's audio to 16k mono wav for analysis."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(media_path),
         "-vn", "-ac", "1", "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", str(out_path)],
        check=True, capture_output=True, timeout=1800)


def analyze_speech(media_path: Path) -> Dict[str, Any]:
    """
    Run VAD + RMS analysis on a media file's audio.

    Returns {duration_s, speech_ratio, speech_segments: [{start_s,end_s}],
             rms_peaks: [{start_s, end_s, score(dBFS)}]}.
    Files with no audio stream return speech_ratio 0 and empty lists.
    """
    import wave

    import numpy as np
    import torch
    from silero_vad import get_speech_timestamps

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio.wav"
        try:
            extract_wav(media_path, wav_path)
        except subprocess.CalledProcessError:
            return {"duration_s": 0, "speech_ratio": 0.0,
                    "speech_segments": [], "rms_peaks": []}

        # read the PCM ourselves: torchaudio >= 2.9 dropped built-in
        # decoding (wants torchcodec), and we already have clean
        # 16k mono s16le from ffmpeg
        with wave.open(str(wav_path), "rb") as wav_file:
            n_frames = wav_file.getnframes()
            samples = np.frombuffer(wav_file.readframes(n_frames),
                                    dtype=np.int16).astype(np.float32) / 32768.0

        wav = torch.from_numpy(samples)
        duration = len(wav) / 16000.0
        if duration == 0:
            return {"duration_s": 0, "speech_ratio": 0.0,
                    "speech_segments": [], "rms_peaks": []}

        speech = get_speech_timestamps(wav, _load_vad(),
                                       sampling_rate=16000,
                                       return_seconds=True)
        speech_segments = [{"start_s": s["start"], "end_s": s["end"]}
                           for s in speech]
        speech_total = sum(s["end_s"] - s["start_s"] for s in speech_segments)

        # RMS energy per 0.5s window from the same decoded audio
        window = 8000  # 0.5s at 16k
        n_windows = len(samples) // window
        rms_peaks: List[Dict] = []
        if n_windows:
            windows = samples[:n_windows * window].reshape(n_windows, window)
            rms = np.sqrt((windows ** 2).mean(axis=1))
            db = 20 * np.log10(np.maximum(rms, 1e-10))
            # peaks: windows in the top 5% of this clip's energy and above -30dBFS
            if len(db) > 2:
                threshold = max(float(np.percentile(db, 95)), -30.0)
                for i, val in enumerate(db):
                    if val >= threshold:
                        rms_peaks.append({"start_s": i * 0.5,
                                          "end_s": (i + 1) * 0.5,
                                          "score": round(float(val), 2)})

    return {"duration_s": duration,
            "speech_ratio": round(speech_total / duration, 4),
            "speech_segments": speech_segments,
            "rms_peaks": rms_peaks}


class VadSpeech(BaseOperation):
    """Segment speech vs non-speech with Silero VAD; compute energy peaks."""

    name = "vad_speech"
    description = "Speech/no-speech segmentation (Silero VAD)"
    inputs = ["video", "audio"]
    outputs = ["speech_ratio", "speech_segments", "rms_peaks"]

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        try:
            result = analyze_speech(input_path)
        except ImportError:
            return OperationResult(
                success=False,
                error="silero-vad not installed — pip install 'videoedit[analyze]'")
        except Exception as e:
            return OperationResult(success=False, error=str(e))

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{input_path.stem}_vad.json"
        out.write_text(json.dumps(result, indent=2))
        return OperationResult(success=True, output_path=out, data=result)
