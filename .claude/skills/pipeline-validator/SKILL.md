---
name: pipeline-validator
description: Validate videoedit pipeline YAML files before execution
---

# Pipeline Validator

Validates `videoedit` pipeline YAML files ensuring operation existence, required parameters, valid paths, and proper step dependencies.

## Usage

Provide a pipeline file path to validate:

```
validate reel.yaml
```

Or use the skill directly:

```
Use pipeline-validator to check src/python/videoedit/presets/reel.yaml
```

## Validation Checks

1. **YAML Syntax**: Valid YAML structure
2. **Operation Registry**: All operations exist in videoedit/operations/
3. **Parameter Schema**: Params match operation signatures
4. **Step Dependencies**: `input` references point to existing steps
5. **No Circular Dependencies**: Step graph is acyclic
6. **Path Validation**: Input/output paths are syntactically valid

## Operations Registry

Valid operations (from videoedit/operations/):

| Operation | Description | Key Parameters |
|-----------|-------------|-----------------|
| transcribe_whisper | Whisper AI speech-to-text | model, language, output_format |
| detect_highlights_audio | Audio spike detection | threshold, max_clips, padding |
| detect_highlights_transcript | Keyword-based transcript analysis | keywords, min_duration |
| extract_segments | Clip extraction from timestamps | segments, padding, codec |
| format_video | Resize/crop/pad videos | aspect_ratio, resolution |
| burn_captions | Subtitle burning | srt_file, style |
| generate_edl | DaVinci Resolve EDL creation | fps, reel_name |
| concatenate_videos | Combine multiple clips | clips, output_name |
| add_crossfades | Transition effects between clips | duration, transition |
| normalize_audio | EBU R128 loudness normalization | target_level, preset |
| probe_media | Media metadata via ffprobe/EXIF | (none) |
| scene_detect | Shot boundaries (PySceneDetect) | threshold, min_scene_len_s |
| vad_speech | Speech segmentation (Silero VAD) | (none) |
| embed_frames | CLIP embeddings + zero-shot tags | interval_s, model, thumb_width |
| quality_frames | Blur/exposure metrics | (none) |
| events_audio | Audio event tags (PANNs, optional) | window_s, min_prob |
| contact_sheet | Thumbnail grid for review | cols, rows, title |

## Implementation

Uses existing videoedit validation:

```bash
videoedit validate pipeline.yaml
```

Or via Python:

```python
from videoedit.pipeline import Pipeline
import yaml

with open('pipeline.yaml') as f:
    data = yaml.safe_load(f)
pipeline = Pipeline.from_dict(data)  # Raises if invalid
```

## Error Handling

Returns structured errors:

| Error Type | Cause | Resolution |
|-------------|-------|------------|
| **YAMLError** | Invalid YAML syntax | Fix YAML formatting |
| **ValueError** | Unknown operation or invalid parameter | Check operation name and params |
| **RuntimeError** | Circular dependency or missing step | Fix step input references |
| **FileNotFoundError** | Pipeline file not found | Provide valid file path |

## Example Pipeline Structure

```yaml
name: My Custom Pipeline
description: Pipeline description
steps:
  - name: detect_highlights
    operation: detect_highlights_audio
    params:
      threshold: -25
      max_clips: 5
  - name: extract_clips
    operation: extract_segments
    input: detect_highlights  # References previous step
    params:
      padding: 0.5
  - name: format_vertical
    operation: format_video
    input: extract_clips
    params:
      aspect_ratio: 9:16
      resolution: 1080x1920
```

## Preset Templates

Built-in presets available:

- **reel**: Instagram Reel from Raw (9:16 vertical)
- **youtube**: YouTube Highlights (16:9 horizontal)
- **simple**: Simple Clip Extract (audio detection only)
- **documentary**: Transcribe and extract key moments

Generate a new preset:

```bash
videoedit init reel --output my_reel.yaml
```
