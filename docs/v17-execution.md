# V17 Execution Record

Source of truth: milestone 13 and umbrella issue #66. This is implementation
evidence and design rulings, not a second backlog.

## Rough-Cut Bounds Slice

- Previous turn: PR #95 / `8ba94bb`, 325 tests, 33 independent-reader checks,
  five CI jobs and final CodeRabbit 0 issues; unmerged. Refreshed milestone 13,
  #66/#79 before branching `codex/v17-roughcut-bounds` in the isolated clone.
- Pre-flight: plans consume normalized selections and feed FFmpeg assembly and
  the shared handoff timeline. Normalization alone hid mixed-rate SMPTE ambiguity;
  the original selection rows must reach native-rate validation before handles.
- Ruling: invalid approved ranges fail before adding handles; only requested
  pre/post-roll is clamped to zero and known video extent. Unknown duration stays
  null/partial, not a claimed bound. Preserve source metadata and unsupported edit
  features instead of discarding them during plan/assembly conversion.
- Ruling: targets trim elapsed tail endpoints, including sub-second remainders.
  Applied handles are recalculated and original approved ranges remain visible.
  Zero-frame first clips fail; a sub-frame remainder after valid clips is omitted.
  Targets can trim approved content, which is explicitly flagged, not hidden.
- Eighteen focused tests cover source bounds, target tails, invalid finite-number
  controls, path resolution/ambiguity, source metadata conflicts, legacy SMPTE,
  one probe per source, unknown-duration partial status and unsupported features.
  Tests reproduced the defects before fixes. The old missing-media manifest
  expectation was corrected from `ok` to `partial`; no metadata is fabricated.
- Local suite: 343 tests passed, one optional-reader skip. All 33 independent
  interchange-reader checks passed. Wheel/source builds and whitespace passed.
- User authorized Lexar: a separate validation directory holds only generated
  fixtures/outputs. A hash-verified synthetic copy rendered bounded handles to
  120 frames / 5.0 seconds and a sub-second target to 12 frames / 0.5 seconds;
  both retain a stereo audio stream. These checks do not establish audio fidelity,
  real-footage editorial quality or live editor compatibility.
- Real interview copy stalled on a Google Drive `compressed,dataless` placeholder
  with zero bytes written. The agent's process was stopped; the empty destination
  was marked `.part`, not presented as media. Original media was not modified.
  Resolve GUI is reachable but an edited Untitled project is left untouched;
  read-only external SDK attachment remains unavailable. Live relink validation,
  independent three-profile annotations/ablations and final RC gates remain open.

## Source-Aware Interchange Slice

- Previous turn: PR #94 / `7e928e3`, 258 tests and four CI jobs passed;
  unmerged. Refreshed milestone 13, #66/#79 and PR review state before branching
  `codex/v17-interchange-exports`. Primary experiments/media remain untouched.
- Ruling: correct the existing supported CMX/FCP7 exports without promoting the
  alternate Shoot/Resolve architecture. OTIO adapters are independent validation
  readers only; runtime dependencies remain FFmpeg/ffprobe plus the standard
  library. Optional runtime OTIO/Resolve integration remains separately gated.
- A shared versioned native-rate timeline now feeds EDL, XML and handoff mapping.
  Unique local sources are probed once for rational FPS, video-stream extent,
  dimensions, embedded timecode and audio. Reel identities are bounded and
  collision-checked; XML file URLs are escaped/encoded and repeated files use
  references. Known mono/stereo streams generate linked XML audio tracks.
- Standard single-line CMX event columns and FCM replace the legacy EDL layout;
  FCP7 media clip/file items replace generator items. XML separates native
  source in/out from timeline start/end, including fractional and mixed rates.
  VLC playlists now use numeric seconds without six-digit precision loss.
- Missing metadata remains unknown/partial. Unsupported mixed-rate or mixed
  DF/NDF EDLs contain no edit events and are explicitly diagnostic-only; XML is
  still emitted. CLI warnings surface partial/non-importable exports. Effects,
  retiming, compound clips, multistream/surround audio and video-only EDL limits
  remain explicit rather than silently claimed as supported.
- Test-first checks reproduced invalid EDL columns, unescaped XML, missing audio,
  absent source TC/rate mapping, lossy playlists, URI privacy leakage, ambiguous
  relative relinks and invalid XML text before fixes.
