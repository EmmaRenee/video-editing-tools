"""Content planning and editorial reports built from ratings artifacts."""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
from typing import Any


SERIES_TEMPLATES: dict[str, dict[str, Any]] = {
    "what_were_looking_for": {
        "name": "What We're Looking For",
        "description": "Educational condition and inspection clips",
        "duration": "15-45s",
        "hashtags": ["#automotive", "#inspection", "#cartok", "#shoplife"],
        "hooks": [
            "Here is what we look for first.",
            "This is the detail most people miss.",
            "One quick way to spot the issue.",
        ],
        "labels": ["transcript_hit", "scene_change", "audio_spike"],
    },
    "team_tuesday": {
        "name": "Team Tuesday",
        "description": "Quote-led expert insight clips",
        "duration": "30-60s",
        "hashtags": ["#teamtuesday", "#shoplife", "#automotive", "#behindthescenes"],
        "hooks": [
            "The team take on this was simple.",
            "A quick shop-floor perspective.",
            "This is the kind of detail experience catches.",
        ],
        "labels": ["transcript_hit"],
    },
    "engine_build_montage": {
        "name": "Engine Build Montage",
        "description": "High-energy build progress and motion clips",
        "duration": "15-45s",
        "hashtags": ["#enginebuild", "#fabrication", "#automotive", "#reels"],
        "hooks": [
            "Build progress in motion.",
            "A few seconds from the engine bay.",
            "This is where the build starts to come together.",
        ],
        "labels": ["audio_spike", "scene_change", "scene_cluster"],
    },
    "shop_tour": {
        "name": "Shop Tour",
        "description": "Location, process, and behind-the-scenes clips",
        "duration": "20-60s",
        "hashtags": ["#shoptour", "#behindthescenes", "#automotive", "#garage"],
        "hooks": [
            "A quick look around the shop.",
            "This corner of the shop tells the story.",
            "Behind the scenes from today.",
        ],
        "labels": ["scene_change", "audio_present", "broll"],
    },
}

PILLARS: dict[str, dict[str, Any]] = {
    "expert_quotes": {
        "title": "Quote-Led Expert Reels",
        "keywords": ["transcript", "quote", "said", "interview", "explain", "team", "expert"],
        "labels": ["transcript_hit"],
    },
    "educational_teardown": {
        "title": "Educational Teardown / Condition Explainers",
        "keywords": ["teardown", "condition", "inspect", "looking for", "why", "because", "transmission", "engine"],
        "labels": ["transcript_hit"],
    },
    "build_diary": {
        "title": "Build Diary",
        "keywords": ["build", "install", "assembly", "progress", "fabrication", "engine"],
        "labels": ["scene_change", "audio_spike"],
    },
    "motion_bank": {
        "title": "Motion Bank / B-Roll",
        "keywords": ["b-roll", "broll", "motion", "detail", "shop"],
        "labels": ["scene_change", "scene_cluster", "audio_spike", "broll"],
    },
    "branded_assets": {
        "title": "Branded Templates / Lower Thirds",
        "keywords": ["logo", "lower third", "template", "intro", "outro", "brand"],
        "labels": [],
    },
    "motorsports_moments": {
        "title": "Motorsports Moments",
        "keywords": ["pass", "spin", "crash", "race", "start", "checkered", "lap", "driver"],
        "labels": ["motorsports_event", "audio_spike", "scene_change"],
    },
}


def list_series_templates() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in sorted(SERIES_TEMPLATES.items())]


