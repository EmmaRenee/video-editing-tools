# Videoedit User Guide

Current package version: `0.5.0`.

This guide is the user-facing map for the `videoedit` toolkit. It explains what each major feature does, when to use it, the commands to run, and the artifacts to expect. For install steps, start with [INSTALL.md](../INSTALL.md). For maintainer ownership and module internals, see [docs/components.md](components.md).

## The Workflow In One Pass

Use this path when you have raw footage and want a reviewable rough cut:

```bash
videoedit doctor
videoedit modules list
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit review-tui review/review_assets.json --decisions review/review_decisions.json
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence review_order --target-duration 90 --format reel
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit export-edl approved.json --output edl/
videoedit extract-segments approved.json --output clips/
```

The default pipeline is deterministic and local-first. FFmpeg and ffprobe are the base requirements. Whisper, YOLO, OpenCV, Tesseract, OpenCLIP, Torch, local VLM judges, and cloud adapters are optional layers.

## Core Concepts

`videoedit` works by turning raw video into reusable JSON artifacts:

- Inventory: what media exists and what metadata ffprobe can read.
- Signals: scene changes, audio spikes, silence, transcript hits, objects, OCR text, face/person presence, motorsports events, topic clusters, AI frame scores, and learned scoring features.
- Candidates: scored clip windows with labels, reasons, and recommended actions.
- Review decisions: human approval, rejection, notes, and ordering.
- Selections: clips ready for extraction, EDL/XML/M3U handoff, or rough-cut assembly.
- Calibration: comparison between machine picks and human ground truth.

The tool does not auto-replace editorial judgment. It narrows the footage, explains why each candidate was selected, then lets a person approve, reject, tune, and assemble.

## Install And Preflight

Use [INSTALL.md](../INSTALL.md) for platform-specific setup. After install, run:

```bash
videoedit doctor
videoedit doctor --json
videoedit operations
videoedit modules list
videoedit modules doctor
```

What these do:

- `videoedit doctor` checks required tools such as FFmpeg and ffprobe, plus optional providers.
- `videoedit operations` lists composable pipeline operations that are currently enabled.
- `videoedit modules list` shows feature modules and whether they are enabled, disabled, or unavailable.
- `videoedit modules doctor` reports missing optional dependencies by module.

## Inventory

Use inventory when you need a catalog of footage before rating or editing.

```bash
videoedit inventory footage/ --output analysis/
```

Outputs:

- `inventory.json`
- `inventory.csv`
- `inventory.md`

Inventory includes file paths, filenames, duration, resolution, codecs, frame rate, audio presence, and probe metadata where available.

## Rating And Candidate Selection

Use rating when you want the tool to find likely usable or exciting moments.

```bash
videoedit rate footage/ --output analysis/
```

Useful options:

```bash
videoedit rate footage/ --output analysis/ --transcript auto
videoedit rate footage/ --output analysis/ --config configs/scoring.json
videoedit rate footage/ --output analysis/ --max-candidates 100
videoedit rate footage/ --output analysis/ --min-select-score 70 --min-review-score 45
videoedit rate footage/ --output analysis/ --window-pre-roll 3 --window-post-roll 12
videoedit rate footage/ --output analysis/ --no-cache
```

Rating outputs:

- `inventory.json`
- `ratings.json`
- `candidates.csv`
- `review.md`
- `review.html`
- `selections/*.json`

How scoring works:

- Metadata and technical quality create a base score.
- Scene changes help identify visual activity.
- Silence and non-silence windows help avoid dead air.
- Audio spikes identify energetic moments.
- Optional transcripts add topic and quote signals.
- Optional signal artifacts add object, OCR, face/person, motorsports, topic, AI, and learned-score signals.
- Each candidate gets `labels`, `signals`, `reasons`, `score`, and an `action` such as `select`, `review`, `broll`, `cut`, or `reject`.

Compatibility wrapper:

```bash
python src/python/rate_footage.py footage/ --output analysis/
```

## Review

Use review when you want to inspect candidates before assembly.

```bash
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit review-assets analysis/ratings.json --output review/ --calibration calibration/calibration_report.json --proxy
videoedit review-assets analysis/ratings.json --output review_ai/ --ai-clip-judgments analysis/ai_clip_judgments.json
```

Outputs:

