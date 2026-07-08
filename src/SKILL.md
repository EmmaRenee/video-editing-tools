---
name: video-editing
description: Use when editing racing footage, social media reels, or documentary content. Automates footage inventory, rating, highlight selection, review, rough cuts, DaVinci/FFmpeg handoff, captions, and social formats. Use when overwhelmed by raw footage or needing repeatable local editing workflows.
---

# Video Editing for Racing & Social Media

## Overview

AI-assisted video editing for cutting real footage, not generating from scratch. Start with the local `videoedit` pipeline to inventory footage, score exciting moments, create reviewable candidates, assemble rough cuts, and prepare DaVinci/FFmpeg handoff files. Use manual FFmpeg commands only as fallback or low-level reference.

**This skill is portable** — works on Windows, macOS, and Linux with Python, FFmpeg, and ffprobe. Claude, Whisper, OCR, and visual detectors are optional layers.

**📦 Source Repository:** https://github.com/EmmaRenee/video-editing-tools

**📚 Additional Resources:**
- Root `INSTALL.md` — Canonical installation for `videoedit`, YOLO, the skill, and optional tooling
- `SETUP.md` — Cross-platform installation and configuration guide
- `VideoEditing.psm1` — PowerShell module with 20+ video editing cmdlets
- `QUICKREF.md` — Cmdlet quick reference and common workflows
- `python/README.md` — `videoedit` package, CLI, presets, and pipeline docs

---

## When to Use

```
User mentions video editing?
  ├── Social media reels (Instagram/Facebook)
  ├── Racing footage or motorsports content
  ├── YouTube content or documentary series
  ├── "Too much footage", "overwhelmed", "need rough cut"
  ├── "Inventory/rate this footage", "find exciting moments"
  ├── Caption, subtitle, or dead air removal
  └── Repetitive cutting tasks
```

**Use when:**
- Cutting racing footage into highlights or reels
- Converting long recordings into social media clips
- Inventorying and rating raw footage before editing
- Generating candidate clips, review sheets, and selection JSON
- Creating automated rough cuts from approved selections
- Need to remove dead air, silence, or boring sections
- Want captions or subtitles automatically
- Preparing footage for DaVinci Resolve
- Repetitive format conversions (vertical/horizontal)

**Don't use for:**
- Generating video from prompts (this is for editing real footage)
- Advanced color grading or VFX (use DaVinci directly)
- Audio mastering (use dedicated audio tools)

---

## Core Principle

**Edit, don't generate.** The value is compression — turning hours of raw footage into minutes of compelling content. The deterministic pipeline finds candidate moments and explains why; you make the creative decisions in review.

---

## Preferred Automated Pipeline

```
Raw footage (hours)
  → videoedit modules/doctor (confirm enabled feature surface)
  → videoedit inventory/rate (metadata, scenes, silence, audio spikes, transcripts)
  → optional detect_visual_objects + rate --visual-objects when YOLO vision signals should affect B-roll
  → optional videoedit ai score-frames + rate --ai-frame-scores for profile-based AI scoring
  → optional ai_reel / ai_garage_shop / ai_event_recap presets for local AI-assisted recall
  → ratings.json + candidates.csv + review assets
  → optional videoedit ai judge after review-assets when a local VLM provider is configured
  → optional videoedit ai dataset/train-scorer when reviewed decisions exist across projects
  → videoedit calibrate from-decisions/evaluate/tune/compare/apply when human feedback exists
  → content-map / quote-mining / series planning when editorial direction is needed
  → review/contact_sheet.html or review_decisions.json
  → approved.json
  → videoedit roughcut plan + assemble --plan
  → rough_cut.mp4 + captioned clips + EDL/XML/M3U + extracted clips
  → DaVinci Resolve (final polish, color, export)
```

Use package automation first. It keeps outputs JSON-first and explainable, and it produces artifacts that can be reused by DaVinci, FFmpeg, or later pipeline steps.

---

## Preferred Automated Workflow

### 1. Check local tools

```bash
videoedit doctor
videoedit doctor --json
videoedit modules list
videoedit modules doctor
```

Required base tools are FFmpeg and ffprobe. Whisper, Tesseract, OpenCV, YOLO, OpenCLIP, and Torch are optional providers. The recommended AI path is local/open-source and does not require a paid subscription.

### 1a. Check or configure feature modules

```bash
videoedit modules list
videoedit modules enable content.series
videoedit modules disable advanced.vision
videoedit modules scaffold my_feature --output videoedit-my-feature/
```

Core modules are always enabled. Optional modules are project-local via `.videoedit/config.json`. Pipelines may declare `requires_modules`; validate before long runs.

