# Python Tools

Cross-platform Python scripts for video editing workflows.

---

## Footage Rating and Pipeline System

Local-first video editing analysis package. V1 inventories footage, scores it, and writes explainable clip candidates. The `videoedit` package builds on that scanner with CLI commands, typed artifacts, reusable operations, YAML presets, DaVinci/FFmpeg handoff files, and rough-cut assembly.

### Quick Start

```bash
# Install the pipeline package from the repository root
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "./src/python[whisper,advanced]"
# Optional OpenCLIP frame scoring
python -m pip install -e "./src/python[ai]"

# V1-compatible scanner/rater
python src/python/rate_footage.py footage/ --output analysis/

# Package CLI
videoedit doctor
videoedit modules list
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
videoedit ai profiles list
videoedit ai score-frames footage/ --profile garage_shop --output analysis/ai_frame_scores.json
videoedit rate footage/ --output analysis_ai/ --ai-frame-scores analysis/ai_frame_scores.json
videoedit ai find-missed analysis/ratings.json --ai-frame-scores analysis/ai_frame_scores.json --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json
videoedit review-assets analysis/ratings.json --output review_ai/ --ai-clip-judgments analysis/ai_clip_judgments.json
videoedit ai dataset build --inputs analysis/*/review_decisions.json --output training/review_dataset.jsonl
videoedit ai train-scorer training/review_dataset.jsonl --output models/local_scorer.json
videoedit rate footage/ --output analysis_learned/ --learned-scorer models/local_scorer.json
videoedit calibrate init --output annotations.json
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
videoedit calibrate apply calibration/proposed_config.json --output configs/scoring.json

# Pipeline preset
videoedit init reel --output reel.yaml
videoedit validate reel.yaml
videoedit run reel.yaml --input footage/ --output output/

# One-pass rough cut pipeline
videoedit init roughcut --output roughcut.yaml
videoedit run roughcut.yaml --input footage/ --output output/

# Handoff and rough cut
videoedit review-assets analysis/ratings.json --output review/ --calibration calibration/calibration_report.json
videoedit review-tui review/review_assets.json --decisions review/review_decisions.json
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence diversified --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl analysis/selections/*.json --output edl/

# Editorial/content helpers
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series analysis/ratings.json --template team_tuesday --output series/
videoedit init-project "May Shop Reel" --type reel --output projects/
videoedit burn-captions video.mp4 subs.srt --output out.mp4 --style automotive_racing --format reel
```

### Python API

```python
from videoedit import AnalysisConfig, run_rating

config = AnalysisConfig(max_candidates=40, transcript_mode="auto")
report = run_rating("footage/", "analysis/", config=config)

for clip in report.candidates[:10]:
    print(clip.id, clip.score, clip.action, clip.reasons)
```

### Rating Outputs

`videoedit rate` and `python rate_footage.py` write:

- `inventory.json`, `inventory.csv`, `inventory.md`
- `ratings.json`
- `candidates.csv`
- `review.md`
- `review.html`
- `selections/*.json`

Scoring is deterministic and explainable. It combines technical metadata, scene-change density, silence/non-silence ratio, audio spike windows, and optional transcript keyword hits. Each candidate carries labels, signal scores, and human-readable reasons.

### Optional AI Frame Scoring

AI frame scoring is an explicit optional layer. It uses project-agnostic profiles to score sampled frames against prompt sets, writes a JSON artifact, and lets `videoedit rate` fuse that artifact only when supplied.

```bash
videoedit ai profiles list
videoedit ai profiles show garage_shop
videoedit ai score-frames footage/ --profile garage_shop --output analysis/ai_frame_scores.json

videoedit rate footage/ --output analysis_ai/ \
  --ai-frame-scores analysis/ai_frame_scores.json
```

Built-in profiles are `general_broll`, `garage_shop`, `motorsports`, `interview`, `event_recap`, `social_reel`, and `documentary`. The frame-score artifact includes schema version, provider metadata, source paths, frame times, prompt scores, labels, and explanations. Missing OpenCLIP/Torch dependencies produce install guidance instead of breaking core rating.

