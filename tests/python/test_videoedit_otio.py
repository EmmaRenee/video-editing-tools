"""Optional OTIO export contracts, with real SDK readback when installed."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/python"))

from videoedit.handoff import build_handoff_timeline


def info(fps="30000/1001", tc="01:00:00;00", channels=2, duration=20.02):
    return SimpleNamespace(status="ok", fps=fps, duration=duration, width=1920,
                           height=1080, timecode=tc, warnings=[],
                           audio_streams=[{"index": 1, "channels": channels, "sample_rate": 48000}]
                           if channels else [])


class _OtioFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.selection = self.root / "approved.json"
        self.clips = [{"source": str(self.root / "A & B.mov"), "start_seconds": 1.001,
                       "end_seconds": 3.003, "label": "First"}]
        self.selection.write_text(json.dumps({"fps": "30000/1001", "clips": self.clips}))

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("videoedit.otio"), "Optional OTIO adapter is missing")
        return importlib.import_module("videoedit.otio")

    def timeline(self, clips=None, fps="30000/1001", media=None):
        with patch("videoedit.handoff.probe_handoff_media", return_value=media or info()):
            return build_handoff_timeline(clips or self.clips, "mixed", fps)


class OtioBaseTests(_OtioFixture, unittest.TestCase):
    def test_core_cli_import_does_not_load_the_optional_sdk_or_shoot_database(self):
        self.api()
        result = subprocess.run([sys.executable, "-c", "import sys; import videoedit.cli; "
                                 "assert 'opentimelineio' not in sys.modules; "
                                 "assert not any(x.startswith('videoedit.shoot') for x in sys.modules)"],
                                env={**os.environ, "PYTHONPATH": str(ROOT / "src/python")},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_dependency_leaves_existing_output_and_records_failure(self):
        api = self.api()
        output = self.root / "edit.otio"
        output.write_text("existing output")
        with patch("videoedit.otio.importlib.import_module", side_effect=ImportError("SDK absent")):
            with self.assertRaisesRegex(RuntimeError, r"videoedit\[editor\]"):
                api.export_otio_file(self.selection, output)
        self.assertEqual(output.read_text(), "existing output")
        report = json.loads((self.root / "edit_otio_handoff.json").read_text())
        self.assertEqual(report["status"], "error")
        self.assertFalse(report["complete"])

    def test_module_disable_hides_operation_and_blocks_cli(self):
        self.api()
        from videoedit.cli import main
        from videoedit.modules import disable_module
        from videoedit.operations import default_registry
        disable_module("editor.otio", str(self.root))
        self.assertNotIn("generate_otio", [op.name for op in default_registry(cwd=str(self.root)).list()])
        with patch("os.getcwd", return_value=str(self.root)), redirect_stderr(StringIO()) as error:
            result = main(["export-otio", str(self.selection), "--output", str(self.root / "edit.otio")])
        self.assertEqual(result, 1)
        self.assertIn("disabled", error.getvalue())
        self.assertFalse((self.root / "edit.otio").exists())

    def test_module_diagnostics_reports_optional_sdk_without_importing_it(self):
        self.api()
        from videoedit.diagnostics import run_diagnostics
        from videoedit.modules import run_module_diagnostics
        report = run_diagnostics(resolver=lambda name: "/bin/" + name, module_resolver=lambda _: None)
        self.assertEqual(report["status"], "ok")
        self.assertIn("opentimelineio", report["missing_optional"])
        checks = run_module_diagnostics(str(self.root))["checks"]
        self.assertEqual(next(row for row in checks if row["module"] == "editor.otio")["checks"][0]["name"],
                         "opentimelineio")

    def test_export_never_overwrites_input_or_source_with_output_or_manifest(self):
        api = self.api()
        output = self.root / "edit.otio"
        manifest = self.root / "edit_otio_handoff.json"
        original = self.selection.read_bytes()
        manifest.write_bytes(original)
        with self.assertRaises(ValueError):
            api.export_otio_file(manifest, output)
        self.assertEqual(manifest.read_bytes(), original)
        for source in (output, manifest):
            source.write_text("original media")
            self.selection.write_text(json.dumps({"clips": [{"source": str(source), "start": 0, "end": 1}]}))
            with self.assertRaises(ValueError):
                api.export_otio_file(self.selection, output)
            self.assertEqual(source.read_text(), "original media")


@unittest.skipUnless(importlib.util.find_spec("opentimelineio"), "Optional OpenTimelineIO SDK not installed")
class OtioReadbackTests(_OtioFixture, unittest.TestCase):
    def read(self, timeline, name="Example"):
        import opentimelineio as otio
        return otio.adapters.read_from_string(self.api().generate_otio(timeline, name=name), "otio_json")

    def test_native_timecode_available_range_and_offsets_survive_serialization(self):
        timeline = self.read(self.timeline())
        clip = timeline.video_tracks()[0][0]
        self.assertEqual(clip.media_reference.target_url, (self.root / "A & B.mov").resolve().as_uri())
        self.assertEqual(clip.media_reference.available_range.start_time.value, 107892)
        self.assertEqual(clip.media_reference.available_range.duration.value, 600)
        self.assertEqual(clip.source_range.start_time.value, 107922)
        self.assertEqual(clip.source_range.duration.value, 60)
        self.assertAlmostEqual(clip.source_range.duration.rate, 30000 / 1001)
        self.assertEqual(clip.metadata["videoedit"]["source_timecode"], "01:00:00;00")
        self.assertEqual(timeline.metadata["videoedit"]["schema_version"], "videoedit.otio.v1")
        self.assertFalse(timeline.metadata["videoedit"]["editor_verified"])
        self.assertEqual(len(timeline.audio_tracks()), 1)
        self.assertEqual(timeline.audio_tracks()[0][0].source_range, clip.source_range)
        self.assertEqual(timeline.audio_tracks()[0][0].metadata["videoedit"]["audio_channels"], 2)

    def test_mixed_rates_preserve_native_frames_without_silent_retime(self):
        clips = [{"source": str(self.root / "a.mov"), "start": 0, "end": 1 / 24},
                 {"source": str(self.root / "b.mov"), "start": 0, "end": 1 / 30}]
        with patch("videoedit.handoff.probe_handoff_media", side_effect=[info("24", "00:00:00:00"),
                                                                     info("30", "00:00:00:00")]):
            native = build_handoff_timeline(clips, "mixed", 30)
        timeline = self.read(native)
        track = timeline.video_tracks()[0]
        self.assertEqual([clip.source_range.duration.value for clip in track], [1, 1])
        self.assertEqual([clip.source_range.duration.rate for clip in track], [24, 30])
        self.assertEqual([len(clip.effects) for clip in track], [0, 0])
        self.assertAlmostEqual(track[1].range_in_parent().start_time.to_seconds(), 1 / 24)
        self.assertAlmostEqual(timeline.duration().to_seconds(), .075)
        metadata = timeline.metadata["videoedit"]
        self.assertIn("native_duration_differs_from_quantized_record", metadata["limitations"])
        self.assertNotIn("edl_unsupported_mixed_rate", metadata["limitations"])

    def test_native_sub_timeline_frame_cut_is_preserved_but_legacy_export_still_rejects(self):
        import opentimelineio as otio
        clips = [{"source": str(self.root / "high-speed.mov"), "start": 0, "end": 1 / 120}]
        self.selection.write_text(json.dumps({"fps": 24, "clips": clips}))
        output = self.root / "short.otio"
        with patch("videoedit.handoff.probe_handoff_media", return_value=info("120", "00:00:00:00")):
            result = self.api().export_otio_file(self.selection, output)
            with self.assertRaisesRegex(ValueError, "timeline frame"):
                build_handoff_timeline(clips, "mixed", 24)
        timeline = otio.adapters.read_from_file(str(output))
        self.assertEqual(timeline.video_tracks()[0][0].source_range.duration.value, 1)
        self.assertEqual(timeline.video_tracks()[0][0].source_range.duration.rate, 120)
        self.assertAlmostEqual(result["duration_seconds"], 1 / 120)
        self.assertIn("native_duration_differs_from_quantized_record", result["warnings"])

    def test_redaction_keeps_path_free_otio_placement_and_quantization_diagnostics(self):
        self.selection.write_text(json.dumps({"fps": 30, "clips": [
            {"source": str(self.root / "a.mov"), "start": 0, "end": 1 / 24}]}))
        with patch("videoedit.handoff.probe_handoff_media", return_value=info("24", "01:00:00:00")):
            result = self.api().export_otio_file(self.selection, self.root / "mixed.otio", manifest_paths="redacted")
        report = json.loads(Path(result["run_manifest"]).read_text())
        self.assertAlmostEqual(report["otio"]["duration_seconds"], 1 / 24)
        self.assertEqual(report["otio"]["placements"][0]["start_seconds"], 0)
        self.assertAlmostEqual(report["otio"]["placements"][0]["record_quantization_delta_seconds"], 1 / 120)
        self.assertIn("native_duration_differs_from_quantized_record", report["otio"]["limitations"])

    def test_otio_sidecar_never_replaces_legacy_handoff_manifest(self):
        from videoedit.edl import export_selection_file
        handoff = self.root / "handoff"
        with patch("videoedit.handoff.probe_handoff_media", return_value=info()):
            export_selection_file(str(self.selection), str(handoff))
            legacy_path = handoff / "approved_handoff.json"
            original = legacy_path.read_bytes()
            result = self.api().export_otio_file(self.selection, handoff / "approved.otio")
        self.assertNotEqual(Path(result["run_manifest"]), legacy_path)
        self.assertEqual(legacy_path.read_bytes(), original)

    def test_audio_gaps_keep_silent_clip_alignment_and_order(self):
        import opentimelineio as otio
        clips = [{**self.clips[0], "label": str(index), "source": str(self.root / f"{index}.mov")}
                 for index in range(3)]
        with patch("videoedit.handoff.probe_handoff_media", side_effect=[info(channels=1), info(channels=0), info()]):
            native = build_handoff_timeline(clips, "mixed", "30000/1001")
        timeline = self.read(native)
        self.assertEqual([clip.name for clip in timeline.video_tracks()[0]], ["0", "1", "2"])
        audio = timeline.audio_tracks()[0]
        self.assertIsInstance(audio[1], otio.schema.Gap)
        self.assertEqual(audio[2].range_in_parent().start_time.value, 120)
        self.assertEqual(audio[0].metadata["videoedit"]["audio_channels"], 1)
        self.assertEqual(audio[2].metadata["videoedit"]["audio_channels"], 2)

    def test_offline_extent_stays_unknown_and_unsupported_audio_is_not_invented(self):
        missing = info(channels=0, duration=None)
        missing.status, missing.fps, missing.timecode = "missing", None, None
        timeline = self.read(self.timeline(media=missing))
        self.assertIsNone(timeline.video_tracks()[0][0].media_reference.available_range)
        self.assertIn("source_metadata_unavailable", timeline.metadata["videoedit"]["limitations"])
        surround = self.read(self.timeline(media=info(channels=6)))
        self.assertEqual(len(surround.audio_tracks()), 0)
        self.assertIn("unsupported_audio_layout", surround.metadata["videoedit"]["limitations"])

    def test_unsupported_edits_are_reported_not_silently_exported(self):
        clips = [{**self.clips[0], "transition": "dissolve", "speed": 2, "effects": ["grade"]}]
        timeline = self.read(self.timeline(clips))
        self.assertEqual(len(timeline.video_tracks()[0][0].effects), 0)
        self.assertTrue({"transitions_not_exported", "retiming_not_exported", "compound_or_effects_not_exported"}
                        <= set(timeline.metadata["videoedit"]["limitations"]))

    def test_cli_and_operation_export_compatible_roughcut_shapes(self):
        self.api()
        from videoedit.cli import main
        from videoedit.operations import default_registry
        output = self.root / "edit.otio"
        with patch("videoedit.handoff.probe_handoff_media", return_value=info()), redirect_stdout(StringIO()):
            self.assertEqual(main(["export-otio", str(self.selection), "--output", str(output)]), 0)
            result = default_registry().get("generate_otio").func(
                {"output": str(self.root), "approved": str(self.selection)}, {"output": str(self.root / "plan.otio")})
        self.assertTrue(output.is_file())
        self.assertTrue(Path(result["output"]).is_file())
        self.assertEqual(result["clips"], 1)
        report = json.loads(Path(result["run_manifest"]).read_text())
        self.assertTrue(report["complete"])
        self.assertEqual(report["outputs"][0]["method"], "content_sha256")
        self.assertEqual(report["outputs"][0]["sha256"], hashlib.sha256(Path(result["output"]).read_bytes()).hexdigest())

    def test_roughcut_handles_and_document_relative_source_export_at_native_rate(self):
        import opentimelineio as otio
        from videoedit.roughcut import plan_roughcut
        self.selection.write_text(json.dumps({"fps": 30, "source": "relative.mov", "clips": [
            {"start_seconds": .25, "end_seconds": 4.75}]}))
        plan, output = self.root / "roughcut_plan.json", self.root / "plan.otio"
        with patch("videoedit.handoff.probe_handoff_media", return_value=info("24", "01:00:00:00", duration=5)):
            plan_roughcut(str(self.selection), str(plan), handles=1)
            result = self.api().export_otio_file(plan, output, fps=25)
        timeline = otio.adapters.read_from_file(str(output))
        clip = timeline.video_tracks()[0][0]
        self.assertEqual(timeline.global_start_time.rate, 25)
        self.assertEqual(clip.source_range.start_time.value, 86400)
        self.assertEqual(clip.source_range.duration.value, 120)
        self.assertEqual(clip.source_range.duration.rate, 24)
        self.assertEqual(clip.media_reference.target_url, (self.root / "relative.mov").resolve().as_uri())
        manifest = json.loads(Path(result["run_manifest"]).read_text())
        planned_clip = json.loads(plan.read_text())["clips"][0]
        self.assertEqual(planned_clip["handles_applied"], {"pre": .25, "post": .25})
        self.assertEqual(manifest["handoff"]["sources"][0]["xml_in_frames"], 0)
        self.assertEqual(manifest["handoff"]["sources"][0]["xml_out_frames"], 125)
        self.assertEqual(manifest["handoff"]["sources"][0]["source_out_frames"], 120)
        self.assertEqual(manifest["handoff"]["sources"][0]["xml_clip_rate"], "25")

    def test_pipeline_validates_and_plans_otio_output_and_sidecar_reference(self):
        from videoedit.pipeline import plan_pipeline, run_pipeline, validate_pipeline
        pipeline = {"requires_modules": ["editor.otio"], "steps": [
            {"name": "edit", "operation": "generate_otio", "input": str(self.selection),
             "params": {"output": "${output}/edit.otio"}},
            {"name": "manifest", "operation": "generate_content_map", "input": "${edit.run_manifest}"}]}
        validate_pipeline(pipeline)
        pipeline["steps"][1]["input"] = "${edit.not_a_field}"
        with self.assertRaisesRegex(ValueError, "unknown output"):
            validate_pipeline(pipeline)
        pipeline["steps"].pop()
        path = self.root / "pipeline.json"
        path.write_text(json.dumps(pipeline))
        out = self.root / "pipeline-output"
        planned = plan_pipeline(str(path), str(self.root), str(out))
        self.assertEqual(planned["steps"][0]["planned_result"]["run_manifest"], str(out / "edit_otio_handoff.json"))
        self.assertFalse(out.exists(), "Planning must not render or create outputs")
        with patch("videoedit.handoff.probe_handoff_media", return_value=info()):
            context = run_pipeline(str(path), str(self.root), str(out))
        self.assertEqual(context["results"]["edit"]["clips"], 1)
        self.assertTrue((out / "edit.otio").is_file())

    def test_pipeline_default_output_uses_the_roughcut_plan_context(self):
        import opentimelineio as otio
        from videoedit.pipeline import plan_pipeline, run_pipeline
        pipeline = {"steps": [
            {"name": "planned", "operation": "plan_roughcut", "input": str(self.selection),
             "params": {"output": "${output}/planned.json", "handles": .25}},
            {"name": "edit", "operation": "generate_otio"}]}
        path, out = self.root / "pipeline.json", self.root / "default-output"
        path.write_text(json.dumps(pipeline))
        planned = plan_pipeline(str(path), str(self.root), str(out))
        self.assertEqual(planned["steps"][1]["input"], str(out / "planned.json"))
        self.assertEqual(planned["steps"][1]["planned_result"]["output"], str(out / "edit.otio"))
        with patch("videoedit.handoff.probe_handoff_media", return_value=info()):
            result = run_pipeline(str(path), str(self.root), str(out))
        self.assertEqual(result["results"]["edit"]["output"], str(out / "edit.otio"))
        clip = otio.adapters.read_from_file(str(out / "edit.otio")).video_tracks()[0][0]
        self.assertEqual(clip.source_range.start_time.value, 107915)
        self.assertEqual(clip.source_range.duration.value, 74)

    def test_empty_selection_and_multistream_audio_are_explicit(self):
        empty = build_handoff_timeline([], "mixed", 25)
        self.assertEqual(self.read(empty).duration().to_seconds(), 0)
        multi = info()
        multi.audio_streams.append({"index": 2, "channels": 1, "sample_rate": 48000})
        timeline = self.read(self.timeline(media=multi))
        self.assertEqual(len(timeline.audio_tracks()), 0)
        self.assertIn("unsupported_audio_layout", timeline.metadata["videoedit"]["limitations"])

    def test_redacted_sidecar_does_not_leak_operational_media_urls(self):
        output = self.root / "private-edit.otio"
        with patch("videoedit.handoff.probe_handoff_media", return_value=info()):
            result = self.api().export_otio_file(self.selection, output, manifest_paths="redacted")
        serialized = Path(result["run_manifest"]).read_text()
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("A%20%26%20B", serialized)
        self.assertIn((self.root / "A & B.mov").resolve().as_uri(), output.read_text())

    def test_atomic_replace_failure_keeps_previous_edit(self):
        api = self.api()
        output = self.root / "edit.otio"
        output.write_text("previous")
        replace = os.replace

        def fail_edit_replace(source, destination):
            if Path(destination) == output:
                raise OSError("blocked")
            return replace(source, destination)

        with patch("videoedit.handoff.probe_handoff_media", return_value=info()), \
                patch("videoedit.otio.os.replace", side_effect=fail_edit_replace):
            with self.assertRaises(OSError):
                api.export_otio_file(self.selection, output)
        self.assertEqual(output.read_text(), "previous")
        self.assertEqual(json.loads((self.root / "edit_otio_handoff.json").read_text())["status"], "error")

    def test_serialization_is_deterministic(self):
        api = self.api()
        native = self.timeline()
        self.assertEqual(api.generate_otio(native), api.generate_otio(native))


if __name__ == "__main__":
    unittest.main()
