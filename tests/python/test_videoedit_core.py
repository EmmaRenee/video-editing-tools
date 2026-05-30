import io
import builtins
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_SRC = os.path.join(ROOT, "src", "python")
sys.path.insert(0, PYTHON_SRC)

from videoedit.config import AnalysisConfig
from videoedit.advanced import (
    cluster_transcript_topics,
    detect_face_person_presence,
    detect_motorsports_events,
    detect_visual_objects,
)
from videoedit.captions import srt_to_ass
from videoedit.cli import main
import videoedit.cli as cli_module
from videoedit.content import generate_content_map, generate_quote_mining, plan_content_series
from videoedit.diagnostics import format_diagnostics, run_diagnostics
from videoedit.edl import export_selection_file
from videoedit.ffmpeg import parse_audio_metadata_output, parse_scene_output, parse_silence_output, run_command_check
from videoedit.models import AudioLevel, CandidateClip, MediaAsset, SignalReport
from videoedit.modules import disable_module, enable_module, module_rows, operation_enabled
from videoedit.operations import default_registry
import videoedit.operations as operations_module
from videoedit.pipeline import load_pipeline, plan_pipeline, run_pipeline, validate_pipeline, write_preset
from videoedit.rating import generate_candidates, score_signal
from videoedit.review import create_approval_file, generate_review_assets
from videoedit.scaffold import scaffold_project
from videoedit.selections import load_selection
from videoedit.simple_yaml import load_mapping


class ParserTests(unittest.TestCase):
    def test_parse_scene_output(self):
        output = "n:0 pts_time:1.25 x\nn:1 pts_time:3.5 x\n"
        self.assertEqual(parse_scene_output(output), [1.25, 3.5])

    def test_parse_silence_output(self):
        output = """
        [silencedetect @ abc] silence_start: 2.1
        [silencedetect @ abc] silence_end: 4.6 | silence_duration: 2.5
        """
        intervals = parse_silence_output(output, duration=10)
        self.assertEqual(len(intervals), 1)
        self.assertAlmostEqual(intervals[0].start, 2.1)
        self.assertAlmostEqual(intervals[0].end, 4.6)

    def test_parse_audio_metadata_output(self):
        output = """
        frame:0 pts:0 pts_time:0
        lavfi.astats.Overall.RMS_level=-40.5
        frame:1 pts:48000 pts_time:1
        lavfi.astats.Overall.RMS_level=-12.25
        """
        levels = parse_audio_metadata_output(output)
        self.assertEqual(len(levels), 2)
        self.assertEqual(levels[1].time, 1)
        self.assertEqual(levels[1].rms_db, -12.25)


class ScoringTests(unittest.TestCase):
    def test_candidate_from_dict_accepts_formatted_timecodes(self):
        clip = CandidateClip.from_dict(
            {
                "id": "clip_0001",
                "source": "/tmp/source.mp4",
                "start": "00:00:05",
                "end": "00:00:09",
                "score": 80,
                "action": "review",
            }
        )
        self.assertEqual(clip.start, 5.0)
        self.assertEqual(clip.end, 9.0)

    def test_score_and_candidate_generation(self):
        config = AnalysisConfig(max_candidates=10)
        asset = MediaAsset(
            filename="race.mp4",
            filepath="/tmp/race.mp4",
            duration=30,
            width=1920,
            height=1080,
            codec="h264",
            fps=30,
            has_audio=True,
        )
        levels = [AudioLevel(time=5, rms_db=-40), AudioLevel(time=6, rms_db=-10)]
        scores = score_signal(asset, [6], [], levels, [], config)
        report = SignalReport(asset=asset, scene_changes=[6], audio_levels=levels, scores=scores)
        candidates = generate_candidates([report], config)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertIn("audio_spike", candidates[0].labels)
        self.assertGreater(candidates[0].score, 50)