Community extensions should be installable Python packages registered through the `videoedit.modules` entry point group. Use `docs/community-modules.md` and `videoedit modules scaffold` for the contract: stable dotted IDs, lightweight imports, diagnostics for optional providers, JSON-first artifacts, preset `requires_modules`, and tests. Do not load arbitrary local scripts as modules.

Available built-in modules:

| Module | Use |
|--------|-----|
| `core.inventory` | Footage catalog and metadata |
| `core.rating` | Signal analysis, scoring, candidate selection |
| `core.calibration` | Ground-truth scoring evaluation and tuning |
| `core.pipeline` | YAML planning, validation, and runs |
| `core.review` | Review assets, approvals, rough cuts |
| `core.handoff` | EDL/XML/M3U and clip extraction |
| `delivery.captions` | Styled caption burning and delivery formats |
| `content.series` | Reusable social/content series plans |
| `content.reports` | Content maps and quote mining |
| `project.scaffold` | Project folder scaffolding |
| `advanced.vision` | OCR, object, face/person providers |
| `advanced.ai` | AI profiles, OpenCLIP frame scoring, clip judging, review learning, missed-moment discovery |
| `advanced.motorsports` | Motorsports event/topic artifacts |
| `cloud.adapters` | Future maintained cloud adapters |

### 2. Inventory, score, and select candidates

```bash
videoedit rate footage/ --output analysis/
```

This writes inventory, ratings, candidates, review docs, and per-source selections. For V1 compatibility:

```bash
python src/python/rate_footage.py footage/ --output analysis/
```

### 2a. Optional vision and signal fusion

Use this only when optional providers should influence B-roll or rough-cut selection. `vision_reel` runs object, OCR, and face/person providers first, then rates with the generated artifacts:

```bash
videoedit init vision_reel --output vision_reel.yaml
videoedit run vision_reel.yaml --input footage/ --output output/
```

For explicit fused rating:

```bash
videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals ocr footage/ --output analysis/ocr_signage.json
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit signals motorsports analysis/ratings.json --output analysis/motorsports_events.json
videoedit signals topics analysis/ratings.json --output analysis/topic_clusters.json
videoedit signals validate analysis/visual_objects.json

videoedit rate footage/ --output analysis_fused/ \
  --visual-objects analysis/visual_objects.json \
  --ocr-signage analysis/ocr_signage.json \
  --face-person analysis/face_person_presence.json \
  --motorsports-events analysis/motorsports_events.json \
  --topic-clusters analysis/topic_clusters.json \
  --ai-frame-scores analysis/ai_frame_scores.json
```

Fused ratings add labels and scores such as `object_*`, `ocr_signage`, `face_presence`, `person_presence`, `motorsports_event`, `topic_cluster`, `ai_garage_work`, `ai_vehicle_action`, `ai_interview_moment`, `object_presence_score`, `ai_frame_score`, and provider-specific advanced scores.

### 2b. Optional AI profile scoring and missed moments

Use this when deterministic signals need help finding visual context, garage work, motorsports action, interviews, event recap moments, social reel openers, or documentary context. It is explicit: base ratings do not change unless `--ai-frame-scores` is supplied.

```bash
videoedit ai profiles list
videoedit ai profiles show garage_shop
videoedit ai score-frames footage/ --profile garage_shop --output analysis/ai_frame_scores.json

videoedit rate footage/ --output analysis_ai/ \
  --ai-frame-scores analysis/ai_frame_scores.json

videoedit ai find-missed analysis/ratings.json \
  --ai-frame-scores analysis/ai_frame_scores.json \
  --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
videoedit calibrate from-decisions review_missed/missed_review_decisions.json \
  --ratings analysis/ratings.json \
  --output annotations_from_missed.json
```

Built-in AI profiles: `general_broll`, `garage_shop`, `motorsports`, `interview`, `event_recap`, `social_reel`, and `documentary`.

AI missed moments are review-only. Never insert them into `approved.json` or a rough cut automatically; route them through `missed_review.html`, decisions, and calibration annotations first.

For reusable YAML workflows, prefer these AI presets before hand-writing steps:

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

Use `ai_reel` for short-form local AI frame scoring and review handoff. Use `ai_garage_shop` for generic shop work, tools, vehicle detail, and build-process B-roll. Use `ai_event_recap` for generic event or motorsports recap footage and review-only missed moments. These presets declare `advanced.ai` and OpenCLIP/Torch/Pillow dependency metadata; run `videoedit modules doctor` when setup is unclear.

### 2c. Optional AI clip judging

