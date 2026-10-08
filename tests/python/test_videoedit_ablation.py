"""Controlled provider comparisons and truthful processing coverage."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))


class AblationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "tests" / "fixtures" / "benchmarks", self.root / "inputs")
        self.inputs = self.root / "inputs"
        self.manifest = self.inputs / "manifest.json"
        self.output = self.root / "result"

    def read(self, path):
        return json.loads(Path(path).read_text())

    def write(self, path, data):
        Path(path).write_text(json.dumps(data))

    def candidate(self, providers=("yolo",)):
        from videoedit.provenance import build_provenance
        bindings = {"yolo": "visual_objects_path", "openclip": "ai_frame_scores_path", "clip_judge": "ai_clip_judgments_path", "learned_scorer": "learned_scorer_path"}
        kinds = {"yolo": "visual_objects", "openclip": "ai_frame_scores", "clip_judge": "ai_clip_judgments", "learned_scorer": "learned_scorer", "face_person": "face_person_presence"}
        data = self.read(self.manifest)
        ratings = self.read(self.inputs / "ratings.json")
        ratings["candidates"][1].update(start=10, end=14)
        artifacts = {}
        for provider in providers:
            artifact = self.inputs / f"{provider}.json"
            payload = {"schema_version": "videoedit.signal.v1", "artifact_kind": kinds[provider], "status": "ok", "sources": [],
                       "provenance": build_provenance(provider, kinds[provider], model_name="fixture", revision="a",
                                                       library_version="test-1", device="cpu", precision="float32", random_seed=0),
                       "coverage": {"schema_version": "videoedit.coverage.v1", "scope": "temporal", "sources": [
                           {"source": "source_a.mp4", "status": "ok", "expected_units": 3, "processed_units": 3,
                            "intervals": [[0, 30]]}]},
                       "telemetry": {"elapsed_seconds": 1, "cache_hits": 0, "cache_misses": 1}}
            self.write(artifact, payload)
            artifacts[provider] = artifact.name
            if provider == "face_person":
                ratings["config"].setdefault("signal_artifacts", {})["face_person"] = str(artifact)
            else:
                ratings["config"][bindings[provider]] = str(artifact)
        self.write(self.inputs / "candidate.json", ratings)
        data["projects"][0]["runs"].append({"id": "with-signals", "role": "candidate", "ratings": "candidate.json",
                                           "providers": list(providers), "provider_artifacts": artifacts,
                                           "telemetry": {"elapsed_seconds": 3, "storage_bytes": 2048}})
        self.write(self.manifest, data)

    def cli(self):
        return subprocess.run([sys.executable, "-m", "videoedit.cli", "benchmark", "ablate", str(self.manifest),
                               "--output", str(self.output)], env={**os.environ, "PYTHONPATH": str(ROOT / "src" / "python")},
                              capture_output=True, text=True)

    def effect(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read(self.output / "ablation_report.json")["effects"][0]

    def test_ablation_cli_reports_delta_cost_and_synthetic_limits(self):
        self.candidate()
        row = self.effect()
        self.assertEqual(row["status"], "evaluated")
        self.assertEqual(row["delta"]["f1"], 0.5)
        self.assertEqual(row["delta"]["candidate_count"], 0)
        self.assertEqual(row["delta"]["elapsed_seconds"], 1)
        self.assertEqual(row["providers"][0]["coverage"]["temporal_ratio"], 1)
        self.assertEqual(row["providers"][0]["dependency_status"], "artifact_available")
        report = self.read(self.output / "ablation_report.json")
        self.assertEqual(report["scorecards"][0]["recommendation"], "experimental")
        self.assertIn("synthetic_evidence", report["scorecards"][0]["reason_codes"])
        self.assertTrue((self.output / "provider_scorecards.csv").is_file())
        self.assertIn("F1", (self.output / "ablation_report.md").read_text())
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_combinations_do_not_claim_individual_causal_credit(self):
        self.candidate(("openclip", "yolo"))
        row = self.effect()
        self.assertEqual(row["attribution"], "combination_only")
        self.assertEqual([item["id"] for item in row["providers"]], ["openclip", "yolo"])

    def test_native_face_artifact_kind_is_distinct_from_configuration_binding(self):
        self.candidate(("face_person",))
        row = self.effect()
        self.assertEqual(row["status"], "evaluated", row["reason_codes"])
        self.assertEqual(row["providers"][0]["coverage"]["temporal_ratio"], 1)

    def test_empty_partial_and_low_coverage_are_not_evaluated(self):
        self.candidate()
        original = self.read(self.inputs / "yolo.json")
        for kind in ("empty", "partial", "low"):
            with self.subTest(kind=kind):
                data = json.loads(json.dumps(original))
                if kind == "empty":
                    data.pop("coverage")
                elif kind == "partial":
                    data["coverage"]["sources"][0]["status"] = "partial"
                else:
                    data["coverage"]["sources"][0]["intervals"] = [[0, 5]]
                self.write(self.inputs / "yolo.json", data)
                row = self.effect()
                self.assertEqual(row["status"], "not_evaluated")
                self.assertIsNone(row["delta"])

    def test_missing_provider_has_actionable_diagnostic(self):
        self.candidate()
        (self.inputs / "yolo.json").unlink()
        row = self.effect()
        self.assertEqual(row["status"], "not_evaluated")
        self.assertIn("videoedit signals objects", row["providers"][0]["diagnostic"])
        self.assertEqual(row["providers"][0]["dependency_status"], "artifact_unavailable")

    def test_unbound_provider_cannot_receive_quality_credit(self):
        self.candidate()
        ratings = self.read(self.inputs / "candidate.json")
        ratings["config"] = {}
        self.write(self.inputs / "candidate.json", ratings)
        row = self.effect()
        self.assertEqual(row["status"], "not_evaluated")
        self.assertIn("artifact_not_consumed", row["reason_codes"])

    def test_base_scoring_config_change_invalidates_causal_comparison(self):
        self.candidate()
        ratings = self.read(self.inputs / "candidate.json")
        ratings["config"]["min_select_score"] = 99
        self.write(self.inputs / "candidate.json", ratings)
        row = self.effect()
        self.assertEqual(row["status"], "not_evaluated")
        self.assertIn("base_config_changed", row["reason_codes"])

    def test_annotation_only_judge_cannot_claim_selection_improvement(self):
        self.candidate(("clip_judge",))
        row = self.effect()
        self.assertEqual(row["status"], "not_evaluated")
        self.assertIn("annotation_only", row["reason_codes"])

    def test_wrong_artifact_kind_and_undeclared_inputs_are_confounds(self):
        self.candidate()
        artifact = self.read(self.inputs / "yolo.json")
        artifact["artifact_kind"] = "ocr_signage"
        self.write(self.inputs / "yolo.json", artifact)
        self.assertIn("artifact_kind_mismatch", self.effect()["reason_codes"])
        artifact["artifact_kind"] = "visual_objects"
        self.write(self.inputs / "yolo.json", artifact)
        ratings = self.read(self.inputs / "candidate.json")
        ratings["config"]["ai_frame_scores_path"] = "undeclared.json"
        self.write(self.inputs / "candidate.json", ratings)
        self.assertIn("undeclared_optional_inputs", self.effect()["reason_codes"])

    def test_historical_binding_cannot_be_replaced_after_rating(self):
        self.candidate()
        from videoedit.provenance import file_sha256
        manifest = {"status": "ok", "complete": True, "operation": "rate_footage",
                    "inputs": [{"sha256": "0" * 64, "complete": True}],
                    "outputs": [{"sha256": file_sha256(self.inputs / "candidate.json"), "complete": True}]}
        self.write(self.inputs / "run.json", manifest)
        data = self.read(self.manifest)
        data["projects"][0]["runs"][1]["run_manifest"] = "run.json"
        self.write(self.manifest, data)
        self.assertIn("historical_artifact_binding_mismatch", self.effect()["reason_codes"])

    def test_registry_and_dry_run_expose_ablation_output_contract(self):
        from videoedit.modules import operation_enabled
        from videoedit.operations import default_registry
        from videoedit.pipeline import _planned_result, OPERATION_OUTPUTS
        self.assertTrue(operation_enabled("evaluate_provider_ablations", str(self.root)))
        self.assertIn("evaluate_provider_ablations", [item.name for item in default_registry(cwd=str(self.root)).list()])
        planned = _planned_result("evaluate_provider_ablations", {}, str(self.output), {})
        self.assertEqual(set(planned), OPERATION_OUTPUTS["evaluate_provider_ablations"])
        self.assertTrue(planned["scorecards"].endswith("provider_scorecards.csv"))

    def test_policy_rejects_fractional_profile_count(self):
        from videoedit.ablation import evaluate_ablations
        data = self.read(self.manifest)
        data["ablation_policy"] = {"min_profiles_default": 1.5}
        self.write(self.manifest, data)
        with self.assertRaisesRegex(ValueError, "ablation_policy"):
            evaluate_ablations(str(self.manifest), str(self.output))
        from videoedit.benchmark import validate_manifest
        self.assertFalse(validate_manifest(str(self.manifest))["valid"])

    def test_invalid_rating_config_reports_failure_instead_of_crashing(self):
        self.candidate()
        data = self.read(self.inputs / "candidate.json")
        data["config"] = []
        self.write(self.inputs / "candidate.json", data)
        self.assertEqual(self.effect()["status"], "not_evaluated")

    def test_learned_scorer_coverage_comes_from_scored_candidate_rows_not_model(self):
        self.candidate(("learned_scorer",))
        model = self.read(self.inputs / "learned_scorer.json")
        model.pop("coverage")
        self.write(self.inputs / "learned_scorer.json", model)
        data = self.read(self.inputs / "candidate.json")
        # Learning only re-scores existing windows, not the entire video.
        data["candidates"] = self.read(self.inputs / "ratings.json")["candidates"]
        for clip in data["candidates"]:
            clip.setdefault("signals", {})["learned_score"] = 60
        self.write(self.inputs / "candidate.json", data)
        row = self.effect()
        self.assertEqual(row["status"], "evaluated")
        self.assertEqual(row["providers"][0]["coverage"]["scope"], "candidate")
        self.assertEqual(row["providers"][0]["coverage"]["unit_ratio"], 1)
        data["candidates"][0]["signals"].pop("learned_score")
        self.write(self.inputs / "candidate.json", data)
        self.assertEqual(self.effect()["status"], "not_evaluated")


class CoverageTests(unittest.TestCase):
    def test_overlapping_intervals_do_not_double_count_and_sources_resolve(self):
        self.assertIsNotNone(importlib.util.find_spec("videoedit.coverage"), "shared coverage contract is missing")
        from videoedit.coverage import assess_coverage
        data = {"schema_version": "videoedit.coverage.v1", "scope": "temporal", "sources": [
            {"source": "folder/a.mp4", "status": "ok", "expected_units": 3, "processed_units": 3,
             "intervals": [[0, 10], [5, 15], [15, 30]]}]}
        result = assess_coverage(data, {"a.mp4": [(0, 30)]}, resolve=lambda value: Path(value).name)
        self.assertEqual(result["covered_seconds"], 30)
        self.assertEqual(result["temporal_ratio"], 1)
        self.assertEqual(result["unit_ratio"], 1)

    def test_full_negative_scan_is_distinct_from_no_processing(self):
        self.assertIsNotNone(importlib.util.find_spec("videoedit.coverage"), "shared coverage contract is missing")
        from videoedit.coverage import assess_coverage, sample_coverage
        row = sample_coverage("a.mp4", 20, [5, 15], [5, 15], 10)
        result = assess_coverage({"schema_version": "videoedit.coverage.v1", "scope": "temporal", "sources": [row]},
                                 {"a.mp4": [(0, 20)]})
        self.assertEqual(result["status"], "ok")
        row["processed_units"] = 0
        row["intervals"] = []
        self.assertEqual(assess_coverage({"schema_version": "videoedit.coverage.v1", "scope": "temporal", "sources": [row]},
                                        {"a.mp4": [(0, 20)]})["status"], "empty")

    def test_processed_units_without_intervals_do_not_cover_source(self):
        from videoedit.coverage import assess_coverage
        coverage = {"schema_version": "videoedit.coverage.v1", "scope": "candidate", "sources": [
            {"source": "a.mp4", "status": "ok", "expected_units": 1, "processed_units": 1, "intervals": []}]}
        self.assertEqual(assess_coverage(coverage, {"a.mp4": [(0, 20)]})["status"], "invalid")
        coverage["sources"][0]["intervals"] = [[30, 40]]
        self.assertEqual(assess_coverage(coverage, {"a.mp4": [(0, 20)]})["source_ratio"], 0)

    def test_submillisecond_timestamp_normalization_does_not_invent_failure(self):
        from videoedit.coverage import sample_coverage
        self.assertEqual(sample_coverage("a.mp4", 1.2345, [0.61725], [0.617], 10)["status"], "ok")


class RecommendationTests(unittest.TestCase):
    def effect(self, profile, delta=0.1, identity="a"):
        return {"project": profile, "profile": profile, "run": "candidate", "status": "evaluated",
                "review_origin": "human", "baseline_status": "ok", "candidate_status": "ok", "reason_codes": [],
                "baseline_binding": "verified", "delta": {"f1": delta, "recall": delta},
                "providers": [{"id": "yolo", "provenance": {"identity_sha256": identity}, "provenance_warnings": [],
                               "binding": "verified", "elapsed_seconds": 1, "coverage": {"scope": "temporal"}}],
                "baseline_telemetry": {"origin": "run_manifest", "elapsed_seconds": 1, "storage_bytes": 1, "storage_scope": "tracked_output_files"},
                "telemetry": {"origin": "run_manifest", "elapsed_seconds": 2, "storage_bytes": 2, "storage_scope": "tracked_output_files"}}

    def cards(self, rows):
        from videoedit.ablation import _scorecards, DEFAULT_POLICY
        return _scorecards(rows, DEFAULT_POLICY)

    def test_three_qualified_profiles_support_default_but_declared_cost_does_not(self):
        rows = [self.effect(profile) for profile in ("interview", "motion_event", "general_broll")]
        self.assertEqual(self.cards(rows)[0]["recommendation"], "default_enablement_supported")
        for row in rows:
            row["telemetry"]["origin"] = "declared"
        self.assertEqual(self.cards(rows)[0]["recommendation"], "experimental")

    def test_harmful_quality_failed_candidates_can_support_removal(self):
        rows = [self.effect(profile, delta=-0.2) for profile in ("interview", "motion_event", "general_broll")]
        for row in rows:
            row["candidate_status"] = "quality_failed"
        self.assertEqual(self.cards(rows)[0]["recommendation"], "removal_supported")

    def test_conflicting_profile_results_and_unverified_binding_do_not_promote(self):
        rows = [self.effect("interview"), self.effect("interview", delta=-0.2)]
        self.assertEqual(self.cards(rows)[0]["recommendation"], "experimental")
        rows = [self.effect("interview")]
        rows[0]["providers"][0]["binding"] = "declared_config"
        self.assertEqual(self.cards(rows)[0]["recommendation"], "experimental")

    def test_model_revisions_are_separate_scorecards(self):
        cards = self.cards([self.effect("interview", identity="a"), self.effect("motion_event", identity="b")])
        self.assertEqual(len(cards), 2)


if __name__ == "__main__":
    unittest.main()
