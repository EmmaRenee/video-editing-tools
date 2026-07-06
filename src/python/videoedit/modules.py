"""Feature module registry and project-local module configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import importlib.metadata
import importlib.util
import json
import logging
import os
import re
from typing import Any, Callable

from .diagnostics import resolve_command


CONFIG_DIR = ".videoedit"
CONFIG_FILE = "config.json"
ENTRY_POINT_GROUP = "videoedit.modules"
logger = logging.getLogger(__name__)

DiagnosticFunc = Callable[[], dict[str, Any]]


@dataclass
class ModuleOperation:
    name: str
    description: str
    func: Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass
class FeatureModule:
    id: str
    description: str
    category: str
    core: bool = False
    enabled_by_default: bool = True
    available: bool = True
    unavailable_reason: str | None = None
    operations: list[ModuleOperation] = field(default_factory=list)
    presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    diagnostics: DiagnosticFunc | None = None
    source: str = "builtin"


BUILTIN_MODULES: dict[str, FeatureModule] = {
    "core.inventory": FeatureModule(
        id="core.inventory",
        description="Footage inventory and media metadata scanning",
        category="core",
        core=True,
    ),
    "core.rating": FeatureModule(
        id="core.rating",
        description="Deterministic signal analysis, rating, and candidate selection",
        category="core",
        core=True,
    ),
    "core.calibration": FeatureModule(
        id="core.calibration",
        description="Ground-truth scoring evaluation and calibration reports",
        category="core",
        core=True,
    ),
    "core.pipeline": FeatureModule(
        id="core.pipeline",
        description="YAML pipeline planning, validation, and execution",
        category="core",
        core=True,
    ),
    "core.review": FeatureModule(
        id="core.review",
        description="Review assets, approvals, and rough-cut assembly",
        category="core",
        core=True,
    ),
    "core.handoff": FeatureModule(
        id="core.handoff",
        description="DaVinci/FFmpeg handoff artifacts and clip extraction",
        category="core",
        core=True,
    ),
    "delivery.captions": FeatureModule(
        id="delivery.captions",
        description="Styled caption burning and delivery formatting",
        category="delivery",
    ),
    "content.series": FeatureModule(
        id="content.series",
        description="Reusable content-series planning from rated footage",
        category="content",
    ),
    "content.reports": FeatureModule(
        id="content.reports",
        description="Editorial content maps and quote-mining reports",
        category="content",
    ),
    "project.scaffold": FeatureModule(
        id="project.scaffold",
        description="Video project folder and workflow scaffolding",
        category="project",
    ),
    "advanced.vision": FeatureModule(
        id="advanced.vision",
        description="Optional OCR, object, face, and person detection providers",
        category="advanced",
    ),
    "advanced.ai": FeatureModule(
        id="advanced.ai",
        description="Optional AI profiles, frame scoring, and missed-moment discovery",
        category="advanced",
    ),
    "advanced.motorsports": FeatureModule(
        id="advanced.motorsports",
        description="Motorsports event inference from rated footage",
        category="advanced",
    ),
    "cloud.adapters": FeatureModule(
        id="cloud.adapters",
        description="Optional maintained adapters for cloud video and voice tools",
        category="cloud",
        enabled_by_default=False,
        available=False,
        unavailable_reason="cloud adapters are documented as future maintained modules",
    ),
}

OPERATION_MODULES = {
    "inventory": "core.inventory",
    "analyze_signals": "core.rating",
    "rate_footage": "core.rating",
    "detect_highlights_audio": "core.rating",
    "detect_highlights_transcript": "core.rating",
    "transcribe_whisper": "core.rating",
    "evaluate_ratings": "core.calibration",
    "calibrate_scoring": "core.calibration",
    "extract_segments": "core.handoff",
    "generate_edl": "core.handoff",
    "generate_review_assets": "core.review",
    "approve_candidates": "core.review",
    "plan_roughcut": "core.review",
    "assemble_rough_cut": "core.review",
    "format_video": "delivery.captions",
    "burn_captions": "delivery.captions",
    "normalize_audio": "delivery.captions",
    "concatenate_videos": "delivery.captions",
    "detect_ocr_signage": "advanced.vision",
    "detect_visual_objects": "advanced.vision",
    "score_ai_frames": "advanced.ai",
    "detect_face_person_presence": "advanced.vision",
    "detect_motorsports_events": "advanced.motorsports",
    "cluster_transcript_topics": "content.reports",
    "find_ai_missed_moments": "advanced.ai",
    "generate_missed_review": "advanced.ai",
    "plan_content_series": "content.series",
    "generate_content_map": "content.reports",
    "quote_mining": "content.reports",
    "scaffold_project": "project.scaffold",
}

PRESET_MODULES = {
    "simple": {"core.rating"},
    "reel": {"core.rating", "core.handoff"},
    "roughcut": {"core.rating", "core.review", "core.handoff"},
    "youtube": {"core.rating", "core.handoff"},
    "documentary": {"core.rating", "core.handoff"},
    "motorsports": {"core.rating", "advanced.motorsports", "content.reports", "core.review", "core.handoff"},
}


def load_module_config(cwd: str | None = None) -> dict[str, Any]:
    path = module_config_path(cwd)
    if not os.path.exists(path):
        return {"enabled_modules": [], "disabled_modules": []}
    with open(path, encoding="utf-8") as handle:
        data = json.loads(handle.read())
    data.setdefault("enabled_modules", [])
    data.setdefault("disabled_modules", [])
    return data


def save_module_config(config: dict[str, Any], cwd: str | None = None) -> str:
    path = module_config_path(cwd)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "generated": config.get("generated"),
        "updated": datetime.now().isoformat(),
        "enabled_modules": sorted(set(config.get("enabled_modules", []))),
        "disabled_modules": sorted(set(config.get("disabled_modules", []))),
    }
    if not payload["generated"]:
        payload["generated"] = payload["updated"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    return path


def module_config_path(cwd: str | None = None) -> str:
    root = os.fspath(cwd or os.getcwd())
    return os.path.join(root, CONFIG_DIR, CONFIG_FILE)


def all_modules(cwd: str | None = None, include_external: bool = True) -> dict[str, FeatureModule]:
    modules = {key: value for key, value in BUILTIN_MODULES.items()}
    if include_external:
        modules.update(discover_external_modules())
    return modules


def enabled_modules(cwd: str | None = None, include_external: bool = True) -> dict[str, FeatureModule]:
    config = load_module_config(cwd)
    modules = all_modules(cwd, include_external=include_external)
    return {
        module_id: module
        for module_id, module in modules.items()
        if is_module_enabled(module, config)
    }


def is_module_enabled(module: FeatureModule, config: dict[str, Any] | None = None) -> bool:
    config = config or load_module_config()
    if module.core:
        return True
    if not module.available:
        return False
    enabled = set(config.get("enabled_modules", []))
    disabled = set(config.get("disabled_modules", []))
    if module.id in disabled:
        return False
    if module.id in enabled:
        return True
    return module.enabled_by_default


def require_module_enabled(module_id: str, cwd: str | None = None) -> None:
    modules = all_modules(cwd)
    if module_id not in modules:
        raise KeyError(f"Unknown module: {module_id}")
    module = modules[module_id]
    if not module.available:
        reason = f": {module.unavailable_reason}" if module.unavailable_reason else ""
        raise RuntimeError(f"module {module_id} is unavailable{reason}")
    if not is_module_enabled(module, load_module_config(cwd)):
        raise RuntimeError(f"module {module_id} is disabled; run `videoedit modules enable {module_id}`")


def enable_module(module_id: str, cwd: str | None = None) -> str:
    modules = all_modules(cwd)
    if module_id not in modules:
        raise KeyError(f"Unknown module: {module_id}")
    module = modules[module_id]
    if module.core:
        return save_module_config(load_module_config(cwd), cwd)
    if not module.available:
        reason = f": {module.unavailable_reason}" if module.unavailable_reason else ""
        raise RuntimeError(f"module {module_id} is unavailable{reason}")
    config = load_module_config(cwd)
    enabled = set(config.get("enabled_modules", []))
    disabled = set(config.get("disabled_modules", []))
    enabled.add(module_id)
    disabled.discard(module_id)
    config["enabled_modules"] = sorted(enabled)
    config["disabled_modules"] = sorted(disabled)
    return save_module_config(config, cwd)


def disable_module(module_id: str, cwd: str | None = None) -> str:
    modules = all_modules(cwd)
    if module_id not in modules:
        raise KeyError(f"Unknown module: {module_id}")
    module = modules[module_id]
    if module.core:
        raise RuntimeError(f"core module {module_id} cannot be disabled")
    config = load_module_config(cwd)
    enabled = set(config.get("enabled_modules", []))
    disabled = set(config.get("disabled_modules", []))
    enabled.discard(module_id)
    disabled.add(module_id)
    config["enabled_modules"] = sorted(enabled)
    config["disabled_modules"] = sorted(disabled)
    return save_module_config(config, cwd)


def module_for_operation(operation_name: str) -> str:
    return OPERATION_MODULES.get(operation_name, "core.pipeline")


def operation_enabled(operation_name: str, cwd: str | None = None) -> bool:
    modules = all_modules(cwd)
    module = modules.get(module_for_operation(operation_name))
    if module is None:
        return True
    return is_module_enabled(module, load_module_config(cwd))


def preset_enabled(preset_name: str, cwd: str | None = None) -> bool:
    required = PRESET_MODULES.get(preset_name, set())
    return modules_available(required, cwd)


def modules_available(module_ids: set[str] | list[str] | tuple[str, ...] | str, cwd: str | None = None) -> bool:
    if not module_ids:
        return True
    if isinstance(module_ids, str):
        module_ids = [module_ids]
    modules = all_modules(cwd)
    config = load_module_config(cwd)
    for module_id in module_ids:
        module = modules.get(str(module_id))
        if module is None or not is_module_enabled(module, config):
            return False
    return True


def assert_modules_available(module_ids: list[str] | set[str] | tuple[str, ...] | str, cwd: str | None = None) -> None:
    if not module_ids:
        return
    if isinstance(module_ids, str):
        module_ids = [module_ids]
    modules = all_modules(cwd)
    config = load_module_config(cwd)
    for module_id in module_ids:
        module = modules.get(str(module_id))
        if module is None:
            raise ValueError(f"requires unknown module: {module_id}")
        if not module.available:
            reason = f": {module.unavailable_reason}" if module.unavailable_reason else ""
            raise ValueError(f"requires unavailable module {module_id}{reason}")
        if not is_module_enabled(module, config):
            raise ValueError(f"requires disabled module {module_id}")


def module_rows(cwd: str | None = None) -> list[dict[str, Any]]:
    config = load_module_config(cwd)
    rows = []
    for module in sorted(all_modules(cwd).values(), key=lambda item: item.id):
        rows.append(
            {
                "id": module.id,
                "category": module.category,
                "core": module.core,
                "enabled": is_module_enabled(module, config),
                "available": module.available,
                "source": module.source,
                "description": module.description,
                "unavailable_reason": module.unavailable_reason,
            }
        )
    return rows


def run_module_diagnostics(cwd: str | None = None) -> dict[str, Any]:
    rows = module_rows(cwd)
    checks = [_module_dependency_check(row["id"]) for row in rows]
    return {
        "generated": datetime.now().isoformat(),
        "config": module_config_path(cwd),
        "modules": rows,
        "checks": checks,
    }


def scaffold_module(module_name: str, output: str) -> dict[str, str]:
    slug = _safe_slug(module_name).replace("_", "-")
    package = _safe_slug(module_name).replace("-", "_")
    root = os.path.abspath(os.fspath(output))
    package_dir = os.path.join(root, package)
    tests_dir = os.path.join(root, "tests")
    os.makedirs(package_dir, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)
    files = {
        "pyproject": os.path.join(root, "pyproject.toml"),
        "init": os.path.join(package_dir, "__init__.py"),
        "module": os.path.join(package_dir, "module.py"),
        "test": os.path.join(tests_dir, "test_module.py"),
        "readme": os.path.join(root, "README.md"),
    }
    _write_file(
        files["pyproject"],
        f"""[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "videoedit-{slug}"
version = "0.1.0"
description = "Community videoedit module: {module_name}"
requires-python = ">=3.10"
dependencies = ["videoedit"]

[project.entry-points."{ENTRY_POINT_GROUP}"]
{package} = "{package}.module:get_module"
""",
    )
    _write_file(files["init"], '"""Community videoedit module."""\n')
    _write_file(
        files["module"],
        f'''"""videoedit community module entry point."""

from __future__ import annotations


def example_operation(context, params):
    output = params.get("output") or context.get("output")
    return {{"output": output, "status": "ok"}}


def get_module():
    return {{
        "id": "community.{package}",
        "description": "Community module generated by videoedit",
        "category": "community",
        "operations": [
            {{
                "name": "{package}_example",
                "description": "Example generated operation",
                "func": example_operation,
            }}
        ],
        "presets": {{}},
    }}
''',
    )
    _write_file(
        files["test"],
        f'''from {package}.module import get_module


def test_module_metadata():
    module = get_module()
    assert module["id"] == "community.{package}"
    assert module["operations"][0]["name"] == "{package}_example"
''',
    )
    _write_file(
        files["readme"],
        f"""# videoedit-{slug}

Install this module in editable mode from this directory:

```bash
python -m pip install -e .
videoedit modules list
videoedit operations
```

The package contributes modules through the `{ENTRY_POINT_GROUP}` entry point group.
""",
    )
    return files


def discover_external_modules() -> dict[str, FeatureModule]:
    modules: dict[str, FeatureModule] = {}
    try:
        entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - old importlib.metadata API
        entry_points = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])
    for entry_point in entry_points:
        try:
            loaded = entry_point.load()
            value = loaded() if callable(loaded) else loaded
            module = _coerce_module(value, source=f"entry_point:{entry_point.name}")
            modules[module.id] = module
        except (ImportError, SyntaxError, AttributeError, TypeError, ValueError) as exc:
            logger.warning("Skipping videoedit module entry point %s: %s", entry_point.name, exc)
            continue
    return modules


def _coerce_module(value: Any, source: str) -> FeatureModule:
    if isinstance(value, FeatureModule):
        value.source = source
        return value
    if not isinstance(value, dict):
        raise TypeError("videoedit module entry point must return a FeatureModule or dict")
    operations = []
    for item in value.get("operations", []):
        if isinstance(item, ModuleOperation):
            operations.append(item)
        else:
            operations.append(
                ModuleOperation(
                    name=item["name"],
                    description=item.get("description", ""),
                    func=item["func"],
                )
            )
    return FeatureModule(
        id=value["id"],
        description=value.get("description", ""),
        category=value.get("category", "community"),
        core=bool(value.get("core", False)),
        enabled_by_default=bool(value.get("enabled_by_default", True)),
        available=bool(value.get("available", True)),
        unavailable_reason=value.get("unavailable_reason"),
        operations=operations,
        presets=dict(value.get("presets", {})),
        diagnostics=value.get("diagnostics"),
        source=source,
    )


def _module_dependency_check(module_id: str) -> dict[str, Any]:
    if module_id == "advanced.vision":
        return {
            "module": module_id,
            "checks": [
                _command_status("tesseract"),
                _command_status("yolo"),
                _python_module_status("cv2"),
            ],
        }
    if module_id == "advanced.ai":
        return {
            "module": module_id,
            "checks": [
                _python_module_status("open_clip"),
                _python_module_status("torch"),
                _python_module_status("PIL"),
            ],
        }
    if module_id == "core.rating":
        return {"module": module_id, "checks": [_command_status("whisper")]}
    if module_id == "delivery.captions":
        return {"module": module_id, "checks": [_command_status("ffmpeg"), _command_status("ffprobe")]}
    return {"module": module_id, "checks": []}


def _command_status(name: str) -> dict[str, Any]:
    path = resolve_command(name)
    return {"name": name, "type": "command", "available": bool(path), "path": path}


def _python_module_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    return {"name": name, "type": "python_module", "available": bool(spec), "path": getattr(spec, "origin", None)}


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "module"


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
