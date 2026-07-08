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
from videoedit.ai import (
    find_missed_moments,
    generate_missed_review,
    get_ai_profile,
    list_ai_profiles,
    score_frames,
    show_ai_profile,
)
import videoedit.ai as ai_module
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
from videoedit.cloud import cloud_diagnostics, list_cloud_adapters, plan_cloud_job
from videoedit.cli import main
import videoedit.cli as cli_module
from videoedit.content import generate_content_map, generate_quote_mining, plan_content_series
from videoedit.diagnostics import format_diagnostics, run_diagnostics
from videoedit.edl import export_selection_file, generate_extract_script
from videoedit.ffmpeg import CommandResult, parse_audio_metadata_output, parse_scene_output, parse_silence_output, run_command_check
from videoedit.models import AudioLevel, CandidateClip, MediaAsset, ObjectHit, SignalReport
from videoedit.modules import disable_module, enable_module, module_rows, operation_enabled
import videoedit.modules as modules_module
from videoedit.operations import default_registry
import videoedit.operations as operations_module
from videoedit.pipeline import available_presets, load_pipeline, plan_pipeline, run_pipeline, validate_pipeline, write_preset
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

    def test_ai_frame_hits_seed_labels_and_scores(self):
        config = AnalysisConfig(max_candidates=10)
        asset = MediaAsset(
            filename="shop.mp4",
            filepath="/tmp/shop.mp4",
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
                {
                    "kind": "ai_frame_score",
                    "start": 8,
                    "end": 9,
                    "top_score": 0.86,
                    "top_label": "ai_garage_work",
                    "labels": ["ai_garage_work", "ai_broll_candidate"],
                    "explanation": "AI frame match",
                }
            ],
        )
        candidates = generate_candidates([report], config)
        self.assertEqual(len(candidates), 1)
        self.assertIn("ai_garage_work", candidates[0].labels)
        self.assertIn("ai_broll_candidate", candidates[0].labels)
        self.assertGreater(candidates[0].signals["ai_frame_score"], 0)


