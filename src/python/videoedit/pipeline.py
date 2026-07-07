"""YAML pipeline runner."""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import time
from typing import Any

from .modules import PRESET_MODULES, all_modules, assert_modules_available, is_module_enabled, load_module_config
from .operations import OperationRegistry, default_registry
from .presets import PRESETS
from .simple_yaml import dumps, load_mapping


REFERENCE_ROOTS = {"input", "output", "pipeline"}

OPERATION_OUTPUTS = {
    "inventory": {"inventory", "count"},
    "analyze_signals": {"ratings", "candidates"},
    "rate_footage": {"ratings", "candidates"},
    "detect_highlights_audio": {"output", "selections", "files", "count"},
    "detect_highlights_transcript": {"output", "selections", "files", "count"},
    "transcribe_whisper": {"output", "count"},
    "evaluate_ratings": {"report", "markdown", "missed", "false_positives", "metrics"},
    "calibrate_scoring": {
        "report",
        "markdown",
        "missed",
        "false_positives",
        "config_candidates",
        "proposed_config",
        "best",
        "metrics",
    },
    "extract_segments": {"output", "files"},
    "generate_edl": {"output", "files"},
    "generate_review_assets": {"manifest", "contact_sheet", "decisions", "clips", "thumbnails", "proxies", "warnings"},
    "approve_candidates": {"approved"},
    "plan_roughcut": {"plan", "report", "clips", "duration"},
    "assemble_rough_cut": {"output"},
    "format_video": {"output"},
    "burn_captions": {"output"},
    "normalize_audio": {"output"},
    "concatenate_videos": {"output"},
    "detect_ocr_signage": {"output", "count", "status", "warnings"},
    "detect_visual_objects": {
        "output",
        "count",
        "detection_count",
        "class_count",
        "segment_count",
        "status",
        "warnings",
    },
    "detect_face_person_presence": {"output", "count", "status", "warnings"},
    "score_ai_frames": {"output", "status", "sources", "frames", "warnings"},
    "detect_motorsports_events": {"output", "count"},
    "cluster_transcript_topics": {"output", "count"},
    "find_ai_missed_moments": {"output", "count"},
    "generate_missed_review": {"html", "decisions", "count"},
    "plan_content_series": {"plan", "captions", "selections", "count"},
    "generate_content_map": {"json", "markdown"},
    "quote_mining": {"markdown", "candidates", "transcript_hits"},
    "scaffold_project": {"project", "folders", "files"},
}

OPERATION_CONTEXT_OUTPUTS = {
    "inventory": {"inventory"},
    "analyze_signals": {"ratings", "selections"},
    "rate_footage": {"ratings", "selections"},
    "detect_highlights_audio": {"filtered_candidates", "filtered_selections"},
    "detect_highlights_transcript": {"filtered_candidates", "filtered_selections"},
    "evaluate_ratings": {"calibration_report"},
    "calibrate_scoring": {"calibration_report", "proposed_config"},
    "generate_review_assets": {"review_assets", "review_decisions"},
    "approve_candidates": {"approved"},
    "plan_roughcut": {"roughcut_plan"},
    "detect_ocr_signage": {"ocr_signage"},
    "detect_visual_objects": {"visual_objects"},
    "detect_face_person_presence": {"face_person_presence"},
    "score_ai_frames": {"ai_frame_scores"},
    "detect_motorsports_events": {"motorsports_events"},
    "cluster_transcript_topics": {"topic_clusters"},
    "find_ai_missed_moments": {"ai_missed_moments"},
    "generate_missed_review": {"missed_review_decisions"},
    "plan_content_series": {"series_plan", "series_selections"},
    "generate_content_map": {"content_map"},
    "quote_mining": {"quote_mining"},
}


