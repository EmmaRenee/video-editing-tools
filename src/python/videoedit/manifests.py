"""Atomic execution diagnostics with portable, explicitly redacted projections."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import unquote, urlparse

from ._version import __version__
from .provenance import canonical_hash, file_sha256, library_version, public_provenance, validate_artifact

RUN_SCHEMA = "videoedit.run_manifest.v1"
PATH_MODES = {"absolute", "relative", "redacted"}
JSON_SUFFIXES = {".json", ".yaml", ".yml", ".csv", ".srt", ".ass", ".edl", ".xml", ".otio", ".m3u", ".sh", ".md", ".html", ".txt"}
PROVIDER_LIBRARIES = ("open_clip_torch", "torch", "Pillow", "opencv-python", "ultralytics", "openai-whisper", "opentimelineio")
CACHE_REASON_CODES = frozenset({
    "cache_disabled", "cache_not_found", "cache_unreadable", "cache_invalid", "cache_entry_invalid",
    "analysis_policy_changed", "source_changed", "decoder_changed", "transcript_changed",
    "signal_artifacts_changed", "analysis_config_changed", "cached_analysis_incomplete",
})


def atomic_json(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def environment_snapshot() -> dict[str, Any]:
    tools = {}
    for command in ("ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        version = None
        if executable:
            try:
                result = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=3)
                first = result.stdout.splitlines()[0].split()
                version = first[2] if result.returncode == 0 and len(first) >= 3 else None
            except (OSError, subprocess.TimeoutExpired, IndexError):
                pass
        tools[command] = {"available": executable is not None, "version": version}
    return {"package_version": __version__, "python": platform.python_version(),
            "platform": platform.system(), "machine": platform.machine(),
            "tools": tools, "providers": {name: library_version(name) for name in PROVIDER_LIBRARIES}}


def fingerprint(path: str | Path, *, content: bool = True) -> dict[str, Any]:
    path = Path(path)
    row: dict[str, Any] = {"path": str(path.resolve()), "status": "missing", "sha256": None}
    try:
        stat = path.stat()
        row.update(status="ok", size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
                   type="file" if path.is_file() else "directory", method="content_sha256" if content and path.is_file() else "size_mtime")
        row["sha256"] = file_sha256(path) if content and path.is_file() else canonical_hash({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    except OSError:
        row["status"] = "unavailable"
    return row


def _result_paths(result: Any) -> list[str]:
    found = set()
    metadata_keys = {"input", "source", "source_root", "selection", "warnings", "error", "description",
                     "provenance", "provider_metadata", "telemetry", "summary"}
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in metadata_keys:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            try:
                if Path(value).is_file():
                    found.add(str(Path(value).resolve()))
            except OSError:
                pass
    walk(result)
    return sorted(found)


def _artifact(path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = fingerprint(path, content=Path(path).suffix.lower() in JSON_SUFFIXES)
    data = {}
    valid_json = True
    if Path(path).suffix.lower() == ".json":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            data = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            valid_json = False
            row["validation_errors"] = ["json_unreadable_or_invalid"]
    status = data.get("status", "ok")
    row["complete"] = row["status"] == "ok" and valid_json and isinstance(status, str) and status not in {"error", "failed", "unavailable", "interrupted", "partial", "running"}
    if "provenance" in data:
        validation = validate_artifact(data)
        row["provenance_warnings"] = validation["warnings"]
        if validation["errors"]:
            row.update(complete=False, provenance_errors=validation["errors"])
        else:
            row["provenance"] = public_provenance(data)
    return row, data


def _cache_details(result: dict[str, Any], artifacts: list[dict[str, Any]]) -> tuple[int | None, int | None, dict[str, Any]]:
    # Keep reuse context tied to the selected counters; do not sum duplicate sidecars.
    for data in [result.get("telemetry", {}), result.get("summary", {}), result, *[item.get("telemetry", {}) for item in artifacts]]:
        if isinstance(data, dict) and all(isinstance(data.get(key), int) and not isinstance(data[key], bool) and data[key] >= 0 for key in ("cache_hits", "cache_misses")):
            return data["cache_hits"], data["cache_misses"], data
    return None, None, result["telemetry"] if isinstance(result.get("telemetry"), dict) else {}


class RunManifest:
    def __init__(self, path: str, operation: str, *, inputs: list[str] | None = None,
                 config: dict[str, Any] | None = None, path_mode: str = "absolute") -> None:
        if path_mode not in PATH_MODES:
            raise ValueError("manifest paths must be absolute, relative, or redacted")
        self.path = Path(path)
        self.mode = path_mode
        self.started = time.monotonic()
        self.data: dict[str, Any] = {
            "schema_version": RUN_SCHEMA, "operation": operation, "path_mode": path_mode,
            "environment": environment_snapshot(), "started": datetime.now().isoformat(),
            "status": "running", "complete": False, "config_sha256": canonical_hash(config or {}),
            "inputs": [_artifact(item)[0] if Path(item).suffix.lower() == ".json" else fingerprint(item, content=Path(item).suffix.lower() in JSON_SUFFIXES) for item in inputs or []],
            "steps": [], "outputs": [], "warnings": [], "telemetry": {},
        }

    def __enter__(self) -> "RunManifest":
        self.write()
        return self

    def legacy(self, **fields: Any) -> None:
        self.data.update(fields)

    def add_outputs(self, paths: list[str]) -> list[dict[str, Any]]:
        rows = [_artifact(path)[0] for path in paths]
        self._remember_outputs(rows)
        return rows

    def _remember_outputs(self, rows: list[dict[str, Any]]) -> None:
        existing = {item["path"]: item for item in self.data["outputs"]}
        existing.update((row["path"], row) for row in rows)
        self.data["outputs"] = [existing[key] for key in sorted(existing)]

    def record_step(self, name: str, operation: str, params: dict[str, Any], result: dict[str, Any],
                    duration: float, status: str = "ok", error: BaseException | None = None) -> dict[str, Any]:
        paths = _result_paths(result) if status == "ok" else []
        artifacts = [_artifact(path) for path in paths]
        outputs, artifact_data = [item[0] for item in artifacts], [item[1] for item in artifacts]
        self._remember_outputs(outputs)
        hits, misses, telemetry = _cache_details(result, artifact_data)
        cache_status = "unknown" if hits is None or not hits + misses else "mixed" if hits and misses else "cached" if hits else "computed"
        step = {"name": name, "operation": operation, "status": status, "duration_seconds": round(duration, 6),
                "config_sha256": canonical_hash(params), "cache_status": cache_status,
                "cache_hits": hits, "cache_misses": misses, "outputs": outputs, "result": result,
                "warnings": result.get("warnings", [])}
        reasons = telemetry.get("cache_miss_reasons")
        if isinstance(reasons, dict):
            step["cache_miss_reasons"] = {key: value for key, value in reasons.items()
                                         if key in CACHE_REASON_CODES and isinstance(value, int)
                                         and not isinstance(value, bool) and value >= 0}
        reused = telemetry.get("detector_cache_reuses")
        if isinstance(reused, int) and not isinstance(reused, bool) and reused >= 0 and (misses is None or reused <= misses):
            step["detector_cache_reuses"] = reused
        if error is not None:
            step.update(error=str(error), error_type=type(error).__name__)
        self.data["steps"].append(step)
        self.write()
        return step

    def write(self) -> None:
        atomic_json(self.path, self._portable())

    def _portable(self) -> dict[str, Any]:
        if self.mode == "absolute":
            return self.data
        if self.mode == "relative":
            def relative(value: Any) -> Any:
                if isinstance(value, dict):
                    return {key: relative(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [relative(item) for item in value]
                if isinstance(value, str) and os.path.isabs(value):
                    try:
                        return os.path.relpath(Path(value).resolve(), self.path.parent.resolve())
                    except ValueError:
                        return value
                if isinstance(value, str) and value.startswith("file:///"):
                    uri = urlparse(value)
                    path = unquote(uri.path)
                    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
                        path = path[1:]
                    try:
                        return os.path.relpath(Path(path).resolve(), self.path.parent.resolve())
                    except ValueError:
                        return value
                return value
            return relative(self.data)
        payload = {key: self.data[key] for key in ("schema_version", "operation", "path_mode", "environment", "started", "status", "complete", "config_sha256", "telemetry")}
        for key in ("finished", "duration_seconds", "error_type"):
            if key in self.data:
                payload[key] = self.data[key]
        def records(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
            return [{**{key: value for key, value in row.items() if key != "path"}, "path": f"{prefix}_{index:03d}"}
                    for index, row in enumerate(rows, 1)]
        payload.update(inputs=records(self.data["inputs"], "input"), outputs=records(self.data["outputs"], "output"),
                       warnings=[], warning_count=len(self.data["warnings"]), steps=[], results={})
        for index, step in enumerate(self.data["steps"], 1):
            row = {key: step[key] for key in ("operation", "status", "duration_seconds", "config_sha256", "cache_status", "cache_hits", "cache_misses")}
            row.update(name=f"step_{index:03d}", warning_count=len(step["warnings"]), outputs=records(step["outputs"], "output"), result={})
            if "cache_miss_reasons" in step:
                row["cache_miss_reasons"] = step["cache_miss_reasons"]
            if "detector_cache_reuses" in step:
                row["detector_cache_reuses"] = step["detector_cache_reuses"]
            if step.get("error_type"):
                row["error_type"] = step["error_type"]
            payload["steps"].append(row)
            payload["results"][row["name"]] = {"outputs": row["outputs"]}
        for key in ("pipeline", "input", "output"):
            if key in self.data:
                payload[key] = key
        if "handoff" in self.data:
            handoff = dict(self.data["handoff"])
            safe_fields = {"event", "metadata_status", "source_fps", "source_timecode", "source_timecode_frames",
                           "duration_seconds", "width", "height", "start_seconds", "end_seconds",
                           "source_in_frames", "source_out_frames", "xml_clip_rate",
                           "xml_start_delta_seconds", "xml_end_delta_seconds",
                           "xml_in_frames", "xml_out_frames", "record_in_frames", "record_out_frames",
                           "edl_in", "edl_out", "edl_record_in", "edl_record_out", "timeline_start_seconds"}
            handoff["sources"] = [{**{key: value for key, value in row.items() if key in safe_fields},
                                   "source": f"source_{index:03d}", "reel": f"reel_{index:03d}"}
                                  for index, row in enumerate(handoff.get("sources", []), 1)]
            handoff["warning_count"] = len(handoff.get("warnings", []))
            handoff["warnings"] = []
            payload["handoff"] = handoff
        if "otio" in self.data:
            details = self.data["otio"]
            safe_fields = {"schema_version", "timeline_rate", "duration_seconds", "limitations",
                           "editor_verified", "rounding"}
            payload["otio"] = {key: value for key, value in details.items() if key in safe_fields}
            payload["otio"]["provider"] = {key: value for key, value in details.get("provider", {}).items()
                                             if key in {"name", "version"}}
            safe_placement = {"event", "start_seconds", "duration_seconds", "record_quantization_delta_seconds"}
            payload["otio"]["placements"] = [{key: value for key, value in row.items() if key in safe_placement}
                                              for row in details.get("placements", [])]
        return payload

    def __exit__(self, error_type: Any, error: BaseException | None, _traceback: Any) -> bool:
        self.data["status"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "error" if error is not None else "partial" if self.data.get("partial") or any(not item["complete"] for item in self.data["outputs"]) else "ok"
        self.data["complete"] = error is None and self.data["status"] == "ok"
        self.data["finished"] = datetime.now().isoformat()
        self.data["duration_seconds"] = round(time.monotonic() - self.started, 6)
        if error is not None:
            self.data.update(error=str(error), error_type=type(error).__name__)
        steps = self.data["steps"]
        counters = {key: sum(step[key] for step in steps if step[key] is not None) if any(step[key] is not None for step in steps) else None for key in ("cache_hits", "cache_misses")}
        self.data["telemetry"] = {"elapsed_seconds": self.data["duration_seconds"], **counters,
                                  "storage_scope": "tracked_output_files",
                                  "storage_bytes": sum(row.get("size_bytes", 0) for row in self.data["outputs"] if row.get("type") == "file")}
        if any("detector_cache_reuses" in step for step in steps):
            self.data["telemetry"]["detector_cache_reuses"] = sum(step.get("detector_cache_reuses", 0) for step in steps)
        if any("cache_miss_reasons" in step for step in steps):
            self.data["telemetry"]["cache_miss_reasons"] = {
                key: sum(step.get("cache_miss_reasons", {}).get(key, 0) for step in steps)
                for key in sorted({key for step in steps for key in step.get("cache_miss_reasons", {})})
            }
        self.write()
        return False
