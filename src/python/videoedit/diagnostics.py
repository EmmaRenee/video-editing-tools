"""Local dependency diagnostics for videoedit."""

from __future__ import annotations

from datetime import datetime
import importlib.metadata
import importlib.util
import os
import re
import shutil
import sys
from typing import Any, Callable


REQUIRED_COMMANDS = {
    "ffmpeg": "video processing and clip assembly",
    "ffprobe": "media metadata inventory",
}

OPTIONAL_COMMANDS = {
    "whisper": "speech transcription",
    "tesseract": "OCR/signage detection",
    "yolo": "visual object detection",
}

OPTIONAL_MODULES = {
    "cv2": "face/person presence detection",
}

OPENCV_FACE_PERSON_INSTALL = 'Install one OpenCV 4.x wheel: python -m pip install "opencv-python>=4.8,<5"'
OPENCV_DISTRIBUTIONS = (
    "opencv-python", "opencv-python-headless", "opencv-contrib-python", "opencv-contrib-python-headless",
)


def run_diagnostics(
    resolver: Callable[[str], str | None] | None = None,
    module_resolver: Callable[[str], Any] | None = None,
) -> dict:
    resolver = resolver or resolve_command
    module_resolver = module_resolver or importlib.util.find_spec
    required = [_command_status(name, purpose, resolver) for name, purpose in REQUIRED_COMMANDS.items()]
    optional = [_command_status(name, purpose, resolver) for name, purpose in OPTIONAL_COMMANDS.items()]
    optional.extend(_module_status(name, purpose, module_resolver) for name, purpose in OPTIONAL_MODULES.items())
    ok = all(item["available"] for item in required)
    return {
        "generated": datetime.now().isoformat(),
        "status": "ok" if ok else "error",
        "python": sys.version.split()[0],
        "required": required,
        "optional": optional,
        "missing_required": [item["name"] for item in required if not item["available"]],
        "missing_optional": [item["name"] for item in optional if not item["available"]],
    }


def format_diagnostics(report: dict) -> str:
    lines = [
        f"videoedit doctor: {report['status']}",
        f"python: {report['python']}",
        "",
        "required:",
    ]
    lines.extend(_format_command(item) for item in report.get("required", []))
    lines.append("")
    lines.append("optional:")
    lines.extend(_format_command(item) for item in report.get("optional", []))
    if report.get("missing_required"):
        lines.append("")
        lines.append("missing required: " + ", ".join(report["missing_required"]))
    return "\n".join(lines)


def _command_status(name: str, purpose: str, resolver: Callable[[str], str | None]) -> dict:
    path = resolver(name)
    return {
        "name": name,
        "type": "command",
        "purpose": purpose,
        "available": bool(path),
        "path": path,
    }


def _module_status(name: str, purpose: str, resolver: Callable[[str], Any]) -> dict:
    if name == "cv2":
        return opencv_face_person_status(resolver, purpose)
    try:
        spec = resolver(name)
    except (ImportError, ValueError):
        spec = None
    return {
        "name": name,
        "type": "python_module",
        "purpose": purpose,
        "available": bool(spec),
        "path": getattr(spec, "origin", None) if spec else None,
    }


def opencv_face_person_status(
    resolver: Callable[[str], Any] | None = None,
    purpose: str = "face/person presence detection",
) -> dict:
    """Inspect wheel compatibility without importing optional native code."""
    try:
        spec = (resolver or importlib.util.find_spec)("cv2")
    except (ImportError, ValueError):
        spec = None
    distributions = {}
    for name in OPENCV_DISTRIBUTIONS:
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    result = {
        "name": "cv2", "type": "python_module", "purpose": purpose,
        "available": bool(spec), "installed": bool(spec),
        "path": getattr(spec, "origin", None) if spec else None,
        "distributions": distributions, "status": "unverified",
    }
    if not spec:
        result.update(status="missing", message=OPENCV_FACE_PERSON_INSTALL)
    elif len(distributions) > 1:
        result.update(available=False, status="incompatible",
                      message="Multiple OpenCV wheel variants share cv2; remove conflicting variants first. " + OPENCV_FACE_PERSON_INSTALL)
    elif distributions:
        version = next(iter(distributions.values()))
        match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", version)
        if match and (4, 8) <= tuple(map(int, match.groups())) < (5, 0):
            result["status"] = "compatible"
        else:
            result.update(available=False, status="incompatible",
                          message=f"OpenCV {version} is not supported by the Haar/HOG face/person provider. " + OPENCV_FACE_PERSON_INSTALL)
    else:
        result["message"] = "OpenCV wheel version is unknown; face/person runtime compatibility is unverified."
    return result


def _format_command(item: dict) -> str:
    marker = "ok" if item.get("available") else item.get("status", "missing")
    path = f" ({item['path']})" if item.get("path") else ""
    message = f"\n    {item['message']}" if item.get("message") else ""
    return f"  {marker:7} {item['name']} - {item['purpose']}{path}{message}"


def resolve_command(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    scripts_dir = os.path.dirname(sys.executable)
    candidates = [os.path.join(scripts_dir, name), os.path.join(sys.prefix, "bin", name)]
    if sys.platform == "win32":
        candidates.extend(f"{candidate}.exe" for candidate in list(candidates))
    for candidate in candidates:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