AI frame scores can also scan rejected or low-ranked footage for likely missed usable moments:

```bash
videoedit ai find-missed analysis/ratings.json \
  --ai-frame-scores analysis/ai_frame_scores.json \
  --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
videoedit calibrate from-decisions review_missed/missed_review_decisions.json \
  --ratings analysis/ratings.json \
  --output annotations_from_missed.json
```

Missed moments are review-only. They are not auto-approved and are not inserted into rough cuts unless a human promotes them through the review/calibration loop.

Optional clip judging can add heavier local VLM-style feedback to shortlisted review clips:

```bash
export VIDEOEDIT_AI_JUDGE_COMMAND="/path/to/local-vlm-judge"
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json
videoedit review-assets analysis/ratings.json --output review_ai/ \
  --ai-clip-judgments analysis/ai_clip_judgments.json
videoedit rate footage/ --output analysis_with_ai_explanations/ \
  --ai-clip-judgments analysis/ai_clip_judgments.json
```

The provider command reads request JSON on stdin and writes a judgment JSON object with `score_dimensions`, `suggested_action`, `labels`, and `reason`. These AI reasons are carried in `ai_explanations` and displayed separately from deterministic score explanations.

Optional learned scoring uses reviewed decisions across projects:

```bash
videoedit ai dataset build \
  --inputs analysis/*/review_decisions.json \
  --output training/review_dataset.jsonl
videoedit ai train-scorer training/review_dataset.jsonl \
  --output models/local_scorer.json
videoedit rate footage/ --output analysis_learned/ \
  --learned-scorer models/local_scorer.json
videoedit calibrate evaluate analysis_learned/ratings.json \
  --annotations annotations.json \
  --output calibration/learned/
videoedit calibrate compare calibration/baseline calibration/learned --output calibration/compare/
```

`review_dataset.jsonl` stores portable feature records and reviewed labels without copying source video. `local_scorer.json` is a CPU-friendly linear feature model with version, weights, feature statistics, and training metrics. Learned scoring is opt-in.

### Calibration and Scoring Evaluation

Calibration measures whether `videoedit rate` found the moments a human editor marked as valuable, then proposes scoring configs without changing defaults.

```bash
videoedit rate footage/ --output analysis/
videoedit calibrate init --output annotations.json
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
videoedit calibrate apply calibration/proposed_config.json --output configs/scoring.json
videoedit rate footage/ --output analysis_tuned/ --config calibration/proposed_config.json
```

Annotation JSON is the canonical ground-truth format:

```json
{
  "project": "Drive Auto Sports Calibration",
  "source_root": "footage/",
  "clips": [
    {
      "source": "race_day/interview.mp4",
      "start": "00:00:30",
      "end": "00:00:45",
      "rating": "select",
      "tags": ["quote", "team_tuesday"],
      "notes": "Strong intro soundbite"
    }
  ]
}
```

Supported annotation ratings are `select`, `review`, `broll`, `reject`, `cut`, and `ignore`. Positive ratings are matched to candidates by source plus time overlap; `ignore` clips are excluded from false-positive counts.

Calibration writes `calibration_report.json`, `calibration_report.md`, `missed_moments.csv`, and `false_positives.csv`. `tune` also writes `config_candidates.csv` and `proposed_config.json`, ranked by F1, recall, precision, then fewer candidates.

### Modular Feature Modules

`videoedit` has built-in feature modules so optional functionality can be enabled, disabled, and extended without changing the core rating pipeline.

```bash
videoedit modules list
videoedit modules enable content.series
videoedit modules disable advanced.vision
videoedit modules doctor
videoedit modules scaffold my_feature --output videoedit-my-feature/
```

Core modules are always enabled. Optional modules are project-local and are stored in `.videoedit/config.json` when you enable or disable them. Pipeline YAML may declare `requires_modules`; validation fails before processing if a required module is disabled or unavailable.