class PipelineTests(unittest.TestCase):
    def test_preset_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "reel.yaml")
            write_preset("reel", output)
            data = load_mapping(output)
            self.assertEqual(data["name"], "reel")
            loaded = load_pipeline(output)
            self.assertEqual(loaded["steps"][0]["operation"], "rate_footage")

    def test_roughcut_preset_references_review_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "roughcut.yaml")
            write_preset("roughcut", output)
            data = load_pipeline(output)
            operations = [step["operation"] for step in data["steps"]]
            self.assertEqual(
                operations,
                [
                    "rate_footage",
                    "generate_review_assets",
                    "approve_candidates",
                    "generate_edl",
                    "assemble_rough_cut",
                ],
            )
            self.assertEqual(data["steps"][2]["params"]["decisions"], "review.decisions")

    def test_motorsports_preset_includes_advanced_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "motorsports.yaml")
            write_preset("motorsports", output)
            data = load_pipeline(output)
            operations = [step["operation"] for step in data["steps"]]
            self.assertIn("detect_motorsports_events", operations)
            self.assertIn("cluster_transcript_topics", operations)
            self.assertEqual(data["steps"][1]["input"], "rate.ratings")

    def test_documentary_preset_exports_filtered_transcript_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "documentary.yaml")
            write_preset("documentary", output)
            data = load_pipeline(output)
            self.assertEqual(data["steps"][1]["input"], "rate.ratings")
            self.assertEqual(data["steps"][2]["input"], "transcript_highlights.selections")
            self.assertEqual(data["steps"][2]["params"]["output"], "${output}/edl")

    def test_pipeline_validation_rejects_unknown_step_output_reference(self):
        pipeline = {
            "name": "bad_reference",
            "steps": [
                {"name": "rate", "operation": "rate_footage"},
                {
                    "name": "approve",
                    "operation": "approve_candidates",
                    "params": {"decisions": "rate.missing"},
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "rate.missing"):
            validate_pipeline(pipeline)

    def test_pipeline_validation_rejects_future_step_reference(self):
        pipeline = {
            "name": "future_reference",
            "steps": [
                {"name": "edl", "operation": "generate_edl", "input": "approve.approved"},
                {"name": "approve", "operation": "approve_candidates"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "future step"):
            validate_pipeline(pipeline)

    def test_pipeline_validation_accepts_all_presets(self):
        for preset in ["simple", "reel", "roughcut", "youtube", "documentary", "motorsports"]:
            with tempfile.TemporaryDirectory() as tmp:
                output = os.path.join(tmp, f"{preset}.yaml")
                write_preset(preset, output)
                self.assertEqual(load_pipeline(output)["name"], preset)

    def test_pipeline_run_writes_execution_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "pipeline.json")
            output = os.path.join(tmp, "output")
            with open(pipeline, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "name": "manifest_smoke",
                            "steps": [
                                {
                                    "name": "inventory",
                                    "operation": "inventory",
                                    "params": {},
                                }
                            ],
                        }
                    )
                )
            context = run_pipeline(pipeline, tmp, output)
            self.assertTrue(os.path.exists(context["manifest"]))
            with open(context["manifest"], encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["steps"][0]["name"], "inventory")
            self.assertEqual(manifest["steps"][0]["status"], "ok")

    def test_pipeline_run_writes_failure_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "pipeline.json")
            output = os.path.join(tmp, "output")
            with open(pipeline, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "name": "failure_smoke",
                            "steps": [
                                {
                                    "name": "assemble",
                                    "operation": "assemble_rough_cut",
                                    "params": {},
                                }
                            ],
                        }
                    )
                )
            with self.assertRaises(TypeError):
                run_pipeline(pipeline, tmp, output)
            manifest_path = os.path.join(output, "pipeline_run.json")
            self.assertTrue(os.path.exists(manifest_path))
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            self.assertEqual(manifest["status"], "error")
            self.assertEqual(manifest["steps"][0]["status"], "error")

    def test_pipeline_plan_resolves_known_step_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "roughcut.yaml")
            write_preset("roughcut", pipeline)
            output = os.path.join(tmp, "output")
            plan = plan_pipeline(pipeline, os.path.join(tmp, "footage"), output)
            self.assertEqual(plan["pipeline"], "roughcut")
            self.assertEqual(plan["steps"][1]["params"]["input"], os.path.join(output, "rate", "ratings.json"))
            self.assertEqual(plan["steps"][2]["params"]["decisions"], os.path.join(output, "review", "review_decisions.json"))
            self.assertEqual(plan["steps"][4]["params"]["input"], os.path.join(output, "approved.json"))

    def test_pipeline_plan_treats_filter_step_output_as_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "documentary.yaml")
            write_preset("documentary", pipeline)
            output = os.path.join(tmp, "output")
            plan = plan_pipeline(pipeline, tmp, output)
            filter_step = plan["steps"][1]
            self.assertEqual(filter_step["params"]["input"], os.path.join(output, "rate", "ratings.json"))
            self.assertEqual(
                filter_step["planned_result"]["output"],
                os.path.join(output, "transcript_highlights", "transcript_hit_candidates.json"),
            )
            self.assertEqual(
                filter_step["planned_result"]["selections"],
                os.path.join(output, "transcript_highlights", "transcript_hit_selections"),
            )

    def test_pipeline_plan_surfaces_implicit_edl_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "reel.yaml")
            write_preset("reel", pipeline)
            output = os.path.join(tmp, "output")
            plan = plan_pipeline(pipeline, tmp, output)
            self.assertEqual(plan["steps"][1]["input"], os.path.join(output, "rate", "selections"))
            self.assertEqual(plan["steps"][1]["params"]["input"], os.path.join(output, "rate", "selections"))

    def test_cli_run_dry_run_prints_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = os.path.join(tmp, "simple.yaml")
            output = os.path.join(tmp, "output")
            write_preset("simple", pipeline)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["run", pipeline, "--input", tmp, "--output", output, "--dry-run"])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["pipeline"], "simple")
            self.assertFalse(os.path.exists(os.path.join(output, "pipeline_run.json")))

    def test_cli_extract_segments_dispatches_to_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "approved.json")
            clips = os.path.join(tmp, "clips")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"source": "/tmp/a.mp4", "clips": []}))
            original = cli_module.op_extract_segments

            def fake_extract(context, params):
                self.assertEqual(params["input"], selection)
                self.assertEqual(params["output"], clips)
                return {"output": clips, "files": [os.path.join(clips, "clip.mp4")]}

            stdout = io.StringIO()
            cli_module.op_extract_segments = fake_extract
            try:
                with redirect_stdout(stdout):
                    exit_code = main(["extract-segments", selection, "--output", clips])
            finally:
                cli_module.op_extract_segments = original
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["files"], [os.path.join(clips, "clip.mp4")])


