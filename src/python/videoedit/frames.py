"""Shared, integrity-checked FFmpeg frame samples; no model dependency required."""

from __future__ import annotations

import json
from contextlib import contextmanager
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable

from .coverage import SCHEMA as COVERAGE_SCHEMA, sample_coverage
from .ffmpeg import probe_media, run_command, run_command_check, scan_video_files
from .manifests import atomic_json, fingerprint
from .provenance import canonical_hash, file_sha256

SCHEMA = "videoedit.frame_samples.v1"
SAMPLER = "uniform_midpoints.v1"


def sample_timestamps(duration: float, interval: float, maximum: int) -> list[float]:
    times = []
    timestamp = min(duration / 2, interval / 2)
    while timestamp < duration and len(times) < maximum:
        times.append(round(timestamp, 3))
        timestamp += interval
    return sorted(set(times))


def _settings(interval: float, maximum: int, width: int) -> dict[str, Any]:
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("sample_interval must be positive and finite")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ValueError("max_frames must be a positive integer")
    if isinstance(width, bool) or not isinstance(width, int) or width < 0:
        raise ValueError("width must be zero (original resolution) or a positive integer")
    return {"algorithm": SAMPLER, "sample_interval": float(interval), "max_frames": maximum,
            "width": width, "jpeg_quality": 3}


def _decoder_identity() -> dict[str, Any]:
    identity = {}
    for command in ("ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        version = None
        if executable:
            result = run_command([executable, "-version"], timeout=10)
            lines = result.stdout.splitlines()
            version = lines[0] if result.returncode == 0 and lines else None
        identity[command] = {"executable": executable, "version": version}
    return identity


def _extract(source: str, timestamp: float, output: str, *, width: int, timeout: int) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{timestamp:.3f}",
               "-i", source, "-frames:v", "1"]
    if width:
        command.extend(["-vf", f"scale={width}:-2"])
    run_command_check([*command, "-q:v", "3", "-y", output], timeout=timeout)


def _jpeg(path: Path) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 4:
        return False
    with path.open("rb") as handle:
        start = handle.read(2)
        handle.seek(-2, os.SEEK_END)
        return start == b"\xff\xd8" and handle.read(2) == b"\xff\xd9"


