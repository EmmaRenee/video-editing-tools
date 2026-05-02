"""
Operations - Individual video processing steps

Each operation is a class that inherits from BaseOperation and implements
the execute() method. Operations are chained together in pipelines.
"""

from .base import BaseOperation, OperationResult
from .audio_detect import DetectHighlightsAudio
from .extract import ExtractSegments
from .format import FormatVideo
from .transcribe import TranscribeWhisper
from .captions import BurnCaptions
from .transcript_detect import DetectHighlightsTranscript
from .edl import GenerateEdl
from .concatenate import ConcatenateVideos
from .transitions import AddCrossfades, SimpleCrossfade
from .audio_normalize import NormalizeAudio

__all__ = [
    "BaseOperation",
    "OperationResult",
    "DetectHighlightsAudio",
    "ExtractSegments",
    "FormatVideo",
    "TranscribeWhisper",
    "BurnCaptions",
    "DetectHighlightsTranscript",
    "GenerateEdl",
    "ConcatenateVideos",
    "AddCrossfades",
    "SimpleCrossfade",
    "NormalizeAudio",
]
