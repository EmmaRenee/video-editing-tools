"""Provider processing coverage, separate from positive detection counts."""

from __future__ import annotations

import math
from typing import Any, Callable

SCHEMA = "videoedit.coverage.v1"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def sample_coverage(source: str, duration: float, expected: list[float], processed: list[float], interval: float) -> dict[str, Any]:
    """Coverage cells follow the uniform sampler's midpoint convention."""
    expected, processed = sorted({round(value, 3) for value in expected}), sorted({round(value, 3) for value in processed})
    return {"source": source, "status": "ok" if processed and expected == processed else "partial" if processed else "error",
            "expected_units": len(expected), "processed_units": len(processed),
            "intervals": [[max(0.0, value - interval / 2), min(duration, value + interval / 2)]
                          for value in processed if min(duration, value + interval / 2) > max(0.0, value - interval / 2)]}


def assess_coverage(data: Any, windows: dict[str, list[tuple[float, float]]],
                    resolve: Callable[[str], str] = lambda value: value) -> dict[str, Any]:
    result = {"status": "unknown", "scope": "unknown", "source_ratio": 0.0, "unit_ratio": 0.0,
              "temporal_ratio": 0.0, "covered_seconds": 0.0, "reviewed_seconds": 0.0,
              "expected_units": 0, "processed_units": 0}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
        return result
    scope, rows = data.get("scope"), data.get("sources")
    if scope not in {"temporal", "candidate"} or not isinstance(rows, list):
        return {**result, "status": "invalid"}
    result["scope"] = scope
    seen, covered, incomplete = set(), {}, False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source"), str) or not row["source"]:
            return {**result, "status": "invalid"}
        source = resolve(row["source"])
        if source in seen:
            return {**result, "status": "invalid"}
        seen.add(source)
        expected, processed, intervals = row.get("expected_units"), row.get("processed_units"), row.get("intervals")
        if (not isinstance(expected, int) or isinstance(expected, bool) or not isinstance(processed, int)
                or isinstance(processed, bool) or not 0 <= processed <= expected or not isinstance(intervals, list)):
            return {**result, "status": "invalid"}
        parsed = []
        for interval in intervals:
            if not isinstance(interval, (list, tuple)) or len(interval) != 2 or not all(_number(value) for value in interval) or interval[1] <= interval[0]:
                return {**result, "status": "invalid"}
            parsed.append(tuple(interval))
        if bool(processed) != bool(parsed):
            return {**result, "status": "invalid"}
        if source not in windows:
            continue
        incomplete |= row.get("status") != "ok" or processed != expected
        result["expected_units"] += expected
        result["processed_units"] += processed
        if processed and any(min(end, right) > max(start, left) for start, end in windows[source] for left, right in parsed):
            covered[source] = _merge(parsed)
    reviewed = {source: _merge(intervals) for source, intervals in windows.items()}
    seconds = sum(end - start for intervals in reviewed.values() for start, end in intervals)
    overlap = sum(max(0, min(end, right) - max(start, left)) for source, intervals in reviewed.items()
                  for start, end in intervals for left, right in covered.get(source, []))
    result.update(reviewed_seconds=round(seconds, 6), covered_seconds=round(overlap, 6),
                  temporal_ratio=round(overlap / seconds, 6) if seconds else 0,
                  source_ratio=round(len(covered) / len(reviewed), 6) if reviewed else 0,
                  unit_ratio=round(result["processed_units"] / result["expected_units"], 6) if result["expected_units"] else 0,
                  status="empty" if not result["processed_units"] else "partial" if incomplete else "ok")
    return result