Use this only after `review-assets` exists and only when a local VLM-style provider is configured. The provider command reads request JSON on stdin and writes judgment JSON on stdout. Keep these reasons separate from deterministic scoring reasons.

```bash
export VIDEOEDIT_AI_JUDGE_COMMAND="/path/to/local-vlm-judge"
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json
videoedit review-assets analysis/ratings.json --output review_ai/ \
  --ai-clip-judgments analysis/ai_clip_judgments.json
videoedit rate footage/ --output analysis_with_ai_explanations/ \
  --ai-clip-judgments analysis/ai_clip_judgments.json
```

If no provider is configured, `videoedit ai judge` writes an unavailable artifact and returns non-zero. Do not treat AI clip-judge suggestions as approvals; show them in review as `ai_explanations` and let the human decide.

### 2d. Optional learning from reviewed decisions

Use this after there are reviewed decisions from one or more projects. The dataset is JSONL, portable, and does not copy source video by default. The learned scorer is a small inspectable local model and must be explicitly supplied to `rate`.

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

Do not train from unreviewed machine output. Prefer datasets that include multiple project profiles and both positive and negative decisions.

### 2e. Calibrate scoring with human annotations

Use calibration when the user has reviewed footage or wants to tune the scorer before rough cuts:

```bash
videoedit calibrate init --output annotations.json
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
videoedit calibrate apply calibration/proposed_config.json --output configs/scoring.json
videoedit rate footage/ --output analysis_tuned/ --config calibration/proposed_config.json
```

Annotation ratings are `select`, `review`, `broll`, `reject`, `cut`, and `ignore`. Calibration writes precision/recall reports, missed moments, false positives, ranked config candidates, and `proposed_config.json`; it does not overwrite project defaults.

### 3. Review and approve

```bash
videoedit review-assets analysis/ratings.json --output review/ --calibration calibration/calibration_report.json
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit review-tui review/review_assets.json --decisions review/review_decisions.json
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
```

Open the static review UI at `review/contact_sheet.html` or use `videoedit review-tui` to inspect thumbnails/proxies, filter/sort clips, review signal and calibration context, approve or reject clips, add notes, reorder, and export `review_decisions.json`.

Regenerating `review-assets` into the same folder preserves matching decisions, notes, and order from `review_decisions.json`; do not delete that file unless the user wants to reset review state. Treat `approve`, `promote`, `select`, `review`, and `broll` decisions as handoff-positive, and treat `reject`, `cut`, and `ignore` as excluded from `approved.json`.

### 4. Assemble, extract, and export

```bash
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence diversified --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl approved.json --output edl/
```

Use editorial planning outputs when the user wants content strategy, social series, or interview paper-edit support:

```bash
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
```

`approved.json` can contain mixed source files. The handoff includes EDL, XML, M3U, and extraction scripts.

`videoedit export-edl`, `videoedit extract-segments`, and `videoedit assemble` also accept Drive-style soundbite JSON with top-level `project`/`fps` and per-clip `source`, `start`, `end`, and `label`.

---

## Preset-Based Workflows

Use presets when you want a repeatable pipeline.

```bash
videoedit init roughcut --output roughcut.yaml
videoedit init reel --output reel.yaml
videoedit init documentary --output documentary.yaml
videoedit init motorsports --output motorsports.yaml
videoedit init ai_reel --output ai_reel.yaml
videoedit init ai_garage_shop --output ai_garage_shop.yaml
videoedit init ai_event_recap --output ai_event_recap.yaml
```

Always validate or dry-run before a long scan:

```bash
videoedit validate roughcut.yaml
videoedit plan roughcut.yaml --input footage/ --output output/
videoedit run roughcut.yaml --input footage/ --output output/ --dry-run
videoedit run roughcut.yaml --input footage/ --output output/
```

Preset intent:

| Preset | Use |
|--------|-----|
| `simple` | FFmpeg-only rating with transcripts off |
| `reel` | Short high-energy social candidates |
| `roughcut` | Rate, review, approve, EDL, and assemble a rough cut |
| `youtube` | Longer highlight candidates |
| `documentary` | Transcript-heavy story and soundbite selection |
| `motorsports` | Racing event/topic artifacts plus review outputs |
| `vision_reel` | Optional vision providers plus fused rating and review |
| `ai_reel` | Local AI frame scoring plus deterministic reel review |
| `ai_garage_shop` | Generic shop, tools, vehicle detail, and build-process review |
| `ai_event_recap` | Event recap scoring plus review-only missed moments |

---

## Composable Operations

Use `videoedit operations` to list supported pipeline steps. YAML pipelines can compose these typed artifact operations:

```text
inventory
analyze_signals
rate_footage
transcribe_whisper
detect_highlights_audio
detect_highlights_transcript
evaluate_ratings
calibrate_scoring
generate_review_assets
approve_candidates
plan_roughcut
assemble_rough_cut
extract_segments
generate_edl
format_video
burn_captions
normalize_audio
concatenate_videos
plan_content_series
generate_content_map
quote_mining
scaffold_project
detect_ocr_signage
detect_visual_objects
score_ai_frames
detect_face_person_presence
detect_motorsports_events
cluster_transcript_topics
find_ai_missed_moments
generate_missed_review
judge_ai_clips
build_review_dataset
train_review_scorer
```

Favor `rate_footage`, `generate_review_assets`, `approve_candidates`, `assemble_rough_cut`, and `generate_edl` for rough-cut automation. Use format/caption/audio operations for final delivery variants.

---

## Rating Outputs

`videoedit rate` and `rate_footage.py` produce:

| Artifact | Purpose |
|----------|---------|
| `inventory.json`, `inventory.csv`, `inventory.md` | Footage catalog with metadata |
| `ratings.json` | Full machine-readable report with signals and candidates |
| `candidates.csv` | Spreadsheet-friendly clip candidates |
| `review.md` | Human-readable review summary |
| `review.html` | Table view of candidates and score explanations |
| `selections/*.json` | Per-source selection JSON for EDL/export operations |
| `calibration_report.json`, `calibration_report.md` | Scoring precision/recall against annotations |
| `missed_moments.csv`, `false_positives.csv` | Calibration review queues |
| `config_candidates.csv`, `proposed_config.json` | Ranked tuning candidates from `videoedit calibrate tune` |
| `ai_frame_scores.json` | Optional OpenCLIP/profile frame-score artifact |
| `ai_clip_judgments.json` | Optional local VLM clip-judge artifact with separate AI reasons |
| `ai_missed_moments.json` | Optional review-only AI-discovered missed moments |
| `missed_review.html`, `missed_review_decisions.json` | Review and annotation-compatible decisions for missed moments |

Candidates include score, action (`select`, `review`, `broll`, `cut`), labels, signal scores, and reasons explaining why they were selected.

Learning/training outputs are conditional and are produced by the `videoedit ai dataset build` and `videoedit ai train-scorer` commands:

| Artifact | Purpose |
|----------|---------|
| `review_dataset.jsonl` | Portable reviewed-decision training records without source video copies |
| `local_scorer.json` | Small inspectable learned scorer trained from review decisions |

## Content Planning Outputs

Use these after `videoedit rate` when the user wants editorial planning, reusable social series, or quote mining:

```bash
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
```

Outputs include `ranked_content_map.md`, `content_map.json`, `quote_mining.md`, `series_plan.json`, `caption_suggestions.md`, and `series_selections.json`.

Initial series templates: `what_were_looking_for`, `team_tuesday`, `engine_build_montage`, and `shop_tour`.

## Styled Captions

Prefer the package command:

```bash
videoedit captions styles
videoedit burn-captions clip.mp4 captions.srt --output captioned.mp4 --style automotive_racing --format reel
```

The standalone `python src/python/auto_caption.py` remains a compatibility wrapper. Styles include `automotive_racing`, `clean_tech`, `social_mobile`, `vin_wiki`, and `minimal`.

## Project Scaffolding

Use this when starting a fresh edit package or when the user needs a repeatable folder structure:

```bash
videoedit init-project "May Shop Reel" --type reel --output projects/
videoedit init-project "Interview Pulls" --type interview --output projects/ --source footage/
```

Generated projects include `raw/`, `audio/`, `exports/`, `assets/`, `scripts/`, `drafts/`, `analysis/`, `review/`, `workflow_config.json`, `README.md`, and `.videoedit/config.json`.

Supported project types: `reel`, `youtube`, `documentary`, `interview`, and `broll`.

## Selection JSON And Soundbite Compatibility

Use `videoedit export-edl`, `videoedit extract-segments`, and `videoedit assemble` for handoff or rough-cut generation from selection JSON. The shared loader accepts:

- V1 per-source `selections/*.json`
- `approved.json` from `videoedit approve`
- Drive-style soundbite / paper-edit JSON with top-level `project` and `fps`

Drive-style example:

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

If a selection has no top-level `source`, every clip must include `source`. FPS precedence is explicit `--fps`, then JSON `fps`, then `30`.

---

## Advanced Optional Providers

Keep these optional. The base pipeline should work with only FFmpeg/ffprobe.