class FrameCache:
    """Cache identity includes source, decoder and image format, never provider/model."""

    def __init__(self, cache_dir: str, *, decoder_identity: dict[str, Any] | None = None,
                 extractor: Callable[..., None] | None = None, media_probe: Callable[..., Any] | None = None,
                 timeout: int = 180, source_hash: str = "metadata") -> None:
        if source_hash not in {"metadata", "sha256"}:
            raise ValueError("source_hash must be metadata or sha256")
        self.root = Path(cache_dir).resolve()
        self.decoder = decoder_identity if decoder_identity is not None else _decoder_identity()
        self.extract = extractor or _extract
        self.probe = media_probe or probe_media
        self.timeout, self.source_hash = timeout, source_hash

    def _fingerprint(self, source: str) -> dict[str, Any]:
        return fingerprint(source, content=self.source_hash == "sha256")

    def _cached(self, entry: Path, signature: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if not entry.exists() and not entry.is_symlink():
            return None, "no_entry"
        try:
            manifest = entry / "sample.json"
            if entry.is_symlink() or manifest.is_symlink():
                return None, "cache_manifest_invalid"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if (data.get("schema_version") != SCHEMA or data.get("status") != "ok"
                    or data.get("signature") != signature or not isinstance(data.get("duration"), (int, float))
                    or isinstance(data["duration"], bool) or not math.isfinite(data["duration"]) or data["duration"] <= 0):
                return None, "cache_manifest_invalid"
            settings = signature["sampling"]
            expected = sample_timestamps(data["duration"], settings["sample_interval"], settings["max_frames"])
            frames = data.get("frames")
            if not isinstance(frames, list) or len(frames) != len(expected):
                return None, "cache_manifest_invalid"
            for index, (frame, timestamp) in enumerate(zip(frames, expected), 1):
                if (not isinstance(frame, dict) or frame.get("name") != f"frame_{index:04d}.jpg"
                        or frame.get("time_seconds") != timestamp):
                    return None, "cache_manifest_invalid"
                path = entry / frame["name"]
                if not _jpeg(path):
                    return None, "frame_missing" if not path.exists() else "frame_checksum_changed"
                if file_sha256(path) != frame.get("sha256") or path.stat().st_size != frame.get("size_bytes"):
                    return None, "frame_checksum_changed"
            return data, "valid"
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            return None, "cache_manifest_invalid"

    def _reason(self, source: str, signature: dict[str, Any], reason: str) -> str:
        if reason != "no_entry":
            return reason
        try:
            previous = json.loads((self.root / "index.json").read_text(encoding="utf-8")).get(canonical_hash(source), {})
            for field, code in (("source", "source_changed"), ("sampling", "sampling_changed"), ("decoder", "decoder_changed")):
                if field in previous and previous[field] != signature[field]:
                    return code
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return reason

    def _remember(self, source: str, signature: dict[str, Any]) -> None:
        # The index explains misses only; entry validity never depends on it.
        path = self.root / "index.json"
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(index, dict):
                index = {}
        except (OSError, ValueError):
            index = {}
        index[canonical_hash(source)] = signature
        atomic_json(path, index)

    @contextmanager
    def _publish_lock(self, entry: Path):
        lock = entry.with_name(entry.name + ".lock")
        deadline = time.monotonic() + min(self.timeout, 30)
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("cache_publish_lock_timeout; remove an abandoned lock only after stopping its worker")
                time.sleep(0.01)
        try:
            yield
        finally:
            lock.rmdir()

    def sample(self, source: str, *, sample_interval: float = 10, max_frames: int = 8, width: int = 0) -> dict[str, Any]:
        settings = _settings(sample_interval, max_frames, width)
        started = time.monotonic()
        source = str(Path(source).resolve())
        identity = self._fingerprint(source)
        signature = {"source": identity, "decoder": self.decoder, "sampling": settings}
        telemetry = {"cache_hits": 0, "cache_misses": 1, "invalidation_reason": "no_entry", "decoded_frames": 0,
                     "decode_attempts": 0, "output_size_bytes": 0,
                     "decoded_frames_scope": "successful_sample_images", "output_size_scope": "jpeg_images"}
        data: dict[str, Any] = {"schema_version": SCHEMA, "source": source, "duration": 0, "status": "error",
                                "signature": signature, "sampling": settings, "frames": [], "warnings": []}
        expected = []
        stage = None
        frame_directory = None
        try:
            if identity.get("status") != "ok" or identity.get("type") != "file":
                raise ValueError("source_unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
            entries = self.root / "entries"
            entries.mkdir(exist_ok=True)
            if entries.is_symlink():
                raise ValueError("cache_entries_symlink")
            entry = entries / canonical_hash(signature)
            cached, reason = self._cached(entry, signature)
            telemetry["invalidation_reason"] = self._reason(source, signature, reason)
            if cached:
                data = cached
                expected = [frame["time_seconds"] for frame in data["frames"]]
                frame_directory = entry
                telemetry.update(cache_hits=1, cache_misses=0)
            else:
                asset = self.probe(source, timeout=min(self.timeout, 60))
                duration = asset.duration
                if (asset.status != "ok" or isinstance(duration, bool) or not isinstance(duration, (int, float))
                        or not math.isfinite(duration) or duration <= 0 or not asset.width or not asset.height):
                    raise ValueError("media_probe_failed_or_video_duration_invalid")
                data["duration"] = duration
                expected = sample_timestamps(duration, sample_interval, max_frames)
                stage = Path(tempfile.mkdtemp(prefix=".sampling-", dir=self.root))
                for index, timestamp in enumerate(expected, 1):
                    name = f"frame_{index:04d}.jpg"
                    output = stage / name
                    telemetry["decode_attempts"] += 1
                    try:
                        self.extract(source, timestamp, str(output), width=width, timeout=self.timeout)
                        if not _jpeg(output):
                            raise ValueError("sample_image_invalid")
                        data["frames"].append({"name": name, "time_seconds": timestamp,
                                                "sha256": file_sha256(output), "size_bytes": output.stat().st_size})
                        telemetry["decoded_frames"] += 1
                    except Exception as exc:
                        data["warnings"].append(f"sample_failed:{timestamp:.3f}:{exc}")
                data["status"] = "ok" if len(data["frames"]) == len(expected) else "partial" if data["frames"] else "error"
                if identity != self._fingerprint(source):
                    data.update(status="error", frames=[])
                    data["warnings"].append("source_changed_during_sampling")
                if data["status"] == "ok":
                    atomic_json(stage / "sample.json", data)
                    # Serialize publication/repair only; decoding remains independent.
                    with self._publish_lock(entry):
                        winner, _ = self._cached(entry, signature)
                        if winner:
                            data = winner
                        else:
                            if entry.is_symlink() or entry.is_file():
                                entry.unlink()
                            elif entry.exists():
                                shutil.rmtree(entry)
                            os.rename(stage, entry)
                            stage = None
                    frame_directory = entry
                    self._remember(source, signature)
                elif data["frames"]:
                    # Incomplete samples remain usable diagnostics, never cache hits.
                    frame_directory = self.root / f"incomplete-{stage.name.removeprefix('.sampling-')}"
                    os.rename(stage, frame_directory)
                    stage = None
        except Exception as exc:
            data.update(status="error", frames=[])
            data["warnings"].append(str(exc))
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
        if data["status"] == "ok" and identity != self._fingerprint(source):
            data.update(status="error", frames=[])
            data["warnings"].append("source_changed_during_sampling")
        frames = [{**frame, "path": str(frame_directory / frame["name"])} for frame in data["frames"]] if frame_directory else []
        telemetry.update(elapsed_seconds=round(time.monotonic() - started, 6),
                         output_size_bytes=sum(frame["size_bytes"] for frame in frames))
        return {**data, "frames": frames, "telemetry": telemetry,
                "coverage": sample_coverage(source, data["duration"], expected,
                                            [frame["time_seconds"] for frame in frames], sample_interval)}


def sample_frames(input_path: str, output_dir: str, *, sample_interval: float = 10,
                  max_frames_per_file: int = 8, width: int = 0, source_hash: str = "metadata",
                  timeout: int = 180) -> dict[str, Any]:
    _settings(sample_interval, max_frames_per_file, width)
    started = time.monotonic()
    cache = FrameCache(output_dir, timeout=timeout, source_hash=source_hash)
    files = [os.fspath(input_path)] if os.path.isfile(input_path) else scan_video_files(input_path)
    sources = [cache.sample(path, sample_interval=sample_interval, max_frames=max_frames_per_file, width=width) for path in files]
    status = "ok" if sources and all(row["status"] == "ok" for row in sources) else "partial" if any(row["frames"] for row in sources) else "error"
    telemetry = {key: sum(row["telemetry"][key] for row in sources)
                 for key in ("cache_hits", "cache_misses", "decoded_frames", "decode_attempts", "output_size_bytes")}
    telemetry.update(elapsed_seconds=round(time.monotonic() - started, 6), decoded_frames_scope="successful_sample_images",
                     output_size_scope="jpeg_images")
    payload = {"schema_version": SCHEMA, "status": status, "sources": sources, "telemetry": telemetry,
               "warnings": [] if files else ["no_video_sources"],
               "coverage": {"schema_version": COVERAGE_SCHEMA, "scope": "temporal", "sources": [row["coverage"] for row in sources]}}
    output = Path(output_dir).resolve() / "frames.json"
    atomic_json(output, payload)
    return {"manifest": str(output), "status": status, "sources": len(sources),
            "frames": sum(len(row["frames"]) for row in sources), "telemetry": telemetry}
