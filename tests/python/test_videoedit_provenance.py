"""Shared provider provenance and compatibility contract checks."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))


class ProvenanceTests(unittest.TestCase):
    def test_checkpoint_and_prompt_identity_without_private_text(self):
        from videoedit.provenance import build_provenance, validate_artifact
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp) / "model.pt"
            checkpoint.write_bytes(b"synthetic weights")
            data = build_provenance("openclip", "ai_frame_scores", model_name="ViT-B-32",
                                    repository="example/model", revision="revision-a", checkpoint=str(checkpoint),
                                    library="open_clip_torch", library_version="test-1", device="cpu", precision="float32",
                                    profile={"id": "general_broll", "prompts": [{"text": "private prompt sentence"}]},
                                    sampling={"kind": "uniform", "interval_seconds": 10}, random_seed=7,
                                    config={"token": "secret-token", "model": str(checkpoint)})
            self.assertEqual(data["model"]["sha256"], hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            self.assertEqual(data["model"]["revision"], "revision-a")
            self.assertEqual(data["random_seed"], 7)
            self.assertEqual(len(data["prompt_profile"]["sha256"]), 64)
            for secret in [temp, "secret-token", "private prompt sentence"]:
                self.assertNotIn(secret, json.dumps(data))
            result = validate_artifact({"schema_version": "videoedit.ai_frame_scores.v1", "provenance": data})
            self.assertEqual(result["errors"], [])

    def test_unknown_identity_is_warned_and_future_schema_is_rejected(self):
        from videoedit.provenance import build_provenance, validate_artifact
        legacy = validate_artifact({"schema_version": "videoedit.signal.v1", "provider": "legacy"})
        self.assertIn("provenance_missing", legacy["warnings"])
        data = build_provenance("openclip", "ai_frame_scores", model_name="ViT-B-32")
        result = validate_artifact({"schema_version": "videoedit.ai_frame_scores.v1", "provenance": data})
        self.assertIn("model_identity_unverified", result["warnings"])
        future = validate_artifact({"schema_version": "videoedit.ai_frame_scores.v9"})
        self.assertIn("re-generate", " ".join(future["errors"]))
        data["schema_version"] = "videoedit.provenance.v9"
        self.assertTrue(validate_artifact({"schema_version": "videoedit.signal.v1", "provenance": data})["errors"])

    def test_model_revision_changes_identity(self):
        from videoedit.provenance import build_provenance, canonical_hash
        left = build_provenance("openclip", "ai_frame_scores", model_name="test", revision="a")
        right = build_provenance("openclip", "ai_frame_scores", model_name="test", revision="b")
        self.assertNotEqual(canonical_hash(left), canonical_hash(right))

    def test_future_frame_cache_and_discovery_input_require_migration(self):
        from videoedit.ai import score_frames, find_missed_moments
        with tempfile.TemporaryDirectory() as temp:
            scores, ratings = Path(temp) / "scores.json", Path(temp) / "ratings.json"
            scores.write_text('{"schema_version": "videoedit.ai_frame_scores.v99", "sources": []}')
            ratings.write_text('{"candidates": []}')
            with self.assertRaisesRegex(ValueError, "re-generate"):
                score_frames(temp, str(scores), encoder=SimpleNamespace())
            with self.assertRaisesRegex(ValueError, "re-generate"):
                find_missed_moments(str(ratings), str(scores), str(Path(temp) / "missed.json"))

    def test_missed_moments_retain_upstream_model_identity(self):
        from videoedit.ai import find_missed_moments, generate_missed_review
        from videoedit.provenance import build_provenance, validate_artifact, file_sha256
        with tempfile.TemporaryDirectory() as temp:
            scores, ratings, output = [Path(temp) / name for name in ("scores.json", "ratings.json", "missed.json")]
            original = build_provenance("openclip", "ai_frame_scores", model_name="test", revision="revision-a",
                                         profile={"id": "interview", "prompts": []})
            scores.write_text(json.dumps({"schema_version": "videoedit.ai_frame_scores.v1",
                                          "provenance": original, "sources": []}))
            ratings.write_text('{"candidates": []}')
            find_missed_moments(str(ratings), str(scores), str(output))
            data = json.loads(output.read_text())
            self.assertEqual(data["provenance"]["model"]["revision"], "revision-a")
            self.assertEqual(data["provenance"]["artifact_kind"], "ai_missed_moments")
            self.assertNotEqual(data["provenance"]["identity_sha256"], original["identity_sha256"])
            self.assertEqual(data["derived_from"]["artifact_sha256"], file_sha256(scores))
            self.assertEqual(validate_artifact(data)["errors"], [])
            data["schema_version"] = "videoedit.ai_missed_moments.v99"
            output.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "re-generate"):
                generate_missed_review(str(output), str(Path(temp) / "review"))

    def test_native_ocr_version_is_recorded_without_executable_path(self):
        from videoedit.advanced import detect_ocr_signage
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "ocr.json"
            with patch("videoedit.advanced.has_command", return_value=True), \
                 patch("videoedit.advanced._input_files", return_value=[]), \
                 patch("videoedit.advanced.run_command", return_value=SimpleNamespace(returncode=0, stdout="tesseract 5.5.0\n")):
                detect_ocr_signage(temp, str(output))
            self.assertEqual(json.loads(output.read_text())["provenance"]["provider"]["version"], "5.5.0")

    def test_mutated_and_malformed_provenance_is_not_trusted(self):
        from videoedit.provenance import build_provenance, validate_artifact
        data = build_provenance("openclip", "ai_frame_scores", model_name="test", revision="a")
        data["model"]["revision"] = "b"
        result = validate_artifact({"schema_version": "videoedit.ai_frame_scores.v1", "provenance": data})
        self.assertTrue(result["errors"])
        self.assertIn("identity", " ".join(result["errors"]))
        malformed = validate_artifact({"schema_version": []})
        self.assertTrue(malformed["errors"])

    def test_invalid_identity_values_cannot_enter_public_reports(self):
        from videoedit.provenance import build_provenance, canonical_hash, validate_artifact
        for key, value in [("random_seed", "private token"), ("device", "/private/device"), ("sampling", [])]:
            with self.subTest(key=key):
                data = build_provenance("test", "ai_frame_scores")
                data[key] = value
                data["identity_sha256"] = canonical_hash({key: item for key, item in data.items() if key != "identity_sha256"})
                self.assertTrue(validate_artifact({"schema_version": "videoedit.ai_frame_scores.v1", "provenance": data})["errors"])

    def test_frame_artifact_provenance_and_cache_revision_invalidation(self):
        from videoedit.ai import score_frames
        from videoedit.models import MediaAsset
        class Encoder:
            provider_name = "test_encoder"
            model_name = "test-model"
            model_revision = "a"
            provider_version = "test-1"
            device = "cpu"
            precision = "float32"
            calls = 0
            def score_images(self, paths, prompts):
                self.calls += 1
                return [[1.0 / len(prompts)] * len(prompts) for _ in paths]
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / "source.mp4", Path(temp) / "ai.json"
            source.write_bytes(b"not real media; test provider contract only")
            def sampler(_source, _timestamp, path, **_kwargs):
                Path(path).write_bytes(b"fixture frame")
            def probe(path, **_kwargs):
                return MediaAsset(filename=Path(path).name, filepath=path, duration=1)
            encoder = Encoder()
            args = dict(encoder=encoder, frame_sampler=sampler, media_probe=probe, max_frames_per_file=1)
            score_frames(str(source), str(output), **args)
            first = json.loads(output.read_text())
            self.assertEqual(first["provenance"]["model"]["revision"], "a")
            self.assertEqual(first["telemetry"]["cache_misses"], 1)
            score_frames(str(source), str(output), **args)
            cached = json.loads(output.read_text())
            self.assertEqual(cached["sources"][0]["cache_status"], "cached")
            self.assertEqual(cached["telemetry"]["cache_hits"], 1)
            self.assertEqual(encoder.calls, 1)
            encoder.model_revision = "b"
            score_frames(str(source), str(output), **args)
            self.assertEqual(encoder.calls, 2)
            self.assertEqual(json.loads(output.read_text())["provenance"]["model"]["revision"], "b")

    def test_heuristic_and_unavailable_judge_artifacts_have_provenance(self):
        from videoedit.advanced import detect_motorsports_events
        from videoedit.ai import judge_review_clips
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            ratings = Path(temp) / "ratings.json"
            ratings.write_text(json.dumps({"candidates": []}))
            events = Path(temp) / "events.json"
            detect_motorsports_events(str(ratings), str(events))
            self.assertEqual(json.loads(events.read_text())["provenance"]["sampling"]["kind"], "ratings_candidates")
            review = Path(temp) / "review.json"
            review.write_text(json.dumps({"clips": []}))
            output = Path(temp) / "judge.json"
            with patch.dict("os.environ", {}, clear=True):
                result = judge_review_clips(str(review), str(output))
            self.assertEqual(result["status"], "unavailable")
            self.assertIn("provenance", json.loads(output.read_text()))

    def test_signal_loader_rejects_incompatible_schema_but_accepts_legacy(self):
        from videoedit.config import AnalysisConfig
        from videoedit.signals import load_signal_artifacts, validate_signal_artifact
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "signals.json"
            path.write_text(json.dumps({"schema_version": "videoedit.ai_frame_scores.v9", "artifact_kind": "ai_frame_scores", "sources": []}))
            config = AnalysisConfig(ai_frame_scores_path=str(path))
            with self.assertRaisesRegex(ValueError, "re-generate"):
                load_signal_artifacts(config)
            path.write_text(json.dumps({"schema_version": "videoedit.ai_frame_scores.v1", "artifact_kind": "ai_frame_scores", "sources": []}))
            result = validate_signal_artifact(str(path))
            self.assertEqual(result["status"], "ok")
            self.assertIn("provenance_missing", result["warnings"])
            self.assertFalse(any("unexpected schema" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