Community packages can expose modules through the `videoedit.modules` Python entry point group. External modules may contribute operations, presets, diagnostics, and content templates.

Community module conventions:

- Use a stable dotted module ID such as `community.shop_reports` or `advanced.my_detector`.
- Keep optional dependencies optional; diagnostics should report unavailable providers instead of breaking package import.
- Operations should read/write JSON-first artifacts and return a small result dictionary.
- Presets should declare `requires_modules` when they depend on optional modules.
- Include unit tests for module metadata, operation registration, and generated artifacts.

### Review and Approval

```bash
# Generate thumbnails plus a browsable contact sheet
videoedit review-assets analysis/ratings.json --output review/

# Include low-resolution proxy clips
videoedit review-assets analysis/ratings.json --output review/ --proxy

# Use review/contact_sheet.html or edit review/review_decisions.json to
# promote/demote/reject/reorder clips, then create the assembly-ready file
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json

# Approve by score/action
videoedit approve analysis/ratings.json --output approved.json --actions select,review --min-score 70

# Manually approve specific IDs from candidates.csv/review.html
videoedit approve analysis/ratings.json --output approved.json --ids clip_0001,clip_0004

# Plan and assemble the approved JSON into a rough cut
videoedit roughcut plan approved.json --output roughcut_plan.json --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
```

### Available Operations

| Operation | Description |
|-----------|-------------|
| `inventory` | Scan footage and write inventory artifacts |
| `analyze_signals` | Analyze footage signals and write rating artifacts |
| `rate_footage` | Inventory, score, and rank candidate clips |
| `transcribe_whisper` | Transcribe video with Whisper AI |
| `detect_highlights_audio` | Filter rating candidates with audio labels |
| `detect_highlights_transcript` | Filter rating candidates with transcript labels |
| `evaluate_ratings` | Evaluate candidates against human annotation JSON |
| `calibrate_scoring` | Generate ranked scoring config candidates |
| `extract_segments` | Extract clips from selection JSON files |
| `generate_edl` | Create EDL/XML/M3U and FFmpeg extraction scripts |
| `generate_review_assets` | Generate thumbnails and an HTML contact sheet |
| `approve_candidates` | Create approved.json from rating candidates |
| `plan_roughcut` | Plan clip order, target duration, handles, format, and render settings |
| `assemble_rough_cut` | Assemble a rough cut from approved selections |
| `format_video` | Apply an FFmpeg video filter |
| `burn_captions` | Burn subtitles into video |
| `normalize_audio` | Normalize audio to target loudness |
| `concatenate_videos` | Combine multiple video clips |
| `detect_ocr_signage` | Optional OCR/signage detection from sampled frames |
| `detect_visual_objects` | Optional external object detector handoff |
| `score_ai_frames` | Optional OpenCLIP frame scoring against AI profiles |
| `detect_face_person_presence` | Optional face/person presence detection from sampled frames |
| `detect_motorsports_events` | Infer passes, incidents, starts, finishes, and pace moments |
| `cluster_transcript_topics` | Group transcript hits into editing topics |
| `find_ai_missed_moments` | Find likely missed moments from AI frame scores |
| `generate_missed_review` | Generate review HTML and decisions for missed moments |
| `judge_ai_clips` | Judge review clips with an optional local VLM provider |
| `build_review_dataset` | Build portable JSONL records from reviewed decisions |
| `train_review_scorer` | Train a small inspectable local scorer |
| `plan_content_series` | Generate content-series plan, captions, and selection JSON |
| `generate_content_map` | Generate ranked editorial content-map artifacts |
| `quote_mining` | Generate transcript-forward quote-mining report |
| `scaffold_project` | Create a project folder scaffold and `.videoedit/config.json` |

### CLI Commands

