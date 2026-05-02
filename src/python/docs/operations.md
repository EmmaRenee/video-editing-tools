# Operations Reference

Complete reference for all pipeline operations.

---

## TranscribeWhisper

Transcribe video using OpenAI's Whisper AI model.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | string | "small" | Whisper model size: tiny, base, small, medium, large |

### Input/Output

- **Input**: Video file
- **Output**: SRT, VTT, JSON transcript files

### Example

```python
p.add("transcribe_whisper", model="small")
```

```yaml
steps:
  - name: transcribe
    operation: transcribe_whisper
    params:
      model: small
```

---

## DetectHighlightsAudio

Find highlight moments using audio spike detection.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `threshold` | number | -25 | Audio threshold in dB |
| `max_clips` | number | 10 | Maximum number of clips to extract |
| `min_duration` | number | 2.0 | Minimum clip length in seconds |

### Input/Output

- **Input**: Video file
- **Output**: Segment timestamps (JSON)

### Example

```python
p.add("detect_highlights_audio", threshold=-25, max_clips=5)
```

---

## DetectHighlightsTranscript

Find highlights using transcript keyword analysis.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `keywords` | list | [excitement words] | Keywords to search for |
| `max_clips` | number | 10 | Maximum clips to extract |
| `min_duration` | number | 2.0 | Minimum clip length |
| `context_window` | number | 3.0 | Seconds of context around matches |
| `use_questions` | boolean | false | Also detect questions |

### Input/Output

- **Input**: SRT transcript file
- **Output**: Segment timestamps (JSON)

### Example

```python
p.add("detect_highlights_transcript",
      keywords=["wow", "amazing", "incredible"],
      max_clips=5)
```

---

## ExtractSegments

Extract video clips from timestamp segments.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `padding` | number | 0.5 | Seconds of padding before/after each segment |

### Input/Output

- **Input**: Video file + segments from context
- **Output**: Individual clip files

### Example

```python
p.add("extract_segments", padding=1.0)
```

---

## FormatVideo

Resize, crop, or pad video to target format.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `aspect_ratio` | string | "16:9" | Target ratio: 9:16, 16:9, 1:1 |
| `resolution` | string | "1080p" | Output resolution: 1080p, 720p, 480p |

### Input/Output

- **Input**: Video file
- **Output**: Formatted video file

### Example

```python
p.add("format_video", aspect_ratio="9:16", resolution="1080p")
```

---

## BurnCaptions

Burn SRT subtitles into video with styling.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `srt_file` | string | From context | Path to SRT file |
| `style` | string | "automotive_racing" | Caption style preset |
| `style_overrides` | dict | {} | Override specific style parameters |

### Caption Styles

- `automotive_racing`: High contrast, racing content
- `clean_tech`: Minimalist, tech content
- `social_mobile`: Large text, mobile viewing
- `vin_wiki`: Documentary style
- `minimal`: Simple and clean

### Input/Output

- **Input**: Video file + SRT file
- **Output**: Video with burned-in captions

### Example

```python
p.add("burn_captions", style="automotive_racing")
```

---

## GenerateEdl

Create Edit Decision List (EDL) for DaVinci Resolve.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fps` | number | 30 | Frame rate for timecode |
| `reel_name` | string | "CLIP" | Reel name in EDL |
| `include_transcript` | boolean | true | Include transcript as comments |

### Input/Output

- **Input**: Segment data
- **Output**: EDL file

### Example

```python
p.add("generate_edl", fps=30)
```

---

## ConcatenateVideos

Combine multiple video clips into one.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `clips` | list | From context | List of clip paths |
| `output_name` | string | "concatenated.mp4" | Output file name |
| `reencode` | boolean | false | Force re-encoding (mixed formats) |

### Input/Output

- **Input**: Multiple video clips
- **Output**: Single combined video file

### Example

```python
p.add("concatenate_videos", reencode=False)
```

---

## AddCrossfades

Add crossfade transitions between clips.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `clips` | list | From context | List of clip paths |
| `duration` | number | 0.5 | Transition duration in seconds |
| `transition` | string | "fade" | Transition type |
| `output_name` | string | "with_transitions.mp4" | Output file name |

### Transition Types

- `fade`: Simple fade
- `dissolve`: Dissolve transition
- `wipeleft`: Wipe right to left
- `wiperight`: Wipe left to right
- `wipeup`: Wipe bottom to top
- `wipedown`: Wipe top to bottom

### Input/Output

- **Input**: Multiple video clips
- **Output**: Video with transitions

### Example

```python
p.add("add_crossfades", duration=0.5, transition="fade")
```

### SimpleCrossfade

For two clips only:

```python
p.add("simple_crossfade", duration=1.0)
```

---

## NormalizeAudio

Normalize audio to target loudness level.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target_level` | number | -16 | Target LUFS (loudness) |
| `true_peak` | number | -1.5 | Max true peak in dBTP |
| `lra` | number | 11.0 | Loudness range in LU |
| `preset` | string | null | Named preset (ebu, atsc, podcast, youtube, spotify) |

### Presets

- `ebu`: -16 LUFS (Europe standard)
- `atsc`: -24 LUFS (US standard)
- `podcast`: -16 LUFS
- `youtube`: -14 LUFS
- `spotify`: -14 LUFS

### Input/Output

- **Input**: Video file
- **Output**: Video with normalized audio

### Example

```python
p.add("normalize_audio", preset="youtube")
# or
p.add("normalize_audio", target_level=-14)
```

---

## Context Passing

Operations pass data to each other through a shared context:

```python
# transcribe_whisper puts transcript in context
context["transcript_file"] = "video.srt"
context["transcript_segments"] = [...]

# detect_highlights_transcript reads from context
# and puts segments in context
context["segments"] = [...]

# extract_segments reads segments from context
# and puts clips in context
context["clips"] = ["clip1.mp4", "clip2.mp4", ...]
```

Use `input: step_name` in YAML to specify which step's output to use:

```yaml
steps:
  - name: transcribe
    operation: transcribe_whisper

  - name: detect
    operation: detect_highlights_transcript
    input: transcribe  # Uses transcribe output
```
