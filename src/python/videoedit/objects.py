"""Opt-in, local-checkpoint YOLO scanning with complete-only result caching."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import heapq
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

from .advanced import _input_files, _source_summaries, _unavailable_payload
from .coverage import SCHEMA as COVERAGE_SCHEMA
from .ffmpeg import run_command_check
from .manifests import atomic_json, fingerprint
from .provenance import build_provenance, canonical_hash, library_version
from .timecode import seconds_to_hhmmss

CACHE_SCHEMA = "videoedit.object_cache.v1"
ALGORITHM = "continuous_cfr_v3"


class ObjectSummary:
    """Keep class aggregates and the legacy top 500 segments, not every box."""
    def __init__(self, fps: float, duration: float, gap: float) -> None:
        self.fps, self.duration, self.gap = fps, duration, gap
        self.classes: dict[int, dict[str, Any]] = {}
        self.current: dict[int, dict[str, Any]] = {}
        self.segments: list[tuple] = []
        self.serial = 0
        self.count = 0

    def add(self, row: dict[str, Any]) -> None:
        self.count += 1
        key, seconds, frame = row["class_id"], row["time_seconds"], row["frame"]
        item = self.classes.setdefault(key, {"class_id": key, "class_name": row["class_name"], "count": 0,
                  "frame_count": 0, "confidence_sum": 0, "first": seconds, "last": seconds, "frame": None,
                  "class_order": len(self.classes)})
        item["count"] += 1
        item["frame_count"] += item["frame"] != frame
        item["confidence_sum"] += row["confidence"]
        item.update(last=seconds, frame=frame)
        current = self.current.get(key)
        if current is not None and seconds > current["last"] + self.gap:
            self._close(current)
            current = None
        if current is None:
            current = {"class_id": key, "class_name": row["class_name"], "first": seconds, "last": seconds,
                       "detection_count": 0, "frame_count": 0, "frame": None, "confidence_sum": 0}
            self.current[key] = current
        current["detection_count"] += 1
        current["frame_count"] += current["frame"] != frame
        current["confidence_sum"] += row["confidence"]
        current.update(last=seconds, frame=frame)

    def _close(self, row: dict[str, Any]) -> None:
        start, end = row["first"], min(self.duration, row["last"] + 1 / self.fps)
        segment = {key: row[key] for key in ("class_id", "class_name", "detection_count", "frame_count")}
        segment.update(start_seconds=round(start, 3), end_seconds=round(max(start, end), 3),
                       start=seconds_to_hhmmss(start), end=seconds_to_hhmmss(max(start, end)),
                       average_confidence=round(row["confidence_sum"] / row["detection_count"], 4))
        self.serial += 1
        heapq.heappush(self.segments, (row["detection_count"], -start,
                                    -self.classes[row["class_id"]]["class_order"], -self.serial, segment))
        if len(self.segments) > 500:
            heapq.heappop(self.segments)

    def finish(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        for row in self.current.values():
            self._close(row)
        self.current.clear()
        classes = []
        for row in self.classes.values():
            item = {key: row[key] for key in ("class_id", "class_name", "count", "frame_count")}
            item.update(average_confidence=round(row["confidence_sum"] / row["count"], 4),
                        first_seen_seconds=round(row["first"], 3), first_seen=seconds_to_hhmmss(row["first"]),
                        last_seen_seconds=round(row["last"], 3), last_seen=seconds_to_hhmmss(row["last"]))
            classes.append(item)
        return sorted(classes, key=lambda item: (-item["count"], item["class_name"])), [item[4] for item in sorted(self.segments, reverse=True)]


def probe_object_timing(source: str, timeout: int = 180) -> dict[str, Any]:
    """Verify decoded presentation timestamps, not just nominal container FPS.

    This cold-only ffprobe pass decodes all video frames. It is intentionally
    conservative: VFR or missing timestamps cannot prove nominal YOLO timing.
    """
    result = run_command_check([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time:stream=r_frame_rate,avg_frame_rate,nb_frames,duration,time_base",
        "-of", "json", source,
    ], timeout=timeout)
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("no video stream found for object timing")
    stream = streams[0]
    fps = float(Fraction(stream.get("r_frame_rate", "0/1")))
    frames = data.get("frames", [])
    count = len(frames)
    times = [float(row["best_effort_timestamp_time"]) for row in frames if "best_effort_timestamp_time" in row]
    valid = count > 0 and len(times) == count and fps > 0 and math.isfinite(fps) and all(math.isfinite(value) for value in times)
    try:
        tick = float(Fraction(stream.get("time_base", "0/1")))
    except (ValueError, ZeroDivisionError):
        tick = 0
    # Subtracting a quantized origin can introduce one tick of relative error.
    # Coarse clocks cannot distinguish meaningful variable cadence from CFR.
    tolerance = max(0.000001, tick + 0.000001)
    valid = valid and 0 <= tick < 0.25 / fps and all(right > left for left, right in zip(times, times[1:]))
    valid = valid and all(abs(value - times[0] - index / fps) <= tolerance for index, value in enumerate(times))
    reported = stream.get("nb_frames")
    if reported not in (None, "N/A"):
        valid = valid and int(reported) == count
    return {"duration": count / fps if fps > 0 else 0, "fps": fps, "expected_frames": count,
            "timing_verified": bool(valid), "timing_basis": "decoded_presentation_timestamps",
            "first_timestamp": times[0] if times else None, "timing_probe_decoded_frames": count,
            "timestamp_tolerance_seconds": tolerance}


def _identity() -> dict[str, Any]:
    versions = {name: library_version(name) for name in ("ultralytics", "torch", "opencv-python")}
    try:
        first = run_command_check(["ffprobe", "-version"], timeout=5).stdout.splitlines()[0].split()
        versions["ffprobe"] = first[2]
    except (OSError, RuntimeError, TimeoutError, IndexError):
        versions["ffprobe"] = None
    return versions


def _factory(checkpoint: str) -> Any:
    from ultralytics import YOLO
    return YOLO(checkpoint)


def _precision_arguments() -> dict[str, Any]:
    from ultralytics.cfg import DEFAULT_CFG_DICT
    return {"quantize": 32} if "quantize" in DEFAULT_CFG_DICT else {"half": False}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _cached(path: Path, signature: dict[str, Any]) -> dict[str, Any] | None:
    data = _read(path)
    row = data.get("source")
    if (data.get("schema_version") != CACHE_SCHEMA or data.get("signature") != signature
            or not isinstance(row, dict) or row.get("status") != "ok"):
        return None
    try:
        if data.get("source_sha256") != canonical_hash(row):
            return None
        coverage = row["coverage"]
        if coverage["status"] != "ok" or not 0 < coverage["processed_units"] == coverage["expected_units"]:
            return None
        if not all(isinstance(row[key], list) for key in ("detections", "class_counts", "segments")):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return row


def _results(result: Any, source: str, frame: int, fps: float) -> list[dict[str, Any]]:
    if result.boxes is None:
        raise ValueError("missing detection boxes; this is not a processed negative frame")
    classes = result.boxes.cls.cpu().tolist()
    confidences = result.boxes.conf.cpu().tolist()
    boxes = result.boxes.xywhn.cpu().tolist()
    if not len(classes) == len(confidences) == len(boxes):
        raise ValueError("inconsistent detection tensor lengths")
    rows = []
    for class_id, confidence, box in zip(classes, confidences, boxes):
        values = [class_id, confidence, *box]
        if (len(box) != 4 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
                or int(class_id) != class_id or class_id < 0 or not 0 <= confidence <= 1
                or not all(0 <= value <= 1 for value in box)):
            raise ValueError("invalid detection class, confidence, or normalized box")
        class_id = int(class_id)
        name = result.names[class_id]
        if not isinstance(name, str) or not name:
            raise ValueError("invalid model class name")
        seconds = (frame - 1) / fps if fps > 0 else None
        row = {"source": source, "frame": frame, "class_id": class_id, "class_name": name,
               "confidence": round(confidence, 4), "bbox_norm": dict(zip(
                   ("x_center", "y_center", "width", "height"), [round(value, 6) for value in box]))}
        if seconds is not None:
            row.update(time_seconds=round(seconds, 3), time=seconds_to_hhmmss(seconds))
        rows.append(row)
    return rows


def _intervals(processed: list[int], fps: float, duration: float) -> list[list[float]]:
    merged: list[list[float]] = []
    if fps <= 0:
        return merged
    for frame in processed:
        start, end = (frame - 1) / fps, min(duration, frame / fps)
        if end <= start:
            continue
        if merged and abs(start - merged[-1][1]) < 1e-8:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [[round(start, 6), round(end, 6)] for start, end in merged]


def detect_objects_native(
    input_path: str, output: str, *, model: str | None, confidence: float | None = None,
    max_detections: int = 5000, segment_merge_gap: float = 1.0, timeout: int = 180,
    device: str = "cpu", cache: bool = True, source_hash: str = "metadata", image_size: int = 640,
    max_objects_per_frame: int = 300, model_factory: Callable | None = None,
    metadata_probe: Callable | None = None, provider_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    output = str(output)
    if source_hash not in {"metadata", "sha256"} or device not in {"cpu", "mps"}:
        raise ValueError("native objects requires source_hash metadata/sha256 and device cpu/mps")
    confidence = 0.25 if confidence is None else confidence
    if (not math.isfinite(confidence) or not 0 <= confidence <= 1 or max_detections < 0
            or not math.isfinite(segment_merge_gap) or segment_merge_gap < 0 or image_size <= 0
            or max_objects_per_frame <= 0 or timeout < 0):
        raise ValueError("invalid native object inference settings")
    if not model or not Path(model).is_file() or Path(model).suffix.lower() != ".pt":
        message = "native YOLO requires an existing local PyTorch .pt checkpoint; download weights explicitly before scanning"
        payload = _unavailable_payload("visual_objects", input_path, message)
        payload["error"] = message
        atomic_json(output, payload)
        return {"output": output, "count": 0, "status": "unavailable"}

    checkpoint = str(Path(model).resolve())
    checkpoint_fingerprint = fingerprint(checkpoint)
    identity = provider_identity if provider_identity is not None else _identity()
    missing = [name for name in ("ultralytics", "torch", "opencv-python") if not identity.get(name)]
    if model_factory is None and missing:
        message = f"native YOLO dependencies missing: {', '.join(missing)}; install videoedit[advanced]"
        payload = _unavailable_payload("visual_objects", input_path, message)
        payload["error"] = message
        atomic_json(output, payload)
        return {"output": output, "count": 0, "status": "unavailable"}
    settings = {"algorithm": ALGORITHM, "confidence": confidence, "max_detections": max_detections,
                "segment_merge_gap": segment_merge_gap, "device": device, "precision": "float32",
                "image_size": image_size, "max_objects_per_frame": max_objects_per_frame,
                "vid_stride": 1}
    model_identity = {"name": Path(checkpoint).name, "sha256": checkpoint_fingerprint["sha256"]}
    cache_dir = Path(output).parent / ".object_cache"
    rows, warnings, detector = [], [], None
    model_attempted, model_error = False, None
    telemetry = {"cache_hits": 0, "cache_misses": 0, "cache_invalidations": 0, "invalidation_reasons": {},
                 "models_initialized": 0, "model_initialization_attempts": 0,
                 "model_initialization_seconds": 0.0, "decoded_frames": 0,
                 "timing_probe_decoded_frames": 0, "timing_probe_seconds": 0.0, "inference_seconds": 0.0,
                 "decoded_frames_scope": "native_yolo_results", "cache_scope": "complete_per_source_results",
                 "cache_bytes_written": 0}

    def write(status: str) -> dict[str, Any]:
        telemetry["elapsed_seconds"] = round(time.monotonic() - started, 6)
        payload = {"generated": datetime.now().isoformat(), "schema_version": "videoedit.signal.v1",
                   "artifact_kind": "visual_objects", "provider": "ultralytics_native", "model": checkpoint,
                   "confidence": confidence, "status": status, "input": str(input_path), "count": len(rows),
                   "detection_count": sum(row["detection_count"] for row in rows),
                   "class_count": len({item["class_name"] for row in rows for item in row["class_counts"]}),
                   "segment_count": sum(len(row["segments"]) for row in rows), "runs": [], "sources": rows,
                   "warnings": warnings, "source_count": len(rows), "source_summaries": _source_summaries(rows),
                   "telemetry": dict(telemetry),
                   "coverage": {"schema_version": COVERAGE_SCHEMA, "scope": "temporal",
                                "sources": [row["coverage"] for row in rows]},
                   "provider_metadata": {"name": "ultralytics_native", "version": identity.get("ultralytics"),
                                         "artifact_kind": "visual_objects", "dependencies": identity},
                   "provenance": build_provenance("ultralytics_native", "visual_objects",
                       model_name=model_identity["name"], model_checksum=model_identity["sha256"],
                       library="ultralytics", library_version=identity.get("ultralytics"), device=device,
                       precision="float32", sampling={"kind": "all_frames", "confidence": confidence,
                           "max_detections": max_detections, "segment_merge_gap": segment_merge_gap},
                       config={"settings": settings, "dependencies": identity})}
        atomic_json(output, payload)
        result = {key: payload[key] for key in ("count", "detection_count", "class_count", "segment_count", "status", "warnings", "telemetry")} | {"output": output}
        result["telemetry"]["artifact_bytes"] = Path(output).stat().st_size
        return result

    try:
        for source in _input_files(input_path):
            source = str(Path(source).resolve())
            source_fingerprint = fingerprint(source, content=source_hash == "sha256")
            signature = {"source": source_fingerprint, "model": model_identity, "provider": identity, "settings": settings}
            entry = cache_dir / (canonical_hash(signature) + ".json")
            index = cache_dir / (canonical_hash({"source_path": str(Path(source).resolve())}) + ".index.json")
            cached = _cached(entry, signature) if cache else None
            if cached is not None:
                telemetry["cache_hits"] += 1
                rows.append({**cached, "cache_status": "cached"})
                continue
            telemetry["cache_misses"] += 1
            previous = _read(index).get("signature", {}) if cache else {}
            if not isinstance(previous, dict):
                previous = {}
            corrupt_entry = cache and entry.is_file()
            if previous or corrupt_entry:
                reason = "cache_corrupt" if corrupt_entry else next((label for key, label in (("source", "source_changed"), ("model", "model_changed"),
                               ("settings", "settings_changed"), ("provider", "provider_changed"))
                               if previous.get(key) != signature[key]), "cache_corrupt")
                telemetry["cache_invalidations"] += 1
                reasons = telemetry["invalidation_reasons"]
                reasons[reason] = reasons.get(reason, 0) + 1
            metadata, detections, processed, frame_count, errors = {}, [], [], 0, []
            summary = None
            source_started = time.monotonic()
            stream = None
            interrupted = None
            try:
                probe_started = time.monotonic()
                metadata = (metadata_probe or probe_object_timing)(source, timeout=timeout)
                telemetry["timing_probe_seconds"] += time.monotonic() - probe_started
                telemetry["timing_probe_decoded_frames"] += metadata.get("timing_probe_decoded_frames", 0)
                fps = float(metadata.get("fps") or 0)
                duration = float(metadata.get("duration") or 0)
                if not math.isfinite(fps) or not math.isfinite(duration) or fps <= 0 or duration <= 0:
                    raise ValueError("video timing could not be determined")
                summary = ObjectSummary(fps, duration, segment_merge_gap)
                if detector is None:
                    if model_attempted:
                        raise RuntimeError(f"model initialization already failed: {model_error}")
                    model_attempted = True
                    telemetry["model_initialization_attempts"] += 1
                    model_started = time.monotonic()
                    try:
                        detector = (model_factory or _factory)(checkpoint)
                        telemetry["models_initialized"] += 1
                    except Exception as exc:
                        model_error = str(exc)
                        raise
                    finally:
                        telemetry["model_initialization_seconds"] += time.monotonic() - model_started
                if detector.task != "detect":
                    raise ValueError("native objects requires an object-detection checkpoint")
                inference_started = time.monotonic()
                stream = detector.predict(source=source, stream=True, vid_stride=1, save=False, show=False,
                                          verbose=False, conf=confidence, imgsz=image_size, max_det=max_objects_per_frame,
                                          device=device, batch=1, save_txt=False, save_conf=False, save_crop=False,
                                          **(_precision_arguments() if model_factory is None else {"half": False}))
                try:
                    for frame_count, result in enumerate(stream, 1):
                        telemetry["decoded_frames"] += 1
                        if timeout and time.monotonic() - source_started > timeout:
                            raise TimeoutError("native YOLO exceeded its cooperative per-source time budget")
                        try:
                            hits = _results(result, source, frame_count, fps)
                            for hit in hits:
                                summary.add(hit)
                            detections.extend(hits[:max(0, max_detections - len(detections))])
                            processed.append(frame_count)
                        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
                            errors.append(f"invalid result at frame {frame_count}: {exc}")
                finally:
                    telemetry["inference_seconds"] += time.monotonic() - inference_started
            except Exception as exc:
                errors.append(str(exc))
            except (KeyboardInterrupt, SystemExit) as exc:
                interrupted = exc
                errors.append(f"scan interrupted: {type(exc).__name__}")
            finally:
                if stream is not None and hasattr(stream, "close"):
                    try:
                        stream.close()
                    except Exception as exc:
                        errors.append(f"stream cleanup failed: {exc}")
            fps, duration = float(metadata.get("fps") or 0), float(metadata.get("duration") or 0)
            fps = fps if math.isfinite(fps) and fps > 0 else 0
            duration = duration if math.isfinite(duration) and duration > 0 else 0
            expected = metadata.get("expected_frames")
            verified = isinstance(expected, int) and not isinstance(expected, bool) and expected > 0
            complete = verified and expected == frame_count == len(processed) and metadata.get("timing_verified") is True and not errors
            changed = source_fingerprint != fingerprint(source, content=source_hash == "sha256")
            changed |= checkpoint_fingerprint != fingerprint(checkpoint)
            if changed:
                complete, detections, processed = False, [], []
                summary = None
                errors.append("source or checkpoint changed during inference; results discarded")
            if not complete and not errors:
                errors.append("complete frame count and CFR presentation timing could not be verified")
            expected_units = max(frame_count, expected if verified else 0)
            coverage = {"source": source, "status": "ok" if complete else "partial" if processed else "error",
                        "expected_units": expected_units, "processed_units": len(processed),
                        "intervals": _intervals(processed, fps, duration), "timing_verified": metadata.get("timing_verified") is True,
                        "timing_basis": metadata.get("timing_basis", "supplied_metadata"),
                        "timestamp_tolerance_seconds": metadata.get("timestamp_tolerance_seconds")}
            class_counts, segments = summary.finish() if summary else ([], [])
            count = summary.count if summary else 0
            row = {"source": source, "status": "interrupted" if interrupted else "ok" if complete else "partial" if processed else "error",
                   "fps": fps, "duration": duration, "detection_count": count,
                   "detections": detections, "detections_truncated": count > len(detections),
                   "class_counts": class_counts, "segments": segments,
                   "coverage": coverage, "cache_status": "computed", "warnings": errors}
            rows.append(row)
            warnings.extend(f"{source}: {error}" for error in errors)
            if interrupted is not None:
                raise interrupted
            if cache and complete and all(identity.get(name) for name in ("ultralytics", "torch", "opencv-python", "ffprobe")):
                atomic_json(entry, {"schema_version": CACHE_SCHEMA, "signature": signature, "source": row,
                                    "source_sha256": canonical_hash(row)})
                telemetry["cache_bytes_written"] += entry.stat().st_size
                atomic_json(index, {"signature": signature})
        return write("ok" if rows and all(row["status"] == "ok" for row in rows) else "partial" if any(row["coverage"]["processed_units"] for row in rows) else "error")
    except BaseException as exc:
        try:
            write("interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "error")
        except OSError:
            pass
        raise
