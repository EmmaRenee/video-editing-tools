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
import videoedit.inventory as inventory_module
from videoedit.advanced import (
    cluster_transcript_topics,
    detect_face_person_presence,
    detect_motorsports_events,
    detect_visual_objects,
)
import videoedit.advanced as advanced_module
from videoedit.calibration import (
    annotations_from_review_decisions,
    apply_scoring_config,
    compare_calibration_runs,
    evaluate_ratings,
    load_annotations,
)
from videoedit.captions import srt_to_ass
from videoedit.cli import main
import videoedit.cli as cli_module
from videoedit.content import generate_content_map, generate_quote_mining, plan_content_series
from videoedit.diagnostics import format_diagnostics, run_diagnostics
from videoedit.edl import export_selection_file, generate_extract_script
from videoedit.ffmpeg import CommandResult, parse_audio_metadata_output, parse_scene_output, parse_silence_output, run_command_check
from videoedit.models import AudioLevel, CandidateClip, MediaAsset, ObjectHit, SignalReport
from videoedit.modules import disable_module, enable_module, module_rows, operation_enabled
from videoedit.operations import default_registry
import videoedit.operations as operations_module
from videoedit.pipeline import load_pipeline, plan_pipeline, run_pipeline, validate_pipeline, write_preset
from videoedit.rating import generate_candidates, score_signal
import videoedit.review as review_module
from videoedit.review import create_approval_file, generate_review_assets
from videoedit.roughcut import plan_roughcut
from videoedit.review_tui import (
    _interactive_loop,
    filter_review_clips,
    load_review_session,
    update_review_decision,
    write_review_decisions,
)
from videoedit.scaffold import scaffold_project
from videoedit.selections import load_selection
from videoedit.signals import load_signal_artifacts, validate_signal_artifact
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


