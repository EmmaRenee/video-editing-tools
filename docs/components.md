# Component Reference

Current package version: `0.5.0`.

This page maps the supported repository components. It documents the tracked, releaseable surface of the project; local experiments should be promoted here only after they are committed with tests and user-facing docs.

## Python Package

`src/python/videoedit/` is the installable package behind the `videoedit` CLI.

| Area | Main Modules | Purpose |
|------|--------------|---------|
| Inventory and rating | `inventory.py`, `rating.py`, `config.py`, `models.py` | Scan footage, collect metadata, analyze deterministic signals, score candidate clips, and write JSON-first artifacts. |
| Calibration | `calibration.py` | Compare rated candidates against human annotations, report misses/false positives, tune scoring proposals, and compare calibration runs. |
| Review and rough cuts | `review.py`, `review_tui.py`, `roughcut.py` | Generate review assets/contact sheets, apply decisions, plan sequencing, and assemble rough cuts. |
| Handoff | `edl.py`, `selections.py` | Normalize selection JSON and export EDL/XML/M3U/FFmpeg-friendly handoff files. |
| Signals | `advanced.py`, `signals.py`, `transcript.py` | Load and validate optional object/OCR/face/person/motorsports/topic artifacts and fuse them into scoring. |
| AI assistance | `ai.py`, `learning.py` | Optional OpenCLIP frame scoring, missed-moment review, local clip judgment handoff, review datasets, and learned scoring. |
| Content planning | `content.py`, `reports.py` | Build content maps, quote mining reports, and repeatable series plans from rated footage. |
| Captions and delivery | `captions.py` | Convert SRT to ASS styles and burn captions through FFmpeg. |
| Modules and pipelines | `modules.py`, `operations.py`, `pipeline.py`, `presets.py`, `simple_yaml.py` | Feature-module discovery, operation registry, preset generation, YAML planning, validation, and execution. |
| Cloud handoff | `cloud.py` | Credential-safe cloud adapter metadata, diagnostics, and `cloud_job.json` planning for external execution. |
| Diagnostics and scaffolding | `diagnostics.py`, `scaffold.py`, `timecode.py`, `ffmpeg.py` | Dependency checks, project scaffolding, timecode conversion, and FFmpeg command wrappers. |

## CLI Surface

The primary command is installed from `src/python/pyproject.toml`:

```bash
videoedit doctor
videoedit modules list
videoedit operations
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit roughcut plan approved.json --output roughcut_plan.json
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit export-edl approved.json --output edl/
```

Specialized command groups include:

| Group | Purpose |
|-------|---------|
| `videoedit calibrate ...` | Annotation initialization, decision conversion, evaluation, tuning, comparison, and safe config application. |
| `videoedit signals ...` | Optional object, OCR, face/person, motorsports, topic, and artifact validation commands. |
| `videoedit ai ...` | Optional local/open-source AI scoring, missed-moment review, clip judging, datasets, and learned scoring. |
| `videoedit modules ...` | Enable/disable optional modules, run diagnostics, and scaffold community modules. |
| `videoedit captions ...` / `videoedit burn-captions ...` | Caption style discovery and caption burning. |
| `videoedit series ...`, `content-map`, `quote-mining` | Editorial planning and content-report outputs. |
| `videoedit cloud ...` | Adapter listing, no-network diagnostics, and local `cloud_job.json` planning. |
| `videoedit init`, `validate`, `plan`, `run` | Preset/YAML pipeline generation and execution. |

## Compatibility Scripts

These remain for direct local use and backward compatibility:

| Script | Purpose |
|--------|---------|
| `src/python/rate_footage.py` | V1-compatible wrapper for rating footage. |
| `src/python/inventory.py` | Standalone inventory wrapper. |
| `src/python/auto_caption.py` | Standalone caption-burning wrapper. |
| `src/python/video_start.py` | Project folder initializer retained for older workflows. |
| `src/python/davinci/generate-edl.py` | Legacy DaVinci EDL helper. |
| `src/python/canva/design.py` | Optional graphics automation helper. |

## PowerShell Module

`src/powershell/VideoEditing.psm1` provides Windows-friendly FFmpeg helper cmdlets for metadata, conversion, clip extraction, concatenation, silence removal, audio normalization, captions, Whisper transcription, and project scaffolding. See `src/QUICKREF.md`.

## Skills And Docs

| File | Role |
|------|------|
| `src/SKILL.md` | Agent-facing workflow instructions for using `videoedit` first and FFmpeg manually as fallback. |
| `INSTALL.md` | Canonical install guide for Python, FFmpeg, YOLO/OpenCV, OpenCLIP, cloud extras, skills, and DaVinci handoff. |
| `src/python/README.md` | Package, CLI, preset, artifact, calibration, review, AI, and module documentation. |
| `docs/community-modules.md` | Contract for community extension packages and entry points. |
| `docs/release.md` | Versioning, build, CI, GitHub release, PyPI, and artifact-hygiene checklist. |
| `CHANGELOG.md` | Package history and current release notes. |

## Core Artifacts

The package stays JSON-first. Common artifacts include:

- `inventory.json`, `inventory.csv`, `inventory.md`
- `ratings.json`
- `candidates.csv`
- `review.md`, `review.html`, `review_assets.json`, `review_decisions.json`
- `approved.json`
- `roughcut_plan.json`, `roughcut_report.md`
- `selections/*.json`
- `calibration_report.json`, `calibration_report.md`
- `visual_objects.json`, `ocr_signage.json`, `face_person_presence.json`, `motorsports_events.json`, `topic_clusters.json`, `ai_frame_scores.json`
- `cloud_job.json`

## Versioning

The canonical runtime version is `src/python/videoedit/_version.py`. `videoedit.__version__` exports the same value, and `src/python/pyproject.toml` reads it dynamically for wheel/sdist metadata. README and install docs should refer to the same package version.