```bash
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit roughcut plan approved.json --output roughcut_plan.json --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl analysis/selections/*.json --output edl/
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json
videoedit review-assets analysis/ratings.json --output review_ai/ --ai-clip-judgments analysis/ai_clip_judgments.json
videoedit ai dataset build --inputs analysis/*/review_decisions.json --output training/review_dataset.jsonl
videoedit ai train-scorer training/review_dataset.jsonl --output models/local_scorer.json

videoedit init reel --output pipeline.yaml
videoedit validate pipeline.yaml
videoedit plan pipeline.yaml --input footage/ --output output/
videoedit run pipeline.yaml --input footage/ --output output/ --dry-run
videoedit run pipeline.yaml --input footage/ --output output/

videoedit operations
videoedit modules list
videoedit modules doctor
videoedit doctor
videoedit doctor --json

videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals ocr footage/ --output analysis/ocr_signage.json
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit signals motorsports analysis/ratings.json --output analysis/motorsports_events.json
videoedit signals topics analysis/ratings.json --output analysis/topic_clusters.json
videoedit signals validate analysis/visual_objects.json

videoedit ai profiles list
videoedit ai profiles show motorsports
videoedit ai score-frames footage/ --profile motorsports --output analysis/ai_frame_scores.json
videoedit ai find-missed analysis/ratings.json --ai-frame-scores analysis/ai_frame_scores.json --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/

videoedit captions styles
videoedit burn-captions video.mp4 subs.srt --output out.mp4 --style automotive_racing --format reel
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit init-project "May Shop Reel" --type reel --output projects/
```

### Presets

Built-in presets for common workflows:

- **reel**: Instagram Reel from raw footage
- **roughcut**: Rating, review assets, approval defaults, EDL export, rough cut
- **youtube**: YouTube highlights (16:9)
- **documentary**: Documentary rough cut with transcript analysis
- **motorsports**: Racing-footage event/topic artifacts plus review outputs
- **simple**: Basic audio highlight detection

### Pipeline YAML Format

```yaml
name: reel
description: Rate footage and identify high-energy reel candidates

steps:
  - name: rate
    operation: rate_footage
    params:
      transcript_mode: auto
      max_candidates: 40
      window_pre_roll: 3
      window_post_roll: 9

  - name: edl
    operation: generate_edl
    params: {}
```

Pipeline steps can reference previous artifacts by step name, for example `rate.ratings`, `review.decisions`, and `${output}/approved.json`.

`videoedit validate` checks operation names, duplicate step names, and known step-result references before a run starts. `videoedit plan` and `videoedit run --dry-run` print the resolved execution plan without processing footage. `videoedit run` writes `pipeline_run.json` to the output directory with step results, durations, and final status.

Pipelines can require modules:

```yaml
requires_modules:
  - content.series
  - delivery.captions
```

If a required module is disabled in `.videoedit/config.json`, validation stops with a targeted error.

### Selection And Soundbite JSON

`videoedit export-edl`, `videoedit extract-segments`, and `videoedit assemble` share one selection loader. Existing per-source selection files and `approved.json` remain supported. Drive-style soundbite JSON is also accepted:

```json
{
  "project": "Vin Wiki Soundbites",
  "fps": 30,
  "clips": [
    {
      "source": "interview.mp4",
      "start": "00:00:30",
      "end": "00:01:00",
      "label": "matt_intro"
    }
  ]
}
```

When no top-level `source` is present, each clip must include `source`. FPS precedence is explicit `--fps`, then JSON `fps`, then `30`.

### Content Planning

```bash
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
```

Content reports group candidates into editorial pillars such as expert quotes, educational teardown, build diary, motion bank, branded assets, and motorsports moments. Series planning writes `series_plan.json`, `caption_suggestions.md`, and `series_selections.json`.

### Advanced Signals

Advanced detectors are optional providers layered on top of the deterministic rating artifacts:

