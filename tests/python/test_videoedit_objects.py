"""Native object processing must count negatives and prove safe reusable scans."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))
from videoedit import advanced, cli, objects, operations, pipeline
from videoedit.ffmpeg import CommandResult, run_command_check


class Tensor:
    def __init__(self, values):
        self.values = values
    def cpu(self):
        return self
    def tolist(self):
        return self.values


def frame(classes=(), confidence=(), boxes=()):
    return SimpleNamespace(boxes=SimpleNamespace(cls=Tensor(list(classes)), conf=Tensor(list(confidence)),
                                                xywhn=Tensor(list(boxes))), names={0: "person", 2: "car"})


class ObjectProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "a.mp4"
        self.source.write_bytes(b"source fixture")
        self.weights = self.root / "model.pt"
        self.weights.write_bytes(b"checkpoint fixture")
        self.output = self.root / "visual_objects.json"
        self.metadata = {"duration": 2.0, "fps": 2.0, "expected_frames": 4, "timing_verified": True}
        self.identities = {"ultralytics": "test-1", "torch": "test-1", "opencv-python": "test-1", "ffprobe": "test-1"}
        self.initializations = 0
        self.results = [frame(), frame([0], [0.9], [[0.5, 0.5, 0.2, 0.4]]), frame(), frame()]

    def factory(self, _checkpoint):
        self.initializations += 1
        owner = self
        class Model:
            task = "detect"
            def predict(self, **kwargs):
                if kwargs.get("stream") is not True or kwargs.get("vid_stride") != 1:
                    raise AssertionError("native inference must stream all frames")
                for result in owner.results:
                    if isinstance(result, BaseException):
                        raise result
                    yield result
        return Model()

    def native(self, source=None, **kwargs):
        return advanced.detect_visual_objects(str(source or self.source), str(self.output),
                    model=str(self.weights), backend="native", model_factory=self.factory,
                    metadata_probe=lambda _source, **_kwargs: dict(self.metadata),
                    provider_identity=self.identities, **kwargs)

    def read(self):
        return json.loads(self.output.read_text())

    def test_negative_frames_count_as_processing_not_positive_hits(self):
        result = self.native()
        self.assertEqual(result["status"], "ok")
        data = self.read()
        row = data["coverage"]["sources"][0]
        self.assertEqual(row["expected_units"], 4)
        self.assertEqual(row["processed_units"], 4)
        self.assertEqual(row["intervals"], [[0, 2]])
        self.assertEqual(data["detection_count"], 1)
        self.assertEqual(data["sources"][0]["detections"][0]["time_seconds"], 0.5)
        self.assertEqual(data["sources"][0]["class_counts"][0]["class_name"], "person")
        self.assertEqual(result["telemetry"]["decoded_frames"], 4)

    def test_one_model_handles_multiple_sources_and_warm_run_initializes_none(self):
        other = self.root / "other" / "a.mp4"
        other.parent.mkdir()
        other.write_bytes(b"different fixture")
        cold = self.native(self.root)
        self.assertEqual(cold["count"], 2)
        self.assertEqual(cold["telemetry"]["models_initialized"], 1)
        self.assertEqual(self.initializations, 1)
        first = self.read()["sources"]
        self.assertNotEqual(first[0]["source"], first[1]["source"])
        warm = self.native(self.root)
        self.assertEqual(warm["telemetry"]["models_initialized"], 0)
        self.assertEqual(warm["telemetry"]["decoded_frames"], 0)
        self.assertEqual(warm["telemetry"]["cache_hits"], 2)
        self.assertEqual(self.initializations, 1)
        self.assertEqual([row["segments"] for row in self.read()["sources"]], [row["segments"] for row in first])

    def test_source_model_settings_and_decoder_changes_invalidate(self):
        self.native()
        self.source.write_bytes(b"changed source fixture")
        self.assertEqual(self.native()["telemetry"]["invalidation_reasons"], {"source_changed": 1})
        self.weights.write_bytes(b"changed checkpoint")
        self.assertEqual(self.native()["telemetry"]["invalidation_reasons"], {"model_changed": 1})
        self.assertEqual(self.native(confidence=0.8)["telemetry"]["invalidation_reasons"], {"settings_changed": 1})
        self.identities["opencv-python"] = "test-2"
        self.assertEqual(self.native(confidence=0.8)["telemetry"]["invalidation_reasons"], {"provider_changed": 1})

    def test_partial_failed_and_interrupted_scans_are_not_cached(self):
        self.results = [frame(), RuntimeError("fixture failed frame")]
        result = self.native()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.read()["coverage"]["sources"][0]["processed_units"], 1)
        self.results = [frame()] * 4
        self.assertEqual(self.native()["telemetry"]["cache_hits"], 0)
        self.source.write_bytes(b"new source fixture")
        self.results = [KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.native()
        self.assertEqual(self.read()["status"], "interrupted")
        self.assertEqual(self.read()["sources"][0]["status"], "interrupted")
        self.results = [frame()] * 4
        self.assertEqual(self.native()["telemetry"]["cache_hits"], 0)

    def test_unknown_frame_totals_and_uncertain_timing_are_not_full_coverage(self):
        for field, value in (("expected_frames", None), ("timing_verified", False)):
            with self.subTest(field=field):
                self.metadata = {"duration": 2.0, "fps": 2.0, "expected_frames": 4, "timing_verified": True}
                self.metadata[field] = value
                result = self.native(cache=False)
                self.assertEqual(result["status"], "partial")
                self.assertNotEqual(self.read()["coverage"]["sources"][0]["status"], "ok")

    def test_invalid_result_is_not_a_processed_negative_frame(self):
        self.results[1] = frame([0], [float("nan")], [[0.5, 0.5, 0.2, 0.4]])
        self.assertEqual(self.native()["status"], "partial")
        data = self.read()
        self.assertEqual(data["detection_count"], 0)
        self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 3)
        self.assertEqual(data["coverage"]["sources"][0]["intervals"], [[0, 0.5], [1, 2]])

    def test_native_requires_local_weights_and_never_initializes_missing_checkpoint(self):
        self.weights.unlink()
        result = self.native()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.initializations, 0)
        self.assertIn("local", self.read()["error"])

    def test_native_rejects_other_backends_before_implicit_runtime_install(self):
        other = self.root / "model.onnx"
        other.write_bytes(b"other model format")
        result = advanced.detect_visual_objects(str(self.source), str(self.output), backend="native", model=str(other),
                                               model_factory=self.factory, provider_identity=self.identities)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.initializations, 0)
        self.assertIn(".pt", self.read()["error"])

    def test_corrupt_cache_is_recomputed(self):
        self.native()
        entry = next(path for path in (self.root / ".object_cache").glob("*.json") if ".index." not in path.name)
        data = json.loads(entry.read_text())
        data["source"]["detection_count"] = 500
        entry.write_text(json.dumps(data))
        result = self.native()
        self.assertEqual(result["detection_count"], 1)
        self.assertEqual(result["telemetry"]["cache_hits"], 0)
        self.assertEqual(result["telemetry"]["invalidation_reasons"], {"cache_corrupt": 1})

    def test_corrupt_index_does_not_prevent_recomputation(self):
        self.native()
        directory = self.root / ".object_cache"
        index = next(directory.glob("*.index.json"))
        index.write_text('{"signature": ["corrupt index"]}')
        for path in directory.glob("*.json"):
            if ".index." not in path.name:
                path.write_text("invalid entry")
        result = self.native()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["telemetry"]["cache_hits"], 0)
        self.assertEqual(result["telemetry"]["invalidation_reasons"], {"cache_corrupt": 1})

    def test_source_mutation_discards_positive_results(self):
        original = self.factory
        def factory(checkpoint):
            model = original(checkpoint)
            predict = model.predict
            def changed(**kwargs):
                yield from predict(**kwargs)
                self.source.write_bytes(b"mutated while scanning")
            model.predict = changed
            return model
        with patch.object(self, "factory", side_effect=factory):
            result = self.native()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["detection_count"], 0)
        self.assertEqual(self.read()["coverage"]["sources"][0]["processed_units"], 0)

    def test_probe_checks_decoded_timestamps_not_just_nominal_fps(self):
        for timestamps, verified in (([10, 10.5, 11, 11.5], True), ([10, 10.2, 11, 11.5], False)):
            fixture = {"streams": [{"r_frame_rate": "2/1", "nb_frames": "4"}],
                       "frames": [{"best_effort_timestamp_time": str(value)} for value in timestamps]}
            with patch.object(objects, "run_command_check", return_value=CommandResult([], 0, json.dumps(fixture), "")):
                result = objects.probe_object_timing(str(self.source))
            self.assertEqual(result["expected_frames"], 4)
            self.assertEqual(result["timing_verified"], verified)

    def test_timestamp_tolerance_follows_container_quantization_without_accepting_vfr(self):
        for tick, shift, verified in (("1/1000", 0, True), ("1/1000", 0.004, False), ("1/10", 0, False)):
            times = [round(10 + index * 1001 / 30000, 3) for index in range(300)]
            times[150] += shift
            fixture = {"streams": [{"r_frame_rate": "30000/1001", "time_base": tick, "nb_frames": "300"}],
                       "frames": [{"best_effort_timestamp_time": str(value)} for value in times]}
            with patch.object(objects, "run_command_check", return_value=CommandResult([], 0, json.dumps(fixture), "")):
                result = objects.probe_object_timing(str(self.source))
            self.assertEqual(result["timing_verified"], verified)

    def test_missing_video_stream_has_targeted_error(self):
        with patch.object(objects, "run_command_check", return_value=CommandResult([], 0, '{"streams": [], "frames": []}', "")):
            with self.assertRaisesRegex(ValueError, "no video stream"):
                objects.probe_object_timing(str(self.source))

    def test_quoted_cache_boolean_is_parsed_and_invalid_values_fail(self):
        with patch.object(operations, "detect_visual_objects", return_value={"status": "ok"}) as detector:
            operations.op_detect_objects({"input": str(self.source), "output": str(self.root)}, {"cache": "false"})
        self.assertIs(detector.call_args.kwargs["cache"], False)
        with patch.object(operations, "score_frames", return_value={"status": "ok"}) as scorer:
            operations.op_score_ai_frames({"input": str(self.source), "output": str(self.root)}, {"cache": "false"})
        self.assertIs(scorer.call_args.kwargs["cache"], False)
        with self.assertRaisesRegex(ValueError, "cache.*boolean"):
            operations.op_detect_objects({"input": str(self.source), "output": str(self.root)}, {"cache": "perhaps"})

    def test_streaming_summary_matches_legacy_class_and_segment_aggregation(self):
        detections = []
        for index in range(1, 21):
            classes = [0, 2] if index % 4 else []
            detections.extend(objects._results(frame(classes, [0.9] * len(classes), [[0.5, 0.5, 0.2, 0.4]] * len(classes)),
                                              str(self.source), index, 2))
        summary = objects.ObjectSummary(2, 10, 1)
        for row in detections:
            summary.add(row)
        class_counts, segments = summary.finish()
        self.assertEqual(class_counts, advanced._summarize_classes(detections))
        self.assertEqual(segments, advanced._summarize_segments(detections, 2, 10, 1))

    def test_streaming_summary_preserves_legacy_tie_order_and_top_segment_limit(self):
        detections = []
        for index in range(1, 602):
            classes = [0] if index == 1 else [2, 0]
            detections.extend(objects._results(frame(classes, [0.9] * len(classes), [[0.5, 0.5, 0.2, 0.4]] * len(classes)),
                                              str(self.source), index, 2))
        summary = objects.ObjectSummary(2, 301, 0.1)
        for row in detections:
            summary.add(row)
        class_counts, segments = summary.finish()
        self.assertEqual(class_counts, advanced._summarize_classes(detections))
        self.assertEqual(segments, advanced._summarize_segments(detections, 2, 301, 0.1))

    def test_bad_timing_metadata_is_a_diagnostic_not_invalid_json(self):
        self.metadata["fps"] = float("nan")
        result = self.native()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.read()["coverage"]["sources"][0]["processed_units"], 0)

    def test_non_detection_checkpoint_remains_invalid_for_every_source(self):
        other = self.root / "other.mp4"
        other.write_bytes(b"other source")
        with patch.object(self, "factory", return_value=SimpleNamespace(task="classify")):
            result = self.native(self.root)
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.read()["sources"]), 2)
        self.assertTrue(all(row["status"] == "error" for row in self.read()["sources"]))

    def test_summary_retains_all_counts_after_detailed_detection_limit(self):
        self.results = [frame([0], [0.9], [[0.5, 0.5, 0.2, 0.4]])] * 4
        self.native(max_detections=1)
        row = self.read()["sources"][0]
        self.assertEqual(len(row["detections"]), 1)
        self.assertEqual(row["detection_count"], 4)
        self.assertEqual(row["class_counts"][0]["frame_count"], 4)
        self.assertEqual(row["segments"][0]["detection_count"], 4)

    def test_missing_native_dependency_has_targeted_unavailable_result(self):
        with patch.object(objects, "_identity", return_value={"ultralytics": None, "torch": None, "opencv-python": None}), \
                patch.object(objects, "_factory") as factory:
            result = advanced.detect_visual_objects(str(self.source), str(self.output), backend="native", model=str(self.weights))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("advanced", self.read()["error"])
        factory.assert_not_called()

    def test_failed_model_initialization_is_not_repeated_for_each_source(self):
        (self.root / "other.mp4").write_bytes(b"other source")
        with patch.object(self, "factory", side_effect=RuntimeError("cannot load fixture model")) as factory:
            result = self.native(self.root)
        factory.assert_called_once()
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.read()["sources"]), 2)
        self.assertEqual(result["telemetry"]["model_initialization_attempts"], 1)

    def test_cli_and_operation_forward_native_settings_and_failure_exit(self):
        with patch.object(cli, "detect_visual_objects", return_value={"status": "partial"}) as detector:
            code = cli.main(["signals", "objects", str(self.source), "--output", str(self.output),
                             "--backend", "native", "--model", str(self.weights), "--device", "cpu",
                             "--no-cache", "--source-hash", "sha256", "--image-size", "320", "--timeout", "300"])
        self.assertEqual(code, 1)
        self.assertEqual(detector.call_args.kwargs["backend"], "native")
        self.assertEqual(detector.call_args.kwargs["source_hash"], "sha256")
        self.assertFalse(detector.call_args.kwargs["cache"])

    def test_pipeline_executes_native_provider_and_records_cache_telemetry(self):
        path = self.root / "objects.yaml"
        path.write_text(f"name: objects\nsteps:\n  - name: objects\n    operation: detect_visual_objects\n    params:\n      backend: native\n      model: {self.weights}\n")
        output = self.root / "pipeline"
        plan = pipeline.plan_pipeline(str(path), str(self.source), str(output))
        self.assertEqual(plan["steps"][0]["params"]["backend"], "native")
        self.assertFalse(output.exists())
        with patch.object(objects, "_identity", return_value=self.identities), \
                patch.object(objects, "_factory", side_effect=self.factory), \
                patch.object(objects, "_precision_arguments", return_value={"half": False}), \
                patch.object(objects, "probe_object_timing", return_value=self.metadata):
            result = pipeline.run_pipeline(str(path), str(self.source), str(output))
        self.assertEqual(result["results"]["objects"]["status"], "ok")
        self.assertEqual(result["results"]["objects"]["telemetry"]["models_initialized"], 1)
        manifest = json.loads((output / "pipeline_run.json").read_text())
        self.assertEqual(manifest["steps"][0]["cache_misses"], 1)

    def test_negative_only_scan_is_complete_but_short_scan_is_not(self):
        self.results = [frame()] * 4
        result = self.native()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["detection_count"], 0)
        self.results = [frame()] * 2
        self.assertEqual(self.native(cache=False)["status"], "partial")
        self.assertEqual(self.read()["coverage"]["sources"][0]["intervals"], [[0, 1]])
        with patch.object(operations, "detect_visual_objects", return_value={"status": "ok"}) as detector:
            operations.op_detect_objects({"input": str(self.source), "output": str(self.root)},
                                          {"backend": "native", "model": str(self.weights), "device": "mps", "cache": False})
        self.assertEqual(detector.call_args.kwargs["backend"], "native")
        self.assertFalse(detector.call_args.kwargs["cache"])

    def test_cli_outputs_are_isolated_and_failed_sources_remain_visible(self):
        other = self.root / "other" / "a.mp4"
        other.parent.mkdir()
        other.write_bytes(b"other source")
        def command(args, **_kwargs):
            source = next(value.split("=", 1)[1] for value in args if value.startswith("source="))
            project = Path(next(value.split("=", 1)[1] for value in args if value.startswith("project=")))
            name = next(value.split("=", 1)[1] for value in args if value.startswith("name="))
            if source == str(other):
                return CommandResult(args, 1, "", "fixture failed source")
            folder = project / name / "labels"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "a_1.txt").write_text("0 0.5 0.5 0.2 0.4 0.9\n")
            return CommandResult(args, 0, "video 1/1 (frame 1/4) (no detections)\nvideo 1/1 (frame 2/4) (no detections)\nvideo 1/1 (frame 3/4) (no detections)\nvideo 1/1 (frame 4/4) (no detections)\n", "")
        with patch.object(advanced, "resolve_command", return_value="fixture-yolo"), \
                patch.object(advanced, "run_command", side_effect=command), \
                patch.object(advanced, "probe_media", return_value=SimpleNamespace(duration=2, fps=2)):
            first = advanced.detect_visual_objects(str(self.root), str(self.output))
            first_runs = self.read()["runs"]
            second = advanced.detect_visual_objects(str(self.root), str(self.output))
        self.assertEqual(first["status"], "partial")
        self.assertEqual(second["status"], "partial")
        self.assertEqual(first["telemetry"]["command_invocation_attempts"], 2)
        self.assertIsNone(first["telemetry"]["models_initialized"])
        self.assertEqual(len(self.read()["sources"]), 2)
        self.assertNotEqual(first_runs[0]["run"], self.read()["runs"][0]["run"])
        self.assertEqual(self.read()["coverage"]["sources"][0]["processed_units"], 4)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for timing smoke")
class ObjectTimingSmokeTests(unittest.TestCase):
    def test_fractional_fps_nonzero_origin_is_verified_from_real_video(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fractional.mp4"
            run_command_check(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                               "testsrc2=size=96x64:rate=30000/1001", "-frames:v", "30", "-vf",
                               "setpts=PTS+10/TB", "-fps_mode", "passthrough", "-c:v", "mpeg4", str(source)])
            result = objects.probe_object_timing(str(source))
        self.assertTrue(result["timing_verified"])
        self.assertEqual(result["expected_frames"], 30)
        self.assertGreater(result["first_timestamp"], 9)
        self.assertAlmostEqual(result["duration"], 1.001)

    def test_real_mkv_fractional_timestamps_allow_millisecond_quantization(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fractional.mkv"
            run_command_check(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                               "testsrc2=size=96x64:rate=30000/1001", "-frames:v", "300", "-c:v", "mpeg4", str(source)])
            result = objects.probe_object_timing(str(source))
        self.assertTrue(result["timing_verified"])
        self.assertEqual(result["expected_frames"], 300)


if __name__ == "__main__":
    unittest.main()