class InventoryTests(unittest.TestCase):
    def test_build_inventory_skips_probe_failures(self):
        original_scan = inventory_module.scan_video_files
        original_probe = inventory_module.probe_media

        def fake_scan(_directory):
            return ["/tmp/bad.mp4", "/tmp/good.mp4"]

        def fake_probe(path, timeout=60):
            if path.endswith("bad.mp4"):
                raise RuntimeError("probe failed")
            return MediaAsset(filename=os.path.basename(path), filepath=path, duration=1.0)

        inventory_module.scan_video_files = fake_scan
        inventory_module.probe_media = fake_probe
        try:
            with self.assertLogs("videoedit.inventory", level="WARNING") as logs:
                items = inventory_module.build_inventory("/tmp")
        finally:
            inventory_module.scan_video_files = original_scan
            inventory_module.probe_media = original_probe

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].filename, "good.mp4")
        self.assertIn("probe failed", logs.output[0])


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
        scores = score_signal(asset, [6], [], levels, [], [], [], config)
        report = SignalReport(asset=asset, scene_changes=[6], audio_levels=levels, scores=scores)
        candidates = generate_candidates([report], config)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertIn("audio_spike", candidates[0].labels)
        self.assertGreater(candidates[0].score, 50)

    def test_object_hits_seed_and_score_candidates_when_configured(self):
        config = AnalysisConfig(max_candidates=10)
        asset = MediaAsset(
            filename="source.mp4",
            filepath="/tmp/source.mp4",
            duration=20,
            width=1920,
            height=1080,
            codec="h264",
            fps=30,
            has_audio=False,
        )
        report = SignalReport(
            asset=asset,
            scores={"technical_score": 17},
            object_hits=[ObjectHit(start=5, end=8, class_name="person", class_id=0, count=20)],
        )
        candidates = generate_candidates([report], config)
        self.assertEqual(len(candidates), 1)
        self.assertIn("object_presence", candidates[0].labels)
        self.assertIn("object_person", candidates[0].labels)
        self.assertGreater(candidates[0].signals["object_presence_score"], 0)

    def test_advanced_hits_seed_labels_and_scores(self):
        config = AnalysisConfig(max_candidates=10)
        asset = MediaAsset(
            filename="race.mp4",
            filepath="/tmp/race.mp4",
            duration=30,
            width=1920,
            height=1080,
            codec="h264",
            fps=30,
            has_audio=False,
        )
        report = SignalReport(
            asset=asset,
            scores={"technical_score": 17},
            advanced_hits=[
                {"kind": "motorsports_event", "start": 5, "end": 8, "event_type": "pass", "confidence": 0.8},
                {"kind": "topic_cluster", "start": 6, "end": 9, "topic": "racecraft"},
                {"kind": "ocr_signage", "source_wide": True, "text": "DRIVE AUTO SPORTS"},
                {"kind": "face_person", "source_wide": True, "face_count": 2, "person_count": 3},
            ],
        )
        candidates = generate_candidates([report], config)
        self.assertEqual(len(candidates), 1)
        self.assertIn("motorsports_event", candidates[0].labels)
        self.assertIn("topic_cluster", candidates[0].labels)
        self.assertIn("ocr_signage", candidates[0].labels)
        self.assertIn("face_presence", candidates[0].labels)
        self.assertGreater(candidates[0].signals["motorsports_event_score"], 0)
        self.assertGreater(candidates[0].signals["topic_cluster_score"], 0)

    def test_signal_artifact_loader_matches_unique_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            visual = os.path.join(tmp, "visual_objects.json")
            ocr = os.path.join(tmp, "ocr_signage.json")
            with open(visual, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "sources": [
                                {
                                    "source": "clips/source.mp4",
                                    "segments": [
                                        {
                                            "class_name": "person",
                                            "class_id": 0,
                                            "start_seconds": 1,
                                            "end_seconds": 3,
                                            "detection_count": 10,
                                        }
                                    ],
                                }
                            ]
                        }
                    )
                )
            with open(ocr, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"hits": [{"source": "clips/source.mp4", "text": "shop sign"}]}))
            config = AnalysisConfig(
                visual_objects_path=visual,
                signal_artifacts={"ocr_signage": ocr},
            )
            bundle = load_signal_artifacts(config)
            self.assertEqual(len(bundle.objects_for(os.path.join(tmp, "other", "source.mp4"))), 1)
            self.assertEqual(bundle.advanced_for(os.path.join(tmp, "other", "source.mp4"))[0]["kind"], "ocr_signage")


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
                    "plan_roughcut",
                    "assemble_rough_cut",
                ],
            )
            self.assertEqual(data["steps"][2]["params"]["decisions"], "review.decisions")
            self.assertEqual(data["steps"][4]["input"], "approve.approved")

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

    def test_vision_reel_preset_fuses_vision_outputs_into_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "vision_reel.yaml")
            write_preset("vision_reel", output)
            data = load_pipeline(output)
            operations = [step["operation"] for step in data["steps"]]
            self.assertEqual(operations[:4], ["detect_visual_objects", "detect_ocr_signage", "detect_face_person_presence", "rate_footage"])
            self.assertEqual(data["steps"][3]["params"]["visual_objects"], "objects.output")
            plan = plan_pipeline(output, tmp, os.path.join(tmp, "out"))
            self.assertEqual(plan["steps"][0]["planned_result"]["status"], "planned")
            self.assertIn("detection_count", plan["steps"][0]["planned_result"])

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
        for preset in ["simple", "reel", "roughcut", "youtube", "documentary", "motorsports", "vision_reel"]:
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
            self.assertEqual(plan["steps"][4]["planned_result"]["plan"], os.path.join(output, "roughcut_plan.json"))
            self.assertEqual(plan["steps"][5]["params"]["input"], os.path.join(output, "approved.json"))

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

    def test_rate_operation_rejects_conflicting_signal_artifact_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError,
                "visual_objects: visual_objects, visual_objects_path",
            ):
                operations_module.op_rate_footage(
                    {"input": tmp, "output": tmp},
                    {
                        "config": {
                            "visual_objects": "objects_a.json",
                            "visual_objects_path": "objects_b.json",
                        }
                    },
                )

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


