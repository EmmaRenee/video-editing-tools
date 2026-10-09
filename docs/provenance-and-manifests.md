# Provenance And Execution Manifests

V17 adds shared provider identity and execution diagnostics without replacing
the existing ratings, selections, review decisions, or handoff artifacts.
These diagnostics support the [benchmark protocol](benchmarking.md); they do
not establish editorial quality or successful import into an editor.

## Provider Identity

New signal, OpenCLIP frame-score, clip-judgment, and learned-scorer artifacts
include a `provenance` object with `schema_version: videoedit.provenance.v1`.
The artifact's existing schema and content fields remain unchanged.

| Field | Meaning |
|-------|---------|
| `artifact_kind` | Signal or model-output category |
| `provider` | Portable provider name, library name when applicable, and observed version |
| `model` | Model name, repository, revision, checkpoint SHA-256, and pretrained identifier when known |
| `device`, `precision` | Observed execution device and numerical type; unknown values are null |
| `prompt_profile` | Profile ID, content hash/version, and prompt count; no prompt text |
| `sampling` | Typed sampling policy, interval, limits, and thresholds |
| `random_seed` | Declared provider seed, or null if not controlled/known |
| `config_sha256` | Canonical configuration hash, not raw configuration |
| `identity_sha256` | Canonical hash of all preceding provenance fields |

An explicitly supplied local checkpoint is streamed into SHA-256. A pretrained
tag or repository name alone does not prove a particular model revision or
weight checksum. OpenCLIP records its observed library version, device,
precision, configured model/repository, and prompt identity; unknown loaded
weight revisions remain null. External detector/judge executables are not
assumed to use the Python library installed in the caller's environment.
Native OCR records the Tesseract version reported by its executable.

Missed-moment outputs reuse validated upstream model/provider identity and record
`derived_from` hashes plus the deterministic transform version. Their config and
identity hashes include the discovery settings; they do not claim fresh model
inference. Future-version score caches and discovery/review inputs also require
migration. `score-frames --no-cache` explicitly regenerates incompatible caches.

Provenance stores identifiers and hashes, not executable paths, raw commands,
credentials, transcripts, or custom prompt text. Operational artifacts still
contain source paths and content needed for editing; keep those private.

### Compatibility And Migration

- Existing supported v1 artifacts without provenance remain readable and emit
  `provenance_missing`. Artifacts without a schema also receive a legacy warning.
- Unknown provider/model/device/precision/seed fields receive explicit warnings;
  no revision or seed is invented to make the result look reproducible.
- Unsupported future artifact/provenance versions, malformed identity fields,
  and identity hashes that do not match their fields fail with upgrade or
  re-generation guidance.
- Re-run the producing command to migrate an old artifact. Do not just change
  its schema version or copy provenance from another run.
- `videoedit signals validate ARTIFACT.json` reports compatibility warnings.
  Rating input loaders and benchmark provider checks enforce the same contract.