def write_preset(name: str, output: str) -> dict[str, Any]:
    presets = available_presets(enabled_only=False)
    if name not in presets:
        raise KeyError(f"Unknown preset: {name}")
    required = set(PRESET_MODULES.get(name, set()))
    required.update(presets[name].get("requires_modules", []))
    if required:
        assert_modules_available(sorted(required))
    output = os.fspath(output)
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(dumps(presets[name]) + "\n")
    return presets[name]


def available_presets(enabled_only: bool = True) -> dict[str, dict[str, Any]]:
    presets = dict(PRESETS)
    module_config = load_module_config()
    for module in all_modules().values():
        if not module.presets:
            continue
        if enabled_only and not is_module_enabled(module, module_config):
            continue
        presets.update(module.presets)
    if not enabled_only:
        return presets
    return {name: preset for name, preset in presets.items() if _preset_is_enabled(name, preset)}


def load_pipeline(path: str) -> dict[str, Any]:
    data = load_mapping(path)
    validate_pipeline(data)
    return data


def validate_pipeline(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("pipeline must be a mapping")
    if "steps" not in data or not isinstance(data["steps"], list):
        raise ValueError("pipeline requires a steps list")
    assert_modules_available(data.get("requires_modules", []))
    _validate_required_dependencies(data.get("requires_dependencies", []))
    registry = default_registry(enabled_only=False)
    step_infos = []
    step_names: set[str] = set()
    for index, step in enumerate(data["steps"], 1):
        if not isinstance(step, dict):
            raise ValueError(f"step {index} must be a mapping")
        if "operation" not in step:
            raise ValueError(f"step {index} is missing operation")
        operation = registry.get(step["operation"])
        assert_modules_available([operation.module])
        step_name = str(step.get("name") or operation.name)
        if not _valid_reference_name(step_name):
            raise ValueError(f"step {index} has invalid name: {step_name}")
        if step_name in step_names:
            raise ValueError(f"duplicate step name: {step_name}")
        if "params" in step and not isinstance(step["params"], dict):
            raise ValueError(f"step {index} params must be a mapping")
        step_infos.append((index, step, step_name, operation.name))
        step_names.add(step_name)

    seen_steps: set[str] = set()
    step_operations = {name: operation_name for _index, _step, name, operation_name in step_infos}
    available_roots = set(REFERENCE_ROOTS)
    for index, step, step_name, operation_name in step_infos:
        label = f"step {index} ({step_name})"
        if "input" in step:
            _validate_references(step["input"], seen_steps, step_names, step_operations, available_roots, label)
        _validate_references(step.get("params") or {}, seen_steps, step_names, step_operations, available_roots, label)
        seen_steps.add(step_name)
        available_roots.update(OPERATION_CONTEXT_OUTPUTS.get(operation_name, set()))


def run_pipeline(
    path: str,
    input_path: str,
    output_dir: str,
    registry: OperationRegistry | None = None,
) -> dict[str, Any]:
    path = os.fspath(path)
    input_path = os.fspath(input_path)
    output_dir = os.fspath(output_dir)
    pipeline = load_pipeline(path)
    registry = registry or default_registry(enabled_only=False)
    os.makedirs(output_dir, exist_ok=True)
    started = datetime.now()
    started_monotonic = time.monotonic()
    context: dict[str, Any] = {
        "input": input_path,
        "output": output_dir,
        "pipeline": pipeline.get("name", os.path.splitext(os.path.basename(path))[0]),
        "results": {},
        "steps": [],
    }
    manifest_path = os.path.join(output_dir, "pipeline_run.json")
    try:
        for step in pipeline["steps"]:
            operation = registry.get(step["operation"])
            step_name = step.get("name", operation.name)
            step_start = time.monotonic()
            params = _resolve_value(dict(step.get("params") or {}), context)
            if "input" in step:
                params.setdefault("input", _resolve_value(step["input"], context))
            step_output = os.path.join(output_dir, step_name)
            if operation.name not in {"generate_edl", "extract_segments"}:
                params.setdefault("output", step_output)
            try:
                result = operation.func(context, params)
            except Exception as exc:
                context["steps"].append(
                    {
                        "name": step_name,
                        "operation": operation.name,
                        "status": "error",
                        "duration_seconds": round(time.monotonic() - step_start, 3),
                        "error": str(exc),
                    }
                )
                _write_run_manifest(
                    manifest_path,
                    pipeline,
                    context,
                    started,
                    started_monotonic,
                    status="error",
                    error=str(exc),
                )
                raise
            context["results"][step_name] = result
            context["steps"].append(
                {
                    "name": step_name,
                    "operation": operation.name,
                    "status": "ok",
                    "duration_seconds": round(time.monotonic() - step_start, 3),
                    "result": result,
                }
            )
        _write_run_manifest(manifest_path, pipeline, context, started, started_monotonic, status="ok")
        context["manifest"] = manifest_path
    except Exception:
        context["manifest"] = manifest_path
        raise
    return context


def plan_pipeline(path: str, input_path: str, output_dir: str) -> dict[str, Any]:
    path = os.fspath(path)
    input_path = os.fspath(input_path)
    output_dir = os.fspath(output_dir)
    pipeline = load_pipeline(path)
    registry = default_registry(enabled_only=False)
    context: dict[str, Any] = {
        "input": input_path,
        "output": output_dir,
        "pipeline": pipeline.get("name", os.path.splitext(os.path.basename(path))[0]),
        "results": {},
    }
    steps = []
    for step in pipeline["steps"]:
        operation = registry.get(step["operation"])
        step_name = step.get("name", operation.name)
        params = _resolve_value(dict(step.get("params") or {}), context)
        step_input = None
        if "input" in step:
            step_input = _resolve_value(step["input"], context)
            params.setdefault("input", step_input)
        else:
            step_input = _planned_implicit_input(operation.name, params, context)
            if step_input is not None:
                params.setdefault("input", step_input)
        step_output = os.path.join(output_dir, step_name)
        if operation.name not in {"generate_edl", "extract_segments"}:
            params.setdefault("output", step_output)
        elif "output" not in params:
            params["output"] = output_dir
        planned_result = _planned_result(operation.name, params, step_output, context)
        context["results"][step_name] = planned_result
        _apply_planned_context(operation.name, planned_result, context)
        steps.append(
            {
                "name": step_name,
                "operation": operation.name,
                "input": step_input,
                "params": params,
                "default_output": step_output,
                "planned_result": planned_result,
            }
        )
    return {
        "pipeline": context["pipeline"],
        "description": pipeline.get("description"),
        "requirements": {
            "modules": list(pipeline.get("requires_modules", [])),
            "dependencies": list(pipeline.get("requires_dependencies", [])),
        },
        "input": input_path,
        "output": output_dir,
        "steps": steps,
    }


def _resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context) for item in value]
    if not isinstance(value, str):
        return value
    if "${" in value:
        return re.sub(r"\$\{([^}]+)\}", lambda match: str(_lookup_reference(match.group(1), context, match.group(0))), value)
    if value.startswith("$"):
        return _lookup_reference(value[1:], context, default=value)
    if value in context or "." in value:
        resolved = _lookup_reference(value, context, default=None)
        if resolved is not None:
            return resolved
    return value


