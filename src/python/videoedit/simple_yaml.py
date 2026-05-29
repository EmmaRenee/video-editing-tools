"""Small YAML subset reader/writer for pipeline preset files.

The project only needs a conservative YAML shape: dictionaries, lists of
dictionaries, scalar values, and inline arrays. This avoids making the CLI
depend on optional YAML packages for normal operation.
"""

from __future__ import annotations

import ast
import json
import os
from typing import Any


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if (value.startswith("[") and value.endswith("]")) or (
        value.startswith("{") and value.endswith("}")
    ):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_mapping(path: str) -> dict[str, Any]:
    with open(os.fspath(path), encoding="utf-8") as handle:
        text = handle.read()
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return json.loads(text)

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()

    for line_index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            item_text = line[2:].strip()
            if not isinstance(parent, list):
                raise ValueError(f"List item without list parent: {raw_line}")
            if ":" in item_text:
                key, value = item_text.split(":", 1)
                item: dict[str, Any] = {key.strip(): parse_scalar(value)}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(parse_scalar(item_text))
            continue

        if ":" not in line:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            parent[key] = parse_scalar(value)
            continue

        child: Any
        next_is_list = _next_significant_line_starts_list(lines, line_index)
        child = [] if next_is_list else {}
        parent[key] = child
        stack.append((indent, child))

    return root


def _next_significant_line_starts_list(lines: list[str], index: int) -> bool:
    current_line = lines[index]
    current_indent = len(current_line) - len(current_line.lstrip(" "))
    for line in lines[index + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        return indent > current_indent and line.strip().startswith("- ")
    return False


def dumps(data: Any, indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(dumps(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}- {{}}")
                    continue
                first = True
                for key, value in item.items():
                    if first:
                        if isinstance(value, (dict, list)):
                            lines.append(f"{prefix}- {key}:")
                            lines.append(dumps(value, indent + 4))
                        else:
                            lines.append(f"{prefix}- {key}: {_format_scalar(value)}")
                        first = False
                    else:
                        if isinstance(value, (dict, list)):
                            lines.append(f"{prefix}  {key}:")
                            lines.append(dumps(value, indent + 4))
                        else:
                            lines.append(f"{prefix}  {key}: {_format_scalar(value)}")
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
    return "\n".join(lines)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value)
    text = str(value)
    if any(ch in text for ch in ":#[]{}") or text.strip() != text:
        return json.dumps(text)
    return text