- `review_assets.json`
- `contact_sheet.html`
- thumbnails
- optional proxy clips
- downloadable `review_decisions.json`

The HTML contact sheet supports filtering, sorting, decision edits, notes, ordering, bulk actions, and export of review decisions. Decision changes are saved in browser local storage until you download or copy the decisions JSON.

Terminal review:

```bash
videoedit review-tui review/review_assets.json --decisions review/review_decisions.json
```

Use the terminal review when you want a keyboard-driven pass over the same manifest and decisions schema.

## Approval

Use approval to turn reviewed candidates into an edit-ready selection file.

```bash
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
```

Other approval modes:

```bash
videoedit approve analysis/ratings.json --output approved.json --actions select,review
videoedit approve analysis/ratings.json --output approved.json --min-score 65
videoedit approve analysis/ratings.json --output approved.json --ids clip_0001,clip_0007
```

Output:

- `approved.json`

`approved.json` is the main bridge from review into rough cuts, segment extraction, and EDL/XML/M3U handoff.

## Rough-Cut Planning And Assembly

Use rough-cut planning when you want deterministic sequencing before rendering.

```bash
videoedit roughcut plan approved.json --output roughcut_plan.json
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence score --target-duration 90 --format reel --render-mode render
videoedit roughcut plan approved.json --output roughcut_plan.json --sequence diversified --handles 1.5 --max-clips 20 --report-output roughcut_report.md
```

Sequencing modes:

- `review_order`: preserve human review order.
- `score`: highest-ranked clips first.
- `source_order`: preserve source/time order.
- `diversified`: reduce repetition across sources and labels.

Common outputs:

- `roughcut_plan.json`
- `roughcut_report.md`

Assemble the rough cut:

```bash
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4
videoedit assemble approved.json --output rough_cut.mp4
```

`assemble` can use copy-based concatenation when compatible, or rendered output when the plan requests it.

## Handoff And Segment Extraction

Use handoff when you want clips or timeline metadata for DaVinci Resolve, FFmpeg, or another editor.

```bash
videoedit export-edl approved.json --output edl/
videoedit export-edl analysis/selections/*.json --output edl/ --fps 29.97
videoedit extract-segments approved.json --output clips/
videoedit extract-segments analysis/selections/*.json --output clips/
```

Supported selection input shapes include standard `videoedit` selections and Drive-style soundbite JSON:

```json
{
  "project": "Interview Soundbites",
  "fps": 30,
  "clips": [
    {
      "source": "interview.mp4",
      "start": "00:00:30",
      "end": "00:01:00",
      "label": "intro_quote"
    }
  ]
}
```

FPS precedence is explicit `--fps`, then JSON `fps`, then `30`.

## Calibration

Use calibration when you have human decisions and want to measure or improve scoring.

Recommended loop:

```bash
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
videoedit calibrate apply calibration/proposed_config.json --output configs/scoring.json
videoedit rate footage/ --output analysis_tuned/ --config configs/scoring.json
```

Starter annotation file:

```bash
videoedit calibrate init --output annotations.json --project "Project Calibration" --source-root footage/
```

Annotation schema:

```json
{
  "project": "Project Calibration",
  "source_root": "footage/",
  "clips": [
    {
      "source": "race_day/interview.mp4",
      "start": "00:00:30",
      "end": "00:00:45",
      "rating": "select",
      "tags": ["quote", "team_tuesday"],
      "notes": "Strong intro soundbite"
    }
  ]
}
```

Supported annotation ratings:

- `select`
- `review`
- `broll`
- `reject`
- `cut`
- `ignore`

Calibration outputs:

- `calibration_report.json`
- `calibration_report.md`
- `missed_moments.csv`
- `false_positives.csv`
- `config_candidates.csv`
- `proposed_config.json`

`tune` proposes scoring changes but does not overwrite project defaults. `apply` copies a proposed config only to the output path you choose.

## Optional Signals And Vision

Use signal providers when deterministic rating needs more context than audio, scenes, and transcripts.

```bash
videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals ocr footage/ --output analysis/ocr_signage.json
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit signals motorsports analysis/ratings.json --output analysis/motorsports_events.json
videoedit signals topics analysis/ratings.json --output analysis/topic_clusters.json
videoedit signals validate analysis/visual_objects.json
```

Fuse signal artifacts into rating:

```bash
videoedit rate footage/ --output analysis_fused/ \
  --visual-objects analysis/visual_objects.json \
  --ocr-signage analysis/ocr_signage.json \
  --face-person analysis/face_person_presence.json \
  --motorsports-events analysis/motorsports_events.json \
  --topic-clusters analysis/topic_clusters.json
```

Signal artifacts:

- `visual_objects.json`
- `ocr_signage.json`
- `face_person_presence.json`
- `motorsports_events.json`
- `topic_clusters.json`

Typical fused labels and scores:

- `object_person`
- `object_presence`
- `ocr_signage`
- `face_presence`
- `person_presence`
- `motorsports_event`
- `topic_cluster`
- `object_presence_score`
- `ocr_signage_score`
- `face_person_score`
- `motorsports_event_score`
- `topic_cluster_score`

## Optional AI Assistance

AI support is opt-in and local-first. It is designed to improve recall and review quality without requiring a paid subscription.

List and inspect profiles:

```bash
videoedit ai profiles list
videoedit ai profiles show general_broll
videoedit ai profiles show garage_shop
videoedit ai profiles show social_reel
```

Score sampled frames with OpenCLIP:

```bash
videoedit ai score-frames footage/ --profile garage_shop --output analysis/ai_frame_scores.json
videoedit rate footage/ --output analysis_ai/ --ai-frame-scores analysis/ai_frame_scores.json
```

Find and review likely missed moments:

```bash
videoedit ai find-missed analysis/ratings.json --ai-frame-scores analysis/ai_frame_scores.json --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
```

Judge shortlisted clips with a local VLM-style provider:

```bash
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit ai judge review/review_assets.json --profile social_reel --output analysis/ai_clip_judgments.json --provider-command "/path/to/local-vlm-judge"
videoedit review-assets analysis/ratings.json --output review_ai/ --ai-clip-judgments analysis/ai_clip_judgments.json
videoedit rate footage/ --output analysis_judged/ --ai-clip-judgments analysis/ai_clip_judgments.json
```

Build a portable review dataset and train a small local scorer:

```bash
videoedit ai dataset build --inputs analysis/*/review_decisions.json --output training/review_dataset.jsonl
videoedit ai train-scorer training/review_dataset.jsonl --output models/local_scorer.json
videoedit rate footage/ --output analysis_learned/ --learned-scorer models/local_scorer.json
```

AI artifacts:

- `ai_frame_scores.json`
- `ai_missed_moments.json`
- `missed_review_decisions.json`
- `ai_clip_judgments.json`
- `review_dataset.jsonl`
- `local_scorer.json`

## Captions

Use captions when you have SRT subtitles and want a styled burned-in output.

```bash
videoedit captions styles
videoedit burn-captions input.mp4 captions.srt --output out.mp4 --style automotive_racing --format reel
```

Built-in styles:

- `automotive_racing`
- `clean_tech`
- `social_mobile`
- `vin_wiki`
- `minimal`

Compatibility wrapper:

```bash
python src/python/auto_caption.py input.mp4 out.mp4 captions.srt
```

## Content Planning And Editorial Reports

Use content planning after `ratings.json` exists and you need editorial direction.

```bash
videoedit content-map analysis/ratings.json --output reports/
videoedit quote-mining analysis/ratings.json --output reports/
videoedit series templates
videoedit series analysis/ratings.json --template team_tuesday --output series/
```

Report outputs:

- `content_map.json`
- `ranked_content_map.md`
- `quote_mining.md`

Series outputs:

- `series_plan.json`
- `caption_suggestions.md`
- `series_selections.json`

Initial series templates:

- `what_were_looking_for`
- `team_tuesday`
- `engine_build_montage`
- `shop_tour`

Content reports group footage into editable pillars such as expert quotes, educational teardown, build diary, motion bank, branded assets, and motorsports moments. Transcript-aware sections appear when transcript data exists; otherwise reports still use ratings, labels, and score explanations.

## Project Scaffolding

Use scaffolding when starting a new editing project.

```bash
videoedit init-project "May Shop Reel" --type reel --output projects/
videoedit init-project "Interview Day" --type interview --output projects/ --source footage/
```

Supported project types:

- `reel`
- `youtube`
- `documentary`
- `interview`
- `broll`

The scaffold creates standard folders, a starter README, optional metadata, and `.videoedit/config.json`.

