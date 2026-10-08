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

## Remaining Execution Order

Follow the dependencies recorded on GitHub: protocol and runner (#73/#74),
shared provenance and manifests (#78/#80), benchmark runs and ablations
(#75/#76), measured optimizations (#77), handoff consolidation (#72/#79),
then release-candidate qualification (#81).
