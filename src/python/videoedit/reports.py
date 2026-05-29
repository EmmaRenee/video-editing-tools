"""Report writers for rating outputs."""

from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict

from .models import CandidateClip, RatingReport, SelectionSet


def write_rating_json(report: RatingReport, output: str) -> None:
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(report.to_dict(), indent=2))


def write_candidate_csv(candidates: list[CandidateClip], output: str) -> None:
    with open(os.fspath(output), "w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "id",
            "source",
            "start",
            "end",
            "duration",
            "score",
            "action",
            "labels",
            "reasons",
        ]
        handle.write(_csv_row(fieldnames) + "\n")
        for clip in candidates:
            data = clip.to_dict()
            handle.write(
                _csv_row(
                    [
                        clip.id,
                        clip.source,
                        data["start"],
                        data["end"],
                        round(clip.duration, 2),
                        clip.score,
                        clip.action,
                        ", ".join(clip.labels),
                        " | ".join(clip.reasons),
                    ]
                )
                + "\n"
            )


def write_review_markdown(report: RatingReport, output: str) -> None:
    lines = [
        "# Footage Review",
        "",
        f"**Generated:** {report.generated}",
        f"**Files:** {report.summary['files']}",
        f"**Candidates:** {report.summary['candidates']}",
        "",
        "## Top Candidates",
        "",
        "| Rank | Clip | Score | Action | Source | Time | Why |",
        "|------|------|-------|--------|--------|------|-----|",
    ]
    for index, clip in enumerate(report.candidates[:50], 1):
        data = clip.to_dict()
        source = os.path.basename(clip.source)
        lines.append(
            f"| {index} | {clip.id} | {clip.score} | {clip.action} | {source} | "
            f"{data['start']} - {data['end']} | {'; '.join(clip.reasons)} |"
        )

    lines.extend(["", "## File Signal Summary", ""])
    for signal in report.signals:
        asset = signal.asset
        lines.extend(
            [
                f"### {asset.filename}",
                "",
                f"- Status: {asset.status}",
                f"- Duration: {asset.to_dict()['duration_formatted']}",
                f"- Resolution: {asset.resolution}",
                f"- Total score: {signal.scores.get('total_score', 0)}",
                f"- Reasons: {'; '.join(signal.reasons)}",
            ]
        )
        if signal.warnings:
            lines.append(f"- Warnings: {'; '.join(signal.warnings)}")
        lines.append("")
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def write_review_html(report: RatingReport, output: str) -> None:
    rows = []
    for index, clip in enumerate(report.candidates[:200], 1):
        data = clip.to_dict()
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(clip.id)}</td>"
            f"<td>{clip.score}</td>"
            f"<td>{html.escape(clip.action)}</td>"
            f"<td>{html.escape(os.path.basename(clip.source))}</td>"
            f"<td>{data['start']} - {data['end']}</td>"
            f"<td>{html.escape(', '.join(clip.labels))}</td>"
            f"<td>{html.escape('; '.join(clip.reasons))}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Footage Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; position: sticky; top: 0; }}
    .summary {{ display: flex; gap: 16px; margin: 16px 0 24px; }}
    .summary div {{ border: 1px solid #d9e2ec; padding: 10px 12px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Footage Review</h1>
  <div class="summary">
    <div><strong>Files</strong><br>{report.summary['files']}</div>
    <div><strong>Candidates</strong><br>{report.summary['candidates']}</div>
    <div><strong>Select</strong><br>{report.summary['select']}</div>
    <div><strong>Review</strong><br>{report.summary['review']}</div>
  </div>
  <table>
    <thead>
      <tr><th>Rank</th><th>Clip</th><th>Score</th><th>Action</th><th>Source</th><th>Time</th><th>Labels</th><th>Why</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    with open(os.fspath(output), "w", encoding="utf-8") as handle:
        handle.write(document)


def write_selection_sets(candidates: list[CandidateClip], output_dir: str) -> list[str]:
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    grouped: dict[str, list[CandidateClip]] = defaultdict(list)
    for clip in candidates:
        if clip.action in {"select", "review"}:
            grouped[clip.source].append(clip)

    paths: list[str] = []
    for source, clips in grouped.items():
        safe_name = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        path = os.path.join(output_dir, f"{safe_name}_selections.json")
        selection = SelectionSet(source=source, clips=sorted(clips, key=lambda item: item.start))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(selection.to_dict(), indent=2))
        paths.append(path)
    return paths


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "source"


def _csv_row(values: list[object]) -> str:
    cells = []
    for value in values:
        text = "" if value is None else str(value)
        if any(char in text for char in [",", '"', "\n", "\r"]):
            text = '"' + text.replace('"', '""') + '"'
        cells.append(text)
    return ",".join(cells)
