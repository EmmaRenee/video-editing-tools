"""Optional cloud adapter metadata and local job specs."""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any


CLOUD_JOB_SCHEMA_VERSION = "videoedit.cloud_job.v1"


CLOUD_ADAPTERS: dict[str, dict[str, Any]] = {
    "elevenlabs": {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "kind": "voice",
        "description": "Voiceover and narration handoff for optional ElevenLabs execution.",
        "required_env": ["ELEVENLABS_API_KEY"],
        "supported_jobs": ["voiceover", "narration"],
        "outputs": ["audio"],
        "notes": "Planning writes a job spec only; execution belongs in an adapter package or external runner.",
    },
    "heygen": {
        "id": "heygen",
        "name": "HeyGen",
        "kind": "avatar_video",
        "description": "Avatar-video handoff for optional HeyGen execution.",
        "required_env": ["HEYGEN_API_KEY"],
        "supported_jobs": ["avatar_video", "presenter_video"],
        "outputs": ["video"],
        "notes": "Planning writes a job spec only; execution belongs in an adapter package or external runner.",
    },
    "descript": {
        "id": "descript",
        "name": "Descript",
        "kind": "text_editing",
        "description": "Transcript and text-editing handoff for Descript-style review workflows.",
        "required_env": [],
        "required_connectors": ["descript_desktop_or_mcp"],
        "supported_jobs": ["transcript_edit", "review_handoff"],
        "outputs": ["project_handoff"],
        "notes": "Use a maintained connector or desktop workflow to execute the planned handoff.",
    },
}


def list_cloud_adapters() -> list[dict[str, Any]]:
    """Return built-in cloud adapter metadata sorted by adapter id."""

    return [dict(CLOUD_ADAPTERS[key]) for key in sorted(CLOUD_ADAPTERS)]


def get_cloud_adapter(adapter_id: str) -> dict[str, Any]:
    adapter_id = str(adapter_id).strip().lower()
    if adapter_id not in CLOUD_ADAPTERS:
        raise KeyError(f"unknown cloud adapter: {adapter_id}")
    return dict(CLOUD_ADAPTERS[adapter_id])


def cloud_diagnostics(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Report adapter readiness without calling external APIs."""

    env = env if env is not None else os.environ
    adapters = []
    for adapter in list_cloud_adapters():
        checks = []
        for name in adapter.get("required_env", []):
            checks.append(
                {
                    "name": name,
                    "type": "env",
                    "available": bool(env.get(name)),
                    "message": "configured" if env.get(name) else f"set {name} to enable execution",
                }
            )
        for name in adapter.get("required_connectors", []):
            checks.append(
                {
                    "name": name,
                    "type": "connector",
                    "available": False,
                    "message": "verify the maintained connector or desktop workflow before execution",
                }
            )
        ready = bool(checks) and all(check["available"] for check in checks)
        adapters.append({"id": adapter["id"], "name": adapter["name"], "ready": ready, "checks": checks})
    return {"generated": datetime.now().isoformat(), "adapters": adapters}


def plan_cloud_job(
    adapter_id: str,
    output: str,
    job_type: str,
    input_path: str | None = None,
    params: dict[str, Any] | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Write a portable cloud job spec and return a summary.

    This function deliberately does not call provider APIs. It creates a reviewable
    handoff artifact that a maintained adapter runner can execute later.
    """

    adapter = get_cloud_adapter(adapter_id)
    if job_type not in adapter.get("supported_jobs", []):
        supported = ", ".join(adapter.get("supported_jobs", []))
        raise ValueError(f"adapter {adapter_id} does not support job type {job_type}; supported: {supported}")
    output = os.fspath(output)
    payload = {
        "schema_version": CLOUD_JOB_SCHEMA_VERSION,
        "artifact_kind": "cloud_job",
        "generated": datetime.now().isoformat(),
        "status": "planned",
        "project": project,
        "adapter": adapter,
        "job": {
            "type": job_type,
            "input": os.fspath(input_path) if input_path else None,
            "params": dict(params or {}),
        },
        "execution": {
            "mode": "manual_or_external_adapter",
            "network_called": False,
            "credentials_stored": False,
        },
    }
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    return {"output": output, "adapter": adapter["id"], "job_type": job_type, "status": "planned"}

