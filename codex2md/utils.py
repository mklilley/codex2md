from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


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
