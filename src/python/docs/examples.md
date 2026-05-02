# Pipeline Examples

Common workflow examples for the videoedit pipeline system.

---

## Example 1: Instagram Reel from Raw Footage

Create a 9:16 vertical reel with highlights and captions.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("instagram_reel", "Instagram Reel from racing footage")

# 1. Transcribe audio
p.add("transcribe_whisper", name="transcribe", model="small")

# 2. Find exciting moments (transcript-based)
p.add("detect_highlights_transcript", name="detect",
      keywords=["wow", "amazing", "incredible", "oh my god"],
      max_clips=5,
      input_from="transcribe")

# 3. Extract clips with padding
p.add("extract_segments", name="extract",
      padding=0.5,
      input_from="detect")

# 4. Format for 9:16 vertical
p.add("format_video", name="format",
      aspect_ratio="9:16",
      resolution="1080p",
      input_from="extract")

# 5. Burn captions with racing style
p.add("burn_captions", name="captions",
      style="automotive_racing",
      input_from="format")

# Run
runner = Runner(p)
result = runner.run("raw_footage.mp4", "output/")
```

### YAML

```yaml
name: "Instagram Reel"
description: "Create 9:16 reel with highlights and captions"

steps:
  - name: transcribe
    operation: transcribe_whisper
    params:
      model: small

  - name: detect
    operation: detect_highlights_transcript
    input: transcribe
    params:
      keywords: ["wow", "amazing", "incredible", "oh my god"]
      max_clips: 5

  - name: extract
    operation: extract_segments
    input: detect
    params:
      padding: 0.5

  - name: format
    operation: format_video
    params:
      aspect_ratio: "9:16"
      resolution: "1080p"

  - name: captions
    operation: burn_captions
    params:
      style: automotive_racing
```

### CLI

```bash
# Use the preset
videoedit init reel --output my_reel.yaml
videoedit run my_reel.yaml --input footage.mp4 --output output/
```

---

## Example 2: YouTube Highlights

Extract highlights for horizontal video format.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("youtube_highlights")

# Use audio spike detection (faster than transcript)
p.add("detect_highlights_audio",
      threshold=-20,
      max_clips=10)

p.add("extract_segments", padding=1.0)

p.add("format_video",
      aspect_ratio="16:9",
      resolution="1080p")

runner = Runner(p)
result = runner.run("long_video.mp4", "output/")
```

### YAML

```yaml
name: "YouTube Highlights"
description: "Extract highlights for 16:9 horizontal format"

steps:
  - operation: detect_highlights_audio
    params:
      threshold: -20
      max_clips: 10

  - operation: extract_segments
    params:
      padding: 1.0

  - operation: format_video
    params:
      aspect_ratio: "16:9"
```

---

## Example 3: DaVinci Resolve Export

Generate an EDL file for further editing in DaVinci.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("davinci_export")

p.add("transcribe_whisper", model="small")

p.add("detect_highlights_transcript",
      keywords=["important", "key point", "remember"],
      max_clips=20)

# Generate EDL instead of extracting clips
p.add("generate_edl",
      fps=30,
      include_transcript=True)

runner = Runner(p)
result = runner.run("interview.mp4", "output/")
```

### YAML

```yaml
name: "DaVinci Export"
description: "Generate EDL for further editing"

steps:
  - operation: transcribe_whisper
    params:
      model: small

  - operation: detect_highlights_transcript
    params:
      keywords: ["important", "key point", "remember"]
      max_clips: 20

  - operation: generate_edl
    params:
      fps: 30
      include_transcript: true
```

---

## Example 4: Concatenate with Transitions

Join multiple clips with smooth transitions.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("montage")

# Assuming you already have clips from somewhere
# Or use extract_segments first
context = {"clips": ["clip1.mp4", "clip2.mp4", "clip3.mp4"]}

p.add("add_crossfades",
      duration=0.5,
      transition="dissolve")

# Or use simple_crossfade for exactly 2 clips
# p.add("simple_crossfade", duration=1.0)

runner = Runner(p)
result = runner.run("clip1.mp4", "output/")
```

