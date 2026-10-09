"""Rough-cut handles and targets must not hide invalid media ranges."""

import json
import os
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.roughcut import clips_from_plan, plan_roughcut
from videoedit.source_info import HandoffMediaInfo


class RoughcutBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.mov"
        self.source.touch()
        self.selection = self.root / "approved.json"
        self.output = self.root / "plan.json"
        self.info = HandoffMediaInfo(str(self.source), "ok", fps="24/1", duration=5.0,
                                     width=160, height=90, timecode="01:00:00:00",
                                     audio_streams=[{"index": 1, "channels": 2,
                                                     "sample_rate": 48000, "codec": "pcm_s16le"}])

    def write_selection(self, clips=None, fps=24):
        clips = clips if clips is not None else [{"source": str(self.source), "start_seconds": 1,
                                                 "end_seconds": 3, "label": "selected"}]
        self.selection.write_text(json.dumps({"fps": fps, "clips": clips}))

    def plan(self, **kwargs):
        with patch("videoedit.handoff.probe_handoff_media", return_value=self.info):
            plan_roughcut(str(self.selection), str(self.output), **kwargs)
        return json.loads(self.output.read_text())

    def run_manifest(self):
        return json.loads((self.root / "plan_run.json").read_text())

    def test_handles_stop_at_known_video_extent(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 0.25,
                               "end_seconds": 4.75}])
        try:
            plan = self.plan(handles=1)
        except ValueError as error:
            self.fail(f"valid selection handles should be clamped, not rejected: {error}")
        clip = plan["clips"][0]
        self.assertEqual((clip["start_seconds"], clip["end_seconds"]), (0, 5))
        self.assertEqual(clip.get("handles_applied"), {"pre": 0.25, "post": 0.25})
        self.assertEqual((clip.get("selection_start_seconds"), clip.get("selection_end_seconds")), (0.25, 4.75))
        self.assertTrue(clip.get("handles_clamped_to_source"))

    def test_invalid_approved_range_is_not_repaired_by_handles(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 1,
                               "end_seconds": 6}])
        with self.assertRaisesRegex(ValueError, "exceeds media duration"):
            self.plan(handles=1)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.run_manifest()["status"], "error")

    def test_subsecond_target_does_not_keep_whole_first_clip(self):
        self.write_selection()
        plan = self.plan(target_duration=0.5)
        self.assertEqual(plan["summary"]["duration"], 0.5)
        self.assertEqual(plan["clips"][0]["end_seconds"], 1.5)
        self.assertTrue(plan["clips"][0].get("target_trimmed"))

    def test_subsecond_remainder_can_use_next_clip(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 0, "end_seconds": 1},
                               {"source": str(self.source), "start_seconds": 3, "end_seconds": 5}])
        plan = self.plan(target_duration=1.5)
        self.assertEqual(len(plan["clips"]), 2)
        self.assertEqual(plan["clips"][1]["end_seconds"], 3.5)
        self.assertEqual(plan["summary"]["duration"], 1.5)

    def test_target_too_short_for_a_frame_is_rejected(self):
        self.write_selection()
        with self.assertRaisesRegex(ValueError, "frame"):
            self.plan(target_duration=0.001)
        self.assertFalse(self.output.exists())

    def test_subframe_remainder_does_not_invalidate_preceding_clips(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 0, "end_seconds": 0.99},
                               {"source": str(self.source), "start_seconds": 3, "end_seconds": 5}])
        try:
            plan = self.plan(target_duration=1)
        except ValueError as error:
            self.fail(f"a subframe remainder should be omitted after valid clips: {error}")
        self.assertEqual(len(plan["clips"]), 1)
        self.assertEqual(plan["summary"]["duration"], 0.99)

    def test_target_trim_updates_applied_handles(self):
        self.write_selection()
        clip = self.plan(handles=0.5, target_duration=2.75)["clips"][0]
        self.assertEqual(clip.get("handles_applied"), {"pre": 0.5, "post": 0.25})
        self.assertTrue(clip.get("target_trimmed"))
        self.assertEqual(clip["end_seconds"], 3.25)

    def test_zero_target_and_zero_clip_limit_produce_empty_plans(self):
        self.write_selection()
        for settings in ({"target_duration": 0}, {"max_clips": 0}):
            with self.subTest(settings=settings):
                plan = self.plan(**settings)
                self.assertEqual(plan["clips"], [])
                self.assertEqual(plan["summary"]["duration"], 0)

    def test_invalid_numeric_controls_fail_without_plan_output(self):
        self.write_selection()
        for field, values in (("handles", [-1, float("nan"), float("inf"), True]),
                              ("target_duration", [-1, float("nan"), float("inf"), True]),
                              ("max_clips", [-1, 1.5, float("inf"), True])):
            for index, value in enumerate(values):
                with self.subTest(field=field, value=value):
                    self.output = self.root / f"{field}_{index}.json"
                    with self.assertRaisesRegex(ValueError, field):
                        self.plan(**{field: value})
                    self.assertFalse(self.output.exists())

    def test_document_relative_source_is_resolved_in_plan(self):
        self.write_selection([{"source": "source.mov", "start_seconds": 1, "end_seconds": 3}])
        clip = self.plan()["clips"][0]
        self.assertEqual(clip["source"], str(self.source))
        self.assertEqual(clips_from_plan(str(self.output))[0]["source"], str(self.source))

    def test_relative_source_ambiguity_is_not_silently_rebound(self):
        other = self.root / "other"
        other.mkdir()
        (other / "source.mov").touch()
        self.write_selection([{"source": "source.mov", "start_seconds": 1, "end_seconds": 3}])
        previous = os.getcwd()
        try:
            os.chdir(other)
            with self.assertRaisesRegex(ValueError, "ambiguous relative"):
                self.plan()
        finally:
            os.chdir(previous)

    def test_metadata_survives_planning_and_loading_for_assembly(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 1, "end_seconds": 3,
                               "source_fps": 24, "source_timecode": "01:00:00:00", "reel": "REEL_1"}])
        self.plan()
        clip = clips_from_plan(str(self.output))[0]
        self.assertEqual(clip.get("source_fps"), "24")
        self.assertEqual(clip.get("source_timecode"), "01:00:00:00")
        self.assertEqual(clip.get("reel"), "REEL_1")
        self.assertEqual((clip.get("start_seconds"), clip.get("end_seconds")), (1, 3))

    def test_conflicting_source_metadata_is_not_dropped(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 1, "end_seconds": 3,
                               "source_fps": 30}])
        with self.assertRaisesRegex(ValueError, "source_fps conflicts"):
            self.plan()

    def test_legacy_plan_smpte_uses_declared_native_rate_for_render_timestamps(self):
        self.output.write_text(json.dumps({"fps": 30, "clips": [
            {"source": str(self.source), "source_fps": 24,
             "start": "00:00:01:12", "end": "00:00:02:12"}]}))
        clip = clips_from_plan(str(self.output))[0]
        self.assertEqual((clip["start"], clip["end"]), ("00:00:01.5", "00:00:02.5"))
        self.assertEqual((clip["start_seconds"], clip["end_seconds"]), (1.5, 2.5))

    def test_mixed_rate_smpte_ambiguity_is_not_hidden_by_normalization(self):
        self.write_selection([{"source": str(self.source), "start": "00:00:01:12",
                               "end": "00:00:03:12"}], fps=30)
        with self.assertRaisesRegex(ValueError, "explicit source_fps"):
            self.plan()

    def test_each_unique_source_is_probed_once_during_planning(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 1, "end_seconds": 2},
                               {"source": str(self.source), "start_seconds": 3, "end_seconds": 4}])
        with patch("videoedit.handoff.probe_handoff_media", return_value=self.info) as probe:
            plan_roughcut(str(self.selection), str(self.output), handles=0.25)
        self.assertEqual(probe.call_count, 1)

    def test_unknown_duration_is_partial_not_claimed_clamped(self):
        self.info = replace(self.info, duration=None, warnings=["video_duration_unavailable"])
        self.write_selection()
        plan = self.plan(handles=0.5)
        self.assertEqual(plan.get("status"), "partial")
        self.assertIsNone(plan["clips"][0].get("source_duration_seconds"))
        self.assertFalse(plan["clips"][0].get("handles_clamped_to_source"))
        self.assertEqual(self.run_manifest()["status"], "partial")
        self.assertFalse(self.run_manifest()["complete"])

    def test_unsupported_edit_features_remain_visible_in_plan_manifest(self):
        self.write_selection([{"source": str(self.source), "start_seconds": 1, "end_seconds": 3,
                               "transition": "dissolve"}])
        self.plan()
        manifest = self.run_manifest()
        self.assertIn("transitions_not_exported", manifest["handoff"]["limitations"])
        self.assertEqual(manifest["status"], "partial")


if __name__ == "__main__":
    unittest.main()