class OperationTests(unittest.TestCase):
    def test_highlight_filter_operations_use_distinct_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            audio_output = os.path.join(tmp, "audio.json")
            transcript_output = os.path.join(tmp, "transcript.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "audio_only",
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:04",
                                    "labels": ["audio_spike"],
                                },
                                {
                                    "id": "transcript_only",
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:05",
                                    "end": "00:00:08",
                                    "labels": ["transcript_hit"],
                                },
                                {
                                    "id": "both",
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:09",
                                    "end": "00:00:12",
                                    "labels": ["audio_spike", "transcript_hit"],
                                },
                            ]
                        }
                    )
                )
            registry = default_registry()
            context = {"ratings": ratings, "output": tmp}
            audio = registry.get("detect_highlights_audio").func(context, {"output": audio_output})
            transcript = registry.get("detect_highlights_transcript").func(
                context,
                {"output": transcript_output},
            )
            self.assertEqual(audio["count"], 2)
            self.assertEqual(transcript["count"], 2)
            with open(audio_output, encoding="utf-8") as handle:
                audio_ids = [item["id"] for item in json.loads(handle.read())["candidates"]]
            with open(transcript_output, encoding="utf-8") as handle:
                transcript_ids = [item["id"] for item in json.loads(handle.read())["candidates"]]
            self.assertEqual(audio_ids, ["audio_only", "both"])
            self.assertEqual(transcript_ids, ["transcript_only", "both"])
            self.assertTrue(os.path.isdir(audio["selections"]))
            self.assertEqual(len(audio["files"]), 1)
            with open(audio["files"][0], encoding="utf-8") as handle:
                selection = json.loads(handle.read())
            self.assertEqual([item["label"] for item in selection["clips"]], ["audio_only", "both"])

    def test_advanced_analysis_writes_motorsports_and_topic_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            events = os.path.join(tmp, "motorsports_events.json")
            topics = os.path.join(tmp, "topic_clusters.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/tmp/race.mp4",
                                    "start": "00:00:04",
                                    "end": "00:00:12",
                                    "score": 86,
                                    "labels": ["audio_spike", "scene_change"],
                                    "reasons": ["driver makes an inside pass for position"],
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/tmp/race.mp4",
                                    "start": "00:00:20",
                                    "end": "00:00:28",
                                    "score": 72,
                                    "labels": ["scene_cluster"],
                                    "reasons": ["car has a spin after contact"],
                                },
                            ],
                            "signals": [
                                {
                                    "asset": {"filepath": "/tmp/race.mp4"},
                                    "transcript_hits": [
                                        {
                                            "start": 4,
                                            "end": 8,
                                            "text": "Great inside pass into turn one.",
                                            "keywords": ["pass"],
                                        },
                                        {
                                            "start": 20,
                                            "end": 25,
                                            "text": "There is contact and a spin.",
                                            "keywords": ["contact", "spin"],
                                        },
                                    ],
                                }
                            ],
                        }
                    )
                )
            event_result = detect_motorsports_events(ratings, events)
            topic_result = cluster_transcript_topics(ratings, topics)
            self.assertEqual(event_result["count"], 2)
            self.assertEqual(topic_result["count"], 2)
            with open(events, encoding="utf-8") as handle:
                event_types = [item["event_type"] for item in json.loads(handle.read())["events"]]
            with open(topics, encoding="utf-8") as handle:
                topic_names = [item["topic"] for item in json.loads(handle.read())["topics"]]
            self.assertIn("pass", event_types)
            self.assertIn("incident", event_types)
            self.assertIn("racecraft", topic_names)
            self.assertIn("incidents", topic_names)

    def test_optional_object_provider_writes_unavailable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "visual_objects.json")
            result = detect_visual_objects(tmp, output, command="definitely_missing_videoedit_detector")
            self.assertEqual(result["status"], "unavailable")
            with open(output, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["provider"], "visual_objects")
            self.assertEqual(data["count"], 0)

    def test_optional_face_person_provider_writes_unavailable_manifest_without_opencv(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "face_person_presence.json")
            original_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "cv2":
                    raise ImportError("no cv2")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = fake_import
            try:
                result = detect_face_person_presence(tmp, output)
            finally:
                builtins.__import__ = original_import
            self.assertEqual(result["status"], "unavailable")
            with open(output, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["provider"], "face_person_presence")
            self.assertEqual(data["count"], 0)

    def test_extract_segments_uses_per_clip_sources_for_mixed_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "approved.json")
            clips_dir = os.path.join(tmp, "clips")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "source": "mixed",
                            "clips": [
                                {
                                    "source": "/tmp/a cam.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:03",
                                    "label": "clip a",
                                },
                                {
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:04",
                                    "end": "00:00:08",
                                    "label": "clip_b",
                                },
                            ],
                        }
                    )
                )
            calls = []
            original = operations_module.run_command_check

            def fake_run_command_check(args, timeout=180):
                calls.append(args)
                return None

            operations_module.run_command_check = fake_run_command_check
            try:
                result = operations_module.op_extract_segments({}, {"input": selection, "output": clips_dir})
            finally:
                operations_module.run_command_check = original

            self.assertEqual(calls[0][2], "/tmp/a cam.mp4")
            self.assertEqual(calls[1][2], "/tmp/b.mp4")
            self.assertTrue(result["files"][0].endswith("a_cam_clip_a.mp4"))
            self.assertTrue(result["files"][1].endswith("b_clip_b.mp4"))


class DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_reports_required_dependency_status(self):
        paths = {"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}
        report = run_diagnostics(lambda name: paths.get(name), lambda name: object() if name == "cv2" else None)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["missing_required"], [])
        self.assertIn("whisper", report["missing_optional"])
        self.assertIn("videoedit doctor: ok", format_diagnostics(report))

    def test_diagnostics_fails_when_required_dependency_missing(self):
        report = run_diagnostics(lambda name: None, lambda name: None)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["missing_required"], ["ffmpeg", "ffprobe"])


class ReviewTests(unittest.TestCase):
    def test_create_approval_file_filters_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            approved = os.path.join(tmp, "approved.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:05",
                                    "score": 92,
                                    "action": "select",
                                    "labels": ["audio_spike"],
                                    "reasons": ["audio peak"],
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:06",
                                    "end": "00:00:10",
                                    "score": 62,
                                    "action": "review",
                                },
                            ]
                        }
                    )
                )
            create_approval_file(ratings, approved, actions=["select", "review"], min_score=80)
            with open(approved, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(len(data["clips"]), 1)
            self.assertEqual(data["clips"][0]["label"], "clip_0001")
            self.assertEqual(data["source"], "/tmp/a.mp4")

    def test_create_approval_file_uses_review_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            decisions = os.path.join(tmp, "review_decisions.json")
            approved = os.path.join(tmp, "approved.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:05",
                                    "score": 95,
                                    "action": "select",
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:06",
                                    "end": "00:00:10",
                                    "score": 40,
                                    "action": "cut",
                                },
                            ]
                        }
                    )
                )
            with open(decisions, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "decisions": [
                                {"id": "clip_0001", "decision": "reject", "order": 2, "note": "too shaky"},
                                {"id": "clip_0002", "decision": "promote", "order": 1, "note": "story beat"},
                            ]
                        }
                    )
                )
            create_approval_file(ratings, approved, decisions_json=decisions)
            with open(approved, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(len(data["clips"]), 1)
            self.assertEqual(data["clips"][0]["label"], "clip_0002")
            self.assertEqual(data["clips"][0]["review_note"], "story beat")

    def test_generate_review_assets_writes_manifest_without_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            output = os.path.join(tmp, "review")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/missing/source.mp4",
                                    "start_seconds": 0,
                                    "end_seconds": 4,
                                    "score": 70,
                                    "action": "review",
                                }
                            ]
                        }
                    )
                )
            result = generate_review_assets(ratings, output, max_items=1)
            self.assertTrue(os.path.exists(result["manifest"]))
            self.assertTrue(os.path.exists(result["contact_sheet"]))
            self.assertTrue(os.path.exists(result["decisions"]))
            self.assertEqual(result["clips"], 1)
            self.assertEqual(result["thumbnails"], 0)
            self.assertTrue(result["warnings"])
            with open(result["contact_sheet"], encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn("downloadDecisions", html)
            self.assertIn('class="decision"', html)
            self.assertIn('value="approve"', html)

    def test_export_handoff_uses_per_clip_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "approved.json")
            output = os.path.join(tmp, "edl")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "source": "mixed",
                            "clips": [
                                {
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:03",
                                    "label": "clip_a",
                                },
                                {
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:04",
                                    "end": "00:00:08",
                                    "label": "clip_b",
                                },
                            ],
                        }
                    )
                )
            paths = export_selection_file(selection, output)
            with open(paths[0], encoding="utf-8") as handle:
                edl = handle.read()
            with open(paths[2], encoding="utf-8") as handle:
                m3u = handle.read()
            self.assertIn("/tmp/a.mp4", edl)
            self.assertIn("/tmp/b.mp4", edl)
            self.assertIn("/tmp/a.mp4", m3u)
            self.assertIn("/tmp/b.mp4", m3u)

    def test_drive_style_soundbite_json_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "soundbites.json")
            output = os.path.join(tmp, "edl")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "project": "Vin Wiki Soundbites",
                            "fps": 24,
                            "clips": [
                                {
                                    "source": "/tmp/interview.mp4",
                                    "start": "00:00:30",
                                    "end": "00:01:00",
                                    "label": "matt_intro",
                                }
                            ],
                        }
                    )
                )
            document = load_selection(selection)
            self.assertEqual(document.project, "Vin Wiki Soundbites")
            self.assertEqual(document.fps, 24)
            paths = export_selection_file(selection, output)
            with open(paths[0], encoding="utf-8") as handle:
                self.assertIn("/tmp/interview.mp4", handle.read())

    def test_selection_requires_per_clip_source_without_top_level_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "bad.json")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"project": "Paper Edit", "clips": [{"start": "00:00:01", "end": "00:00:02"}]}))
            with self.assertRaisesRegex(ValueError, "missing source"):
                load_selection(selection)