- Independent review reproduced four further defects: file-level SMPTE parsing
  before native-rate probing, container duration extending video, a rounded EOF
  overrun and DF midnight overflow. New red regressions passed after targeted
  fixes. Mixed-rate SMPTE file bounds without `source_fps` are rejected rather
  than silently reinterpreting legacy loader semantics; numeric bounds win.
- Actual synthetic MOVs use built-in MPEG-4/PCM: 24 fps/stereo/nonzero NDF, and
  30000/1001 fps/mono/nonzero DF. A separate 1s-video/3s-audio MOV proves audio
  cannot extend the video selection. No hard `libx264` dependency for these tests.
- An available private 300-second interview probes at 30000/1001, embedded DF TC,
  4096x2160 and stereo PCM. Two engineering windows exported as 127 record frames
  and two linked audio tracks. Integer and fractional synthetic exports contain
  54 and 60 record frames respectively. These are engineering windows, not human
  editorial ground truth. Two old approved-file references are missing; neither
  the originals nor their historical selection files were altered or guessed.
- Independent OTIO 0.18.1, FCP adapter 1.0.0 and CMX adapter 1.0.0 read the three
  actual generated exports. URLs/source timecode/ranges and mono/stereo track
  structure matched, with XML native endpoints within one frame. This does not
  prove editor codec support, real-media relink, audio fidelity or live import.
- Local verification: 321 Python 3.12 tests passed, one optional-reader skip in
  the core-only environment; all 29 focused interchange tests passed separately
  with the readers installed. Whitespace, wheel/source build and fresh core-only
  wheel doctor/operations/modules checks passed. Installed-wheel CLI exported
  all three runtime fixtures. A separate CI reader job was added; no heavy
  provider was made a core dependency. Private outputs remain outside Git.
- Remaining #79/#81/full-goal gates: actual Resolve import/relink/timecode/audio/
  handles, approved optional adapters, representative independent three-profile
  quality/ablation evidence, and final RC qualification. No issue closes from
  format-reader or synthetic evidence alone; nothing is merged or published.
- Draft PR #95 from #94 passed all five CI jobs on its initial revision,
  including independent interchange readers. CodeRabbit reviewed all 17 files
  and raised one minor record-day calculation issue. A failing long-duration
  mixed-rate regression reproduced it; record-day limits now use the same
  supported timeline DF/NDF mode as the EDL writer and mapping. Latest local
  suite: 322 tests; 30 independent-reader checks passed. Wheel/source build,
  core-only reinstall and the three installed-CLI runtime exports/readback
  checks passed again. Final committed re-review/CI remain pending.
- Follow-up independent review reproduced unsupported 120-fps CMX labels and a
  valid alias resolving to an XML-invalid filename. Red tests include an actual
  on-disk POSIX symlink. Both are fixed with tested-rate gating and resolved-path
  validation. Independent re-review reports no remaining concrete findings;
  all ten supported CMX rates and five unsupported-rate combinations were
  independently parsed/rejected as appropriate. Full suite/actual symlink/live
  editor were not run by that read-only reviewer; local tests cover the first
  two, while live editor remains outstanding.
- CodeRabbit's second completed pass raised one major invalid-DF-rate issue,
  but it does not reproduce: the existing `timecode_to_seconds` rejects DF25
  and DF23.976 before creating a source. A regression verifies that existing
  guard without introducing a redundant validator. Latest local suite: 325
  tests, one optional-reader skip; all 33 focused reader tests pass, covering
  every advertised CMX rate and XML 120 fps. Wheel/source build, core-only
  reinstall and three installed-CLI exports passed after the final fixes.

## Selection Timebase Slice

- Previous goal turn: verified progress, PR #93 / `f789585`, 224 local tests
  and four CI jobs passed. Refreshed milestone 13, #66, #71/#72/#79 and #93
  review state before branching `codex/v17-editor-handoff`; no merge.
- Pre-flight: selection writers produce boundaries consumed by planning,
  extraction, assembly and export. A loader-only fix cannot recover precision
  already discarded by upstream writers, so each delivery writer is covered.
- Ruling: repair existing supported timing first; this is not implicit approval
  of the experimental Shoot/Resolve architecture. Optional SDK/OTIO adaptations
  remain proposed work, subject to the disposition and PR review gates.
