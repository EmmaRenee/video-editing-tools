"""Controlled optional-provider scorecards over the shared benchmark protocol."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .benchmark import (
    DEFAULT_ABLATION_POLICY, ablation_policy, _contained, _digest, _file_digest,
    _number, _path, _read, _times, _windows, run_benchmark,
)
from .calibration import _SourceIndex
from .config import AnalysisConfig
from .coverage import SCHEMA as COVERAGE_SCHEMA, assess_coverage
from .manifests import atomic_json
from .provenance import ensure_compatible, public_provenance
from .signals import signal_artifact_paths

SCHEMA = "videoedit.ablation_report.v1"
PROVIDERS = {
    "openclip": ("ai_frame_scores", "videoedit ai score-frames", None),
    "yolo": ("visual_objects", "videoedit signals objects", None),
    "ocr": ("ocr_signage", "videoedit signals ocr", None),
    "face_person": ("face_person", "videoedit signals face-person", None),
    "topics": ("topic_clusters", "videoedit signals topics", None),
    "motorsports": ("motorsports_events", "videoedit signals motorsports", None),
    "clip_judge": ("ai_clip_judgments", "videoedit ai judge", "ai_clip_judgments_path"),
    "learned_scorer": ("learned_scorer", "videoedit ai train-scorer", "learned_scorer_path"),
}
DEFAULT_POLICY = DEFAULT_ABLATION_POLICY
QUALITY_METRICS = ("precision", "recall", "f1", "recall_at_review_limit", "human_acceptance_rate", "candidate_count")


def _bindings(ratings: dict[str, Any]) -> dict[str, str]:
    config = AnalysisConfig.from_mapping(ratings.get("config", {}))
    return {**signal_artifact_paths(config), **{kind: getattr(config, field) for kind, _command, field in PROVIDERS.values()
                                             if field and getattr(config, field)}}


def _base_config(ratings: dict[str, Any]) -> str:
    config = AnalysisConfig.from_mapping(ratings.get("config", {})).to_dict()
    for key in ("signal_artifacts", "visual_objects_path", "ai_frame_scores_path", "ai_clip_judgments_path", "learned_scorer_path"):
        config.pop(key, None)
    return _digest(config)


def _ratings_path(run: dict[str, Any], base: Path, output: Path, project: str) -> Path:
    return _path(base, run["ratings"]) if "ratings" in run else output / ".private" / project / run["id"] / "ratings.json"


def _run_manifest(run: dict[str, Any], base: Path, ratings_path: Path) -> dict[str, Any] | None:
    path = _path(base, run["run_manifest"]) if run.get("run_manifest") else ratings_path.parent / "rating_run.json"
    if path.is_file():
        return _read(path)
    return None


def _binding(manifest: dict[str, Any] | None, ratings_path: Path, artifact_sha256: str | None = None) -> str:
    if manifest is None:
        return "declared_config"
    def recorded(key: str, digest: str) -> bool:
        rows = manifest.get(key, [])
        return isinstance(rows, list) and any(isinstance(row, dict) and row.get("sha256") == digest
                                             and row.get("complete") is True for row in rows)
    if (manifest.get("schema_version") != "videoedit.run_manifest.v1" or manifest.get("status") != "ok"
            or manifest.get("complete") is not True or manifest.get("operation") != "rate_footage"
            or not recorded("outputs", _file_digest(ratings_path))
            or artifact_sha256 and not recorded("inputs", artifact_sha256)):
        return "mismatch"
    return "verified"


def _learned_coverage(ratings: dict[str, Any], baseline: dict[str, Any], windows: dict[str, list[tuple[float, float]]], index: _SourceIndex) -> dict[str, Any]:
    def key(clip: dict[str, Any]) -> tuple[str, float, float]:
        return (index.resolve(clip["source"]), *_times(clip))
    scored = {key(clip) for clip in ratings.get("candidates", []) if _number(clip.get("signals", {}).get("learned_score"), maximum=100)}
    rows = {}
    for clip in baseline.get("candidates", []):
        source, start, end = item = key(clip)
        if not _contained(source, start, end, windows):
            continue
        row = rows.setdefault(source, {"source": source, "expected_units": 0, "processed_units": 0, "intervals": []})
        row["expected_units"] += 1
        if item in scored:
            row["processed_units"] += 1
            row["intervals"].append([start, end])
    for row in rows.values():
        row["status"] = "ok" if row["processed_units"] == row["expected_units"] else "partial"
    return {"schema_version": COVERAGE_SCHEMA, "scope": "candidate", "sources": list(rows.values())}


def _provider(provider: str, run: dict[str, Any], ratings: dict[str, Any], ratings_path: Path,
              base: Path, windows: dict[str, list[tuple[float, float]]], index: _SourceIndex,
              policy: dict[str, float], manifest: dict[str, Any] | None, baseline_ratings: dict[str, Any]) -> dict[str, Any]:
    row = {"id": provider, "status": "not_evaluated", "dependency_status": "artifact_unavailable", "reason_codes": [],
           "diagnostic": "Use a supported provider ID and run videoedit modules doctor.", "coverage": None,
           "elapsed_seconds": None, "artifact_size_bytes": None, "storage_scope": "artifact_file_only"}
    if provider not in PROVIDERS:
        row["reason_codes"] = ["unknown_provider"]
        return row
    kind, command, _field = PROVIDERS[provider]
    row["diagnostic"] = f"Run videoedit modules doctor; generation command: {command}. Check processing coverage; legacy artifacts without instrumentation cannot be evaluated."
    try:
        path = _path(base, run.get("provider_artifacts", {})[provider])
        artifact = _read(path)
        compatibility = ensure_compatible(artifact)
    except (OSError, KeyError, ValueError):
        row["reason_codes"] = ["provider_artifact_unavailable_or_invalid"]
        return row
    row.update(dependency_status="artifact_available", artifact_sha256=_file_digest(path), artifact_size_bytes=path.stat().st_size,
               provenance=public_provenance(artifact), provenance_warnings=compatibility["warnings"])
    elapsed = artifact.get("telemetry", {}).get("elapsed_seconds") if isinstance(artifact.get("telemetry"), dict) else None
    row["elapsed_seconds"] = elapsed if _number(elapsed) else None
    if artifact.get("status", "ok") != "ok":
        row["reason_codes"] = ["provider_failed_or_unavailable"]
        return row
    expected_kind = "face_person_presence" if kind == "face_person" else kind
    if artifact.get("artifact_kind") != expected_kind:
        row["reason_codes"].append("artifact_kind_mismatch")
    row["binding"] = _binding(manifest, ratings_path, row["artifact_sha256"])
    if row["binding"] == "mismatch":
        row["reason_codes"].append("historical_artifact_binding_mismatch")
    configured = _bindings(ratings).get(kind)
    if not configured or not any(candidate.is_file() and _file_digest(candidate) == row["artifact_sha256"]
                                  for candidate in [_path(base, configured), _path(ratings_path.parent, configured)]):
        row["reason_codes"].append("artifact_not_consumed")
    if provider == "clip_judge":
        row["reason_codes"].append("annotation_only")
    try:
        coverage_data = _learned_coverage(ratings, baseline_ratings, windows, index) if provider == "learned_scorer" else artifact.get("coverage")
        coverage = assess_coverage(coverage_data, windows, resolve=index.resolve)
    except (ValueError, TypeError, KeyError, AttributeError):
        coverage = {"status": "invalid"}
    row["coverage"] = coverage
    if coverage["status"] != "ok":
        row["reason_codes"].append(f"coverage_{coverage['status']}")
    elif (coverage["source_ratio"] < policy["min_source_ratio"] or coverage["unit_ratio"] < policy["min_unit_ratio"]
          or coverage["scope"] == "temporal" and coverage["temporal_ratio"] < policy["min_temporal_ratio"]):
        row["reason_codes"].append("coverage_below_threshold")
    if not row["reason_codes"]:
        row.update(status="evaluated", diagnostic="Artifact evaluated locally; inference dependencies were not rerun.")
    return row


def _effect(project: dict[str, Any], run: dict[str, Any], result: dict[str, Any], baseline: dict[str, Any],
            baseline_ratings: dict[str, Any], base: Path, output: Path, policy: dict[str, float]) -> dict[str, Any]:
    row = {"project": project["id"], "profile": project["profile"], "run": run["id"], "baseline": baseline["id"],
           "status": "not_evaluated", "reason_codes": [], "providers": [], "delta": None,
           "baseline_telemetry": baseline.get("telemetry", {}), "telemetry": result.get("telemetry", {}),
           "attribution": "single_provider" if len(run.get("providers", [])) == 1 else "combination_only",
           "review_origin": project["review"]["origin"], "baseline_status": baseline["status"], "candidate_status": result["status"]}
    ratings_path = _ratings_path(run, base, output, project["id"])
    try:
        ratings = _read(ratings_path)
        if not isinstance(ratings.get("config", {}), dict):
            raise ValueError("invalid config")
        _bindings(ratings)
        index = _SourceIndex(ratings, annotation_path=str(_path(base, project["annotations"])),
                             source_root=_read(_path(base, project["annotations"])).get("source_root"))
        windows = _windows(project, index)
        manifest = _run_manifest(run, base, ratings_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        ratings, index, windows = {}, _SourceIndex({}), {}
        row["reason_codes"].append("invalid_candidate_artifact")
        manifest = None
    row["providers"] = [_provider(provider, run, ratings, ratings_path, base, windows, index, policy, manifest, baseline_ratings)
                        for provider in sorted(run.get("providers", []))]
    if not row["providers"]:
        row["reason_codes"].append("no_provider_addition")
    row["reason_codes"].extend(reason for provider in row["providers"] for reason in provider["reason_codes"])
    if baseline["status"] == "failed":
        row["reason_codes"].append("baseline_failed")
    if result["status"] == "failed":
        row["reason_codes"].append("benchmark_run_failed")
    try:
        if _base_config(baseline_ratings) != _base_config(ratings):
            row["reason_codes"].append("base_config_changed")
        if _bindings(baseline_ratings):
            row["reason_codes"].append("baseline_has_optional_inputs")
    except (TypeError, ValueError, AttributeError):
        row["reason_codes"].append("invalid_baseline_config")
    declared_kinds = {PROVIDERS[provider][0] for provider in run.get("providers", []) if provider in PROVIDERS}
    if set(_bindings(ratings)) - declared_kinds:
        row["reason_codes"].append("undeclared_optional_inputs")
    baseline_path = _ratings_path(next(item for item in project["runs"] if item.get("role") == "baseline"), base, output, project["id"])
    try:
        baseline_manifest = _run_manifest(next(item for item in project["runs"] if item.get("role") == "baseline"), base, baseline_path)
        row["baseline_binding"] = _binding(baseline_manifest, baseline_path)
    except (OSError, ValueError):
        row["baseline_binding"] = "mismatch"
    if row["baseline_binding"] == "mismatch":
        row["reason_codes"].append("baseline_binding_mismatch")
    if baseline.get("inputs", {}).get("source_fingerprint_sha256") != result.get("inputs", {}).get("source_fingerprint_sha256"):
        row["reason_codes"].append("source_fingerprints_changed")
    row["reason_codes"] = sorted(set(row["reason_codes"]))
    if row["reason_codes"]:
        return row
    deltas = {key: round(result["metrics"][key] - baseline["metrics"][key], 4)
              if result["metrics"].get(key) is not None and baseline["metrics"].get(key) is not None else None for key in QUALITY_METRICS}
    for key in ("elapsed_seconds", "storage_bytes"):
        before, after = baseline.get("telemetry", {}).get(key), result.get("telemetry", {}).get(key)
        deltas[key] = round(after - before, 6) if before is not None and after is not None else None
    row.update(status="evaluated", delta=deltas, baseline_metrics=baseline["metrics"], metrics=result["metrics"])
    return row


def _qualified(row: dict[str, Any]) -> bool:
    telemetry = [row.get("baseline_telemetry", {}), row.get("telemetry", {})]
    return (row["status"] == "evaluated" and row["review_origin"] == "human"
            and row["baseline_status"] in {"ok", "quality_failed"} and row["candidate_status"] in {"ok", "quality_failed"}
            and row.get("baseline_binding") == "verified"
            and all(item.get("binding") == "verified" and not item.get("provenance_warnings")
                    and item.get("provenance") and item.get("elapsed_seconds") is not None
                    and item.get("coverage", {}).get("scope") == "temporal" for item in row["providers"])
            and all(item.get("origin") in {"measured", "run_manifest"} and item.get("elapsed_seconds") is not None
                    and item.get("storage_bytes") is not None and item.get("storage_scope") == "tracked_output_files" for item in telemetry))


def _scorecards(effects: list[dict[str, Any]], policy: dict[str, float]) -> list[dict[str, Any]]:
    groups: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = {}
    for effect in effects:
        key = tuple((provider["id"], (provider.get("provenance") or {}).get("identity_sha256", "unknown")) for provider in effect["providers"])
        groups.setdefault(key, []).append(effect)
    cards = []
    for identities, rows in sorted(groups.items()):
        providers = [item[0] for item in identities]
        valid = [row for row in rows if row["status"] == "evaluated"]
        qualified = [row for row in valid if _qualified(row)]
        gains = [row for row in qualified if row["candidate_status"] == "ok" and row["delta"]["f1"] >= policy["min_f1_delta"] and row["delta"]["recall"] >= 0]
        harms = [row for row in qualified if row["delta"]["f1"] <= -policy["removal_f1_delta"]]
        supported_profiles = {profile for profile in {row["profile"] for row in gains}
                              if all(row in gains for row in rows if row["profile"] == profile)}
        recommendation, reasons = "experimental", []
        if not valid:
            reasons.append("no_valid_ablations")
        if any(row["review_origin"] == "synthetic" for row in valid):
            reasons.append("synthetic_evidence")
        if len({row["profile"] for row in gains}) >= policy["min_profiles_default"] and len(gains) == len(qualified) and len(qualified) == len(rows):
            recommendation = "default_enablement_supported"
        elif len({row["profile"] for row in harms}) >= policy["min_profiles_removal"] and len(harms) == len(qualified) and len(qualified) == len(rows):
            recommendation = "removal_supported"
        elif supported_profiles:
            recommendation = "profile_only_enablement_supported"
        if recommendation == "experimental":
            reasons.append("insufficient_controlled_quality_or_cost_evidence")
        def average(values: list[Any]) -> float | None:
            return round(sum(values) / len(values), 6) if values and all(value is not None for value in values) else None
        summaries = {f"mean_{key}_delta": average([row["delta"].get(key) for row in valid])
                     for key in ("f1", "precision", "recall", "candidate_count", "elapsed_seconds", "storage_bytes")}
        summaries.update(mean_provider_elapsed_seconds=average([sum(item["elapsed_seconds"] for item in row["providers"])
                                                               if all(item.get("elapsed_seconds") is not None for item in row["providers"]) else None for row in valid]),
                         mean_provider_artifact_bytes=average([sum(item["artifact_size_bytes"] for item in row["providers"])
                                                              if all(item.get("artifact_size_bytes") is not None for item in row["providers"]) else None for row in valid]))
        cards.append({"providers": providers, "identities": [{"id": provider, "identity_sha256": identity} for provider, identity in identities],
                      "recommendation": recommendation, "reason_codes": sorted(set(reasons)),
                      **summaries,
                      "evaluated_runs": len(valid), "not_evaluated_runs": len(rows) - len(valid),
                      "supported_profiles": sorted(supported_profiles),
                      "effects": [{"project": row["project"], "profile": row["profile"], "run": row["run"],
                                   "status": row["status"], "delta": row["delta"], "reason_codes": row["reason_codes"]} for row in rows]})
    return cards


def evaluate_ablations(manifest: str, output_dir: str) -> dict[str, Any]:
    path, output = Path(manifest).resolve(), Path(output_dir)
    data = _read(path)
    policy = ablation_policy(data)
    benchmark = run_benchmark(manifest, output_dir)
    report = _read(Path(benchmark["report"]))
    projects = {project["id"]: project for project in data["projects"]}
    effects = []
    for project_result in report["projects"]:
        project = projects[project_result["id"]]
        runs = {run["id"]: run for run in project["runs"]}
        baseline = next(run for run in project_result["runs"] if run["role"] == "baseline")
        try:
            baseline_ratings = _read(_ratings_path(runs[baseline["id"]], path.parent, output, project["id"]))
        except (OSError, ValueError):
            baseline_ratings = {}
        for result in project_result["runs"]:
            if result["role"] != "baseline":
                effects.append(_effect(project, runs[result["id"]], result, baseline, baseline_ratings, path.parent, output, policy))
    cards = _scorecards(effects, policy)
    payload = {"schema_version": SCHEMA, "suite": data["suite"], "policy": policy, "benchmark_status": report["status"],
               "status": "not_evaluated" if not any(row["status"] == "evaluated" for row in effects) else "partial" if any(row["status"] != "evaluated" for row in effects) else "ok",
               "effects": effects, "scorecards": cards, "automatic_defaults_changed": False}
    json_path, markdown, csv_path = output / "ablation_report.json", output / "ablation_report.md", output / "provider_scorecards.csv"
    atomic_json(json_path, payload)
    lines = ["# Provider Ablation Report", "", f"Suite: {data['suite']}. Status: {payload['status']}. Benchmark: {report['status']}.", "",
             "| Project | Profile | Providers | Status | F1 delta | Candidate delta | Rating runtime delta |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in effects:
        delta = row["delta"] or {}
        lines.append(f"| {row['project']} | {row['profile']} | {', '.join(item['id'] for item in row['providers'])} | {row['status']} | {delta.get('f1', 'unknown')} | {delta.get('candidate_count', 'unknown')} | {delta.get('elapsed_seconds', 'unknown')} |")
    lines.extend(["", "## Diagnostics", ""])
    for row in effects:
        if row["reason_codes"]:
            lines.append(f"- {row['project']} / {row['run']}: {', '.join(row['reason_codes'])}.")
        for provider in row["providers"]:
            coverage = provider.get("coverage") or {}
            lines.append(f"- {row['project']} / {row['run']} / {provider['id']}: {provider['status']}; "
                         f"coverage {coverage.get('status', 'unknown')} ({coverage.get('scope', 'unknown')}); "
                         f"source/unit/time ratios {coverage.get('source_ratio', 'unknown')}/{coverage.get('unit_ratio', 'unknown')}/{coverage.get('temporal_ratio', 'unknown')}; "
                         f"provider time {provider.get('elapsed_seconds')}s; JSON bytes {provider.get('artifact_size_bytes')}. {provider['diagnostic']}")
    lines.extend(["", "## Detector Cache Context", "",
                  "| Project | Run | Baseline detector reuses | Candidate detector reuses |",
                  "| --- | --- | --- | --- |"])
    for row in effects:
        counts = [row.get(key, {}).get("detector_cache_reuses") for key in ("baseline_telemetry", "telemetry")]
        cells = [row["project"], row["run"], *[str(count) if count is not None else "unknown" for count in counts]]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "Report misses can reuse warm detectors. Unknown counts are not zero; hold detector-cache conditions constant before interpreting runtime deltas.",
                  "", "## Recommendations", "", "Recommendations are evidence summaries, not automatic configuration changes.",
                  "Synthetic or insufficient evidence cannot establish production quality. Combination effects do not isolate each provider.", ""])
    for card in cards:
        lines.append(f"- {', '.join(card['providers'])}: {card['recommendation']} ({', '.join(card['reason_codes']) or 'qualified evidence'}).")
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["providers", "identities", "recommendation", "evaluated_runs", "not_evaluated_runs", "supported_profiles", "reason_codes",
                               *[f"mean_{key}_delta" for key in ("f1", "precision", "recall", "candidate_count", "elapsed_seconds", "storage_bytes")],
                               "mean_provider_elapsed_seconds", "mean_provider_artifact_bytes"])
        writer.writeheader()
        for card in cards:
            writer.writerow({key: ",".join(f"{item['id']}:{item['identity_sha256']}" for item in card[key]) if key == "identities"
                             else ",".join(card[key]) if isinstance(card[key], list) else card[key] for key in writer.fieldnames})
    return {"report": str(json_path), "markdown": str(markdown), "scorecards": str(csv_path), "status": payload["status"], "effects": len(effects)}
