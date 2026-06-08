"""Terminal review helpers for review_assets.json."""

from __future__ import annotations

from datetime import datetime
import json
import os
import sys
from typing import Any

from .review import _default_decision


def load_review_session(manifest_json: str, decisions_json: str | None = None) -> dict[str, Any]:
    manifest = _read_json(manifest_json)
    decisions = _decision_map(_read_json(decisions_json)) if decisions_json and os.path.exists(decisions_json) else {}
    clips = []
    for index, clip in enumerate(manifest.get("clips", []), 1):
        clip_id = clip.get("id") or f"clip_{index:04d}"
        decision = decisions.get(clip_id, {})
        row = dict(clip)
        row["decision"] = decision.get("decision") or _default_decision(clip.get("action", ""))
        row["note"] = decision.get("note", "")
        row["order"] = int(decision.get("order", index) or index)
        clips.append(row)
    return {"manifest": manifest, "clips": clips}


def filter_review_clips(
    clips: list[dict[str, Any]],
    query: str = "",
    action: str = "",
    label: str = "",
    source: str = "",
) -> list[dict[str, Any]]:
    query = query.lower().strip()
    action = action.strip()
    label = label.strip()
    source = source.lower().strip()
    rows = []
    for clip in clips:
        text = " ".join(
            [
                str(clip.get("id", "")),
                str(clip.get("source_name", "")),
                " ".join(clip.get("labels", [])),
                " ".join(clip.get("reasons", [])),
            ]
        ).lower()
        if query and query not in text:
            continue
        if action and clip.get("action") != action:
            continue
        if label and label not in clip.get("labels", []):
            continue
        if source and source not in str(clip.get("source_name", "")).lower():
            continue
        rows.append(clip)
    return sorted(rows, key=lambda item: (int(item.get("order", 999999)), -int(item.get("score", 0))))


def update_review_decision(
    clips: list[dict[str, Any]],
    clip_id: str,
    decision: str | None = None,
    note: str | None = None,
    order: int | None = None,
) -> dict[str, Any]:
    for clip in clips:
        if clip.get("id") != clip_id:
            continue
        if decision is not None:
            clip["decision"] = decision
        if note is not None:
            clip["note"] = note
        if order is not None:
            clip["order"] = int(order)
        return clip
    raise KeyError(f"unknown clip id: {clip_id}")


def write_review_decisions(clips: list[dict[str, Any]], ratings: str, output: str) -> str:
    payload = {
        "generated": datetime.now().isoformat(),
        "ratings": ratings,
        "decisions": [
            {
                "id": clip.get("id"),
                "decision": clip.get("decision", "reject"),
                "order": int(clip.get("order", index)),
                "note": clip.get("note", ""),
                "score": clip.get("score", 0),
                "current_action": clip.get("action", ""),
                "source": clip.get("source"),
                "start": clip.get("start"),
                "end": clip.get("end"),
                "labels": clip.get("labels", []),
                "reasons": clip.get("reasons", []),
                "signals": clip.get("signals", {}),
                "calibration": clip.get("calibration", {}),
            }
            for index, clip in enumerate(sorted(clips, key=lambda item: int(item.get("order", 999999))), 1)
        ],
    }
    _write_json(output, payload)
    return os.fspath(output)


def run_review_tui(manifest_json: str, decisions_json: str) -> dict[str, Any]:
    session = load_review_session(manifest_json, decisions_json)
    clips = session["clips"]
    if sys.stdin.isatty():
        _interactive_loop(clips)
    output = write_review_decisions(clips, session["manifest"].get("ratings", ""), decisions_json)
    return {"decisions": output, "clips": len(clips)}


def _interactive_loop(clips: list[dict[str, Any]]) -> None:
    query = ""
    while True:
        rows = filter_review_clips(clips, query=query)[:20]
        print("")
        for clip in rows:
            labels = ", ".join(clip.get("labels", [])[:4])
            print(
                f"{clip.get('order'):>3} {clip.get('id')} "
                f"{clip.get('score')} {clip.get('decision')} {clip.get('source_name')} {labels}"
            )
        command = input("review> ").strip()
        if command in {"q", "quit", "save", "exit"}:
            return
        if command.startswith("filter "):
            query = command.split(" ", 1)[1].strip()
            continue
        parts = command.split(" ", 3)
        if len(parts) >= 3 and parts[0] in {"approve", "review", "reject", "cut", "broll", "promote"}:
            note = parts[3] if len(parts) == 4 else None
            update_review_decision(clips, parts[1], decision=parts[0], note=note)
            continue
        if len(parts) >= 3 and parts[0] == "order":
            update_review_decision(clips, parts[1], order=int(parts[2]))
            continue
        if len(parts) >= 3 and parts[0] == "note":
            update_review_decision(clips, parts[1], note=command.split(" ", 2)[2])
            continue
        print("Commands: filter TEXT, approve ID [note], review ID, reject ID, order ID N, note ID TEXT, save")


def _decision_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decisions = data.get("decisions", data)
    if isinstance(decisions, dict):
        return {
            str(key): {"id": str(key), **(value if isinstance(value, dict) else {"decision": value})}
            for key, value in decisions.items()
        }
    return {
        str(item.get("id")): item
        for item in decisions
        if isinstance(item, dict) and item.get("id")
    }


def _read_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")
