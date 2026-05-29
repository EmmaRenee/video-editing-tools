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

from .ffmpeg import has_command, run_command, run_command_check, scan_video_files
from .timecode import seconds_to_hhmmss, timecode_to_seconds


MOTORSPORTS_EVENTS = {
    "pass": ["pass", "passed", "passes", "overtake", "overtook", "inside", "outside"],
    "incident": ["incident", "crash", "contact", "hit", "wreck", "spin", "spun", "problem"],
    "start": ["start", "green flag", "launch", "restart"],
    "finish": ["finish", "checkered", "checker", "podium", "win", "winner"],
    "pace": ["fast", "quick", "lap", "sector", "speed", "pace"],
}

TRANSCRIPT_TOPICS = {
    "racecraft": ["pass", "passed", "overtake", "inside", "outside", "line", "brake"],
    "incidents": ["incident", "crash", "contact", "spin", "spun", "problem", "issue"],
    "race_control": ["start", "restart", "yellow", "green", "checkered", "flag", "finish"],
    "performance": ["fast", "quick", "lap", "speed", "pace", "setup", "tires"],
    "results": ["win", "winner", "podium", "position", "place", "finish"],
}


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
    _write_json(output, payload)
    return {"output": output, "count": len(hits), "status": "ok", "warnings": warnings}


def detect_visual_objects(
    input_path: str,
    output: str,
    command: str | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    output = os.fspath(output)
    detector = command or "yolo"
    if not detector or not has_command(detector):
        payload = _unavailable_payload(
            "visual_objects",
            input_path,
            "install or configure an object detector command such as yolo",
        )
        _write_json(output, payload)
        return {"output": output, "count": 0, "status": payload["status"]}

    output_dir = os.path.dirname(output) or "."
    project_dir = os.path.join(output_dir, "object_detector")
    warnings: list[str] = []
    runs = []
    for source in _input_files(input_path):
        name = _safe_slug(os.path.splitext(os.path.basename(source))[0])
        result = run_command(
            [
                detector,
                "predict",
                f"source={source}",
                f"project={project_dir}",
                f"name={name}",
                "save=False",
                "save_txt=True",
            ],
            timeout=timeout,
        )
        if result.returncode == 0:
            runs.append({"source": source, "run": os.path.join(project_dir, name)})
        else:
            warnings.append(f"object detection failed for {source}: {(result.stderr or result.stdout).strip()}")

    payload = {
        "generated": datetime.now().isoformat(),
        "provider": detector,
        "status": "ok" if runs else "error",
        "input": os.fspath(input_path),
        "count": len(runs),
        "runs": runs,
        "warnings": warnings,
    }
    _write_json(output, payload)
    return {"output": output, "count": len(runs), "status": payload["status"], "warnings": warnings}


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
    if "audio_spike" in labels and ("scene_change" in labels or "scene_cluster" in labels):
        return _event_from_clip(clip, "high_energy", ["audio_spike", "scene_change"])
    if "scene_cluster" in labels:
        return _event_from_clip(clip, "visual_activity", ["scene_cluster"])
    return None


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


def _unavailable_payload(provider: str, input_path: str, reason: str) -> dict[str, Any]:
    return {
        "generated": datetime.now().isoformat(),
        "provider": provider,
        "status": "unavailable",
        "input": os.fspath(input_path),
        "count": 0,
        "hits": [],
        "warnings": [reason],
    }


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
