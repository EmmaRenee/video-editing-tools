"""Cached analysis must track its inputs and apply current scoring configuration."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.calibration import generate_config_candidates
from videoedit.config import AnalysisConfig
from videoedit.ffmpeg import CommandResult
from videoedit.models import AudioLevel, MediaAsset
from videoedit.provenance import canonical_hash
from videoedit.rating import _rescore_report, _write_cache, run_rating


class RatingCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.footage = self.root / "footage"
        self.footage.mkdir()
        self.source = self.footage / "source.mp4"
        self.source.write_bytes(b"media-a")
        self.output = self.root / "analysis"
        self.asset = MediaAsset("source.mp4", str(self.source), duration=12, fps=30,
                                width=1920, height=1080, codec="h264", has_audio=True)
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.probe = stack.enter_context(patch("videoedit.rating.probe_media", return_value=self.asset))
        self.scenes = stack.enter_context(patch("videoedit.rating.detect_scene_changes", return_value=([5], None)))
        stack.enter_context(patch("videoedit.rating.detect_silence", return_value=([], None)))
        stack.enter_context(patch("videoedit.rating.analyze_audio_levels", return_value=([AudioLevel(5, -20)], None)))

    def rate(self, config=None, **kwargs):
        return run_rating(str(self.footage), str(self.output), config or AnalysisConfig(), **kwargs)

    def manifest(self):
        return json.loads((self.output / "rating_run.json").read_text())

    def cache_path(self):
        return self.output / ".cache" / "analysis-cache.json"

    def replace_preserving_mtime(self, path, data):
        before = path.stat()
        path.write_bytes(data)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    def assert_miss_reason(self, reason):
        self.assertEqual(self.manifest()["telemetry"].get("cache_miss_reasons"), {reason: 1})

    def test_edited_selected_transcript_invalidates_even_with_same_size_and_mtime(self):
        transcript = self.source.with_suffix(".txt")
        transcript.write_bytes(b"wow")
        first = self.rate()
        self.assertEqual(len(first.signals[0].transcript_hits), 1)
        self.replace_preserving_mtime(transcript, b"nah")
        second = self.rate()
        self.assertEqual(second.signals[0].transcript_hits, [])
        self.assertEqual(self.scenes.call_count, 2)
        self.assert_miss_reason("transcript_changed")

    def test_transcript_appearance_removal_and_directory_priority_invalidate(self):
        self.rate()
        transcript = self.source.with_suffix(".txt")
        transcript.write_text("wow")
        self.assertEqual(len(self.rate().signals[0].transcript_hits), 1)
        self.assert_miss_reason("transcript_changed")
        elsewhere = self.root / "transcripts"
        elsewhere.mkdir()
        (elsewhere / "source.txt").write_text("not a keyword")
        config = AnalysisConfig(transcript_dir=str(elsewhere))
        self.assertEqual(self.rate(config).signals[0].transcript_hits, [])
        self.assert_miss_reason("transcript_changed")
        (elsewhere / "source.txt").unlink()
        self.assertEqual(len(self.rate(config).signals[0].transcript_hits), 1)
        transcript.unlink()
        self.assertEqual(self.rate(config).signals[0].transcript_hits, [])
        self.assert_miss_reason("transcript_changed")

    def test_unselected_or_disabled_transcript_edits_do_not_invalidate(self):
        selected = self.source.with_suffix(".srt")
        selected.write_text("1\n00:00:01,000 --> 00:00:02,000\nwow\n")
        ignored = self.source.with_suffix(".txt")
        ignored.write_text("wow")
        self.rate()
        ignored.write_text("unselected transcript changed")
        self.rate()
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)
        config = AnalysisConfig(transcript_mode="off")
        self.rate(config)
        selected.write_text("selected transcript changed but disabled")
        self.rate(config)
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)

    def test_source_edit_restoring_size_and_mtime_invalidates(self):
        self.rate()
        self.replace_preserving_mtime(self.source, b"media-b")
        self.rate()
        self.assertEqual(self.scenes.call_count, 2)
        self.assert_miss_reason("source_changed")

    def test_decoder_executable_and_version_each_invalidate(self):
        with patch("videoedit.ffmpeg.shutil.which", return_value="/fixture/ffmpeg-one"), \
             patch("videoedit.ffmpeg.run_command", return_value=CommandResult([], 0, "ffmpeg version one", "")):
            self.rate()
        for executable, version in (("/fixture/ffmpeg-two", "one"), ("/fixture/ffmpeg-two", "two")):
            with self.subTest(executable=executable, version=version):
                with patch("videoedit.ffmpeg.shutil.which", return_value=executable), \
                     patch("videoedit.ffmpeg.run_command", return_value=CommandResult([], 0, f"ffmpeg version {version}", "")):
                    self.rate()
                self.assert_miss_reason("decoder_changed")
        self.assertEqual(self.scenes.call_count, 3)

    def test_weight_changes_rescore_cached_signals_and_match_uncached_results(self):
        baseline = self.rate()
        config = AnalysisConfig()
        config.weights["technical"] = 0
        config.audio_spike_floor_db = -10
        warm = self.rate(config)
        self.assertEqual(self.scenes.call_count, 1)
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)
        self.assertEqual(warm.signals[0].scores["technical_score"], 0)
        self.assertEqual(warm.candidates[0].signals["technical_score"], 0)
        self.assertLess(warm.candidates[0].score, baseline.candidates[0].score)
        config.cache = False
        cold = self.rate(config)
        self.assertEqual(warm.signals[0].scores, cold.signals[0].scores)
        self.assertEqual(warm.signals[0].reasons, cold.signals[0].reasons)
        self.assertEqual([clip.to_dict() for clip in warm.candidates], [clip.to_dict() for clip in cold.candidates])

    def test_calibration_rescoring_does_not_use_old_technical_weight(self):
        report = self.rate()
        config = AnalysisConfig()
        config.weights["technical"] = 0
        clips = generate_config_candidates(report.to_dict(), config)
        self.assertEqual(clips[0]["signals"]["technical_score"], 0)

    def test_same_stat_artifact_change_and_direct_ai_path_invalidate(self):
        artifact = self.root / "scores.json"
        artifact.write_text('{"sources":[],"schema_version":"videoedit.ai_frame_scores.v1","count":1}')
        config = AnalysisConfig(ai_frame_scores_path=str(artifact))
        self.rate(config)
        data = artifact.read_bytes().replace(b'"count":1', b'"count":2')
        self.replace_preserving_mtime(artifact, data)
        self.rate(config)
        self.assertEqual(self.scenes.call_count, 1)
        self.assert_miss_reason("signal_artifacts_changed")

    def test_changed_optional_signals_refresh_without_repeating_unchanged_detectors(self):
        objects = self.root / "objects.json"
        ocr = self.root / "ocr.json"
        objects.write_text(json.dumps({"sources": [{"source": str(self.source), "segments": [
            {"class_name": "person", "class_id": 0, "start_seconds": 3,
             "end_seconds": 6, "detection_count": 10}]}]}))
        ocr.write_text(json.dumps({"hits": [{"source": str(self.source), "text": "old sign"}]}))
        config = AnalysisConfig(visual_objects_path=str(objects), signal_artifacts={"ocr_signage": str(ocr)})
        first = self.rate(config)
        self.assertIn("object_person", first.candidates[0].labels)
        self.assertEqual(first.signals[0].advanced_hits[0]["text"], "old sign")
        objects.write_text(objects.read_text().replace('"person"', '"car"'))
        ocr.unlink()
        refreshed = self.rate(config)
        self.assertEqual([hit.class_name for hit in refreshed.signals[0].object_hits], ["car"])
        self.assertEqual(refreshed.signals[0].advanced_hits, [])
        self.assertIn("object_car", refreshed.candidates[0].labels)
        self.assertNotIn("object_person", refreshed.candidates[0].labels)
        self.assertNotIn("ocr_signage", refreshed.candidates[0].labels)
        self.assert_miss_reason("signal_artifacts_changed")
        self.assertEqual(self.scenes.call_count, 1, "Optional JSON changes must not repeat FFmpeg detection")
        self.rate(config)
        self.assertEqual(self.scenes.call_count, 1)
        self.assertEqual(self.manifest()["telemetry"]["cache_hits"], 1)
        config.cache = False
        uncached = self.rate(config)
        self.assertEqual(refreshed.signals[0].to_dict(), uncached.signals[0].to_dict())
        self.assertEqual([clip.to_dict() for clip in refreshed.candidates],
                         [clip.to_dict() for clip in uncached.candidates])

    def test_detector_reuse_is_counted_separately_from_report_hits_and_misses(self):
        self.rate()
        artifact = self.root / "ocr.json"
        artifact.write_text(json.dumps({"hits": [{"source": str(self.source), "text": "private-sign"}]}))
        self.rate(AnalysisConfig(signal_artifacts={"ocr_signage": str(artifact)}), manifest_paths="redacted")
        manifest = self.manifest()
        for counts in (manifest["telemetry"], manifest["steps"][0]):
            self.assertEqual(counts["cache_hits"], 0)
            self.assertEqual(counts["cache_misses"], 1)
            self.assertEqual(counts["detector_cache_reuses"], 1)
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertNotIn("private-sign", json.dumps(manifest))

    def test_removing_all_artifacts_and_changing_weights_reuses_only_detector_measurements(self):
        objects = self.root / "objects.json"
        objects.write_text(json.dumps({"sources": [{"source": str(self.source), "segments": [
            {"class_name": "car", "start_seconds": 3, "end_seconds": 6, "detection_count": 10}]}]}))
        ocr = self.root / "ocr.json"
        ocr.write_text(json.dumps({"hits": [{"source": str(self.source), "text": "old sign"}]}))
        self.rate(AnalysisConfig(visual_objects_path=str(objects), signal_artifacts={"ocr_signage": str(ocr)}))
        config = AnalysisConfig()
        config.weights["technical"] = 0
        refreshed = self.rate(config)
        self.assertEqual(self.scenes.call_count, 1)
        self.assert_miss_reason("signal_artifacts_changed")
        self.assertEqual(refreshed.signals[0].object_hits, [])
        self.assertEqual(refreshed.signals[0].advanced_hits, [])
        self.assertEqual(refreshed.signals[0].scores["technical_score"], 0)
        config.cache = False
        uncached = self.rate(config)
        self.assertEqual(refreshed.signals[0].to_dict(), uncached.signals[0].to_dict())
        self.assertEqual([clip.to_dict() for clip in refreshed.candidates],
                         [clip.to_dict() for clip in uncached.candidates])

    def test_artifact_changes_do_not_mask_changed_detector_inputs(self):
        artifact = self.root / "scores.json"
        for change in ("source", "decoder", "transcript", "scene", "silence", "minimum_silence", "keywords"):
            with self.subTest(change=change):
                self.output = self.root / change
                artifact.write_text('{"sources":[],"schema_version":"videoedit.ai_frame_scores.v1","count":1}')
                config = AnalysisConfig(ai_frame_scores_path=str(artifact))
                self.rate(config)
                before = self.scenes.call_count
                artifact.write_text(artifact.read_text().replace('"count":1', '"count":2'))
                if change == "source":
                    self.source.write_bytes(self.source.read_bytes() + b"changed")
                elif change == "transcript":
                    self.source.with_suffix(".txt").write_text("wow")
                elif change == "scene":
                    config.scene_threshold = .5
                elif change == "silence":
                    config.silence_threshold_db = -40
                elif change == "minimum_silence":
                    config.min_silence_duration = 2
                elif change == "keywords":
                    config.keywords = ["new-keyword"]
                if change == "decoder":
                    with patch("videoedit.rating.decoder_identity", return_value={"changed": True}):
                        self.rate(config)
                else:
                    self.rate(config)
                self.assertEqual(self.scenes.call_count - before, 1)

    def test_unhealthy_or_corrupt_reports_cannot_supply_reused_detector_measurements(self):
        artifact = self.root / "ocr.json"
        for damaged in ("health", "integrity"):
            with self.subTest(damaged=damaged):
                self.output = self.root / damaged
                self.rate()
                before = self.scenes.call_count
                cache = json.loads(self.cache_path().read_text())
                entry = next(iter(cache.values()))
                if damaged == "health":
                    entry["report"]["analysis_status"]["scenes"] = "error"
                    entry["report_sha256"] = canonical_hash(entry["report"])
                else:
                    entry["report"]["scene_changes"] = [999]
                self.cache_path().write_text(json.dumps(cache))
                artifact.write_text(json.dumps({"hits": [{"source": str(self.source), "text": "new sign"}]}))
                report = self.rate(AnalysisConfig(signal_artifacts={"ocr_signage": str(artifact)}))
                self.assertEqual(self.scenes.call_count - before, 1)
                self.assertTrue(report.signals[0].analysis_complete)
                self.assertEqual(report.signals[0].scene_changes, [5])
                self.assertEqual(report.signals[0].advanced_hits[0]["text"], "new sign")

    def test_artifact_mutation_during_reuse_prevents_successful_publication(self):
        self.rate()
        previous = self.cache_path().read_bytes()
        artifact = self.root / "ocr.json"
        artifact.write_text(json.dumps({"hits": [{"source": str(self.source), "text": "new sign"}]}))
        config = AnalysisConfig(signal_artifacts={"ocr_signage": str(artifact)})

        def mutate(report, current_config):
            _rescore_report(report, current_config)
            artifact.write_text('{"hits":[]}')

        with patch("videoedit.rating._rescore_report", side_effect=mutate):
            report = self.rate(config)
        self.assertEqual(self.scenes.call_count, 1)
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(self.cache_path().read_bytes(), previous)

    def test_source_mutation_during_reuse_prunes_the_old_report(self):
        self.rate()
        artifact = self.root / "ocr.json"
        artifact.write_text('{"hits":[]}')

        def mutate(report, current_config):
            _rescore_report(report, current_config)
            self.source.write_bytes(b"changed during reuse")

        with patch("videoedit.rating._rescore_report", side_effect=mutate):
            report = self.rate(AnalysisConfig(signal_artifacts={"ocr_signage": str(artifact)}))
        self.assertEqual(self.scenes.call_count, 1)
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(json.loads(self.cache_path().read_text()), {})

    def test_malformed_cache_entry_is_diagnosed_and_recomputed(self):
        self.rate()
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["report"] = {"unexpected": True}
        self.cache_path().write_text(json.dumps(cache))
        report = self.rate()
        self.assertTrue(report.signals[0].analysis_complete)
        self.assert_miss_reason("cache_entry_invalid")

    def test_invalid_cache_root_is_diagnosed_and_recomputed(self):
        self.rate()
        self.cache_path().write_text('[]')
        self.assertTrue(self.rate().signals[0].analysis_complete)
        self.assert_miss_reason("cache_invalid")

    def test_cache_miss_reasons_survive_redaction_without_paths_or_text(self):
        secret = self.source.with_suffix(".txt")
        secret.write_text("private-customer-secret wow")
        self.rate()
        secret.write_text("private-customer-secret changed")
        self.rate(manifest_paths="redacted")
        self.assert_miss_reason("transcript_changed")
        value = (self.output / "rating_run.json").read_text()
        self.assertNotIn(str(self.root), value)
        self.assertNotIn("private-customer-secret", value)
        self.assertNotIn("source.mp4", value)

    def test_source_change_during_analysis_is_partial_and_not_cacheable(self):
        def change_source(*_args, **_kwargs):
            self.source.write_bytes(b"media changed during analysis")
            return [5], None

        self.scenes.side_effect = change_source
        report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse(self.cache_path().exists())

    def test_cache_disabled_reports_reason_without_reading_or_overwriting_cache(self):
        self.rate()
        before = self.cache_path().read_bytes()
        self.rate(AnalysisConfig(cache=False))
        self.assertEqual(self.cache_path().read_bytes(), before)
        self.assert_miss_reason("cache_disabled")

    def test_policy_and_analysis_parameter_changes_have_distinct_reasons(self):
        self.rate()
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["signature"]["analysis_policy"] = "first_stream_decode_v4"
        self.cache_path().write_text(json.dumps(cache))
        self.rate()
        self.assert_miss_reason("analysis_policy_changed")
        self.rate(AnalysisConfig(scene_threshold=0.5))
        self.assert_miss_reason("analysis_config_changed")

    def test_invalid_json_and_incomplete_cached_reports_are_recomputed(self):
        self.rate()
        self.cache_path().write_text('{not json')
        self.rate()
        self.assert_miss_reason("cache_invalid")
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["report"]["analysis_status"]["audio"] = "error"
        self.cache_path().write_text(json.dumps(cache))
        self.rate()
        self.assert_miss_reason("cached_analysis_incomplete")

    def test_cache_write_interruption_preserves_old_bytes_and_cleans_temporary(self):
        self.rate()
        original = self.cache_path().read_bytes()
        with patch("videoedit.manifests.os.replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                _write_cache(str(self.output), {"new": "not committed"})
        self.assertEqual(self.cache_path().read_bytes(), original)
        self.assertEqual(list(self.cache_path().parent.iterdir()), [self.cache_path()])

    def test_changed_transcript_during_analysis_prevents_cache_publication(self):
        transcript = self.source.with_suffix(".txt")
        transcript.write_text("wow")

        def change_transcript(*_args, **_kwargs):
            transcript.write_text("changed while detectors ran")
            return [5], None

        self.scenes.side_effect = change_transcript
        report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertFalse(self.cache_path().exists())

    def test_artifact_change_during_analysis_keeps_old_cache_and_marks_partial(self):
        artifact = self.root / "scores.json"
        artifact.write_text('{"sources":[],"schema_version":"videoedit.ai_frame_scores.v1","count":1}')
        config = AnalysisConfig(ai_frame_scores_path=str(artifact))
        self.rate(config)
        original_cache = self.cache_path().read_bytes()

        def change_artifact(*_args, **_kwargs):
            artifact.write_text('{"sources":[],"schema_version":"videoedit.ai_frame_scores.v1","count":2}')
            return [5], None

        self.source.write_bytes(b"source changed to require analysis")
        self.scenes.side_effect = change_artifact
        report = self.rate(config)
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(self.cache_path().read_bytes(), original_cache)

    def test_unknown_cache_reason_keys_cannot_escape_in_redacted_manifest(self):
        from videoedit.manifests import RunManifest

        path = self.root / "redacted.json"
        with RunManifest(str(path), "fixture", path_mode="redacted") as manifest:
            manifest.record_step("test", "fixture", {}, {"telemetry": {
                "cache_hits": 0, "cache_misses": 1,
                "cache_miss_reasons": {"transcript_changed": 1, "private_customer_name": 1,
                                       "decoder_changed": True, "source_changed": -1},
            }}, 0)
        self.assertEqual(json.loads(path.read_text())["telemetry"]["cache_miss_reasons"], {"transcript_changed": 1})
        self.assertNotIn("private_customer_name", path.read_text())

    def add_second_source(self):
        second = self.footage / "two.mp4"
        second.write_bytes(b"second source")

        def probe(path, **_kwargs):
            values = vars(self.asset).copy()
            values.update(filename=Path(path).name, filepath=path)
            return MediaAsset(**values)

        self.probe.side_effect = probe
        return second

    def test_interrupted_output_generation_does_not_publish_new_analysis_cache(self):
        with patch("videoedit.rating.write_inventory_outputs", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.rate()
        self.assertEqual(self.manifest()["status"], "interrupted")
        self.assertFalse(self.cache_path().exists())

    def test_partial_multi_source_run_does_not_publish_new_healthy_entries(self):
        second = self.add_second_source()
        original_probe = self.probe.side_effect
        self.probe.side_effect = lambda path, **kwargs: (MediaAsset(second.name, str(second), status="error", error="fixture probe failure")
                                                       if path == str(second) else original_probe(path, **kwargs))
        self.rate()
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse(self.cache_path().exists())

    def test_later_source_analysis_mutation_invalidates_earlier_source(self):
        second = self.add_second_source()

        def scenes(path, **_kwargs):
            if path == str(second):
                self.source.write_bytes(b"changed while second source was being analyzed")
            return [5], None

        self.scenes.side_effect = scenes
        report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse(self.cache_path().exists())

    def test_later_mutation_of_a_cache_hit_is_revalidated_and_pruned(self):
        self.rate()
        second = self.add_second_source()

        def scenes(path, **_kwargs):
            if path == str(second):
                self.source.write_bytes(b"changed after its cache hit")
            return [5], None

        self.scenes.side_effect = scenes
        report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(json.loads(self.cache_path().read_text()), {})

    def test_missing_cached_detector_fields_are_rejected_not_defaulted(self):
        self.rate()
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["report"].pop("scene_changes")
        self.cache_path().write_text(json.dumps(cache))
        report = self.rate()
        self.assertEqual(report.signals[0].scene_changes, [5])
        self.assert_miss_reason("cache_entry_invalid")

    def test_invalid_cached_numeric_metadata_reanalyzes_instead_of_raising(self):
        self.rate()
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["report"]["asset"]["duration"] = "invalid-duration"
        self.cache_path().write_text(json.dumps(cache))
        report = self.rate()
        self.assertEqual(report.signals[0].asset.duration, 12)
        self.assert_miss_reason("cache_entry_invalid")

    def test_same_target_transcript_symlinks_preserve_parser_identity(self):
        target = self.root / "transcript.data"
        target.write_text("wow")
        self.source.with_suffix(".txt").symlink_to(target)
        self.assertEqual(len(self.rate().signals[0].transcript_hits), 1)
        self.source.with_suffix(".srt").symlink_to(target)
        warm = self.rate()
        self.assertEqual(warm.signals[0].transcript_hits, [])
        self.assert_miss_reason("transcript_changed")
        cold = self.rate(AnalysisConfig(cache=False))
        self.assertEqual(warm.candidates[0].score, cold.candidates[0].score)

    def test_source_change_during_output_writing_prevents_cache_commit(self):
        from videoedit.inventory import write_inventory_outputs

        def mutate_source(*args, **kwargs):
            self.source.write_bytes(b"changed before cache commit")
            return write_inventory_outputs(*args, **kwargs)

        with patch("videoedit.rating.write_inventory_outputs", side_effect=mutate_source):
            report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse(self.cache_path().exists())

    def test_detector_content_corruption_is_reanalyzed(self):
        self.rate()
        cache = json.loads(self.cache_path().read_text())
        next(iter(cache.values()))["report"]["scene_changes"] = [9]
        self.cache_path().write_text(json.dumps(cache))
        report = self.rate()
        self.assertEqual(report.signals[0].scene_changes, [5])
        self.assert_miss_reason("cache_entry_invalid")

    def test_interruption_after_output_writes_keeps_existing_cache(self):
        from videoedit.manifests import RunManifest

        self.rate()
        original = self.cache_path().read_bytes()
        self.source.write_bytes(b"changed source requires new analysis")
        write = RunManifest.write

        def interrupt_success(manifest):
            if manifest.data["status"] == "ok":
                raise KeyboardInterrupt
            return write(manifest)

        with patch.object(RunManifest, "write", interrupt_success):
            with self.assertRaises(KeyboardInterrupt):
                self.rate()
        self.assertEqual(self.cache_path().read_bytes(), original)

    def test_partial_run_prunes_stale_entries_without_replacing_other_entries(self):
        self.rate()
        self.source.write_bytes(b"changed source requires new analysis")
        second = self.add_second_source()
        original_probe = self.probe.side_effect
        self.probe.side_effect = lambda path, **kwargs: (MediaAsset(second.name, str(second), status="error", error="fixture failure")
                                                       if path == str(second) else original_probe(path, **kwargs))
        self.rate()
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(json.loads(self.cache_path().read_text()), {})

    def test_source_change_during_final_step_recording_prevents_cache_commit(self):
        from videoedit.manifests import RunManifest

        record = RunManifest.record_step

        def mutate_source(manifest, *args, **kwargs):
            self.source.write_bytes(b"changed during final step recording")
            return record(manifest, *args, **kwargs)

        with patch.object(RunManifest, "record_step", mutate_source):
            report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertEqual(self.manifest()["telemetry"]["cache_misses"], 1)
        self.assertFalse(self.cache_path().exists())

    def test_source_change_during_final_manifest_write_prevents_cache_commit(self):
        from videoedit.manifests import RunManifest

        write = RunManifest.write

        def mutate_source(manifest):
            if manifest.data["status"] == "ok":
                self.source.write_bytes(b"changed during final manifest write")
            return write(manifest)

        with patch.object(RunManifest, "write", mutate_source):
            report = self.rate()
        self.assertFalse(report.signals[0].analysis_complete)
        self.assertEqual(self.manifest()["status"], "partial")
        self.assertFalse(self.cache_path().exists())

    def test_oversized_cached_numeric_metadata_reanalyzes_instead_of_overflowing(self):
        from videoedit.provenance import canonical_hash

        self.rate()
        for refresh_digest in (False, True):
            with self.subTest(refresh_digest=refresh_digest):
                cache = json.loads(self.cache_path().read_text())
                entry = next(iter(cache.values()))
                entry["report"]["asset"]["duration"] = 10 ** 500
                if refresh_digest:
                    entry["report_sha256"] = canonical_hash(entry["report"])
                self.cache_path().write_text(json.dumps(cache))
                report = self.rate()
                self.assertEqual(report.signals[0].asset.duration, 12)
                self.assert_miss_reason("cache_entry_invalid")


if __name__ == "__main__":
    unittest.main()
