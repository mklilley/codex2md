from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class MessageEvent:
    role: str
    text: str
    source: str
    timestamp: datetime | None
    line_num: int
    kind: str = field(default="message", init=False)


@dataclass
class ToolEvent:
    name: str | None
    arguments: str | None
    call_id: str | None
    output: str | None
    timestamp: datetime | None
    line_num: int
    output_timestamp: datetime | None = None
    output_line: int | None = None
    kind: str = field(default="tool", init=False)


@dataclass
class ReasoningEvent:
    summary: list[str]
    timestamp: datetime | None
    line_num: int
    kind: str = field(default="reasoning", init=False)


@dataclass
class MalformedEvent:
    description: str
    timestamp: datetime | None
    line_num: int
    kind: str = field(default="malformed", init=False)


Event = MessageEvent | ToolEvent | ReasoningEvent | MalformedEvent


@dataclass
class Session:
    path: Path
    session_id: str | None
    started_at: datetime | None
    cwd: str | None
    repo_url: str | None
    branch: str | None
    commit_hash: str | None
    cli_version: str | None
    originator: str | None
    ghost_commit: str | None
    events: list[Event]
    parse_warnings: list[str]


@dataclass
class SessionInfo:
    path: Path
    year: int | None
    month: int | None
    day: int | None
    session_id: str | None
    started_at: datetime | None
    cwd: str | None
    repo_url: str | None
    branch: str | None
    preview: str | None
    warnings_count: int
    originator: str | None
