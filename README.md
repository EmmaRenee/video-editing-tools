# Video Editing Tools

Portable video editing toolkit for racing footage, social media reels, and documentary content. Works on Windows, macOS, and Linux.

**Status:** Active | **Version:** 1.0.0

---

## Overview

This toolkit provides FFmpeg-based video editing workflows with optional PowerShell cmdlets, Bash helpers, and AI/cloud integrations. Designed for editing real footage — not generating from scratch.

**What it does:**
- Cut dead air and silence from footage
- Extract highlights and create rough cuts
- Calibrate scoring against human-reviewed moments
- Format for social media (Reels, YouTube, Square)
- Generate captions with Whisper
- Prepare footage for DaVinci Resolve

---

## Quick Start

For a complete installation path covering `videoedit`, YOLO/Ultralytics, PowerShell helpers, Claude/Codex skill installation, and DaVinci handoff, use the canonical [INSTALL.md](INSTALL.md).

### 1. Install FFmpeg

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

### 2. Install PowerShell Module (Windows)

```powershell
# Copy module to your PowerShell modules path
$modulePath = "$HOME\Documents\PowerShell\Modules\VideoEditing"
New-Item -ItemType Directory -Path $modulePath -Force
Copy-Item src/powershell/VideoEditing.psm1 $modulePath

# Add to profile for auto-load
Add-Content -Path $PROFILE -Value "Import-Module VideoEditing -ErrorAction SilentlyContinue"
```

### 3. Use the Skill

Copy `src/SKILL.md` to your Claude skills directory:

```bash
# macOS/Linux
cp src/SKILL.md ~/.claude/skills/video-editing/SKILL.md

# Windows (PowerShell)
Copy-Item src\SKILL.md $env:USERPROFILE\.claude\skills\video-editing\SKILL.md
```

### 4. Python Tools (Optional)

```bash
# Clone or cd into repo
cd video-editing-tools

# Recommended local environment
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "./src/python[whisper,advanced]"

# Run inventory scanner
python src/python/inventory.py "footage/"

# Inventory, score, and select exciting moments
python src/python/rate_footage.py "footage/" --output analysis/

# Package CLI
videoedit doctor
videoedit modules list
videoedit rate footage/ --output analysis/
videoedit calibrate init --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit assemble approved.json --output rough_cut.mp4
videoedit init reel --output reel.yaml
videoedit run reel.yaml --input footage/ --output output/
videoedit init roughcut --output roughcut.yaml
videoedit run roughcut.yaml --input footage/ --output output/
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series analysis/ratings.json --template team_tuesday --output series/
videoedit init-project "May Shop Reel" --type reel --output projects/

# Burn captions
python src/python/auto_caption.py video.mp4 out.mp4 subs.srt
videoedit burn-captions video.mp4 subs.srt --output out.mp4 --style automotive_racing --format reel
```

See [src/python/README.md](src/python/README.md) for full documentation.

### Calibration Loop

Use calibration after the first `videoedit rate` pass to compare machine-selected candidates against human annotations. `evaluate` writes precision/recall reports, missed moments, and false positives. `tune` writes `config_candidates.csv` and `proposed_config.json`; it does not overwrite project defaults.

```bash
videoedit rate footage/ --output analysis/
videoedit calibrate init --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit rate footage/ --output analysis_tuned/ --config calibration/proposed_config.json
```

### Optional YOLO Object Signals

When `advanced.vision` is enabled and YOLO is installed, `detect_visual_objects` writes parsed object detections, class counts, and time-based object segments to `visual_objects.json`. Use that artifact as an explicit rating input when object/person/vehicle presence should influence B-roll and rough-cut candidates:

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

```bash
videoedit run vision.yaml --input footage/ --output analysis/vision
videoedit rate footage/ --output analysis_objects/ --visual-objects analysis/visual_objects.json
```

---

## PowerShell Cmdlets

