"""Reproducible, scoped evaluation of rating artifacts and local footage runs."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from .calibration import (
    AnnotationSet, POSITIVE_RATINGS, NEGATIVE_RATINGS, _SourceIndex,
    evaluate_candidate_set, load_annotations,
)
from .config import AnalysisConfig
from .rating import run_rating
from .timecode import timecode_to_seconds
from .provenance import ensure_compatible, public_provenance

MANIFEST_SCHEMA = "videoedit.benchmark.v1"
REPORT_SCHEMA = "videoedit.benchmark_report.v1"
COMPARE_SCHEMA = "videoedit.benchmark_compare.v1"
PROFILES = {"interview", "motion_event", "general_broll", "shop_build", "documentary", "social"}
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DEFAULT_GATES = {
    "min_reviewed_seconds": 600, "min_positive_annotations": 20,
    "min_negative_annotations": 20, "min_sources": 3,
    "min_precision": 0.7, "min_recall": 0.7, "min_f1": 0.7,
}


class BenchmarkRunError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read(path: Path) -> dict[str, Any]:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")
    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _number(value: Any, minimum: float = 0, maximum: float = float("inf")) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and minimum <= value <= maximum


def _times(row: dict[str, Any]) -> tuple[float, float]:
    values = [row.get("start_seconds", row.get("start", 0)), row.get("end_seconds", row.get("end", 0))]
    if any(isinstance(value, bool) or not isinstance(value, (str, int, float)) for value in values):
        raise ValueError("interval values must be seconds or timecodes")
    start, end = [timecode_to_seconds(value) for value in values]
    if not _number(start) or not _number(end) or end <= start:
        raise ValueError("interval must have finite, nonnegative start and end after start")
    return start, end


def validate_manifest(manifest: str) -> dict[str, Any]:
    data = _read(Path(manifest))
    errors = []
    if data.get("schema_version") != MANIFEST_SCHEMA:
        errors.append("schema_version must be videoedit.benchmark.v1")
    if not ID_RE.fullmatch(str(data.get("suite", ""))):
        errors.append("suite must be a portable lowercase ID")
    limit = data.get("review_limit", 25)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        errors.append("review_limit must be a positive integer")
    gates = data.get("quality_gates", {})
    if not isinstance(gates, dict):
        errors.append("quality_gates must be an object")
    else:
        for key, value in gates.items():
            maximum = 1 if key in {"min_precision", "min_recall", "min_f1"} else float("inf")
            if key not in DEFAULT_GATES or not _number(value, maximum=maximum):
                errors.append(f"quality_gates.{key} is unknown or invalid")
    projects = data.get("projects", [])
    if not isinstance(projects, list) or not projects:
        errors.append("projects must be a nonempty list")
        projects = []
    seen = set()
    for index, project in enumerate(projects, 1):
        label = f"project {index}"
        if not isinstance(project, dict):
            errors.append(f"{label} must be an object")
            continue
        pid = project.get("id")
        if not isinstance(pid, str) or not ID_RE.fullmatch(pid) or pid in seen:
            errors.append(f"{label} requires a unique portable id")
        seen.add(str(pid))
        if not isinstance(project.get("profile"), str) or project["profile"] not in PROFILES:
            errors.append(f"{label} has an unsupported profile")
        if not isinstance(project.get("annotations"), str) or not project["annotations"].strip():
            errors.append(f"{label} requires annotations")
        review = project.get("review", {})
        if not isinstance(review, dict):
            errors.append(f"{label}.review must be an object")
            review = {}
        if not isinstance(review.get("origin"), str) or review["origin"] not in {"human", "synthetic"}:
            errors.append(f"{label}.review.origin must be human or synthetic")
        if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            errors.append(f"{label}.review requires reviewer provenance")
        if not isinstance(review.get("independent"), bool):
            errors.append(f"{label}.review.independent must be a boolean")
        windows = review.get("windows", [])
        if not isinstance(windows, list) or not windows:
            errors.append(f"{label}.review.windows must be a nonempty list")
            windows = []
        for window in windows:
            try:
                if not isinstance(window, dict) or not isinstance(window.get("source"), str) or not window["source"].strip():
                    raise ValueError("source is required")
                _times(window)
            except (TypeError, ValueError):
                errors.append(f"{label} has an invalid review window")
        runs = project.get("runs", [])
        if not isinstance(runs, list) or not runs:
            errors.append(f"{label}.runs must be a nonempty list")
            runs = []
        run_ids = set()
        baselines = 0
        for run in runs:
            if not isinstance(run, dict):
                errors.append(f"{label} run must be an object")
                continue
            rid = run.get("id")
            if not isinstance(rid, str) or not ID_RE.fullmatch(rid) or rid in run_ids:
                errors.append(f"{label} run requires a unique portable id")
            run_ids.add(str(rid))
            role = run.get("role", "candidate")
            if not isinstance(role, str) or role not in {"baseline", "candidate"}:
                errors.append(f"{label} run role must be baseline or candidate")
            baselines += role == "baseline"
            refs = [run[key] for key in ("ratings", "footage") if key in run]
            if len(refs) != 1 or not all(isinstance(ref, str) and ref.strip() for ref in refs):
                errors.append(f"{label} run requires exactly one ratings or footage path")
            for key in ("config", "decisions", "run_manifest"):
                if key in run and (not isinstance(run[key], str) or not run[key].strip()):
                    errors.append(f"{label} run {key} must be a nonempty path")
            providers = run.get("providers", [])
            if not isinstance(providers, list) or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in providers) or len(providers) != len(set(map(str, providers))):
                errors.append(f"{label} run providers must be unique portable IDs")
                providers = []
            telemetry = run.get("telemetry", {})
            if not isinstance(telemetry, dict):
                errors.append(f"{label} run telemetry must be an object")
            elif any(key not in {"elapsed_seconds", "cache_hits", "cache_misses", "storage_bytes"} or not _number(value) for key, value in telemetry.items()):
                errors.append(f"{label} run telemetry is invalid")
            artifacts = run.get("provider_artifacts", {})
            if not isinstance(artifacts, dict) or any(key not in providers or not isinstance(value, str) or not value.strip() for key, value in artifacts.items()):
                errors.append(f"{label} provider_artifacts must map declared provider IDs to paths")
        if baselines != 1:
            errors.append(f"{label} requires exactly one baseline run")
    return {"valid": not errors, "errors": errors, "projects": len(projects), "schema_version": MANIFEST_SCHEMA}


def _windows(project: dict[str, Any], index: _SourceIndex) -> dict[str, list[tuple[float, float]]]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for window in project["review"]["windows"]:
        groups.setdefault(index.resolve(window["source"]), []).append(_times(window))
    for source, intervals in groups.items():
        merged: list[tuple[float, float]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        groups[source] = merged
    return groups


def _contained(source: str, start: float, end: float, windows: dict[str, list[tuple[float, float]]]) -> bool:
    return any(left <= start and end <= right for left, right in windows.get(source, []))


def _acceptance(decisions: dict[str, Any] | None, candidate_ids: set[str]) -> float | None:
    if decisions is None:
        return None
    rows = decisions.get("decisions", [])
    if isinstance(rows, dict):
        rows = [{"id": key, **(value if isinstance(value, dict) else {"decision": value})} for key, value in rows.items()]
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list or mapping")
    accepted = reviewed = 0
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in candidate_ids:
            continue
        if row["id"] in seen:
            raise ValueError("duplicate reviewed clip id")
        seen.add(row["id"])
        decision = str(row.get("decision", "")).lower()
        if decision in {"approve", "approved", "select", "broll", "b-roll"}:
            accepted += 1
            reviewed += 1
        elif decision in {"reject", "rejected", "cut"}:
            reviewed += 1
    return round(accepted / reviewed, 4) if reviewed else None


def _telemetry(run: dict[str, Any], manifest: dict[str, Any] | None, measured: float | None) -> dict[str, Any]:
    values = dict(run.get("telemetry", {}))
    storage_scope = "unknown"
    if manifest:
        if manifest.get("status") not in {"ok", "completed"}:
            raise ValueError("input run manifest is not successful")
        if not isinstance(manifest.get("telemetry", {}), dict):
            raise ValueError("input manifest telemetry must be an object")
        imported = dict(manifest.get("telemetry", {}))
        if imported.get("storage_scope") == "tracked_output_files":
            storage_scope = "tracked_output_files"
        if "elapsed_seconds" not in imported and manifest.get("duration_seconds") is not None:
            imported["elapsed_seconds"] = manifest["duration_seconds"]
        for key in ("elapsed_seconds", "cache_hits", "cache_misses", "storage_bytes"):
            value = imported.get(key)
            if value is not None:
                if not _number(value):
                    raise ValueError("invalid input manifest telemetry")
                values[key] = value
    if measured is not None:
        values["elapsed_seconds"] = round(measured, 6)
    hits, misses = values.get("cache_hits"), values.get("cache_misses")
    rate = hits / (hits + misses) if hits is not None and misses is not None and hits + misses > 0 else None
    return {**{key: values.get(key) for key in ("elapsed_seconds", "cache_hits", "cache_misses", "storage_bytes")},
            "storage_scope": storage_scope,
            "cache_hit_rate": round(rate, 4) if rate is not None else None,
            "origin": "measured" if measured is not None else "run_manifest" if manifest else "declared" if values else "unavailable"}


def _provider_metadata(run: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    rows = []
    for provider in sorted(run.get("providers", [])):
        reference = run.get("provider_artifacts", {}).get(provider)
        if not reference:
            raise BenchmarkRunError("provider_artifact_unavailable")
        artifact_path = _path(base, reference)
        try:
            data = _read(artifact_path)
        except (OSError, ValueError):
            raise BenchmarkRunError("provider_artifact_unavailable") from None
        if data.get("status", "ok") != "ok":
            raise BenchmarkRunError("provider_failed_or_unavailable")
        sources = data.get("sources", [])
        if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
            raise BenchmarkRunError("provider_schema_invalid")
        if any(source.get("status", "ok") != "ok" for source in sources):
            raise BenchmarkRunError("provider_partial_failure")
        version = data.get("schema_version")
        if not isinstance(version, str) or not re.fullmatch(r"videoedit\.[a-z_]+\.v[0-9]+", version):
            raise BenchmarkRunError("provider_schema_invalid")
        metadata = data.get("provider_metadata", data.get("provider", {}))
        try:
            validation = ensure_compatible(data)
            provenance = public_provenance(data)
        except ValueError:
            raise BenchmarkRunError("provider_schema_invalid") from None
        rows.append({"id": provider, "schema_version": version, "artifact_sha256": _file_digest(artifact_path),
                     "provider_metadata_sha256": _digest(metadata), "provenance": provenance,
                     "provenance_warnings": validation["warnings"]})
    return rows


def _evaluate_run(project: dict[str, Any], run: dict[str, Any], base: Path,
                  output: Path, gates: dict[str, float], limit: int) -> dict[str, Any]:
    provider_metadata = _provider_metadata(run, base)
    elapsed = None
    if "footage" in run:
        config = AnalysisConfig.from_mapping(_read(_path(base, run["config"]))) if run.get("config") else AnalysisConfig()
        rating_output = output / ".private" / project["id"] / run["id"]
        before = time.perf_counter()
        run_rating(str(_path(base, run["footage"])), str(rating_output), config)
        elapsed = time.perf_counter() - before
        ratings_path = rating_output / "ratings.json"
    else:
        ratings_path = _path(base, run["ratings"])
    ratings = _read(ratings_path)
    raw_candidates = ratings.get("candidates")
    for key in ("candidates", "inventory", "signals"):
        rows = ratings.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("ratings has invalid rows")
    if raw_candidates is None or not isinstance(ratings.get("config", {}), dict):
        raise ValueError("ratings has invalid candidates or config")
    if any(item.get("status") is not None and item.get("status") != "ok" for item in ratings.get("inventory", [])):
        raise ValueError("ratings contains failed media analysis")
    for row in raw_candidates:
        if not isinstance(row.get("source"), str) or not row["source"].strip():
            raise ValueError("candidate is missing source")
    for signal in ratings.get("signals", []):
        if not isinstance(signal.get("asset", {}), dict) or not isinstance(signal.get("warnings", []), list):
            raise ValueError("ratings has invalid signal metadata")
    annotation_path = _path(base, project["annotations"])
    annotation_data = _read(annotation_path)
    clips = annotation_data.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("annotations must have nonempty clips")
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("source"), str) or not clip["source"].strip():
            raise ValueError("annotation is missing source")
        _times(clip)
        if not isinstance(clip.get("tags", []), (str, list)):
            raise ValueError("annotation tags must be text or a list")
    annotations = load_annotations(str(annotation_path), ratings)
    index = _SourceIndex(ratings, annotation_path=str(annotation_path), source_root=annotations.source_root)
    windows = _windows(project, index)
    ids = [clip.id for clip in annotations.clips]
    if len(ids) != len(set(ids)) or not annotations.clips:
        raise ValueError("annotations must have unique ids and nonempty clips")
    for clip in annotations.clips:
        if not _contained(clip.canonical_source, clip.start, clip.end, windows):
            raise ValueError("annotation lies outside declared review windows")
    candidates = []
    candidate_ids = set()
    for ordinal, row in enumerate(raw_candidates, 1):
        if not isinstance(row, dict) or not row.get("source"):
            raise ValueError("candidate is missing source")
        start, end = _times(row)
        cid = str(row.get("id") or row.get("label") or f"candidate_{ordinal:04d}")
        if cid in candidate_ids or not _number(row.get("score", 0)):
            raise ValueError("candidate has duplicate id or invalid score")
        candidate_ids.add(cid)
        if _contained(index.resolve(row["source"]), start, end, windows):
            candidates.append({**row, "id": cid, "start_seconds": start, "end_seconds": end})
    candidates.sort(key=lambda row: (-float(row.get("score", 0)), index.resolve(row["source"]), row["start_seconds"], row["id"]))
    evaluation = evaluate_candidate_set(ratings, annotations, candidates)
    top_evaluation = evaluate_candidate_set(ratings, annotations, candidates[:limit])
    positive = sum(clip.rating in POSITIVE_RATINGS for clip in annotations.clips)
    negative = sum(clip.rating in NEGATIVE_RATINGS for clip in annotations.clips)
    seconds = sum(end - start for intervals in windows.values() for start, end in intervals)
    tags = sorted(evaluation["metrics"]["recall_by_tag"])
    tag_aliases = {tag: f"tag_{num:03d}" for num, tag in enumerate(tags, 1)}
    decisions = _read(_path(base, run["decisions"])) if run.get("decisions") else None
    metrics = {**evaluation["metrics"], "recall_by_tag": {tag_aliases[key]: value for key, value in evaluation["metrics"]["recall_by_tag"].items()},
               "recall_at_review_limit": top_evaluation["metrics"]["recall"],
               "human_acceptance_rate": _acceptance(decisions, {row["id"] for row in candidates}),
               "candidate_count": len(candidates), "excluded_candidates": len(raw_candidates) - len(candidates),
               "negative_annotations": negative, "reviewed_seconds": round(seconds, 3), "reviewed_sources": len(windows)}
    sample_values = {"min_reviewed_seconds": seconds, "min_positive_annotations": positive,
                     "min_negative_annotations": negative, "min_sources": len(windows)}
    insufficient = [key for key, value in sample_values.items() if value < gates[key]]
    if not project["review"]["independent"]:
        insufficient.append("independent_review_required")
    quality_failures = [key for key in ("min_precision", "min_recall", "min_f1") if metrics[key[4:]] < gates[key]]
    source_rows = []
    for num, source in enumerate(sorted(windows), 1):
        subset = AnnotationSet(annotations.project, annotations.source_root, [clip for clip in annotations.clips if clip.canonical_source == source])
        local = evaluate_candidate_set(ratings, subset, [row for row in candidates if index.resolve(row["source"]) == source])
        source_rows.append({"source": f"source_{num:03d}", "reviewed_seconds": round(sum(end-start for start, end in windows[source]), 3),
                            "metrics": {key: value for key, value in local["metrics"].items() if key != "recall_by_tag"}})
    manifest_path = _path(base, run["run_manifest"]) if run.get("run_manifest") else None
    run_manifest = _read(manifest_path) if manifest_path else None
    review_basis = {"annotations": _file_digest(annotation_path), "review": project["review"], "limit": limit, "profile": project["profile"]}
    inputs = {"ratings_sha256": _file_digest(ratings_path), "annotations_sha256": _file_digest(annotation_path),
              "command_sha256": _digest({"operation": "rate" if "footage" in run else "evaluate_ratings", "parameters": run}),
              "config_sha256": _digest(ratings.get("config", {})), "review_basis_sha256": _digest(review_basis),
              "source_fingerprint_sha256": _digest(ratings.get("inventory", []))}
    if manifest_path:
        inputs["run_manifest_sha256"] = _file_digest(manifest_path)
    if run.get("decisions"):
        inputs["decisions_sha256"] = _file_digest(_path(base, run["decisions"]))
    status = "insufficient_evidence" if insufficient else "quality_failed" if quality_failures else "ok"
    if project["review"]["origin"] == "synthetic":
        status = "synthetic"
    return {"id": run["id"], "role": run.get("role", "candidate"), "status": status,
            "providers": sorted(run.get("providers", [])), "provider_metadata": provider_metadata, "metrics": metrics,
            "gate_failures": insufficient + quality_failures, "sources": source_rows,
            "telemetry": _telemetry(run, run_manifest, elapsed), "inputs": inputs,
            "diagnostics": {"missed": metrics["missed"], "false_positives": metrics["false_positives"],
                            "signal_warning_count": sum(len(signal.get("warnings", [])) for signal in ratings.get("signals", []))}}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run_benchmark(manifest: str, output_dir: str) -> dict[str, Any]:
    validation = validate_manifest(manifest)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    path = Path(manifest).resolve()
    data = _read(path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    gates = {**DEFAULT_GATES, **data.get("quality_gates", {})}
    projects = []
    statuses = []
    for project in sorted(data["projects"], key=lambda row: row["id"]):
        runs = []
        for run in sorted(project["runs"], key=lambda row: (row.get("role") != "baseline", row["id"])):
            try:
                result = _evaluate_run(project, run, path.parent, output, gates, data.get("review_limit", 25))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                result = {"id": run["id"], "role": run.get("role", "candidate"), "status": "failed",
                          "error_code": exc.code if isinstance(exc, BenchmarkRunError) else "input_unavailable" if isinstance(exc, OSError) else "invalid_run_artifact",
                          "providers": sorted(run.get("providers", []))}
            runs.append(result)
            statuses.append(result["status"])
        projects.append({"id": project["id"], "profile": project["profile"], "review_origin": project["review"]["origin"], "runs": runs})
    status = next((value for value in ("failed", "insufficient_evidence", "quality_failed", "synthetic") if value in statuses), "ok")
    suite_failures = []
    profiles = {project["profile"] for project in projects}
    if len(profiles) < 3:
        suite_failures.append("three_distinct_profiles_required")
    for profile in ("interview", "motion_event"):
        if profile not in profiles:
            suite_failures.append(f"{profile}_profile_required")
    if status == "ok" and suite_failures:
        status = "insufficient_evidence"
    payload = {"schema_version": REPORT_SCHEMA, "suite": data["suite"], "status": status,
               "protocol": {"matching": "calibration_overlap_v1", "review_limit": data.get("review_limit", 25),
                            "quality_gates": gates, "unreviewed_candidates": "exclude", "redacted": True},
               "suite_gate_failures": suite_failures, "projects": projects}
    report = output / "benchmark_report.json"
    _write_json(report, payload)
    markdown = output / "benchmark_report.md"
    _write_markdown(markdown, payload)
    source_csv = output / "per_source.csv"
    with source_csv.open("w", newline="", encoding="utf-8") as handle:
        fields = ["project", "run", "source", "reviewed_seconds", "precision", "recall", "f1", "true_positives", "false_positives", "missed"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for project in projects:
            for run in project["runs"]:
                for source in run.get("sources", []):
                    row = {"project": project["id"], "run": run["id"], **source, **source["metrics"]}
                    writer.writerow({field: row[field] for field in fields})
    return {"report": str(report), "markdown": str(markdown), "per_source": str(source_csv), "status": status, "projects": len(projects)}


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = ["# Benchmark Report", "", f"Suite: {report['suite']}. Status: {report['status']}.", "",
             "Source names, reviewer identity, tags, notes, and paths are redacted.", "",
             "| Project | Run | Status | Precision | Recall | F1 | Recall at review limit |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    failures = []
    for project in report["projects"]:
        for run in project["runs"]:
            metrics = run.get("metrics", {})
            cells = [project["id"], run["id"], run["status"]] + [str(metrics.get(key, "unknown")) for key in ("precision", "recall", "f1", "recall_at_review_limit")]
            lines.append("| " + " | ".join(cells) + " |")
            if run.get("gate_failures"):
                failures.append(f"Gate failures for {project['id']}/{run['id']}: {', '.join(run['gate_failures'])}.")
    if report.get("suite_gate_failures"):
        failures.append(f"Suite gate failures: {', '.join(report['suite_gate_failures'])}.")
    if failures:
        lines.extend(["", *failures])
    lines.extend(["", "Synthetic results verify contracts and never qualify a production release.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _comparison_projects(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    projects = report.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("benchmark report requires projects")
    indexed = {}
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str) or not ID_RE.fullmatch(project["id"]) or project["id"] in indexed:
            raise ValueError("benchmark report has invalid or duplicate project IDs")
        runs = project.get("runs")
        if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
            raise ValueError("benchmark report has invalid runs")
        if sum(run.get("role") == "baseline" for run in runs) != 1:
            raise ValueError("benchmark project requires exactly one baseline run")
        for run in runs:
            if run.get("status") == "failed":
                raise ValueError("failed runs cannot be compared")
            inputs = run.get("inputs")
            if not isinstance(inputs, dict) or not isinstance(inputs.get("review_basis_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", inputs["review_basis_sha256"]):
                raise ValueError("benchmark run has invalid input fingerprints")
            metrics = run.get("metrics")
            if not isinstance(metrics, dict) or any(not _number(metrics.get(key)) for key in ("precision", "recall", "f1", "recall_at_review_limit", "candidate_count")):
                raise ValueError("benchmark run has invalid comparison metrics")
            if not isinstance(run.get("id"), str) or not ID_RE.fullmatch(run["id"]):
                raise ValueError("benchmark run has invalid id")
        indexed[project["id"]] = project
    return indexed


def compare_benchmarks(baseline_json: str, candidate_json: str, output_dir: str) -> dict[str, Any]:
    baseline, candidate = _read(Path(baseline_json)), _read(Path(candidate_json))
    if any(data.get("schema_version") != REPORT_SCHEMA for data in (baseline, candidate)):
        raise ValueError("unsupported benchmark report schema")
    if not isinstance(baseline.get("protocol"), dict) or baseline.get("protocol") != candidate.get("protocol"):
        raise ValueError("benchmark protocols differ")
    base_projects, candidate_projects = _comparison_projects(baseline), _comparison_projects(candidate)
    if set(base_projects) != set(candidate_projects):
        raise ValueError("benchmark project sets differ")
    comparisons = []
    for project in sorted(candidate_projects.values(), key=lambda row: row["id"]):
        base = next(run for run in base_projects[project["id"]]["runs"] if run.get("role") == "baseline")
        for run in project["runs"]:
            if base["inputs"]["review_basis_sha256"] != run["inputs"]["review_basis_sha256"]:
                raise ValueError("benchmark review basis differs")
            if run.get("role") == "baseline" and run == base:
                continue
            delta = {key: round(run["metrics"][key] - base["metrics"][key], 4) for key in ("precision", "recall", "f1", "recall_at_review_limit", "candidate_count")}
            comparisons.append({"project": project["id"], "baseline": base["id"], "candidate": run["id"],
                                "baseline_status": base["status"], "candidate_status": run["status"], "delta": delta,
                                "provider_changes": _provider_changes(base, run)})
    payload = {"schema_version": COMPARE_SCHEMA, "comparisons": comparisons}
    output = Path(output_dir)
    report = output / "benchmark_compare.json"
    _write_json(report, payload)
    markdown = output / "benchmark_compare.md"
    lines = ["# Benchmark Comparison", "", "| Project | Candidate | Precision delta | Recall delta | F1 delta |",
             "| --- | --- | --- | --- | --- |"]
    for row in comparisons:
        lines.append(f"| {row['project']} | {row['candidate']} | {row['delta']['precision']} | {row['delta']['recall']} | {row['delta']['f1']} |")
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(report), "markdown": str(markdown), "comparisons": len(comparisons)}


def _provider_changes(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    before = {item["id"]: item.get("provenance") for item in baseline.get("provider_metadata", [])}
    after = {item["id"]: item.get("provenance") for item in candidate.get("provider_metadata", [])}
    rows = []
    for provider in sorted(set(before) | set(after)):
        left, right = before.get(provider), after.get(provider)
        verified = all(isinstance(value, dict) and (value.get("model", {}).get("revision") or value.get("model", {}).get("sha256")) for value in (left, right))
        equivalent = bool(verified and left["identity_sha256"] == right["identity_sha256"])
        rows.append({"id": provider, "baseline": left, "candidate": right, "equivalent": equivalent,
                     "reason": "identity_unverified" if not verified else "same_identity" if equivalent else "identity_changed"})
    return rows