def _lookup_reference(reference: str, context: dict[str, Any], default: Any = None) -> Any:
    if reference in context:
        return context[reference]
    parts = reference.split(".")
    current: Any = context
    if parts and parts[0] in context.get("results", {}):
        current = context["results"][parts[0]]
        parts = parts[1:]
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _planned_result(
    operation_name: str,
    params: dict[str, Any],
    step_output: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    output = os.fspath(params.get("output") or step_output)
    if operation_name in {"rate_footage", "analyze_signals"}:
        return {"ratings": os.path.join(output, "ratings.json"), "candidates": "unknown"}
    if operation_name == "inventory":
        return {"inventory": os.path.join(output, "inventory.json"), "count": "unknown"}
    if operation_name in {"detect_highlights_audio", "detect_highlights_transcript"}:
        label = params.get("label", "audio_spike" if operation_name == "detect_highlights_audio" else "transcript_hit")
        output = _filter_output_plan(output, label)
        selections = os.fspath(
            params.get("selections_output")
            or params.get("selection_output")
            or os.path.join(os.path.dirname(output) or ".", f"{_safe_slug(label)}_selections")
        )
        return {"output": output, "selections": selections, "files": [], "count": "unknown"}
    if operation_name == "generate_review_assets":
        return {
            "manifest": os.path.join(output, "review_assets.json"),
            "contact_sheet": os.path.join(output, "contact_sheet.html"),
            "decisions": os.path.join(output, "review_decisions.json"),
            "clips": "unknown",
            "thumbnails": "unknown",
            "proxies": "unknown",
            "warnings": [],
        }
    if operation_name == "approve_candidates":
        return {"approved": output}
    if operation_name == "plan_roughcut":
        root, _ext = os.path.splitext(output)
        return {"plan": output, "report": f"{root}_report.md", "clips": "unknown", "duration": "unknown"}
    if operation_name in {"generate_edl", "extract_segments"}:
        return {"output": output, "files": []}
    if operation_name == "transcribe_whisper":
        return {"output": output, "count": "unknown"}
    if operation_name == "evaluate_ratings":
        return {
            "report": os.path.join(output, "calibration_report.json"),
            "markdown": os.path.join(output, "calibration_report.md"),
            "missed": os.path.join(output, "missed_moments.csv"),
            "false_positives": os.path.join(output, "false_positives.csv"),
            "metrics": {},
        }
    if operation_name == "calibrate_scoring":
        return {
            "report": os.path.join(output, "calibration_report.json"),
            "markdown": os.path.join(output, "calibration_report.md"),
            "missed": os.path.join(output, "missed_moments.csv"),
            "false_positives": os.path.join(output, "false_positives.csv"),
            "config_candidates": os.path.join(output, "config_candidates.csv"),
            "proposed_config": os.path.join(output, "proposed_config.json"),
            "best": "unknown",
            "metrics": {},
        }
    if operation_name == "assemble_rough_cut":
        return {"output": output}
    if operation_name in {"format_video", "burn_captions", "normalize_audio", "concatenate_videos"}:
        return {"output": output}
    if operation_name == "detect_ocr_signage":
        return {"output": _json_output_plan(output, "ocr_signage.json"), "count": "unknown", "status": "planned", "warnings": []}
    if operation_name == "detect_visual_objects":
        return {
            "output": _json_output_plan(output, "visual_objects.json"),
            "count": "unknown",
            "detection_count": "unknown",
            "class_count": "unknown",
            "segment_count": "unknown",
            "status": "planned",
            "warnings": [],
        }
    if operation_name == "detect_face_person_presence":
        return {"output": _json_output_plan(output, "face_person_presence.json"), "count": "unknown", "status": "planned", "warnings": []}
    if operation_name == "score_ai_frames":
        return {
            "output": _json_output_plan(output, "ai_frame_scores.json"),
            "status": "planned",
            "sources": "unknown",
            "frames": "unknown",
            "warnings": [],
        }
    if operation_name == "detect_motorsports_events":
        return {"output": _json_output_plan(output, "motorsports_events.json"), "count": "unknown"}
    if operation_name == "cluster_transcript_topics":
        return {"output": _json_output_plan(output, "topic_clusters.json"), "count": "unknown"}
    if operation_name == "find_ai_missed_moments":
        return {"output": _json_output_plan(output, "ai_missed_moments.json"), "count": "unknown"}
    if operation_name == "generate_missed_review":
        return {
            "html": os.path.join(output, "missed_review.html"),
            "decisions": os.path.join(output, "missed_review_decisions.json"),
            "count": "unknown",
        }
    if operation_name == "plan_content_series":
        return {
            "plan": os.path.join(output, "series_plan.json"),
            "captions": os.path.join(output, "caption_suggestions.md"),
            "selections": os.path.join(output, "series_selections.json"),
            "count": "unknown",
        }
    if operation_name == "generate_content_map":
        return {"json": os.path.join(output, "content_map.json"), "markdown": os.path.join(output, "ranked_content_map.md")}
    if operation_name == "quote_mining":
        return {"markdown": os.path.join(output, "quote_mining.md"), "candidates": "unknown", "transcript_hits": "unknown"}
    if operation_name == "scaffold_project":
        return {"project": output, "folders": {}, "files": {}}
    return {"output": output}


def _planned_implicit_input(operation_name: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
    if "input" in params:
        return params["input"]
    if operation_name in {"generate_edl", "extract_segments"} and context.get("selections"):
        return context["selections"]
    if operation_name in {"generate_review_assets", "approve_candidates"} and context.get("ratings"):
        return context["ratings"]
    if operation_name in {"detect_highlights_audio", "detect_highlights_transcript"} and context.get("ratings"):
        return context["ratings"]
    if operation_name in {"evaluate_ratings", "calibrate_scoring"} and context.get("ratings"):
        return context["ratings"]
    if operation_name in {"detect_motorsports_events", "cluster_transcript_topics"} and context.get("ratings"):
        return context["ratings"]
    if operation_name in {"plan_content_series", "generate_content_map", "quote_mining"} and context.get("ratings"):
        return context["ratings"]
    if operation_name == "plan_roughcut" and context.get("approved"):
        return context["approved"]
    if operation_name == "assemble_rough_cut" and context.get("approved"):
        return context["approved"]
    return None


def _apply_planned_context(operation_name: str, result: dict[str, Any], context: dict[str, Any]) -> None:
    if operation_name == "inventory":
        context["inventory"] = result.get("inventory")
    elif operation_name in {"rate_footage", "analyze_signals"}:
        ratings = result.get("ratings")
        context["ratings"] = ratings
        context["selections"] = os.path.join(os.path.dirname(os.fspath(ratings)), "selections") if ratings else None
    elif operation_name in {"detect_highlights_audio", "detect_highlights_transcript"}:
        context["filtered_candidates"] = result.get("output")
        context["filtered_selections"] = result.get("selections")
    elif operation_name == "evaluate_ratings":
        context["calibration_report"] = result.get("report")
    elif operation_name == "calibrate_scoring":
        context["calibration_report"] = result.get("report")
        context["proposed_config"] = result.get("proposed_config")
    elif operation_name == "generate_review_assets":
        context["review_assets"] = result.get("manifest")
        context["review_decisions"] = result.get("decisions")
    elif operation_name == "approve_candidates":
        context["approved"] = result.get("approved")
    elif operation_name == "plan_roughcut":
        context["roughcut_plan"] = result.get("plan")
    elif operation_name == "detect_ocr_signage":
        context["ocr_signage"] = result.get("output")
    elif operation_name == "detect_visual_objects":
        context["visual_objects"] = result.get("output")
    elif operation_name == "detect_face_person_presence":
        context["face_person_presence"] = result.get("output")
    elif operation_name == "score_ai_frames":
        context["ai_frame_scores"] = result.get("output")
    elif operation_name == "detect_motorsports_events":
        context["motorsports_events"] = result.get("output")
    elif operation_name == "cluster_transcript_topics":
        context["topic_clusters"] = result.get("output")
    elif operation_name == "find_ai_missed_moments":
        context["ai_missed_moments"] = result.get("output")
    elif operation_name == "generate_missed_review":
        context["missed_review_decisions"] = result.get("decisions")
    elif operation_name == "plan_content_series":
        context["series_plan"] = result.get("plan")
        context["series_selections"] = result.get("selections")
    elif operation_name == "generate_content_map":
        context["content_map"] = result.get("json")
    elif operation_name == "quote_mining":
        context["quote_mining"] = result.get("markdown")


def _json_output_plan(value: str, default_name: str) -> str:
    if os.path.splitext(value)[1].lower() == ".json":
        return value
    return os.path.join(value, default_name)


def _filter_output_plan(value: str, label: str) -> str:
    if os.path.splitext(value)[1].lower() == ".json":
        return value
    return os.path.join(value, f"{_safe_slug(label)}_candidates.json")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"


def _write_run_manifest(
    path: str,
    pipeline: dict[str, Any],
    context: dict[str, Any],
    started: datetime,
    started_monotonic: float,
    status: str,
    error: str | None = None,
) -> None:
    payload = {
        "pipeline": context.get("pipeline"),
        "description": pipeline.get("description"),
        "status": status,
        "started": started.isoformat(),
        "finished": datetime.now().isoformat(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "input": context.get("input"),
        "output": context.get("output"),
        "steps": context.get("steps", []),
        "results": context.get("results", {}),
    }
    if error:
        payload["error"] = error
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2))


def _validate_references(
    value: Any,
    seen_steps: set[str],
    all_steps: set[str],
    step_operations: dict[str, str],
    available_roots: set[str],
    location: str,
) -> None:
    for reference, explicit in _find_references(value):
        _validate_reference(reference, explicit, seen_steps, all_steps, step_operations, available_roots, location)


def _validate_reference(
    reference: str,
    explicit: bool,
    seen_steps: set[str],
    all_steps: set[str],
    step_operations: dict[str, str],
    available_roots: set[str],
    location: str,
) -> None:
    parts = reference.split(".")
    root = parts[0]
    if root in available_roots:
        if len(parts) > 1:
            raise ValueError(f"{location} has invalid context reference: {reference}")
        return
    if root in seen_steps:
        if len(parts) == 1:
            return
        operation_outputs = OPERATION_OUTPUTS.get(step_operations[root], set())
        if operation_outputs and parts[1] not in operation_outputs:
            raise ValueError(f"{location} references unknown output: {reference}")
        return
    if root in all_steps:
        raise ValueError(f"{location} references future step: {reference}")
    if explicit:
        raise ValueError(f"{location} references unknown value: {reference}")


def _find_references(value: Any) -> list[tuple[str, bool]]:
    if isinstance(value, dict):
        references: list[tuple[str, bool]] = []
        for item in value.values():
            references.extend(_find_references(item))
        return references
    if isinstance(value, list):
        references = []
        for item in value:
            references.extend(_find_references(item))
        return references
    if not isinstance(value, str):
        return []

    references = [(match.group(1), True) for match in re.finditer(r"\$\{([^}]+)\}", value)]
    if references:
        return references
    if value.startswith("$") and _looks_like_reference(value[1:]):
        return [(value[1:], True)]
    if "." in value and _looks_like_reference(value):
        return [(value, False)]
    return []


def _looks_like_reference(value: str) -> bool:
    if "/" in value or "\\" in value:
        return False
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)*$", value))


def _valid_reference_name(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", value))


def _validate_required_dependencies(dependencies: Any) -> None:
    if dependencies in (None, []):
        return
    if not isinstance(dependencies, list):
        raise ValueError("requires_dependencies must be a list")
    for index, dependency in enumerate(dependencies, 1):
        if not isinstance(dependency, dict):
            raise ValueError(f"requires_dependencies item {index} must be a mapping")
        if not dependency.get("name"):
            raise ValueError(f"requires_dependencies item {index} is missing name")
        dependency_type = dependency.get("type", "python_module")
        if dependency_type not in {"python_module", "command"}:
            raise ValueError(f"requires_dependencies item {index} has unsupported type: {dependency_type}")


def _preset_is_enabled(name: str, preset: dict[str, Any]) -> bool:
    required = set(PRESET_MODULES.get(name, set()))
    required.update(preset.get("requires_modules", []))
    try:
        assert_modules_available(sorted(required))
    except ValueError:
        return False
    return True