class AITests(unittest.TestCase):
    def test_profiles_are_project_agnostic_and_distinct(self):
        profile_ids = {profile["id"] for profile in list_ai_profiles()}
        self.assertTrue(
            {
                "general_broll",
                "garage_shop",
                "motorsports",
                "interview",
                "event_recap",
                "social_reel",
                "documentary",
            }.issubset(profile_ids)
        )
        garage_prompts = {prompt["text"] for prompt in show_ai_profile("garage_shop")["prompts"]}
        interview_prompts = {prompt["text"] for prompt in show_ai_profile("interview")["prompts"]}
        self.assertNotEqual(garage_prompts, interview_prompts)
        serialized = json.dumps(show_ai_profile("garage_shop")).lower()
        self.assertNotIn("drive auto sports", serialized)
        self.assertNotIn("garage 19", serialized)

    def test_unknown_profile_has_clear_error(self):
        with self.assertRaisesRegex(KeyError, "unknown AI profile"):
            get_ai_profile("not_real")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["ai", "profiles", "show", "not_real"])
        self.assertEqual(exit_code, 1)
        self.assertIn("unknown AI profile", stderr.getvalue())

    def test_generate_missed_review_operation_requires_input(self):
        with self.assertRaisesRegex(ValueError, "requires ai_missed_moments"):
            operations_module.op_generate_missed_review({"output": "/tmp/out"}, {})

    def test_score_frames_with_mock_encoder_and_cache(self):
        class FakeEncoder:
            provider_name = "fake_openclip"
            model_name = "fake-model"

            def __init__(self):
                self.calls = 0

            def score_images(self, image_paths, prompts):
                self.calls += 1
                return [[0.8 if index == 0 else 0.05 for index, _prompt in enumerate(prompts)] for _ in image_paths]

        def fake_probe(path, timeout=60):
            return MediaAsset(filename=os.path.basename(path), filepath=path, duration=22.0)

        def fake_sampler(source, timestamp, output, timeout=180):
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(f"{source} {timestamp}")

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "shop.mp4")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("video")
            output = os.path.join(tmp, "ai_frame_scores.json")
            encoder = FakeEncoder()
            result = score_frames(
                source,
                output,
                profile_id="garage_shop",
                sample_interval=10,
                max_frames_per_file=2,
                encoder=encoder,
                frame_sampler=fake_sampler,
                media_probe=fake_probe,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(encoder.calls, 1)
            data = _read_json(output)
            self.assertEqual(data["schema_version"], "videoedit.ai_frame_scores.v1")
            self.assertEqual(data["profile"]["id"], "garage_shop")
            self.assertEqual(len(data["sources"][0]["frames"]), 2)
            frame = data["sources"][0]["frames"][0]
            self.assertIn("prompt_scores", frame)
            self.assertIn("labels", frame)
            self.assertIn("explanation", frame)

            cached_encoder = FakeEncoder()
            cached = score_frames(
                source,
                output,
                profile_id="garage_shop",
                sample_interval=10,
                max_frames_per_file=2,
                encoder=cached_encoder,
                frame_sampler=fake_sampler,
                media_probe=fake_probe,
            )
            self.assertEqual(cached["frames"], 2)
            self.assertEqual(cached_encoder.calls, 0)

    def test_score_frames_uses_unique_names_for_matching_basenames(self):
        class FakeEncoder:
            provider_name = "fake_openclip"
            model_name = "fake-model"

            def score_images(self, image_paths, prompts):
                return [[0.8 if index == 0 else 0.05 for index, _prompt in enumerate(prompts)] for _ in image_paths]

        def fake_probe(path, timeout=60):
            return MediaAsset(filename=os.path.basename(path), filepath=path, duration=10.0)

        def fake_sampler(source, timestamp, output, timeout=180):
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(f"{source} {timestamp}")

        with tempfile.TemporaryDirectory() as tmp:
            for folder in ("camera_a", "camera_b"):
                os.makedirs(os.path.join(tmp, folder), exist_ok=True)
                with open(os.path.join(tmp, folder, "clip.mp4"), "w", encoding="utf-8") as handle:
                    handle.write("video")
            output = os.path.join(tmp, "ai_frame_scores.json")
            score_frames(
                tmp,
                output,
                profile_id="general_broll",
                sample_interval=10,
                max_frames_per_file=1,
                encoder=FakeEncoder(),
                frame_sampler=fake_sampler,
                media_probe=fake_probe,
            )
            data = _read_json(output)
            frames = [source["frames"][0]["frame"] for source in data["sources"]]
            self.assertEqual(len(frames), 2)
            self.assertEqual(len(set(frames)), 2)
            self.assertTrue(all(os.path.basename(frame).startswith("clip_") for frame in frames))

    def test_score_frames_missing_dependencies_writes_unavailable_artifact(self):
        original = ai_module.OpenCLIPEncoder

        class FailingEncoder:
            def __init__(self, model, pretrained):
                raise ImportError("Install with: python -m pip install -e './src/python[ai]'")

        ai_module.OpenCLIPEncoder = FailingEncoder
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source = os.path.join(tmp, "source.mp4")
                with open(source, "w", encoding="utf-8") as handle:
                    handle.write("video")
                output = os.path.join(tmp, "scores.json")
                result = score_frames(source, output, profile_id="general_broll")
                self.assertEqual(result["status"], "unavailable")
                data = _read_json(output)
                self.assertIn("Install with", data["error"])
        finally:
            ai_module.OpenCLIPEncoder = original

    def test_judge_review_clips_with_mock_provider_writes_artifact(self):
        class FakeProvider:
            provider_name = "fake_vlm"
            model_name = "fake-clip-judge"

            def judge_clip(self, request):
                self.request = request
                return {
                    "score_dimensions": {"visual_interest": 0.82, "story_value": 0.67, "social_hook": 0.91},
                    "suggested_action": "select",
                    "labels": ["ai_clip_judge", "ai_social_hook"],
                    "reason": "Strong hook frame and visible action.",
                }

        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "review_assets.json")
            output = os.path.join(tmp, "ai_clip_judgments.json")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ratings": os.path.join(tmp, "ratings.json"),
                            "clips": [
                                {
                                    "id": "clip_0001",
                                    "source": os.path.join(tmp, "source.mp4"),
                                    "source_name": "source.mp4",
                                    "start": "00:00:05",
                                    "end": "00:00:09",
                                    "start_seconds": 5,
                                    "end_seconds": 9,
                                    "score": 72,
                                    "action": "review",
                                    "labels": ["ai_broll_candidate"],
                                    "reasons": ["deterministic reason"],
                                    "signals": {"audio_interest_score": 12},
                                    "thumbnail": "thumbnails/clip_0001.jpg",
                                    "proxy": "proxies/clip_0001.mp4",
                                }
                            ],
                        }
                    )
                )
            provider = FakeProvider()
            result = ai_module.judge_review_clips(manifest, output, profile_id="social_reel", provider=provider)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(provider.request["profile"]["id"], "social_reel")
            self.assertEqual(provider.request["clip"]["id"], "clip_0001")
            data = _read_json(output)
            self.assertEqual(data["schema_version"], "videoedit.ai_clip_judgments.v1")
            self.assertEqual(data["provider"]["name"], "fake_vlm")
            judgment = data["clips"][0]
            self.assertEqual(judgment["clip_id"], "clip_0001")
            self.assertEqual(judgment["suggested_action"], "select")
            self.assertIn("ai_social_hook", judgment["labels"])
            self.assertIn("Strong hook", judgment["reason"])
            self.assertGreater(judgment["score"], 0)

    def test_judge_review_clips_retries_invalid_model_json(self):
        class FlakyProvider:
            provider_name = "fake_vlm"
            model_name = "fake-clip-judge"

            def __init__(self):
                self.calls = 0

            def judge_clip(self, request):
                self.calls += 1
                if self.calls == 1:
                    return "not json"
                return json.dumps(
                    {
                        "score_dimensions": {"visual_interest": 0.5},
                        "suggested_action": "review",
                        "labels": ["ai_clip_judge"],
                        "reason": "Usable but not a top pick.",
                    }
                )

        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "review_assets.json")
            output = os.path.join(tmp, "ai_clip_judgments.json")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"clips": [{"id": "clip_0001", "source": "source.mp4", "score": 50}]}))
            provider = FlakyProvider()
            result = ai_module.judge_review_clips(manifest, output, provider=provider, retries=1)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(provider.calls, 2)
            self.assertEqual(_read_json(output)["clips"][0]["suggested_action"], "review")

    def test_judge_review_clips_missing_provider_writes_unavailable_artifact(self):
        original = os.environ.pop("VIDEOEDIT_AI_JUDGE_COMMAND", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manifest = os.path.join(tmp, "review_assets.json")
                output = os.path.join(tmp, "ai_clip_judgments.json")
                with open(manifest, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"clips": [{"id": "clip_0001", "source": "source.mp4"}]}))
                result = ai_module.judge_review_clips(manifest, output)
                self.assertEqual(result["status"], "unavailable")
                data = _read_json(output)
                self.assertIn("VIDEOEDIT_AI_JUDGE_COMMAND", data["error"])
        finally:
            if original is not None:
                os.environ["VIDEOEDIT_AI_JUDGE_COMMAND"] = original

    def test_ai_judge_cli_uses_local_provider_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "review_assets.json")
            output = os.path.join(tmp, "ai_clip_judgments.json")
            provider_script = os.path.join(tmp, "judge_provider.py")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"clips": [{"id": "clip_0001", "source": "source.mp4", "score": 50}]}))
            with open(provider_script, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json, sys\n"
                    "json.loads(sys.stdin.read())\n"
                    "print(json.dumps({"
                    "'score_dimensions': {'visual_interest': 0.7}, "
                    "'suggested_action': 'review', "
                    "'labels': ['ai_clip_judge'], "
                    "'reason': 'Local provider accepted the clip.'"
                    "}))\n"
                )
            exit_code = main(
                [
                    "ai",
                    "judge",
                    manifest,
                    "--profile",
                    "social_reel",
                    "--output",
                    output,
                    "--provider-command",
                    f'"{sys.executable}" "{provider_script}"',
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(_read_json(output)["clips"][0]["reason"], "Local provider accepted the clip.")

    def test_candidate_clip_serializes_ai_explanations_only_when_present(self):
        base = CandidateClip(
            id="clip_0001",
            source="source.mp4",
            start=0,
            end=5,
            score=70,
            action="review",
            labels=[],
            reasons=[],
            signals={},
        )
        self.assertNotIn("ai_explanations", base.to_dict())
        with_ai = CandidateClip.from_dict(
            {
                **base.to_dict(),
                "ai_explanations": [
                    {
                        "kind": "ai_clip_judge",
                        "score": 80,
                        "suggested_action": "select",
                        "reason": "AI reason",
                    }
                ],
            }
        )
        self.assertEqual(with_ai.to_dict()["ai_explanations"][0]["reason"], "AI reason")

    def test_ai_signal_artifact_loader_matches_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = os.path.join(tmp, "ai_frame_scores.json")
            with open(artifact, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.ai_frame_scores.v1",
                            "artifact_kind": "ai_frame_scores",
                            "provider": "fake_openclip",
                            "profile": {"id": "garage_shop"},
                            "sources": [
                                {
                                    "source": "clips/shop.mp4",
                                    "frames": [
                                        {
                                            "time_seconds": 5,
                                            "time": "00:00:05",
                                            "top_score": 0.9,
                                            "top_label": "ai_garage_work",
                                            "labels": ["ai_garage_work"],
                                            "prompt_scores": [{"id": "hands_tools", "label": "ai_garage_work", "score": 0.9}],
                                            "explanation": "mock",
                                        }
                                    ],
                                }
                            ],
                        }
                    )
                )
            config = AnalysisConfig(ai_frame_scores_path=artifact)
            bundle = load_signal_artifacts(config)
            hits = bundle.advanced_for(os.path.join(tmp, "other", "shop.mp4"))
            self.assertEqual(hits[0]["kind"], "ai_frame_score")
            self.assertEqual(hits[0]["labels"], ["ai_garage_work"])

    def test_find_missed_moments_merges_adjacent_low_ranked_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "shop.mp4")
            ratings = os.path.join(tmp, "ratings.json")
            scores = os.path.join(tmp, "ai_frame_scores.json")
            output = os.path.join(tmp, "ai_missed_moments.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "root": tmp,
                            "candidates": [
                                {"id": "clip_0001", "source": source, "start": "00:00:10", "end": "00:00:20", "score": 90, "action": "select"},
                                {"id": "clip_0002", "source": source, "start": "00:00:30", "end": "00:00:35", "score": 30, "action": "cut"},
                            ],
                        }
                    )
                )
            with open(scores, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.ai_frame_scores.v1",
                            "artifact_kind": "ai_frame_scores",
                            "profile": {"id": "garage_shop"},
                            "sources": [
                                {
                                    "source": source,
                                    "frames": [
                                        {"time_seconds": 12, "top_score": 0.99, "labels": ["ai_garage_work"], "prompt_scores": []},
                                        {"time_seconds": 31, "top_score": 0.91, "labels": ["ai_garage_work"], "prompt_scores": [{"id": "hands", "label": "ai_garage_work", "score": 0.91}]},
                                        {"time_seconds": 33, "top_score": 0.88, "labels": ["ai_broll_candidate"], "prompt_scores": [{"id": "detail", "label": "ai_broll_candidate", "score": 0.88}]},
                                        {"time_seconds": 60, "top_score": 0.1, "labels": ["ai_garage_work"], "prompt_scores": []},
                                    ],
                                }
                            ],
                        }
                    )
                )
            result = find_missed_moments(ratings, scores, output, min_score=0.35, merge_gap=5)
            self.assertEqual(result["count"], 1)
            data = _read_json(output)
            moment = data["moments"][0]
            self.assertEqual(moment["id"], "missed_0001")
            self.assertIn("ai_garage_work", moment["labels"])
            self.assertIn("ai_broll_candidate", moment["labels"])
            self.assertEqual(moment["existing_candidate"]["id"], "clip_0002")

    def test_missed_review_decisions_are_annotation_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            missed = os.path.join(tmp, "ai_missed_moments.json")
            review_dir = os.path.join(tmp, "review")
            annotations = os.path.join(tmp, "annotations.json")
            source = os.path.join(tmp, "shop.mp4")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"root": tmp, "candidates": []}))
            with open(missed, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.ai_missed_moments.v1",
                            "ratings": ratings,
                            "ai_frame_scores": os.path.join(tmp, "scores.json"),
                            "moments": [
                                {
                                    "id": "missed_0001",
                                    "source": source,
                                    "start": "00:00:30",
                                    "end": "00:00:40",
                                    "start_seconds": 30,
                                    "end_seconds": 40,
                                    "confidence": 0.8,
                                    "labels": ["ai_garage_work"],
                                    "prompt_matches": [],
                                    "reason": "AI frame match",
                                }
                            ],
                        }
                    )
            )
            result = generate_missed_review(missed, review_dir)
            with open(result["html"], encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn("Missed Moment Review", html)
            self.assertIn('value="ignore"', html)
            self.assertIn("preserveScroll", html)
            self.assertIn("applyBulkDecision", html)
            converted = annotations_from_review_decisions(ratings, result["decisions"], annotations)
            self.assertEqual(converted["clips"], 1)
            data = _read_json(annotations)
            self.assertEqual(data["clips"][0]["rating"], "review")


class LearningTests(unittest.TestCase):
    def test_build_review_dataset_from_multiple_projects_without_source_paths(self):
        from videoedit.learning import build_review_dataset

        with tempfile.TemporaryDirectory() as tmp:
            inputs = []
            for project, decision, score, ai_score in (
                ("Drive Example", "approve", 82, 91),
                ("Garage Example", "reject", 42, 20),
            ):
                project_dir = os.path.join(tmp, project.replace(" ", "_"))
                os.makedirs(project_dir, exist_ok=True)
                ratings = os.path.join(project_dir, "ratings.json")
                decisions = os.path.join(project_dir, "review_decisions.json")
                source = os.path.join(project_dir, "private_source.mp4")
                with open(ratings, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "project": project,
                                "root": os.path.join(project_dir, "footage"),
                                "config": {"profile": "shop_reel"},
                                "candidates": [
                                    {
                                        "id": "clip_0001",
                                        "source": source,
                                        "start": "00:00:01",
                                        "end": "00:00:06",
                                        "start_seconds": 1,
                                        "end_seconds": 6,
                                        "duration": 5,
                                        "score": score,
                                        "action": "review",
                                        "labels": ["audio_spike", "ai_clip_judge"],
                                        "reasons": ["deterministic reason"],
                                        "signals": {"audio_interest_score": 12, "ai_frame_score": 4},
                                        "ai_explanations": [
                                            {
                                                "score": ai_score,
                                                "suggested_action": "select",
                                                "labels": ["ai_clip_judge"],
                                                "reason": "AI reason",
                                            }
                                        ],
                                    }
                                ],
                            }
                        )
                    )
                with open(decisions, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "ratings": ratings,
                                "project": project,
                                "project_profile": "shop_reel",
                                "decisions": [
                                    {
                                        "id": "clip_0001",
                                        "decision": decision,
                                        "order": 1,
                                        "note": f"{project} note",
                                    }
                                ],
                            }
                        )
                    )
                inputs.append(decisions)
            output = os.path.join(tmp, "review_dataset.jsonl")
            result = build_review_dataset(inputs, output)
            self.assertEqual(result["records"], 2)
            with open(output, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual({row["project"]["name"] for row in rows}, {"Drive Example", "Garage Example"})
            self.assertNotIn("source_path", json.dumps(rows))
            self.assertIn("source_id", rows[0]["clip"])
            self.assertEqual(rows[0]["features"]["deterministic_score"], 82)
            self.assertIn("label_audio_spike", rows[0]["features"])
            self.assertIn("ai_clip_judge_score", rows[0]["features"])
            self.assertEqual({row["label"]["target"] for row in rows}, {0, 1})

    def test_train_local_scorer_is_small_inspectable_and_ranks_deterministically(self):
        from videoedit.learning import score_candidate_with_model, train_local_scorer

        with tempfile.TemporaryDirectory() as tmp:
            dataset = os.path.join(tmp, "review_dataset.jsonl")
            model = os.path.join(tmp, "local_scorer.json")
            rows = [
                {
                    "schema_version": "videoedit.review_dataset.v1",
                    "features": {"deterministic_score": 90, "audio_interest_score": 12, "label_audio_spike": 1},
                    "label": {"rating": "select", "target": 1},
                },
                {
                    "schema_version": "videoedit.review_dataset.v1",
                    "features": {"deterministic_score": 35, "audio_interest_score": 0, "label_audio_spike": 0},
                    "label": {"rating": "reject", "target": 0},
                },
            ]
            with open(dataset, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            result = train_local_scorer(dataset, model)
            self.assertEqual(result["records"], 2)
            data = _read_json(model)
            self.assertEqual(data["schema_version"], "videoedit.learned_scorer.v1")
            self.assertIn("weights", data)
            self.assertLess(os.path.getsize(model), 10000)
            positive = score_candidate_with_model(
                {
                    "score": 88,
                    "signals": {"audio_interest_score": 10},
                    "labels": ["audio_spike"],
                },
                data,
            )
            negative = score_candidate_with_model(
                {
                    "score": 20,
                    "signals": {"audio_interest_score": 0},
                    "labels": [],
                },
                data,
            )
            self.assertGreater(positive["score"], negative["score"])
            self.assertIn("learned_score", positive["signals"])

    def test_ai_dataset_and_train_scorer_cli_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            decisions = os.path.join(tmp, "review_decisions.json")
            dataset = os.path.join(tmp, "training", "review_dataset.jsonl")
            model = os.path.join(tmp, "models", "local_scorer.json")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/private/source.mp4",
                                    "start_seconds": 0,
                                    "end_seconds": 5,
                                    "score": 80,
                                    "action": "review",
                                    "labels": ["audio_spike"],
                                    "signals": {"audio_interest_score": 10},
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/private/source.mp4",
                                    "start_seconds": 10,
                                    "end_seconds": 15,
                                    "score": 20,
                                    "action": "cut",
                                    "labels": [],
                                    "signals": {"audio_interest_score": 0},
                                }
                            ]
                        }
                    )
                )
            with open(decisions, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ratings": ratings,
                            "decisions": [
                                {"id": "clip_0001", "decision": "approve"},
                                {"id": "clip_0002", "decision": "reject"},
                            ],
                        }
                    )
                )
            self.assertEqual(main(["ai", "dataset", "build", "--inputs", decisions, "--output", dataset]), 0)
            self.assertTrue(os.path.exists(dataset))
            self.assertEqual(main(["ai", "train-scorer", dataset, "--output", model]), 0)
            self.assertEqual(_read_json(model)["schema_version"], "videoedit.learned_scorer.v1")

    def test_train_local_scorer_rejects_single_class_dataset(self):
        from videoedit.learning import train_local_scorer

        with tempfile.TemporaryDirectory() as tmp:
            dataset = os.path.join(tmp, "review_dataset.jsonl")
            model = os.path.join(tmp, "local_scorer.json")
            with open(dataset, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.review_dataset.v1",
                            "features": {"deterministic_score": 90},
                            "label": {"rating": "select", "target": 1},
                        }
                    )
                    + "\n"
                )
            with self.assertRaisesRegex(ValueError, "both positive and negative"):
                train_local_scorer(dataset, model)

    def test_rate_config_accepts_learned_scorer_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = os.path.join(tmp, "local_scorer.json")
            with open(model, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"schema_version": "videoedit.learned_scorer.v1", "weights": {}, "intercept": 0}))
            parser = cli_module.build_parser()
            args = parser.parse_args(["rate", tmp, "--output", os.path.join(tmp, "analysis"), "--learned-scorer", model])
            config = cli_module.config_from_args(args)
            self.assertEqual(config.learned_scorer_path, model)

    def test_run_rating_with_learned_scorer_adds_learned_signal(self):
        import videoedit.rating as rating_module

        original_scan = rating_module.scan_video_files
        original_probe = rating_module.probe_media
        original_scene = rating_module.detect_scene_changes
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "clip.mp4")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("video")
            model = os.path.join(tmp, "local_scorer.json")
            with open(model, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.learned_scorer.v1",
                            "weights": {"deterministic_score": 1.0},
                            "intercept": 0,
                            "threshold": 0,
                        }
                    )
                )

            def fake_scan(_directory):
                return [source]

            def fake_probe(path, timeout=60):
                return MediaAsset(
                    filename=os.path.basename(path),
                    filepath=path,
                    duration=8,
                    width=1920,
                    height=1080,
                    fps=30,
                    codec="h264",
                    has_audio=False,
                )

            rating_module.scan_video_files = fake_scan
            rating_module.probe_media = fake_probe
            rating_module.detect_scene_changes = lambda path, threshold=0.35, timeout=180: ([], None)
            try:
                output = os.path.join(tmp, "analysis")
                report = rating_module.run_rating(tmp, output, AnalysisConfig(learned_scorer_path=model, cache=False))
            finally:
                rating_module.scan_video_files = original_scan
                rating_module.probe_media = original_probe
                rating_module.detect_scene_changes = original_scene

            self.assertEqual(len(report.candidates), 1)
            self.assertIn("learned_score", report.candidates[0].signals)
            self.assertIn("learned_positive", report.candidates[0].labels)
            data = _read_json(os.path.join(output, "ratings.json"))
            self.assertEqual(data["config"]["learned_scorer_path"], model)
            self.assertIn("learned_score", data["candidates"][0]["signals"])

    def test_learned_scorer_does_not_invalidate_file_analysis_signature(self):
        import videoedit.rating as rating_module

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "clip.mp4")
            model_a = os.path.join(tmp, "model_a.json")
            model_b = os.path.join(tmp, "model_b.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("video")
            with open(model_a, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"schema_version": "videoedit.learned_scorer.v1", "weights": {"a": 1}}))
            with open(model_b, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"schema_version": "videoedit.learned_scorer.v1", "weights": {"b": 2}}))

            signature_a = rating_module._file_signature(
                source,
                AnalysisConfig(learned_scorer_path=model_a),
            )
            signature_b = rating_module._file_signature(
                source,
                AnalysisConfig(learned_scorer_path=model_b),
            )
            self.assertEqual(signature_a, signature_b)
            self.assertNotIn("learned_scorer_path", signature_a)
            self.assertNotIn("learned_scorer_signature", signature_a)

    def test_calibration_detects_ai_mode_when_ai_frame_score_is_zero(self):
        import videoedit.calibration as calibration_module

        modes = calibration_module._scoring_modes(
            {"candidates": []},
            [{"signals": {"ai_frame_score": 0.0}}],
        )
        self.assertEqual(modes, ["deterministic", "ai-assisted"])

    def test_calibration_compare_preserves_scoring_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline")
            learned = os.path.join(tmp, "learned")
            os.makedirs(baseline)
            os.makedirs(learned)
            for path, modes, f1 in (
                (baseline, ["deterministic"], 0.5),
                (learned, ["deterministic", "learned"], 0.75),
            ):
                with open(os.path.join(path, "calibration_report.json"), "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "metrics": {
                                    "precision": f1,
                                    "recall": f1,
                                    "f1": f1,
                                    "missed": 1,
                                    "false_positives": 1,
                                },
                                "summary": {},
                                "scoring_modes": modes,
                            }
                        )
                    )
            result = compare_calibration_runs([baseline, learned], os.path.join(tmp, "compare"))
            self.assertEqual(result["best"]["scoring_modes"], ["deterministic", "learned"])
            with open(result["markdown"], encoding="utf-8") as handle:
                markdown = handle.read()
            self.assertIn("Modes", markdown)
            self.assertIn("learned", markdown)


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

    def test_ai_presets_declare_requirements_and_plan_artifacts(self):
        expected_profiles = {
            "ai_reel": "social_reel",
            "ai_garage_shop": "garage_shop",
            "ai_event_recap": "event_recap",
        }
        for preset, profile in expected_profiles.items():
            with tempfile.TemporaryDirectory() as tmp:
                output = os.path.join(tmp, f"{preset}.yaml")
                write_preset(preset, output)
                data = load_pipeline(output)
                self.assertEqual(data["name"], preset)
                self.assertIn("advanced.ai", data["requires_modules"])
                self.assertIn("core.review", data["requires_modules"])
                dependency_names = {item["name"] for item in data["requires_dependencies"]}
                self.assertGreaterEqual(dependency_names, {"open_clip", "torch", "PIL"})
                operations = [step["operation"] for step in data["steps"]]
                self.assertIn("score_ai_frames", operations)
                self.assertIn("rate_footage", operations)
                self.assertIn("generate_review_assets", operations)
                score_step = next(step for step in data["steps"] if step["operation"] == "score_ai_frames")
                self.assertEqual(score_step["params"]["profile"], profile)
                rate_step = next(step for step in data["steps"] if step["operation"] == "rate_footage")
                self.assertEqual(rate_step["params"]["ai_frame_scores"], "ai_scores.output")

                plan = plan_pipeline(output, os.path.join(tmp, "footage"), os.path.join(tmp, "out"))
                self.assertEqual(plan["requirements"]["modules"], data["requires_modules"])
                self.assertEqual(plan["requirements"]["dependencies"], data["requires_dependencies"])
                planned_ai = next(step for step in plan["steps"] if step["operation"] == "score_ai_frames")
                self.assertEqual(
                    planned_ai["planned_result"]["output"],
                    os.path.join(tmp, "out", "signals", "ai_frame_scores.json"),
                )
                planned_rate = next(step for step in plan["steps"] if step["operation"] == "rate_footage")
                self.assertEqual(
                    planned_rate["params"]["ai_frame_scores"],
                    os.path.join(tmp, "out", "signals", "ai_frame_scores.json"),
                )

    def test_ai_preset_validation_fails_when_ai_module_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                disable_module("advanced.ai")
                pipeline = os.path.join(tmp, "ai_reel.yaml")
                with open(pipeline, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "name": "ai_reel",
                                "requires_modules": ["advanced.ai"],
                                "steps": [{"name": "ai_scores", "operation": "score_ai_frames"}],
                            }
                        )
                    )
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    exit_code = main(["validate", pipeline])
                self.assertEqual(exit_code, 1)
                self.assertIn("requires disabled module advanced.ai", stderr.getvalue())
            finally:
                os.chdir(cwd)

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
        for preset in [
            "simple",
            "reel",
            "roughcut",
            "youtube",
            "documentary",
            "motorsports",
            "vision_reel",
            "ai_reel",
            "ai_garage_shop",
            "ai_event_recap",
        ]:
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

    def test_create_approval_file_treats_broll_as_handoff_decision(self):
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
                                    "score": 55,
                                    "action": "cut",
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/tmp/b.mp4",
                                    "start": "00:00:06",
                                    "end": "00:00:10",
                                    "score": 95,
                                    "action": "select",
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
                                {"id": "clip_0001", "decision": "broll", "order": 1, "note": "use as texture"},
                                {"id": "clip_0002", "decision": "ignore", "order": 2, "note": "already used"},
                            ]
                        }
                    )
                )
            create_approval_file(ratings, approved, decisions_json=decisions)
            with open(approved, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual([clip["label"] for clip in data["clips"]], ["clip_0001"])
            self.assertEqual(data["clips"][0]["review_decision"], "broll")
            self.assertEqual(data["clips"][0]["review_note"], "use as texture")

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
            with open(result["manifest"], encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            self.assertNotIn("ai_explanations", manifest["clips"][0])

    def test_generate_review_assets_preserves_existing_decisions_on_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            output = os.path.join(tmp, "review")
            os.makedirs(output, exist_ok=True)
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": "/missing/a.mp4",
                                    "start_seconds": 0,
                                    "end_seconds": 4,
                                    "score": 70,
                                    "action": "review",
                                },
                                {
                                    "id": "clip_0002",
                                    "source": "/missing/b.mp4",
                                    "start_seconds": 10,
                                    "end_seconds": 14,
                                    "score": 50,
                                    "action": "cut",
                                },
                            ]
                        }
                    )
                )
            with open(os.path.join(output, "review_decisions.json"), "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ratings": ratings,
                            "decisions": [
                                {"id": "clip_0001", "decision": "broll", "order": 7, "note": "texture shot"},
                                {"id": "removed_clip", "decision": "approve", "order": 1, "note": "old"},
                            ],
                        }
                    )
                )

            result = generate_review_assets(ratings, output, max_items=2)
            with open(result["decisions"], encoding="utf-8") as handle:
                decisions = json.loads(handle.read())
            rows = {row["id"]: row for row in decisions["decisions"]}
            self.assertEqual(set(rows), {"clip_0001", "clip_0002"})
            self.assertEqual(rows["clip_0001"]["decision"], "broll")
            self.assertEqual(rows["clip_0001"]["order"], 7)
            self.assertEqual(rows["clip_0001"]["note"], "texture shot")
            self.assertEqual(rows["clip_0002"]["decision"], "reject")
            self.assertEqual(rows["clip_0002"]["order"], 8)
            with open(result["contact_sheet"], encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn('<option value="broll" selected>B-roll</option>', html)
            self.assertIn('value="7"', html)
            self.assertIn(">texture shot</textarea>", html)

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

    def test_generate_review_assets_keeps_ai_explanations_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            ratings = os.path.join(tmp, "ratings.json")
            judgments = os.path.join(tmp, "ai_clip_judgments.json")
            output = os.path.join(tmp, "review")
            source = os.path.join(tmp, "source.mp4")
            with open(ratings, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "id": "clip_0001",
                                    "source": source,
                                    "start_seconds": 0,
                                    "end_seconds": 5,
                                    "score": 70,
                                    "action": "review",
                                    "labels": ["audio_spike"],
                                    "reasons": ["1 audio spikes detected"],
                                }
                            ]
                        }
                    )
                )
            with open(judgments, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "videoedit.ai_clip_judgments.v1",
                            "artifact_kind": "ai_clip_judgments",
                            "clips": [
                                {
                                    "clip_id": "clip_0001",
                                    "score": 84.0,
                                    "score_dimensions": {"visual_interest": 0.84},
                                    "suggested_action": "select",
                                    "labels": ["ai_clip_judge"],
                                    "reason": "AI sees a strong visual hook.",
                                }
                            ],
                        }
                    )
                )
            result = generate_review_assets(ratings, output, max_items=1, ai_clip_judgments_json=judgments)
            with open(result["manifest"], encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            clip = manifest["clips"][0]
            self.assertEqual(clip["reasons"], ["1 audio spikes detected"])
            self.assertEqual(clip["ai_explanations"][0]["reason"], "AI sees a strong visual hook.")
            with open(result["contact_sheet"], encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn("Deterministic reasons", html)
            self.assertIn("AI reasons", html)
            self.assertIn("AI sees a strong visual hook.", html)

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
            session["clips"][0]["calibration"] = {"status": "matched"}
            session["clips"][1]["calibration"] = {"status": "false_positive"}
            session["clips"][1]["decision"] = "reject"
            self.assertEqual(
                [clip["id"] for clip in filter_review_clips(session["clips"], decision="reject")],
                ["clip_0002"],
            )
            self.assertEqual(
                [clip["id"] for clip in filter_review_clips(session["clips"], calibration="matched")],
                ["clip_0001"],
            )
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
                with open(os.path.join(module_root, "my_feature", "module.py"), encoding="utf-8") as handle:
                    module_py = handle.read()
                with open(os.path.join(module_root, "README.md"), encoding="utf-8") as handle:
                    readme = handle.read()
                self.assertIn("def diagnose", module_py)
                self.assertIn('"presets"', module_py)
                self.assertIn("schema_version", module_py)
                self.assertIn("Compatibility Rules", readme)
                self.assertIn("videoedit.modules", readme)
            finally:
                os.chdir(cwd)

    def test_external_module_operations_presets_and_diagnostics(self):
        def demo_operation(context, params):
            return {"output": params.get("output"), "status": "ok"}

        def demo_diagnostics():
            return {"module": "community.demo", "checks": [{"name": "demo", "available": True}]}

        module_payload = {
            "id": "community.demo",
            "description": "Demo community module",
            "category": "community",
            "operations": [
                {
                    "name": "demo_operation",
                    "description": "Demo operation",
                    "func": demo_operation,
                }
            ],
            "presets": {
                "demo_preset": {
                    "name": "demo_preset",
                    "description": "Demo preset",
                    "steps": [{"name": "demo", "operation": "demo_operation"}],
                }
            },
            "diagnostics": demo_diagnostics,
        }

        original_entry_points = modules_module.importlib.metadata.entry_points

        class FakeEntryPoint:
            name = "demo"

            def load(self):
                return lambda: module_payload

        def fake_entry_points(group=None):
            return [FakeEntryPoint()] if group == modules_module.ENTRY_POINT_GROUP else []

        modules_module.importlib.metadata.entry_points = fake_entry_points
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                registry = default_registry(cwd=tmp)
                operation = registry.get("demo_operation")
                self.assertEqual(operation.module, "community.demo")
                self.assertIn("demo_preset", available_presets())
                output = os.path.join(tmp, "demo.yaml")
                write_preset("demo_preset", output)
                data = load_pipeline(output)
                self.assertEqual(data["requires_modules"], ["community.demo"])
                report = modules_module.run_module_diagnostics(cwd=tmp)
                demo_checks = [group for group in report["checks"] if group["module"] == "community.demo"][0]
                self.assertTrue(demo_checks["checks"][0]["available"])

                disable_module("community.demo", cwd=tmp)
                self.assertNotIn("demo_preset", available_presets())
                self.assertNotIn("demo_operation", [item.name for item in default_registry(cwd=tmp).list()])
            finally:
                os.chdir(cwd)
                modules_module.importlib.metadata.entry_points = original_entry_points

    def test_invalid_external_modules_are_reported_without_breaking_builtins(self):
        payloads = [
            {
                "id": "core.bad",
                "description": "Reserved prefix",
                "operations": [],
            },
            {
                "id": "community.good",
                "description": "Good module",
                "operations": [],
            },
            {
                "id": "community.good",
                "description": "Duplicate module",
                "operations": [],
            },
            {
                "id": "community.bad_operation",
                "description": "Bad operation",
                "operations": [{"name": "bad operation", "func": lambda _context, _params: {}}],
            },
        ]
        original_entry_points = modules_module.importlib.metadata.entry_points

        class FakeEntryPoint:
            def __init__(self, name, payload):
                self.name = name
                self.payload = payload

            def load(self):
                return lambda: self.payload

        def fake_entry_points(group=None):
            if group != modules_module.ENTRY_POINT_GROUP:
                return []
            return [FakeEntryPoint(f"module_{index}", payload) for index, payload in enumerate(payloads)]

        modules_module.importlib.metadata.entry_points = fake_entry_points
        try:
            rows = module_rows()
            self.assertTrue(any(row["id"] == "core.rating" for row in rows))
            self.assertTrue(any(row["id"] == "community.good" for row in rows))
            errors = modules_module.discover_external_module_errors()
            serialized = json.dumps(errors)
            self.assertIn("reserved prefix", serialized)
            self.assertIn("duplicate module id", serialized)
            self.assertIn("invalid operation name", serialized)
        finally:
            modules_module.importlib.metadata.entry_points = original_entry_points

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


class CloudAdapterTests(unittest.TestCase):
    def test_cloud_adapter_metadata_diagnostics_and_job_schema(self):
        adapters = {adapter["id"]: adapter for adapter in list_cloud_adapters()}
        self.assertGreaterEqual(set(adapters), {"elevenlabs", "heygen", "descript"})
        diagnostics = cloud_diagnostics(env={})
        elevenlabs = [row for row in diagnostics["adapters"] if row["id"] == "elevenlabs"][0]
        self.assertFalse(elevenlabs["ready"])
        self.assertEqual(elevenlabs["checks"][0]["name"], "ELEVENLABS_API_KEY")

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "cloud_job.json")
            result = plan_cloud_job(
                "elevenlabs",
                output,
                job_type="voiceover",
                input_path=os.path.join(tmp, "script.txt"),
                params={"voice": "narrator"},
                project="Launch Reel",
            )
            self.assertEqual(result["status"], "planned")
            with open(output, encoding="utf-8") as handle:
                data = json.loads(handle.read())
            self.assertEqual(data["schema_version"], "videoedit.cloud_job.v1")
            self.assertEqual(data["adapter"]["id"], "elevenlabs")
            self.assertEqual(data["job"]["params"]["voice"], "narrator")
            self.assertFalse(data["execution"]["network_called"])
            self.assertFalse(data["execution"]["credentials_stored"])

    def test_cloud_cli_and_operation_respect_module_enablement(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                rows = module_rows(cwd=tmp)
                cloud = [row for row in rows if row["id"] == "cloud.adapters"][0]
                self.assertTrue(cloud["available"])
                self.assertFalse(cloud["enabled"])
                self.assertNotIn("plan_cloud_job", [item.name for item in default_registry(cwd=tmp).list()])

                adapters_out = io.StringIO()
                with redirect_stdout(adapters_out):
                    self.assertEqual(main(["cloud", "adapters"]), 0)
                self.assertIn("elevenlabs", adapters_out.getvalue())

                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "cloud",
                            "plan",
                            "elevenlabs",
                            "--job-type",
                            "voiceover",
                            "--output",
                            os.path.join(tmp, "blocked.json"),
                        ]
                    )
                self.assertEqual(exit_code, 1)
                self.assertIn("cloud.adapters is disabled", stderr.getvalue())

                enable_module("cloud.adapters", cwd=tmp)
                registry = default_registry(cwd=tmp)
                self.assertIn("plan_cloud_job", [item.name for item in registry.list()])
                with self.assertRaisesRegex(ValueError, "requires job_type"):
                    registry.get("plan_cloud_job").func({"output": tmp}, {"adapter": "elevenlabs"})
                op_output = os.path.join(tmp, "operation_cloud_job.json")
                result = registry.get("plan_cloud_job").func(
                    {"output": tmp},
                    {"adapter": "elevenlabs", "job_type": "voiceover", "output": op_output},
                )
                self.assertEqual(result["status"], "planned")
                self.assertTrue(os.path.exists(op_output))
                output = os.path.join(tmp, "cloud_job.json")
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(
                        main(
                            [
                                "cloud",
                                "plan",
                                "elevenlabs",
                                "--job-type",
                                "voiceover",
                                "--output",
                                output,
                                "--param",
                                "voice=narrator",
                            ]
                        ),
                        0,
                    )
                self.assertTrue(os.path.exists(output))
                self.assertEqual(_read_json(output)["job"]["params"]["voice"], "narrator")
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
