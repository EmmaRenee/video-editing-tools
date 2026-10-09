import copy
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, asdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "python"))

from videoedit.ffmpeg import CommandResult, run_command


def media_payload():
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mpeg4",
                "codec_tag_string": "mp4v",
                "width": 320,
                "height": 240,
                "r_frame_rate": "30000/1001",
                "avg_frame_rate": "30000/1001",
                "duration": "2.002",
                "disposition": {"attached_pic": 0},
                "tags": {"timecode": "01:02:03:04"},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "channels": 1,
                "sample_rate": "48000",
            },
        ],
        "format": {"duration": "2.002", "tags": {}},
    }


class HandoffSourceInfoTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("videoedit.source_info"),
            "The independent handoff source metadata probe is not implemented",
        )
        self.source_info = importlib.import_module("videoedit.source_info")
        directory = tempfile.TemporaryDirectory(prefix=".source-info-test-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "synthetic source ; $literal.mov")
        with open(self.path, "wb") as handle:
            handle.write(b"synthetic probe fixture")
        self.calls = []

    @contextmanager
    def command_result(self, payload=None, *, stdout=None, returncode=0, failure=None):
        original = self.source_info.run_command

        def fake_command(args, timeout=180):
            self.calls.append((args, timeout))
            if failure is not None:
                raise failure
            output = json.dumps(payload) if stdout is None else stdout
            return CommandResult(args, returncode, output, "PRIVATE_PATH credential=SECRET")

        self.source_info.run_command = fake_command
        try:
            yield
        finally:
            self.source_info.run_command = original

    def probe(self, payload):
        with self.command_result(payload):
            return self.source_info.probe_handoff_media(self.path)

    def assert_unknown(self, info, status="error"):
        self.assertEqual(info.path, self.path)
        self.assertEqual(info.status, status)
        for field in ("fps", "duration", "width", "height", "timecode"):
            self.assertIsNone(getattr(info, field), field)
        self.assertEqual(info.audio_streams, [])
        self.assertTrue(info.warnings)
        warnings = " ".join(info.warnings)
        for private in (self.path, "PRIVATE_PATH", "SECRET", "credential=", "{\"streams\""):
            self.assertNotIn(private, warnings)

    def test_valid_metadata_has_exact_dict_contract_and_frozen_fields(self):
        info = self.probe(media_payload())
        self.assertEqual(asdict(info), {
            "path": self.path,
            "status": "ok",
            "fps": "30000/1001",
            "duration": 2.002,
            "width": 320,
            "height": 240,
            "timecode": "01:02:03:04",
            "audio_streams": [{
                "index": 1, "channels": 1, "sample_rate": 48000, "codec": "pcm_s16le",
            }],
            "warnings": [],
        })
        with self.assertRaises(FrozenInstanceError):
            info.fps = "24/1"

    def test_non_ok_dataclass_defaults_are_unknown_with_independent_lists(self):
        first = self.source_info.HandoffMediaInfo(path=self.path, status="error")
        second = self.source_info.HandoffMediaInfo(path=self.path, status="missing")
        self.assertIsNone(first.fps)
        self.assertIsNone(first.duration)
        self.assertIsNone(first.width)
        self.assertIsNone(first.height)
        self.assertIsNone(first.timecode)
        self.assertEqual(first.audio_streams, [])
        self.assertEqual(first.warnings, [])
        first.warnings.append("test")
        first.audio_streams.append({"index": 1})
        self.assertEqual(second.warnings, [])
        self.assertEqual(second.audio_streams, [])

    def test_command_uses_literal_path_full_json_and_requested_timeout(self):
        with self.command_result(media_payload()):
            info = self.source_info.probe_handoff_media(self.path, timeout=7)
        self.assertEqual(info.status, "ok")
        self.assertEqual(self.calls, [([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
            self.path,
        ], 7)])

    def test_missing_file_does_not_run_ffprobe(self):
        os.unlink(self.path)
        with self.command_result(failure=AssertionError("must not run")):
            info = self.source_info.probe_handoff_media(self.path)
        self.assert_unknown(info, "missing")
        self.assertIn("missing", " ".join(info.warnings).lower())
        self.assertEqual(self.calls, [])

    def test_directory_is_not_a_media_file(self):
        self.path = os.path.dirname(self.path)
        with self.command_result(failure=AssertionError("must not run")):
            info = self.source_info.probe_handoff_media(self.path)
        self.assert_unknown(info, "missing")
        self.assertEqual(self.calls, [])

    def test_invalid_timeout_cannot_disable_the_bound(self):
        for timeout in (0, -1, True, None, 1.5, "60"):
            with self.subTest(timeout=timeout), self.command_result(media_payload()):
                info = self.source_info.probe_handoff_media(self.path, timeout=timeout)
            self.assert_unknown(info)
            self.assertIn("timeout", " ".join(info.warnings).lower())
        self.assertEqual(self.calls, [])

    def test_runner_exceptions_are_actionable_and_sanitized(self):
        cases = [
            (TimeoutError("PRIVATE_PATH credential=SECRET"), "timed out"),
            (FileNotFoundError("PRIVATE_PATH credential=SECRET"), "install"),
            (PermissionError("PRIVATE_PATH credential=SECRET"), "permission"),
            (OSError("PRIVATE_PATH credential=SECRET"), "ffprobe"),
        ]
        for failure, hint in cases:
            with self.subTest(failure=type(failure).__name__), self.command_result(failure=failure):
                info = self.source_info.probe_handoff_media(self.path)
            self.assert_unknown(info)
            self.assertIn(hint, " ".join(info.warnings).lower())

    def test_failed_or_unavailable_ffprobe_does_not_leak_output(self):
        for code, hint in ((1, "ffprobe"), (127, "install")):
            with self.subTest(code=code), self.command_result(
                stdout="PRIVATE_PATH credential=SECRET", returncode=code,
            ):
                info = self.source_info.probe_handoff_media(self.path)
            self.assert_unknown(info)
            self.assertIn(hint, " ".join(info.warnings).lower())

    def test_invalid_json_is_not_ok(self):
        for output in ("", "not JSON PRIVATE_PATH credential=SECRET", '{"streams":'):
            with self.subTest(output=output), self.command_result(stdout=output):
                info = self.source_info.probe_handoff_media(self.path)
            self.assert_unknown(info)
            self.assertIn("json", " ".join(info.warnings).lower())

    def test_excessively_nested_json_returns_a_sanitized_error(self):
        output = "[" * 100_000 + "0" + "]" * 100_000
        with self.command_result(stdout=output):
            info = self.source_info.probe_handoff_media(self.path)
        self.assert_unknown(info)
        self.assertIn("json", " ".join(info.warnings).lower())

    def test_invalid_json_structure_is_not_ok(self):
        payloads = [None, [], "private", {}, {"streams": {}}, {"streams": [None]}]
        payload = media_payload()
        payload["format"] = []
        payloads.append(payload)
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assert_unknown(self.probe(payload))

    def test_first_real_video_excludes_cover_art_and_timecode_video(self):
        payload = media_payload()
        cover = copy.deepcopy(payload["streams"][0])
        cover.update(width=32, height=32, r_frame_rate="90000/1")
        cover["disposition"]["attached_pic"] = 1
        timecode_video = {"codec_type": "video", "codec_tag_string": "tmcd"}
        later_video = copy.deepcopy(payload["streams"][0])
        later_video.update(width=640, r_frame_rate="24/1")
        payload["streams"] = [cover, timecode_video] + payload["streams"] + [later_video]
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual((info.width, info.height, info.fps), (320, 240, "30000/1001"))

    def test_no_real_video_is_not_ok(self):
        for streams in ([], [media_payload()["streams"][1]], [
            {"codec_type": "video", "codec_name": "tmcd"},
            {"codec_type": "video", "disposition": {"attached_pic": 1}},
        ]):
            with self.subTest(streams=streams):
                info = self.probe({"streams": streams, "format": {"duration": "1"}})
                self.assert_unknown(info)
                self.assertIn("video", " ".join(info.warnings).lower())

    def test_unreduced_rational_is_preserved_without_false_rate_warning(self):
        payload = media_payload()
        payload["streams"][0]["r_frame_rate"] = "60000/2002"
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.fps, "60000/2002")
        self.assertEqual(info.warnings, [])

    def test_different_average_rate_warns_of_potential_variable_rate(self):
        payload = media_payload()
        payload["streams"][0]["avg_frame_rate"] = "29900/1001"
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.fps, "30000/1001")
        self.assertIn("potential variable", " ".join(info.warnings).lower())

    def test_unknown_average_rate_does_not_certify_constant_rate(self):
        payload = media_payload()
        payload["streams"][0]["avg_frame_rate"] = "0/0"
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertIn("avg_frame_rate", " ".join(info.warnings))

    def test_invalid_video_fields_return_no_partial_metadata(self):
        cases = [
            ("r_frame_rate", value) for value in
            (None, "0/0", "30/0", "-30/1", "0/1", "29.97", "30/1/1", 30, True, "NaN/1")
        ] + [
            ("avg_frame_rate", "not a rate"),
            ("width", 0), ("width", -1), ("width", True), ("width", 320.5),
            ("height", None), ("height", "240"), ("disposition", []),
            ("disposition", {"attached_pic": "yes"}), ("tags", []),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = media_payload()
                payload["streams"][0][field] = value
                info = self.probe(payload)
                self.assert_unknown(info)
                self.assertIn(field, " ".join(info.warnings))

    def test_missing_required_video_fields_are_not_fabricated(self):
        for field in ("width", "height", "r_frame_rate"):
            with self.subTest(field=field):
                payload = media_payload()
                del payload["streams"][0][field]
                self.assert_unknown(self.probe(payload))

    def test_duration_falls_back_to_video_but_is_not_invented(self):
        payload = media_payload()
        del payload["format"]["duration"]
        payload["streams"][0]["duration"] = "1.001"
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.duration, 1.001)
        del payload["streams"][0]["duration"]
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertIsNone(info.duration)
        self.assertIn("duration", " ".join(info.warnings).lower())

    def test_video_duration_is_not_extended_by_longer_audio(self):
        payload = media_payload()
        payload["format"]["duration"] = "10"
        payload["streams"][0]["duration"] = "1"
        self.assertEqual(self.probe(payload).duration, 1)

    def test_container_only_duration_does_not_claim_video_extent(self):
        payload = media_payload()
        payload["streams"][0].pop("duration", None)
        info = self.probe(payload)
        self.assertIsNone(info.duration)
        self.assertIn("duration", " ".join(info.warnings).lower())

    def test_video_duration_ticks_use_exact_stream_timebase(self):
        payload = media_payload()
        payload["streams"][0].pop("duration", None)
        payload["format"]["duration"] = "10"
        payload["streams"][0].update(duration_ts=60060, time_base="1/30000")
        self.assertAlmostEqual(self.probe(payload).duration, 2.002)

    def test_invalid_duration_returns_no_partial_metadata(self):
        for value in ("NaN", "Infinity", "-1", -1, True, "PRIVATE_PATH credential=SECRET", []):
            with self.subTest(value=value):
                payload = media_payload()
                payload["streams"][0]["duration"] = value
                self.assert_unknown(self.probe(payload))

    def test_video_then_format_then_data_timecode_precedence(self):
        payload = media_payload()
        payload["format"]["tags"]["timecode"] = "02:03:04:05"
        payload["streams"].append({
            "index": 2, "codec_type": "data", "codec_tag_string": "tmcd",
            "tags": {"timecode": "03:04:05;06"},
        })
        self.assertEqual(self.probe(payload).timecode, "01:02:03:04")
        del payload["streams"][0]["tags"]["timecode"]
        self.assertEqual(self.probe(payload).timecode, "02:03:04:05")
        payload["format"]["tags"]["timecode"] = ""
        self.assertEqual(self.probe(payload).timecode, "03:04:05;06")
        payload["streams"][2]["codec_type"] = "video"
        self.assertEqual(self.probe(payload).timecode, "03:04:05;06")

    def test_absent_timecode_is_unknown_not_midnight(self):
        payload = media_payload()
        payload["streams"][0]["tags"] = {}
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertIsNone(info.timecode)
        self.assertIn("timecode", " ".join(info.warnings).lower())

    def test_invalid_timecode_is_actionable_without_echoing_tag(self):
        for value in (123, "PRIVATE_PATH credential=SECRET", "01:60:00:00", "24:00:00:00"):
            with self.subTest(value=value):
                payload = media_payload()
                payload["streams"][0]["tags"]["timecode"] = value
                info = self.probe(payload)
                self.assert_unknown(info)
                self.assertIn("timecode", " ".join(info.warnings).lower())

    def test_all_audio_streams_retain_channels_rate_and_codec(self):
        payload = media_payload()
        payload["streams"].append({
            "index": 4, "codec_type": "audio", "codec_name": "aac",
            "channels": 6, "sample_rate": "44100",
        })
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.audio_streams, [
            {"index": 1, "channels": 1, "sample_rate": 48000, "codec": "pcm_s16le"},
            {"index": 4, "channels": 6, "sample_rate": 44100, "codec": "aac"},
        ])

    def test_missing_optional_audio_metadata_is_unknown_and_warned(self):
        payload = media_payload()
        payload["streams"][1].pop("sample_rate")
        payload["streams"][1].pop("codec_name")
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.audio_streams, [
            {"index": 1, "channels": 1, "sample_rate": None, "codec": None},
        ])
        self.assertIn("sample_rate", " ".join(info.warnings))
        self.assertIn("codec", " ".join(info.warnings).lower())

    def test_unknown_audio_values_are_not_fabricated(self):
        payload = media_payload()
        payload["streams"][1].update(sample_rate="N/A", codec_name="unknown")
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertIsNone(info.audio_streams[0]["sample_rate"])
        self.assertIsNone(info.audio_streams[0]["codec"])
        self.assertTrue(info.warnings)

    def test_invalid_audio_fields_are_not_ok(self):
        cases = [
            ("index", -1), ("index", True), ("index", None),
            ("channels", 0), ("channels", "mono"), ("channels", None),
            ("sample_rate", "0"), ("sample_rate", "48000.5"),
            ("sample_rate", -1), ("sample_rate", True), ("codec_name", {}),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = media_payload()
                payload["streams"][1][field] = value
                info = self.probe(payload)
                self.assert_unknown(info)
                self.assertIn(field, " ".join(info.warnings))

    def test_video_without_audio_does_not_fabricate_audio(self):
        payload = media_payload()
        payload["streams"] = payload["streams"][:1]
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(info.audio_streams, [])

    def test_unknown_data_is_warned_but_not_a_required_model_field(self):
        payload = media_payload()
        payload["streams"].append({"codec_type": "data", "codec_name": "bin_data"})
        info = self.probe(payload)
        self.assertEqual(info.status, "ok")
        self.assertEqual(len(info.audio_streams), 1)
        self.assertIn("data stream", " ".join(info.warnings).lower())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    def test_real_video_extent_is_not_extended_by_long_audio(self):
        result = run_command([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=24:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "pcm_s16le", "-ac", "1",
            "-timecode", "01:00:00:00", self.path,
        ], timeout=30)
        self.assertEqual(result.returncode, 0, "Synthetic unequal-stream MOV generation failed")
        info = self.source_info.probe_handoff_media(self.path, timeout=10)
        self.assertEqual(info.status, "ok", info.warnings)
        self.assertEqual(info.duration, 1)
        from videoedit.handoff import build_handoff_timeline
        with self.assertRaisesRegex(ValueError, "duration"):
            build_handoff_timeline([{"source": self.path, "start": 2, "end": 3}], self.path, 24)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    def test_synthetic_mov_nonzero_timecode_fractional_fps_and_mono_pcm(self):
        result = run_command([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30000/1001",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "1.001", "-c:v", "mpeg4", "-q:v", "5",
            "-c:a", "pcm_s16le", "-ac", "1", "-timecode", "01:02:03:04", self.path,
        ], timeout=30)
        self.assertEqual(result.returncode, 0, "Synthetic MPEG-4/PCM MOV generation failed")
        info = self.source_info.probe_handoff_media(self.path, timeout=10)
        self.assertEqual(info.status, "ok", info.warnings)
        self.assertEqual(info.fps, "30000/1001")
        self.assertAlmostEqual(info.duration, 1.001, places=3)
        self.assertEqual((info.width, info.height), (160, 120))
        self.assertEqual(info.timecode, "01:02:03:04")
        self.assertEqual(info.audio_streams, [
            {"index": 1, "channels": 1, "sample_rate": 48000, "codec": "pcm_s16le"},
        ])


if __name__ == "__main__":
    unittest.main()
