# V17 Execution Record

Source of truth: milestone 13 and umbrella issue #66. This is implementation
evidence and design rulings, not a second backlog.

## 2026-10-08

- Refreshed issues #66-#81: all remain open. No existing V17 PR.
- Established an isolated checkout from `main` at `d8eb36f`, preserving the
  primary `feature/shoot-pipeline` checkout.
- Baseline: Python 3.12, 95 unittest tests passed, including FFmpeg smoke.
- #71: inventoried experimental files and recorded dispositions in
  `docs/v17-experimental-inventory.md`.
- Ruling: capabilities from the alternate operation/shoot architecture are
  adapted into existing registries and artifacts; importing both registries
  would shadow `operations.py` and break the established CLI.
- Ruling: real-footage, independent human annotations, and live Resolve
  checks remain required evidence. Synthetic tests establish contracts but
  do not satisfy those acceptance gates.
- #71: opened deferred capability follow-ups #82-#88; linked them from the
  disposition record. These are not new V17 completion gates.
- #73/#74: added the benchmark protocol, structural JSON Schema, synthetic
  valid/invalid fixtures, and `benchmark validate/run/compare` commands.
  Pipeline operations use the existing `core.calibration` module/registry.
- Test-first evidence: the initial contract tests failed on the missing CLI;
  later tests reproduced malformed-input failures and an empty footage key
  incorrectly overriding a consumed ratings input before those fixes.
- Current suite: Python 3.12, 119 tests passed (95 baseline plus 24 benchmark
  checks), including actual FFmpeg-generated media, scoped overlap metrics,
  privacy, provider failures, deterministic ordering, and pipeline execution.
- JSON Schema verified with Draft 2020-12: valid fixture accepted, invalid
  fixture rejected. This check is development-only, not a core dependency.
- Wheel and source distribution build succeeded. A fresh core-only wheel
  environment ran `doctor`, `operations`, `modules list`, benchmark validation
  and benchmark execution without optional Python providers.
- CodeRabbit reviewed the foundation diff and raised one minor issue about
  malformed comparison reports. Regression tests now reject missing
  baselines/fingerprints with clear errors. Identical baseline rows are
  omitted; changed baseline-only reports remain valid before/after inputs.
- Imported existing pipeline `duration_seconds` as runtime telemetry;
  measured rating time and explicit manifest telemetry take precedence.
- Ruling: the existing 100-clip human decision set is shortlist review,
  not independent full-window ground truth. It can inform acceptance rate
  but cannot by itself establish recall or fulfill #75.

## Provenance And Manifest Slice

- Previous goal turn: progress. Commit `4e38b90` / PR #89 changed the
  authoritative implementation and passed all four CI jobs. PR remains open.
- Refreshed #78/#80 and PR #89 before work; no pending PR review comments.
- Isolated `codex/v17-provenance-manifests` from the foundation commit.
- Pre-flight: #78 produces provider identity consumed by #74/#80; existing
  artifact schemas must retain their data fields while gaining provenance.
- Pre-flight: #80 consumes operations/results and produces pipeline and
  delivery diagnostics; existing caller return values must remain compatible.
- Ruling: unknown model revisions, precision, or seeds remain null with
  validation warnings, not fabricated reproducibility claims. Legacy artifacts
  remain readable; incompatible future schemas must fail with guidance.
- Ruling: public redaction is opt-in for diagnostic manifests. Operational
  selections, review assets, and media remain private and usable; their paths
  cannot be removed without breaking editing. Relative paths are portable,
  not a guarantee of privacy.
- #78: shared provenance validates supported schemas and typed identity fields,
  warns on missing/unverified identity, and rejects incompatible future versions
  or mutated identity hashes. Frame-cache identity now includes provider/model,
  prompt, and sampling provenance; comparisons distinguish model revisions.
- #80: atomic diagnostics cover pipeline, rating, review, planning, assembly,
  and handoff. They retain legacy returns/fields and add timing, cache counters,
  input/output fingerprints, portable path modes, and explicit exporter limits.
- Test-first: new checks reproduced missing modules/sidecars, ignored future
  schemas, interruption/validation diagnostic gaps, identity mutation, incomplete
  outputs, unresolved dry-run references, missing media derivatives, failed
  media probes incorrectly reporting success, and missing native OCR version.
- Ruling: empty pipelines remain valid for compatibility. Invalid steps, rather
  than empty lists, exercise validation-failure diagnostics.
- Ruling: storage telemetry covers tracked output files; size/mtime media
  fingerprints are metadata digests, not full media content hashes. Neither
  figure proves full cache/storage cost or recursive directory identity.
- Regression checks also prevent inputs/warning text being counted as output
  files, invalid JSON claiming completion, duplicated artifact hashing, and
  benchmark imports losing the tracked-output storage scope.
- Actual installed OpenCLIP ran offline against cached weights and a synthetic
  clip: one source/frame scored successfully in 6.86 seconds. This is runtime
  compatibility evidence, not editorial quality or independent ground truth.
- Offline warm run: one actual source-cache hit, zero misses, 3.51 seconds.
  Explicit local safetensors checkpoint run: 2.87 seconds and independently
  verified SHA-256. OpenCLIP 3.3.0, CPU float32; random seed remains unknown.
  Tagged weights correctly warn that model identity is unverified; a verified
  local checkpoint removes that warning without fabricating a revision.
