# Continuous Local YOLO Scans

The default `signals objects` backend remains the compatible external `yolo`
command bridge. Opt into native Ultralytics processing for one model per
invocation, verified continuous CFR processing, and reusable complete results:

```bash
videoedit signals objects footage/ --backend native --model /path/to/yolo26n.pt \
  --output analysis/visual_objects.json --device cpu --timeout 3600
videoedit rate footage/ --output analysis/rated/ \
  --visual-objects analysis/visual_objects.json
```

Install the optional `advanced` extra using [INSTALL.md](../INSTALL.md).
Native PyTorch `.pt` weights must already exist as a local file; other backends
are rejected before optional runtime installation/downloads can occur. This path never substitutes
a model name or URL for a missing checkpoint. It is not a custom detector or
training system. Ultralytics remains a separately licensed optional dependency.
The implementation uses the documented [Ultralytics streaming prediction API](https://docs.ultralytics.com/modes/predict/).

## Coverage And Compatibility

Native prediction streams every frame with `vid_stride=1`. Valid negative frames
count as processed units; positive hits alone never prove coverage. Cold scans
perform a separate full-frame ffprobe decoding pass to check presentation
timestamps and the expected frame count. Its cost is measured separately.
Nonzero presentation origins are normalized to the first displayed frame.
Timestamp tolerance follows one container timebase tick plus one microsecond
for serialized timestamp/origin quantization. Clocks coarser than a quarter
frame cannot verify cadence. The tolerance is recorded in coverage metadata;
fractional-FPS MKV millisecond timestamps are tested without accepting genuine
cadence shifts as CFR.
VFR, missing timestamps, uncertain totals, invalid model results, timeouts,
truncated scans and changed inputs cannot claim complete temporal coverage.

Artifacts keep the existing `sources`, `detections`, `class_counts`, and
`segments` rating interface. Native class names come from the actual checkpoint,
not an assumed COCO map. Detailed detections respect `--max-detections` while
class aggregates include every valid detection; segment output retains the
legacy top 500 limit. Provider streaming, bounded retained boxes and online
class/segment aggregation avoid retaining every full detection result/image.
Frame indices and timing-probe timestamp metadata still scale with scan length.

The command bridge now uses unique invocation/source folders to prevent stale
labels and same-basename collisions. Failed sources stay visible and mixed
success/failure is `partial`. Command success remains backward-compatible;
CLI log progress can count processed frames but **cannot independently verify
presentation timing**, so bridge coverage is provisional and not a valid V17
production ablation. Native complete coverage is required for that evidence.

## Cache And Cost

Native complete-only JSON caches live beside the output in `.object_cache/`.
They bind source canonical path/size/nanosecond mtime, checkpoint SHA-256,
Ultralytics/Torch/OpenCV/ffprobe versions, device/precision, algorithm and
inference settings. `--source-hash sha256` additionally hashes source content;
use it for benchmark provenance or media modified without changing metadata.
Metadata mode is faster but cannot detect deliberately preserved size/mtime.
Unknown library identities do not publish reusable source caches.

Cache entries have checksums and atomic publication. Partial, failed, uncertain
or interrupted source scans are never published as complete entries. Earlier
completed sources in an interrupted multi-source run remain reusable. Use
`--no-cache` to recompute detections and timing, not just reload model outputs.
An all-hit invocation initializes no model and decodes no frames.

Read `telemetry` for hits/misses/invalidation reasons, model initialization,
native result-frame counts, timing-probe frame counts, elapsed/inference/probe
times and cache JSON bytes written. Command results also report measured
`artifact_bytes`. Native result counters exclude ffprobe's separately measured
decode pass; inference timing includes native decoding/preprocessing. These are
not GPU kernel timings, unique physical disk bytes, or general speed promises.

CPU/float32 is the explicit default. `--device mps` opts into Apple Silicon
acceleration; kernel reproducibility and performance must be measured on the
actual machine. No fixed seed or cross-device output equivalence is invented.
`--image-size 640` and `--max-objects-per-frame 300` are explicit inference
limits. `--timeout` is a cooperative per-source native budget checked between
results, including cold probe/model setup. It cannot forcibly preempt an
in-process model import or blocked native call. Long continuous footage needs
an appropriate budget; provider cost is not inferred from a sparse sample.

Pipeline operation `detect_visual_objects` accepts `backend`, `model`, `device`,
`cache`, `source_hash`, `image_size`, `max_objects_per_frame`, `timeout`, and the
existing confidence/detection/merge controls. Reports and review outputs stay
private. Do not commit source paths, checkpoint files, cache entries or media.
Compare cold/warm/recomputed outputs before claiming selection-quality parity;
independent annotations and three-profile benchmarks remain V17 quality gates.
