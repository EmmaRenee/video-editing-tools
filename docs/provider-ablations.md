# Provider Ablations

This extends the [benchmark protocol](benchmarking.md) with controlled
optional-provider comparisons. GitHub issue #76 tracks production completion.

## Workflow

1. Rate fixed footage without optional artifacts (the baseline).
2. Independently annotate complete declared windows, including uninteresting
   material. Shortlist review alone cannot measure recall.
3. Explicitly generate artifacts and rate with one provider added, then selected
   combinations. Hold other scoring config, source fingerprints, hardware,
   sampling, and cache state constant. Declare runs in the same private manifest.
4. Evaluate and read quality, coverage, identity, and cost evidence together:

```bash
videoedit benchmark validate benchmark.json
videoedit benchmark ablate benchmark.json --output analysis/ablations/
```

Pipeline operation: `evaluate_provider_ablations` in `core.calibration`, taking
`input` (manifest) and `output`. Return keys: `report`, `markdown`, `scorecards`,
`status`, `effects`. Dry runs resolve paths without inference. No implicit model
downloads or enablement. Add run entries to the complete benchmark project:

```json
[
  {"id": "baseline", "role": "baseline", "ratings": "base/ratings.json",
   "run_manifest": "base/rating_run.json", "providers": []},
  {"id": "with-openclip", "role": "candidate", "ratings": "clip/ratings.json",
   "run_manifest": "clip/rating_run.json", "providers": ["openclip"],
   "provider_artifacts": {"openclip": "signals/ai_frame_scores.json"}}
]
```

Paths are relative to the benchmark manifest. The rating config must consume
the declared artifact's content. A successful `rating_run.json` binds historical
input hashes and the produced ratings hash; replacing either invalidates the
comparison. Legacy config bindings are provisional, not production enablement
evidence. Regenerate rating after input changes; never edit hashes as a shortcut.

## Providers

| ID | Rating input | Generation command |
| --- | --- | --- |
| `openclip` | `ai_frame_scores` | `videoedit ai score-frames` |
| `yolo` | `visual_objects` | `videoedit signals objects` |
| `ocr` | `ocr_signage` | `videoedit signals ocr` |
| `face_person` | `face_person` | `videoedit signals face-person` |
| `motorsports` | `motorsports_events` | `videoedit signals motorsports` |
| `topics` | `topic_clusters` | `videoedit signals topics` |
| `clip_judge` | `ai_clip_judgments_path` | `videoedit ai judge` |
| `learned_scorer` | `learned_scorer_path` | `videoedit ai train-scorer` |

Judge artifacts add explanations, not selection scores: `annotation_only`.
Learned-scorer coverage comes from scored candidate rows against baseline windows,
not its training model. Motorsports/topics inspect existing candidates/transcript
hits, not all raw media. Their `candidate` scope cannot support full-footage
default recommendations. Combinations receive combination-level credit only.

## Coverage Contract

Processing is distinct from positive detections. Successful negatives count;
missing, empty, partial, and insufficient coverage do not:

```json
{"coverage": {"schema_version": "videoedit.coverage.v1", "scope": "temporal",
  "sources": [{"source": "interview.mp4", "status": "ok",
    "expected_units": 2, "processed_units": 2, "intervals": [[0, 10], [10, 20]]}]}}
```

Sources use the benchmark resolver. Finite, nonnegative, nonempty intervals are
merged; only reviewed-window overlap counts. Source, processed-unit, and temporal
ratios are separate. OpenCLIP uniform midpoint cells represent at most half the
sampling interval on either side, clamped to duration: **sampling support**, not
continuous inference. A capped scan of a long source does not cover its full
duration. Invalid encoder dimensions/nonfinite scores and partial sampling are
not successful processing or reusable successful cache entries.

OpenCLIP, motorsports, and topics now emit coverage. YOLO/OCR/face-person artifacts
lacking it remain compatible with rating but are **not evaluated** as production
ablations. Native vision coverage instrumentation is still pending. Do not infer
full processing from detections or manually declare it. Missing dependencies
remain optional; diagnostics name generation commands and `videoedit modules doctor`.

## Outputs And Gates

Outputs: `ablation_report.json`, `ablation_report.md`, `provider_scorecards.csv`,
plus existing benchmark JSON/Markdown and `per_source.csv`. Different model/
prompt/config/sampling identities have separate scorecards. CSV summaries include
mean F1/precision/recall/candidate deltas, rating runtime/storage deltas, provider
generation time, and provider JSON size. Unknown values stay null/blank, not zero.
JSON-only provider bytes exclude weights/frames; run bytes cover tracked outputs,
not all caches/footage. Generation and rating times may overlap: do not blindly
sum them. Warm/cold cache conditions must be held constant and disclosed.

Recommendations change no defaults: `experimental`,
`profile_only_enablement_supported`, `default_enablement_supported`, or
`removal_supported`. Enablement needs independent human evidence passing sample
gates, verified historical bindings/provenance, temporal coverage, and measured
costs. Default/removal requires consistent effects across at least three profiles;
conflicting runs cannot support that profile's enablement. Synthetic evidence
always remains experimental. Quality-failed harmful candidates can still supply
removal evidence when independent sampling is sufficient.

Optional top-level `ablation_policy` defaults: `min_source_ratio`,
`min_temporal_ratio`, `min_unit_ratio` = `0.8`; `min_f1_delta` = `0.02`;
`removal_f1_delta` = `0.05`; `min_profiles_default`, `min_profiles_removal` = `3`.
Ratio/effect values must be in `[0, 1]`; profile counts are positive integers.
These provisional policy overrides never change rating or project defaults.

Report status: `not_evaluated` (no valid effects), `partial` (some invalid), or
`ok` (all declared effects evaluated). None means V17 completed. CLI success means
diagnostics were written; malformed manifests fail. Check benchmark/sample status
and recommendations before drawing conclusions. Keep private footage, manifests,
annotations, and decisions out of Git. Public reports contain aliases, hashes,
and known metadata, not paths, transcript text, notes, or exception messages.