## Modules And Community Extensions

Feature modules let optional capabilities be enabled, disabled, discovered, diagnosed, and extended.

```bash
videoedit modules list
videoedit modules enable content.series
videoedit modules disable advanced.vision
videoedit modules doctor
videoedit modules scaffold my_feature --output videoedit-my-feature/
```

Built-in modules:

- `core.inventory`
- `core.rating`
- `core.calibration`
- `core.pipeline`
- `core.review`
- `core.handoff`
- `delivery.captions`
- `content.series`
- `content.reports`
- `project.scaffold`
- `advanced.vision`
- `advanced.ai`
- `advanced.motorsports`
- `cloud.adapters`

Core modules are always enabled. Optional module settings are stored in `.videoedit/config.json`. Community modules use the `videoedit.modules` Python entry point group. See [docs/community-modules.md](community-modules.md) for naming, diagnostics, optional dependency behavior, artifact compatibility, and test expectations.

## Cloud Handoff

Cloud support is deliberately a planner, not a hidden uploader. Use it to create local job specs that another system or human can execute.

```bash
videoedit modules enable cloud.adapters
videoedit cloud adapters
videoedit cloud doctor
videoedit cloud plan elevenlabs --job-type voiceover --input scripts/narration.txt --output cloud_jobs/voiceover.json --param voice=narrator
videoedit cloud plan heygen --job-type avatar_video --input scripts/narration.txt --output cloud_jobs/avatar.json --project "Launch Reel"
videoedit cloud plan descript --job-type transcript_edit --input rough_cut.mp4 --output cloud_jobs/descript.json
```

Output:

- `cloud_job.json`

The planner records adapter ID, job type, inputs, outputs, parameters, and readiness notes without calling external APIs.

## YAML Pipelines And Presets

Use presets when you want a repeatable workflow file.

```bash
videoedit init simple --output simple.yaml
videoedit init reel --output reel.yaml
videoedit init roughcut --output roughcut.yaml
videoedit init youtube --output youtube.yaml
videoedit init documentary --output documentary.yaml
videoedit init motorsports --output motorsports.yaml
videoedit init vision_reel --output vision_reel.yaml
videoedit init ai_reel --output ai_reel.yaml
videoedit init ai_garage_shop --output ai_garage_shop.yaml
videoedit init ai_event_recap --output ai_event_recap.yaml
```

Validate and run:

```bash
videoedit validate reel.yaml
videoedit plan reel.yaml --input footage/ --output output/
videoedit run reel.yaml --input footage/ --output output/ --dry-run
videoedit run reel.yaml --input footage/ --output output/
```

Pipeline YAML can declare `requires_modules`. Validation fails clearly if a required module is disabled or unavailable.

## PowerShell Helpers

The repository also includes a Windows-friendly PowerShell module in `src/powershell/VideoEditing.psm1`.

Common cmdlets include:

- `Get-VideoInfo`
- `Find-Silence`
- `Find-SceneChanges`
- `ConvertTo-Reel`
- `ConvertTo-YouTube`
- `ConvertTo-Square`
- `Copy-VideoSegment`
- `Join-VideoFiles`
- `Remove-Silence`
- `Set-AudioNormalize`
- `Export-Audio`
- `New-VideoProxy`
- `Export-ForDaVinci`
- `Add-Captions`
- `Invoke-WhisperTranscribe`
- `New-VideoProject`
- `Start-BatchConvert`

See [src/QUICKREF.md](../src/QUICKREF.md) for examples.

## Compatibility Scripts

These scripts remain available for older workflows:

```bash
python src/python/inventory.py footage/
python src/python/rate_footage.py footage/ --output analysis/
python src/python/auto_caption.py input.mp4 out.mp4 captions.srt
python src/python/video_start.py "Project Name"
python src/python/davinci/generate-edl.py selections.json --output edl/
```

Prefer the `videoedit` CLI for new work because it shares config, modules, artifacts, and tests.

## Artifact Glossary

Common files:

- `inventory.json`: structured media inventory.
- `inventory.csv`: spreadsheet-friendly media inventory.
- `inventory.md`: readable inventory summary.
- `ratings.json`: full rating report, candidates, labels, reasons, and summaries.
- `candidates.csv`: ranked candidate table.
- `review.md`: readable candidate review notes.
- `review.html`: static V1 review page.
- `review_assets.json`: manifest for HTML/TUI review.
- `contact_sheet.html`: static visual review surface.
- `review_decisions.json`: human decisions exported from review.
- `approved.json`: approved clips for assembly and handoff.
- `roughcut_plan.json`: sequencing, handles, format, and render plan.
- `roughcut_report.md`: readable rough-cut summary.
- `selections/*.json`: per-source selection files.
- `calibration_report.json`: machine-readable precision/recall and error report.
- `calibration_report.md`: readable calibration summary.
- `missed_moments.csv`: positive annotations the scorer missed.
- `false_positives.csv`: selected candidates not supported by annotations.
- `config_candidates.csv`: scored tuning sweep candidates.
- `proposed_config.json`: best proposed scoring config.
- `visual_objects.json`: object detection signal artifact.
- `ocr_signage.json`: OCR/signage signal artifact.
- `face_person_presence.json`: face/person signal artifact.
- `motorsports_events.json`: motorsports event signal artifact.
- `topic_clusters.json`: transcript topic signal artifact.
- `ai_frame_scores.json`: OpenCLIP/profile frame-score artifact.
- `ai_missed_moments.json`: AI-discovered review-only misses.
- `ai_clip_judgments.json`: optional local VLM clip judgment artifact.
- `review_dataset.jsonl`: portable training records from review decisions.
- `local_scorer.json`: small learned scorer for opt-in rating.
- `series_plan.json`: planned content-series clips.
- `caption_suggestions.md`: suggested post captions.
- `series_selections.json`: selection JSON for a series plan.
- `content_map.json`: structured editorial content map.
- `ranked_content_map.md`: readable content map.
- `quote_mining.md`: transcript-forward quote report.
- `cloud_job.json`: local cloud adapter handoff spec.

## Recommended Recipes

Fast deterministic reel:

```bash
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/ --proxy
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit roughcut plan approved.json --output roughcut_plan.json --format reel --target-duration 60
videoedit assemble approved.json --plan roughcut_plan.json --output reel.mp4
```

Calibration loop:

```bash
videoedit calibrate from-decisions review/review_decisions.json --ratings analysis/ratings.json --output annotations.json
videoedit calibrate evaluate analysis/ratings.json --annotations annotations.json --output calibration/baseline/
videoedit calibrate tune analysis/ratings.json --annotations annotations.json --output calibration/tuned/
videoedit calibrate compare calibration/baseline calibration/tuned --output calibration/compare/
```

Vision-assisted B-roll:

```bash
videoedit modules enable advanced.vision
videoedit signals objects footage/ --output analysis/visual_objects.json --model yolo26n.pt
videoedit signals face-person footage/ --output analysis/face_person_presence.json
videoedit rate footage/ --output analysis_vision/ --visual-objects analysis/visual_objects.json --face-person analysis/face_person_presence.json
```

Local AI-assisted recall:

```bash
videoedit modules enable advanced.ai
videoedit ai score-frames footage/ --profile general_broll --output analysis/ai_frame_scores.json
videoedit rate footage/ --output analysis_ai/ --ai-frame-scores analysis/ai_frame_scores.json
videoedit ai find-missed analysis/ratings.json --ai-frame-scores analysis/ai_frame_scores.json --output analysis/ai_missed_moments.json
videoedit ai review-missed analysis/ai_missed_moments.json --output review_missed/
```

DaVinci handoff:

```bash
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
videoedit export-edl approved.json --output edl/
videoedit extract-segments approved.json --output clips/
```

## Troubleshooting

If a command is missing:

```bash
python -m pip install -e ./src/python
command -v videoedit
videoedit doctor
```

If optional providers are missing:

```bash
videoedit modules doctor
python -m pip install -e "./src/python[advanced]"
python -m pip install -e "./src/python[ai]"
```

If a pipeline fails validation:

```bash
videoedit modules list
videoedit validate pipeline.yaml
videoedit plan pipeline.yaml --input footage/ --output output/
```

If review decisions do not appear in approval, confirm you downloaded or saved `review_decisions.json` from the contact sheet or wrote it with `videoedit review-tui`.

If AI or vision artifacts are unavailable, rerun the base deterministic flow first. The core commands do not require those optional artifacts:

```bash
videoedit rate footage/ --output analysis/
videoedit review-assets analysis/ratings.json --output review/
```
