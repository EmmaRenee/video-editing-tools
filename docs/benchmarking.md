# Footage Benchmark Protocol

V17 uses `videoedit benchmark` to measure editing value across projects.
The protocol is local-first and works without optional models. GitHub
milestone 13 tracks implementation and required real-world evidence.

## Commands

```bash
videoedit benchmark validate benchmark.json
videoedit benchmark run benchmark.json --output analysis/benchmark-baseline/
videoedit benchmark compare analysis/benchmark-baseline/benchmark_report.json \
  analysis/benchmark-candidate/benchmark_report.json --output analysis/benchmark-compare/
```

The `run_benchmark` and `compare_benchmarks` pipeline operations belong to
the always-enabled `core.calibration` module. A pipeline dry run plans
artifact paths without reading footage, loading models, or writing files.

## Manifest V1

The structural JSON Schema is
`tests/fixtures/benchmarks/manifest.schema.json`. `benchmark validate` also
checks semantic constraints that JSON Schema cannot express: unique IDs,
finite parsed timecodes, positive interval length, and declared provider
references. The CLI validator does not require the `jsonschema` package.

Paths are resolved relative to the manifest. Keep real manifests, source
files, annotations, and review decisions in a private project directory.
Project/run IDs are public aliases: use `project-01`, not a customer name.

```json
{
  "schema_version": "videoedit.benchmark.v1",
  "suite": "production-validation",
  "review_limit": 25,
  "projects": [
    {
      "id": "project-01",
      "profile": "interview",
      "annotations": "annotations.json",
      "review": {
        "reviewer": "editor-01",
        "origin": "human",
        "independent": true,
        "windows": [
          {"source": "interview.mp4", "start": 0, "end": 600}
        ]
      },
      "runs": [
        {
          "id": "baseline",
          "role": "baseline",
          "ratings": "analysis/ratings.json",
          "providers": [],
          "decisions": "review/review_decisions.json"
        },
        {
          "id": "openclip",
          "ratings": "analysis-ai/ratings.json",
          "providers": ["openclip"],
          "provider_artifacts": {"openclip": "analysis-ai/ai_frame_scores.json"},
          "run_manifest": "analysis-ai/pipeline_run.json"
        }
      ]
    }
  ]
}
```

Supported profiles are `interview`, `motion_event`, `general_broll`,
`shop_build`, `documentary`, and `social`. Every project requires exactly
one baseline. Every run uses exactly one of `ratings` (consume an existing
artifact) or `footage` (invoke `videoedit rate`). Footage mode accepts an
optional `config` JSON path and stores intermediate private artifacts in
`OUTPUT/.private/PROJECT/RUN/`. It does not invoke providers automatically;
generate their artifacts first and reference them in the rating config.

Each declared provider requires a `provider_artifacts` entry. Missing,
unavailable, failed, malformed, or partially failed artifacts cannot become
a successful benchmark run. Provider artifact and metadata hashes are
recorded without copying prompts, transcript text, model paths, or secrets.
An explicit `run_manifest` must describe a successful execution.

`telemetry` may declare `elapsed_seconds`, `cache_hits`, `cache_misses`, and
`storage_bytes`. These must be finite and nonnegative. A run manifest may
provide the same fields in its `telemetry` object. Footage mode measures
rating elapsed time directly. Existing pipeline `duration_seconds` is
imported when manifest telemetry does not contain `elapsed_seconds`.
Values from a manifest or declared telemetry
are identified by origin; absent measurements are JSON `null`, not zero.
Do not use declared timings as measured production-performance evidence.

## Human Ground Truth

1. Choose representative sources before inspecting predicted candidates.
   Sample different cameras, lighting, audio conditions, shot durations,
   and content types. Include quiet but valuable moments and high-energy
   footage with no editorial value.
2. Record reviewed time windows and watch their complete contents. Log
   reviewer identity locally and mark `independent: true` only when the
   reviewer selected positives before viewing the automated shortlist.
3. Annotate every useful moment in the windows, including moments absent
   from the shortlist. Use `select`, `review`, or `broll` for positives;
   `reject` or `cut` for negatives; `ignore` for unresolved material.
4. Add purposeful tags such as `quote`, `action`, or `detail`. Keep private
   transcripts and notes locally. Do not use model-generated labels as
   human ground truth.
5. Include negative ranges and retain the same annotations across compared
   configurations. Review-decision conversion is useful for precision, but
   shortlist-only decisions cannot establish independent recall.

The existing `videoedit calibrate from-decisions` command can convert
explicit decisions to annotation JSON. Supplement it with manually found
misses and full reviewed-window coverage before qualifying a recall result.
Synthetic fixtures use `origin: synthetic` and never qualify a release.

## Scope And Matching

Review windows are normalized with calibration's source resolver, including
exact, relative, absolute, and unique-basename matches. Overlapping and
adjacent windows are unioned per source so reviewed duration is not counted
twice. An annotation outside a declared window invalidates the run.

Candidates are sorted by descending score, then canonical source, start
time, and ID. Only candidates fully contained in reviewed windows count
in the quality sample. Candidates crossing a window edge or lying outside
reviewed time are excluded and counted separately. Choose windows with
room for expected clip handles to avoid a boundary-heavy sample.

