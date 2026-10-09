"""Shared decoding must be reusable, observable, and never cache partial work."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))
from videoedit.models import MediaAsset
from videoedit.ffmpeg import CommandResult


class FrameCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "a.mp4"
        self.source.write_bytes(b"source fixture")
        self.cache = self.root / "cache"

    def sampler(self, decoder="a", extractor=None, source_hash="metadata"):
        self.assertIsNotNone(importlib.util.find_spec("videoedit.frames"), "shared sampler is missing")
        from videoedit.frames import FrameCache
        def extract(_source, timestamp, output, **_kwargs):
            Path(output).write_bytes(b"\xff\xd8" + f"fixture at {timestamp:.3f}".encode() + b"\xff\xd9")
        return FrameCache(str(self.cache), decoder_identity={"ffmpeg": decoder, "ffprobe": decoder}, source_hash=source_hash,
                          extractor=extractor or extract,
                          media_probe=lambda path, **_kwargs: MediaAsset(filename=Path(path).name, filepath=path, duration=20, width=1920, height=1080))

    def test_compatible_consumers_reuse_identical_frames_without_decoding(self):
        first = self.sampler().sample(str(self.source), sample_interval=10, max_frames=2)
        self.assertEqual(first["status"], "ok")
        self.assertEqual([frame["time_seconds"] for frame in first["frames"]], [5, 15])
        self.assertEqual(first["telemetry"]["decoded_frames"], 2)
        self.assertEqual(first["telemetry"]["cache_misses"], 1)
        second = self.sampler().sample(str(self.source), sample_interval=10, max_frames=2)
        self.assertEqual(second["telemetry"]["decoded_frames"], 0)
        self.assertEqual(second["telemetry"]["cache_hits"], 1)
        self.assertEqual(second["frames"], first["frames"])
        self.assertEqual(Path(second["frames"][0]["path"]).read_bytes(), b"\xff\xd8fixture at 5.000\xff\xd9")
        self.assertGreater(second["telemetry"]["output_size_bytes"], 0)

    def test_same_basename_sources_never_share_a_cache_entry(self):
        other = self.root / "other" / "a.mp4"
        other.parent.mkdir()
        other.write_bytes(b"other footage")
        a = self.sampler().sample(str(self.source))
        b = self.sampler().sample(str(other))
        self.assertNotEqual(a["frames"][0]["path"], b["frames"][0]["path"])
        self.assertEqual(b["telemetry"]["cache_hits"], 0)

    def test_source_sampling_format_and_decoder_changes_invalidate(self):
        self.sampler().sample(str(self.source), sample_interval=10, max_frames=2)
        self.source.write_bytes(b"changed source footage")
        changed = self.sampler().sample(str(self.source), sample_interval=10, max_frames=2)
        self.assertEqual(changed["telemetry"]["invalidation_reason"], "source_changed")
        changed = self.sampler().sample(str(self.source), sample_interval=5, max_frames=2)
        self.assertEqual(changed["telemetry"]["invalidation_reason"], "sampling_changed")
        changed = self.sampler().sample(str(self.source), sample_interval=5, max_frames=2, width=336)
        self.assertEqual(changed["telemetry"]["invalidation_reason"], "sampling_changed")
        changed = self.sampler(decoder="b").sample(str(self.source), sample_interval=5, max_frames=2, width=336)
        self.assertEqual(changed["telemetry"]["invalidation_reason"], "decoder_changed")

    def test_strict_hash_detects_changes_with_identical_size_and_mtime(self):
        self.sampler(source_hash="sha256").sample(str(self.source))
        stat = self.source.stat()
        self.source.write_bytes(b"SOURCE FIXTURE")
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.source.stat().st_size, stat.st_size)
        result = self.sampler(source_hash="sha256").sample(str(self.source))
        self.assertEqual(result["telemetry"]["cache_hits"], 0)
        self.assertEqual(result["telemetry"]["invalidation_reason"], "source_changed")

    def test_missing_or_mutated_frame_is_regenerated(self):
        first = self.sampler().sample(str(self.source))
        frame = Path(first["frames"][0]["path"])
        frame.write_bytes(b"\xff\xd8modified\xff\xd9")
        second = self.sampler().sample(str(self.source))
        self.assertEqual(second["telemetry"]["invalidation_reason"], "frame_checksum_changed")
        self.assertEqual(second["telemetry"]["cache_hits"], 0)
        self.assertEqual(frame.read_bytes(), b"\xff\xd8fixture at 5.000\xff\xd9")
        frame.unlink()
        third = self.sampler().sample(str(self.source))
        self.assertEqual(third["telemetry"]["invalidation_reason"], "frame_missing")
        self.assertEqual(third["status"], "ok")

    def test_partial_or_interrupted_extraction_is_not_a_successful_cache(self):
        def fail(_source, timestamp, output, **_kwargs):
            if timestamp == 15:
                raise RuntimeError("fixture failed sample")
            Path(output).write_bytes(b"\xff\xd8fixture\xff\xd9")
        partial = self.sampler(extractor=fail).sample(str(self.source))
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["coverage"]["processed_units"], 1)
        self.assertEqual(self.sampler().sample(str(self.source))["telemetry"]["cache_hits"], 0)
        shutil.rmtree(self.cache)
        def interrupt(_source, _timestamp, _output, **_kwargs):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.sampler(extractor=interrupt).sample(str(self.source))
        self.assertEqual(self.sampler().sample(str(self.source))["telemetry"]["cache_hits"], 0)

    def test_staging_cleanup_failure_does_not_replace_original_interrupt(self):
        from videoedit import frames
        def interrupt(_source, _timestamp, _output, **_kwargs):
            raise KeyboardInterrupt
        def failed_cleanup(_path, **kwargs):
            if not kwargs.get("ignore_errors"):
                raise PermissionError("fixture open Windows file handle")
        with patch.object(frames.shutil, "rmtree", side_effect=failed_cleanup), self.assertRaises(KeyboardInterrupt):
            self.sampler(extractor=interrupt).sample(str(self.source))
        self.assertEqual(self.sampler().sample(str(self.source))["telemetry"]["cache_hits"], 0)

    def test_source_changing_during_sampling_cannot_publish_mixed_frames(self):
        def mutate(_source, _timestamp, output, **_kwargs):
            self.source.write_bytes(b"source changed while decoding")
            Path(output).write_bytes(b"\xff\xd8fixture\xff\xd9")
        result = self.sampler(extractor=mutate).sample(str(self.source))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["frames"], [])
        self.assertIn("source_changed_during_sampling", result["warnings"])
        self.assertEqual(self.sampler().sample(str(self.source))["telemetry"]["cache_hits"], 0)

    def test_invalid_sampling_settings_are_rejected_before_decoding(self):
        for params in ({"sample_interval": float("nan")}, {"sample_interval": 0}, {"max_frames": 0}, {"width": -1}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.sampler().sample(str(self.source), **params)

    def test_manifest_cannot_redirect_frame_paths_outside_cache(self):
        first = self.sampler().sample(str(self.source))
        manifest = Path(first["frames"][0]["path"]).parent / "sample.json"
        data = json.loads(manifest.read_text())
        external = self.root / "external.jpg"
        external.write_bytes(b"\xff\xd8untouched\xff\xd9")
        data["frames"][0]["name"] = str(external)
        manifest.write_text(json.dumps(data))
        result = self.sampler().sample(str(self.source))
        self.assertEqual(result["telemetry"]["invalidation_reason"], "cache_manifest_invalid")
        self.assertEqual(external.read_bytes(), b"\xff\xd8untouched\xff\xd9")
        self.assertEqual(Path(result["frames"][0]["path"]).name, "frame_0001.jpg")

    def test_concurrent_repair_publishes_one_complete_valid_entry(self):
        first = self.sampler().sample(str(self.source))
        Path(first["frames"][0]["path"]).unlink()
        barrier = threading.Barrier(2)
        def extract(_source, timestamp, output, **_kwargs):
            Path(output).write_bytes(b"\xff\xd8fixture\xff\xd9")
            if timestamp == 15:
                barrier.wait(timeout=5)
        results = []
        workers = [threading.Thread(target=lambda: results.append(self.sampler(extractor=extract).sample(str(self.source)))) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive())
        self.assertEqual([row["status"] for row in results], ["ok", "ok"])
        for row in results:
            self.assertTrue(all(Path(frame["path"]).is_file() for frame in row["frames"]))
        self.assertEqual(self.sampler().sample(str(self.source))["telemetry"]["cache_hits"], 1)

    def test_warm_source_changes_during_integrity_check_are_rejected(self):
        from videoedit import frames
        self.sampler().sample(str(self.source))
        original = frames.file_sha256
        def changing_checksum(path):
            self.source.write_bytes(b"changed while verifying cached frames")
            return original(path)
        with patch.object(frames, "file_sha256", side_effect=changing_checksum):
            result = self.sampler().sample(str(self.source))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["frames"], [])
        self.assertIn("source_changed_during_sampling", result["warnings"])

    def test_negative_ocr_and_face_results_have_full_processing_coverage_and_share_frames(self):
        from videoedit import advanced
        sampler = self.sampler()
        def command(args, **_kwargs):
            return CommandResult(args, 0, "tesseract 5.5.0" if "--version" in args else "", "")
        cv2 = SimpleNamespace(__version__="fixture", imread=lambda _path: object())
        with patch.object(advanced, "FrameCache", return_value=sampler, create=True), \
                patch.object(advanced, "has_command", return_value=True), patch.object(advanced, "run_command", side_effect=command), \
                patch.dict(sys.modules, {"cv2": cv2}), \
                patch.object(advanced, "_opencv_face_detector", return_value=object()), \
                patch.object(advanced, "_opencv_person_detector", return_value=object()), \
                patch.object(advanced, "_count_faces", return_value=0), patch.object(advanced, "_count_people", return_value=0):
            ocr = advanced.detect_ocr_signage(str(self.source), str(self.root / "ocr.json"), frame_cache=str(self.cache))
            face = advanced.detect_face_person_presence(str(self.source), str(self.root / "face.json"), frame_cache=str(self.cache))
        self.assertEqual(ocr["status"], "ok")
        self.assertEqual(face["status"], "ok")
        for output in ("ocr.json", "face.json"):
            data = json.loads((self.root / output).read_text())
            self.assertEqual(data["count"], 0)
            self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 2)
            self.assertEqual(data["coverage"]["sources"][0]["intervals"], [[0, 10], [10, 20]])
        self.assertEqual(ocr["telemetry"]["decoded_frames"], 2)
        self.assertEqual(face["telemetry"]["decoded_frames"], 0)
        self.assertEqual(face["telemetry"]["cache_hits"], 1)

    def test_provider_failures_cannot_be_reported_as_negative_detections(self):
        from videoedit import advanced
        def command(args, **_kwargs):
            if "--version" in args:
                return CommandResult(args, 0, "tesseract 5.5.0", "")
            if "frame_0002" in args[1]:
                raise TimeoutError("fixture OCR timeout")
            return CommandResult(args, 0, "fixture sign", "")
        with patch.object(advanced, "FrameCache", return_value=self.sampler(), create=True), \
                patch.object(advanced, "has_command", return_value=True), patch.object(advanced, "run_command", side_effect=command):
            ocr = advanced.detect_ocr_signage(str(self.source), str(self.root / "ocr.json"))
        self.assertEqual(ocr["status"], "partial")
        data = json.loads((self.root / "ocr.json").read_text())
        self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 1)
        self.assertEqual(data["hits"][0]["time_seconds"], 5)
        cv2 = SimpleNamespace(__version__="fixture", imread=lambda _path: object())
        with patch.object(advanced, "FrameCache", return_value=self.sampler(), create=True), \
                patch.object(advanced, "has_command", return_value=True), patch.dict(sys.modules, {"cv2": cv2}), \
                patch.object(advanced, "_opencv_face_detector", return_value=None), \
                patch.object(advanced, "_opencv_person_detector", return_value=object()):
            face = advanced.detect_face_person_presence(str(self.source), str(self.root / "face.json"))
        self.assertEqual(face["status"], "unavailable")
        self.assertEqual(json.loads((self.root / "face.json").read_text())["hits"], [])

    def test_ai_native_sampler_reuses_frames_across_profiles_without_reusing_inference(self):
        from videoedit import ai
        class Encoder:
            provider_name, provider_version = "fixture", "test"
            calls = 0
            def score_images(self, images, prompts):
                self.calls += 1
                return [[0.1 for _prompt in prompts] for _image in images]
        encoder, sampler = Encoder(), self.sampler()
        with patch.object(ai, "FrameCache", return_value=sampler, create=True):
            first = ai.score_frames(str(self.source), str(self.root / "ai-a.json"), encoder=encoder, cache=False, frame_cache=str(self.cache))
            second = ai.score_frames(str(self.source), str(self.root / "ai-b.json"), profile_id="garage_shop", encoder=encoder, cache=False, frame_cache=str(self.cache))
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(encoder.calls, 2)
        self.assertEqual(first["telemetry"]["frame_sampling"]["decoded_frames"], 2)
        self.assertEqual(second["telemetry"]["frame_sampling"]["decoded_frames"], 0)
        self.assertEqual(second["telemetry"]["frame_sampling"]["cache_hits"], 1)
        self.assertEqual(json.loads((self.root / "ai-a.json").read_text())["sources"][0]["coverage"]["processed_units"], 2)

    def test_pipeline_sampling_operation_and_dry_run_share_cache_context(self):
        from videoedit import frames, advanced
        from videoedit.operations import default_registry
        from videoedit.pipeline import plan_pipeline, run_pipeline
        pipeline = self.root / "frames.yaml"
        pipeline.write_text("name: shared\nsteps:\n  - name: samples\n    operation: sample_frames\n    params:\n      max_frames_per_file: 6\n  - name: ocr\n    operation: detect_ocr_signage\n    params:\n      frame_cache: $frame_cache\n")
        output = self.root / "pipeline"
        plan = plan_pipeline(str(pipeline), str(self.source), str(output))
        self.assertEqual(default_registry().get("sample_frames").module, "core.inventory")
        self.assertEqual(plan["steps"][1]["params"]["frame_cache"], str(output / "samples"))
        self.assertFalse(output.exists())
        sampler = self.sampler()
        def command(args, **_kwargs):
            return CommandResult(args, 0, "tesseract 5.5.0" if "--version" in args else "", "")
        with patch.object(frames, "FrameCache", return_value=sampler), \
                patch.object(advanced, "FrameCache", return_value=sampler), \
                patch.object(advanced, "has_command", return_value=True), patch.object(advanced, "run_command", side_effect=command):
            result = run_pipeline(str(pipeline), str(self.source), str(output))
        self.assertEqual(result["results"]["samples"]["telemetry"]["decoded_frames"], 2)
        self.assertEqual(result["results"]["ocr"]["telemetry"]["decoded_frames"], 0)
        self.assertEqual(result["results"]["ocr"]["telemetry"]["cache_hits"], 1)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for sample CLI smoke")
class FrameCLITests(unittest.TestCase):
    def test_sample_frames_cli_decodes_real_jpegs_then_reuses_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=10",
                            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
            cmd = [sys.executable, "-m", "videoedit.cli", "signals", "sample-frames", str(source),
                   "--output", str(root / "cache"), "--sample-interval", "1", "--max-frames-per-file", "2"]
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src" / "python")}
            first = subprocess.run(cmd, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            data = json.loads((root / "cache" / "frames.json").read_text())
            self.assertEqual(data["telemetry"]["decoded_frames"], 2)
            self.assertEqual([row["time_seconds"] for row in data["sources"][0]["frames"]], [0.5, 1.5])
            frame = data["sources"][0]["frames"][0]["path"]
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", frame], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(probe.stdout)["streams"][0]["width"], 64)
            self.assertEqual(json.loads(probe.stdout)["streams"][0]["height"], 48)
            second = subprocess.run(cmd, capture_output=True, text=True, env=env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads((root / "cache" / "frames.json").read_text())["telemetry"]["decoded_frames"], 0)


if __name__ == "__main__":
    unittest.main()
