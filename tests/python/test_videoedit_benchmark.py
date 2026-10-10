"""Benchmark contract checks with hand-derived quality and coverage metrics."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "benchmarks"


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        shutil.copytree(FIXTURES, self.workspace / "inputs")
        self.manifest = self.workspace / "inputs" / "manifest.json"
        self.output = self.workspace / "result"

    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src" / "python"))
        return subprocess.run([sys.executable, "-m", "videoedit.cli", "benchmark", *map(str, args)],
                              capture_output=True, text=True, env=env, cwd=self.workspace)

    def read(self, path):
        return json.loads(Path(path).read_text())

    def write(self, path, value):
        Path(path).write_text(json.dumps(value))

    def run_report(self):
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read(self.output / "benchmark_report.json")

    def test_validates_manifest_and_rejects_zero_limit(self):
        valid = self.cli("validate", self.manifest)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        invalid = self.cli("validate", self.manifest.parent / "invalid.json")
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertIn("review_limit", invalid.stdout)

    def test_empty_footage_key_cannot_override_consumed_ratings(self):
        data = self.read(self.manifest)
        run = data["projects"][0]["runs"][0]
        run["footage"] = ""
        self.write(self.manifest, data)
        result = self.cli("validate", self.manifest)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.read_json_output(result)["valid"])
        run.pop("footage")
        run["ratings"] = " "
        self.write(self.manifest, data)
        self.assertEqual(self.cli("validate", self.manifest).returncode, 1)

    def test_malformed_manifest_field_types_have_validation_errors(self):
        original = self.read(self.manifest)
        for section, field, value in [("project", "profile", []), ("review", "origin", {}),
                                      ("run", "role", []), ("run", "providers", None)]:
            with self.subTest(field=field):
                data = json.loads(json.dumps(original))
                project = data["projects"][0]
                target = project if section == "project" else project["review"] if section == "review" else project["runs"][0]
                target[field] = value
                if field == "providers":
                    target["provider_artifacts"] = {"yolo": "objects.json"}
                self.write(self.manifest, data)
                result = self.cli("validate", self.manifest)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.read_json_output(result)["valid"])

    def read_json_output(self, result):
        self.assertTrue(result.stdout.strip(), result.stderr)
        return json.loads(result.stdout)

    def test_metrics_exclude_unreviewed_time_and_report_misses(self):
        report = self.run_report()
        run = report["projects"][0]["runs"][0]
        self.assertEqual(run["metrics"]["precision"], 0.5)
        self.assertEqual(run["metrics"]["recall"], 0.5)
        self.assertEqual(run["metrics"]["f1"], 0.5)
        self.assertEqual(run["metrics"]["recall_at_review_limit"], 0.5)
        self.assertEqual(run["metrics"]["excluded_candidates"], 1)
        self.assertEqual(run["metrics"]["candidate_count"], 2)
        self.assertEqual(run["metrics"]["reviewed_seconds"], 30)
        self.assertEqual(run["telemetry"]["cache_hit_rate"], 0.5)
        self.assertIsNone(run["metrics"]["human_acceptance_rate"])
        self.assertEqual(report["status"], "synthetic")
        self.assertTrue((self.output / "per_source.csv").is_file())
        self.assertTrue((self.output / "benchmark_report.md").is_file())

    def test_redacted_report_omits_private_paths_notes_and_reviewer(self):
        ann = self.read(self.manifest.parent / "annotations.json")
        ann["project"] = "Secret customer name"
        ann["clips"][0]["notes"] = "Confidential transcript sentence"
        self.write(self.manifest.parent / "annotations.json", ann)
        report = self.run_report()
        text = json.dumps(report)
        for private in [self.temp.name, "Secret customer name", "Confidential transcript sentence", "editor-a", "source_a.mp4", "quote"]:
            self.assertNotIn(private, text)
        self.assertEqual(report["projects"][0]["runs"][0]["sources"][0]["source"], "source_001")

    def test_absent_telemetry_is_unknown_and_missing_input_is_failed(self):
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0].pop("telemetry")
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertIsNone(report["projects"][0]["runs"][0]["telemetry"]["elapsed_seconds"])
        data["projects"][0]["runs"].append({"id": "unavailable", "ratings": "missing.json", "providers": ["openclip"]})
        self.write(self.manifest, data)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.read(self.output / "benchmark_report.json")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["projects"][0]["runs"][1]["status"], "failed")
        self.assertNotIn("missing.json", json.dumps(report))

    def test_insufficient_human_samples_cannot_pass_release_gate(self):
        data = self.read(self.manifest)
        data["quality_gates"]["min_positive_annotations"] = 30
        data["projects"][0]["review"]["origin"] = "human"
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("min_positive_annotations", report["projects"][0]["runs"][0]["gate_failures"])

    def test_fractional_review_windows_meet_exact_duration_gate(self):
        self.check_fractional_review_duration(200, False)

    def test_fractional_review_windows_below_duration_gate_remain_insufficient(self):
        self.check_fractional_review_duration(199.999999, True)

    def test_large_offset_microsecond_short_review_remains_insufficient(self):
        self.check_fractional_review_duration(199.999999, True, starts=(2 ** 30,) * 3)

    def test_extreme_offset_short_review_remains_insufficient(self):
        self.check_fractional_review_duration(192, True, starts=(2 ** 56,) * 3, expected_seconds=576)

    def test_integer_duration_gate_retains_precision_beyond_float_range(self):
        self.check_fractional_review_duration(2 ** 53, True, starts=(0,) * 3,
                                             expected_seconds=2 ** 53 + 400, duration_gate=2 ** 53 + 401)

    def test_fragmented_windows_cannot_expand_roundoff_allowance(self):
        data = self.read(self.manifest)
        project = data["projects"][0]
        start = 8192
        windows = [{"source": "source_a.mp4", "start": start + index / 16,
                    "end": start + index / 16 + 1 / 32} for index in range(19200)]
        project["review"].update(origin="human", windows=windows)
        data["quality_gates"].update(min_reviewed_seconds=600, min_positive_annotations=1,
                                      min_negative_annotations=1, min_sources=1,
                                      min_precision=1, min_recall=1, min_f1=1)
        self.write(self.manifest.parent / "ratings.json", {
            "inventory": [{"path": "source_a.mp4", "duration": 10000, "status": "ok"}],
            "candidates": [{"id": "clip_1", "source": "source_a.mp4", "start": start,
                            "end": start + 1 / 64, "score": 90}],
        })
        self.write(self.manifest.parent / "annotations.json", {"clips": [
            {"source": "source_a.mp4", "start": start, "end": start + 1 / 64, "rating": "select"},
            {"source": "source_a.mp4", "start": start + 1 / 16,
             "end": start + 1 / 16 + 1 / 64, "rating": "reject"},
        ]})
        original_end = windows[-1]["end"]
        for shortage in (0, 2e-9, 1e-6):
            with self.subTest(shortage=shortage):
                windows[-1]["end"] = original_end - shortage
                self.write(self.manifest, data)
                run = self.run_report()["projects"][0]["runs"][0]
                self.assertEqual("min_reviewed_seconds" in run["gate_failures"], shortage > 0)
                self.assertEqual(run["status"], "insufficient_evidence" if shortage else "ok")
                self.assertEqual(run["metrics"]["reviewed_seconds"], 600)

    def test_count_gates_remain_strict(self):
        data = self.read(self.manifest)
        data["projects"][0]["review"]["origin"] = "human"
        for key, actual in (("min_positive_annotations", 2), ("min_negative_annotations", 1), ("min_sources", 1)):
            for shortage in (1, 0.25):
                with self.subTest(gate=key, shortage=shortage):
                    candidate = json.loads(json.dumps(data))
                    candidate["quality_gates"][key] = actual + shortage
                    self.write(self.manifest, candidate)
                    run = self.run_report()["projects"][0]["runs"][0]
                    self.assertIn(key, run["gate_failures"])
                    self.assertEqual(run["status"], "insufficient_evidence")

    def check_fractional_review_duration(self, final_duration, insufficient,
                                         starts=(1173.272, 848.89, 612.862), expected_seconds=600,
                                         duration_gate=600):
        data = self.read(self.manifest)
        project = data["projects"][0]
        project["review"].update(origin="human", windows=[])
        data["quality_gates"].update(min_reviewed_seconds=duration_gate, min_positive_annotations=3,
                                      min_negative_annotations=3, min_sources=3,
                                      min_precision=1, min_recall=1, min_f1=1)
        ratings, annotations = {"inventory": [], "candidates": []}, {"clips": []}
        for index, start in enumerate(starts):
            source = f"source_{index}.mp4"
            end = start + (final_duration if index == 2 else 200)
            project["review"]["windows"].append({"source": source, "start": start, "end": end})
            ratings["inventory"].append({"path": source, "duration": end + 1600, "status": "ok"})
            ratings["candidates"].append({"id": f"clip_{index}", "source": source,
                                           "start": start + 32, "end": start + 64, "score": 90})
            annotations["clips"].extend([
                {"id": f"positive_{index}", "source": source, "start": start + 32,
                 "end": start + 64, "rating": "select"},
                {"id": f"negative_{index}", "source": source, "start": start + 96,
                 "end": start + 128, "rating": "reject"},
            ])
        self.write(self.manifest, data)
        self.write(self.manifest.parent / "ratings.json", ratings)
        self.write(self.manifest.parent / "annotations.json", annotations)
        run = self.run_report()["projects"][0]["runs"][0]
        self.assertEqual("min_reviewed_seconds" in run["gate_failures"], insufficient)
        self.assertEqual(run["status"], "insufficient_evidence" if insufficient else "ok")
        self.assertEqual(run["metrics"]["reviewed_sources"], 3)
        self.assertEqual(run["metrics"]["reviewed_seconds"], expected_seconds)

    def test_comparison_reports_delta_and_rejects_changed_annotations(self):
        baseline = self.run_report()
        baseline_path = self.workspace / "baseline.json"
        self.write(baseline_path, baseline)
        ratings = self.read(self.manifest.parent / "ratings.json")
        ratings["candidates"][1].update(source="source_a.mp4", start=10, end=14)
        self.write(self.manifest.parent / "ratings.json", ratings)
        self.run_report()
        result = self.cli("compare", baseline_path, self.output / "benchmark_report.json", "--output", self.workspace / "comparison")
        self.assertEqual(result.returncode, 0, result.stderr)
        comparison = self.read(self.workspace / "comparison" / "benchmark_compare.json")
        self.assertEqual(comparison["comparisons"][0]["delta"]["f1"], 0.5)
        annotations = self.read(self.manifest.parent / "annotations.json")
        annotations["clips"][0]["end"] = 5
        self.write(self.manifest.parent / "annotations.json", annotations)
        self.run_report()
        changed = self.cli("compare", baseline_path, self.output / "benchmark_report.json", "--output", self.workspace / "incompatible")
        self.assertEqual(changed.returncode, 1)
        self.assertIn("review basis", changed.stderr)

    def test_comparison_rejects_missing_baseline_and_input_fingerprints(self):
        baseline = self.run_report()
        baseline_path = self.workspace / "baseline.json"
        candidate_path = self.output / "benchmark_report.json"
        for broken in ("baseline", "inputs"):
            with self.subTest(broken=broken):
                data = json.loads(json.dumps(baseline))
                run = data["projects"][0]["runs"][0]
                if broken == "baseline":
                    run["role"] = "candidate"
                else:
                    run.pop("inputs")
                self.write(baseline_path, data)
                result = self.cli("compare", baseline_path, candidate_path, "--output", self.workspace / "comparison")
                self.assertEqual(result.returncode, 1)
                expected = "exactly one baseline" if broken == "baseline" else "input fingerprints"
                self.assertIn(expected, result.stderr)

    def test_comparison_skips_identical_baseline_rows(self):
        self.run_report()
        path = self.output / "benchmark_report.json"
        result = self.cli("compare", path, path, "--output", self.workspace / "comparison")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(self.workspace / "comparison" / "benchmark_compare.json")["comparisons"], [])

    def test_repeated_consumption_has_stable_metrics_and_order(self):
        first = self.run_report()
        second = self.run_report()
        self.assertEqual(first, second)

    def test_overlapping_windows_do_not_double_count_reviewed_duration(self):
        data = self.read(self.manifest)
        data["projects"][0]["review"]["windows"].append({"source": "source_a.mp4", "start": 10, "end": 25})
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertEqual(report["projects"][0]["runs"][0]["metrics"]["reviewed_seconds"], 30)

    def test_explicit_decisions_count_acceptance_and_skip_undecided_clips(self):
        self.write(self.manifest.parent / "decisions.json", {"decisions": [
            {"id": "clip_a", "decision": "approve"}, {"id": "clip_c", "decision": "review"},
            {"id": "outside", "decision": "reject"}]})
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0]["decisions"] = "decisions.json"
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertEqual(report["projects"][0]["runs"][0]["metrics"]["human_acceptance_rate"], 1)

    def test_duplicate_annotation_ids_and_invalid_source_intervals_fail(self):
        annotations = self.read(self.manifest.parent / "annotations.json")
        annotations["clips"][1]["id"] = "a"
        self.write(self.manifest.parent / "annotations.json", annotations)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.read(self.output / "benchmark_report.json")["status"], "failed")

    def test_missing_provider_artifact_cannot_be_a_successful_run(self):
        data = self.read(self.manifest)
        data["projects"][0]["runs"].append({"id": "objects", "ratings": "ratings.json", "providers": ["yolo"],
                                          "provider_artifacts": {"yolo": "missing-objects.json"}})
        self.write(self.manifest, data)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        run = self.read(self.output / "benchmark_report.json")["projects"][0]["runs"][1]
        self.assertEqual(run["error_code"], "provider_artifact_unavailable")

    def test_provider_fingerprints_and_partial_failure_are_visible(self):
        artifact = {"schema_version": "videoedit.visual_objects.v1", "status": "ok",
                    "provider_metadata": {"model": "synthetic", "secret": "private-reference"},
                    "sources": [{"source": "source_a.mp4", "status": "ok", "detections": []}]}
        self.write(self.manifest.parent / "objects.json", artifact)
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0].update(providers=["yolo"], provider_artifacts={"yolo": "objects.json"})
        self.write(self.manifest, data)
        report = self.run_report()
        provider = report["projects"][0]["runs"][0]["provider_metadata"][0]
        self.assertEqual(provider["schema_version"], "videoedit.visual_objects.v1")
        self.assertEqual(len(provider["artifact_sha256"]), 64)
        self.assertNotIn("private-reference", json.dumps(report))
        artifact["sources"][0]["status"] = "unavailable"
        self.write(self.manifest.parent / "objects.json", artifact)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        run = self.read(self.output / "benchmark_report.json")["projects"][0]["runs"][0]
        self.assertEqual(run["error_code"], "provider_partial_failure")

    def test_failed_run_manifest_cannot_be_reported_as_success(self):
        self.write(self.manifest.parent / "execution.json", {"status": "error", "error": "private path"})
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0]["run_manifest"] = "execution.json"
        self.write(self.manifest, data)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("private path", (self.output / "benchmark_report.json").read_text())

    def test_existing_pipeline_runtime_is_imported(self):
        self.write(self.manifest.parent / "execution.json", {"status": "ok", "duration_seconds": 4.25,
                   "telemetry": {"storage_bytes": 400, "storage_scope": "tracked_output_files"}})
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0].update(run_manifest="execution.json", telemetry={})
        self.write(self.manifest, data)
        report = self.run_report()
        telemetry = report["projects"][0]["runs"][0]["telemetry"]
        self.assertEqual(telemetry["elapsed_seconds"], 4.25)
        self.assertEqual(telemetry["origin"], "run_manifest")
        self.assertEqual(telemetry["storage_scope"], "tracked_output_files")

    def test_malformed_rating_rows_fail_with_a_redacted_report(self):
        original = self.read(self.manifest.parent / "ratings.json")
        for field, value in [("inventory", [None]), ("signals", [None]), ("candidates", [None])]:
            with self.subTest(field=field):
                ratings = {**original, field: value}
                self.write(self.manifest.parent / "ratings.json", ratings)
                result = self.cli("run", self.manifest, "--output", self.output)
                self.assertEqual(result.returncode, 1)
                report = self.read(self.output / "benchmark_report.json")
                self.assertEqual(report["status"], "failed")
                self.assertNotIn(self.temp.name, json.dumps(report))

    def test_boolean_intervals_and_malformed_annotation_rows_are_rejected(self):
        annotations = self.read(self.manifest.parent / "annotations.json")
        for clips in [[None], [{**annotations["clips"][0], "start": True}]]:
            with self.subTest(clips=clips):
                self.write(self.manifest.parent / "annotations.json", {**annotations, "clips": clips})
                result = self.cli("run", self.manifest, "--output", self.output)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.read(self.output / "benchmark_report.json")["status"], "failed")

    def test_three_profiles_without_motion_cannot_pass_suite_gate(self):
        data = self.read(self.manifest)
        data["quality_gates"].update(min_precision=0, min_recall=0, min_f1=0)
        project = data["projects"][0]
        project["review"]["origin"] = "human"
        data["projects"] = [{**project, "id": f"project-{index}", "profile": profile}
                            for index, profile in enumerate(["interview", "shop_build", "general_broll"], 1)]
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("motion_event_profile_required", report["suite_gate_failures"])

    def test_pipeline_benchmark_operation_plans_without_writes_and_runs(self):
        sys.path.insert(0, str(ROOT / "src" / "python"))
        from videoedit.pipeline import plan_pipeline, run_pipeline, validate_pipeline
        from videoedit.operations import default_registry
        self.assertIn("run_benchmark", [operation.name for operation in default_registry().list()])
        pipeline = {"name": "benchmark", "requires_modules": ["core.calibration"], "steps": [
            {"id": "benchmark", "operation": "run_benchmark", "params": {"input": str(self.manifest), "output": str(self.output)}}]}
        validate_pipeline(pipeline)
        pipeline_path = self.workspace / "pipeline.json"
        self.write(pipeline_path, pipeline)
        plan = plan_pipeline(str(pipeline_path), str(self.manifest), str(self.output))
        self.assertEqual(plan["steps"][0]["planned_result"]["report"], str(self.output / "benchmark_report.json"))
        self.assertFalse(self.output.exists())
        run_pipeline(str(pipeline_path), str(self.manifest), str(self.output))
        self.assertTrue((self.output / "benchmark_report.json").is_file())

    def test_invoked_rating_imports_generated_run_telemetry(self):
        from unittest.mock import patch
        from videoedit.benchmark import run_benchmark
        data = self.read(self.manifest)
        run = data["projects"][0]["runs"][0]
        run.pop("ratings")
        run["footage"] = "fixture-media"
        def fake_rating(_input, output, _config):
            path = Path(output)
            path.mkdir(parents=True)
            self.write(path / "ratings.json", self.read(self.manifest.parent / "ratings.json"))
            self.write(path / "rating_run.json", {"status": "ok", "telemetry": {
                "elapsed_seconds": 1, "storage_bytes": 123, "storage_scope": "tracked_output_files"}})
        self.write(self.manifest, data)
        with patch("videoedit.benchmark.run_rating", fake_rating):
            run_benchmark(str(self.manifest), str(self.output))
        result = self.read(self.output / "benchmark_report.json")["projects"][0]["runs"][0]
        self.assertEqual(result["telemetry"]["storage_bytes"], 123)
        self.assertEqual(result["telemetry"]["storage_scope"], "tracked_output_files")
        self.assertIn("run_manifest_sha256", result["inputs"])

    def test_review_windows_cannot_claim_time_beyond_known_source_duration(self):
        ratings = self.read(self.manifest.parent / "ratings.json")
        ratings["inventory"][0]["duration"] = 10
        self.write(self.manifest.parent / "ratings.json", ratings)
        result = self.cli("run", self.manifest, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.read(self.output / "benchmark_report.json")["status"], "failed")

    def test_report_records_command_and_provider_fingerprints(self):
        report = self.run_report()
        run = report["projects"][0]["runs"][0]
        self.assertEqual(len(run["inputs"]["command_sha256"]), 64)
        self.assertEqual(run["provider_metadata"], [])

    def test_comparison_distinguishes_model_revisions_with_shared_provenance(self):
        sys.path.insert(0, str(ROOT / "src" / "python"))
        from videoedit.provenance import build_provenance
        artifact = {"schema_version": "videoedit.signal.v1", "status": "ok", "sources": [],
                    "provenance": build_provenance("yolo", "visual_objects", model_name="test", revision="a")}
        artifact_path = self.manifest.parent / "objects.json"
        self.write(artifact_path, artifact)
        data = self.read(self.manifest)
        data["projects"][0]["runs"][0].update(providers=["yolo"], provider_artifacts={"yolo": "objects.json"})
        self.write(self.manifest, data)
        baseline = self.run_report()
        baseline_path = self.workspace / "baseline.json"
        self.write(baseline_path, baseline)
        artifact["provenance"] = build_provenance("yolo", "visual_objects", model_name="test", revision="b")
        self.write(artifact_path, artifact)
        self.run_report()
        result = self.cli("compare", baseline_path, self.output / "benchmark_report.json", "--output", self.workspace / "comparison")
        self.assertEqual(result.returncode, 0, result.stderr)
        comparison = self.read(self.workspace / "comparison" / "benchmark_compare.json")["comparisons"][0]
        self.assertFalse(comparison["provider_changes"][0]["equivalent"])
        self.assertEqual(comparison["provider_changes"][0]["candidate"]["model"]["revision"], "b")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_invokes_rating_from_local_synthetic_footage(self):
        footage = self.workspace / "footage"
        footage.mkdir()
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=160x90:r=10:d=1",
                        "-c:v", "mpeg4", str(footage / "source_a.mp4")], check=True, capture_output=True)
        annotations = self.read(self.manifest.parent / "annotations.json")
        annotations["clips"] = [{"id": "a", "source": "source_a.mp4", "start": 0.1, "end": 0.5, "rating": "select"}]
        self.write(self.manifest.parent / "annotations.json", annotations)
        data = self.read(self.manifest)
        data["projects"][0]["review"]["windows"] = [{"source": "source_a.mp4", "start": 0, "end": 1}]
        data["projects"][0]["runs"] = [{"id": "baseline", "role": "baseline", "footage": str(footage), "providers": []}]
        self.write(self.manifest, data)
        report = self.run_report()
        self.assertGreater(report["projects"][0]["runs"][0]["telemetry"]["elapsed_seconds"], 0)
        self.assertTrue((self.output / ".private" / "dialogue" / "baseline" / "ratings.json").is_file())


if __name__ == "__main__":
    unittest.main()