### YAML

```yaml
name: "Montage with Transitions"
description: "Join clips with dissolve transitions"

steps:
  - operation: add_crossfades
    params:
      duration: 0.5
      transition: dissolve
```

---

## Example 5: Audio Normalization

Fix audio levels for consistent loudness.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("normalize_audio")

p.add("normalize_audio",
      preset="youtube")  # -14 LUFS for YouTube

runner = Runner(p)
result = runner.run("varying_audio.mp4", "output/")
```

### YAML

```yaml
name: "Normalize Audio"
description: "Fix audio levels to YouTube standard"

steps:
  - operation: normalize_audio
    params:
      preset: youtube
```

---

## Example 6: Full Documentary Workflow

Complete pipeline for documentary rough cut.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("documentary_rough_cut")

# 1. Transcribe all footage
p.add("transcribe_whisper", name="transcribe", model="base")

# 2. Find key moments based on transcript
p.add("detect_highlights_transcript", name="detect",
      keywords=["important", "crucial", "key", "significant"],
      max_clips=30,
      input_from="transcribe")

# 3. Extract with longer padding for context
p.add("extract_segments", name="extract",
      padding=2.0,
      input_from="detect")

# 4. Format for documentary (16:9)
p.add("format_video", name="format",
      aspect_ratio="16:9",
      resolution="1080p",
      input_from="extract")

# 5. Create EDL for fine-tuning in DaVinci
p.add("generate_edl", name="edl",
      fps=24,
      input_from="detect")

runner = Runner(p)
result = runner.run("raw_interview.mp4", "output/")
```

### YAML

```yaml
name: "Documentary Rough Cut"
description: "Extract key moments and prepare for editing"

steps:
  - name: transcribe
    operation: transcribe_whisper
    params:
      model: base

  - name: detect
    operation: detect_highlights_transcript
    input: transcribe
    params:
      keywords: ["important", "crucial", "key", "significant"]
      max_clips: 30
      min_duration: 5.0

  - name: extract
    operation: extract_segments
    input: detect
    params:
      padding: 2.0

  - name: format
    operation: format_video
    params:
      aspect_ratio: "16:9"
      resolution: "1080p"

  - name: edl
    operation: generate_edl
    params:
      fps: 24
```

---

## Example 7: Custom Caption Style

Create custom styled captions.

### Python API

```python
from videoedit import Pipeline, Runner

p = Pipeline("custom_captions")

p.add("transcribe_whisper", model="small")

# Use style overrides for custom look
p.add("burn_captions",
      style="minimal",
      style_overrides={
          "font": "Helvetica Bold",
          "fontsize": 32,
          "fontcolor": "yellow",
          "marginv": 100
      })

runner = Runner(p)
result = runner.run("video.mp4", "output/")
```

---

## Example 8: Batch Processing

Process multiple videos with the same pipeline.

```python
from pathlib import Path
from videoedit import Pipeline, Runner

# Define pipeline once
p = Pipeline("batch_reel")
p.add("detect_highlights_audio", threshold=-25, max_clips=3)
p.add("extract_segments", padding=0.5)
p.add("format_video", aspect_ratio="9:16")
p.add("burn_captions", style="automotive_racing")

runner = Runner(p)

# Process all videos in directory
input_dir = Path("raw_footage/")
output_dir = Path("output/")

for video_file in input_dir.glob("*.mp4"):
    print(f"Processing {video_file.name}...")
    try:
        result = runner.run(video_file, output_dir / video_file.stem)
        print(f"  ✓ Complete")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
```

---

## Tips

1. **Start with presets** - Use `videoedit init` to generate from presets
2. **Use TUI for building** - `videoedit tui` provides visual pipeline builder
3. **Test each step** - Run with small clips first
4. **Check intermediate outputs** - Look in the work directory for files
5. **Adjust thresholds** - Audio detection varies by content type
6. **Use appropriate models** - `tiny` is fast, `medium` is accurate
7. **Customize styles** - Override caption styles for your brand
