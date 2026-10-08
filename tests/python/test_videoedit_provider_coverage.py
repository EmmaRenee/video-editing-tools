"""Processing evidence must not confuse an empty result with successful inference."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.ai import score_frames
from videoedit.models import MediaAsset


class FrameCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"provider contract fixture")
        self.output = self.root / "scores.json"

    def run_provider(self, fail_at=None, matrix=None):
        class Encoder:
            provider_name = "test"
            model_name = "test"
            model_revision = "a"
            def score_images(self, paths, prompts):
                return matrix(paths, prompts) if matrix else [[0.0] * len(prompts) for _ in paths]
        def sampler(_source, timestamp, path, **_kwargs):
            if fail_at is not None and timestamp in fail_at:
                raise ValueError("fixture sampling failure")
            Path(path).write_bytes(b"sample")
        return score_frames(str(self.source), str(self.output), encoder=Encoder(), frame_sampler=sampler,
                            media_probe=lambda source, **_kwargs: MediaAsset(filename="source.mp4", filepath=source, duration=20),
                            sample_interval=10, max_frames_per_file=2)

    def data(self):
        return json.loads(self.output.read_text())

    def test_negative_frames_still_record_processing_coverage(self):
        self.assertEqual(self.run_provider()["status"], "ok")
        data = self.data()
        self.assertEqual(data["coverage"]["sources"][0]["expected_units"], 2)
        self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 2)
        self.assertEqual(data["coverage"]["sources"][0]["intervals"], [[0.0, 10.0], [10.0, 20.0]])
        self.assertEqual(data["sources"][0]["top_score"], 0)
        self.assertEqual(self.run_provider()["telemetry"]["cache_hits"], 1)
        self.assertEqual(self.data()["coverage"], data["coverage"])

    def test_partial_and_failed_sampling_are_not_cache_hits(self):
        self.assertEqual(self.run_provider(fail_at={15})["status"], "partial")
        data = self.data()
        self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 1)
        self.assertEqual(self.run_provider()["telemetry"]["cache_hits"], 0)
        self.output.unlink()
        self.assertEqual(self.run_provider(fail_at={5, 15})["status"], "error")
        self.assertEqual(self.data()["coverage"]["sources"][0]["processed_units"], 0)
        self.assertEqual(self.run_provider()["status"], "ok")

    def test_bad_score_matrix_never_becomes_a_successful_cached_artifact(self):
        for matrix in (lambda paths, prompts: [], lambda paths, prompts: [[0.0] for _ in paths],
                       lambda paths, prompts: [[float("nan")] * len(prompts) for _ in paths]):
            with self.subTest(matrix=matrix):
                if self.output.exists():
                    self.output.unlink()
                self.assertEqual(self.run_provider(matrix=matrix)["status"], "error")
                self.assertEqual(self.data()["coverage"]["sources"][0]["processed_units"], 0)
                self.assertEqual(self.run_provider()["telemetry"]["cache_hits"], 0)


class HeuristicCoverageTests(unittest.TestCase):
    def test_no_input_units_do_not_claim_success(self):
        from videoedit.advanced import cluster_transcript_topics, detect_motorsports_events
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ratings = root / "ratings.json"
            ratings.write_text(json.dumps({"candidates": [], "signals": []}))
            for provider in (cluster_transcript_topics, detect_motorsports_events):
                with self.subTest(provider=provider.__name__):
                    path = root / f"{provider.__name__}.json"
                    provider(str(ratings), str(path))
                    data = json.loads(path.read_text())
                    self.assertEqual(data["status"], "partial")
                    self.assertEqual(data["coverage"]["sources"], [])

    def test_no_positive_events_or_topics_still_records_evaluated_units(self):
        from videoedit.advanced import cluster_transcript_topics, detect_motorsports_events
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ratings = root / "ratings.json"
            ratings.write_text(json.dumps({"candidates": [{"source": "a.mp4", "start": 0, "end": 10, "labels": []}],
                                            "signals": [{"asset": {"filepath": "a.mp4"},
                                                         "transcript_hits": [{"start": 0, "end": 10, "text": "hello world", "keywords": []}]}]}))
            for provider in (cluster_transcript_topics, detect_motorsports_events):
                with self.subTest(provider=provider.__name__):
                    path = root / f"{provider.__name__}.json"
                    provider(str(ratings), str(path))
                    data = json.loads(path.read_text())
                    self.assertEqual(data["count"], 0)
                    self.assertEqual(data["coverage"]["scope"], "candidate")
                    self.assertEqual(data["coverage"]["sources"][0]["processed_units"], 1)
                    self.assertEqual(data["coverage"]["sources"][0]["intervals"], [[0, 10]])
                    self.assertGreaterEqual(data["telemetry"]["elapsed_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
