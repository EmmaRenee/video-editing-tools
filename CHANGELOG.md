# Changelog

All notable changes to this repository should be documented here.

This project uses semantic versioning for the Python `videoedit` package once published. Until the first external package release, keep the version aligned between `src/python/videoedit/_version.py`, package metadata, release notes, and GitHub releases.

## Unreleased

- Added optional native OTIO export through `editor.otio`, the `[editor]` extra,
  `videoedit export-otio`, and `generate_otio`, without promoting the experimental
  Shoot/Resolve SDK architecture or requiring an editor dependency for core use.
- Corrected source/record timebase handling, fractional selection precision,
  bounded rough-cut handles/targets, source-aware CMX/FCP7 exports, XML sequence
  format and stereo panning. Mixed-rate XML now uses timeline-rate clip counters
  while retaining native file metadata and explicit rounding diagnostics.
- Documented the [XML counter reader migration](docs/editor-handoff.md#xml-counter-reader-migration)
  for legacy/current `videoedit.handoff.v1` rows, including null unsupported
  ranges. Regenerate older mixed-rate XML; changing its manifest alone is not a fix.
- Added shared sampled-frame reuse and per-run YOLO/OpenCLIP model lifecycles,
  stricter rating-cache identities and decode-completion checks. Interrupted or
  incomplete inference is not reused as a successful cache result.
- Added tracked-distribution auditing and fresh core-only installed-workflow CI
  on Python 3.10-3.12, plus independent CMX/FCP7/OTIO structure checks.
- Recorded scoped Resolve Studio 20.3.2 validation of original-media relinking,
  DF EDL controls, mixed-rate XML/OTIO ranges, bounded handles, rendered pixels
  and stereo audio. See the [V17 evidence snapshot](docs/v17-execution.md#evidence-snapshot-2026-10-10)
  for limitations; independent quality benchmarks and RC qualification remain open.

- Added controlled provider-ablation scorecards with coverage, historical input
  binding, explicit cost limits, identity-separated recommendations, and no
  automatic default changes.
- Added OpenCLIP/heuristic processing evidence; incomplete frame inference is
  no longer reported or cached as successful.

- Added scoped footage benchmark validation, execution, comparison reports,
  pipeline operations, privacy-safe summaries, and synthetic contract tests.
- Documented V17 experimental-component dispositions and production evidence gates.
- Added shared, validated provider provenance with legacy migration warnings,
  revision-aware AI cache identities, and benchmark provider-change reports.
- Added atomic pipeline/rating/review/planning/assembly/handoff diagnostics,
  relative/redacted path modes, partial and interrupted states, fingerprints,
  observed cache counters, and explicit legacy editor-export limitations.

- Added local-first footage inventory, rating, calibration, review, rough-cut, signal fusion, AI scoring, community module, cloud adapter, and release-hardening workflows.
- Added CI and package-build verification for the Python `videoedit` package.
- Added a component reference and version-consistency checks for README/install docs.
- Added a user guide covering the supported feature set, commands, artifacts, and recommended workflows.

## 0.5.0

- Current package line for the local-first `videoedit` CLI and Python package.
- Supports deterministic rating, calibration, review assets, rough cuts, optional advanced signals, optional AI frame scoring, community modules, and credential-safe cloud handoff planning.

## Historical Repository Notes

### 2026-05-01

- Initial public repository release.
- PowerShell cmdlets for common FFmpeg workflows.
- Cross-platform FFmpeg workflows.
- Claude/Codex skill for assisted editing.
- Whisper transcription support.
- DaVinci Resolve export formats.