OpenCLIP source-cache signatures include provenance identity. Model revision,
checkpoint, library versions, prompt profile, and sampling changes invalidate
those cached scores. Per-source `cache_status` and aggregate hit/miss telemetry
identify reuse versus newly computed scores. Native OpenCLIP records Torch and
Pillow versions in `provider_metadata.runtime_libraries` and binds them in the
configuration hash alongside its OpenCLIP version. Earlier native score caches
without that runtime binding recompute once; their artifacts remain readable.
The float32 policy is explicit and checked against the loaded model. A local
checkpoint must remain stable across loading and match the artifact's model
checksum before scores can be accepted. Full cache hits skip model loading;
device/library/decoder/checkpoint identity checks remain. See
[model lifecycle and telemetry](frame-cache.md#telemetry-and-providers).

Benchmark comparisons expose `provider_changes`. Matching hashes with known
model revision/checksum can be marked equivalent; changed identities and
unverified model identities cannot. Equivalent metadata is not proof of
bit-identical numerical execution on different hardware.

## Execution Sidecars

| Workflow | Sidecar |
|----------|---------|
| `videoedit run` | `pipeline_run.json` in the output directory |
| `videoedit rate` | `rating_run.json` in the analysis directory |
| `videoedit review-assets` | `review_run.json` in the review directory |
| `videoedit roughcut plan` | `PLAN_STEM_run.json` beside the plan |
| `videoedit assemble` | `OUTPUT_STEM_assembly.json` beside the video |
| `videoedit export-edl` | `SELECTION_STEM_handoff.json` in the export directory |

All use `videoedit.run_manifest.v1`. They record package, Python, platform,
machine architecture, FFmpeg/ffprobe and installed optional-library versions;
input fingerprints; canonical config hash; step timing; cache counters and
origin; tracked output fingerprints; warnings; and terminal status. JSON signal
inputs/outputs include validated provider provenance. Core imports and these
diagnostics do not load optional models or require extra Python dependencies.

Small text/JSON artifacts use content SHA-256. Media and directory fingerprints
use `size_mtime`, a metadata digest explicitly identified by `method`, not a
full-content checksum. A directory fingerprint is not recursive: rating,
review, planning, assembly, and handoff also record the media they consume.
Review output records include generated thumbnails/proxies; rating includes
inventory reports, HTML, and per-source selections.

`telemetry.storage_bytes` has `storage_scope: tracked_output_files`. It is not
the size of an entire frame cache, model cache, or output directory. Unobserved
cache behavior is `unknown`, not an assumed cache miss; absent counters are null.

### Deterministic Rating Cache

Core rating caches successful detector/transcript reports, not a frozen scoring
configuration. Cache hits recompute file scores/reasons with the current weights
and audio-spike settings; candidate generation and calibration likewise recompute
technical scores from asset metadata. Changing scoring weights, window/merge
settings, thresholds, limits or the learned scorer does not require re-decoding
unchanged source analysis.

The `input_identity_v5` cache policy binds FFmpeg/ffprobe executable paths and
version lines, detector settings, source size/nanosecond mtime/ctime and file
identity, the actually selected transcript's path/content SHA-256, and canonical
signal-artifact paths/content hashes (including direct AI-frame-score API paths).
Transcript discovery uses the same directory/suffix priority as analysis. A
new/deleted/replaced selected transcript invalidates; edits to an unselected
fallback or disabled transcript do not. Earlier detector caches refresh once.

Media identity remains a fast local metadata fingerprint, not a cryptographic
content checksum. Filesystem timestamp semantics vary; use `--no-cache` when
metadata cannot be trusted and separately checksum originals for validation.
Private cache entries contain operational paths and transcript hits; never share
them as redacted diagnostics. Executable/version identity does not checksum every
decoder library or guarantee bit-identical output across machines.

`rating_run.json` step and aggregate telemetry include `cache_miss_reasons` counts:
`cache_disabled`, `cache_not_found`, `cache_unreadable`, `cache_invalid`,
`cache_entry_invalid`, `analysis_policy_changed`, `source_changed`,
`decoder_changed`, `transcript_changed`, `signal_artifacts_changed`,
`analysis_config_changed`, or `cached_analysis_incomplete`. One first applicable
reason is counted per miss; an all-hit run has an empty map. These fixed codes,
not filenames or transcript text, survive redaction. The reason map is additive;
existing hit/miss counters and manifest/schema consumers remain compatible.

Cache publication is atomic. Ordinary source/transcript changes during detector
execution and signal-artifact changes during loading/analysis make the run
incomplete and prevent publication of the affected new cache data. Retained old
entries still need an exact input match on retry. Concurrent file mutation is
not a supported input workflow; stabilize media and sidecars before analysis.

### Path Modes

The default `absolute` preserves operational paths and legacy pipeline fields.
For portable diagnostics, use `relative`; for shareable diagnostics, use
`redacted`:

```bash
videoedit rate footage/ --output analysis/ --manifest-paths redacted
videoedit review-assets analysis/ratings.json --output review/ --proxy --manifest-paths redacted
videoedit roughcut plan approved.json --output roughcut_plan.json --manifest-paths relative
videoedit assemble approved.json --plan roughcut_plan.json --output rough_cut.mp4 --manifest-paths redacted
videoedit export-edl approved.json --output edl/ --manifest-paths redacted
videoedit run pipeline.yaml --input footage/ --output output/ --manifest-paths redacted
```

Pipeline path mode propagates to the above operations. A step may explicitly
set `params.manifest_paths` to override it. Pipeline output references expose
`rating.run_manifest`, `review.run_manifest`, `plan.run_manifest`,
`assembly.run_manifest`, and `handoff.run_manifests` (a list for multiple
selection files). Planning/dry-run resolves expected sidecar fields without
creating outputs; glob-dependent handoff lists are unknown until execution.

Relative mode normalizes absolute path values against the sidecar directory;
paths on another Windows drive remain absolute because no relative path exists.
It does not strip filenames, free-form text, notes, or credentials. Redacted
mode uses generic input/output/step aliases, removes raw results, descriptions,
errors and warning text, and retains typed diagnostics and warning counts.
The default mode must not be posted publicly without inspection. Redaction
applies only to execution sidecars, not `ratings.json`, selections, contact
sheets, EDL/XML, media, or decisions. Hashes remain linkable identifiers; use
private storage for all sensitive footage and review content.

### Failures And Interruptions

Core rating analyzes the first video stream (`0:v:0`) for scenes and the first
audio stream (`0:a:0`) for silence/RMS, rather than following container default
dispositions or selecting the largest video/most-channel audio stream. This
matches the first-video metadata in the inventory. Audio passes do not decode
video, and scene analysis does not decode audio. Additional tracks are not
combined. A corrupt video can leave valid audio measurements, but the failed
scene analysis still makes the overall rating partial and non-cacheable.
Source signatures invalidate caches made before this explicit stream policy;
rerun rating once rather than carrying forward automatic-selection results.
FFmpeg may still inspect the input container/stream headers, so an unreadable
container can prevent all detectors from running.

Manifests are checkpointed atomically while running and after each step.
`status` is `running`, `ok`, `partial`, `error`, or `interrupted`; `complete`
is true only for `ok`. Failed media probes, missing review media, incomplete
provider outputs, exceptions, and Python interruptions do not claim a complete
run. Completed prior outputs remain diagnostic records, not an assertion that
the failed final deliverable exists.

KeyboardInterrupt/SystemExit produce terminal interruption diagnostics.
Uncatchable process termination (for example SIGKILL or power loss) can leave
the last checkpoint at `running` with `complete: false`. Retry into an appropriate
output path after examining the diagnostic; do not manually mark it complete.
Invalid pipelines also write failure diagnostics before any operation runs.

## Handoff Limits

Handoff and planning sidecars record source-to-reel mappings, source windows,
timeline frame-rate assumptions, generated timecodes/frame positions, rounding,
handles, known omitted features, and files produced. Redacted sidecars alias
source paths, reel names, and labels.

Delivery boundaries retain fractional elapsed seconds; numeric selection
bounds take precedence over truncated display strings. Plans retain their FPS
and precise endpoint strings. NDF timecode formatting uses exact conventional
NTSC rates and nearest-frame half-up rounding with correct carry. See
[selection timing](../src/python/README.md#selection-timing) for parsing rules
and regenerating legacy files that lost their numeric bounds.

These fixes do not certify Resolve compatibility. Current exports probe native
rates and embedded start timecodes; XML includes linked single-stream mono/stereo
audio, while EDL is video-only and mixed-rate EDL is diagnostic-only. Rough-cut
plans validate approved bounds and clamp handles to known video extents, retaining
applied pre/post-roll and target trims. Unknown duration and unsupported effects
remain partial rather than complete. See [Editor Handoff](editor-handoff.md).
Live real-media/editor validation remains required in V17 #79; `editor_verified`
remains false.
Output generation succeeding is not evidence that relinking, timing, or audio
survived an editor import. Stream-copy extraction is keyframe-dependent even
when its requested timestamps are precise.
