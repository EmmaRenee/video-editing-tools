# Install Guide

Canonical setup for the Video Editing Tools repository, the `videoedit` Python package, YOLO/advanced detectors, PowerShell helpers, and the portable editing skill.

## What Gets Installed

| Layer | Required | Purpose |
|-------|----------|---------|
| FFmpeg + ffprobe | Yes | Metadata, signal analysis, clip extraction, rough-cut assembly |
| Python 3.12 virtual environment | Yes for `videoedit` | Local package, CLI, YAML pipelines, review assets |
| `videoedit` package | Yes for automation | Inventory, rating, calibration, selections, EDL/XML/M3U, rough cuts |
| Whisper | Optional | Transcript signals and captions |
| Tesseract | Optional | OCR/signage detection |
| YOLO / Ultralytics | Optional | Visual object detection through `detect_visual_objects` |
| OpenCV | Optional | Face/person presence detection |
| OpenCLIP + Torch | Optional | AI profile frame scoring and missed-moment discovery |
| Local VLM judge command | Optional | Heavier review-clip judging through `videoedit ai judge` |
| Local learned scorer | Optional | Dependency-free scorer trained from reviewed decisions |
| Cloud adapter planner | Optional | Credential-safe ElevenLabs, HeyGen, and Descript-style handoff specs |
| PowerShell module | Optional | Windows-friendly FFmpeg helper cmdlets |
| DaVinci Resolve | Optional | Final polish after generated handoff files |

The deterministic pipeline works with only Python, FFmpeg, and ffprobe. The core `videoedit` package intentionally has no mandatory Python runtime dependencies beyond the standard library; install extras only when you need Whisper, YOLO/OpenCV, OpenCLIP/Torch, UI, or cloud providers.

`videoedit` 0.5.0 supports Python 3.10+; Python 3.12 is recommended for this repository's full local setup. Python 3.9 users should stay on the 0.4.x package line or upgrade Python before installing current `main`.

## macOS Setup

Install base tools:

```bash
brew install ffmpeg tesseract python@3.12
```

Create the repo-local virtual environment from the repository root:

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Install the core package:

```bash
python -m pip install -e ./src/python
```

Install the full local pipeline with Whisper, OpenCV, and YOLO/Ultralytics:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
```

Optional extras:

```bash
python -m pip install -e "./src/python[ai]"
python -m pip install -e "./src/python[ui]"
python -m pip install -e "./src/python[cloud]"
```

Activate this environment before running repository commands:

```bash
source .venv/bin/activate
```

Package and release verification commands are documented in [docs/release.md](docs/release.md). Build artifacts such as `dist/`, `build/`, wheels, source distributions, generated media, analysis folders, and model weights should stay out of git.

## Windows Setup

Install system tools:

```powershell
winget install Gyan.FFmpeg
winget install Python.Python.3.12
winget install UB-Mannheim.TesseractOCR
```

Create and activate the virtual environment from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .\src\python
python -m pip install -e ".\src\python[whisper,advanced]"
python -m pip install -e ".\src\python[ai]"
```

If PowerShell blocks activation scripts:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Install the optional PowerShell helper module:

```powershell
$modulePath = "$HOME\Documents\PowerShell\Modules\VideoEditing"
New-Item -ItemType Directory -Path $modulePath -Force
Copy-Item src\powershell\VideoEditing.psm1 $modulePath\VideoEditing.psm1 -Force
Import-Module VideoEditing
```

## Linux Setup

Install base tools:

```bash
sudo apt update
sudo apt install ffmpeg tesseract-ocr python3.12 python3.12-venv python3-pip
```

Create and activate the virtual environment from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ./src/python
python -m pip install -e "./src/python[whisper,advanced]"
python -m pip install -e "./src/python[ai]"
```

If Python 3.12 is not available from your distribution packages, install Python 3.12 with `pyenv`, your distribution backports, or the official Python installer before creating `.venv`.

## Verify Installation

From the repository root with the virtual environment active:

```bash
python --version
python -m pip show videoedit ultralytics opencv-python openai-whisper open-clip-torch torch Pillow
command -v videoedit
command -v yolo
videoedit doctor
videoedit operations
videoedit modules list
videoedit modules doctor
yolo checks
```

Expected `videoedit doctor` result:

- Required `ffmpeg` and `ffprobe` are `ok`.
- Optional `whisper`, `tesseract`, `yolo`, and `cv2` are `ok` when full extras are installed.
- Optional `open_clip`, `torch`, and `PIL` are reported by `videoedit modules doctor` for the `advanced.ai` module when AI extras are installed.

Optional YOLO smoke test outside the repository:

```bash
mkdir -p /tmp/videoedit-yolo-smoke
cd /tmp/videoedit-yolo-smoke
yolo predict model=yolo26n.pt source=https://ultralytics.com/images/bus.jpg project=/tmp/videoedit-yolo-smoke name=predict exist_ok=True
```

The first YOLO run downloads model weights. Keep YOLO `runs/` output outside the repo or rely on `.gitignore`.

## Use The Pipeline

Inventory and rate footage:

```bash
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
```

Optional AI frame scoring and missed-moment review:

```bash
videoedit ai profiles list
videoedit ai profiles show garage_shop
videoedit ai score-frames footage/ --profile garage_shop --output analysis/ai_frame_scores.json
videoedit rate footage/ --output analysis_ai/ --ai-frame-scores analysis/ai_frame_scores.json
videoedit ai find-missed analysis/ratings.json --ai-frame-scores analysis/ai_frame_scores.json --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
```

AI frame scoring is optional, local-first, and does not require a paid subscription. Missing OpenCLIP/Torch dependencies write an unavailable artifact with install guidance; core inventory, rating, review, and rough-cut commands still work.

AI-assisted presets declare their optional modules and local dependencies. Use `validate` and `run --dry-run` before long footage runs:

```bash
videoedit init ai_reel --output ai_reel.yaml
videoedit validate ai_reel.yaml
videoedit run ai_reel.yaml --input footage/ --output output/ --dry-run