class ModuleTests(unittest.TestCase):
    def test_modules_can_disable_and_enable_optional_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(operation_enabled("plan_content_series", cwd=tmp))
            disable_module("content.series", cwd=tmp)
            self.assertFalse(operation_enabled("plan_content_series", cwd=tmp))
            registry = default_registry(cwd=tmp)
            with self.assertRaises(KeyError):
                registry.get("plan_content_series")
            enable_module("content.series", cwd=tmp)
            self.assertTrue(operation_enabled("plan_content_series", cwd=tmp))

    def test_cli_modules_list_and_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    self.assertEqual(main(["modules", "list"]), 0)
                self.assertIn("content.series", buffer.getvalue())
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["modules", "disable", "content.series"]), 0)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["series", "templates"]), 1)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["modules", "enable", "content.series"]), 0)
                module_root = os.path.join(tmp, "videoedit-my-feature")
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["modules", "scaffold", "my_feature", "--output", module_root]), 0)
                self.assertTrue(os.path.exists(os.path.join(module_root, "pyproject.toml")))
                self.assertTrue(os.path.exists(os.path.join(module_root, "my_feature", "module.py")))
            finally:
                os.chdir(cwd)

    def test_pipeline_requires_modules_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                disable_module("content.series")
                with self.assertRaisesRegex(ValueError, "disabled module content.series"):
                    validate_pipeline(
                        {
                            "name": "series",
                            "requires_modules": ["content.series"],
                            "steps": [{"name": "rate", "operation": "rate_footage"}],
                        }
                    )
            finally:
                os.chdir(cwd)


