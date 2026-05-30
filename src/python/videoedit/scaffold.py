"""Project scaffolding helpers."""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
from typing import Any

from .modules import CONFIG_DIR, CONFIG_FILE


PROJECT_TYPES = {
    "reel": {"description": "Instagram/TikTok vertical reel", "aspect": "9:16"},
    "youtube": {"description": "YouTube horizontal video", "aspect": "16:9"},
    "documentary": {"description": "Long-form documentary or interview edit", "aspect": "16:9"},
    "interview": {"description": "Interview or talking-head package", "aspect": "16:9"},
    "broll": {"description": "B-roll footage package", "aspect": "original"},
}

FOLDERS = {
    "raw": "Raw footage",
    "audio": "Music, voiceover, and sound effects",
    "exports": "Final exports",
    "assets": "Graphics, lower thirds, overlays, captions",
    "scripts": "Scripts, transcripts, and paper edits",
    "drafts": "Work-in-progress renders",
    "analysis": "videoedit inventory, ratings, and reports",
    "review": "Thumbnails, proxies, and approval files",
}


def scaffold_project(
    name: str,
    output_dir: str,
    project_type: str = "reel",
    source: str | None = None,
    team_config: str | None = None,
) -> dict[str, Any]:
    if project_type not in PROJECT_TYPES:
        raise KeyError(f"Unknown project type: {project_type}")
    project_root = os.path.join(os.fspath(output_dir), _safe_slug(name))
    os.makedirs(project_root, exist_ok=True)
    folders = {}
    for folder, description in FOLDERS.items():
        path = os.path.join(project_root, folder)
        os.makedirs(path, exist_ok=True)
        folders[folder] = {"path": path, "description": description}
    workflow = {
        "title": name,
        "project_type": project_type,
        "aspect": PROJECT_TYPES[project_type]["aspect"],
        "created": datetime.now().isoformat(),
        "source_footage": source or "raw/",
        "output": "exports/",
        "analysis": "analysis/",
    }
    if team_config:
        workflow["team_config"] = os.path.abspath(team_config)
    config = {
        "generated": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
        "enabled_modules": ["content.series", "content.reports", "delivery.captions", "project.scaffold"],
        "disabled_modules": [],
    }
    files = {
        "workflow": os.path.join(project_root, "workflow_config.json"),
        "readme": os.path.join(project_root, "README.md"),
        "module_config": os.path.join(project_root, CONFIG_DIR, CONFIG_FILE),
    }
    os.makedirs(os.path.dirname(files["module_config"]), exist_ok=True)
    _write_json(files["workflow"], workflow)
    _write_json(files["module_config"], config)
    _write_text(files["readme"], _readme(name, project_type, source))
    return {"project": project_root, "folders": folders, "files": files}


def _readme(name: str, project_type: str, source: str | None) -> str:
    preset = "reel" if project_type == "reel" else "roughcut"
    return f"""# {name}

Created: {datetime.now().strftime('%Y-%m-%d')}
Type: {project_type}
Source: {source or 'raw/'}

## Structure

- `raw/` - raw footage
- `audio/` - music, voiceover, and sound effects
- `assets/` - graphics, lower thirds, overlays, captions
- `scripts/` - scripts, transcripts, and paper edits
- `analysis/` - inventory, ratings, candidates, and reports
- `review/` - thumbnails, proxies, and approval files
- `drafts/` - work-in-progress renders
- `exports/` - final exports

## Starter Workflow

```bash
videoedit doctor
videoedit init {preset} --output pipeline.yaml
videoedit run pipeline.yaml --input raw/ --output analysis/
videoedit content-map analysis/ratings.json --output analysis/reports/
videoedit series analysis/ratings.json --template team_tuesday --output analysis/series/
```
"""


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "video_project"


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