videoedit init ai_garage_shop --output ai_garage_shop.yaml
videoedit validate ai_garage_shop.yaml
videoedit run ai_garage_shop.yaml --input footage/ --output output/ --dry-run

videoedit init ai_event_recap --output ai_event_recap.yaml
videoedit validate ai_event_recap.yaml
videoedit run ai_event_recap.yaml --input footage/ --output output/ --dry-run
```

`ai_reel` uses the `social_reel` profile. `ai_garage_shop` targets generic shop work, tools, vehicle details, and build-process B-roll. `ai_event_recap` targets event or motorsports recap material and creates review-only missed-moment artifacts.

Optional AI clip judging runs after `review-assets` and requires a configured local provider command. The provider command must read request JSON on stdin and write judgment JSON on stdout.

```bash
export VIDEOEDIT_AI_JUDGE_COMMAND="/path/to/local-vlm-judge"
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json
videoedit review-assets analysis/ratings.json --output review_ai/ --ai-clip-judgments analysis/ai_clip_judgments.json
```

If no provider is configured, `videoedit ai judge` writes an unavailable `ai_clip_judgments.json` artifact with setup guidance and returns a non-zero CLI status.

Optional local scorer trained from reviewed decisions:

```bash
videoedit ai dataset build --inputs analysis/*/review_decisions.json --output training/review_dataset.jsonl
videoedit ai train-scorer training/review_dataset.jsonl --output models/local_scorer.json
videoedit rate footage/ --output analysis_learned/ --learned-scorer models/local_scorer.json
```

The JSONL dataset is portable and does not copy source videos by default. `local_scorer.json` is small and inspectable, and learned scoring only affects rating when a scorer path is supplied via `--learned-scorer` or `AnalysisConfig.learned_scorer_path`.

Calibrate scoring after marking human-approved moments:

```bash
videoedit calibrate init --output annotations.json
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
videoedit calibrate apply calibration/proposed_config.json --output configs/scoring.json
videoedit rate footage/ --output analysis_tuned/ --config calibration/proposed_config.json
```

Calibration writes precision/recall reports, missed moments, false positives, ranked config candidates, and a proposed config. It never overwrites `.videoedit/config.json` or package defaults.

Review and approve candidates:

```bash
videoedit review-assets analysis/ratings.json --output review/ --calibration calibration/calibration_report.json
videoedit review-tui review/review_assets.json --decisions review/review_decisions.json
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
```

Assemble and export handoff files:

```bash
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence diversified --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl approved.json --output edl/
```

Preset pipelines:

```bash
videoedit init roughcut --output roughcut.yaml
videoedit init vision_reel --output vision_reel.yaml
videoedit validate roughcut.yaml
videoedit plan roughcut.yaml --input footage/ --output output/
videoedit run roughcut.yaml --input footage/ --output output/ --dry-run
videoedit run roughcut.yaml --input footage/ --output output/
```

YOLO is used by the `detect_visual_objects` operation when the `yolo` command is available. The operation writes `visual_objects.json` with parsed YOLO labels, bounded timestamped detections, class counts, and object-presence segments. `videoedit rate` can fuse that file with optional OCR, face/person, motorsports event, and transcript-topic artifacts.

Example one-step vision pipeline:

```yaml
name: vision
requires_modules:
  - advanced.vision
steps:
  - name: objects
    operation: detect_visual_objects
    params:
      input: footage/
      output: analysis/visual_objects.json
      model: yolo26n.pt
      max_detections: 5000
```

Use those parsed object signals during rating:

```bash
videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals ocr footage/ --output analysis/ocr_signage.json
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit signals motorsports analysis/ratings.json --output analysis/motorsports_events.json
videoedit signals topics analysis/ratings.json --output analysis/topic_clusters.json
videoedit signals validate analysis/visual_objects.json

videoedit run vision_reel.yaml --input footage/ --output analysis/vision
videoedit rate footage/ --output analysis_fused/ \
  --visual-objects analysis/visual_objects.json \
  --ocr-signage analysis/ocr_signage.json \
  --face-person analysis/face_person_presence.json \
  --motorsports-events analysis/motorsports_events.json \
  --topic-clusters analysis/topic_clusters.json \
  --ai-frame-scores analysis/ai_frame_scores.json
```

## Optional Feature Modules

`videoedit` is modular. Core inventory, rating, pipeline, review, and handoff modules are always enabled. Optional modules can be enabled or disabled per project in `.videoedit/config.json`:

```bash
videoedit modules list
videoedit modules enable content.series
videoedit modules disable advanced.vision
videoedit modules doctor
videoedit modules scaffold my_feature --output videoedit-my-feature/
```

Optional built-in modules include styled captions, content series planning, editorial reports, project scaffolding, advanced vision, AI frame scoring, motorsports events, and credential-safe cloud adapter planning. Community packages can register modules through the `videoedit.modules` Python entry point group; see `docs/community-modules.md` for module ID, diagnostics, preset, artifact, and test rules.

## Content, Captions, And Projects

```bash
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
videoedit captions styles
videoedit burn-captions video.mp4 subs.srt --output out.mp4 --style automotive_racing --format reel
videoedit init-project "May Shop Reel" --type reel --output projects/
```

`videoedit export-edl`, `videoedit extract-segments`, and `videoedit assemble` accept normal `approved.json` files, per-source selections, and Drive-style soundbite JSON with top-level `project`/`fps` plus per-clip `source`, `start`, `end`, and `label`.

## Install The Skill

Claude-style local skill:

```bash
mkdir -p ~/.claude/skills/video-editing
cp src/SKILL.md ~/.claude/skills/video-editing/SKILL.md
```

Codex-style local skill:

```bash
mkdir -p ~/.codex/skills/video-editing
cp src/SKILL.md ~/.codex/skills/video-editing/SKILL.md
```

Windows PowerShell equivalents:

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\.claude\skills\video-editing" -Force
Copy-Item src\SKILL.md "$env:USERPROFILE\.claude\skills\video-editing\SKILL.md" -Force

New-Item -ItemType Directory -Path "$env:USERPROFILE\.codex\skills\video-editing" -Force
Copy-Item src\SKILL.md "$env:USERPROFILE\.codex\skills\video-editing\SKILL.md" -Force
```

After installing the skill, start a fresh agent/chat session so the skill registry can reload.

## DaVinci Resolve Handoff

Use `videoedit export-edl` to generate DaVinci-friendly artifacts:

```bash
videoedit export-edl analysis/selections/*.json --output edl/
videoedit export-edl approved.json --output edl/
```

Generated handoff files include EDL, XML, M3U, and FFmpeg extraction scripts. Use DaVinci Resolve for color, sound mix, fine timing, and final delivery.

## Optional Cloud/API Tools

Cloud integrations are not required for local scanning or rough cuts. The built-in cloud planner uses only package code, but install the cloud extra before adding maintained execution adapters:

```bash
python -m pip install -e "./src/python[cloud]"
```

List adapters and check readiness without calling external APIs:

```bash
videoedit cloud adapters
videoedit cloud doctor
videoedit cloud doctor --json
```

Enable cloud handoff planning per project and write a reviewable job spec:

```bash
videoedit modules enable cloud.adapters
videoedit cloud plan elevenlabs \
  --job-type voiceover \
  --input scripts/narration.txt \
  --output cloud_jobs/voiceover.json \
  --project "Launch Reel" \
  --param voice=narrator
```

`videoedit cloud plan` writes `cloud_job.json`; it does not call provider APIs and does not store credentials. The artifact records `network_called: false` and `credentials_stored: false`. Keep credentials in your shell environment or a local `.env` outside version control for external runners:

```bash
ELEVENLABS_API_KEY=your_key_here
HEYGEN_API_KEY=your_key_here
```

Descript-style handoffs currently expect a maintained desktop or MCP connector workflow rather than a stored API key.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `videoedit: command not found` | Activate `.venv`, then reinstall with `python -m pip install -e ./src/python` |
| `yolo: command not found` | Activate `.venv`, then install `python -m pip install -e "./src/python[advanced]"` |
| `ffmpeg` or `ffprobe` missing | Install FFmpeg and confirm both commands are on `PATH` |
| `cv2` missing in `videoedit doctor` | Install the advanced extra in the active `.venv` |
| YOLO writes files into the repo | Use `project=/tmp/...` for smoke tests; `runs/` is ignored |
| Whisper model download is slow | Use a smaller model first, such as `tiny` or `base` |
| Windows script activation fails | Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |

## Licensing Note

This repository is MIT licensed. Ultralytics is a separate dependency distributed under AGPL-3.0 with commercial licensing options from Ultralytics. Review the Ultralytics license before using YOLO in commercial or closed-source workflows.
