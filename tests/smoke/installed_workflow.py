"""Exercise an installed core wheel using generated media, never private footage."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import time
import xml.etree.ElementTree as ET


def run_workflow(output: Path, checkout: Path) -> dict:
    import videoedit

    package = Path(videoedit.__file__).resolve()
    expected = Path(sysconfig.get_path("purelib")) / "videoedit" / "__init__.py"
    if sys.prefix == sys.base_prefix or package != expected.resolve():
        raise ValueError("core_wheel_install_required")
    if checkout.resolve() / "src" / "python" in package.parents:
        raise ValueError("source_checkout_imported")
    distribution = importlib.metadata.distribution("videoedit")
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    if direct_url.get("dir_info", {}).get("editable"):
        raise ValueError("editable_install_not_allowed")
    if distribution.version != videoedit.__version__:
        raise ValueError("installed_version_mismatch")
    optional = ("cv2", "ultralytics", "torch", "open_clip", "whisper", "textual", "elevenlabs")
    if any(importlib.util.find_spec(name) is not None for name in optional):
        raise ValueError("core_only_environment_required")
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        raise ValueError("ffmpeg_and_ffprobe_required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("empty_output_directory_required")
    output.mkdir(parents=True, exist_ok=True)
    logs = output / "logs"
    logs.mkdir()
    report = {"schema_version": "videoedit.installed_smoke.v1", "status": "running", "complete": False,
              "python": platform.python_version(), "package_version": distribution.version,
              "import_origin": "venv_site_packages", "synthetic_only": True,
              "editor_verified": False, "steps": []}
    started = time.monotonic()
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    executable = Path(sysconfig.get_path("scripts")) / ("videoedit.exe" if os.name == "nt" else "videoedit")

    def run(name: str, args: list[str], expected: int = 0) -> str:
        before = time.monotonic()
        step = {"name": name, "status": "running", "expected_returncode": expected}
        report["steps"].append(step)
        try:
            result = subprocess.run([str(arg) for arg in args], cwd=output, env=env,
                                    capture_output=True, text=True, timeout=180)
            (logs / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            (logs / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
            step.update(status="ok" if result.returncode == expected else "error", returncode=result.returncode)
            if result.returncode != expected:
                raise ValueError(f"command_failed:{name}")
            return result.stdout
        except BaseException:
            step["status"] = "error"
            raise
        finally:
            step["duration_seconds"] = round(time.monotonic() - before, 6)

    def cli(name: str, *args: str, expected: int = 0) -> str:
        return run(name, [str(executable), *args], expected=expected)

    def read(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        report["ffmpeg"] = run("ffmpeg_version", ["ffmpeg", "-version"]).splitlines()[0]
        report["ffprobe"] = run("ffprobe_version", ["ffprobe", "-version"]).splitlines()[0]
        doctor = json.loads(cli("doctor", "doctor", "--json"))
        assert doctor["status"] == "ok" and doctor["missing_required"] == [], "doctor_required_tools"
        assert "cv2" in doctor["missing_optional"], "doctor_missing_optional"
        assert "rate_footage" in cli("operations", "operations"), "operations_unavailable"
        assert "core.review" in cli("modules", "modules", "list"), "modules_unavailable"

        footage = output / "footage"
        footage.mkdir()
        source = footage / "synthetic.mov"
        run("create_media", ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                             "testsrc2=size=160x90:rate=30:duration=4", "-f", "lavfi", "-i",
                             "sine=frequency=440:sample_rate=48000:duration=4", "-c:v", "mpeg4",
                             "-q:v", "3", "-c:a", "pcm_s16le", "-ac", "2", "-timecode", "01:00:00:00",
                             str(source)])
        analysis = output / "analysis"
        cli("inventory", "inventory", str(footage), "--output", str(output / "inventory"))
        cli("rate", "rate", str(footage), "--output", str(analysis), "--transcript", "off",
            "--max-candidates", "5", "--manifest-paths", "redacted")
        ratings = read(analysis / "ratings.json")
        assert ratings["summary"]["files"] == 1 and ratings["candidates"], "rating_empty"
        assert ratings["summary"]["analysis_failed"] == 0, "rating_detector_failed"
        assert all(row["analysis_complete"] and not row["warnings"] for row in ratings["signals"]), "signal_analysis_incomplete"
        assert ratings["signals"][0]["audio_levels"], "audio_analysis_empty"
        assert read(analysis / "rating_run.json")["status"] == "ok", "rating_incomplete"
        cli("rate_warm", "rate", str(footage), "--output", str(analysis), "--transcript", "off",
            "--max-candidates", "5", "--manifest-paths", "redacted")
        assert read(analysis / "rating_run.json")["telemetry"]["cache_hits"] == 1, "warm_cache_not_reused"

        review = output / "review"
        cli("review", "review-assets", str(analysis / "ratings.json"), "--output", str(review),
            "--proxy", "--max-items", "5", "--manifest-paths", "redacted")
        assert (review / "contact_sheet.html").is_file(), "contact_sheet_missing"
        assets = read(review / "review_assets.json")
        assert assets["clips"], "review_empty"
        decisions = review / "review_decisions.json"
        decisions.write_text(json.dumps({"decisions": [
            {"id": row["id"], "decision": "approve" if index == 0 else "reject", "order": index + 1,
             "note": "Synthetic functional check; not editorial ground truth"}
            for index, row in enumerate(ratings["candidates"])]}), encoding="utf-8")
        approved = output / "approved.json"
        cli("approve", "approve", str(analysis / "ratings.json"), "--decisions", str(decisions), "--output", str(approved))
        assert len(read(approved)["clips"]) == 1, "approval_decisions_not_applied"

        plan = output / "roughcut_plan.json"
        cli("roughcut_plan", "roughcut", "plan", str(approved), "--output", str(plan), "--handles", "0.125",
            "--target-duration", "1", "--render-mode", "render", "--manifest-paths", "redacted")
        planned = read(plan)
        assert planned["status"] == "ok" and planned["summary"]["duration"] == 1, "plan_incomplete"
        cut = output / "rough_cut.mp4"
        cli("assemble", "assemble", str(approved), "--plan", str(plan), "--output", str(cut), "--manifest-paths", "redacted")
        streams = json.loads(run("probe_render", ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(cut)]))["streams"]
        video = next(row for row in streams if row["codec_type"] == "video")
        audio = next(row for row in streams if row["codec_type"] == "audio")
        assert int(video["nb_frames"]) == 30 and abs(float(video["duration"]) - 1) < 1e-6, "render_frame_count"
        assert audio["channels"] == 2, "render_stereo_stream_missing"
        assert read(output / "rough_cut_assembly.json")["status"] == "ok", "assembly_incomplete"

        handoff = output / "handoff"
        cli("export", "export-edl", str(plan), "--output", str(handoff), "--manifest-paths", "redacted")
        mapping = read(handoff / "roughcut_plan_handoff.json")
        assert mapping["status"] == "ok" and not mapping["handoff"]["editor_verified"], "handoff_manifest"
        xml = ET.parse(handoff / "roughcut_plan.xml").getroot()
        assert xml.findtext("sequence/duration") == "30", "xml_duration"
        assert len(xml.findall("sequence/media/audio/track")) == 2, "xml_audio_tracks"
        assert xml.findtext("sequence/media/video/track/clipitem/file/timecode/string") == "01:00:00:00", "xml_source_timecode"

        pipeline = output / "roughcut.yaml"
        cli("preset", "init", "roughcut", "--output", str(pipeline))
        cli("validate", "validate", str(pipeline))
        cli("dry_run", "run", str(pipeline), "--input", str(footage), "--output", str(output / "dry_run"), "--dry-run")
        absent = output / "face_unavailable.json"
        cli("optional_absent", "signals", "face-person", str(footage), "--output", str(absent), expected=1)
        assert read(absent)["status"] == "unavailable", "missing_provider_not_diagnosed"
        report.update(status="ok", complete=True, video_frames=30, video_duration_seconds=1.0,
                      audio_channels=2, rating_candidates=len(ratings["candidates"]), optional_absent="verified")
    except BaseException as error:
        report.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 6)
        report["storage_scope"] = "synthetic_workspace_before_report"
        report["storage_bytes"] = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
        (output / "smoke_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run_workflow(args.output.resolve(), args.checkout.resolve()), indent=2))
    except (Exception, KeyboardInterrupt) as error:
        print(f"installed workflow failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