V1 uses the existing `calibration_overlap_v1` matcher: same source, positive
temporal overlap, and one candidate per positive annotation. Match choice
uses largest overlap, then score, then ranked order. `select`, `review`, and
`broll` candidates count as predicted positives. Unmatched predicted clips
overlapping ignored annotations are excluded from false positives.

This compatibility metric does not prove editorially precise clip
boundaries: a brief overlap can match a much longer clip. Inspect boundaries
and false-positive explanations as part of real-footage acceptance; a
future stricter matching protocol requires a versioned comparison basis.

## Metrics

| Metric | Definition |
| --- | --- |
| Precision | Matched positive candidates / (matched positives + false positives). |
| Recall | Matched positive annotations / all positive annotations in the reviewed windows. |
| F1 | Harmonic mean of precision and recall; zero if both are zero. |
| Recall at review limit | Recall when only the first `review_limit` scoped candidates are available, using the same one-to-one matcher. |
| Recall at N | Existing calibration recall at 5, 10, 25, 50; this legacy supplementary metric uses independent annotation coverage and may differ from one-to-one recall. |
| Human acceptance rate | Explicit approve/select/b-roll decisions divided by explicitly approved or rejected/cut scoped candidates. Undecided `review` and `ignore` choices are excluded. Null when explicit decisions are absent. |
| Candidate count | Number of candidate ranges inside reviewed windows, including cut actions; predicted-positive counts remain available through calibration metrics. |
| Reviewed seconds | Union length of declared windows, summed across sources. |
| Cache hit rate | Hits / (hits + misses); null if counters are absent or total zero. |
| Runtime | Measured elapsed rating seconds in footage mode, or explicitly identified imported telemetry. |
| Storage | Measured or declared output bytes; null when unavailable. |

Reports include per-source quality metrics and per-tag recall. Sources and
tags use stable aliases within a fixed review basis (`source_001`,
`tag_001`); consult the private manifest/annotations to interpret them.
No raw reviewer names, filenames, paths, notes, tag text, or transcripts
are copied into the public JSON/Markdown/CSV report.

## Provisional Quality Gates

Per-profile default sampling requirements are 600 reviewed seconds, 20
positive annotations, 20 negative annotations, and 3 reviewed sources.
Initial quality targets are precision >= 0.70, recall >= 0.70, and
F1 >= 0.70. Override these through `quality_gates` for a contract fixture or
an exploratory run; document changes when reporting production evidence.
These are provisional thresholds to calibrate from #75, not a measured
claim that the current tool reaches them.

`insufficient_evidence` indicates missing sample coverage or dependent
review. `quality_failed` indicates sufficient samples below targets.
`synthetic` indicates artificial ground truth. `failed` indicates unavailable
or invalid input/provider execution. A production suite can be `ok` only
with at least three distinct profiles, including `interview` and
`motion_event`, and successful human evaluation.
V17's manual evidence audit additionally requires actual human review provenance and measured
telemetry; a self-declared JSON manifest is not independent proof.

The CLI returns nonzero on validation errors and failed executions.
Exploratory `synthetic`, `insufficient_evidence`, and `quality_failed` reports
are successfully generated with exit zero so they can be inspected. Release
automation must inspect the report status and all required evidence gates.

## Outputs And Comparisons

- `benchmark_report.json`: versioned projects/runs, metrics, gates,
  diagnostics, provider fingerprints, input/config/command hashes, telemetry.
- `benchmark_report.md`: redacted quality summary.
- `per_source.csv`: source aliases, reviewed duration, precision/recall/F1,
  true/false positives, and misses.
- `benchmark_compare.json` and `benchmark_compare.md`: quality deltas for
  each candidate run against its project's baseline in the first report.

Identical baseline rows are omitted. A changed baseline-only report still
gets a comparison row, supporting before/after evaluations from separate
manifests. Missing baselines or fingerprints are invalid reports.

Comparisons require the same protocol, project IDs, profile, review limit,
annotations, windows, reviewer basis, and quality gates. Changed ground
truth invalidates a direct comparison. Configuration/provider changes are
the independent variable. Reconsuming identical artifacts yields stable
report data; freshly measured runtime varies and is reported as telemetry.

For ablations, hold annotations, windows, sampling, config, and limits
fixed; compare deterministic baseline, each provider alone, then justified
combinations. #76 adds provider coverage and empty-artifact scorecards;
#77 measures warm/cold runs and cache improvements. Never infer a benefit
from the presence of an artifact or a model label alone.

## Synthetic Verification

```bash
PYTHONPATH=src/python python -m videoedit.cli benchmark validate tests/fixtures/benchmarks/manifest.json
PYTHONPATH=src/python python -m videoedit.cli benchmark run tests/fixtures/benchmarks/manifest.json --output /tmp/videoedit-benchmark-smoke
python -m unittest discover -s tests/python -p test_videoedit_benchmark.py
```

The fixture contains two positive annotations, one negative, a true
positive and a false positive, and a higher-scored unreviewed candidate.
Its scoped precision/recall/F1 are 0.5. It is a contract test, not real
footage validation or an AI-quality result.
