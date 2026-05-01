# Video Editing Tools

Portable video editing toolkit for racing footage, social media reels, and documentary content. Works on Windows, macOS, and Linux.

**Status:** Active | **Version:** 1.0.0

---

## Overview

This toolkit provides FFmpeg-based video editing workflows with optional PowerShell cmdlets, Bash helpers, and AI/cloud integrations. Designed for editing real footage — not generating from scratch.

**What it does:**
- Cut dead air and silence from footage
- Extract highlights and create rough cuts
- Format for social media (Reels, YouTube, Square)
- Generate captions with Whisper
- Prepare footage for DaVinci Resolve

---

## Quick Start

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
│   │   └── VideoEditing.psm1  # PowerShell module
│   └── bash/              # Bash helpers (coming soon)
├── README.md
└── LICENSE
```

---

## Requirements

| Tool | Required | Version |
|------|----------|---------|
| FFmpeg | Yes | 4.0+ |
| Python | Optional | 3.9+ (for Whisper) |
| Whisper | Optional | Latest |
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
| [SKILL.md](src/SKILL.md) | Claude skill — workflows and techniques |
| [SETUP.md](src/SETUP.md) | Platform-specific setup guide |
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
