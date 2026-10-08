"""Shared, text-free identity for optional model and heuristic providers."""

from __future__ import annotations

import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import re
from typing import Any

PROVENANCE_SCHEMA = "videoedit.provenance.v1"
SUPPORTED_SCHEMAS = {
    "videoedit.signal.v1", "videoedit.ai_frame_scores.v1", "videoedit.ai_clip_judgments.v1",
    "videoedit.ai_missed_moments.v1", "videoedit.missed_review.v1",
    "videoedit.learned_scorer.v1", "videoedit.review_dataset.v1",
    "videoedit.visual_objects.v1", "videoedit.ocr_signage.v1",
    "videoedit.face_person_presence.v1", "videoedit.motorsports_events.v1",
    "videoedit.topic_clusters.v1",
}
SAMPLING_FIELDS = {
    "kind", "interval_seconds", "max_frames_per_file", "max_clips", "min_score",
    "confidence", "max_detections", "segment_merge_gap", "records",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def library_version(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _name(value: Any) -> str | None:
    if not isinstance(value, str) or value.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:[/\\]", value):
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_.+@:-]+(?:/[A-Za-z0-9_.+@-]+)?", value) else None


def build_provenance(
    provider: str, artifact_kind: str, *, model_name: str | None = None,
    repository: str | None = None, revision: str | None = None,
    checkpoint: str | None = None, model_checksum: str | None = None,
    pretrained: str | None = None, library: str | None = None,
    library_version: str | None = None, device: str | None = None,
    precision: str | None = None, profile: dict[str, Any] | None = None,
    sampling: dict[str, Any] | None = None, random_seed: int | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checksum = model_checksum if isinstance(model_checksum, str) and re.fullmatch(r"[0-9a-f]{64}", model_checksum) else None
    if checkpoint and Path(checkpoint).is_file():
        checksum = file_sha256(checkpoint)
    distribution_version = library_version
    policy = {key: value for key, value in (sampling or {}).items()
              if key in SAMPLING_FIELDS and ((key == "kind" and _name(value)) or
                 (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0))}
    prompt_profile = None
    if profile is not None:
        prompt_profile = {"id": _name(profile.get("id")), "sha256": canonical_hash(profile),
                          "version": canonical_hash(profile), "prompt_count": len(profile.get("prompts", []))}
    data = {
        "schema_version": PROVENANCE_SCHEMA, "artifact_kind": _name(artifact_kind),
        "provider": {"name": _name(provider), "library": _name(library), "version": _name(distribution_version)},
        "model": {"name": _name(model_name), "repository": _name(repository), "revision": _name(revision),
                  "sha256": checksum, "pretrained": _name(pretrained)},
        "device": _name(device), "precision": _name(precision),
        "prompt_profile": prompt_profile, "sampling": policy,
        "random_seed": random_seed if isinstance(random_seed, int) and not isinstance(random_seed, bool) else None,
        "config_sha256": canonical_hash(config or {}),
    }
    data["identity_sha256"] = canonical_hash(data)
    return data


def validate_artifact(data: dict[str, Any]) -> dict[str, list[str]]:
    errors, warnings = [], []
    version = data.get("schema_version")
    if version is None:
        warnings.append("legacy_artifact_schema_missing")
    elif not isinstance(version, str) or version not in SUPPORTED_SCHEMAS:
        errors.append("unsupported artifact schema; upgrade videoedit or re-generate the artifact with a supported version")
    provenance = data.get("provenance")
    if provenance is None:
        warnings.append("provenance_missing")
        return {"errors": errors, "warnings": warnings}
    if not isinstance(provenance, dict) or provenance.get("schema_version") != PROVENANCE_SCHEMA:
        errors.append("unsupported provenance schema; upgrade videoedit or re-generate the artifact")
        return {"errors": errors, "warnings": warnings}
    provider, model = provenance.get("provider"), provenance.get("model")
    if not isinstance(provider, dict) or not isinstance(model, dict):
        errors.append("provenance provider and model must be objects")
        return {"errors": errors, "warnings": warnings}
    allowed = {"schema_version", "artifact_kind", "provider", "model", "device", "precision", "prompt_profile",
               "sampling", "random_seed", "config_sha256", "identity_sha256"}
    if set(provenance) - allowed or set(provider) - {"name", "library", "version"} or set(model) - {"name", "repository", "revision", "sha256", "pretrained"}:
        errors.append("unknown provenance fields; re-generate the artifact using the shared contract")
    seed = provenance.get("random_seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        errors.append("invalid provenance random seed; re-generate the artifact")
    for key in ("device", "precision", "artifact_kind"):
        if provenance.get(key) is not None and _name(provenance[key]) is None:
            errors.append(f"invalid provenance {key}; re-generate the artifact")
    sampling = provenance.get("sampling")
    if not isinstance(sampling, dict) or any(key not in SAMPLING_FIELDS or
                                            (_name(value) is None if key == "kind" else
                                             not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0)
                                            for key, value in sampling.items()):
        errors.append("invalid provenance sampling policy; re-generate the artifact")
    for group, keys in [(provider, ("name", "library", "version")), (model, ("name", "repository", "revision", "pretrained"))]:
        if any(value is not None and _name(value) is None for key in keys for value in [group.get(key)]):
            errors.append("provenance contains invalid identity fields; re-generate the artifact")
    if not provider.get("version"):
        warnings.append("provider_version_unknown")
    if model.get("name") and not (model.get("revision") or model.get("sha256")):
        warnings.append("model_identity_unverified")
    for key in ("device", "precision", "random_seed"):
        if provenance.get(key) is None:
            warnings.append(f"{key}_unknown")
    for key in ("config_sha256", "identity_sha256"):
        if not isinstance(provenance.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", provenance[key]):
            errors.append(f"invalid provenance {key}; re-generate the artifact")
    profile = provenance.get("prompt_profile")
    if profile is not None and (not isinstance(profile, dict) or
                               any(not isinstance(profile.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", profile[key]) for key in ("sha256", "version"))):
        errors.append("invalid provenance prompt identity; re-generate the artifact")
    elif isinstance(profile, dict) and (set(profile) - {"id", "sha256", "version", "prompt_count"} or
                                      (profile.get("id") is not None and _name(profile["id"]) is None) or
                                      not isinstance(profile.get("prompt_count"), int) or isinstance(profile["prompt_count"], bool) or profile["prompt_count"] < 0):
        errors.append("invalid provenance prompt profile; re-generate the artifact")
    checksum = model.get("sha256")
    if checksum is not None and (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)):
        errors.append("invalid provenance model checksum; re-generate the artifact")
    try:
        identity = canonical_hash({key: value for key, value in provenance.items() if key != "identity_sha256"})
        if identity != provenance.get("identity_sha256"):
            errors.append("provenance identity does not match its fields; re-generate the artifact")
    except (ValueError, TypeError):
        errors.append("invalid provenance identity values; re-generate the artifact")
    return {"errors": errors, "warnings": warnings}


def ensure_compatible(data: dict[str, Any]) -> dict[str, list[str]]:
    result = validate_artifact(data)
    if result["errors"]:
        raise ValueError("; ".join(result["errors"]))
    return result


def public_provenance(data: dict[str, Any]) -> dict[str, Any] | None:
    """Project known identity fields only; never copy arbitrary provider metadata."""
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return None
    ensure_compatible(data)
    profile = provenance.get("prompt_profile")
    return build_provenance(
        provenance["provider"].get("name") or "unknown", provenance.get("artifact_kind") or "unknown",
        model_name=provenance["model"].get("name"), repository=provenance["model"].get("repository"),
        revision=provenance["model"].get("revision"), model_checksum=provenance["model"].get("sha256"),
        pretrained=provenance["model"].get("pretrained"), library=provenance["provider"].get("library"),
        library_version=provenance["provider"].get("version"), device=provenance.get("device"),
        precision=provenance.get("precision"), sampling=provenance.get("sampling"),
        random_seed=provenance.get("random_seed"),
    ) | {"prompt_profile": {**{key: profile.get(key) for key in ("sha256", "version", "prompt_count")}, "id": _name(profile.get("id"))} if isinstance(profile, dict) else None,
         "config_sha256": provenance["config_sha256"], "identity_sha256": provenance["identity_sha256"]}
