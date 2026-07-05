---
name: video-editing
description: Use when facing raw footage from a shoot (racing, interviews, events, documentary) that needs sorting, highlight discovery, or a rough cut in DaVinci Resolve — or when editing clips for social media, removing dead air, or adding captions. Handles shoots of 100s of GB: video, audio, and photos.
---

# Video Editing: Shoot → Rough Cut → Social

## Overview

AI-assisted post-production for real footage. The core workflow takes a
post-shoot dump (video + audio + photos, often 100s of GB) through a
**hybrid funnel**: cheap local analysis triages everything, Claude reviews
only the top candidates visually, and the result lands as a rough cut in
DaVinci Resolve Studio ready for the editor's final polish.

**Core principle: edit, don't generate.** The value is compression —
hours of raw footage into minutes of compelling content. Local ML finds
*candidates*; Claude's eye picks *keepers*; the editor makes the final
creative call in Resolve.

**📦 Source Repository:** https://github.com/EmmaRenee/video-editing-tools

Requirements: `pip install -e "src/python[analyze]"` (adds faster-whisper,
Silero VAD, PySceneDetect, OpenCLIP), plus `[resolve]` for OTIO export.
ffmpeg/ffprobe on PATH. DaVinci Resolve Studio for the direct API push.

---

## The Shoot Workflow (primary)

```
1 INGEST     videoedit shoot init/scan     → inventory + shoot.db
2 ANALYZE    videoedit shoot analyze       → scenes, speech, transcripts,
                                             CLIP tags, photo quality  (hours, unattended)
3 REVIEW     candidates + contact-sheets   → Claude LOOKS at the footage,
             review-export/import            emits verdict JSON
4 COMPOSE    timeline spec → shoot timeline → .otio + Resolve Studio push
             → shoot resolve-push
5 POLISH     editor takes over in Resolve; downstream layers below for
             social formats / captions
```

The shoot database (`<root>/.videoedit/shoot.db`) is the contract between
steps. Everything is resumable: interrupted analysis picks up where it
stopped, and re-running any step never repeats finished work.

### Step 1 — Ingest

```bash
videoedit shoot init "/path/to/shoot" --name "Spring GP Weekend"
videoedit shoot scan                    # parallel probe; idempotent
videoedit shoot status                  # counts, sizes, phase progress
videoedit shoot report                  # CSV/MD/JSON inventory
```

**Claude: after scanning, present the inventory summary, then interview
the editor** — event type, deliverables, people/subjects to look for,
anything special ("watch for the #42 red car"). Store the answers:

```bash
# answers become CLIP prompts and transcript keywords for the funnel
python3 -c "
from videoedit.shoot.db import ShootDB
db = ShootDB.find('.')
db.update_config(1, {
    'event_type': 'racing',
    'deliverables': ['3 reels', 'YouTube recap'],
    'people': ['Jane Doe'],
    'extra_prompts': ['a red race car with number 42'],
})"
```

NAS tip: point `--workspace` at local scratch so thumbnails and the DB
don't live over SMB. Keep `--workers` low (4) on network storage.

### Step 2 — Analyze (long-running, unattended)

```bash
videoedit shoot analyze --whisper-model small    # all phases
# or selectively:
videoedit shoot analyze --only scenes,vad
```

Phases: `scenes` (shot boundaries) → `vad` (speech ratio — the A/B-roll
signal) → `transcribe` (**only** assets with speech ratio > 0.15 hit
Whisper) → `embed` (CLIP tags + embeddings per frame) → `quality` (photo
blur/exposure) → `events` (optional PANNs audio tags) → `photos`
(grouping + dedupe + rank).

**Claude: run this in the background and poll `videoedit shoot status`.**
On a big shoot this takes hours — that's expected and fine.

### Step 3 — Review (Claude's judgment)

```bash
videoedit shoot candidates        # fuse signals → ranked A/B-roll candidates
videoedit shoot contact-sheets --top 60
videoedit shoot review-export     # → .videoedit/reviews/review_batch.json
```

**Claude: you MUST Read the contact-sheet images** (each grid = ~30
candidate thumbnails captioned `#id kind start-end`) **alongside the
transcript excerpts in review_batch.json. Never rank from filenames or
scores alone — the local scores only chose who got in front of you.**
When in/out points need refinement for a specific clip, request a dense
strip: `videoedit shoot contact-sheets --candidate 17`.

Then emit verdict JSON and import it:

```json
{"reviews": [
  {"candidate_id": 42, "rank": 1, "kind": "aroll",
   "in_s": 12.5, "out_s": 31.0, "story_beat": "climax",
   "tags": ["podium celebration"], "notes": "great reaction, clean audio"},
  {"candidate_id": 17, "kind": "reject", "notes": "out of focus"}
]}
```

- `kind`: `aroll` | `broll` | `reject`
- `story_beat`: `hook` | `context` | `rising` | `climax` | `resolution` | `color`
- `rank`, `in_s`, `out_s` required unless rejecting

```bash
videoedit shoot review-import verdicts.json --model claude-fable-5
```

**Photos:** same loop with `videoedit shoot review-export --photos` —
group sheets show `id=N rank KEEP?` captions; emit:

```json
{"groups": [
  {"group_id": 7, "keepers": [31, 34], "hero": 34, "rejects": [32, 33],
   "notes": "34 sharpest of the burst"}
]}
```

### Step 4 — Compose the rough cut

