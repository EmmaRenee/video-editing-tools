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
from .probe import ProbeMedia
from .scene import SceneDetect
from .vad import VadSpeech
from .embed import EmbedFrames
from .quality import QualityFrames
from .events import EventsAudio
from .contact import ContactSheet

__all__ = [
    "ProbeMedia",
    "SceneDetect",
    "VadSpeech",
    "EmbedFrames",
    "QualityFrames",
    "EventsAudio",
    "ContactSheet",
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
