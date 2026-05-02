---
name: video-editing
description: Use when editing racing footage, social media reels, or documentary content. Helps cut dead air, find highlights, create rough cuts, prepare footage for DaVinci Resolve, and format for Instagram/Facebook/YouTube. Use when overwhelmed by raw footage or needing captions.
---

# Video Editing for Racing & Social Media

## Overview

AI-assisted video editing for cutting real footage, not generating from scratch. Focus: organize overwhelming raw footage, create rough cuts, remove dead air, and prepare for final polish in DaVinci Resolve.

**This skill is portable** — works on Windows, macOS, and Linux with FFmpeg + Claude.

**📦 Source Repository:** https://github.com/EmmaRenee/video-editing-tools

**📚 Additional Resources:**
- `SETUP.md` — Cross-platform installation and configuration guide
- `VideoEditing.psm1` — PowerShell module with 20+ video editing cmdlets
- `QUICKREF.md` — Cmdlet quick reference and common workflows

---

## When to Use

```
User mentions video editing?
  ├── Social media reels (Instagram/Facebook)
  ├── Racing footage or motorsports content
  ├── YouTube content or documentary series
  ├── "Too much footage", "overwhelmed", "need rough cut"
  ├── Caption, subtitle, or dead air removal
  └── Repetitive cutting tasks
```

**Use when:**
- Cutting racing footage into highlights or reels
- Converting long recordings into social media clips
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

**Edit, don't generate.** The value is compression — turning hours of raw footage into minutes of compelling content. AI helps find the good parts; you make the creative decisions.

---

## The Pipeline

```
Raw footage (hours)
  → FFmpeg (analyze, cut, normalize)
  → Claude (identify highlights, transcript, plan structure)
  → FFmpeg (create rough cut)
  → DaVinci Resolve (final polish, color, export)
```

---

## Layer 1: Analyze Footage (FFmpeg)

Before editing, understand what you have.

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

## Layer 2: Identify Highlights (Claude)

Claude helps you find the good parts without watching everything.

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

## Layer 3: Create Rough Cut (FFmpeg)

Once you know what to keep, let FFmpeg do the cutting.

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

## Layer 4: Social Media Formats

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

## Layer 5: Captions & Subtitles

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

## Layer 6: DaVinci Resolve Prep

### Generate EDL from Claude highlights

When Claude identifies highlights with timestamps, create an EDL for DaVinci:

**EDL format example:**
```
001  001  V     C        00:00:12:00 00:00:15:30 00:00:00:00 00:00:03:30
* | FROM CLIP NAME: race_raw.mp4
002  002  V     C        00:00:45:00 00:00:46:30 00:00:03:30 00:00:05:00
* | FROM CLIP NAME: race_raw.mp4
```

**Or use a Python script to generate EDL from JSON:**
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

*If you have these tools set up, they can automate parts of your workflow.*

### Eleven Labs - AI Voiceover

Generate AI narration from text, transcripts, or scripts.

```bash
# Generate from text (requires tools/elevenlabs/voiceover.py)
python tools/elevenlabs/voiceover.py --text "Welcome" --output intro.mp3
```

### HeyGen - AI Avatar Videos

Create AI avatar host segments without filming.

```bash
# Create avatar intro (requires tools/heygen/avatar.py)
python tools/heygen/avatar.py --text "Welcome!" --output intro.mp4
```

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
# If you have these scripts, use them. Otherwise, use the FFmpeg commands above.
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

### From raw racing footage to 3 reels

```bash
# 1. Analyze - find silence
ffmpeg -i race_raw.mp4 -af silencedetect=noise=-30dB:d=1 -f null - 2>&1 | findstr silence > silence_log.txt

# 2. Extract highlights (manually pick timestamps or use Claude analysis)
# Example: overtake at 12:30, incident at 45:20, podium at 1:23:10
ffmpeg -i race_raw.mp4 -ss 00:12:00 -to 00:13:30 -c copy overtake.mp4
ffmpeg -i race_raw.mp4 -ss 00:45:00 -to 00:46:45 -c copy incident.mp4
ffmpeg -i race_raw.mp4 -ss 01:22:30 -to 01:24:00 -c copy podium.mp4

# 3. Format for reels
ffmpeg -i overtake.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_overtake.mp4
ffmpeg -i incident.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_incident.mp4
ffmpeg -i podium.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel_podium.mp4
```

### Create captioned reel

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
| **FFmpeg** | Boring cuts, batch processing, format conversion | ✅ Cross-platform |
| **Claude** | Planning, highlights, transcripts, structure | ✅ Cross-platform |
| **Whisper** | Transcription | ✅ Cross-platform |
| **DaVinci Resolve** | Color grading, audio mix, final polish | Windows, Mac, Linux |
| **Descript** | Text-based editing (MCP via Claude) | ✅ Web/cloud |
| **Eleven Labs** | AI voice from text | ✅ API/Cloud |
| **HeyGen** | AI avatars | ✅ API/Cloud |
| **Gling** | AI highlight detection | Web UI only |

---

## Quick Reference: Common Commands

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
| Re-encoding unnecessarily | Use `-c copy` for simple cuts |
| Not normalizing audio | Levels vary wildly between clips |
| Skipping preview | Always watch rough cut before final polish |
| Starting in DaVinci with raw footage | Use FFmpeg to cut down first |
| Forgetting aspect ratio | Square video doesn't fit reels |

---

## Learning Path

**Start here:** Use FFmpeg to cut one highlight from your next race video.

**Next:** Use Claude to analyze a transcript and suggest 3 reel concepts.

**Then:** Create a rough cut entirely with FFmpeg, export to DaVinci for polish.

**Goal:** Spend 80% of your time on creative decisions in DaVinci, not on boring cutting.