**Claude: draft a story-beat outline in chat first (hook → context →
rising → climax → resolution) using the reviewed candidates, and get the
editor's approval before building the timeline.** Then write the spec:

```json
{"timeline_name": "spring_gp_rough_v1", "fps": 29.97,
 "tracks": [
   {"index": 1, "clips": [
     {"candidate_id": 42, "asset_id": 3, "in_s": 12.5, "out_s": 31.0,
      "marker": {"color": "Blue", "note": "trim tail after cheer"}}
   ]},
   {"index": 2, "clips": [ ...B-roll overlay track... ]}
 ]}
```

Use Claude-refined `claude_in_s`/`claude_out_s` from the review, not the
original candidate bounds. `in_s`/`out_s` are seconds in the SOURCE clip.

```bash
videoedit shoot timeline rough_cut.json     # validates + writes .otio (always)
videoedit shoot resolve-push 1              # builds it inside Resolve Studio
```

`resolve-push` needs Resolve Studio **running** with external scripting
enabled (Preferences → System → General → External scripting: Local).
It creates bins (A-Roll/Interviews, B-Roll/Action…), imports reviewed
media with clip colors + keywords + Claude's notes as metadata, builds
the timeline with per-clip-fps frame math, and adds markers. If Resolve
isn't available, hand the editor the `.otio` path — Resolve 17+ imports
it natively (File → Import → Timeline). See `python/docs/resolve.md`.

### Claude behavior rules for shoot work

1. Interview the editor at ingest; persist answers to shoot config.
2. Long analysis runs go in the background; poll status, don't block.
3. Always look at contact sheets before ranking — signals shortlist,
   eyes decide.
4. Feed yourself transcript *excerpts* (already in review_batch.json),
   never whole transcripts.
5. Get outline approval in chat before composing a timeline.
6. The `.otio` is the durable artifact; the Resolve push is convenience.

---

## Per-file pipelines (secondary)

For single files, the YAML pipeline system still applies:

```bash
videoedit init reel --output my_reel.yaml
videoedit run my_reel.yaml --input footage.mp4
videoedit operations          # list available operations
videoedit tui                 # interactive builder
```

Presets: `reel` (9:16 audio-driven), `youtube` (16:9), `documentary`
(transcript-driven), `simple`, `ingest` (probe → scenes → VAD →
transcribe → embed on one file).

---

## Layer: Social Media Formats

```bash
# Vertical for Reels/TikTok (center crop, 9:16)
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reels_ready.mp4

# Square (1:1)
ffmpeg -i input.mp4 -vf "crop=ih:ih,scale=1080:1080" square.mp4

# Horizontal 1080p for YouTube
ffmpeg -i input.mp4 -vf "scale=-2:1080" youtube_ready.mp4

# Blurred-pad when going horizontal → vertical
ffmpeg -i input.mp4 -vf "split[s][b];[s]scale=1080:1920[bg];[b]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2" vertical_blurred.mp4
```

## Layer: Captions

```bash
# Transcribe (faster-whisper via pipeline, or CLI):
videoedit run - <<'EOF' --input clip.mp4
name: caption
steps:
  - {name: transcribe, operation: transcribe_whisper, params: {model: small}}
EOF

# Burn captions
ffmpeg -i video.mp4 -vf "subtitles=captions.srt:force_style='FontSize=28,BorderStyle=1'" output.mp4
```

## Layer: Manual FFmpeg reference

```bash
ffprobe -i video.mp4 -show_format -show_streams          # info
ffmpeg -i in.mp4 -ss 00:01:00 -to 00:02:00 -c copy out.mp4   # cut (no re-encode)
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4      # join
ffmpeg -i in.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11 out.mp4   # normalize audio
ffmpeg -i in.mp4 -af silencedetect=noise=-30dB:d=1 -f null - # find dead air
ffmpeg -i in.mp4 -vf "scale=960:-2" -c:v libx264 -preset ultrafast -crf 28 proxy.mp4
ffmpeg -i in.mp4 -c:v prores_ks -profile:v 3 -c:a pcm_s16le for_davinci.mov
```

---

## Optional: Cloud AI Tools

- **Eleven Labs** (`python/elevenlabs/voiceover.py`) — AI narration from text.
- **HeyGen** (`python/heygen/avatar.py`) — AI avatar segments.
- **Descript MCP** — text-based editing via Claude connectors
  (`https://api.descript.com/v2/mcp`): "Import race_footage.mp4,
  remove filler words, add Studio Sound."

---

## Tool Comparison

| Tool | Best For |
|------|----------|
| **shoot pipeline** | Whole-shoot triage, highlight discovery, rough cuts |
| **FFmpeg** | Cuts, batch processing, format conversion |
| **faster-whisper** | Transcription (2-4× faster than openai-whisper) |
| **Claude** | Visual review, ranking, story structure, timeline specs |
| **DaVinci Resolve** | Final polish: color, audio mix, export |
| **Descript** | Text-based editing (MCP) |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Ranking clips without reading the contact sheets | Sheets exist so Claude can *look*; signals only shortlist |
| Transcribing everything | VAD gate first — most B-roll has no speech |
| Full-file hashing over NAS | quick_hash covers change detection |
| Re-encoding for simple cuts | `-c copy` |
| Building timelines with timeline-fps frame math | source frames use each clip's own fps |
| Starting in Resolve with raw footage | Funnel first; Resolve gets reviewed material only |
