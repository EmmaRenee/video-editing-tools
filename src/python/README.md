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

# V1-compatible scanner/rater
python src/python/rate_footage.py footage/ --output analysis/

# Package CLI
videoedit doctor
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/

# Pipeline preset
videoedit init reel --output reel.yaml
videoedit validate reel.yaml
videoedit run reel.yaml --input footage/ --output output/

# One-pass rough cut pipeline
videoedit init roughcut --output roughcut.yaml
videoedit run roughcut.yaml --input footage/ --output output/

# Handoff and rough cut
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit assemble approved.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl analysis/selections/*.json --output edl/
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

# Assemble the approved JSON into a rough cut
videoedit assemble approved.json --output rough_cut.mp4
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
| `extract_segments` | Extract clips from selection JSON files |
| `generate_edl` | Create EDL/XML/M3U and FFmpeg extraction scripts |
| `generate_review_assets` | Generate thumbnails and an HTML contact sheet |
| `approve_candidates` | Create approved.json from rating candidates |
| `assemble_rough_cut` | Assemble a rough cut from approved selections |
| `format_video` | Apply an FFmpeg video filter |
| `burn_captions` | Burn subtitles into video |
| `normalize_audio` | Normalize audio to target loudness |
| `concatenate_videos` | Combine multiple video clips |
| `detect_ocr_signage` | Optional OCR/signage detection from sampled frames |
| `detect_visual_objects` | Optional external object detector handoff |
| `detect_face_person_presence` | Optional face/person presence detection from sampled frames |
| `detect_motorsports_events` | Infer passes, incidents, starts, finishes, and pace moments |
| `cluster_transcript_topics` | Group transcript hits into editing topics |

### CLI Commands

```bash
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit assemble approved.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl analysis/selections/*.json --output edl/

videoedit init reel --output pipeline.yaml
videoedit validate pipeline.yaml
videoedit plan pipeline.yaml --input footage/ --output output/
videoedit run pipeline.yaml --input footage/ --output output/ --dry-run
videoedit run pipeline.yaml --input footage/ --output output/

videoedit operations
videoedit doctor
videoedit doctor --json
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

### Advanced Signals

Advanced detectors are optional providers layered on top of the deterministic rating artifacts:

- `detect_motorsports_events` reads `ratings.json` and writes `motorsports_events.json`.
- `cluster_transcript_topics` reads transcript hits from `ratings.json` and writes `topic_clusters.json`.
- `detect_ocr_signage` writes `ocr_signage.json`; it runs only when FFmpeg and Tesseract are installed.
- `detect_visual_objects` writes `visual_objects.json`; it runs only when an object detector command such as `yolo` is available.
- `detect_face_person_presence` writes `face_person_presence.json`; it runs only when FFmpeg and OpenCV are installed.

These operations produce JSON artifacts and report `status: unavailable` when optional tools are missing, so normal inventory/rating/rough-cut automation does not depend on heavy AI packages.

Optional advanced dependencies can be installed separately:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
```

The `detect_highlights_audio` and `detect_highlights_transcript` operations also write per-source selection JSON directories, so a pipeline can feed `audio_step.selections` or `transcript_step.selections` directly into `generate_edl`.

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

---

## Tools

### Core Tools

| Tool | Description | Usage |
|------|-------------|-------|
| `inventory.py` | Scan directory and generate footage reports | `python inventory.py "footage/"` |
| `auto_caption.py` | Burn SRT captions into video with styling | `python auto_caption.py video.mp4 out.mp4 subs.srt` |
| `video_start.py` | Interactive project initializer | `python video_start.py --interactive` |

### Cloud API Tools

| Tool | Description | Setup |
|------|-------------|-------|
| `elevenlabs/voiceover.py` | AI text-to-speech voiceover generation | Requires Eleven Labs API key |
| `heygen/avatar.py` | AI avatar video generation | Requires HeyGen API key |
| `canva/design.py` | Motion graphics automation | Requires Canva API key |
| `descript/mcp.py` | Descript MCP server setup | Requires Descript API key |

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

### Eleven Labs (Voiceover)

1. Get API key from https://elevenlabs.io/app/settings/api-keys
2. Set environment variable:
   ```bash
   export ELEVENLABS_API_KEY=your_key_here
   ```
3. Run:
   ```bash
   python elevenlabs/voiceover.py --text "Welcome to the show" --output intro.mp3
   ```

### HeyGen (Avatars)

1. Get API key from https://dashboard.heygen.com/settings
2. Set environment variable:
   ```bash
   export HEYGEN_API_KEY=your_key_here
   ```
3. Run:
   ```bash
   python heygen/avatar.py --text "Welcome!" --output intro.mp4
   ```

### Canva (Design)

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

Create a `requirements.txt` for easy setup:

```txt
# Cloud API tools (optional)
elevenlabs
python-dotenv
requests

# Transcription (optional)
openai-whisper
```

Install with:
```bash
pip install -r requirements.txt
```
