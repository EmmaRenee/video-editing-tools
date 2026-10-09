"""Selection and delivery timing contracts, independent of an installed editor."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.edl import generate_edl, generate_extract_script, generate_xml, handoff_metadata
from videoedit.content import plan_content_series
from videoedit.models import CandidateClip, SelectionSet
from videoedit.operations import _write_candidate_selections, op_extract_segments
from videoedit.review import _extract_roughcut_clip, create_approval_file
from videoedit.roughcut import clips_from_plan, plan_roughcut
from videoedit.selections import load_selection
from videoedit.timecode import seconds_to_frames, seconds_to_timecode, timecode_to_seconds


class TimecodeTests(unittest.TestCase):
    def test_rounding_carries_into_next_second(self):
        self.assertEqual(seconds_to_timecode(0.999, 30), "00:00:01:00")
        self.assertEqual(seconds_to_timecode(59.999, 24), "00:01:00:00")

    def test_float_derived_half_frame_ties_round_up(self):
        self.assertEqual(seconds_to_timecode(11 / 48, 24), "00:00:00:06")
        self.assertEqual(seconds_to_timecode(59 + 47 / 48, 24), "00:01:00:00")
        self.assertEqual(seconds_to_timecode(11 / 48 - 1e-7, 24), "00:00:00:05")

    def test_float_tolerance_does_not_invent_frames_for_large_integers(self):
        self.assertEqual(seconds_to_frames(2 ** 52, 1), 2 ** 52)
        self.assertEqual(seconds_to_frames(2 ** 56, 1), 2 ** 56)
        self.assertEqual(seconds_to_frames(2 ** 56 + 1, 1), 2 ** 56 + 1)

    def test_finite_large_frame_counts_do_not_need_a_float_conversion(self):
        self.assertEqual(seconds_to_frames(1e308, 30), int(1e308) * 30)

    def test_frame_component_is_not_discarded(self):
        self.assertEqual(timecode_to_seconds("00:00:01:15"), 1.5)
        self.assertEqual(timecode_to_seconds("00:00:01:12", fps=24), 1.5)

    def test_fractional_rates_use_actual_frame_count(self):
        # 30000/1001 media frames, not 30 seconds-counting frames per second.
        self.assertEqual(seconds_to_timecode(3600, 29.97), "00:59:56:12")
        self.assertAlmostEqual(timecode_to_seconds("01:00:00:00", fps=29.97), 3603.6)
        self.assertEqual(seconds_to_timecode(1001, 23.976), "00:16:40:00")

    def test_drop_frame_boundaries_and_invalid_skipped_labels(self):
        self.assertAlmostEqual(timecode_to_seconds("00:01:00;02", fps=29.97), 60.06)
        self.assertAlmostEqual(timecode_to_seconds("00:10:00;00", fps=29.97), 599.9994)
        with self.assertRaisesRegex(ValueError, "drop.frame"):
            timecode_to_seconds("00:01:00;00", fps=29.97)
        with self.assertRaisesRegex(ValueError, "drop.frame"):
            timecode_to_seconds("00:01:00;02", fps=30)

    def test_invalid_rates_and_components_fail_clearly(self):
        for fps in (0, -1, float("nan"), float("inf"), "bad", "1e309"):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                seconds_to_timecode(1, fps)
        for value in ("00:00:00:30", "00:60:00:00", "-01:00:00:00", "00:00:00:-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timecode_to_seconds(value)

    def test_elapsed_timestamps_remain_seconds_not_smpte_labels(self):
        self.assertEqual(timecode_to_seconds("01:00:00.125", fps=29.97), 3600.125)
        self.assertEqual(timecode_to_seconds(1.125), 1.125)

    def test_legacy_nonpadded_timestamps_remain_readable(self):
        self.assertEqual(timecode_to_seconds("0:0:1.25"), 1.25)
        self.assertEqual(timecode_to_seconds("0:0:1:15"), 1.5)

    def test_fraction_rate_and_5994_drop_frame(self):
        self.assertEqual(timecode_to_seconds("00:00:01:12", fps="24/1"), 1.5)
        self.assertAlmostEqual(timecode_to_seconds("00:01:00;04", fps=59.94), 60.06)
        with self.assertRaisesRegex(ValueError, "drop.frame"):
            timecode_to_seconds("00:01:00;03", fps=59.94)


class DeliveryTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def selection(self, clips, fps=30):
        path = self.root / "approved.json"
        path.write_text(json.dumps({"fps": fps, "source": "source.mp4", "clips": clips}))
        return path

    def test_seconds_fields_are_authoritative_and_preserved(self):
        path = self.selection([{"start": "00:00:01", "end": "00:00:02",
                                "start_seconds": 1.125, "end_seconds": 2.875}])
        clip = load_selection(str(path)).clips[0]
        self.assertEqual(clip["start"], "00:00:01.125")
        self.assertEqual(clip["end"], "00:00:02.875")
        self.assertEqual(clip["start_seconds"], 1.125)
        self.assertEqual(clip["end_seconds"], 2.875)

    def test_seconds_only_subsecond_clip_is_valid(self):
        path = self.selection([{"start_seconds": 0.125, "end_seconds": 0.875}])
        clip = load_selection(str(path)).clips[0]
        self.assertEqual(clip["start"], "00:00:00.125")
        self.assertEqual(clip["end"], "00:00:00.875")

    def test_source_frame_rate_is_used_for_smpte_selections(self):
        path = self.selection([{"start": "00:00:01:12", "end": "00:00:02:12",
                                "source_fps": 24}], fps=30)
        clip = load_selection(str(path)).clips[0]
        self.assertEqual(clip["start_seconds"], 1.5)
        self.assertEqual(clip["end_seconds"], 2.5)
        self.assertEqual(clip["start"], "00:00:01.5")

    def test_invalid_selection_values_have_targeted_errors(self):
        for key, value in (("start_seconds", -0.1), ("start_seconds", float("nan")),
                           ("end_seconds", float("inf")), ("start_seconds", True)):
            path = self.selection([{"start_seconds": 0.1, "end_seconds": 2, key: value}])
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "clip 1"):
                load_selection(str(path))
        for fps in (0, -1, "bad", float("nan")):
            path = self.selection([{"start": 0, "end": 2}], fps=fps)
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, "fps"):
                load_selection(str(path))

    def test_extraction_operation_uses_precise_timestamps(self):
        path = self.selection([{"start": "00:00:01", "end": "00:00:02",
                                "start_seconds": 1.125, "end_seconds": 2.875}])
        with patch("videoedit.operations.run_command_check") as run:
            op_extract_segments({}, {"input": str(path), "output": str(self.root / "clips")})
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("-ss") + 1], "00:00:01.125")
        self.assertEqual(args[args.index("-to") + 1], "00:00:02.875")

    def test_extraction_script_prefers_numeric_fields(self):
        script = generate_extract_script([{"source": "source.mp4", "start": "00:00:01",
                                           "end": "00:00:02", "start_seconds": 1.125,
                                           "end_seconds": 2.875}], "source.mp4", str(self.root))
        self.assertIn("-ss 00:00:01.125", script)
        self.assertIn("-to 00:00:02.875", script)

    def test_extraction_script_retains_submillisecond_bounds(self):
        script = generate_extract_script([{"source": "source.mp4", "start_seconds": 0.000125,
                                           "end_seconds": 1.000875}], "source.mp4", str(self.root))
        self.assertIn("-ss 00:00:00.000125", script)
        self.assertIn("-to 00:00:01.000875", script)

    def test_planner_preserves_precision_through_assembly(self):
        path = self.selection([{"start_seconds": 1.125, "end_seconds": 2.875}])
        plan = self.root / "roughcut_plan.json"
        plan_roughcut(str(path), str(plan), handles=0.25, render_mode="render")
        clip = clips_from_plan(str(plan))[0]
        self.assertEqual(clip["start"], "00:00:00.875")
        self.assertEqual(clip["end"], "00:00:03.125")
        with patch("videoedit.review.run_command_check") as run:
            _extract_roughcut_clip("source.mp4", clip, "clip.mp4")
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("-ss") + 1], "00:00:00.875")
        self.assertEqual(args[args.index("-to") + 1], "00:00:03.125")

    def test_legacy_plan_with_decimal_fields_is_not_truncated(self):
        plan = self.root / "legacy_plan.json"
        plan.write_text(json.dumps({"clips": [{"source": "source.mp4", "start": "00:00:01",
                                                "end": "00:00:02", "start_seconds": 1.25,
                                                "end_seconds": 2.75}]}))
        clip = clips_from_plan(str(plan))[0]
        self.assertEqual(clip["start"], "00:00:01.25")
        self.assertEqual(clip["end"], "00:00:02.75")

    def test_target_duration_trim_keeps_fractional_endpoint(self):
        path = self.selection([{"start_seconds": 1.125, "end_seconds": 5.875}])
        plan = self.root / "roughcut_plan.json"
        plan_roughcut(str(path), str(plan), target_duration=1.25)
        clip = clips_from_plan(str(plan))[0]
        self.assertEqual(clip["end"], "00:00:02.375")

    def test_planner_retains_submillisecond_bounds_and_timeline_rate(self):
        path = self.selection([{"start_seconds": 1 / 60, "end_seconds": 61 / 60}], fps=29.97)
        plan = self.root / "roughcut_plan.json"
        plan_roughcut(str(path), str(plan))
        data = json.loads(plan.read_text())
        self.assertEqual(data["fps"], 29.97)
        self.assertEqual(data["clips"][0]["start_seconds"], 1 / 60)
        self.assertEqual(timecode_to_seconds(clips_from_plan(str(plan))[0]["start"]), 1 / 60)

    def candidate(self):
        return {"id": "a", "source": "source.mp4", "start": "00:00:01", "end": "00:00:02",
                "start_seconds": 1.125, "end_seconds": 2.875, "score": 90,
                "action": "select", "labels": [], "reasons": [], "signals": {}}

    def test_approval_writer_preserves_candidate_numeric_bounds(self):
        ratings = self.root / "ratings.json"
        ratings.write_text(json.dumps({"candidates": [self.candidate()]}))
        approved = self.root / "approved.json"
        create_approval_file(str(ratings), str(approved))
        clip = load_selection(str(approved)).clips[0]
        self.assertEqual(clip["start_seconds"], 1.125)
        self.assertEqual(clip["end_seconds"], 2.875)

    def test_rating_selection_writer_preserves_numeric_bounds(self):
        candidate = CandidateClip.from_dict(self.candidate())
        path = self.root / "selections.json"
        path.write_text(json.dumps(SelectionSet("source.mp4", [candidate]).to_dict()))
        clip = load_selection(str(path)).clips[0]
        self.assertEqual(clip["start_seconds"], 1.125)
        self.assertEqual(clip["end_seconds"], 2.875)

    def test_signal_selection_writer_preserves_numeric_bounds(self):
        paths = _write_candidate_selections([self.candidate()], str(self.root / "selections"))
        clip = load_selection(paths[0]).clips[0]
        self.assertEqual(clip["start_seconds"], 1.125)
        self.assertEqual(clip["end_seconds"], 2.875)

    def test_series_selection_writer_preserves_numeric_bounds(self):
        ratings = self.root / "ratings.json"
        ratings.write_text(json.dumps({"candidates": [self.candidate()]}))
        result = plan_content_series(str(ratings), str(self.root / "series"))
        clip = load_selection(result["selections"]).clips[0]
        self.assertEqual(clip["start_seconds"], 1.125)
        self.assertEqual(clip["end_seconds"], 2.875)

    def test_handoff_mapping_reports_exact_requested_bounds(self):
        clip = {"source": "source.mp4", "start": "00:00:01", "end": "00:00:02",
                "start_seconds": 1.125, "end_seconds": 2.875}
        source = handoff_metadata([clip], 30)["sources"][0]
        self.assertEqual(source["start_seconds"], 1.125)
        self.assertEqual(source["end_seconds"], 2.875)

    def test_edl_source_and_record_frame_spans_agree(self):
        clips = [{"source": "a.mp4", "start_seconds": 1.125, "end_seconds": 2.875},
                 {"source": "b.mp4", "start_seconds": 3.125, "end_seconds": 4.875}]
        lines = [line.split() for line in generate_edl(clips, "mixed", 30).splitlines()
                 if line.startswith("00:")]
        cursor = 0
        for source_in, source_out, record_in, record_out in lines:
            frames = lambda tc: round(timecode_to_seconds(tc, 30) * 30)
            self.assertEqual(frames(record_in), cursor)
            self.assertEqual(frames(source_out) - frames(source_in), frames(record_out) - frames(record_in))
            cursor = frames(record_out)
        self.assertEqual(cursor, 104)

    def test_handoff_mapping_reports_quantized_edl_record_positions(self):
        clips = [{"source": "a.mp4", "start_seconds": 1.125, "end_seconds": 2.875},
                 {"source": "b.mp4", "start_seconds": 1.125, "end_seconds": 2.875}]
        sources = handoff_metadata(clips, 30)["sources"]
        self.assertEqual(sources[1]["timeline_start_seconds"], 52 / 30)
        self.assertEqual(sources[0]["edl_record_out"], "00:00:01:22")
        self.assertEqual(sources[1]["edl_record_in"], "00:00:01:22")

    def test_fractional_xml_limitation_remains_explicit(self):
        metadata = handoff_metadata([{"source": "a.mp4", "start_seconds": 0,
                                      "end_seconds": 1001}], 29.97)
        self.assertIn("fractional_rate_legacy_formatting", metadata["limitations"])

    def test_legacy_xml_sequence_duration_matches_its_track_endpoints(self):
        clips = [{"start_seconds": 1.125, "end_seconds": 2.875},
                 {"start_seconds": 1.125, "end_seconds": 2.875}]
        root = ET.fromstring(generate_xml(clips, "source.mp4", 30))
        sequence = root.find("sequence")
        items = sequence.findall("media/video/track/generatoritem")
        self.assertEqual(int(sequence.findtext("duration")), 106)
        self.assertEqual(sum(int(item.findtext("duration")) for item in items), 106)
        self.assertEqual(int(items[-1].findtext("start")) + int(items[-1].findtext("duration")), 106)

    def test_edl_rejects_ranges_that_collapse_to_zero_frames(self):
        with self.assertRaisesRegex(ValueError, "frame"):
            generate_edl([{"start_seconds": 0, "end_seconds": 0.001}], "a.mp4", 30)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_render_smoke_skips_a_build_without_libx264(self):
        result = subprocess.CompletedProcess([], 0, " V..... mpeg4  MPEG-4 part 2\n", "")
        with patch("subprocess.run", return_value=result) as run, self.assertRaises(unittest.SkipTest):
            self.test_rendered_subsecond_selection_has_expected_frames()
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_rendered_subsecond_selection_has_expected_frames(self):
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                                  text=True, timeout=10)
        if encoders.returncode or not any(len(parts := line.split()) > 1 and parts[1] == "libx264"
                                         for line in encoders.stdout.splitlines()):
            self.skipTest("FFmpeg libx264 encoder unavailable")
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=24",
                        "-t", "2", "-c:v", "libx264", "-y", str(source)], check=True)
        path = self.selection([{"source": str(source), "start_seconds": 0.125, "end_seconds": 0.875}])
        plan = self.root / "roughcut_plan.json"
        plan_roughcut(str(path), str(plan), render_mode="render")
        output = self.root / "clip.mp4"
        _extract_roughcut_clip(str(source), clips_from_plan(str(plan))[0], str(output))
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_frames,duration", "-of", "json", str(output)],
                               capture_output=True, text=True, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        self.assertEqual(int(stream["nb_frames"]), 18)
        self.assertAlmostEqual(float(stream["duration"]), 0.75, places=5)


if __name__ == "__main__":
    unittest.main()