- `detect_motorsports_events` reads `ratings.json` and writes `motorsports_events.json`.
- `cluster_transcript_topics` reads transcript hits from `ratings.json` and writes `topic_clusters.json`.
- `detect_ocr_signage` writes `ocr_signage.json`; it runs only when FFmpeg and Tesseract are installed.
- `detect_visual_objects` writes `visual_objects.json`; it runs only when an object detector command such as `yolo` is available. YOLO labels are parsed into bounded `detections`, `class_counts`, and time-based `segments`.
- `detect_face_person_presence` writes `face_person_presence.json`; it runs only when FFmpeg and OpenCV are installed.
- `score_ai_frames` writes `ai_frame_scores.json`; it runs only when OpenCLIP, Torch, Pillow, and FFmpeg are installed.

These operations produce JSON artifacts and report `status: unavailable` when optional tools are missing, so normal inventory/rating/rough-cut automation does not depend on heavy AI packages.

The direct signal CLI writes schema-versioned artifacts with provider metadata, source summaries, and validation diagnostics:

```bash
videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals ocr footage/ --output analysis/ocr_signage.json
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit signals motorsports analysis/ratings.json --output analysis/motorsports_events.json
videoedit signals topics analysis/ratings.json --output analysis/topic_clusters.json
videoedit signals validate analysis/visual_objects.json
```

Use parsed signal artifacts as explicit rating inputs when people, vehicles, signage, racing events, or topics should affect B-roll selection. The `vision_reel` preset runs object/OCR/face providers first, then rates with the generated artifacts:

```yaml
name: vision_reel
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

```bash
videoedit init vision_reel --output vision_reel.yaml
videoedit run vision_reel.yaml --input footage/ --output output/
videoedit rate footage/ --output analysis_fused/ \
  --visual-objects analysis/visual_objects.json \
  --ocr-signage analysis/ocr_signage.json \
  --face-person analysis/face_person_presence.json \
  --motorsports-events analysis/motorsports_events.json \
  --topic-clusters analysis/topic_clusters.json \
  --ai-frame-scores analysis/ai_frame_scores.json
```

Optional advanced dependencies can be installed separately:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
python -m pip install -e "./src/python[ai]"
```

The `detect_highlights_audio` and `detect_highlights_transcript` operations also write per-source selection JSON directories, so a pipeline can feed `audio_step.selections` or `transcript_step.selections` directly into `generate_edl`.

### Rough-Cut Planning

Use a plan when approved clips need deterministic ordering, target duration, format intent, handles, or render settings before assembly:

```bash
videoedit roughcut plan approved.json --output roughcut_plan.json \
  --sequence diversified \
  --target-duration 90 \
  --format reel \
  --handles 0.5 \
  --max-clips 12 \
  --render-mode render

videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
```

Supported sequencing modes are `review_order`, `score`, `source_order`, and `diversified`. The planner writes `roughcut_plan.json` and `roughcut_report.md`.

---

## Installation

See [../../INSTALL.md](../../INSTALL.md) for the canonical full setup guide, including Python 3.12 virtual environments, YOLO/Ultralytics, Whisper, OpenCV, Tesseract, skill installation, and DaVinci handoff.

```bash
# Requires Python 3.10+; Python 3.12 is recommended for full local extras.
python --version

# Install FFmpeg (required)
# macOS: brew install ffmpeg-full
# Windows: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z
# Linux: sudo apt install ffmpeg
```

`videoedit` 0.5.0 supports Python 3.10+. Python 3.9 users should stay on the 0.4.x package line or upgrade Python before installing current `main`.

The base package has no mandatory Python runtime dependencies beyond the standard library. Optional provider dependencies stay in extras: `whisper`, `advanced`, `ui`, and `cloud`.

---

## Tools

### Core Tools

| Tool | Description | Usage |
|------|-------------|-------|
| `inventory.py` | Scan directory and generate footage reports | `python inventory.py "footage/"` |
| `auto_caption.py` | Burn SRT captions into video with styling | `python auto_caption.py video.mp4 out.mp4 subs.srt` |
| `video_start.py` | Interactive project initializer | `python video_start.py --interactive` |