def plan_content_series(
    ratings_json: str,
    output_dir: str,
    template: str = "team_tuesday",
    max_clips: int = 5,
) -> dict[str, str | int]:
    if template not in SERIES_TEMPLATES:
        raise KeyError(f"Unknown series template: {template}")
    data = _read_json(ratings_json)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    template_data = SERIES_TEMPLATES[template]
    candidates = _rank_candidates(data.get("candidates", []), preferred_labels=template_data.get("labels", []))
    selected = candidates[: max(0, int(max_clips))]
    clips = [_series_item(clip, template_data, index) for index, clip in enumerate(selected, 1)]
    plan = {
        "generated": datetime.now().isoformat(),
        "ratings": os.fspath(ratings_json),
        "template": template,
        "series": template_data,
        "clips": clips,
    }
    selection = {
        "generated": plan["generated"],
        "project": template_data["name"],
        "source": "mixed",
        "clips": [
            {
                "source": clip["source"],
                "start": clip["start"],
                "end": clip["end"],
                "label": clip["id"],
                "score": clip["score"],
                "reasons": clip["reasons"],
            }
            for clip in clips
        ],
    }
    plan_path = os.path.join(output_dir, "series_plan.json")
    captions_path = os.path.join(output_dir, "caption_suggestions.md")
    selections_path = os.path.join(output_dir, "series_selections.json")
    _write_json(plan_path, plan)
    _write_json(selections_path, selection)
    _write_text(captions_path, _series_caption_markdown(plan))
    return {
        "plan": plan_path,
        "captions": captions_path,
        "selections": selections_path,
        "count": len(clips),
    }


def generate_content_map(ratings_json: str, output_dir: str) -> dict[str, str]:
    data = _read_json(ratings_json)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    candidates = data.get("candidates", [])
    pillars = {
        key: {
            "title": config["title"],
            "candidates": _rank_candidates(_pillar_candidates(candidates, config))[:10],
        }
        for key, config in PILLARS.items()
    }
    payload = {
        "generated": datetime.now().isoformat(),
        "ratings": os.fspath(ratings_json),
        "summary": data.get("summary", {}),
        "pillars": pillars,
        "top_candidates": _rank_candidates(candidates)[:20],
    }
    json_path = os.path.join(output_dir, "content_map.json")
    markdown_path = os.path.join(output_dir, "ranked_content_map.md")
    _write_json(json_path, payload)
    _write_text(markdown_path, _content_map_markdown(payload))
    return {"json": json_path, "markdown": markdown_path}


def generate_quote_mining(ratings_json: str, output_dir: str) -> dict[str, str | int]:
    data = _read_json(ratings_json)
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    transcript_hits = _transcript_hits(data)
    transcript_candidates = _rank_candidates(
        [
            clip
            for clip in data.get("candidates", [])
            if "transcript_hit" in clip.get("labels", []) or _text_matches(clip, ["transcript", "quote", "says", "interview"])
        ]
    )
    path = os.path.join(output_dir, "quote_mining.md")
    _write_text(path, _quote_mining_markdown(data, transcript_candidates, transcript_hits))
    return {"markdown": path, "candidates": len(transcript_candidates), "transcript_hits": len(transcript_hits)}


def _series_item(clip: dict[str, Any], template: dict[str, Any], index: int) -> dict[str, Any]:
    hooks = template.get("hooks", [])
    hook = hooks[(index - 1) % len(hooks)] if hooks else "Clip candidate"
    reasons = list(clip.get("reasons", []))
    return {
        "id": clip.get("id") or clip.get("label") or f"clip_{index:04d}",
        "source": clip.get("source"),
        "start": clip.get("start"),
        "end": clip.get("end"),
        "duration": clip.get("duration"),
        "score": clip.get("score", 0),
        "labels": clip.get("labels", []),
        "reasons": reasons,
        "hook": hook,
        "caption": f"{hook} {' '.join(template.get('hashtags', []))}",
        "edit_note": _edit_note(clip),
    }


def _rank_candidates(candidates: list[dict[str, Any]], preferred_labels: list[str] | None = None) -> list[dict[str, Any]]:
    preferred = set(preferred_labels or [])

    def key(clip: dict[str, Any]) -> tuple[int, int, str]:
        labels = set(clip.get("labels", []))
        label_bonus = 20 if labels & preferred else 0
        return (int(clip.get("score", 0)) + label_bonus, len(labels & preferred), str(clip.get("id") or ""))

    return sorted((dict(item) for item in candidates), key=key, reverse=True)