| Cmdlet | Purpose |
|--------|---------|
| `Get-VideoInfo` | Get video metadata |
| `ConvertTo-Reel` | 9:16 vertical format |
| `ConvertTo-YouTube` | 16:9 horizontal format |
| `Copy-VideoSegment` | Extract clip |
| `Join-VideoFiles` | Concatenate videos |
| `Remove-Silence` | Cut dead air |
| `Set-AudioNormalize` | Fix audio levels |
| `Add-Captions` | Burn subtitles |
| `Invoke-WhisperTranscribe` | Transcribe with Whisper |
| `New-VideoProject` | Create project structure |

See [QUICKREF.md](src/QUICKREF.md) for complete documentation.

---

## Project Structure

```
video-editing-tools/
├── src/
│   ├── SKILL.md           # Claude skill file
│   ├── SETUP.md           # Installation guide
│   ├── QUICKREF.md        # Cmdlet reference
│   ├── powershell/
│   │   └── VideoEditing.psm1  # PowerShell module (20+ cmdlets)
│   ├── python/            # Python tools
│   │   ├── inventory.py        # Footage inventory wrapper
│   │   ├── rate_footage.py     # V1-compatible footage rater
│   │   ├── videoedit/          # Installable scanner/rater/pipeline package
│   │   ├── auto_caption.py     # Cross-platform caption burning
│   │   ├── elevenlabs/         # TTS integration
│   │   ├── heygen/             # Avatar generation
│   │   ├── canva/              # Graphics automation
│   │   ├── davinci/            # EDL tools
│   │   └── descript/           # MCP server
│   └── bash/              # Bash helpers (coming soon)
├── tests/
│   └── Test-VideoEditing.ps1   # Windows installation test
├── README.md
└── LICENSE
```

---

## Requirements

| Tool | Required | Version |
|------|----------|---------|
| FFmpeg | Yes | 4.0+ |
| Python | Yes for `videoedit` | 3.12 recommended |
| Whisper | Optional | Latest |
| YOLO/Ultralytics | Optional | Latest compatible |
| PowerShell | Optional | 5.1+ / 7+ |

---

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10/11 | ✅ Full | PowerShell cmdlets available |
| macOS | ✅ Full | Bash + Python workflows |
| Linux | ✅ Full | Bash + Python workflows |

---

## Examples

### Create an Instagram Reel

```powershell
# PowerShell
Import-Module VideoEditing
ConvertTo-Reel raw_footage.mp4 reel.mp4
```

```bash
# Bash
ffmpeg -i raw_footage.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" -c:a copy reel.mp4
```

### Extract and Join Clips

```powershell
# Extract segments
Copy-VideoSegment race.mp4 overtake.mp4 -Start "00:12:30" -End "00:13:30"
Copy-VideoSegment race.mp4 incident.mp4 -Start "00:45:00" -End "00:46:30"

# Join together
Join-VideoFiles overtake.mp4,incident.mp4 highlights.mp4
```

### Add Captions

```powershell
# Transcribe first
Invoke-WhisperTranscribe video.mp4 -Model small

# Burn captions
Add-Captions video.mp4 video.srt final.mp4 -FontSize 28
```

---

## Installation via Git

```bash
# Clone to your preferred location
git clone <your-repo-url> video-editing-tools

# Or add as submodule to existing project
git submodule add <your-repo-url> tools/video-editing
```

---

## Documentation

| File | Description |
|------|-------------|
| [INSTALL.md](INSTALL.md) | Canonical install guide for all tooling, YOLO, and the skill |
| [SKILL.md](src/SKILL.md) | Claude skill — workflows and techniques |
| [SETUP.md](src/SETUP.md) | Legacy platform-specific setup reference |
| [QUICKREF.md](src/QUICKREF.md) | PowerShell cmdlet reference |

---

## Contributing

Contributions welcome! Areas for enhancement:

- Bash equivalents of PowerShell cmdlets
- Additional format presets (TikTok, Snapchat, etc.)
- FFmpeg preset templates
- More caption styles
- DaVinci Resolve script templates

---

## License

MIT License - see [LICENSE](LICENSE) file.

---

## Changelog

### 1.0.0 (2026-05-01)
- Initial release
- 20+ PowerShell cmdlets
- Cross-platform FFmpeg workflows
- Claude skill for AI-assisted editing
- Whisper transcription support
- DaVinci Resolve export formats