### Optional Cloud/API Tools

Cloud integrations are not required for local scanning, review, or rough cuts. Maintained integrations should be added as `cloud.adapters` modules. Older direct cloud scripts are legacy references unless restored as package-backed adapters.

| Tool | Description | Setup |
|------|-------------|-------|
| `canva/design.py` | Local/optional motion graphics automation | Optional Canva credentials |

### DaVinci Tools

| Tool | Description | Usage |
|------|-------------|-------|
| `davinci/generate-edl.py` | Convert JSON highlights to EDL for DaVinci | `python generate-edl.py highlights.json` |

---

## Core Tool Details

### inventory.py

Generate inventory reports from footage directories.

```bash
# Generate all report formats (CSV, Markdown, JSON)
python inventory.py "footage/"

# Custom output location
python inventory.py "footage/" --output my_inventory

# CSV only
python inventory.py "footage/" --csv-only
```

**Output files:**
- `inventory.csv` — Spreadsheet-compatible format
- `inventory.md` — Human-readable summary
- `inventory.json` — Machine-readable for Claude analysis

### auto_caption.py

Burn SRT captions into video with professional styling.

```bash
# Caption a single video
python auto_caption.py video.mp4 video_captioned.mp4 transcript.srt

# Create a formatted reel with captions
python auto_caption.py raw.mp4 reel_final.mp4 subs.srt --format reel --style automotive_racing

# Batch process a directory
python auto_caption.py --batch clips/ subtitles/ output/ --style social_mobile

# List available styles
python auto_caption.py --list-styles
```

**Caption styles:**
| Style | Best For |
|-------|----------|
| `automotive_racing` | Racing content, high contrast |
| `clean_tech` | Tech content, minimalist |
| `social_mobile` | Mobile viewing, large text |
| `vin_wiki` | Documentary, interviews |
| `minimal` | Simple, clean look |

### video_start.py

Interactive project initializer that creates folder structures and config files.

```bash
# Interactive mode (walks through all options)
python video_start.py --interactive

# Quick setup
python video_start.py "My Project" --type reel

# With team config
python video_start.py interview --type interview --team-config team_config.json

# List available project types
python video_start.py --list-types
```

**Project types:**
| Type | Description |
|------|-------------|
| `reel` | Instagram Reel (9:16 vertical) |
| `youtube` | YouTube video (16:9 horizontal) |
| `documentary` | Long-form documentary |
| `interview` | Interview/Talking head |
| `broll` | B-roll footage package |
| `podcast` | Podcast/Audio content |
| `tutorial` | Tutorial/How-to video |

**Team Config:**

Create a `team_config.json` file to pre-define team members for lower thirds:

```json
{
  "team_name": "Your Team",
  "team_members": [
    {"name": "Jane Doe", "role": "Host"},
    {"name": "John Smith", "role": "Expert"}
  ]
}
```

See `team_config.example.json` for a template.

---

## Cloud API Setup

The local pipeline does not require cloud APIs. Future ElevenLabs, HeyGen, Descript, and similar integrations should be added as optional `cloud.adapters` modules through the `videoedit.modules` entry point group.

### Canva Design Helpers

1. Get API key from https://www.canva.dev/developers/connect/api
2. Set environment variables:
   ```bash
   export CANVA_API_KEY=your_key_here
   export CANVA_REFRESH_TOKEN=your_refresh_token
   ```

---

## Platform Notes

### Windows

- Use Python from `python.org` or Windows Store
- FFmpeg must be in PATH or specify full path
- Use backslashes or forward slashes for paths (both work)

### macOS

- Install FFmpeg with: `brew install ffmpeg-full`
- Python via Homebrew: `brew install python`
- For subtitle burning, `ffmpeg-full` is required

### Linux

- Install FFmpeg with libass support
- Use distribution Python or pyenv

---

## Requirements.txt

The package extras are preferred over a standalone `requirements.txt`:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
python -m pip install -e "./src/python[cloud]"
```
