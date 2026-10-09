"""Interchange structure and relink metadata; no editor installation required."""

import json
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.edl import export_selection_file, generate_edl, generate_m3u, generate_xml


def media(path="/tmp/a.mp4", fps="30000/1001", timecode="01:00:00:00", audio=None):
    return SimpleNamespace(path=path, status="ok", fps=fps, duration=20.02,
                           width=1920, height=1080, timecode=timecode,
                           audio_streams=audio or [], warnings=[])


class InterchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clips = [{"source": str(self.root / "A & B.mov"), "label": "A < B & C",
                       "start_seconds": 1.001, "end_seconds": 3.003}]

    def timeline(self, clips=None, fps=29.97, info=None):
        from videoedit.handoff import build_handoff_timeline
        with patch("videoedit.handoff.probe_handoff_media", return_value=info or media()) as probe:
            result = build_handoff_timeline(clips or self.clips, "mixed", fps)
        return result, probe

    def test_edl_events_have_standard_columns_and_frame_mode(self):
        text = generate_edl(self.clips, "mixed", 30)
        self.assertIn("FCM: NON-DROP FRAME", text)
        events = [line for line in text.splitlines() if re.match(r"^\d{3}\s", line)]
        self.assertEqual(len(events), 1)
        columns = events[0].split()
        self.assertEqual(len(columns), 8)
        self.assertRegex(columns[1], r"^[A-Z0-9_]{1,8}$")
        self.assertEqual(columns[2:4], ["V", "C"])
        self.assertTrue(all(re.fullmatch(r"\d{2}:\d{2}:\d{2}:\d{2}", value) for value in columns[4:]))

    def test_xml_escapes_names_and_uses_media_clip_items(self):
        root = ET.fromstring(generate_xml(self.clips, "mixed", 29.97))
        item = root.find("sequence/media/video/track/clipitem")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("name"), "A < B & C")
        self.assertEqual(item.findtext("file/pathurl"), Path(self.clips[0]["source"]).resolve().as_uri())
        self.assertEqual(root.findtext("sequence/rate/timebase"), "30")
        self.assertEqual(root.findtext("sequence/rate/ntsc"), "TRUE")

    def test_nonzero_source_timecode_and_native_bounds(self):
        timeline, _ = self.timeline()
        edl = generate_edl(self.clips, "mixed", 29.97, timeline=timeline)
        event = next(line.split() for line in edl.splitlines() if re.match(r"^\d{3}\s", line))
        self.assertEqual(event[4:8], ["01:00:01:00", "01:00:03:00", "00:00:00:00", "00:00:02:00"])
        root = ET.fromstring(generate_xml(self.clips, "mixed", 29.97, timeline=timeline))
        item = root.find("sequence/media/video/track/clipitem")
        self.assertEqual((item.findtext("in"), item.findtext("out")), ("30", "90"))
        self.assertEqual(item.findtext("file/timecode/string"), "01:00:00:00")
        self.assertEqual(item.findtext("file/timecode/frame"), "108000")

    def test_mixed_rate_xml_separates_source_and_sequence_frame_counts(self):
        timeline, _ = self.timeline(fps=30, info=media(fps="24/1", timecode="01:00:00:00"))
        root = ET.fromstring(generate_xml(self.clips, "mixed", 30, timeline=timeline))
        item = root.find("sequence/media/video/track/clipitem")
        self.assertEqual(item.findtext("rate/timebase"), "24")
        self.assertEqual((item.findtext("in"), item.findtext("out")), ("24", "72"))
        self.assertEqual((item.findtext("start"), item.findtext("end")), ("0", "60"))
        self.assertEqual(root.findtext("sequence/duration"), "60")
        with self.assertRaisesRegex(ValueError, "mixed.rate"):
            generate_edl(self.clips, "mixed", 30, timeline=timeline)

    def test_mono_and_stereo_audio_are_linked_to_video(self):
        audio = [{"index": 1, "channels": 2, "sample_rate": 48000, "codec": "pcm_s16le"}]
        timeline, _ = self.timeline(info=media(audio=audio))
        root = ET.fromstring(generate_xml(self.clips, "mixed", 29.97, timeline=timeline))
        video = root.find("sequence/media/video/track/clipitem")
        tracks = root.findall("sequence/media/audio/track")
        self.assertEqual(len(tracks), 2)
        ids = {video.get("id"), *(track.find("clipitem").get("id") for track in tracks)}
        self.assertEqual({link.findtext("linkclipref") for link in video.findall("link")}, ids)
        self.assertEqual(video.findtext("file/media/audio/channelcount"), "2")
        self.assertEqual(video.findtext("file/media/audio/samplecharacteristics/samplerate"), "48000")
        self.assertEqual([track.findtext("clipitem/sourcetrack/trackindex") for track in tracks], ["1", "2"])

    def test_one_probe_per_unique_source_and_stable_unique_reels(self):
        clips = [*self.clips, *self.clips, {**self.clips[0], "source": str(self.root / "other" / "A & B.mov")}]
        timeline, probe = self.timeline(clips)
        self.assertEqual(probe.call_count, 2)
        mapping = timeline.to_dict()["sources"]
        self.assertEqual(mapping[0]["reel"], mapping[1]["reel"])
        self.assertNotEqual(mapping[0]["reel"], mapping[2]["reel"])

    def test_metadata_conflicts_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "source_fps"):
            self.timeline([{**self.clips[0], "source_fps": 24}])

    def test_media_bounds_are_checked(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            self.timeline([{**self.clips[0], "end_seconds": 30}])

    def test_unsupported_audio_and_effects_are_explicit(self):
        timeline, _ = self.timeline([{**self.clips[0], "transition": "dissolve", "speed": 2}],
                                   info=media(audio=[{"index": 1, "channels": 6, "sample_rate": 48000, "codec": "aac"}]))
        metadata = timeline.to_dict()
        self.assertIn("unsupported_audio_layout", metadata["limitations"])
        self.assertIn("transitions_not_exported", metadata["limitations"])
        self.assertIn("retiming_not_exported", metadata["limitations"])
        self.assertFalse(metadata["editor_verified"])

    def test_unknown_media_does_not_fabricate_metadata(self):
        text = generate_xml(self.clips, "mixed", 30)
        root = ET.fromstring(text)
        file = root.find("sequence/media/video/track/clipitem/file")
        self.assertIsNone(file.find("media/video/samplecharacteristics/width"))
        self.assertIsNone(file.find("media/audio"))

    def test_vlc_ranges_are_seconds_not_timestamp_strings(self):
        text = generate_m3u([{"source": "source.mp4", "start": "00:00:01.25", "end": "00:00:02.75"}], "mixed")
        self.assertIn("#EXTVLCOPT:start-time=1.25", text)
        self.assertIn("#EXTVLCOPT:stop-time=2.75", text)
        self.assertIn("#EXTINF:1.5,", text)

    def test_missing_media_exports_are_partial_and_redacted(self):
        selection = self.root / "private-name.json"
        selection.write_text(json.dumps({"fps": 30, "clips": self.clips}))
        paths = export_selection_file(str(selection), str(self.root / "out"), manifest_paths="redacted")
        self.assertEqual(len(paths), 4)
        path = self.root / "out" / "private-name_handoff.json"
        serialized = path.read_text()
        manifest = json.loads(serialized)
        self.assertEqual(manifest["status"], "partial")
        self.assertFalse(manifest["complete"])
        self.assertIn("source_metadata_unavailable", manifest["handoff"]["limitations"])
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("A & B", serialized)
        self.assertNotIn("A%20%26%20B", serialized)

    def test_drop_frame_labels_round_trip_across_minutes_and_hours(self):
        from videoedit.handoff import drop_timecode
        from videoedit.timecode import frame_rate, seconds_to_frames, timecode_to_seconds
        for fps in (29.97, 59.94):
            rate = frame_rate(fps)
            for count in (0, 1, 1799, 1800, 17982, 107892, 2159999):
                with self.subTest(fps=fps, count=count):
                    tc = drop_timecode(count, rate)
                    self.assertEqual(seconds_to_frames(timecode_to_seconds(tc, rate), rate), count)

    def test_drop_frame_edl_and_xml_keep_native_mode(self):
        timeline, _ = self.timeline(info=media(timecode="01:00:00;00"))
        text = generate_edl(self.clips, "mixed", 29.97, timeline=timeline)
        self.assertIn("FCM: DROP FRAME", text)
        event = next(line.split() for line in text.splitlines() if re.match(r"^\d{3}\s", line))
        self.assertEqual(event[4], "01:00:01;00")
        root = ET.fromstring(generate_xml(self.clips, "mixed", 29.97, timeline=timeline))
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/file/timecode/displayformat"), "DF")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/file/timecode/frame"), "107892")

    def test_conflicting_later_declaration_fails_and_equivalent_rates_work(self):
        clips = [{**self.clips[0], "source_fps": 29.97}, {**self.clips[0], "source_fps": "30000/1001"}]
        timeline, _ = self.timeline(clips)
        self.assertEqual(len(timeline.clips), 2)
        for field, value in (("source_timecode", "02:00:00:00"), ("reel", "OTHER")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.timeline([self.clips[0], {**self.clips[0], field: value}])

    def test_reel_collision_is_not_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "reel.*collides"):
            self.timeline([{**self.clips[0], "reel": "CAMERA"},
                           {**self.clips[0], "source": str(self.root / "b.mov"), "reel": "CAMERA"}])

    def test_xml_file_ids_are_unique_definitions_and_audio_links_resolve(self):
        audio = [{"index": 1, "channels": 1, "sample_rate": 48000, "codec": "pcm_s16le"}]
        timeline, _ = self.timeline([*self.clips, *self.clips], info=media(audio=audio))
        root = ET.fromstring(generate_xml([], "mixed", 29.97, timeline=timeline))
        definitions = [node for node in root.iter("file") if len(node)]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(len(root.findall("sequence/media/audio/track")), 1)
        items = {node.get("id") for node in root.iter("clipitem")}
        self.assertTrue(all(link.text in items for link in root.iter("linkclipref")))

    def test_relative_selection_sources_use_document_directory_when_missing_from_cwd(self):
        selection = self.root / "approved.json"
        selection.write_text(json.dumps({"fps": 30, "source": "relative-new-source.mov", "clips": [{"start": 0, "end": 1}]}))
        output = self.root / "out"
        paths = export_selection_file(str(selection), str(output))
        root = ET.fromstring(Path(paths[1]).read_text())
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/file/pathurl"),
                         (self.root / "relative-new-source.mov").resolve().as_uri())

    def test_mixed_rate_export_keeps_xml_and_diagnostic_only_edl(self):
        selection = self.root / "approved.json"
        selection.write_text(json.dumps({"fps": 30, "clips": self.clips}))
        with patch("videoedit.handoff.probe_handoff_media", return_value=media(fps="24/1")) as probe:
            paths = export_selection_file(str(selection), str(self.root / "out"))
        self.assertEqual(probe.call_count, 1)
        self.assertIn("NOT AN IMPORTABLE EDIT", Path(paths[0]).read_text())
        self.assertFalse(any(re.match(r"^\d{3}\s", line) for line in Path(paths[0]).read_text().splitlines()))
        self.assertIsNotNone(ET.fromstring(Path(paths[1]).read_text()).find("sequence/media/video/track/clipitem"))
        manifest = json.loads((self.root / "out" / "approved_handoff.json").read_text())
        self.assertEqual(manifest["status"], "partial")
        self.assertFalse(manifest["handoff"]["edl_supported"])

    def test_playlist_preserves_long_timestamp_precision(self):
        text = generate_m3u([{"source": "source.mp4", "start_seconds": 3600.125,
                              "end_seconds": 3600.875}], "mixed")
        self.assertIn("#EXTVLCOPT:start-time=3600.125", text)
        self.assertIn("#EXTVLCOPT:stop-time=3600.875", text)

    def test_relative_handoff_manifest_does_not_keep_absolute_file_uri(self):
        selection = self.root / "approved.json"
        selection.write_text(json.dumps({"fps": 30, "clips": self.clips}))
        export_selection_file(str(selection), str(self.root / "out"), manifest_paths="relative")
        manifest = json.loads((self.root / "out" / "approved_handoff.json").read_text())
        row = manifest["handoff"]["sources"][0]
        self.assertEqual(row["source"], "../A & B.mov")
        self.assertNotIn("file:///", row["pathurl"])

    def test_ambiguous_relative_media_paths_fail_instead_of_relinking_wrong_source(self):
        from videoedit.handoff import build_handoff_timeline
        with patch("videoedit.handoff.Path.exists", return_value=True):
            with self.assertRaisesRegex(ValueError, "ambiguous relative"):
                build_handoff_timeline([{"source": "duplicate.mov", "start": 0, "end": 1}],
                                       "mixed", 30, base_dir=str(self.root))

    def test_invalid_xml_label_fails_with_a_targeted_error(self):
        for label in ("bad\x00name", "bad\x01name", "bad\ud800name", "bad\uffffname"):
            with self.subTest(label=repr(label)), self.assertRaisesRegex(ValueError, "label"):
                generate_xml([{**self.clips[0], "label": label}], "mixed", 30)

    def test_file_export_rejects_ambiguous_native_smpte_instead_of_shifting_bounds(self):
        selection = self.root / "approved.json"
        clip = {"source": self.clips[0]["source"], "start": "00:00:01:12", "end": "00:00:02:12"}
        selection.write_text(json.dumps({"fps": 30, "clips": [clip]}))
        with patch("videoedit.handoff.probe_handoff_media", return_value=media(fps="24/1")):
            with self.assertRaisesRegex(ValueError, "SMPTE.*source_fps"):
                export_selection_file(str(selection), str(self.root / "out"))
        selection.write_text(json.dumps({"fps": 30, "clips": [{**clip, "source_fps": 24}]}))
        with patch("videoedit.handoff.probe_handoff_media", return_value=media(fps="24/1")):
            paths = export_selection_file(str(selection), str(self.root / "out"))
        root = ET.fromstring(Path(paths[1]).read_text())
        item = root.find("sequence/media/video/track/clipitem")
        self.assertEqual((item.findtext("in"), item.findtext("out")), ("36", "60"))

    def test_numeric_bounds_override_ambiguous_smpte_display_text(self):
        selection = self.root / "approved.json"
        selection.write_text(json.dumps({"fps": 30, "clips": [{**self.clips[0], "start": "00:00:01:12",
                                           "end": "00:00:02:12", "start_seconds": 1.5, "end_seconds": 2.5}]}))
        with patch("videoedit.handoff.probe_handoff_media", return_value=media(fps="24/1")):
            paths = export_selection_file(str(selection), str(self.root / "out"))
        item = ET.fromstring(Path(paths[1]).read_text()).find("sequence/media/video/track/clipitem")
        self.assertEqual((item.findtext("in"), item.findtext("out")), ("36", "60"))

    def test_rounding_at_eof_cannot_add_an_unavailable_video_frame(self):
        info = media(fps="24/1")
        info.duration = 1
        with self.assertRaisesRegex(ValueError, "duration"):
            self.timeline([{**self.clips[0], "start_seconds": 0, "end_seconds": 1 + 0.5 / 24}], 24, info)

    def test_drop_frame_midnight_requires_diagnostic_edl(self):
        timeline, _ = self.timeline([{**self.clips[0], "start_seconds": 0, "end_seconds": 1}],
                                   info=media(timecode="23:59:59;29"))
        self.assertFalse(timeline.edl_supported)
        self.assertIn("edl_unsupported_event_or_timecode_range", timeline.limitations)

    def test_cli_surfaces_partial_and_non_importable_edl_without_changing_return_contract(self):
        from videoedit.cli import main
        selection = self.root / "approved.json"
        selection.write_text(json.dumps({"fps": 30, "clips": self.clips}))
        stdout, stderr = StringIO(), StringIO()
        with patch("videoedit.handoff.probe_handoff_media", return_value=media(fps="24/1")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["export-edl", str(selection), "--output", str(self.root / "out")])
        self.assertEqual(result, 0)
        self.assertIn("Wrote 4 handoff files", stdout.getvalue())
        self.assertIn("Partial handoff", stderr.getvalue())
        self.assertIn("not an importable edit", stderr.getvalue())

    @unittest.skipUnless(importlib.util.find_spec("opentimelineio"), "Optional OTIO readers unavailable")
    def test_independent_otio_readers_preserve_ranges_and_media_urls(self):
        import opentimelineio as otio
        from videoedit.timecode import frame_rate
        required = {"fcp_xml", "cmx_3600"}
        if not required <= set(otio.adapters.available_adapter_names()):
            self.skipTest("Optional FCP/CMX adapters unavailable")
        cases = [("24/1", 24, "01:00:00:00"), ("30000/1001", 29.97, "01:00:00:00"),
                 ("30000/1001", 29.97, "01:00:00;00"), ("60000/1001", 59.94, "01:00:00;00"),
                 ("24/1", 30, "01:00:00:00"), ("24000/1001", 30, "01:00:00:00")]
        for source_rate, fps, tc in cases:
            with self.subTest(source_rate=source_rate, fps=fps, tc=tc):
                audio = [{"index": 1, "channels": 2, "sample_rate": 48000, "codec": "pcm_s16le"}]
                timeline, _ = self.timeline([*self.clips, *self.clips], fps, media(fps=source_rate, timecode=tc, audio=audio))
                xml = otio.adapters.read_from_string(generate_xml([], "mixed", fps, timeline=timeline), adapter_name="fcp_xml")
                self.assertEqual(len(xml.video_tracks()[0]), 2)
                self.assertEqual(len(xml.audio_tracks()), 2)
                for loaded, normalized in zip(xml.video_tracks()[0], timeline.clips):
                    actual = loaded.source_range
                    self.assertEqual(loaded.media_reference.target_url, Path(normalized.source.path).as_uri())
                    self.assertAlmostEqual(actual.start_time.rate, float(frame_rate(source_rate)))
                    self.assertAlmostEqual(actual.start_time.value, normalized.source.timecode_frames + normalized.source_in)
                    self.assertLessEqual(abs(actual.end_time_exclusive().value - normalized.source.timecode_frames - normalized.source_out), 1)
                if timeline.edl_supported:
                    edit = otio.adapters.read_from_string(generate_edl([], "mixed", fps, timeline=timeline),
                                                         adapter_name="cmx_3600", rate=float(timeline.rate))
                    for loaded, normalized in zip(edit.video_tracks()[0], timeline.clips):
                        self.assertEqual(loaded.source_range.start_time.value, normalized.source.timecode_frames + normalized.source_in)
                        self.assertEqual(loaded.source_range.duration.value, normalized.source_out - normalized.source_in)


if __name__ == "__main__":
    unittest.main()