| Operation | Output | Dependency |
|-----------|--------|------------|
| `detect_ocr_signage` | `ocr_signage.json` | FFmpeg + Tesseract |
| `detect_visual_objects` | `visual_objects.json` | External detector such as YOLO; includes parsed detections, class counts, and timestamped object segments |
| `detect_face_person_presence` | `face_person_presence.json` | FFmpeg + OpenCV |
| `detect_motorsports_events` | `motorsports_events.json` | `ratings.json` |
| `cluster_transcript_topics` | `topic_clusters.json` | Transcript hits in `ratings.json` |

Install optional advanced dependencies only when needed:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
```

---

## Manual Fallback / Low-Level Reference

---

## Manual Fallback: Analyze Footage (FFmpeg)

Use these commands when the `videoedit` pipeline is unavailable or when you need a one-off low-level probe.

### Get video info

```bash
# Duration, resolution, codecs, audio info
ffprobe -i raw_footage.mp4 -show_format -show_streams -v quiet

# Quick duration check
ffprobe -i raw_footage.mp4 -show_entries format=duration -v quiet -of csv="p=0"
```

### Detect scenes (automatic cut points)

```bash
# Find scene changes - gives you timestamps for potential cuts
# Windows: use findstr instead of grep
ffmpeg -i raw_footage.mp4 -vf "select='gt(scene,0.4)',showinfo" -vsync vfr -f null - 2>&1 | findstr pts_time

# macOS/Linux:
ffmpeg -i raw_footage.mp4 -vf "select='gt(scene,0.4)',showinfo" -vsync vfr -f null - 2>&1 | grep pts_time
```

### Extract audio for transcription

```bash
# Pull audio for Claude to analyze
ffmpeg -i raw_footage.mp4 -vn -acodec pcm_s16le -ar 16000 audio.wav

# Or if there's no audio, create a silent reference
ffmpeg -f lavfi -i anullsrc=cl=mono:r=16000 -t 10 silent.wav
```

### Detect silence (find dead air to remove)

```bash
# Find quiet sections for potential cutting
ffmpeg -i raw_footage.mp4 -af silencedetect=noise=-30dB:d=1 -f null - 2>&1 | findstr silence
```

---

## Manual Fallback: Identify Highlights (Claude)

If `videoedit rate` is unavailable, Claude can still help interpret timestamps, transcripts, and notes. Prefer `ratings.json` and `candidates.csv` when available.

### Prompt template for racing footage

```
I have [X hours] of racing footage. Here's what I know:
- Track: [track name]
- Session: [practice, qualifying, race]
- Driver: [name, car number]

Help me:
1. Identify the most exciting moments (passes, incidents, fast laps)
2. Suggest 3-5 clips that would work for Instagram reels
3. Recommend which sections to cut entirely

I can provide: timestamps, transcript, or description of key events.
```

### For social media reels

```
I need to create [30/60/90]-second reels from this footage.
Target audience: [fans, friends, sponsors]

Suggest:
- 3-5 reel concepts with themes
- Rough timestamps for each
- Hook ideas (first 3 seconds to grab attention)
- Music suggestions or mood
```

### For documentary series

```
This is for a documentary about [specific story/season/driver].

Help me plan a narrative arc:
- Beginning: setup, context, what's at stake
- Middle: rising action, challenges, turning points
- End: resolution, aftermath, what's next

Suggest which footage supports each part of the story.
```

---

## Manual Fallback: Create Rough Cut (FFmpeg)

Use this when you already have timestamps but are not using `videoedit assemble` or `videoedit extract-segments`.

### Extract specific segments

```bash
# Cut from 12:30 to 15:45
ffmpeg -i raw.mp4 -ss 00:12:30 -to 00:15:45 -c copy highlight_01.mp4

# PowerShell batch cutting (Windows)
Get-Content cuts.txt | ForEach-Object {
    $parts = $_.Split(',')
    $start = $parts[0]
    $end = $parts[1]
    $label = $parts[2]
    ffmpeg -i raw.mp4 -ss $start -to $end -c copy "clips/$label.mp4"
}

# Bash/mksh batch cutting (macOS/Linux)
while IFS=, read -r start end label; do
  ffmpeg -i raw.mp4 -ss "$start" -to "$end" -c copy "clips/${label}.mp4"
done < cuts.txt
```

### Concatenate clips into rough cut

```bash
# Create concat file (paths must be escaped on Windows)
# Windows: use backslashes or forward slashes (both work)
file clip1.mp4
file clip2.mp4
file clip3.mp4

