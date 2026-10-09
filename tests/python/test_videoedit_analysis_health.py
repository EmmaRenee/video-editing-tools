"""Empty detections are valid only when the requested analysis actually succeeded."""

from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.config import AnalysisConfig
from videoedit.ffmpeg import detect_scene_changes
from videoedit.models import AudioLevel, MediaAsset, SignalReport
from videoedit.rating import run_rating


class AnalysisHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.footage = self.root / "footage"
        self.footage.mkdir()
        self.source = self.footage / "source.mp4"
        self.source.touch()
        self.output = self.root / "analysis"
        self.asset = MediaAsset("source.mp4", str(self.source), duration=4, fps=30,
                                width=160, height=90, codec="mpeg4", has_audio=True)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("videoedit.rating.probe_media", return_value=self.asset))
        self.scene = self.stack.enter_context(patch("videoedit.rating.detect_scene_changes", return_value=([], None)))
        self.silence = self.stack.enter_context(patch("videoedit.rating.detect_silence", return_value=([], None)))
        self.audio = self.stack.enter_context(patch("videoedit.rating.analyze_audio_levels", return_value=([AudioLevel(0, -20)], None)))

    def rate(self, mode="off"):
        return run_rating(str(self.footage), str(self.output), AnalysisConfig(transcript_mode=mode))

    def manifest(self):
        return json.loads((self.output / "rating_run.json").read_text())

    def test_successful_negative_detection_is_complete_and_cacheable(self):
        report = self.rate()
        self.assertTrue(getattr(report.signals[0], "analysis_complete", False))
        self.assertEqual(self.manifest()["status"], "ok")
        self.rate()
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)

    def test_each_failed_detector_marks_rating_partial_without_caching(self):
        for detector, name in ((self.scene, "scene"), (self.silence, "silence"), (self.audio, "audio")):
            with self.subTest(detector=name):
                self.output = self.root / name
                original = detector.return_value
                detector.return_value = ([], f"{name} detection failed")
                report = self.rate()
                detector.return_value = original
                self.assertEqual(report.inventory[0].status, "ok")
                self.assertEqual(self.manifest()["status"], "partial")
                self.assertFalse(self.manifest()["complete"])
                self.assertEqual(report.summary.get("analysis_failed"), 1)
                self.assertFalse((self.output / ".cache" / "analysis-cache.json").exists())

    def test_failed_detection_is_retried_then_healthy_result_can_be_reused(self):
        self.scene.return_value = ([], "scene detection failed")
        self.rate()
        self.rate()
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 0)
        self.assertEqual(self.manifest()["telemetry"]["cache_misses"], 1)
        self.scene.return_value = ([2.0], None)
        report = self.rate()
        self.assertEqual(report.signals[0].scene_changes, [2.0])
        self.assertEqual(self.manifest()["telemetry"]["cache_misses"], 1)
        self.assertEqual(self.manifest()["status"], "ok")
        self.rate()
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)

    def test_legacy_cached_report_without_health_is_reanalyzed(self):
        self.rate()
        cache = self.output / ".cache" / "analysis-cache.json"
        data = json.loads(cache.read_text())
        entry = next(iter(data.values()))
        entry["report"].pop("analysis_status", None)
        cache.write_text(json.dumps(data))
        self.scene.return_value = ([2.0], None)
        report = self.rate()
        self.assertEqual(report.signals[0].scene_changes, [2.0])
        self.assertEqual(self.manifest()["telemetry"]["cache_misses"], 1)
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 0)

    def test_video_without_audio_is_not_an_audio_analysis_failure(self):
        self.asset.has_audio = False
        report = self.rate()
        self.assertTrue(getattr(report.signals[0], "analysis_complete", False))
        self.assertEqual(self.manifest()["status"], "ok")
        self.assertEqual(report.signals[0].to_dict().get("analysis_status", {}).get("audio"), "not_applicable")

    def test_optional_missing_transcript_remains_complete(self):
        report = self.rate(mode="auto")
        self.assertTrue(report.signals[0].analysis_complete)
        self.assertEqual(report.signals[0].analysis_status["transcript"], "unavailable_optional")

    def test_invalidated_healthy_cache_is_removed_after_failed_reanalysis(self):
        self.rate()
        self.source.write_bytes(b"source changed")
        self.scene.return_value = ([], "scene detection failed")
        self.rate()
        cache = json.loads((self.output / ".cache" / "analysis-cache.json").read_text())
        self.assertEqual(cache, {})
        self.assertEqual(self.manifest()["status"], "partial")

    def test_health_roundtrip_is_computed_not_trusted_from_json_boolean(self):
        report = self.rate().signals[0]
        payload = report.to_dict()
        self.assertTrue(SignalReport.from_dict(payload).analysis_complete)
        payload["analysis_status"]["scenes"] = "error"
        payload["analysis_complete"] = True
        self.assertFalse(SignalReport.from_dict(payload).analysis_complete)

    def test_probe_failure_does_not_run_or_cache_detectors(self):
        self.asset.status = "error"
        self.asset.error = "probe failed"
        report = self.rate()
        self.scene.assert_not_called()
        self.silence.assert_not_called()
        self.audio.assert_not_called()
        self.assertEqual(report.signals[0].analysis_status["probe"], "error")
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse((self.output / ".cache" / "analysis-cache.json").exists())

    def test_required_missing_transcript_is_partial(self):
        self.rate(mode="required")
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse((self.output / ".cache" / "analysis-cache.json").exists())

    def test_legacy_signal_json_remains_readable_without_certifying_health(self):
        legacy = {"asset": self.asset.to_dict(), "scene_changes": [1.0]}
        report = SignalReport.from_dict(legacy)
        self.assertEqual(report.scene_changes, [1.0])
        self.assertFalse(getattr(report, "analysis_complete", False))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class ActualSceneTests(unittest.TestCase):
    def test_real_scene_transition_is_detected_without_removed_sync_options(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.mov"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=96x64:r=24:d=1", "-f", "lavfi", "-i",
                            "color=c=white:s=96x64:r=24:d=1", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                            "-map", "[v]", "-c:v", "mpeg4", str(source)], check=True, capture_output=True)
            scenes, warning = detect_scene_changes(str(source))
            self.assertIsNone(warning)
            self.assertEqual(scenes, [1.0])


if __name__ == "__main__":
    unittest.main()
