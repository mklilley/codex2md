from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

_REQUEST_HEADING_RE = re.compile(r"^#{1,6}\s*My request for Codex\s*:?\s*$", re.IGNORECASE)
_FILES_MENTIONED_HEADING_RE = re.compile(r"^#{1,6}\s*Files mentioned by the user\s*:?\s*$", re.IGNORECASE)
_ENVIRONMENT_CONTEXT_BLOCK_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL | re.IGNORECASE)
_AGENTS_HEADER_RE = re.compile(r"^#?\s*AGENTS\.md instructions\b.*$", re.IGNORECASE)
_IDE_CONTEXT_HEADER_RE = re.compile(r"^#?\s*Context from my IDE setup\b.*$", re.IGNORECASE)


def parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def parse_date_from_path(path: Path) -> tuple[int, int, int] | None:
    parts = path.parts
    # Expect .../sessions/YYYY/MM/DD/rollout-*.jsonl
    if len(parts) < 4:
        return None
    try:
        year = int(parts[-4])
        month = int(parts[-3])
        day = int(parts[-2])
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


def safe_json_loads(line: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(line), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _trim_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _parse_files_mentioned(lines: list[str]) -> list[str]:
    files: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        entry: str | None = None
        if line.startswith("#"):
            entry = line.lstrip("#").strip()
        elif line.startswith(("- ", "* ")):
            entry = line[2:].strip()

        if not entry:
            continue

        if ":" in entry:
            _, right = entry.split(":", 1)
            entry = right.strip() or entry

        files.append(entry)

    seen: set[str] = set()
    unique: list[str] = []
    for item in files:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _strip_agents_instructions(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if _AGENTS_HEADER_RE.match(line.strip()):
            idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
            if idx < len(lines) and lines[idx].strip().lower() == "<instructions>":
                idx += 1
                while idx < len(lines) and lines[idx].strip().lower() != "</instructions>":
                    idx += 1
                if idx < len(lines):
                    idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
            continue
        output.append(line)
        idx += 1
    return "\n".join(output)


def _cleanup_ide_context_user_message(text: str, include_files: bool) -> str:
    lines = text.splitlines()
    request_idx: int | None = None
    for idx, line in enumerate(lines):
        if _REQUEST_HEADING_RE.match(line.strip()):
            request_idx = idx
            break
    if request_idx is None:
        return text

    files: list[str] = []
    if include_files:
        files_heading_idx: int | None = None
        for idx, line in enumerate(lines[:request_idx]):
            if _FILES_MENTIONED_HEADING_RE.match(line.strip()):
                files_heading_idx = idx
                break
        if files_heading_idx is not None:
            files = _parse_files_mentioned(lines[files_heading_idx + 1 : request_idx])

    request_lines = _trim_blank_lines(lines[request_idx + 1 :])
    request_text = "\n".join(request_lines).rstrip()

    output_lines: list[str] = []
    if request_text:
        output_lines.append(request_text)
    if include_files and files:
        if output_lines:
            output_lines.append("")
        rendered = ", ".join(f"`{item}`" for item in files)
        output_lines.append(f"Files: {rendered}")

    return "\n".join(output_lines).rstrip() or text


def clean_user_message(text: str, *, include_files: bool = True) -> str | None:
    cleaned = text
    stripped = cleaned.strip()
    if stripped.startswith("<environment_context>") and "</environment_context>" not in stripped:
        return None
    cleaned = _ENVIRONMENT_CONTEXT_BLOCK_RE.sub("", cleaned).strip()
    if not cleaned:
        return None
    cleaned = _strip_agents_instructions(cleaned).strip()
    if not cleaned:
        return None

    lines = cleaned.splitlines()
    has_context = any(_IDE_CONTEXT_HEADER_RE.match(line.strip()) for line in lines)
    has_request = any(_REQUEST_HEADING_RE.match(line.strip()) for line in lines)
    if has_context and not has_request:
        return None

    cleaned = _cleanup_ide_context_user_message(cleaned, include_files=include_files).strip()
    if not cleaned:
        return None
    return cleaned