- Root-cause reproduction: SMPTE frames were ignored, frame rounding dropped
  second carry, seconds-only subsecond clips collapsed to zero length, approval
  and selection writers discarded numeric bounds, and plans sent whole-second
  strings rather than their saved decimal bounds to FFmpeg.
- Ruling: numeric `start_seconds`/`end_seconds` are authoritative; display text
  may be truncated. Timing is an elapsed media offset, not an embedded source
  start timecode. Decimal NTSC aliases use exact rational media rates internally;
  NDF formatting uses nearest-frame, half-up quantization. Drop-frame input
  validates skipped labels; output remains explicitly non-drop-frame.
- Ruling: preserve elapsed precision through delivery instead of rounding each
  plan to milliseconds. Legacy whole-second-only files cannot be reconstructed;
  regenerate from original ratings and decisions rather than inventing bounds.
- Test-first: new checks reproduced timing/validation failures before fixes,
  then exposed four upstream writers and submillisecond script truncation.
  An actual 24 fps synthetic FFmpeg render of [0.125, 0.875) independently
  probes at 18 frames / 0.75 seconds. This is timing evidence, not editor fidelity.
- Independent read-only feasibility check: Resolve 20.3.2, macOS SDK and native
  library are installed. Installed manual/SDK document native OTIO import/export.
  Python OTIO is absent; active Studio/license, external scripting permission
  and live API connection remain unverified. No app/project/settings changes.
- Remaining #79 gates: replace legacy EDL event columns and XML generator items;
  source-start timecodes, media identity/relink, audio, mixed FPS, handles bounds,
  optional approved adapters and actual real-project editor import verification.
- Verification: 249 Python 3.12 tests passed, including 25 focused timing tests;
  wheel/source build and a fresh core-only install passed. Installed CLI approval
  -> planning -> rendering preserved [0.125, 0.875); independent FFprobe reports
  18 video frames / 0.75 seconds at 24 fps. AAC audio remains present with its
  codec padding; this is not an audio-layout/editor fidelity assertion.
- Installed-wheel doctor, operations, module listing, timing helpers and handoff
  generation passed. Redacted handoff/assembly diagnostics contain no private
  runtime root and retain exact requested bounds and `editor_verified: false`.
  Core imports do not load Torch/OpenCV/Ultralytics/OpenCLIP/Whisper.
- CodeRabbit reviewed the 13-file slice and raised zero issues. Primary tracked
  files remain untouched; synthetic inputs and generated delivery outputs live
  outside Git. No V17 issue is closed based on this timing evidence alone.
- Fresh agent review identified two timing regressions missed by that review:
  float-derived half-frame ties and independently rounded EDL record duration.
  A third finding restored the still-valid legacy fractional XML warning.
  Regression tests failed on all three before fixes. EDL source/record spans
  now share one integer-frame cursor, also used by the handoff mapping.
- Ruling: interpret up to two floating-point ULPs at a half-frame boundary as
  representation noise, capped at 1e-9 frames. Large integer and truly below-tie
  tests prevent that tolerance from inventing frames. Invalid overflowing FPS
  also has a targeted validation failure instead of an overflow traceback.
- Read-only external SDK probe returned no Resolve connection. No application,
  project or security setting was changed; no reason for unavailable attachment
  is inferred. Live-editor evidence remains outstanding.
- Fresh review also noted the preexisting subsecond target-duration minimum;
  source-bound/handle/target policy hardening remains separate from this slice.
- CodeRabbit's second whole-slice review raised one valid XML duration issue:
  flooring each elapsed duration disagreed with the legacy endpoint frame spans.
  A failing two-clip regression reproduced 104 declared frames vs 106 on track.
  The existing track accumulator now supplies the sequence duration; this does
  not remove legacy generator-item or fractional-rate limitations.
- Final local verification: 256 tests passed (32 timing checks added to the
  previous 224), whitespace check, wheel/source build and core-only wheel
  install passed after fixes. Installed-wheel quantization/EDL/XML assertions
  passed; the rendered synthetic output remains 18 frames / 0.75 video seconds.
- Scoped re-review verified the original findings were fixed, then reproduced
  extreme scientific-notation integer drift and finite frame-total overflow.
  Regression tests failed before switching to exact integer/binary-float inputs
  and guarding the ULP conversion. CodeRabbit's third pass raised only a render
  test portability issue: the test now checks `libx264` and skips unsupported
  FFmpeg builds, with a simulated missing-encoder regression.
