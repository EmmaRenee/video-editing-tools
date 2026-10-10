"""Run diagnostics, portable paths, and handoff traceability checks."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_benchmark_validates_imported_elapsed_before_measured_override(self):
        from videoedit.benchmark import _telemetry
        for elapsed in ("private-invalid", True, -1, float("nan"), float("inf")):
            with self.subTest(elapsed=elapsed):
                with self.assertRaisesRegex(ValueError, "invalid input manifest telemetry"):
                    _telemetry({}, {"status": "ok", "telemetry": {"elapsed_seconds": elapsed}}, 1.25)

    def test_manifest_success_fingerprints_versions_and_cache(self):
        from videoedit.manifests import RunManifest
        source, output = self.root / "input.json", self.root / "result.json"
        source.write_text('{"input": 1}')
        output.write_text('{"telemetry": {"cache_hits": 2, "cache_misses": 0}}')
        path = self.root / "run.json"
        with RunManifest(str(path), "fixture", inputs=[str(source)], config={"threshold": 4}) as run:
            run.record_step("analysis", "fixture", {}, {"output": str(output)}, 0.1)
        data = json.loads(path.read_text())
        self.assertEqual(data["schema_version"], "videoedit.run_manifest.v1")
        self.assertEqual(data["status"], "ok")
        self.assertIn("package_version", data["environment"])
        self.assertIn("ffmpeg", data["environment"]["tools"])
        self.assertEqual(len(data["config_sha256"]), 64)
        self.assertEqual(len(data["inputs"][0]["sha256"]), 64)
        self.assertEqual(data["steps"][0]["cache_status"], "cached")
        self.assertEqual(data["telemetry"]["cache_hits"], 2)
        self.assertEqual(data["outputs"][0]["complete"], True)

    def test_step_artifacts_are_fingerprinted_once(self):
        from videoedit import manifests
        output = self.root / "result.json"
        output.write_text('{"telemetry": {"cache_hits": 1, "cache_misses": 0}}')
        with manifests.RunManifest(str(self.root / "run.json"), "fixture") as run:
            with patch("videoedit.manifests._artifact", wraps=manifests._artifact) as artifact:
                run.record_step("fixture", "fixture", {}, {"output": str(output)}, 0.1)
                self.assertEqual(artifact.call_count, 1)

    def test_redacted_detector_reuse_counts_are_validated_and_summed(self):
        from videoedit.manifests import RunManifest
        path = self.root / "run.json"
        with RunManifest(str(path), "fixture", path_mode="redacted") as run:
            for value in (0, 2, True, -1, 1.5, "private-path", None):
                run.record_step("fixture", "fixture", {}, {"telemetry": {
                    "cache_hits": 0, "cache_misses": 2, "detector_cache_reuses": value}}, .1)
            run.record_step("unrelated", "fixture", {}, {}, .1)
        data = json.loads(path.read_text())
        self.assertEqual(data["telemetry"]["detector_cache_reuses"], 2)
        self.assertEqual([step.get("detector_cache_reuses") for step in data["steps"]],
                         [0, 2, None, None, None, None, None, None])
        self.assertNotIn("private-path", path.read_text())

    def test_output_sidecar_reuse_context_survives_pipeline_redaction(self):
        from videoedit.manifests import RunManifest
        sidecar = self.root / "private-rating-run.json"
        sidecar.write_text(json.dumps({"status": "ok", "telemetry": {
            "cache_hits": 0, "cache_misses": 3, "detector_cache_reuses": 3,
            "cache_miss_reasons": {"signal_artifacts_changed": 3, "private-source-path": 1}}}))
        path = self.root / "pipeline_run.json"
        with RunManifest(str(path), "pipeline", path_mode="redacted") as run:
            run.record_step("rating", "rate_footage", {}, {"run_manifest": str(sidecar)}, .1)
        data = json.loads(path.read_text())
        for counters in (data["telemetry"], data["steps"][0]):
            self.assertEqual(counters.get("detector_cache_reuses"), 3)
            self.assertEqual(counters["cache_miss_reasons"], {"signal_artifacts_changed": 3})
        self.assertNotIn("private-", path.read_text())
        self.assertNotIn(str(self.root), path.read_text())

    def test_cache_context_stays_with_the_selected_counter_source(self):
        from videoedit.manifests import RunManifest
        sidecar = self.root / "sidecar.json"
        sidecar.write_text(json.dumps({"status": "ok", "telemetry": {
            "cache_hits": 0, "cache_misses": 3, "detector_cache_reuses": 3,
            "cache_miss_reasons": {"signal_artifacts_changed": 3}}}))
        path = self.root / "run.json"
        with RunManifest(str(path), "fixture") as run:
            run.record_step("fixture", "fixture", {}, {"output": str(sidecar),
                            "telemetry": {"cache_hits": 1, "cache_misses": 0}}, .1)
        data = json.loads(path.read_text())
        self.assertEqual(data["telemetry"]["cache_hits"], 1)
        self.assertNotIn("detector_cache_reuses", data["telemetry"])
        self.assertNotIn("cache_miss_reasons", data["telemetry"])

    def test_duplicate_sidecars_do_not_double_count_detector_reuse(self):
        from videoedit.manifests import RunManifest
        sidecars = [self.root / "one.json", self.root / "two.json"]
        for path in sidecars:
            path.write_text(json.dumps({"telemetry": {
                "cache_hits": 0, "cache_misses": 3, "detector_cache_reuses": 3}}))
        path = self.root / "run.json"
        with RunManifest(str(path), "fixture") as run:
            run.record_step("fixture", "fixture", {}, {"outputs": list(map(str, sidecars))}, .1)
        self.assertEqual(json.loads(path.read_text())["telemetry"]["detector_cache_reuses"], 3)

    def test_detector_reuse_above_selected_report_misses_is_not_recorded(self):
        from videoedit.manifests import RunManifest
        path = self.root / "run.json"
        with RunManifest(str(path), "fixture", path_mode="redacted") as run:
            run.record_step("fixture", "fixture", {}, {"telemetry": {
                "cache_hits": 0, "cache_misses": 1, "detector_cache_reuses": 2}}, .1)
        self.assertNotIn("detector_cache_reuses", json.loads(path.read_text())["telemetry"])

    def test_input_paths_and_warning_text_are_not_output_files(self):
        from videoedit.manifests import RunManifest
        source, output = self.root / "source.mp4", self.root / "result.json"
        source.write_bytes(b"fixture input")
        output.write_text('{}')
        with RunManifest(str(self.root / "run.json"), "fixture") as run:
            run.record_step("fixture", "fixture", {}, {"input": str(source), "source": str(source),
                            "warnings": [str(source)], "output": str(output)}, 0.1)
        data = json.loads((self.root / "run.json").read_text())
        self.assertEqual([Path(row["path"]).name for row in data["outputs"]], ["result.json"])

    def test_invalid_json_output_is_not_complete(self):
        from videoedit.manifests import RunManifest
        output = self.root / "broken.json"
        output.write_text('{not valid JSON')
        with RunManifest(str(self.root / "run.json"), "fixture") as run:
            run.record_step("fixture", "fixture", {}, {"output": str(output)}, 0.1)
        data = json.loads((self.root / "run.json").read_text())
        self.assertEqual(data["status"], "partial")
        self.assertFalse(data["outputs"][0]["complete"])

    def test_failed_and_interrupted_runs_never_claim_complete_outputs(self):
        from videoedit.manifests import RunManifest
        for error, status in [(ValueError("private token=secret"), "error"), (KeyboardInterrupt(), "interrupted")]:
            with self.subTest(status=status):
                path = self.root / f"{status}.json"
                with self.assertRaises(type(error)):
                    with RunManifest(str(path), "fixture", path_mode="redacted"):
                        raise error
                data = json.loads(path.read_text())
                self.assertEqual(data["status"], status)
                self.assertEqual(data["outputs"], [])
                self.assertFalse(data["complete"])
                self.assertNotIn("secret", path.read_text())

    def test_relative_and_redacted_paths_are_explicit(self):
        from videoedit.manifests import RunManifest
        source = self.root / "private-customer.json"
        source.write_text('{"private": "private transcript"}')
        for mode in ("relative", "redacted"):
            path = self.root / f"run-{mode}.json"
            with RunManifest(str(path), "fixture", inputs=[str(source)], path_mode=mode) as run:
                run.legacy(input=str(source), output=str(self.root), description="private transcript")
            data = json.loads(path.read_text())
            self.assertEqual(data["path_mode"], mode)
            self.assertNotIn(str(self.root), path.read_text())
            if mode == "relative":
                self.assertEqual(data["input"], "private-customer.json")
            else:
                self.assertNotIn("private-customer", path.read_text())
                self.assertNotIn("private transcript", path.read_text())

    def test_relative_paths_on_other_drives_cannot_abort_manifest_writes(self):
        from videoedit.manifests import RunManifest
        source = self.root / "input.json"
        source.write_text('{}')
        path = self.root / "relative.json"
        with patch("videoedit.manifests.os.path.relpath", side_effect=ValueError("path is on another drive")):
            with RunManifest(str(path), "fixture", inputs=[str(source)], path_mode="relative"):
                pass
        data = json.loads(path.read_text())
        self.assertEqual(data["status"], "ok")
        self.assertTrue(Path(data["inputs"][0]["path"]).is_absolute())

    def pipeline(self):
        path = self.root / "pipeline.json"
        path.write_text(json.dumps({"name": "fixture", "steps": [{"name": "inventory", "operation": "inventory"}]}))
        return path

    def test_pipeline_interrupt_has_terminal_diagnostic_manifest(self):
        from videoedit.pipeline import run_pipeline
        from videoedit.operations import OperationRegistry
        registry = OperationRegistry()
        def interrupted(_context, _params):
            raise KeyboardInterrupt()
        registry.register("inventory", "fixture", interrupted)
        output = self.root / "output"
        with self.assertRaises(KeyboardInterrupt):
            run_pipeline(str(self.pipeline()), str(self.root), str(output), registry=registry)
        data = json.loads((output / "pipeline_run.json").read_text())
        self.assertEqual(data["status"], "interrupted")
        self.assertEqual(data["steps"][0]["status"], "interrupted")
        self.assertFalse(data["complete"])

    def test_pipeline_validation_failure_is_recorded_before_steps(self):
        from videoedit.pipeline import run_pipeline
        pipeline = self.root / "bad.json"
        pipeline.write_text('{"steps": [{}]}')
        output = self.root / "output"
        with self.assertRaises(ValueError):
            run_pipeline(str(pipeline), str(self.root), str(output))
        data = json.loads((output / "pipeline_run.json").read_text())
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["outputs"], [])

    def test_pipeline_preserves_legacy_fields_and_redacts_opt_in(self):
        from videoedit.pipeline import run_pipeline
        output = self.root / "output"
        run_pipeline(str(self.pipeline()), str(self.root), str(output), manifest_paths="redacted")
        text = (output / "pipeline_run.json").read_text()
        data = json.loads(text)
        for key in ["pipeline", "input", "output", "steps", "results", "duration_seconds", "status"]:
            self.assertIn(key, data)
        self.assertNotIn(str(self.root), text)
        self.assertEqual(data["status"], "ok")
        self.assertIn("schema_version", data)

    def test_dry_run_resolves_sidecar_references_without_writing_outputs(self):
        from videoedit.pipeline import plan_pipeline
        pipeline = self.root / "sidecars.json"
        pipeline.write_text(json.dumps({"steps": [
            {"name": "rating", "operation": "rate_footage"},
            {"name": "audit", "operation": "compare_benchmarks", "input": "${rating.run_manifest}",
             "params": {"candidate": "${rating.run_manifest}"}}]}))
        output = self.root / "dry-run"
        plan = plan_pipeline(str(pipeline), str(self.root), str(output))
        expected = str(output / "rating" / "rating_run.json")
        self.assertEqual(plan["steps"][0]["planned_result"]["run_manifest"], expected)
        self.assertEqual(plan["steps"][1]["input"], expected)
        self.assertFalse(output.exists())

    def test_pipeline_propagates_redaction_to_operation_sidecars(self):
        from videoedit.pipeline import run_pipeline
        pipeline = self.root / "delivery.json"
        pipeline.write_text(json.dumps({"steps": [
            {"name": "handoff", "operation": "generate_edl", "input": str(self.selection())},
            {"name": "plan", "operation": "plan_roughcut", "input": str(self.selection()),
             "params": {"output": str(self.root / "plan.json")}}]}))
        output = self.root / "delivery"
        context = run_pipeline(str(pipeline), str(self.root), str(output), manifest_paths="redacted")
        paths = context["results"]["handoff"]["run_manifests"] + [context["results"]["plan"]["run_manifest"]]
        for path in paths:
            data = json.loads(Path(path).read_text())
            self.assertEqual(data["path_mode"], "redacted")
            self.assertNotIn(str(self.root), json.dumps(data))

    def test_failed_media_probe_marks_rating_partial(self):
        from videoedit.rating import run_rating
        footage = self.root / "footage"
        footage.mkdir()
        (footage / "broken.mp4").write_text("not a video")
        output = self.root / "ratings"
        report = run_rating(str(footage), str(output))
        self.assertEqual(report.inventory[0].status, "error")
        manifest = json.loads((output / "rating_run.json").read_text())
        self.assertEqual(manifest["status"], "partial")
        self.assertFalse(manifest["complete"])
        paths = {Path(row["path"]).name for row in manifest["outputs"]}
        self.assertTrue({"inventory.csv", "inventory.md", "review.html"}.issubset(paths))

    def selection(self):
        path = self.root / "approved.json"
        path.write_text(json.dumps({"fps": 29.97, "clips": [
            {"source": str(self.root / "source.mp4"), "start": 1.1, "end": 2.2, "label": "clip-a"}]}))
        return path

    def test_edl_handoff_manifest_records_rounding_and_omissions(self):
        from videoedit.edl import export_selection_file
        output = self.root / "edl"
        paths = export_selection_file(str(self.selection()), str(output), manifest_paths="redacted")
        self.assertEqual(len(paths), 4)
        path = output / "approved_handoff.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["handoff"]["timeline_fps"], 29.97)
        self.assertEqual(data["handoff"]["rounding"]["xml"], "nearest_frame_half_up")
        self.assertIn("source_metadata_unavailable", data["handoff"]["limitations"])
        self.assertFalse(data["handoff"]["editor_verified"])
        self.assertEqual(data["handoff"]["edl_frame_count_mode"], "NON-DROP FRAME")
        self.assertTrue(data["handoff"]["xml_supported"])
        row = data["handoff"]["sources"][0]
        self.assertEqual(row["xml_clip_rate"], "30000/1001")
        self.assertIn("source_in_frames", row)
        self.assertIn("source_out_frames", row)
        self.assertEqual(row["xml_start_delta_seconds"], 0)
        self.assertEqual(row["xml_end_delta_seconds"], 0)
        self.assertNotIn(str(self.root), path.read_text())

    def test_assembly_failure_has_manifest_without_output_claim(self):
        from videoedit.review import assemble
        output = self.root / "rough.mp4"
        with patch("videoedit.review.run_command_check", side_effect=RuntimeError("private failure")):
            with self.assertRaises(RuntimeError):
                assemble(str(self.selection()), str(output), manifest_paths="redacted")
        data = json.loads((self.root / "rough_assembly.json").read_text())
        self.assertEqual(data["status"], "error")
        self.assertFalse(data["complete"])
        self.assertNotIn(str(output), json.dumps(data["outputs"]))

    def test_review_and_roughcut_plan_write_traceable_sidecars(self):
        from videoedit.review import generate_review_assets
        from videoedit.roughcut import plan_roughcut
        ratings = self.root / "ratings.json"
        ratings.write_text(json.dumps({"candidates": [{"id": "a", "source": str(self.root / "missing.mp4"),
                                                       "start": 0, "end": 1, "score": 80, "action": "review"}]}))
        output = self.root / "review"
        result = generate_review_assets(str(ratings), str(output), manifest_paths="redacted")
        self.assertTrue(Path(result["manifest"]).is_file())
        review_run = json.loads((output / "review_run.json").read_text())
        self.assertEqual(review_run["status"], "partial")
        self.assertNotIn(str(self.root), json.dumps(review_run))
        plan = self.root / "roughcut_plan.json"
        plan_roughcut(str(self.selection()), str(plan), handles=0.25, manifest_paths="redacted")
        plan_run = json.loads((self.root / "roughcut_plan_run.json").read_text())
        self.assertEqual(plan_run["status"], "partial")
        self.assertFalse(plan_run["complete"])
        self.assertIn("source_metadata_unavailable", plan_run["handoff"]["limitations"])
        self.assertEqual(plan_run["handoff"]["handles"], 0.25)
        self.assertFalse(plan_run["handoff"]["editor_verified"])

    def test_delivery_cli_accepts_manifest_path_modes(self):
        env = {**__import__("os").environ, "PYTHONPATH": str(ROOT / "src" / "python")}
        result = subprocess.run([sys.executable, "-m", "videoedit.cli", "export-edl", str(self.selection()),
                                 "--output", str(self.root / "edl"), "--manifest-paths", "redacted"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / "edl" / "approved_handoff.json").read_text())["path_mode"], "redacted")

    def test_partial_artifact_cannot_be_a_complete_step_output(self):
        from videoedit.manifests import RunManifest
        artifact = self.root / "partial.json"
        artifact.write_text('{"status": "partial"}')
        with RunManifest(str(self.root / "run.json"), "fixture") as run:
            run.record_step("fixture", "fixture", {}, {"output": str(artifact)}, 0.1)
        data = json.loads((self.root / "run.json").read_text())
        self.assertEqual(data["status"], "partial")
        self.assertFalse(data["complete"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_rating_records_actual_warm_cache_and_input_fingerprints(self):
        from videoedit.rating import run_rating
        footage = self.root / "footage"
        footage.mkdir()
        source = footage / "source.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:r=10:d=1",
                        "-c:v", "mpeg4", str(source)], check=True, capture_output=True)
        output = self.root / "ratings"
        run_rating(str(footage), str(output), manifest_paths="redacted")
        first = json.loads((output / "rating_run.json").read_text())
        self.assertEqual(first["telemetry"]["cache_misses"], 1)
        run_rating(str(footage), str(output), manifest_paths="redacted")
        warm = json.loads((output / "rating_run.json").read_text())
        self.assertEqual(warm["telemetry"]["cache_hits"], 1)
        self.assertEqual(warm["telemetry"]["cache_misses"], 0)
        self.assertTrue(any(row.get("type") == "file" for row in warm["inputs"]))
        self.assertNotIn(str(self.root), json.dumps(warm))

        ratings = json.loads((output / "ratings.json").read_text())
        ratings["candidates"] = [{"id": "a", "source": str(source), "start": 0, "end": 0.5,
                                  "score": 80, "action": "review"}]
        (output / "ratings.json").write_text(json.dumps(ratings))
        from videoedit.review import generate_review_assets
        generate_review_assets(str(output / "ratings.json"), str(self.root / "review"), proxies=True)
        review = json.loads((self.root / "review" / "review_run.json").read_text())
        media = {Path(row["path"]).suffix for row in review["outputs"]}
        self.assertTrue({".jpg", ".mp4"}.issubset(media))


if __name__ == "__main__":
    unittest.main()