class CaptionContentScaffoldTests(unittest.TestCase):
    def test_srt_to_ass_uses_packaged_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "captions.srt")
            with open(srt, "w", encoding="utf-8") as handle:
                handle.write("1\n00:00:01,000 --> 00:00:02,000\nHello\nworld\n\n")
            ass = srt_to_ass(srt, style_name="automotive_racing", width=1080, height=1920)
            self.assertIn("PlayResX: 1080", ass)
            self.assertIn("Style: Default,Arial", ass)
            self.assertIn(r"Hello\Nworld", ass)

    def test_content_series_and_reports_from_ratings(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            _write_sample_ratings(ratings)
            series_dir = os.path.join(tmp, "series")
            series = plan_content_series(ratings, series_dir, template="team_tuesday", max_clips=2)
            self.assertTrue(os.path.exists(series["plan"]))
            self.assertTrue(os.path.exists(series["captions"]))
            self.assertTrue(os.path.exists(series["selections"]))
            reports = os.path.join(tmp, "reports")
            content_map = generate_content_map(ratings, reports)
            quote_mining = generate_quote_mining(ratings, reports)
            self.assertTrue(os.path.exists(content_map["markdown"]))
            self.assertTrue(os.path.exists(content_map["json"]))
            self.assertTrue(os.path.exists(quote_mining["markdown"]))

    def test_project_scaffold_writes_videoedit_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = scaffold_project("My Reel", tmp, project_type="reel")
            project = result["project"]
            self.assertTrue(os.path.isdir(os.path.join(project, "raw")))
            self.assertTrue(os.path.exists(os.path.join(project, ".videoedit", "config.json")))
            self.assertTrue(os.path.exists(os.path.join(project, "README.md")))


def _write_sample_ratings(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "summary": {"files": 2, "candidates": 2, "total_duration": 120},
                    "signals": [
                        {
                            "asset": {"filename": "interview.mp4", "filepath": "/tmp/interview.mp4"},
                            "transcript_hits": [
                                {
                                    "start": 30,
                                    "end": 40,
                                    "start_tc": "00:00:30",
                                    "end_tc": "00:00:40",
                                    "text": "This is the part customers need to understand.",
                                    "keywords": ["customers"],
                                }
                            ],
                        }
                    ],
                    "candidates": [
                        {
                            "id": "clip_0001",
                            "source": "/tmp/interview.mp4",
                            "start": "00:00:30",
                            "end": "00:00:45",
                            "duration": 15,
                            "score": 92,
                            "action": "select",
                            "labels": ["transcript_hit"],
                            "reasons": ["transcript keywords: customers, detail"],
                            "signals": {"transcript_score": 20},
                        },
                        {
                            "id": "clip_0002",
                            "source": "/tmp/shop.mp4",
                            "start": "00:01:00",
                            "end": "00:01:20",
                            "duration": 20,
                            "score": 84,
                            "action": "review",
                            "labels": ["audio_spike", "scene_change"],
                            "reasons": ["engine build progress", "audio peak -10 dB RMS"],
                            "signals": {"audio_interest_score": 25},
                        },
                    ],
                }
            )
        )