- Latest verification after those fixes: 258 tests passed, including 34 timing
  checks; source/wheel build, core-only install and installed numeric boundary
  checks passed again. No production-quality or live-editor gate is waived.

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

## Shared Frame And Vision Coverage Slice

- Previous goal turn: verified progress, PR #91 / `acfb974`, 178 local tests,
  clean-wheel workflow, CodeRabbit fix, and four CI jobs passed. Refreshed #66,
  milestone 13, #77, and prerequisite review feedback before starting.
- Isolated `codex/v17-shared-frame-cache` from #91; primary experiments and media
  remain untouched. GitHub remains the backlog; this is an execution ledger.
- Pre-flight: #77's shared decoded samples feed optional providers and #76's
  processing-coverage contract. Frame identity must exclude model/prompt identity
  (so providers can reuse decoding), while inference identity must include it.
- Ruling: retain full-resolution OCR/face samples and 336px OpenCLIP samples as
  distinct cache formats. Reuse only compatible sampling/format settings; forcing
  OCR into AI-sized thumbnails would risk reducing signage detection quality.
- Ruling: cache entries are atomically published only after all requested samples
  complete and pass integrity checks. Interrupted/partial outputs are diagnostics,
  never reusable successful entries. Cache paths include source and decoder/config
  fingerprints, not only basenames; private frames and source paths stay local.
- Work: shared sampler/CLI/operation and measurable cache behavior; integrate
  OCR/face/AI consumers and truthful vision coverage; measure actual cold/warm
  reuse and selection parity before claiming performance improvement.
- Independent real-footage annotations and final editor/RC evidence remain
  required. Existing shortlist review cannot substitute for full-window recall.
- Implemented `signals sample-frames` / `sample_frames`, atomic complete-entry
  publication, concurrent repair locking, source/decoder/format keys, integrity
  checks, optional strict SHA-256, explicit timestamps, and scoped cache telemetry.
  Source changes during warm verification are rejected, not silently reused.
- Native OCR/face/AI consumers share compatible images; OCR/face emit negative
  processing coverage and explicit hit times. Failed inference/classifier setup
  cannot masquerade as zero detections. AI separates frame and inference counters;
  model initialization still occurs once per invocation even on a warm run.
- Fixed native `face_person_presence` artifact validation independently of the
  `face_person` configuration binding. Existing OCR/face source-wide scoring
  remains unchanged; no defaults or production recommendations were changed.
- Test-first regressions reproduced missing sampling, stale/foreign frame paths,
  incomplete inference, concurrent repair failure, source mutation during warm
  verification, and incorrect face-artifact ablation exclusion. Compatible pipeline
  prewarming requires matching quotas (six for default OCR/face, eight for AI).
- Actual private interview derivative, 300.033 seconds, two samples at 5/15
  seconds: FFmpeg 9.0.1 independently confirmed 4096x2160 full-resolution JPEGs.
  Fresh and reused JPEG checksums matched; storage was 1,427,112 JPEG bytes.
  OCR cold total 16.01s, a hydrated-source fresh extraction 4.37s, shared reuse
  0.67s; OCR hits and coverage matched exactly. Single-run timings include
  OS/cloud cache effects and do not establish general performance guarantees.
- Native OpenCV 4.13.0 face/person processing reused both images without decoding,
  emitted complete two-unit sampling coverage and two positive frames, but took
  175.00s. Full-resolution detector cost/budgets remain unresolved; detection
  accuracy and counts have not been independently validated.
- Actual OpenCLIP 3.3.0, verified local checkpoint, fully offline: cold extraction
  plus inference 8.98s, frame-reuse with inference deliberately recomputed 4.33s.
  Scored source payloads and coverage matched exactly. Two 336px images used
  31,051 JPEG bytes, distinct from the full-resolution cache format.
- These are runtime/image/provider-output parity checks on a preselected private
  clip, not independent selection-quality/recall benchmarks. #75/#77 remain open
  until representative quality and remaining provider/lifecycle evidence exist.
- CodeRabbit reviewed 17 files and raised one minor cleanup issue. A failing
  regression proved staging cleanup could mask `KeyboardInterrupt`; best-effort
  cleanup now preserves the original interrupt and never publishes the stage.