# Stitch together
ffmpeg -f concat -safe 0 -i concat.txt -c copy rough_cut.mp4
```

### Remove silence (auto-cut dead air)

```bash
# Remove anything quieter than -35dB for 0.5+ seconds
ffmpeg -i input.mp4 -af silenceremove=start_periods=1:start_silence=0.5:start_threshold=-35dB:stop_periods=-1:stop_silence=0:stop_threshold=-35dB output.mp4
```

### Normalize audio levels

```bash
# EBU R128 loudness standard (consistent volume)
ffmpeg -i input.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11 -c:v copy normalized.mp4
```

---

## Manual Fallback: Social Media Formats

### Reformat for different platforms

```bash
# Vertical for Instagram Reels/TikTok (center crop, 9:16)
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reels_ready.mp4

# Square for Instagram feed (1:1)
ffmpeg -i input.mp4 -vf "crop=ih:ih,scale=1080:1080" square.mp4

# Horizontal for YouTube (16:9, ensure 1080p)
ffmpeg -i input.mp4 -vf "scale=-2:1080" youtube_ready.mp4
```

### Smart reframing with padding

```bash
# Add blurred sides when going horizontal → vertical
ffmpeg -i input.mp4 -vf "split[s][b];[s]scale=1080:1920[bg];[b]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2" vertical_blurred.mp4
```

### Create proxy for faster editing

```bash
# Smaller file for editing speed
ffmpeg -i raw.mp4 -vf "scale=960:-2" -c:v libx264 -preset ultrafast -crf 28 proxy.mp4

# After editing, replace with full quality
ffmpeg -i final_edit.mp4 -i raw.mp4 -map 0 -c copy -map 1 -c:v:1 libx264 -preset slow -crf 18 final_high_quality.mp4
```

---

## Manual Fallback: Captions & Subtitles

### Generate SRT with Whisper

```bash
# Transcribe audio to SRT format
whisper video.mp4 --model medium --output_format srt --output_dir transcripts/

# Available models: tiny, base, small, medium, large (faster→slower, less→more accurate)
```

### Burn captions with FFmpeg

```bash
# Basic subtitle burn (requires FFmpeg with libass support)
ffmpeg -i video.mp4 -vf "subtitles=captions.srt" output.mp4

# With custom styling
ffmpeg -i video.mp4 -vf "subtitles=captions.srt:force_style='FontSize=28,BorderStyle=1'" output.mp4

