"""FFmpeg/ffprobe integration and parsers."""

from __future__ import annotations

import json
import math
import os
import re
import signal
import shutil
import time
from dataclasses import dataclass

from .models import AudioLevel, MediaAsset, SilenceInterval


VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".m4v", ".avi")


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: list[str], timeout: int = 180) -> CommandResult:
    """Run a command without importing subprocess.

    The local Python build used in this workspace can hang importing
    subprocess, so this runner keeps the package importable while still
    capturing FFmpeg output.
    """
    normalized = [os.fspath(arg) for arg in args]
    stdout_r, stdout_w = os.pipe()
    stderr_r, stderr_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(stdout_r)
            os.close(stderr_r)
            os.dup2(stdout_w, 1)
            os.dup2(stderr_w, 2)
            os.close(stdout_w)
            os.close(stderr_w)
            os.execvp(normalized[0], normalized)
        except OSError as exc:
            os.write(2, str(exc).encode("utf-8", errors="ignore"))
            os._exit(127)

    os.close(stdout_w)
    os.close(stderr_w)
    os.set_blocking(stdout_r, False)
    os.set_blocking(stderr_r, False)
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    open_fds = {stdout_r: stdout_chunks, stderr_r: stderr_chunks}
    deadline = time.monotonic() + timeout if timeout else None
    returncode: int | None = None

    try:
        while open_fds or returncode is None:
            for fd, chunks in list(open_fds.items()):
                while True:
                    try:
                        chunk = os.read(fd, 65536)
                    except BlockingIOError:
                        break
                    except OSError:
                        open_fds.pop(fd, None)
                        break
                    if not chunk:
                        open_fds.pop(fd, None)
                        os.close(fd)
                        break
                    chunks.append(chunk)

            if returncode is None:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
                if waited_pid == pid:
                    returncode = os.waitstatus_to_exitcode(status)

            if deadline is not None and time.monotonic() > deadline and returncode is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise TimeoutError(f"command timed out after {timeout}s: {normalized[0]}")

            if open_fds or returncode is None:
                time.sleep(0.01)
    finally:
        for fd in list(open_fds):
            try:
                os.close(fd)
            except OSError:
                pass

    return CommandResult(
        args=normalized,
        returncode=returncode if returncode is not None else -1,
        stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
        stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
    )


def run_command_check(args: list[str], timeout: int = 180) -> CommandResult:
    result = run_command(args, timeout=timeout)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(message or f"command failed: {args[0]}")
    return result


def scan_video_files(directory: str, extensions: tuple[str, ...] = VIDEO_EXTENSIONS) -> list[str]:
    files: list[str] = []
    root = os.fspath(directory)
    for current_dir, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in extensions:
                files.append(os.path.join(current_dir, filename))
    return sorted(files)


def probe_media(path: str, timeout: int = 60) -> MediaAsset:
    path_str = os.fspath(path)
    filename = os.path.basename(path_str)
    if not has_command("ffprobe"):
        return MediaAsset(
            filename=filename,
            filepath=path_str,
            status="error",
            error="ffprobe not found",
        )
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=width,height,codec_type,codec_name,r_frame_rate",
        "-of",
        "json",
        path_str,
    ]
    try:
        result = run_command(cmd, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        return MediaAsset(
            filename=filename,
            filepath=path_str,
            status="error",
            error=str(exc),
        )
    if result.returncode != 0:
        return MediaAsset(
            filename=filename,
            filepath=path_str,
            status="error",
            error=(result.stderr or result.stdout).strip() or "ffprobe failed",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return MediaAsset(
            filename=filename,
            filepath=path_str,
            status="error",
            error=f"ffprobe JSON parse failed: {exc}",
        )

    fmt = data.get("format", {})
    asset = MediaAsset(
        filename=filename,
        filepath=path_str,
        size_mb=round(int(fmt.get("size", 0)) / (1024 * 1024), 2),
        duration=round(float(fmt.get("duration", 0.0)), 3),
    )
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and asset.width is None:
            asset.width = stream.get("width")
            asset.height = stream.get("height")
            asset.codec = stream.get("codec_name")
            fps = stream.get("r_frame_rate")
            if fps and "/" in fps:
                num, den = fps.split("/", 1)
                try:
                    asset.fps = round(float(num) / float(den), 3) if float(den) else None
                except ValueError:
                    asset.fps = None
        elif stream.get("codec_type") == "audio":
            asset.has_audio = True
    return asset


def parse_scene_output(output: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", output):
        values.append(float(match.group(1)))
    return sorted(set(values))


def detect_scene_changes(path: str, threshold: float = 0.35, timeout: int = 180) -> tuple[list[float], str | None]:
    if not has_command("ffmpeg"):
        return [], "ffmpeg not found"
    path_str = os.fspath(path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        path_str,
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-vsync",
        "vfr",
        "-f",
        "null",
        "-",
    ]
    try:
        result = run_command(cmd, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        return [], str(exc)
    output = f"{result.stdout}\n{result.stderr}"
    return parse_scene_output(output), None if result.returncode == 0 else "scene detection failed"


def parse_silence_output(output: str, duration: float | None = None) -> list[SilenceInterval]:
    intervals: list[SilenceInterval] = []
    open_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)", line)
        if start_match:
            open_start = float(start_match.group(1))
            continue
        end_match = re.search(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)", line)
        if end_match:
            end = float(end_match.group(1))
            start = open_start if open_start is not None else end
            if end > start:
                intervals.append(SilenceInterval(start=start, end=end))
            open_start = None
    if open_start is not None and duration is not None and duration > open_start:
        intervals.append(SilenceInterval(start=open_start, end=duration))
    return intervals


def detect_silence(
    path: str,
    threshold_db: float = -30.0,
    min_duration: float = 1.0,
    duration: float | None = None,
    timeout: int = 180,
) -> tuple[list[SilenceInterval], str | None]:
    if not has_command("ffmpeg"):
        return [], "ffmpeg not found"
    path_str = os.fspath(path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        path_str,
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = run_command(cmd, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        return [], str(exc)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 and "Output file is empty" not in output:
        return [], "silence detection failed"
    return parse_silence_output(output, duration=duration), None


def parse_audio_metadata_output(output: str) -> list[AudioLevel]:
    levels: list[AudioLevel] = []
    current_time: float | None = None
    for line in output.splitlines():
        time_match = re.search(r"pts_time:([0-9]+(?:\.[0-9]+)?)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        rms_match = re.search(r"lavfi\.astats\.Overall\.RMS_level=([-+a-zA-Z0-9.]+)", line)
        if rms_match and current_time is not None:
            raw = rms_match.group(1).lower()
            if raw in {"-inf", "inf", "+inf", "nan"}:
                rms = -120.0
            else:
                try:
                    rms = float(raw)
                except ValueError:
                    continue
            if math.isfinite(rms):
                levels.append(AudioLevel(time=current_time, rms_db=rms))
    return levels


def analyze_audio_levels(path: str, timeout: int = 180) -> tuple[list[AudioLevel], str | None]:
    if not has_command("ffmpeg"):
        return [], "ffmpeg not found"
    path_str = os.fspath(path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        path_str,
        "-af",
        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f",
        "null",
        "-",
    ]
    try:
        result = run_command(cmd, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        return [], str(exc)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        return [], "audio level analysis failed"
    return parse_audio_metadata_output(output), None