- Final verification: 196 Python 3.12 tests, whitespace check, wheel/source build,
  clean core-only wheel doctor/operations/modules, and real JPEG cold/warm sampling.
  Core import loaded no Torch, OpenCLIP, OpenCV, Ultralytics, or Whisper modules.
  All private runtime artifacts stayed outside Git and the primary checkout.

## Native YOLO Lifecycle Slice

- Previous turn: verified progress, PR #92 / `dcf3d86`, 196 local tests,
  clean-wheel checks and four CI jobs passed; unmerged. Refreshed #66/#76/#77,
  milestone 13 and prerequisite review feedback before continuing.
- Reused the isolated clone on `codex/v17-yolo-lifecycle`; primary experimental
  files and private footage remain untouched. Execution/TDD is inline because no
  subagent tool is available; the GitHub issues remain the specification.
- Pre-flight: native visual-object artifacts must preserve the existing scorer's
  `sources`/`segments` contract and supply #76 processing evidence; #77 cache
  identity must bind media, checkpoint, library/decoder and inference settings.
- Ruling: retain the legacy command backend and add an explicit native backend
  using one Ultralytics instance per invocation. Native weights must already
  exist locally; no silent model download or new mandatory dependency.
- Ruling: continuous native video inference is not replaced with easier sparse
  frame sampling. Count successful negative frames independently of detections;
  unknown frame totals or timing cannot claim production temporal coverage.
- Ruling: only complete source scans with validated cache integrity are reusable;
  failures/interruption/source mutation remain diagnostic outputs. Model warmup
  is avoided entirely for an all-cache-hit invocation, never reported as done
  unless the model really initialized.
- Work: native continuous processing, coverage/provenance/cache instrumentation,
  command-run isolation and honest diagnostics, actual local-checkpoint cold/warm
  and repeated-inference measurements, then whole-branch review and CI.
- Native scans now verify decoded presentation timestamps in a separate cold
  ffprobe pass rather than inferring CFR from matching nominal FPS fields. VFR,
  bad results, missing totals/timing, interruption and changed inputs cannot
  publish complete caches. CPU/float32 is explicit; optional MPS needs evidence.
- Tests cover negative scans, incomplete/invalid frames, source/checkpoint/config/
  provider invalidation, cache corruption, interrupts, same-basename isolation,
  pipeline/CLI wiring, bounded online summaries and legacy top-500 tie parity.
  Actual FFmpeg fractional-FPS/nonzero-origin timing passed. 219 tests passed.
- Private real-media runtime, two 2-second 640px/10fps derivatives with identical
  basenames: Ultralytics 8.4.90 / Torch 2.12.1 / OpenCV 5.0.0.93 / ffprobe 9.0.1.
  One model, 40 native frames plus 40 timing-probe frames, 80 detections; cold
  14.64s (13.0s model/import/font setup), warm 0.06s (two hits/no model/no decode),
  recomputed inference 0.97s. Source/coverage/detection summaries matched exactly.
  Final implementation rerun after import/font hydration: cold 2.37s, warm 0.05s,
  recomputed 0.96s; same counts/coverage, one initialization attempt on misses and
  none on hits. Failed model initialization is not retried for every source.
  The legacy command bridge produced identical class/segment totals; its timing
  coverage remains provisional. All three cache states yielded the same two
  rating candidates; these short-window candidates were cuts, not quality wins.
- The original cloud-venv check stalled reading Torch Python files (confirmed by
  process sampling), was interrupted, and was replaced with the existing local
  model environment. No primary files/environments were edited or models fetched.
- These are single-machine runtime/parity checks, not independent provider
  accuracy or representative quality improvements. Private sources, weights,
  scripts and artifacts stayed under the local runtime directory/outside Git.
- Whole-diff CodeRabbit review raised three issues. Red tests (including a real
  fractional-FPS MKV) reproduced the CFR quantization bug, missing-stream
  diagnostics and quoted cache booleans. Fixes account for container timebase
  ticks without accepting coarse clocks or real cadence changes; native/AI
  operations parse true/false explicitly. An author-review corruption test also
  proved malformed cache indices could abort scans; they now trigger recompute.
- Final corrected-diff CodeRabbit review raised zero issues. 224 Python 3.12
  tests passed; wheel/source builds and a clean core-only wheel's doctor,
  operations and modules commands passed. Missing native dependencies were
  diagnosed without importing Torch/OpenCLIP/OpenCV/Ultralytics/Whisper.