class SmokeTests(unittest.TestCase):
    def test_ffmpeg_smoke_rating_when_available(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp
            video = os.path.join(tmp_path, "sample.mp4")
            run_command_check(
                [
                    "ffmpeg",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x240:rate=30:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:duration=2",
                    "-shortest",
                    "-pix_fmt",
                    "yuv420p",
                    video,
                    "-y",
                ]
            )
            output = os.path.join(tmp_path, "analysis")
            exit_code = main(
                [
                    "rate",
                    tmp_path,
                    "--output",
                    output,
                    "--transcript",
                    "off",
                    "--no-cache",
                    "--max-candidates",
                    "5",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(os.path.join(output, "ratings.json")))
            with open(os.path.join(output, "ratings.json"), encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["summary"]["files"], 1)

            review_output = os.path.join(tmp_path, "review_assets")
            exit_code = main(
                [
                    "review-assets",
                    os.path.join(output, "ratings.json"),
                    "--output",
                    review_output,
                    "--max-items",
                    "1",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(os.path.join(review_output, "contact_sheet.html")))
            self.assertTrue(os.path.exists(os.path.join(review_output, "review_decisions.json")))

            approved = os.path.join(tmp_path, "approved.json")
            exit_code = main(
                [
                    "approve",
                    os.path.join(output, "ratings.json"),
                    "--output",
                    approved,
                    "--ids",
                    "clip_0001",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(approved))

            decisions_approved = os.path.join(tmp_path, "decisions_approved.json")
            exit_code = main(
                [
                    "approve",
                    os.path.join(output, "ratings.json"),
                    "--output",
                    decisions_approved,
                    "--decisions",
                    os.path.join(review_output, "review_decisions.json"),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(decisions_approved))

            rough_cut = os.path.join(tmp_path, "rough_cut.mp4")
            exit_code = main(["assemble", approved, "--output", rough_cut])
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(rough_cut))

            pipeline = os.path.join(tmp_path, "roughcut.yaml")
            write_preset("roughcut", pipeline)
            pipeline_output = os.path.join(tmp_path, "pipeline")
            context = run_pipeline(pipeline, tmp_path, pipeline_output)
            self.assertTrue(os.path.exists(os.path.join(pipeline_output, "approved.json")))
            self.assertTrue(os.path.exists(os.path.join(pipeline_output, "rough_cut.mp4")))
            self.assertIn("assemble", context["results"])


if __name__ == "__main__":
    unittest.main()