- CodeRabbit reviewed 26 changed files and raised one minor cross-Windows-drive
  relative-path issue. A failing regression reproduced it; paths that cannot be
  made relative now retain their absolute values, with the privacy limit documented.
- Final author boundary review added future-version AI cache/discovery/review
  checks and upstream model/hash lineage for deterministic missed-moment outputs.
  Regression tests reproduced both gaps before fixes.
- Final local verification: Python 3.12, 150 tests passed (31 new checks on top
  of the foundation's 119), including real FFmpeg smoke and all prior regressions.
  Whitespace checks, wheel/source build, and core-only wheel install passed.
  Installed-wheel doctor, operation/module listing, synthetic benchmarking,
  redacted pipeline/rating/review, handoff, and assembly commands succeeded.
  The synthetic assembly was independently probed at 10 frames / 1.0 second.
  Installed-wheel missed-moment discovery retained the verified model checksum.
- Core CLI import did not load Torch, OpenCLIP, OpenCV, Ultralytics, or Whisper.
  Primary checkout remains untouched. No footage, weights, private manifests,
  review decisions, or annotations were added to Git.

## Provider Ablation Slice

- Previous goal turn: verified progress, PR #90 / commit `268736e`, 150 local
  tests and four CI jobs passed; no merge. Refreshed milestone 13, #66, #76,
  #77 and prerequisite PR feedback before starting this branch.
- Reusing the isolated checkout on `codex/v17-provider-ablations`; the primary
  experimental checkout remains untouched. GitHub remains the backlog.
- Pre-flight: #76 consumes #74 benchmark metrics and #78/#80 provenance/input
  hashes. Coverage must distinguish scanned negative results from no processing,
  and must align to the same independently reviewed source/time windows.
- Ruling: new `benchmark ablate` evaluates declared baseline, individual-provider
  and combination runs using the existing benchmark runner; no model download or
  provider enablement is implicit. Coverage failures are not valid ablations.
- Ruling: sparse frame processing must report temporal coverage, not just claim
  full source coverage from one frame. Candidate-scoped learned/judge/heuristic
  providers must disclose their restricted scope; clip judging is annotation-only
  in the current scorer and cannot claim selection improvement.
- Ruling: default/profile recommendations require real independent, sufficiently
  sampled, controlled evidence. Synthetic evidence remains experimental; missing
  provenance/binding/costs are explicit limits, never fabricated measurements.
- Requested the missing benchmark project paths and independent annotations
  asynchronously; implementation can continue while production evidence is
  being gathered. Existing shortlist decisions do not establish full recall.

- #76 implementation: `benchmark ablate` / `evaluate_provider_ablations` writes
  identity-separated scorecards with quality/candidate deltas, cost scope,
  dependency diagnostics, source/unit/time coverage, and explicit confounds.
  Historical manifests must bind artifact inputs and ratings outputs; legacy
  config-only bindings remain provisional. Changed thresholds, undeclared inputs,
  failed providers, partial/empty/low coverage, and source changes cannot earn
  causal credit. No defaults are applied.
- Default/profile/removal evidence rules are deterministic and tested, including
  harmful quality-failed candidates and conflicting results within one profile.
  Clip judging is annotation-only. Learned scoring measures baseline candidate
  windows only; it cannot claim raw-footage discovery coverage.
- OpenCLIP now emits sampling-support coverage, rejects invalid encoder matrices,
  and never caches incomplete/failed inference as successful. Motorsports/topics
  record all inspected candidate/transcript-hit units, including negative results.
  YOLO/OCR/face-person native coverage instrumentation remains pending; old
  artifacts still work for rating but are not valid production ablations.
- Test-first evidence reproduced missing CLI/coverage, config/binding confounds,
  mixed-revision scorecards, premature recommendations, malformed policy counts,
  absent negative-scan evidence, incomplete inference caching, and missing
  generated-run telemetry. Actual runtime testing also exposed review windows
  beyond known media duration; a failing regression now rejects these.
- Python 3.12: 177 tests passed (27 added to the previous 150). Whitespace,
  structural schema policy checks, wheel/source build, and core-only wheel
  doctor/operations/modules checks passed. Import did not load optional libraries.
- Installed OpenCLIP 3.3.0 ran entirely offline with the existing local checkpoint:
  4.25 seconds cold, 2.51 seconds warm, one actual source-cache hit. The complete
  artifact -> rating -> ablation path verified input/output hashes and full
  sampling-support coverage for a one-second synthetic fixture; F1 delta was 0,
  correctly classified experimental. This is compatibility evidence, not
  real-footage quality or an optimization claim.
- CodeRabbit reviewed all 20 changed files and raised one minor issue: heuristic
  artifacts with no input units reported `ok`. A failing regression reproduced
  both providers; empty processing is now `partial`. Final suite: 178 tests.

## Remaining Execution Order

Follow the dependencies recorded on GitHub: protocol and runner (#73/#74),
shared provenance and manifests (#78/#80), benchmark runs and ablations
(#75/#76), measured optimizations (#77), handoff consolidation (#72/#79),
then release-candidate qualification (#81).