def _pillar_candidates(candidates: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = config.get("keywords", [])
    labels = set(config.get("labels", []))
    matches = []
    for clip in candidates:
        clip_labels = set(clip.get("labels", []))
        if clip_labels & labels or _text_matches(clip, keywords):
            matches.append(clip)
    return matches


def _text_matches(clip: dict[str, Any], keywords: list[str]) -> bool:
    text = " ".join(
        [
            str(clip.get("id", "")),
            " ".join(clip.get("labels", [])),
            " ".join(clip.get("reasons", [])),
            json.dumps(clip.get("signals", {})),
        ]
    ).lower()
    return any(keyword.lower() in text for keyword in keywords)


def _transcript_hits(data: dict[str, Any]) -> list[dict[str, Any]]:
    hits = []
    for report in data.get("signals", []):
        asset = report.get("asset", {})
        for hit in report.get("transcript_hits", []):
            item = dict(hit)
            item["source"] = asset.get("filepath")
            item["source_name"] = asset.get("filename")
            hits.append(item)
    return hits


def _edit_note(clip: dict[str, Any]) -> str:
    labels = ", ".join(clip.get("labels", [])) or "rated candidate"
    reasons = "; ".join(clip.get("reasons", [])[:2])
    return f"{labels}. {reasons}".strip()


def _series_caption_markdown(plan: dict[str, Any]) -> str:
    lines = [f"# {plan['series']['name']} Caption Suggestions", ""]
    for clip in plan["clips"]:
        lines.extend(
            [
                f"## {clip['id']} ({clip['score']})",
                f"- Source: `{clip.get('source')}`",
                f"- Time: {clip.get('start')} to {clip.get('end')}",
                f"- Hook: {clip['hook']}",
                f"- Caption: {clip['caption']}",
                f"- Edit note: {clip['edit_note']}",
                "",
            ]
        )
    return "\n".join(lines)


def _content_map_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# Ranked Content Map",
        "",
        f"- Files: {summary.get('files', 'unknown')}",
        f"- Candidates: {summary.get('candidates', 'unknown')}",
        f"- Total duration: {summary.get('total_duration', 'unknown')}",
        "",
    ]
    for key, pillar in payload["pillars"].items():
        lines.extend([f"## {pillar['title']}", ""])
        if not pillar["candidates"]:
            lines.extend(["No strong candidates yet.", ""])
            continue
        for clip in pillar["candidates"][:10]:
            lines.append(
                f"- {clip.get('id', 'clip')} | score {clip.get('score', 0)} | "
                f"{clip.get('start')} to {clip.get('end')} | `{os.path.basename(clip.get('source') or '')}`"
            )
            if clip.get("reasons"):
                lines.append(f"  Edit note: {'; '.join(clip['reasons'][:2])}")
        lines.append("")
    return "\n".join(lines)


def _quote_mining_markdown(data: dict[str, Any], candidates: list[dict[str, Any]], hits: list[dict[str, Any]]) -> str:
    lines = ["# Interview Quote Mining", ""]
    if hits:
        lines.extend(["## Transcript Hit Queue", ""])
        for hit in hits[:50]:
            text = re.sub(r"\s+", " ", str(hit.get("text", ""))).strip()
            lines.append(
                f"- `{os.path.basename(hit.get('source') or '')}` {hit.get('start_tc', hit.get('start'))} "
                f"to {hit.get('end_tc', hit.get('end'))}: {text}"
            )
        lines.append("")
    lines.extend(["## Candidate Soundbites", ""])
    if not candidates:
        lines.append("No transcript-labeled candidates found. Run rating with transcript mode enabled for stronger quote mining.")
    for clip in candidates[:25]:
        lines.append(
            f"- {clip.get('id', 'clip')} | score {clip.get('score', 0)} | "
            f"{clip.get('start')} to {clip.get('end')} | `{os.path.basename(clip.get('source') or '')}`"
        )
        if clip.get("reasons"):
            lines.append(f"  Pull prompt: {'; '.join(clip['reasons'][:2])}")
    return "\n".join(lines) + "\n"


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
