# Python Tools

Cross-platform Python scripts for video editing workflows.

---

## Pipeline System (New)

AI-first video editing pipeline system. Build, run, and automate video editing workflows.

### Quick Start

```bash
# Install the pipeline package
cd /path/to/video-editing-tools/src/python
pip install -e .

# Run a pipeline from preset
videoedit init reel --output my_reel.yaml
videoedit run my_reel.yaml --input footage.mp4 --output output/

# Launch the TUI
videoedit tui
```

### Python API

```python
from videoedit import Pipeline, Runner

# Build a pipeline
p = Pipeline("my_reel", "Create Instagram Reel")
p.add("transcribe_whisper", model="small")
p.add("detect_highlights_transcript", keywords=["wow", "amazing"])
p.add("extract_segments", padding=0.5)
p.add("format_video", aspect_ratio="9:16")
p.add("burn_captions", style="automotive_racing")

# Run it
runner = Runner(p)
result = runner.run("footage.mp4", "output/")
```

### Available Operations

| Operation | Description |
|-----------|-------------|
| `transcribe_whisper` | Transcribe video with Whisper AI |
| `detect_highlights_audio` | Find highlights via audio spike detection |
| `detect_highlights_transcript` | Find highlights via transcript analysis |
| `extract_segments` | Extract clips from timestamps |
| `format_video` | Resize, crop, or pad video |
| `burn_captions` | Burn subtitles into video |
| `generate_edl` | Create EDL for DaVinci Resolve |
| `concatenate_videos` | Combine multiple video clips |
| `add_crossfades` | Add crossfade transitions between clips |
| `normalize_audio` | Normalize audio to target loudness |

### CLI Commands

```bash
# Generate pipeline from preset
videoedit init reel --output my_pipeline.yaml

# Run pipeline
videoedit run my_pipeline.yaml --input footage.mp4 --output output/

# List operations
videoedit operations

# Validate pipeline
videoedit validate my_pipeline.yaml

# Launch TUI
videoedit tui
```

### Presets

Built-in presets for common workflows:

- **reel**: Instagram Reel from raw footage
- **youtube**: YouTube highlights (16:9)
- **documentary**: Documentary rough cut with transcript analysis
- **simple**: Basic audio highlight detection

### Pipeline YAML Format

```yaml
name: "Instagram Reel"
description: "Extract highlights and format for 9:16"

steps:
  - name: transcribe
    operation: transcribe_whisper
    params:
      model: small

  - name: detect_highlights
    operation: detect_highlights_transcript
    input: transcribe
    params:
      keywords: ["wow", "amazing"]
      max_clips: 5

  - name: extract_clips
    operation: extract_segments
    input: detect_highlights
    params:
      padding: 0.5

  - name: format
    operation: format_video
    params:
      aspect_ratio: "9:16"
```

---

## Installation

```bash
# Requires Python 3.9+
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
