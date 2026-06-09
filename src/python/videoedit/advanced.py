"""Optional advanced signal providers.

These providers are deliberately optional. The deterministic rating pipeline
must keep working without OCR, object detection, or other heavy dependencies.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
from typing import Any

from .diagnostics import resolve_command
from .ffmpeg import has_command, probe_media, run_command, run_command_check, scan_video_files
from .timecode import seconds_to_hhmmss, timecode_to_seconds


MOTORSPORTS_EVENTS = {
    "pass": ["pass", "passed", "passes", "overtake", "overtook", "inside", "outside"],
    "incident": ["incident", "crash", "contact", "hit", "wreck", "spin", "spun", "problem"],
    "start": ["start", "green flag", "launch", "restart"],
    "finish": ["finish", "checkered", "checker", "podium", "win", "winner"],
    "pace": ["fast", "quick", "lap", "sector", "speed", "pace"],
    "battle": ["battle", "side by side", "door to door", "defend", "defending", "attack"],
    "yellow": ["yellow", "caution", "safety car", "full course yellow"],
    "pit": ["pit", "pitlane", "pit lane", "stop", "fuel", "tires"],
    "mechanical": ["mechanical", "engine", "gearbox", "brake", "failure", "broken"],
}

TRANSCRIPT_TOPICS = {
    "racecraft": ["pass", "passed", "overtake", "inside", "outside", "line", "brake"],
    "incidents": ["incident", "crash", "contact", "spin", "spun", "problem", "issue"],
    "race_control": ["start", "restart", "yellow", "green", "checkered", "flag", "finish"],
    "performance": ["fast", "quick", "lap", "speed", "pace", "setup", "tires"],
    "results": ["win", "winner", "podium", "position", "place", "finish"],
    "mechanical": ["engine", "gearbox", "brake", "failure", "broken", "setup"],
}

COCO_CLASS_NAMES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]

SIGNAL_SCHEMA_VERSION = "videoedit.signal.v1"


def detect_motorsports_events(ratings_json: str, output: str, min_confidence: float = 0.2) -> dict[str, Any]:
    data = _read_json(ratings_json)
    events = []
    for clip in data.get("candidates", []):
        text = _candidate_text(clip)
        matched_any = False
        for event_type, keywords in MOTORSPORTS_EVENTS.items():
            matched = _matched_keywords(text, keywords)
            if not matched:
                continue
            matched_any = True
            event = _event_from_clip(clip, event_type, matched)
            if event["confidence"] >= min_confidence:
                events.append(event)
        if not matched_any:
            inferred = _inferred_event(clip)
            if inferred and inferred["confidence"] >= min_confidence:
                events.append(inferred)

    events.sort(key=lambda item: (-item["confidence"], -item["score"], item["source"], item["start_seconds"]))
    payload = {
        "generated": datetime.now().isoformat(),
        "ratings": os.fspath(ratings_json),
        "provider": "deterministic_motorsports_heuristics",
        "count": len(events),
        "events": events,
    }
    _attach_signal_metadata(payload, "motorsports_events", payload["provider"], ratings_json, events)
    _write_json(output, payload)
    return {"output": os.fspath(output), "count": len(events)}


def cluster_transcript_topics(ratings_json: str, output: str) -> dict[str, Any]:
    data = _read_json(ratings_json)
    clusters: dict[str, dict[str, Any]] = {
        topic: {"topic": topic, "keywords": [], "hits": []} for topic in TRANSCRIPT_TOPICS
    }
    for signal in data.get("signals", []):
        source = signal.get("asset", {}).get("filepath")
        for hit in signal.get("transcript_hits", []):
            text = " ".join([hit.get("text", ""), " ".join(hit.get("keywords", []))]).lower()
            for topic, keywords in TRANSCRIPT_TOPICS.items():
                matched = _matched_keywords(text, keywords)
                if not matched:
                    continue
                clusters[topic]["keywords"].extend(matched)
                clusters[topic]["hits"].append(
                    {
                        "source": source,
                        "start": seconds_to_hhmmss(_clip_seconds(hit, "start", "start_seconds")),
                        "end": seconds_to_hhmmss(_clip_seconds(hit, "end", "end_seconds")),
                        "start_seconds": _clip_seconds(hit, "start", "start_seconds"),
                        "end_seconds": _clip_seconds(hit, "end", "end_seconds"),
                        "text": hit.get("text", ""),
                        "keywords": matched,
                    }
                )

    topics = []
    for topic in sorted(clusters):
        cluster = clusters[topic]
        if not cluster["hits"]:
            continue
        cluster["keywords"] = sorted(set(cluster["keywords"]))
        cluster["count"] = len(cluster["hits"])
        topics.append(cluster)
    topics.sort(key=lambda item: (-item["count"], item["topic"]))

    payload = {
        "generated": datetime.now().isoformat(),
        "ratings": os.fspath(ratings_json),
        "provider": "deterministic_transcript_topic_clustering",
        "count": len(topics),
        "topics": topics,
    }
    _attach_signal_metadata(payload, "topic_clusters", payload["provider"], ratings_json, _topic_records(topics))
    _write_json(output, payload)
    return {"output": os.fspath(output), "count": len(topics)}


def detect_ocr_signage(
    input_path: str,
    output: str,
    sample_interval: float = 10.0,
    max_frames_per_file: int = 6,
    timeout: int = 180,
) -> dict[str, Any]:
    output = os.fspath(output)
    output_dir = os.path.dirname(output) or "."
    frames_dir = os.path.join(output_dir, "ocr_frames")
    warnings: list[str] = []
    hits: list[dict[str, Any]] = []
    if not has_command("ffmpeg") or not has_command("tesseract"):
        payload = _unavailable_payload(
            "ocr_signage",
            input_path,
            "ffmpeg and tesseract are required for OCR signage detection",
        )
        _write_json(output, payload)
        return {"output": output, "count": 0, "status": payload["status"]}

    os.makedirs(frames_dir, exist_ok=True)
    for source in _input_files(input_path):
        stem = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        pattern = os.path.join(frames_dir, f"{stem}_%04d.jpg")
        try:
            run_command_check(
                [
                    "ffmpeg",
                    "-i",
                    source,
                    "-vf",
                    f"fps=1/{max(1.0, float(sample_interval))}",
                    "-frames:v",
                    str(max(1, int(max_frames_per_file))),
                    pattern,
                    "-y",
                ],
                timeout=timeout,
            )
        except Exception as exc:
            warnings.append(f"frame sampling failed for {source}: {exc}")
            continue
        for frame in sorted(_matching_frames(frames_dir, stem)):
            result = run_command(["tesseract", frame, "stdout"], timeout=timeout)
            text = result.stdout.strip()
            if result.returncode == 0 and text:
                hits.append({"source": source, "frame": frame, "text": text})
            elif result.returncode != 0:
                warnings.append(f"ocr failed for {frame}: {(result.stderr or result.stdout).strip()}")

    payload = {
        "generated": datetime.now().isoformat(),
        "provider": "tesseract_ocr",
        "status": "ok",
        "input": os.fspath(input_path),
        "count": len(hits),
        "hits": hits,
        "warnings": warnings,
    }
    _attach_signal_metadata(payload, "ocr_signage", payload["provider"], input_path, hits)
    _write_json(output, payload)
    return {"output": output, "count": len(hits), "status": "ok", "warnings": warnings}


def detect_visual_objects(
    input_path: str,
    output: str,
    command: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    max_detections: int = 5000,
    segment_merge_gap: float = 1.0,
    timeout: int = 180,
) -> dict[str, Any]:
    output = os.fspath(output)
    detector = command or resolve_command("yolo")
    if not detector or (command and not has_command(detector)):
        payload = _unavailable_payload(
            "visual_objects",
            input_path,
            "install or configure an object detector command such as yolo",
        )
        _write_json(output, payload)
        return {"output": output, "count": 0, "status": payload["status"]}

    output_dir = os.path.dirname(output) or "."
    project_dir = os.path.abspath(os.path.join(output_dir, "object_detector"))
    warnings: list[str] = []
    runs = []
    sources = []
    for source in _input_files(input_path):
        name = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        expected_run = os.path.join(project_dir, name)
        command_args = [
            detector,
            "predict",
            f"source={source}",
            f"project={project_dir}",
            f"name={name}",
            "exist_ok=True",
            "save=False",
            "save_txt=True",
            "save_conf=True",
        ]
        if model:
            command_args.insert(2, f"model={model}")
        if confidence is not None:
            command_args.append(f"conf={confidence}")
        result = run_command(
            command_args,
            timeout=timeout,
        )
        if result.returncode == 0:
            run_dir = _resolve_yolo_run_dir(expected_run)
            asset = probe_media(source, timeout=min(timeout, 60))
            source_summary = _parse_yolo_run(
                source=source,
                run_dir=run_dir,
                fps=asset.fps,
                duration=asset.duration,
                max_detections=max_detections,
                segment_merge_gap=segment_merge_gap,
            )
            warnings.extend(source_summary.pop("warnings"))
            sources.append(source_summary)
            runs.append(
                {
                    "source": source,
                    "run": run_dir,
                    "labels_dir": source_summary.get("labels_dir"),
                    "detection_count": source_summary.get("detection_count", 0),
                    "class_count": len(source_summary.get("class_counts", [])),
                    "segment_count": len(source_summary.get("segments", [])),
                }
            )
        else:
            warnings.append(f"object detection failed for {source}: {(result.stderr or result.stdout).strip()}")

    detection_count = sum(int(item.get("detection_count", 0)) for item in sources)
    classes = sorted({item["class_name"] for source in sources for item in source.get("class_counts", [])})
    segment_count = sum(len(source.get("segments", [])) for source in sources)
    payload = {
        "generated": datetime.now().isoformat(),
        "provider": detector,
        "model": model,
        "confidence": confidence,
        "status": "ok" if runs else "error",
        "input": os.fspath(input_path),
        "count": len(runs),
        "detection_count": detection_count,
        "class_count": len(classes),
        "segment_count": segment_count,
        "runs": runs,
        "sources": sources,
        "warnings": warnings,
    }
    _attach_signal_metadata(payload, "visual_objects", detector, input_path, sources)
    _write_json(output, payload)
    return {
        "output": output,
        "count": len(runs),
        "detection_count": detection_count,
        "class_count": len(classes),
        "segment_count": segment_count,
        "status": payload["status"],
        "warnings": warnings,
    }


def detect_face_person_presence(
    input_path: str,
    output: str,
    sample_interval: float = 10.0,
    max_frames_per_file: int = 6,
    timeout: int = 180,
) -> dict[str, Any]:
    output = os.fspath(output)
    output_dir = os.path.dirname(output) or "."
    frames_dir = os.path.join(output_dir, "face_person_frames")
    try:
        cv2 = __import__("cv2")
    except ImportError:
        payload = _unavailable_payload(
            "face_person_presence",
            input_path,
            "opencv-python is required for face/person presence detection",
        )
        _write_json(output, payload)
        return {"output": output, "count": 0, "status": payload["status"]}
    if not has_command("ffmpeg"):
        payload = _unavailable_payload(
            "face_person_presence",
            input_path,
            "ffmpeg is required for frame sampling",
        )
        _write_json(output, payload)
        return {"output": output, "count": 0, "status": payload["status"]}

    os.makedirs(frames_dir, exist_ok=True)
    warnings: list[str] = []
    hits: list[dict[str, Any]] = []
    face_detector = _opencv_face_detector(cv2, warnings)
    person_detector = _opencv_person_detector(cv2, warnings)

    for source in _input_files(input_path):
        stem = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        pattern = os.path.join(frames_dir, f"{stem}_%04d.jpg")
        try:
            run_command_check(
                [
                    "ffmpeg",
                    "-i",
                    source,
                    "-vf",
                    f"fps=1/{max(1.0, float(sample_interval))}",
                    "-frames:v",
                    str(max(1, int(max_frames_per_file))),
                    pattern,
                    "-y",
                ],
                timeout=timeout,
            )
        except Exception as exc:
            warnings.append(f"frame sampling failed for {source}: {exc}")
            continue

        for frame in sorted(_matching_frames(frames_dir, stem)):
            image = cv2.imread(frame)
            if image is None:
                warnings.append(f"frame read failed: {frame}")
                continue
            face_count = _count_faces(cv2, face_detector, image)
            person_count = _count_people(person_detector, image)
            if face_count or person_count:
                hits.append(
                    {
                        "source": source,
                        "frame": frame,
                        "face_count": face_count,
                        "person_count": person_count,
                    }
                )

    payload = {
        "generated": datetime.now().isoformat(),
        "provider": "opencv_face_person",
        "status": "ok",
        "input": os.fspath(input_path),
        "count": len(hits),
        "hits": hits,
        "warnings": warnings,
    }
    _attach_signal_metadata(payload, "face_person_presence", payload["provider"], input_path, hits)
    _write_json(output, payload)
    return {"output": output, "count": len(hits), "status": "ok", "warnings": warnings}


def _candidate_text(clip: dict[str, Any]) -> str:
    parts = [
        clip.get("id", ""),
        clip.get("source", ""),
        " ".join(str(item) for item in clip.get("labels", [])),
        " ".join(str(item) for item in clip.get("reasons", [])),
    ]
    return " ".join(parts).lower()


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    matched = []
    for keyword in keywords:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(keyword.lower()) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text):
            matched.append(keyword)
    return matched


def _event_from_clip(clip: dict[str, Any], event_type: str, matched: list[str]) -> dict[str, Any]:
    score = int(clip.get("score", 0))
    confidence = min(1.0, 0.35 + (score / 200.0) + min(0.3, len(matched) * 0.1))
    return {
        "candidate_id": clip.get("id") or clip.get("label"),
        "event_type": event_type,
        "confidence": round(confidence, 3),
        "source": clip.get("source"),
        "start": seconds_to_hhmmss(_clip_seconds(clip, "start", "start_seconds")),
        "end": seconds_to_hhmmss(_clip_seconds(clip, "end", "end_seconds")),
        "start_seconds": _clip_seconds(clip, "start", "start_seconds"),
        "end_seconds": _clip_seconds(clip, "end", "end_seconds"),
        "score": score,
        "labels": list(clip.get("labels", [])),
        "evidence": matched,
    }


def _inferred_event(clip: dict[str, Any]) -> dict[str, Any] | None:
    labels = set(clip.get("labels", []))
    reasons = " ".join(str(item).lower() for item in clip.get("reasons", []))
    if {"object_car", "object_truck", "object_motorcycle"} & labels and "audio_spike" in labels:
        return _event_from_clip(clip, "vehicle_action", ["object_vehicle", "audio_spike"])
    if "motorsports_event" in labels:
        return _event_from_clip(clip, "motorsports_context", ["motorsports_event"])
    if "engine" in reasons and "audio_spike" in labels:
        return _event_from_clip(clip, "mechanical", ["engine", "audio_spike"])
    if "audio_spike" in labels and ("scene_change" in labels or "scene_cluster" in labels):
        return _event_from_clip(clip, "high_energy", ["audio_spike", "scene_change"])
    if "scene_cluster" in labels:
        return _event_from_clip(clip, "visual_activity", ["scene_cluster"])
    return None


def _attach_signal_metadata(
    payload: dict[str, Any],
    artifact_kind: str,
    provider_name: str,
    input_path: str,
    records: list[dict[str, Any]],
) -> None:
    summaries = _source_summaries(records)
    payload["schema_version"] = SIGNAL_SCHEMA_VERSION
    payload["artifact_kind"] = artifact_kind
    payload["provider_metadata"] = {
        "name": provider_name,
        "version": "unknown",
        "artifact_kind": artifact_kind,
    }
    payload["source_count"] = len(summaries)
    payload["source_summaries"] = summaries
    payload.setdefault("input", os.fspath(input_path))


def _source_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for record in records:
        source = record.get("source")
        if not source:
            continue
        row = rows.setdefault(
            os.fspath(source),
            {
                "source": os.fspath(source),
                "count": 0,
                "detection_count": 0,
                "segment_count": 0,
                "class_count": 0,
                "confidence_values": [],
            },
        )
        row["count"] += int(record.get("count", 1) or 1)
        row["detection_count"] += int(record.get("detection_count", 0) or 0)
        row["segment_count"] += len(record.get("segments", [])) if isinstance(record.get("segments"), list) else 0
        row["class_count"] = max(
            int(row["class_count"]),
            len(record.get("class_counts", [])) if isinstance(record.get("class_counts"), list) else 0,
        )
        for key in ["confidence", "average_confidence"]:
            if record.get(key) is not None:
                row["confidence_values"].append(float(record[key]))
    summaries = []
    for row in rows.values():
        values = row.pop("confidence_values")
        if values:
            row["average_confidence"] = round(sum(values) / len(values), 4)
        summaries.append(row)
    return sorted(summaries, key=lambda item: item["source"])


def _topic_records(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for topic in topics:
        for hit in topic.get("hits", []):
            row = dict(hit)
            row["topic"] = topic.get("topic")
            records.append(row)
    return records


def _clip_seconds(clip: dict[str, Any], formatted_key: str, seconds_key: str) -> float:
    if seconds_key in clip:
        return float(clip[seconds_key])
    return timecode_to_seconds(clip.get(formatted_key, 0))


def _input_files(input_path: str) -> list[str]:
    input_path = os.fspath(input_path)
    if os.path.isfile(input_path):
        return [input_path]
    return scan_video_files(input_path)


def _matching_frames(frames_dir: str, stem: str) -> list[str]:
    prefix = f"{stem}_"
    return [
        os.path.join(frames_dir, filename)
        for filename in os.listdir(frames_dir)
        if filename.startswith(prefix) and filename.lower().endswith(".jpg")
    ]


def _resolve_yolo_run_dir(expected_run: str) -> str:
    if os.path.isdir(os.path.join(expected_run, "labels")):
        return expected_run
    cwd = os.getcwd()
    try:
        relative = os.path.relpath(expected_run, cwd)
    except ValueError:
        relative = expected_run
    fallback = os.path.join(cwd, "runs", "detect", relative)
    if os.path.isdir(os.path.join(fallback, "labels")):
        return fallback
    basename = os.path.basename(expected_run)
    matches = []
    for current_dir, dirnames, _filenames in os.walk(os.path.join(cwd, "runs", "detect")):
        if os.path.basename(current_dir) == basename and "labels" in dirnames:
            matches.append(current_dir)
    if len(matches) == 1:
        return matches[0]
    return expected_run


def _parse_yolo_run(
    source: str,
    run_dir: str,
    fps: float | None,
    duration: float,
    max_detections: int,
    segment_merge_gap: float,
) -> dict[str, Any]:
    labels_dir = os.path.join(run_dir, "labels")
    warnings: list[str] = []
    detections: list[dict[str, Any]] = []
    summary_detections: list[dict[str, Any]] = []
    total_detections = 0
    if not os.path.isdir(labels_dir):
        return {
            "source": source,
            "run": run_dir,
            "labels_dir": labels_dir,
            "fps": fps,
            "duration": duration,
            "detection_count": 0,
            "detections": [],
            "detections_truncated": False,
            "class_counts": [],
            "segments": [],
            "warnings": [f"YOLO labels directory not found for {source}: {labels_dir}"],
        }

    label_files = sorted(
        [
            os.path.join(labels_dir, filename)
            for filename in os.listdir(labels_dir)
            if filename.lower().endswith(".txt")
        ],
        key=_label_sort_key,
    )
    for label_path in label_files:
        frame = _frame_number_from_label(label_path)
        time_seconds = _frame_time(frame, fps)
        try:
            with open(label_path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError as exc:
            warnings.append(f"failed to read YOLO label file {label_path}: {exc}")
            continue
        for index, line in enumerate(lines, 1):
            parsed = _parse_yolo_label_line(line, label_path, index, frame, time_seconds, source)
            if parsed is None:
                continue
            total_detections += 1
            summary_detections.append(parsed)
            if len(detections) < max_detections:
                detections.append(parsed)

    class_counts = _summarize_classes(summary_detections)
    segments = _summarize_segments(summary_detections, fps, duration, segment_merge_gap)
    return {
        "source": source,
        "run": run_dir,
        "labels_dir": labels_dir,
        "fps": fps,
        "duration": duration,
        "detection_count": total_detections,
        "detections": detections,
        "detections_truncated": total_detections > len(detections),
        "class_counts": class_counts,
        "segments": segments,
        "warnings": warnings,
    }


def _parse_yolo_label_line(
    line: str,
    label_path: str,
    line_number: int,
    frame: int | None,
    time_seconds: float | None,
    source: str,
) -> dict[str, Any] | None:
    parts = line.strip().split()
    if len(parts) < 5:
        return None
    try:
        class_id = int(float(parts[0]))
        x_center, y_center, width, height = [float(value) for value in parts[1:5]]
        confidence = float(parts[5]) if len(parts) >= 6 else None
    except ValueError:
        return None
    detection = {
        "source": source,
        "label_file": label_path,
        "line": line_number,
        "frame": frame,
        "class_id": class_id,
        "class_name": _class_name(class_id),
        "confidence": round(confidence, 4) if confidence is not None else None,
        "bbox_norm": {
            "x_center": round(x_center, 6),
            "y_center": round(y_center, 6),
            "width": round(width, 6),
            "height": round(height, 6),
        },
    }
    if time_seconds is not None:
        detection["time_seconds"] = round(time_seconds, 3)
        detection["time"] = seconds_to_hhmmss(time_seconds)
    return detection


def _summarize_classes(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_class: dict[int, dict[str, Any]] = {}
    for detection in detections:
        class_id = int(detection["class_id"])
        summary = by_class.setdefault(
            class_id,
            {
                "class_id": class_id,
                "class_name": detection["class_name"],
                "count": 0,
                "frames": set(),
                "confidences": [],
                "times": [],
            },
        )
        summary["count"] += 1
        if detection.get("frame") is not None:
            summary["frames"].add(detection["frame"])
        if detection.get("confidence") is not None:
            summary["confidences"].append(float(detection["confidence"]))
        if detection.get("time_seconds") is not None:
            summary["times"].append(float(detection["time_seconds"]))

    rows = []
    for summary in by_class.values():
        times = summary["times"]
        confidences = summary["confidences"]
        row = {
            "class_id": summary["class_id"],
            "class_name": summary["class_name"],
            "count": summary["count"],
            "frame_count": len(summary["frames"]),
        }
        if confidences:
            row["average_confidence"] = round(sum(confidences) / len(confidences), 4)
        if times:
            first = min(times)
            last = max(times)
            row.update(
                {
                    "first_seen_seconds": round(first, 3),
                    "first_seen": seconds_to_hhmmss(first),
                    "last_seen_seconds": round(last, 3),
                    "last_seen": seconds_to_hhmmss(last),
                }
            )
        rows.append(row)
    return sorted(rows, key=lambda item: (-item["count"], item["class_name"]))


def _summarize_segments(
    detections: list[dict[str, Any]],
    fps: float | None,
    duration: float,
    merge_gap: float,
) -> list[dict[str, Any]]:
    by_class: dict[int, list[dict[str, Any]]] = {}
    for detection in detections:
        if detection.get("time_seconds") is None:
            continue
        by_class.setdefault(int(detection["class_id"]), []).append(detection)

    frame_duration = 1.0 / fps if fps and fps > 0 else 0.0
    segments: list[dict[str, Any]] = []
    for class_id, items in by_class.items():
        items.sort(key=lambda item: float(item["time_seconds"]))
        current: list[dict[str, Any]] = []
        last_time: float | None = None
        for item in items:
            current_time = float(item["time_seconds"])
            if current and last_time is not None and current_time > last_time + merge_gap:
                segments.append(_segment_from_detections(current, frame_duration, duration))
                current = []
            current.append(item)
            last_time = current_time
        if current:
            segments.append(_segment_from_detections(current, frame_duration, duration))
    return sorted(segments, key=lambda item: (-item["detection_count"], item["start_seconds"]))[:500]


def _segment_from_detections(items: list[dict[str, Any]], frame_duration: float, duration: float) -> dict[str, Any]:
    times = [float(item["time_seconds"]) for item in items]
    start = min(times)
    end = max(times) + frame_duration
    if duration:
        end = min(duration, end)
    confidences = [float(item["confidence"]) for item in items if item.get("confidence") is not None]
    frames = {item.get("frame") for item in items if item.get("frame") is not None}
    segment = {
        "class_id": int(items[0]["class_id"]),
        "class_name": items[0]["class_name"],
        "start_seconds": round(start, 3),
        "end_seconds": round(max(start, end), 3),
        "start": seconds_to_hhmmss(start),
        "end": seconds_to_hhmmss(max(start, end)),
        "detection_count": len(items),
        "frame_count": len(frames),
    }
    if confidences:
        segment["average_confidence"] = round(sum(confidences) / len(confidences), 4)
    return segment


def _frame_number_from_label(path: str) -> int | None:
    stem = os.path.splitext(os.path.basename(path))[0]
    match = re.search(r"_(\d+)$", stem)
    if match:
        return int(match.group(1))
    if stem.isdigit():
        return int(stem)
    return None


def _frame_time(frame: int | None, fps: float | None) -> float | None:
    if frame is None or not fps or fps <= 0:
        return None
    return max(0.0, (float(frame) - 1.0) / fps)


def _label_sort_key(path: str) -> tuple[int, str]:
    frame = _frame_number_from_label(path)
    return (frame if frame is not None else 0, path)


def _class_name(class_id: int) -> str:
    if 0 <= class_id < len(COCO_CLASS_NAMES):
        return COCO_CLASS_NAMES[class_id]
    return f"class_{class_id}"


def _unavailable_payload(provider: str, input_path: str, reason: str) -> dict[str, Any]:
    payload = {
        "generated": datetime.now().isoformat(),
        "provider": provider,
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "artifact_kind": provider,
        "provider_metadata": {"name": provider, "version": "unknown", "artifact_kind": provider},
        "status": "unavailable",
        "input": os.fspath(input_path),
        "count": 0,
        "hits": [],
        "source_count": 0,
        "source_summaries": [],
        "warnings": [reason],
    }
    return payload


def _opencv_face_detector(cv2: Any, warnings: list[str]) -> Any:
    cascade_root = getattr(getattr(cv2, "data", None), "haarcascades", "")
    cascade_path = os.path.join(cascade_root, "haarcascade_frontalface_default.xml")
    if not cascade_root or not os.path.exists(cascade_path):
        warnings.append("OpenCV face cascade not found")
        return None
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        warnings.append("OpenCV face cascade failed to load")
        return None
    return detector


def _opencv_person_detector(cv2: Any, warnings: list[str]) -> Any:
    try:
        detector = cv2.HOGDescriptor()
        detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return detector
    except Exception as exc:
        warnings.append(f"OpenCV person detector unavailable: {exc}")
        return None


def _count_faces(cv2: Any, detector: Any, image: Any) -> int:
    if detector is None:
        return 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    return int(len(faces))


def _count_people(detector: Any, image: Any) -> int:
    if detector is None:
        return 0
    people, _weights = detector.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.05)
    return int(len(people))


def _read_json(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.fspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2))


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"