- Post-review actual runtime rerun: cold 3.66s, warm 0.05s, recomputed 0.92s;
  same 80 detections/40 frames and exact source/coverage parity. Repeat legacy
  summary and rating-candidate comparisons also passed. Warm-up, OS and font
  caches affect these timings; none establishes independent selection quality.
- Independent three-profile annotations, detector-budget work, editor handoff and
  final RC qualification remain full-goal gates, not replaced by runtime smoke.

## Clean-Install Validation Slice

- Continued on the isolated clone from PR #96 (`b9cb060`), leaving the primary
  experimental checkout, private originals and the user's open Resolve project
  untouched. GitHub milestone 13 and #66/#71/#81 remain the acceptance source.
- Added a developer-only wheel/source auditor: compare tracked runtime and
  compatibility file bytes to Git, reject unexpected/unsafe/duplicate/link
  members, verify version, console entrypoint and license. Build from a Git
  archive, never the checkout containing untracked experiments.
- Added an installed core-only synthetic workflow outside the checkout. It
  exercises rating/cache, review/proxies, decisions/approval, bounded planning,
  actual rendering, EDL/XML and missing optional-provider diagnostics, recording
  versions, per-step timings, logs and scoped storage. Synthetic checks never
  certify independent selection quality or live-editor behavior.
- The first smoke exposed a real false-success: FFmpeg 9.0.1 rejected obsolete
  scene-analysis `-vsync`, but rating reported `ok` and cached empty detections.
  A real black/white fixture reproduced the failure before the fix. Removed the
  unnecessary sync option from null-output analysis, added explicit per-detector
  completion status, partial-run reporting and cache retry rules. Legacy JSON
  remains readable; legacy caches without health evidence reanalyze once.
- The stricter installed smoke rejects the old wheel rather than accepting its
  fallback candidate. Successful empty detections and audio-free sources still
  complete normally; missing required transcripts and failed requested detectors
  cannot be cached as successful analysis. Old benchmarks with detector warnings
  must be rerun, not retroactively treated as healthy quality evidence.
- Expanded CI to eight jobs: Python 3.10-3.12 unit and installed-workflow matrices,
  tracked-snapshot distribution audit/build, and independent editor readers.
  Official actions are pinned by immutable revision, with an explicit Ubuntu
  24.04 baseline, read-only token and no persisted checkout credentials.
- Proposed `0.6.0rc1` only as a pending-review candidate; no version change, tag,
  release or publication. Independent three-profile ground truth, provider
  quality/cost ablations, approved experimental dispositions and actual original-
  media Resolve relink/timecode/audio/boundary/handle verification remain gates.
- Independent review reproduced four qualification gaps: recovered decoder errors
  were still cacheable, review rows could hide missing media, extra wheel console
  scripts were accepted, and ZIP directory-name handling bypassed link checks.
  Red tests and actual proxy fault injection verified them before repair. Analysis
  now stops on decoding errors, the smoke checks real review files/manifests and
  corrupted-media retries, and the auditor validates full entrypoint mappings and
  member types/duplicate names before skipping directories. Green initial CI or a
  zero-issue automated review did not override independently reproduced failures.
- Ubuntu CI caught an additional real version-specific recovery path. An isolated
  official Ubuntu 24.04 container reproduced FFmpeg 6.1.1 logging decoder errors
  while returning zero even with `-xerror`, `-max_error_rate 0` or `explode`.
  Severity-prefixed logs now supplement exit status without interpreting arbitrary
  error-like text in info messages. Cache policy v2 invalidates earlier results;
  the corrupted-media partial/no-cache gate remains unchanged.
- A further review reproduced chained logger-prefix and multiline-filename
  ambiguity. Measurements now use metadata stdout and error-only stderr;
  physical-line severity parsing supports complete context-prefix chains without
  reading info text as errors. Real multiline filenames, scene transitions and
  trailing silence have regressions. Cache policy v3 invalidates prior analyses.

## Remaining Execution Order

Follow the dependencies recorded on GitHub: protocol and runner (#73/#74),
shared provenance and manifests (#78/#80), benchmark runs and ablations
(#75/#76), measured optimizations (#77), handoff consolidation (#72/#79),
then release-candidate qualification (#81).
