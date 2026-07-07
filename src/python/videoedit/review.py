"""Review and rough-cut helpers."""

from __future__ import annotations

from datetime import datetime
import html
import json
import os
import re

from .ai import load_clip_judgment_explanations
from .edl import export_selection_file
from .ffmpeg import run_command_check
from .roughcut import clips_from_plan
from .selections import load_selection
from .timecode import seconds_to_hhmmss, timecode_to_seconds


def assemble(selection_json: str, output: str, plan_json: str | None = None) -> str:
    selection_json = os.fspath(selection_json)
    output = os.fspath(output)
    clips = clips_from_plan(plan_json) if plan_json else load_selection(selection_json).clips
    output_dir = os.path.dirname(output) or "."
    output_stem = os.path.splitext(os.path.basename(output))[0]
    os.makedirs(output_dir, exist_ok=True)
    clips_dir = os.path.join(output_dir, f"{output_stem}_clips")
    os.makedirs(clips_dir, exist_ok=True)
    concat = os.path.join(output_dir, f"{output_stem}_concat.txt")
    lines: list[str] = []
    for index, clip in enumerate(clips, 1):
        source = clip["source"]
        label = _safe_slug(clip.get("label") or clip.get("id") or f"clip_{index:03d}")
        clip_path = os.path.join(clips_dir, f"{index:03d}_{label}.mp4")
        _extract_roughcut_clip(source, clip, clip_path)
        lines.append(f"file '{os.path.abspath(clip_path)}'")
    if not lines:
        raise ValueError("selection has no clips to assemble")
    with open(concat, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    run_command_check(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", output, "-y"])
    return output


def _extract_roughcut_clip(source: str, clip: dict, clip_path: str) -> None:
    if clip.get("render_mode") != "render":
        run_command_check(
            ["ffmpeg", "-i", source, "-ss", clip["start"], "-to", clip["end"], "-c", "copy", clip_path, "-y"],
        )
        return
    args = ["ffmpeg", "-i", source, "-ss", clip["start"], "-to", clip["end"]]
    if clip.get("video_filter"):
        args.extend(["-vf", clip["video_filter"]])
    args.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", clip_path, "-y"])
    run_command_check(args)


def create_approval_file(
    ratings_json: str,
    output: str,
    actions: list[str] | None = None,
    min_score: int | None = None,
    ids: list[str] | None = None,
    decisions_json: str | None = None,
) -> str:
    ratings_json = os.fspath(ratings_json)
    output = os.fspath(output)
    data = _read_json(ratings_json)
    candidates = data.get("candidates", [])
    selected: list[dict] = []
    id_set = {item.strip() for item in ids or [] if item.strip()}
    action_set = {item.strip() for item in actions or ["select", "review"] if item.strip()}
    score_floor = int(min_score) if min_score is not None else None
    decisions = _load_decisions(decisions_json)

    for clip in candidates:
        clip_id = clip.get("id") or clip.get("label")
        keep = _candidate_selected(clip, id_set, action_set, score_floor, decisions)
        if not keep:
            continue
        selected.append(_approved_clip(clip, decisions.get(clip_id)))

    if decisions:
        selected.sort(key=lambda clip: clip.get("review_order", 999999))

    sources = sorted({clip["source"] for clip in selected if clip.get("source")})
    payload = {
        "generated": datetime.now().isoformat(),
        "source": sources[0] if len(sources) == 1 else "mixed",
        "clips": selected,
        "review": {
            "ratings": ratings_json,
            "actions": sorted(action_set),
            "min_score": score_floor,
            "ids": sorted(id_set),
            "decisions": os.fspath(decisions_json) if decisions_json else None,
        },
    }
    _write_json(output, payload)
    return output


def generate_review_assets(
    ratings_json: str,
    output_dir: str,
    max_items: int = 100,
    proxies: bool = False,
    thumbnail_width: int = 360,
    calibration_json: str | None = None,
    ai_clip_judgments_json: str | None = None,
) -> dict:
    ratings_json = os.fspath(ratings_json)
    output_dir = os.fspath(output_dir)
    data = _read_json(ratings_json)
    signal_context = _signal_context(data)
    source_context = _source_context(data)
    calibration_context = _calibration_context(calibration_json)
    ai_judgments = load_clip_judgment_explanations(ai_clip_judgments_json)
    os.makedirs(output_dir, exist_ok=True)
    thumbs_dir = os.path.join(output_dir, "thumbnails")
    proxies_dir = os.path.join(output_dir, "proxies")
    os.makedirs(thumbs_dir, exist_ok=True)
    if proxies:
        os.makedirs(proxies_dir, exist_ok=True)

    warnings: list[str] = []
    rows: list[dict] = []
    for clip in data.get("candidates", [])[: max(0, max_items)]:
        row = _review_row(clip, signal_context, source_context, calibration_context["by_candidate"], ai_judgments)
        source = row.get("source")
        if not source or not os.path.exists(source):
            warnings.append(f"missing source for {row['id']}: {source}")
            rows.append(row)
            continue

        midpoint = row["start_seconds"] + max(0.0, row["duration"] / 2.0)
        thumb_name = f"{_safe_slug(row['id'])}.jpg"
        thumb_path = os.path.join(thumbs_dir, thumb_name)
        try:
            run_command_check(
                [
                    "ffmpeg",
                    "-ss",
                    f"{midpoint:.3f}",
                    "-i",
                    source,
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={int(thumbnail_width)}:-1",
                    "-q:v",
                    "3",
                    thumb_path,
                    "-y",
                ]
            )
            row["thumbnail"] = os.path.join("thumbnails", thumb_name)
        except Exception as exc:
            warnings.append(f"thumbnail failed for {row['id']}: {exc}")

        if proxies:
            proxy_name = f"{_safe_slug(row['id'])}.mp4"
            proxy_path = os.path.join(proxies_dir, proxy_name)
            try:
                run_command_check(
                    [
                        "ffmpeg",
                        "-ss",
                        f"{row['start_seconds']:.3f}",
                        "-i",
                        source,
                        "-t",
                        f"{row['duration']:.3f}",
                        "-vf",
                        "scale=640:-2",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "28",
                        "-c:a",
                        "aac",
                        proxy_path,
                        "-y",
                    ]
                )
                row["proxy"] = os.path.join("proxies", proxy_name)
            except Exception as exc:
                warnings.append(f"proxy failed for {row['id']}: {exc}")
        rows.append(row)

    manifest = {
        "generated": datetime.now().isoformat(),
        "ratings": ratings_json,
        "calibration": {
            "report": os.fspath(calibration_json) if calibration_json else None,
            "summary": calibration_context.get("summary", {}),
            "missed_moments": calibration_context.get("missed_moments", []),
        },
        "ai_clip_judgments": os.fspath(ai_clip_judgments_json) if ai_clip_judgments_json else None,
        "count": len(rows),
        "clips": rows,
        "warnings": warnings,
    }
    manifest_path = os.path.join(output_dir, "review_assets.json")
    contact_sheet_path = os.path.join(output_dir, "contact_sheet.html")
    decisions_path = os.path.join(output_dir, "review_decisions.json")
    existing_decisions = _load_decisions(decisions_path) if os.path.exists(decisions_path) else {}
    decisions_payload = _decision_template(ratings_json, rows, existing_decisions)
    _write_json(manifest_path, manifest)
    _write_json(decisions_path, decisions_payload)
    _write_contact_sheet(contact_sheet_path, manifest, decisions_payload)
    return {
        "manifest": manifest_path,
        "contact_sheet": contact_sheet_path,
        "decisions": decisions_path,
        "clips": len(rows),
        "thumbnails": sum(1 for row in rows if row.get("thumbnail")),
        "proxies": sum(1 for row in rows if row.get("proxy")),
        "warnings": warnings,
    }


def export_review_handoff(selection_json: str, output_dir: str) -> list[str]:
    return export_selection_file(selection_json, output_dir)


def _approved_clip(clip: dict, decision: dict | None = None) -> dict:
    start_seconds = _clip_seconds(clip, "start", "start_seconds")
    end_seconds = _clip_seconds(clip, "end", "end_seconds")
    approved = {
        "source": clip.get("source"),
        "start": seconds_to_hhmmss(start_seconds),
        "end": seconds_to_hhmmss(end_seconds),
        "label": clip.get("id") or clip.get("label") or "clip",
        "score": clip.get("score", 0),
        "action": "approved",
        "original_action": clip.get("action"),
        "labels": list(clip.get("labels", [])),
        "reasons": list(clip.get("reasons", [])),
    }
    if decision:
        approved["review_decision"] = decision.get("decision")
        approved["review_order"] = _decision_order(decision)
        note = str(decision.get("note") or "").strip()
        if note:
            approved["review_note"] = note
    return approved


def _review_row(
    clip: dict,
    signal_context: dict[str, dict],
    source_context: dict[str, dict],
    calibration_by_candidate: dict[str, dict],
    ai_judgments: dict[str, list[dict]],
) -> dict:
    start_seconds = _clip_seconds(clip, "start", "start_seconds")
    end_seconds = _clip_seconds(clip, "end", "end_seconds")
    source = clip.get("source")
    signal = signal_context.get(source or "", {})
    source_meta = source_context.get(source or "", {})
    clip_id = clip.get("id") or clip.get("label") or "clip"
    row = {
        "id": clip_id,
        "source": source,
        "source_name": os.path.basename(source or ""),
        "source_metadata": source_meta,
        "start": seconds_to_hhmmss(start_seconds),
        "end": seconds_to_hhmmss(end_seconds),
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "duration": max(0.0, end_seconds - start_seconds),
        "score": clip.get("score", 0),
        "action": clip.get("action", ""),
        "labels": list(clip.get("labels", [])),
        "reasons": list(clip.get("reasons", [])),
        "signals": dict(clip.get("signals", {})),
        "file_scores": dict(signal.get("scores", {})),
        "object_hits": _overlapping_object_hits(signal.get("object_hits", []), start_seconds, end_seconds),
        "advanced_hits": _overlapping_advanced_hits(signal.get("advanced_hits", []), start_seconds, end_seconds),
        "calibration": calibration_by_candidate.get(clip_id, {"status": "unreviewed"}),
        "thumbnail": None,
        "proxy": None,
    }
    explanations = [dict(item) for item in clip.get("ai_explanations", []) if isinstance(item, dict)]
    explanations.extend(ai_judgments.get(clip_id, []))
    if explanations:
        row["ai_explanations"] = explanations
    return row


def _signal_context(data: dict) -> dict[str, dict]:
    rows = {}
    for signal in data.get("signals", []):
        asset = signal.get("asset", {})
        source = asset.get("filepath")
        if source:
            rows[os.fspath(source)] = signal
    return rows


def _source_context(data: dict) -> dict[str, dict]:
    rows = {}
    for asset in data.get("inventory", []):
        source = asset.get("filepath")
        if not source:
            continue
        rows[os.fspath(source)] = {
            "filename": asset.get("filename"),
            "duration": asset.get("duration"),
            "duration_formatted": asset.get("duration_formatted"),
            "resolution": asset.get("resolution"),
            "fps": asset.get("fps"),
            "codec": asset.get("codec"),
            "has_audio": asset.get("has_audio"),
            "size_mb": asset.get("size_mb"),
        }
    return rows


def _calibration_context(path: str | None) -> dict:
    if not path:
        return {"by_candidate": {}, "summary": {}, "missed_moments": []}
    try:
        data = _read_json(path)
    except OSError:
        return {"by_candidate": {}, "summary": {}, "missed_moments": []}
    by_candidate: dict[str, dict] = {}
    for match in data.get("matches", []):
        candidate = match.get("candidate", {})
        candidate_id = candidate.get("id")
        if candidate_id:
            by_candidate[candidate_id] = {
                "status": "matched",
                "annotation_id": match.get("annotation", {}).get("id"),
                "annotation_rating": match.get("annotation", {}).get("rating"),
                "overlap_seconds": match.get("overlap_seconds"),
                "overlap_ratio": match.get("overlap_ratio"),
            }
    for row in data.get("false_positives", []):
        candidate = row.get("candidate", {})
        candidate_id = candidate.get("id")
        if candidate_id:
            by_candidate[candidate_id] = {
                "status": "false_positive",
                "nearest_annotation": (row.get("nearest_annotation") or {}).get("id"),
                "nearest_rating": (row.get("nearest_annotation") or {}).get("rating"),
                "nearest_gap_seconds": row.get("nearest_gap_seconds"),
            }
    return {
        "by_candidate": by_candidate,
        "summary": data.get("metrics", {}),
        "missed_moments": data.get("missed_moments", []),
    }


def _overlapping_object_hits(hits: list[dict], start: float, end: float) -> list[dict]:
    rows = []
    for hit in hits:
        hit_start = _clip_seconds(hit, "start_tc", "start")
        hit_end = _clip_seconds(hit, "end_tc", "end")
        if _overlaps(start, end, hit_start, hit_end):
            rows.append(hit)
    return rows[:20]


def _overlapping_advanced_hits(hits: list[dict], start: float, end: float) -> list[dict]:
    rows = []
    for hit in hits:
        if hit.get("source_wide"):
            rows.append(hit)
            continue
        hit_start = float(hit.get("start", 0.0))
        hit_end = float(hit.get("end", hit_start))
        if _overlaps(start, end, hit_start, hit_end):
            rows.append(hit)
    return rows[:20]


def _overlaps(start: float, end: float, hit_start: float, hit_end: float) -> bool:
    return min(end, hit_end) > max(start, hit_start)


def _clip_seconds(clip: dict, formatted_key: str, seconds_key: str) -> float:
    if seconds_key in clip:
        return float(clip[seconds_key])
    return timecode_to_seconds(clip.get(formatted_key, 0))


def _decision_template(ratings_json: str, rows: list[dict], existing: dict[str, dict] | None = None) -> dict:
    decisions = []
    existing = existing or {}
    active_existing_orders = [
        _decision_order(existing[row["id"]])
        for row in rows
        if row.get("id") in existing and _decision_order(existing[row["id"]]) != 999999
    ]
    next_order = (max(active_existing_orders) + 1) if active_existing_orders else 1
    for index, row in enumerate(rows, 1):
        action = row.get("action", "")
        previous = existing.get(row["id"], {})
        if previous:
            order = _decision_order(previous)
        else:
            order = next_order if active_existing_orders else index
            next_order += 1
        decisions.append(
            _decision_row(
                row,
                decision=str(previous.get("decision") or _default_decision(action)),
                order=order,
                note=str(previous.get("note") or ""),
            )
        )
    return {
        "generated": datetime.now().isoformat(),
        "ratings": ratings_json,
        "decisions": decisions,
    }


def _decision_row(row: dict, decision: str, order: int, note: str) -> dict:
    return {
        "id": row["id"],
        "decision": decision,
        "order": order,
        "note": note,
        "score": row.get("score", 0),
        "current_action": row.get("action", ""),
        "source": row.get("source"),
        "start": row.get("start"),
        "end": row.get("end"),
        "labels": row.get("labels", []),
        "reasons": row.get("reasons", []),
        "signals": row.get("signals", {}),
        "calibration": row.get("calibration", {}),
    }


def _load_decisions(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    data = _read_json(path)
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


def _candidate_selected(
    clip: dict,
    id_set: set[str],
    action_set: set[str],
    score_floor: int | None,
    decisions: dict[str, dict],
) -> bool:
    clip_id = clip.get("id") or clip.get("label")
    if decisions:
        decision = str(decisions.get(clip_id, {}).get("decision", "")).strip().lower()
        if decision in {"approve", "approved", "promote", "select", "review", "broll", "b-roll", "b_roll", "yes", "y"}:
            return True
        if decision in {"reject", "rejected", "demote", "skip", "cut", "ignore", "no", "n"}:
            return False
    score = int(clip.get("score", 0))
    action = clip.get("action", "")
    keep = bool(id_set and clip_id in id_set)
    if not id_set:
        keep = action in action_set and (score_floor is None or score >= score_floor)
    return keep


def _decision_order(decision: dict) -> int:
    try:
        return int(decision.get("order", 999999))
    except (TypeError, ValueError):
        return 999999


def _write_contact_sheet(path: str, manifest: dict, decisions: dict | None = None) -> None:
    decision_by_id = {
        str(item.get("id")): item
        for item in (decisions or {}).get("decisions", [])
        if isinstance(item, dict) and item.get("id")
    }
    cards = []
    for index, clip in enumerate(manifest.get("clips", []), 1):
        labels_text = ", ".join(clip.get("labels", []))
        signal_items = _signal_summary_items(clip.get("signals", {}))
        calibration = clip.get("calibration", {})
        calibration_status = calibration.get("status", "unreviewed")
        object_items = _object_summary_items(clip.get("object_hits", []))
        advanced_items = _advanced_summary_items(clip.get("advanced_hits", []))
        ai_items = _ai_explanation_items(clip.get("ai_explanations", []))
        ai_reasons = (
            f'<p class="ai-reasons"><strong>AI reasons</strong>: {html.escape(ai_items)}</p>'
            if ai_items
            else ""
        )
        source_meta = clip.get("source_metadata", {})
        thumbnail = clip.get("thumbnail")
        image = (
            f'<img src="{html.escape(thumbnail)}" alt="{html.escape(clip["id"])}">'
            if thumbnail
            else '<div class="missing">No thumbnail</div>'
        )
        proxy = (
            f'<a class="proxy" href="{html.escape(clip["proxy"])}">Proxy</a>'
            if clip.get("proxy")
            else ""
        )
        decision_row = decision_by_id.get(clip["id"], {})
        decision = str(decision_row.get("decision") or _default_decision(clip.get("action", "")))
        order = _decision_order(decision_row) if decision_row else index
        note = str(decision_row.get("note") or "")
        cards.append(
            '<article class="clip"'
            f' data-id="{html.escape(clip["id"], quote=True)}"'
            f' data-score="{html.escape(str(clip.get("score", 0)), quote=True)}"'
            f' data-current-action="{html.escape(str(clip.get("action", "")), quote=True)}"'
            f' data-labels="{html.escape(labels_text, quote=True)}"'
            f' data-calibration="{html.escape(str(calibration_status), quote=True)}"'
            f' data-source="{html.escape(str(clip.get("source") or ""), quote=True)}"'
            f' data-source-name="{html.escape(str(clip.get("source_name") or ""), quote=True)}"'
            f' data-start="{html.escape(str(clip.get("start") or ""), quote=True)}"'
            f' data-end="{html.escape(str(clip.get("end") or ""), quote=True)}">'
            f"{image}"
            '<div class="clip-body">'
            f'<div class="clip-head"><h2>{html.escape(clip["id"])}</h2>'
            f'<span class="score">{html.escape(str(clip["score"]))}</span></div>'
            f'<p class="source">{html.escape(clip["source_name"])}<br>{clip["start"]} - {clip["end"]}</p>'
            f'<p class="meta-line">{html.escape(_source_meta_line(source_meta))}</p>'
            f'<p class="labels">{html.escape(labels_text)}</p>'
            f'<p class="reasons"><strong>Deterministic reasons</strong>: {html.escape("; ".join(clip.get("reasons", [])))}</p>'
            f"{ai_reasons}"
            f'<p class="signals">{html.escape(signal_items)}</p>'
            f'<p class="objects">{html.escape(object_items)}</p>'
            f'<p class="advanced">{html.escape(advanced_items)}</p>'
            f'<p class="calibration calibration-{html.escape(str(calibration_status))}">{html.escape(_calibration_line(calibration))}</p>'
            f"{proxy}"
            '<div class="review-controls">'
            '<label>Decision'
            f'<select class="decision">{_decision_options(decision)}</select>'
            '</label>'
            '<label>Order'
            f'<input class="order" type="number" min="1" value="{html.escape(str(order), quote=True)}">'
            '</label>'
            '<label>Note'
            f'<textarea class="note" rows="2">{html.escape(note)}</textarea>'
            '</label>'
            '</div>'
            '</div>'
            "</article>"
        )
    warning_items = "".join(
        f"<li>{html.escape(str(warning))}</li>" for warning in manifest.get("warnings", [])
    )
    warnings = f'<section class="warnings"><h2>Warnings</h2><ul>{warning_items}</ul></section>' if warning_items else ""
    calibration_summary = _calibration_summary_line(manifest.get("calibration", {}))
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Videoedit Contact Sheet</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #1f2933; background: #f7f9fb; }}
    header {{ position: sticky; top: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 20px; border-bottom: 1px solid #d9e2ec; background: rgba(255,255,255,0.96); }}
    h1 {{ font-size: 18px; margin: 0; }}
    .meta {{ font-size: 12px; color: #52606d; margin: 3px 0 0; }}
    .toolbar {{ display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }}
    .bulk-controls {{ display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; padding-left: 10px; border-left: 1px solid #d9e2ec; }}
    .bulk-controls label {{ min-width: 132px; }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 20px; border-bottom: 1px solid #d9e2ec; background: #fff; }}
    .counts {{ font-size: 12px; color: #334e68; }}
    .visible-count {{ font-size: 12px; font-weight: 700; color: #102a43; }}
    button {{ border: 1px solid #9fb3c8; background: #fff; color: #102a43; border-radius: 6px; padding: 8px 10px; font: inherit; cursor: pointer; }}
    button:hover {{ background: #f0f4f8; }}
    .export-panel {{ margin: 16px; padding: 12px; border: 1px solid #bcccdc; border-radius: 6px; background: #fff; }}
    .export-panel textarea {{ min-height: 180px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; padding: 16px; }}
    .clip {{ border: 1px solid #d9e2ec; border-radius: 6px; background: #fff; overflow: hidden; }}
    .clip[data-state="approve"], .clip[data-state="promote"] {{ border-color: #51a36d; }}
    .clip[data-state="reject"], .clip[data-state="cut"] {{ opacity: 0.66; }}
    img, .missing {{ width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #e6edf3; display: block; }}
    .missing {{ display: grid; place-items: center; color: #627d98; font-size: 13px; }}
    .clip-body {{ padding: 11px; }}
    .clip-head {{ display: flex; justify-content: space-between; align-items: start; gap: 10px; }}
    h2 {{ font-size: 14px; margin: 0 0 6px; }}
    .score {{ min-width: 34px; text-align: center; border-radius: 999px; background: #eaf5ef; color: #276749; padding: 3px 7px; font-weight: 700; font-size: 12px; }}
    p {{ font-size: 12px; line-height: 1.35; margin: 6px 0; }}
    .source {{ color: #52606d; }}
    .labels {{ color: #334e68; font-weight: 600; }}
    .reasons, .ai-reasons, .signals, .objects, .advanced, .meta-line {{ color: #334e68; }}
    .ai-reasons {{ border-left: 3px solid #805ad5; padding-left: 8px; }}
    .calibration {{ font-weight: 600; }}
    .calibration-matched {{ color: #276749; }}
    .calibration-false_positive {{ color: #9b2c2c; }}
    .proxy {{ display: inline-block; margin: 4px 0 8px; font-size: 12px; }}
    .review-controls {{ display: grid; grid-template-columns: 1fr 74px; gap: 8px; margin-top: 10px; }}
    label {{ display: grid; gap: 4px; font-size: 11px; color: #52606d; }}
    select, input, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #bcccdc; border-radius: 5px; padding: 6px; font: inherit; background: #fff; color: #102a43; }}
    textarea {{ grid-column: 1 / -1; resize: vertical; min-height: 54px; }}
    .warnings {{ margin: 16px; padding: 12px; border: 1px solid #f0b429; border-radius: 6px; background: #fffbea; }}
    .warnings h2 {{ margin: 0 0 8px; }}
    .warnings li {{ font-size: 12px; margin: 4px 0; }}
  </style>
</head>
<body data-ratings="{html.escape(manifest.get("ratings", ""), quote=True)}">
  <header>
    <div>
      <h1>Videoedit Contact Sheet</h1>
      <p class="meta">{manifest.get("count", 0)} candidates from {html.escape(manifest.get("ratings", ""))}</p>
      <p class="meta">{html.escape(calibration_summary)}</p>
    </div>
    <div class="toolbar">
      <span class="visible-count" id="visibleCount"></span>
      <span class="counts" id="decisionCounts"></span>
      <div class="bulk-controls">
        <label>Bulk decision
          <select id="bulkDecision">
            <option value="approve">Approve</option>
            <option value="promote">Promote</option>
            <option value="review">Review</option>
            <option value="reject">Reject</option>
            <option value="broll">B-roll</option>
            <option value="cut">Cut</option>
          </select>
        </label>
        <button type="button" onclick="applyBulkDecision()">Apply to visible</button>
        <button type="button" onclick="quickBulkDecision('approve')">Approve visible</button>
        <button type="button" onclick="quickBulkDecision('reject')">Reject visible</button>
        <button type="button" onclick="quickBulkDecision('broll')">B-roll visible</button>
        <button type="button" onclick="quickBulkDecision('cut')">Cut visible</button>
      </div>
      <button type="button" onclick="downloadDecisions()">Download decisions JSON</button>
      <button type="button" onclick="copyDecisions()">Copy JSON</button>
      <button type="button" onclick="showExportPanel()">Show JSON</button>
    </div>
  </header>
  <section class="filters">
    <label>Search<input id="searchFilter" type="search" placeholder="clip, source, label, reason"></label>
    <label>Action<select id="actionFilter"><option value="">All actions</option></select></label>
    <label>Decision<select id="decisionFilter"><option value="">All decisions</option><option value="approve">Approve</option><option value="promote">Promote</option><option value="review">Review</option><option value="reject">Reject</option><option value="broll">B-roll</option><option value="cut">Cut</option></select></label>
    <label>Label<select id="labelFilter"><option value="">All labels</option></select></label>
    <label>Calibration<select id="calibrationFilter"><option value="">All calibration</option></select></label>
    <label>Sort<select id="sortMode"><option value="rank">Rank</option><option value="score-desc">Score high-low</option><option value="score-asc">Score low-high</option><option value="source">Source</option><option value="order">Review order</option></select></label>
    <button type="button" onclick="clearFilters()">Clear filters</button>
  </section>
  <section class="export-panel" id="exportPanel" hidden>
    <label>Decisions JSON
      <textarea id="exportDecisionsText" spellcheck="false"></textarea>
    </label>
    <div class="toolbar">
      <button type="button" onclick="refreshExportText(true)">Refresh and select JSON</button>
      <button type="button" onclick="hideExportPanel()">Hide JSON</button>
    </div>
  </section>
  {warnings}
  <section class="grid" id="clipGrid">
    {''.join(cards)}
  </section>
  <script>
    const storageKey = "videoedit-review:" + document.body.dataset.ratings;

    function cards() {{
      return Array.from(document.querySelectorAll(".clip"));
    }}

    function grid() {{
      return document.getElementById("clipGrid");
    }}

    function visibleCards() {{
      return cards().filter((card) => !card.hidden);
    }}

    function collectDecisions() {{
      return {{
        generated: new Date().toISOString(),
        ratings: document.body.dataset.ratings,
        decisions: cards().map((card, index) => {{
          const orderInput = card.querySelector(".order");
          return {{
            id: card.dataset.id,
            decision: card.querySelector(".decision").value,
            order: Number(orderInput.value || index + 1),
            note: card.querySelector(".note").value,
            score: Number(card.dataset.score || 0),
            current_action: card.dataset.currentAction || "",
            source: card.dataset.source || "",
            start: card.dataset.start || "",
            end: card.dataset.end || ""
          }};
        }})
      }};
    }}

    function saveState() {{
      localStorage.setItem(storageKey, JSON.stringify(collectDecisions()));
      updateCounts();
      refreshExportText(false);
    }}

    function restoreState() {{
      const saved = localStorage.getItem(storageKey);
      if (!saved) {{
        updateCounts();
        return;
      }}
      try {{
        const byId = Object.fromEntries(JSON.parse(saved).decisions.map((item) => [item.id, item]));
        cards().forEach((card) => {{
          const item = byId[card.dataset.id];
          if (!item) return;
          card.querySelector(".decision").value = item.decision || "reject";
          card.querySelector(".order").value = item.order || "";
          card.querySelector(".note").value = item.note || "";
        }});
      }} catch (error) {{
        console.warn(error);
      }}
      updateCounts();
    }}

    function updateCounts() {{
      const counts = {{}};
      cards().forEach((card) => {{
        const decision = card.querySelector(".decision").value;
        card.dataset.state = decision;
        counts[decision] = (counts[decision] || 0) + 1;
      }});
      document.getElementById("decisionCounts").textContent = Object.keys(counts)
        .sort()
        .map((key) => key + ": " + counts[key])
        .join("  ");
      document.getElementById("visibleCount").textContent = visibleCards().length + " visible / " + cards().length + " total";
    }}

    function populateFilters() {{
      const actions = new Set();
      const labels = new Set();
      const calibration = new Set();
      cards().forEach((card) => {{
        if (card.dataset.currentAction) actions.add(card.dataset.currentAction);
        if (card.dataset.calibration) calibration.add(card.dataset.calibration);
        (card.dataset.labels || "").split(",").map((value) => value.trim()).filter(Boolean).forEach((value) => labels.add(value));
      }});
      fillSelect("actionFilter", actions);
      fillSelect("labelFilter", labels);
      fillSelect("calibrationFilter", calibration);
    }}

    function fillSelect(id, values) {{
      const select = document.getElementById(id);
      Array.from(values).sort().forEach((value) => {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
    }}

    function applyFilters() {{
      preserveScroll(() => {{
        filterCards();
        applySort();
        updateCounts();
      }});
    }}

    function filterCards() {{
      const query = document.getElementById("searchFilter").value.toLowerCase();
      const action = document.getElementById("actionFilter").value;
      const decision = document.getElementById("decisionFilter").value;
      const label = document.getElementById("labelFilter").value;
      const calibration = document.getElementById("calibrationFilter").value;
      cards().forEach((card) => {{
        const text = card.textContent.toLowerCase();
        const labels = (card.dataset.labels || "").split(",").map((value) => value.trim());
        const matches = (!query || text.includes(query))
          && (!action || card.dataset.currentAction === action)
          && (!decision || card.querySelector(".decision").value === decision)
          && (!label || labels.includes(label))
          && (!calibration || card.dataset.calibration === calibration);
        card.hidden = !matches;
      }});
    }}

    function applySort() {{
      const mode = document.getElementById("sortMode").value;
      const sorted = cards().sort((a, b) => {{
        if (mode === "score-desc") return Number(b.dataset.score || 0) - Number(a.dataset.score || 0);
        if (mode === "score-asc") return Number(a.dataset.score || 0) - Number(b.dataset.score || 0);
        if (mode === "source") return (a.dataset.sourceName || "").localeCompare(b.dataset.sourceName || "") || Number(a.dataset.score || 0) - Number(b.dataset.score || 0);
        if (mode === "order") return Number(a.querySelector(".order").value || 999999) - Number(b.querySelector(".order").value || 999999);
        return Number(a.querySelector(".order").defaultValue || 0) - Number(b.querySelector(".order").defaultValue || 0);
      }});
      sorted.forEach((card) => grid().appendChild(card));
    }}

    function preserveScroll(callback) {{
      const anchor = scrollAnchor();
      callback();
      restoreScroll(anchor);
    }}

    function scrollAnchor() {{
      const activeCard = document.activeElement ? document.activeElement.closest(".clip") : null;
      const card = activeCard && !activeCard.hidden
        ? activeCard
        : visibleCards().find((item) => item.getBoundingClientRect().bottom > 120);
      if (!card) return null;
      return {{ id: card.dataset.id, top: card.getBoundingClientRect().top }};
    }}

    function restoreScroll(anchor) {{
      if (!anchor) return;
      const card = cards().find((item) => item.dataset.id === anchor.id);
      if (!card || card.hidden) return;
      window.scrollBy(0, card.getBoundingClientRect().top - anchor.top);
    }}

    function clearFilters() {{
      preserveScroll(() => {{
        document.getElementById("searchFilter").value = "";
        document.getElementById("actionFilter").value = "";
        document.getElementById("decisionFilter").value = "";
        document.getElementById("labelFilter").value = "";
        document.getElementById("calibrationFilter").value = "";
        document.getElementById("sortMode").value = "rank";
        filterCards();
        applySort();
        updateCounts();
      }});
    }}

    function applyBulkDecision() {{
      quickBulkDecision(document.getElementById("bulkDecision").value);
    }}

    function quickBulkDecision(decision) {{
      preserveScroll(() => {{
        visibleCards().forEach((card) => {{
          card.querySelector(".decision").value = decision;
        }});
        localStorage.setItem(storageKey, JSON.stringify(collectDecisions()));
        filterCards();
        applySort();
        updateCounts();
      }});
    }}

    function downloadDecisions() {{
      const blob = new Blob([JSON.stringify(collectDecisions(), null, 2)], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "review_decisions.json";
      link.click();
      URL.revokeObjectURL(url);
    }}

    async function copyDecisions() {{
      await navigator.clipboard.writeText(JSON.stringify(collectDecisions(), null, 2));
    }}

    function showExportPanel() {{
      document.getElementById("exportPanel").hidden = false;
      refreshExportText(true);
    }}

    function hideExportPanel() {{
      document.getElementById("exportPanel").hidden = true;
    }}

    function refreshExportText(selectText) {{
      const panel = document.getElementById("exportPanel");
      if (panel.hidden) return;
      const textarea = document.getElementById("exportDecisionsText");
      textarea.value = JSON.stringify(collectDecisions(), null, 2);
      if (selectText) {{
        textarea.focus();
        textarea.select();
      }}
    }}

    function bindReviewControls() {{
      cards().forEach((card) => {{
        card.querySelectorAll(".decision, .order, .note").forEach((control) => {{
          control.addEventListener("change", saveState);
          control.addEventListener("input", saveState);
        }});
      }});
    }}

    populateFilters();
    bindReviewControls();
    ["searchFilter", "actionFilter", "decisionFilter", "labelFilter", "calibrationFilter", "sortMode"].forEach((id) => {{
      document.getElementById(id).addEventListener("input", applyFilters);
      document.getElementById(id).addEventListener("change", applyFilters);
    }});
    restoreState();
  </script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document)


def _default_decision(action: str) -> str:
    if action in {"select", "review"}:
        return "approve"
    if action in {"broll", "b-roll", "b_roll"}:
        return "broll"
    return "reject"


def _decision_options(selected: str) -> str:
    options = [
        ("approve", "Approve"),
        ("promote", "Promote"),
        ("review", "Review"),
        ("reject", "Reject"),
        ("broll", "B-roll"),
        ("cut", "Cut"),
    ]
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in options
    )


def _source_meta_line(source_meta: dict) -> str:
    parts = [
        source_meta.get("resolution"),
        f"{source_meta.get('fps')} fps" if source_meta.get("fps") else None,
        source_meta.get("codec"),
        source_meta.get("duration_formatted"),
    ]
    return " | ".join(str(item) for item in parts if item)


def _signal_summary_items(signals: dict) -> str:
    keys = [
        "technical_score",
        "visual_activity_score",
        "audio_interest_score",
        "transcript_score",
        "object_presence_score",
        "ocr_signage_score",
        "face_person_score",
        "motorsports_event_score",
        "topic_cluster_score",
        "ai_frame_score",
    ]
    parts = []
    for key in keys:
        value = signals.get(key)
        if value not in {None, 0, 0.0}:
            parts.append(f"{key.replace('_score', '').replace('_', ' ')} {value}")
    return "Signals: " + ", ".join(parts) if parts else ""


def _object_summary_items(hits: list[dict]) -> str:
    if not hits:
        return ""
    classes = {}
    for hit in hits:
        name = str(hit.get("class_name") or "object")
        classes[name] = classes.get(name, 0) + int(hit.get("count", 1) or 1)
    text = ", ".join(f"{name} x{count}" for name, count in sorted(classes.items())[:6])
    return f"Objects: {text}"


def _advanced_summary_items(hits: list[dict]) -> str:
    if not hits:
        return ""
    kinds = {}
    for hit in hits:
        kind = str(hit.get("kind") or "advanced")
        kinds[kind] = kinds.get(kind, 0) + 1
    ai_labels = sorted(
        {
            str(label)
            for hit in hits
            if hit.get("kind") == "ai_frame_score"
            for label in hit.get("labels", [])
            if label
        }
    )
    text = ", ".join(f"{kind} x{count}" for kind, count in sorted(kinds.items())[:6])
    if ai_labels:
        text = f"{text}; AI labels: {', '.join(ai_labels[:6])}"
    return f"Advanced: {text}"


def _ai_explanation_items(explanations: list[dict]) -> str:
    rows = []
    for item in explanations:
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        score = item.get("score")
        action = item.get("suggested_action")
        labels = ", ".join(str(label) for label in item.get("labels", [])[:4])
        prefix_parts = []
        if score not in {None, ""}:
            prefix_parts.append(f"score {score}")
        if action:
            prefix_parts.append(f"suggested {action}")
        if labels:
            prefix_parts.append(labels)
        prefix = f" ({'; '.join(prefix_parts)})" if prefix_parts else ""
        rows.append(f"{reason}{prefix}")
    return " | ".join(rows[:3])


def _calibration_line(calibration: dict) -> str:
    status = calibration.get("status", "unreviewed")
    if status == "matched":
        return f"Calibration: matched {calibration.get('annotation_id', '')} overlap {calibration.get('overlap_ratio', '')}"
    if status == "false_positive":
        return f"Calibration: false positive nearest {calibration.get('nearest_annotation', '')}"
    return f"Calibration: {status}"


def _calibration_summary_line(calibration: dict) -> str:
    summary = calibration.get("summary") or {}
    if not summary:
        return "No calibration report attached"
    return (
        f"Calibration precision {summary.get('precision', 0)}, "
        f"recall {summary.get('recall', 0)}, F1 {summary.get('f1', 0)}"
    )


def _read_json(path: str) -> dict:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path: str, data: dict) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2))


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "clip"
