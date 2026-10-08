# Shared Frame Samples

`sample_frames` belongs to always-enabled `core.inventory`; it requires only
FFmpeg/ffprobe. No inference or model download occurs during sampling.

```bash
videoedit signals sample-frames footage/ --output analysis/frame_cache/ --max-frames-per-file 6
videoedit signals ocr footage/ --output analysis/ocr_signage.json --frame-cache analysis/frame_cache/
videoedit signals face-person footage/ --output analysis/face_person_presence.json --frame-cache analysis/frame_cache/
videoedit ai score-frames footage/ --output analysis/ai_frame_scores.json --frame-cache analysis/frame_cache/
```

OCR needs Tesseract; face/person needs OpenCV; AI scoring needs the optional AI
extra. The latter command's default maximum is eight, whereas OCR/face default
to six. Match the maximum and interval when prewarming a provider's frames.

## Contract

`frames.json` uses `videoedit.frame_samples.v1`. It contains per-source frame
paths, explicit timestamps, source/decoder/sampling signatures, SHA-256 checksums,
status, warnings, processing coverage, and telemetry. This is a **private editing
artifact**: absolute source paths and frame images are not privacy-safe exports.

The uniform midpoint sampler starts at `min(duration / 2, interval / 2)` and
advances by the interval, capped by the requested maximum. Default interval is
10 seconds. A capped scan does not cover the rest of a long source. Coverage
cells express sampling support, not continuous inference.

Compatible consumers share samples across invocations. Keys include canonical
source path, size and nanosecond mtime, FFmpeg/ffprobe executable and version,
sampling algorithm, interval, maximum, width, and JPEG quality. They exclude
model/profile/prompt identities; those belong to the separate inference cache.
Basenames alone never identify a cache entry.

`--width 0` preserves source resolution. OCR/face use this default; AI uses
336px width. These formats intentionally do not share entries. Quality remains
FFmpeg JPEG `-q:v 3`. Only matching settings are reused, even if a short source
happens to yield the same sample count for different requested maxima.

`--source-hash metadata` is the fast default: size/mtime is an invalidation
heuristic, not cryptographic media identity. Use `--source-hash sha256` on the
sampling CLI for strict content checks; it reads the entire source before and
after sampling and can be expensive on cloud/removable storage. Existing native
provider convenience flags use metadata identity. For strict runs, callers can
inject a SHA-256-configured `FrameCache` through their own provider integration.

## Integrity And Lifecycle

Complete entries publish by directory rename only after every requested JPEG
passes marker/checksum checks. Subsequent reuse verifies the manifest, expected
times, fixed filenames, checksums and sizes. This does not authenticate externally
modified cache manifests or prove byte identity across decoder builds.

Partial samples are kept under `incomplete-*` for diagnostics and consumption
within the failing run, never as successful cache entries. An interruption
cleans its staging directory. If a source changes while sampling or validating
warm frames, the result is an error with no usable mixed-source frame list.

Publication/repair uses a per-entry directory lock with a bounded wait. A worker
terminated externally may leave `entries/<hash>.lock`; another worker fails with
`cache_publish_lock_timeout` rather than stealing it. Remove an abandoned lock
only after confirming its worker has stopped. Cached reads need no lock.
Concurrent cold workers may decode the same frames, but publish one complete
entry. Old source/settings entries are retained; no automatic eviction policy
is promised. Remove only the chosen generated cache when reclaiming storage.

## Telemetry And Providers

Source telemetry records cache hits/misses, invalidation reason, elapsed seconds,
decode attempts, successful sampled images, and JPEG bytes. `decoded_frames`
means successful output images, **not** every GOP frame internally decoded by
FFmpeg. `output_size_bytes` is JPEG storage, not total recursive cache storage.
Warm hits report bytes of the reused images, not newly written bytes.

OCR/face artifacts report `cache_scope: frame_extraction` and temporal processing
coverage including negative frames. Failed inference or unavailable classifiers
cannot be represented as successful zero detections. Their models/classifiers
initialize once per invocation; Tesseract runs once per sampled image.

AI keeps top-level cache counters scoped to inference, with nested
`telemetry.frame_sampling` counters for extraction. `--no-cache` bypasses AI
score reuse, not the shared frame cache. Different profiles can reuse compatible
images while recomputing their own scores. Injected custom samplers remain
compatible but report extraction telemetry as `not_instrumented`. OpenCLIP model
initialization still occurs once per invocation, including a warm inference run;
no zero-startup-cost claim is made.

Existing OCR/face rating semantics remain source-wide; timestamps and coverage
do not silently change scoring policy. Positive hits are not proof of detection
accuracy. Native YOLO's continuous video decoding does not consume this uniform
sample cache; it remains a separate lifecycle/coverage task.

## Pipelines

Each pipeline has a shared `${frame_cache}` at `<output>/.frame_cache`. Native
OCR/face/AI operations use it automatically; explicit `params.frame_cache`
overrides it. A `sample_frames` step publishes `frame_samples` and changes
`frame_cache` to its output directory, so compatible later operations reuse it.

```yaml
name: sampled_ocr
steps:
  - name: samples
    operation: sample_frames
    params:
      max_frames_per_file: 6
  - name: signage
    operation: detect_ocr_signage
    params:
      frame_cache: ${frame_cache}
```

Sampling CLI/pipeline failure is nonzero for empty, partial, or failed input.
OCR/face CLI commands now likewise return nonzero for incomplete/unavailable
processing while retaining their diagnostic JSON. Optional provider operations
retain existing nonfatal result behavior; inspect status before using ablations.

## Measurement Limits

Compare cold and warm runs with identical source, timestamps, format, model,
profile, and thresholds. Report OS/cloud cache effects, machine, versions,
sampling limits and storage scope. Verify image checksums, detection outputs,
and downstream selection parity. Runtime checks on preselected clips do not
replace independent full-window annotations or multi-project selection-quality
benchmarks; those remain V17 production acceptance gates.