# Note: On Windows, escape colons in force_style: force_style='FontSize=28'
```

### Windows subtitle note

Standard FFmpeg builds on Windows may not include libass. Install a full-featured build:
- Download from: https://www.gyan.dev/ffmpeg/builds/
- Use `ffmpeg-release-full.7z`

---

## Manual Fallback: DaVinci Resolve Prep

### Generate EDL from manual highlights

Prefer `videoedit export-edl analysis/selections/*.json --output edl/` or `videoedit export-edl approved.json --output edl/`. Use this reference only when manually converting timestamp notes into a DaVinci handoff.

**EDL format example:**
```
001  001  V     C        00:00:12:00 00:00:15:30 00:00:00:00 00:00:03:30
* | FROM CLIP NAME: race_raw.mp4
002  002  V     C        00:00:45:00 00:00:46:30 00:00:03:30 00:00:05:00
* | FROM CLIP NAME: race_raw.mp4
```

**Manual JSON shape:**
```json
{
  "source": "race_raw.mp4",
  "clips": [
    {"start": "00:12:30", "end": "00:15:45", "label": "overtake"},
    {"start": "00:45:00", "end": "00:46:30", "label": "incident"}
  ]
}
```

### Export format for DaVinci

```bash
# DNxHD/HR (best for DaVinci on Mac/PC)
ffmpeg -i rough_cut.mp4 -c:v dnxhd -profile:v dqxhr_444 -pix_fmt rgb48le -c:a pcm_s16le for_davinci.mov

# Or ProRes (alternative, works better on Windows)
ffmpeg -i rough_cut.mp4 -c:v prores_ks -profile:v 3 -c:a pcm_s16le for_davinci.mov
```

---

## Optional: Cloud AI Tools

Cloud tools are optional and should not be required for inventory, scoring, review, rough cuts, or handoff.

Prefer maintained `cloud.adapters` modules when they exist:

```bash
videoedit modules list
videoedit modules doctor
```

Older direct ElevenLabs, HeyGen, and Descript scripts are legacy references unless restored as package-backed modules.

### Descript - Text-Based Editing (MCP)

**Requires Claude desktop app** with MCP connector setup.

**Setup:** Customize → Connectors → Add custom → URL: `https://api.descript.com/v2/mcp`

**Example prompts in Claude Chat mode:**
```
"Import race_footage.mp4 and transcribe it"
"Remove all filler words and add Studio Sound"
"Create a 60-second highlight reel from this footage"
```

---

## Optional: Local Tool Configuration

*If you have wrapper scripts installed, configure their locations here.*

### Format conversion scripts

```bash
# Prefer videoedit commands first. If you have these older wrapper scripts, use them as low-level shortcuts.
# Configure your script paths:

# reels-format input.mp4 output_reel.mp4
# youtube-format input.mp4 output_youtube.mp4
# find-silence input.mp4
# fix-audio input.mp4 output_normalized.mp4
# make-proxy raw.mp4
# video-start
```

### Windows setup

If using Windows, you can create batch files or PowerShell functions as wrappers. Example `reels-format.bat`:
```batch
@echo off
ffmpeg -i %1 -vf "crop=ih*9/16:ih,scale=1080:1920" %2
```

Or PowerShell function in `$PROFILE`:
```powershell
function reels-format {
    param($input, $output)
    ffmpeg -i $input -vf "crop=ih*9/16:ih,scale=1080:1920" $output
}
```

---

## Common Workflows

### Automated: raw racing footage to rough cut and handoff

```bash
videoedit doctor
videoedit init roughcut --output roughcut.yaml
videoedit plan roughcut.yaml --input footage/ --output output/
videoedit run roughcut.yaml --input footage/ --output output/ --dry-run
videoedit run roughcut.yaml --input footage/ --output output/
```

The `roughcut` preset rates footage, creates review assets, approves the default high-value candidates, exports EDL/XML/M3U handoff files, and assembles a rough cut.

### Automated: racing footage to reel candidates

```bash
videoedit init reel --output reel.yaml
videoedit run reel.yaml --input footage/ --output reel_output/
videoedit review-assets reel_output/ratings.json --output reel_review/
videoedit approve reel_output/ratings.json --output approved_reels.json --decisions reel_review/review_decisions.json
videoedit extract-segments approved_reels.json --output reel_clips/
```

Use `reel_review/contact_sheet.html`, `candidates.csv`, and `review.html` to pick the strongest moments before final social formatting.

### Manual fallback: raw racing footage to 3 reels

```bash
# 1. Analyze - find silence
ffmpeg -i race_raw.mp4 -af silencedetect=noise=-30dB:d=1 -f null - 2>&1 | findstr silence > silence_log.txt

# 2. Extract highlights from manual timestamps if videoedit candidates are unavailable
# Example: overtake at 12:30, incident at 45:20, podium at 1:23:10
ffmpeg -i race_raw.mp4 -ss 00:12:00 -to 00:13:30 -c copy overtake.mp4
ffmpeg -i race_raw.mp4 -ss 00:45:00 -to 00:46:45 -c copy incident.mp4
ffmpeg -i race_raw.mp4 -ss 01:22:30 -to 01:24:00 -c copy podium.mp4

# 3. Format for reels
ffmpeg -i overtake.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_overtake.mp4
ffmpeg -i incident.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_incident.mp4
ffmpeg -i podium.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_podium.mp4
```

### Manual fallback: create captioned reel

```bash
# 1. Vertical format
ffmpeg -i clip.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" vertical.mp4

# 2. Generate captions with Whisper
whisper vertical.mp4 --model medium --output_format srt

# 3. Burn in captions
ffmpeg -i vertical.mp4 -vf "subtitles=vertical.srt:force_style='FontSize=28,BorderStyle=1'" final_reel.mp4
```

---

## Tool Comparison

| Tool | Best For | Portability |
|------|----------|-------------|
| **videoedit** | Inventory, scoring, candidate selection, review, rough cuts, EDL/XML/M3U handoff | ✅ Cross-platform |
| **FFmpeg** | Low-level cuts, batch processing, format conversion | ✅ Cross-platform |
| **Claude** | Editorial planning, interpreting transcripts/notes, narrative structure | ✅ Cross-platform |
| **Whisper** | Transcription | ✅ Cross-platform |
| **DaVinci Resolve** | Color grading, audio mix, final polish | Windows, Mac, Linux |
| **Descript** | Text-based editing (MCP via Claude) | ✅ Web/cloud |
| **Eleven Labs** | AI voice from text | ✅ API/Cloud |
| **HeyGen** | AI avatars | ✅ API/Cloud |
| **Gling** | AI highlight detection | Web UI only |

---

## Quick Reference: Common Commands

### videoedit Automated Pipeline

```bash
# Check dependencies
videoedit doctor
videoedit modules list
videoedit modules doctor

# Configure optional feature modules for this project
videoedit modules enable content.series
videoedit modules disable advanced.vision
videoedit modules scaffold my_feature --output videoedit-my-feature/

# Inventory only
videoedit inventory footage/ --output analysis/

# Inventory, analyze, rate, and write selections
videoedit rate footage/ --output analysis/

# Review and approve
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json

# Assemble and hand off
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence diversified --target-duration 90 --format reel --render-mode render
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit export-edl approved.json --output edl/
videoedit extract-segments approved.json --output clips/

# Content and editorial planning
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/

# Captions and delivery
videoedit captions styles
videoedit burn-captions clip.mp4 captions.srt --output captioned.mp4 --style automotive_racing --format reel

# Project setup
videoedit init-project "Race Day Reel" --type reel --output projects/

# Preset pipelines
videoedit init roughcut --output roughcut.yaml
videoedit validate roughcut.yaml
videoedit plan roughcut.yaml --input footage/ --output output/
videoedit run roughcut.yaml --input footage/ --output output/ --dry-run
videoedit run roughcut.yaml --input footage/ --output output/
videoedit operations
```

### PowerShell Cmdlets (Windows-first, cross-platform)

```powershell
# Import module first
Import-Module VideoEditing

# Video info
Get-VideoInfo video.mp4

# Format conversion
ConvertTo-Reel video.mp4              # 9:16 vertical
ConvertTo-YouTube video.mp4           # 16:9 horizontal
ConvertTo-Square video.mp4             # 1:1 square

# Cutting/joining
Copy-VideoSegment in.mp4 out.mp4 -Start "00:01:00" -End "00:02:00"
Join-VideoFiles clip1.mp4,clip2.mp4 output.mp4

# Audio
Remove-Silence in.mp4 out.mp4
Set-AudioNormalize in.mp4 out.mp4
Export-Audio video.mp4 audio.wav

# Captions
Invoke-WhisperTranscribe video.mp4 -Model small
Add-Captions video.mp4 subs.srt out.mp4

# Projects
New-VideoProject "Race Day" -Type Reel -BasePath \\NAS\projects
```

### FFmpeg Direct Commands

```bash
# Get video info
ffprobe -i video.mp4 -show_format -show_streams

# Cut segment
ffmpeg -i in.mp4 -ss 00:01:00 -to 00:02:00 -c copy out.mp4

# Concatenate
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4

# Resize for reels (9:16)
ffmpeg -i in.mp4 -vf "scale=1080:1920" out.mp4

# Normalize audio
ffmpeg -i in.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11 out.mp4

# Create proxy
ffmpeg -i in.mp4 -vf "scale=960:-2" -c:v libx264 -preset ultrafast -crf 28 proxy.mp4

# Detect silence
ffmpeg -i in.mp4 -af silencedetect=noise=-30dB:d=1 -f null -

# Export for DaVinci
ffmpeg -i in.mp4 -c:v prores_ks -profile:v 3 -c:a pcm_s16le out.mov

# Whisper
whisper video.mp4 --model medium --output_format srt
```

---

## Platform-Specific Notes

### Windows
- Use `findstr` instead of `grep`
- Use PowerShell or batch files for wrappers
- Use forward slashes or escaped backslashes for paths in concat files
- Download full FFmpeg build for subtitle support

### macOS
- Install FFmpeg: `brew install ffmpeg`
- Use `grep` for filtering output
- Bash/zsh for wrappers in `~/.local/bin/`

### Linux
- Use distribution package manager or download static build
- Use `grep` for filtering output
- Bash for wrappers

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Manually timestamping before scanning | Run `videoedit rate` first, then review `candidates.csv` and `review.html` |
| Treating optional AI as required | Start with FFmpeg/ffprobe signals; add Whisper/OCR/object providers only when useful |
| Re-encoding unnecessarily | Use `-c copy` for simple cuts |
| Not normalizing audio | Levels vary wildly between clips |
| Skipping review | Inspect `review/contact_sheet.html` or `review.md` before assembling final output |
| Starting in DaVinci with raw footage | Run `videoedit rate` or a preset pipeline first |
| Forgetting aspect ratio | Square video doesn't fit reels |

---

## Learning Path

**Start here:** Run `videoedit doctor`, then `videoedit rate footage/ --output analysis/`.

**Next:** Review `candidates.csv`, `review.md`, `review.html`, and `selections/*.json` to understand why clips were selected.

**Then:** Use `videoedit init roughcut`, `videoedit plan`, `videoedit run --dry-run`, and `videoedit run` to automate rough cuts and handoff files.

**Advanced:** Add transcript, OCR/signage, object, face/person, motorsports-event, and topic-clustering providers after the deterministic pipeline is working.

**Goal:** Spend 80% of your time on creative decisions in DaVinci, not on boring cutting.
