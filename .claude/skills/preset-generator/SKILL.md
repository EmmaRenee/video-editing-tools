---
name: preset-generator
description: Generate custom videoedit pipeline presets from user requirements
disable-model-invocation: true
---

# Preset Generator

Creates custom `videoedit` pipeline YAML files for social media formats, multi-stage workflows, and batch processing.

## Usage

```
preset-generator --goal "create 60-second TikTok with captions" --output tiktok_captions.yaml
```

Or use the skill directly:

```
Use preset-generator to create a TikTok preset with captions and save to tiktok_captions.yaml
```

## Supported Presets

### Social Media Formats

| Platform | Aspect Ratio | Duration | Features |
|----------|-------------|----------|----------|
| **TikTok** | 9:16 vertical | 60 seconds | Captions, auto-crop |
| **YouTube Shorts** | 9:16 vertical | 59 seconds | Captions, auto-crop |
| **Instagram Reel** | 9:16 vertical | 90 seconds | Captions, auto-crop |
| **Snapchat** | 9:16 vertical | 60 seconds | Captions, auto-crop |
| **YouTube Horizontal** | 16:9 horizontal | Unlimited | HD output |

### Workflow Types

- **simple**: Audio detection → extract clips
- **transcribed**: Whisper → keyword detection → extract → format
- **captioned**: Extract → format → burn captions
- **batch**: Multi-file processing with concat
- **documentary**: Full pipeline with transcription

## Template Structure

Generated YAML follows this structure:

```yaml
name: Custom Preset
description: Generated from user requirements
steps:
  - name: step_name
    operation: operation_name
    params: {...}
    input: previous_step_name  # Optional: chains to previous step output
```

## Operation Parameters

### detect_highlights_audio
- `threshold`: dB threshold for audio spikes (default: -25)
- `min_duration`: Minimum clip duration in seconds (default: 2.0)
- `max_clips`: Maximum number of clips (default: 10)
- `padding`: Padding around highlights in seconds (default: 0.5)

### extract_segments
- `padding`: Padding around timestamps (default: 0.5)
- `codec`: Video codec (default: copy)
- `preset`: Encoding preset (default: ultrafast)
- `crf`: Quality factor (default: 23)

### format_video
- `aspect_ratio`: Target ratio (9:16, 16:9, 1:1)
- `resolution`: Target resolution (1080x1920, 1920x1080, 1080x1080)
- `crop`: Crop mode (center, smart)

### burn_captions
- `style`: Caption style (automotive_racing, clean_tech, social_mobile, minimal)
- `style_overrides`: Custom style parameters

### transcribe_whisper
- `model`: Whisper model (tiny, base, small, medium, large)
- `language`: Language code (en, es, fr, etc.)
- `output_format`: Format (srt, vtt, json)

## Example Usage

### Create a TikTok preset with captions

Input:
```
Generate a preset for TikTok with auto-captions, 60-second clips, and audio detection
```

Output:
```yaml
name: TikTok with Captions
description: 60-second vertical clips with burned-in captions
steps:
  - name: detect_highlights
    operation: detect_highlights_audio
    params:
      threshold: -25
      max_clips: 5
      min_duration: 3.0
      padding: 0.3
  - name: transcribe
    operation: transcribe_whisper
    params:
      model: small
      output_format: srt
  - name: extract_clips
    operation: extract_segments
    input: detect_highlights
    params:
      padding: 0.3
      codec: libx264
      preset: fast
  - name: format_vertical
    operation: format_video
    input: extract_clips
    params:
      aspect_ratio: 9:16
      resolution: 1080x1920
      crop: center
  - name: add_captions
    operation: burn_captions
    input: format_vertical
    params:
      style: social_mobile
```

### Create a YouTube horizontal preset

Input:
```
Generate a YouTube preset with 16:9 horizontal format, no captions
```

Output:
```yaml
name: YouTube Horizontal
description: 16:9 horizontal highlights for YouTube
steps:
  - name: detect_highlights
    operation: detect_highlights_audio
    params:
      threshold: -20
      max_clips: 10
      padding: 1.0
  - name: extract_clips
    operation: extract_segments
    input: detect_highlights
    params:
      padding: 1.0
  - name: format_horizontal
    operation: format_video
    input: extract_clips
    params:
      aspect_ratio: 16:9
      resolution: 1920x1080
```

## Output Usage

Generated presets can be used with the videoedit CLI:

```bash
# Run the generated preset
videoedit run my_preset.yaml --input footage.mp4 --output output/

# Or validate first
videoedit validate my_preset.yaml
```

## Quick Generation Commands

```bash
# TikTok preset
preset-generator --platform tiktok --with-captions --output tiktok.yaml

# YouTube preset
preset-generator --platform youtube --output youtube.yaml

# Instagram Reel preset
preset-generator --platform instagram --output reel.yaml

# Custom preset
preset-generator --goal "create 30-second clips with automotive captions" --output custom.yaml
```