class CalibrationTests(unittest.TestCase):
    def test_annotation_parsing_source_matching_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            footage = os.path.join(tmp, "footage")
            interview = os.path.join(footage, "race_day", "interview.mp4")
            broll = os.path.join(footage, "cars", "broll.mp4")
            shop = os.path.join(footage, "shop.mp4")
            ratings = os.path.join(tmp, "ratings.json")
            annotations = os.path.join(tmp, "annotations.json")
            output = os.path.join(tmp, "calibration")
            _write_calibration_ratings(ratings, footage, interview, broll, shop)
            _write_calibration_annotations(annotations, footage)

            annotation_set = load_annotations(annotations, _read_json(ratings))
            broll_annotation = [clip for clip in annotation_set.clips if clip.source == "broll.mp4"][0]
            self.assertEqual(broll_annotation.canonical_source, broll)
            self.assertEqual(broll_annotation.start, 20.0)

            result = evaluate_ratings(ratings, annotations, output)
            self.assertEqual(result["metrics"]["true_positives"], 1)
            self.assertEqual(result["metrics"]["false_positives"], 1)
            self.assertEqual(result["metrics"]["missed"], 1)
            self.assertEqual(result["metrics"]["precision"], 0.5)
            self.assertEqual(result["metrics"]["recall"], 0.5)
            self.assertTrue(os.path.exists(os.path.join(output, "calibration_report.json")))
            self.assertTrue(os.path.exists(os.path.join(output, "missed_moments.csv")))
            self.assertTrue(os.path.exists(os.path.join(output, "false_positives.csv")))
            with open(os.path.join(output, "calibration_report.json"), encoding="utf-8") as handle:
                report = json.loads(handle.read())
            self.assertEqual(report["metrics"]["recall_by_tag"]["quote"]["recall"], 1.0)
            self.assertEqual(report["score_action_confusion"]["review"]["reject"], 1)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "calibrate",
                            "evaluate",
                            ratings,
                            "--annotations",
                            annotations,
                            "--output",
                            os.path.join(tmp, "calibration_cli"),
                        ]
                    ),
                    0,
                )

    def test_calibration_tune_writes_config_candidates_and_proposed_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            footage = os.path.join(tmp, "footage")
            source = os.path.join(footage, "race.mp4")
            ratings = os.path.join(tmp, "ratings.json")
            annotations = os.path.join(tmp, "annotations.json")
            output = os.path.join(tmp, "calibration")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "root": footage,
                            "config": AnalysisConfig(max_candidates=10).to_dict(),
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": source,
                                    "start": "00:00:08",
                                    "end": "00:00:18",
                                    "score": 78,
                                    "action": "review",
                                    "labels": ["audio_spike"],
                                }
                            ],
                            "signals": [
                                {
                                    "asset": {
                                        "filename": "race.mp4",
                                        "filepath": source,
                                        "duration": 60,
                                        "width": 1920,
                                        "height": 1080,
                                        "codec": "h264",
                                        "fps": 30,
                                        "has_audio": True,
                                        "status": "ok",
                                    },
                                    "scene_changes": [10],
                                    "audio_levels": [
                                        {"time": 9, "rms_db": -42},
                                        {"time": 10, "rms_db": -12},
                                    ],
                                    "scores": {"technical_score": 17},
                                }
                            ],
                        }
                    )
                )
            with open(annotations, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "project": "Tune",
                            "source_root": footage,
                            "clips": [
                                {
                                    "source": "race.mp4",
                                    "start": "00:00:09",
                                    "end": "00:00:14",
                                    "rating": "select",
                                    "tags": ["pass"],
                                }
                            ],
                        }
                    )
                )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(["calibrate", "tune", ratings, "--annotations", annotations, "--output", output]),
                    0,
                )
            result = json.loads(stdout.getvalue())
            self.assertTrue(os.path.exists(result["config_candidates"]))
            self.assertTrue(os.path.exists(result["proposed_config"]))
            with open(result["proposed_config"], encoding="utf-8") as handle:
                proposed = json.loads(handle.read())
            self.assertIn("weights", proposed)
            self.assertIn("min_review_score", proposed)

    def test_calibration_from_decisions_compare_and_apply_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            footage = os.path.join(tmp, "footage")
            interview = os.path.join(footage, "race_day", "interview.mp4")
            broll = os.path.join(footage, "cars", "broll.mp4")
            shop = os.path.join(footage, "shop.mp4")
            ratings = os.path.join(tmp, "ratings.json")
            annotations = os.path.join(tmp, "annotations.json")
            decisions = os.path.join(tmp, "review_decisions.json")
            calibration_a = os.path.join(tmp, "calibration_a")
            calibration_b = os.path.join(tmp, "calibration_b")
            comparison = os.path.join(tmp, "compare")
            _write_calibration_ratings(ratings, footage, interview, broll, shop)
            _write_calibration_annotations(annotations, footage)
            with open(decisions, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "decisions": [
                                {
                                    "id": "clip_0001",
                                    "decision": "approve",
                                    "source": interview,
                                    "start": "00:00:30",
                                    "end": "00:00:45",
                                    "note": "keeper",
                                    "labels": ["quote"],
                                },
                                {
                                    "id": "clip_0002",
                                    "decision": "reject",
                                    "source": interview,
                                    "start": "00:01:10",
                                    "end": "00:01:20",
                                },
                            ]
                        }
                    )
                )

            converted = annotations_from_review_decisions(ratings, decisions, os.path.join(tmp, "from_decisions.json"))
            self.assertEqual(converted["clips"], 2)
            with open(converted["annotations"], encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["clips"][0]["rating"], "select")
            self.assertEqual(data["clips"][1]["rating"], "reject")

            evaluate_ratings(ratings, annotations, calibration_a)
            evaluate_ratings(ratings, converted["annotations"], calibration_b)
            compare = compare_calibration_runs([calibration_a, calibration_b], comparison)
            self.assertTrue(os.path.exists(compare["json"]))
            self.assertTrue(os.path.exists(compare["markdown"]))
            self.assertEqual(compare["runs"], 2)

            proposed = os.path.join(tmp, "proposed_config.json")
            with open(proposed, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"max_candidates": 12, "weights": {"audio": 40}}))
            applied = apply_scoring_config(proposed, os.path.join(tmp, "scoring_config.json"))
            with open(applied["config"], encoding="utf-8") as handle:
                config = json.loads(handle.read())
            self.assertEqual(config["max_candidates"], 12)
            self.assertEqual(config["weights"]["audio"], 40)
            with self.assertRaises(FileExistsError):
                apply_scoring_config(proposed, applied["config"])

    def test_cli_calibrate_commands_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            annotations = os.path.join(tmp, "annotations.json")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["calibrate", "init", "--output", annotations]), 0)
            self.assertTrue(os.path.exists(annotations))
            rows = module_rows(cwd=tmp)
            self.assertTrue(any(row["id"] == "core.calibration" and row["enabled"] for row in rows))
            operations = [operation.name for operation in default_registry(cwd=tmp).list()]
            self.assertIn("evaluate_ratings", operations)
            self.assertIn("calibrate_scoring", operations)


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
                event_data = json.loads(handle.read())
                event_types = [item["event_type"] for item in event_data["events"]]
            with open(topics, encoding="utf-8") as handle:
                topic_data = json.loads(handle.read())
                topic_names = [item["topic"] for item in topic_data["topics"]]
            self.assertEqual(event_data["schema_version"], "videoedit.signal.v1")
            self.assertEqual(event_data["artifact_kind"], "motorsports_events")
            self.assertEqual(event_data["source_count"], 1)
            self.assertIn("pass", event_types)
            self.assertIn("incident", event_types)
            self.assertIn("racecraft", topic_names)
            self.assertIn("incidents", topic_names)
            validation = validate_signal_artifact(events)
            self.assertEqual(validation["status"], "ok")
            self.assertEqual(validation["kind"], "motorsports_events")

            cli_output = os.path.join(tmp, "cli_events.json")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["signals", "motorsports", ratings, "--output", cli_output]), 0)
            self.assertEqual(validate_signal_artifact(cli_output)["status"], "ok")

    def test_optional_object_provider_writes_unavailable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "visual_objects.json")
            result = detect_visual_objects(tmp, output, command="definitely_missing_videoedit_detector")
            self.assertEqual(result["status"], "unavailable")
            with open(output, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["provider"], "visual_objects")
            self.assertEqual(data["schema_version"], "videoedit.signal.v1")
            self.assertEqual(data["status"], "unavailable")
            self.assertEqual(data["count"], 0)

    def test_object_provider_uses_diagnostics_resolver_for_venv_yolo(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            output = os.path.join(tmp, "visual_objects.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("")
            calls = []
            original_resolve = advanced_module.resolve_command
            original_run = advanced_module.run_command

            def fake_resolve(name):
                return "/tmp/videoedit-venv/yolo" if name == "yolo" else None

            def fake_run(args, timeout=180):
                calls.append(args)
                return CommandResult(args=args, returncode=0, stdout="", stderr="")

            advanced_module.resolve_command = fake_resolve
            advanced_module.run_command = fake_run
            try:
                result = detect_visual_objects(source, output)
            finally:
                advanced_module.resolve_command = original_resolve
                advanced_module.run_command = original_run

            self.assertEqual(result["status"], "ok")
            self.assertEqual(calls[0][0], "/tmp/videoedit-venv/yolo")

    def test_object_provider_parses_yolo_labels_into_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            output = os.path.join(tmp, "visual_objects.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("")
            calls = []
            original_resolve = advanced_module.resolve_command
            original_run = advanced_module.run_command
            original_probe = advanced_module.probe_media

            def fake_resolve(name):
                return "/tmp/videoedit-venv/yolo" if name == "yolo" else None

            def fake_run(args, timeout=180):
                calls.append(args)
                project = next(item.split("=", 1)[1] for item in args if item.startswith("project="))
                name = next(item.split("=", 1)[1] for item in args if item.startswith("name="))
                labels = os.path.join(project, name, "labels")
                os.makedirs(labels, exist_ok=True)
                with open(os.path.join(labels, "source_1.txt"), "w", encoding="utf-8") as handle:
                    handle.write("0 0.5 0.5 0.2 0.4 0.91\n2 0.4 0.5 0.3 0.3 0.77\n")
                with open(os.path.join(labels, "source_31.txt"), "w", encoding="utf-8") as handle:
                    handle.write("0 0.6 0.5 0.2 0.4 0.82\n")
                return CommandResult(args=args, returncode=0, stdout="", stderr="")

            def fake_probe(path, timeout=60):
                return MediaAsset(
                    filename=os.path.basename(path),
                    filepath=path,
                    duration=2.0,
                    fps=30.0,
                    status="ok",
                )

            advanced_module.resolve_command = fake_resolve
            advanced_module.run_command = fake_run
            advanced_module.probe_media = fake_probe
            try:
                result = detect_visual_objects(source, output)
            finally:
                advanced_module.resolve_command = original_resolve
                advanced_module.run_command = original_run
                advanced_module.probe_media = original_probe

            project_arg = next(item.split("=", 1)[1] for item in calls[0] if item.startswith("project="))
            self.assertTrue(os.path.isabs(project_arg))
            self.assertEqual(result["detection_count"], 3)
            with open(output, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["schema_version"], "videoedit.signal.v1")
            self.assertEqual(data["artifact_kind"], "visual_objects")
            source_summary = data["sources"][0]
            counts = {item["class_name"]: item["count"] for item in source_summary["class_counts"]}
            self.assertEqual(counts["person"], 2)
            self.assertEqual(counts["car"], 1)
            self.assertEqual(source_summary["detections"][0]["confidence"], 0.91)
            self.assertTrue(any(item["class_name"] == "person" for item in source_summary["segments"]))
            self.assertEqual(data["source_summaries"][0]["detection_count"], 3)

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
            self.assertEqual(data["schema_version"], "videoedit.signal.v1")
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

    def test_extract_script_quotes_shell_arguments_and_validates_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = generate_extract_script(
                [
                    {
                        "source": "/tmp/source; touch pwned.mp4",
                        "start": "00:00:01",
                        "end": "00:00:02.5",
                        "label": "clip; name",
                    }
                ],
                "/tmp/fallback.mp4",
                tmp,
            )
            self.assertIn("'/tmp/source; touch pwned.mp4'", script)
            self.assertIn("-ss 00:00:01", script)
            self.assertIn("-to 00:00:02.5", script)
            self.assertIn("clip_name.mp4", script)
            self.assertNotIn("clip; name.mp4", script)
            with self.assertRaises(ValueError):
                generate_extract_script(
                    [{"source": "/tmp/a.mp4", "start": "00:00:02", "end": "00:00:01", "label": "bad"}],
                    "/tmp/fallback.mp4",
                    tmp,
                )


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

    def test_roughcut_plan_sequences_limits_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            approved = os.path.join(tmp, "approved.json")
            plan = os.path.join(tmp, "roughcut_plan.json")
            with open(approved, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "source": "mixed",
                            "clips": [
                                {
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:10",
                                    "end": "00:00:20",
                                    "label": "first",
                                    "score": 70,
                                    "review_order": 2,
                                },
                                {
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:05",
                                    "end": "00:00:15",
                                    "label": "best",
                                    "score": 95,
                                    "review_order": 1,
                                },
                            ],
                        }
                    )
                )
            result = plan_roughcut(
                approved,
                plan,
                sequence="score",
                target_duration=12,
                format_type="reel",
                handles=1,
                render_mode="render",
            )
            self.assertTrue(os.path.exists(result["plan"]))
            self.assertTrue(os.path.exists(result["report"]))
            with open(plan, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["clips"][0]["label"], "best")
            self.assertEqual(data["format"], "reel")
            self.assertEqual(data["render_mode"], "render")
            self.assertLessEqual(data["summary"]["duration"], 12)

    def test_assemble_uses_roughcut_plan_render_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = os.path.join(tmp, "approved.json")
            plan = os.path.join(tmp, "roughcut_plan.json")
            output = os.path.join(tmp, "rough_cut.mp4")
            with open(selection, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "source": "/tmp/a.mp4",
                            "clips": [
                                {
                                    "source": "/tmp/a.mp4",
                                    "start": "00:00:01",
                                    "end": "00:00:04",
                                    "label": "clip",
                                }
                            ],
                        }
                    )
                )
            plan_roughcut(selection, plan, format_type="youtube", render_mode="render")
            calls = []
            original = review_module.run_command_check

            def fake_run_command_check(args, timeout=180):
                calls.append(args)
                if args[-2].endswith(".mp4"):
                    os.makedirs(os.path.dirname(args[-2]), exist_ok=True)
                    with open(args[-2], "w", encoding="utf-8") as handle:
                        handle.write("")
                return None

            review_module.run_command_check = fake_run_command_check
            try:
                assembled = review_module.assemble(selection, output, plan_json=plan)
            finally:
                review_module.run_command_check = original

            self.assertEqual(assembled, output)
            self.assertIn("-vf", calls[0])
            self.assertIn("libx264", calls[0])
            self.assertEqual(calls[-1][0], "ffmpeg")

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
            self.assertIn("decisionFilter", html)
            self.assertIn("bulkDecision", html)
            self.assertIn("applyBulkDecision", html)
            self.assertIn("clearFilters", html)
            self.assertIn("preserveScroll", html)
            self.assertIn("visibleCount", html)
            self.assertIn("showExportPanel", html)
            self.assertIn("exportDecisionsText", html)

    def test_generate_review_assets_includes_signal_and_calibration_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            ratings = os.path.join(tmp, "ratings.json")
            calibration = os.path.join(tmp, "calibration_report.json")
            output = os.path.join(tmp, "review")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "inventory": [
                                {
                                    "filepath": source,
                                    "filename": "source.mp4",
                                    "duration": 10,
                                    "duration_formatted": "00:00:10",
                                    "resolution": "1920x1080",
                                    "fps": 30,
                                    "codec": "h264",
                                    "has_audio": True,
                                    "size_mb": 10,
                                }
                            ],
                            "signals": [
                                {
                                    "asset": {"filepath": source},
                                    "scores": {"object_presence_score": 10},
                                    "object_hits": [
                                        {
                                            "start": 0,
                                            "end": 4,
                                            "class_name": "person",
                                            "class_id": 0,
                                            "count": 12,
                                        }
                                    ],
                                    "advanced_hits": [
                                        {"kind": "ocr_signage", "source_wide": True, "text": "shop"}
                                    ],
                                }
                            ],
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": source,
                                    "start_seconds": 1,
                                    "end_seconds": 3,
                                    "score": 70,
                                    "action": "review",
                                    "labels": ["object_person"],
                                    "reasons": ["objects detected"],
                                    "signals": {"object_presence_score": 10},
                                }
                            ],
                        }
                    )
                )
            with open(calibration, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "metrics": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                            "matches": [
                                {
                                    "annotation": {"id": "ann_1", "rating": "review"},
                                    "candidate": {"id": "clip_0001"},
                                    "overlap_seconds": 2,
                                    "overlap_ratio": 1.0,
                                }
                            ],
                            "false_positives": [],
                            "missed_moments": [],
                        }
                    )
                )
            result = generate_review_assets(ratings, output, max_items=1, calibration_json=calibration)
            with open(result["manifest"], encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            clip = manifest["clips"][0]
            self.assertEqual(clip["calibration"]["status"], "matched")
            self.assertEqual(clip["source_metadata"]["resolution"], "1920x1080")
            self.assertEqual(clip["object_hits"][0]["class_name"], "person")
            self.assertEqual(clip["advanced_hits"][0]["kind"], "ocr_signage")
            with open(result["contact_sheet"], encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn("searchFilter", html)
            self.assertIn("Calibration: matched", html)
            self.assertIn("Objects: person", html)
            self.assertIn("Approve visible", html)
            self.assertIn("B-roll visible", html)
            self.assertIn("Refresh and select JSON", html)

    def test_review_tui_data_layer_filters_updates_and_saves_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "review_assets.json")
            decisions = os.path.join(tmp, "review_decisions.json")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ratings": "ratings.json",
                            "clips": [
                                {
                                    "id": "clip_0001",
                                    "source_name": "a.mp4",
                                    "action": "review",
                                    "score": 80,
                                    "labels": ["object_person"],
                                    "reasons": ["objects"],
                                    "start": "00:00:01",
                                    "end": "00:00:02",
                                },
                                {
                                    "id": "clip_0002",
                                    "source_name": "b.mp4",
                                    "action": "cut",
                                    "score": 40,
                                    "labels": ["low_signal"],
                                    "reasons": ["fallback"],
                                    "start": "00:00:03",
                                    "end": "00:00:04",
                                },
                            ],
                        }
                    )
                )
            session = load_review_session(manifest)
            filtered = filter_review_clips(session["clips"], label="object_person")
            self.assertEqual([clip["id"] for clip in filtered], ["clip_0001"])
            update_review_decision(session["clips"], "clip_0002", decision="promote", note="use it", order=0)
            write_review_decisions(session["clips"], "ratings.json", decisions)
            with open(decisions, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["decisions"][0]["id"], "clip_0002")
            self.assertEqual(data["decisions"][0]["decision"], "promote")

    def test_review_tui_accepts_decision_without_note(self):
        clips = [
            {
                "id": "clip_0001",
                "source_name": "a.mp4",
                "action": "review",
                "score": 80,
                "labels": [],
                "reasons": [],
                "decision": "review",
                "order": 1,
            }
        ]
        commands = iter(["approve clip_0001", "save"])
        original_input = builtins.input
        try:
            builtins.input = lambda prompt="": next(commands)
            with redirect_stdout(io.StringIO()):
                _interactive_loop(clips)
        finally:
            builtins.input = original_input

        self.assertEqual(clips[0]["decision"], "approve")

    def test_review_tui_handles_invalid_order_and_eof(self):
        clips = [
            {
                "id": "clip_0001",
                "source_name": "a.mp4",
                "action": "review",
                "score": 80,
                "labels": [],
                "reasons": [],
                "decision": "review",
                "order": 1,
            }
        ]
        commands = iter(["order clip_0001 abc"])

        def fake_input(prompt=""):
            try:
                return next(commands)
            except StopIteration as exc:
                raise EOFError from exc

        original_input = builtins.input
        output = io.StringIO()
        try:
            builtins.input = fake_input
            with redirect_stdout(output):
                _interactive_loop(clips)
        finally:
            builtins.input = original_input

        self.assertEqual(clips[0]["order"], 1)
        self.assertIn("Invalid order value: abc", output.getvalue())

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

    def test_project_scaffold_rejects_path_traversal_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = scaffold_project("../..", tmp, project_type="reel")
            self.assertEqual(os.path.basename(result["project"]), "video_project")
            self.assertTrue(os.path.realpath(result["project"]).startswith(os.path.realpath(tmp)))


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


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_calibration_ratings(
    path: str,
    root: str,
    interview: str,
    broll: str,
    shop: str,
) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "root": root,
                    "config": AnalysisConfig().to_dict(),
                    "signals": [
                        {"asset": {"filename": "interview.mp4", "filepath": interview}},
                        {"asset": {"filename": "broll.mp4", "filepath": broll}},
                        {"asset": {"filename": "shop.mp4", "filepath": shop}},
                    ],
                    "candidates": [
                        {
                            "id": "clip_0001",
                            "source": interview,
                            "start": "00:00:30",
                            "end": "00:00:45",
                            "score": 92,
                            "action": "select",
                            "labels": ["transcript_hit"],
                            "reasons": ["strong quote"],
                        },
                        {
                            "id": "clip_0002",
                            "source": interview,
                            "start": "00:01:10",
                            "end": "00:01:20",
                            "score": 82,
                            "action": "review",
                            "labels": ["audio_spike"],
                            "reasons": ["loud but not useful"],
                        },
                        {
                            "id": "clip_0003",
                            "source": shop,
                            "start": "00:00:10",
                            "end": "00:00:15",
                            "score": 72,
                            "action": "review",
                            "labels": ["scene_change"],
                            "reasons": ["ignored calibration region"],
                        },
                    ],
                }
            )
        )


def _write_calibration_annotations(path: str, source_root: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "project": "Drive Auto Sports Calibration",
                    "source_root": source_root,
                    "clips": [
                        {
                            "source": "race_day/interview.mp4",
                            "start": "00:00:32",
                            "end": "00:00:40",
                            "rating": "select",
                            "tags": ["quote"],
                            "notes": "Strong quote",
                        },
                        {
                            "source": "broll.mp4",
                            "start": 20,
                            "end": 30,
                            "rating": "broll",
                            "tags": ["motion_bank"],
                        },
                        {
                            "source": "race_day/interview.mp4",
                            "start": "00:01:10",
                            "end": "00:01:20",
                            "rating": "reject",
                        },
                        {
                            "source": "shop.mp4",
                            "start": "00:00:10",
                            "end": "00:00:15",
                            "rating": "ignore",
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
