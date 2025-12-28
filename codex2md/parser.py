from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
from typing import Any

from .config import configure_logging
from .models import (
    MalformedEvent,
    MessageEvent,
    ReasoningEvent,
    Session,
    SessionInfo,
    ToolEvent,
)
from .utils import coerce_text, format_timestamp, parse_date_from_path, parse_timestamp, safe_json_loads

logger = configure_logging()


@dataclass
class _FastMeta:
    session_id: str | None = None
    started_at: datetime | None = None
    cwd: str | None = None
    repo_url: str | None = None
    branch: str | None = None
    originator: str | None = None
    cli_version: str | None = None


def _unwrap_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and "type" not in payload and "payload" in payload:
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return nested
    return payload


def _normalize_content_blocks(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if "text" in content:
            return coerce_text(content.get("text"))
        if "content" in content:
            return _normalize_content_blocks(content.get("content"))
        return None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if text is None and "content" in block:
                text = _normalize_content_blocks(block.get("content"))
            if text is None:
                continue
            parts.append(str(text))
        if parts:
            return "".join(parts)
    return None


def _extract_message_text(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if content is None:
        content = payload.get("text")
    return _normalize_content_blocks(content)


def _extract_reasoning_summary(payload: dict[str, Any]) -> list[str]:
    summary_blocks = payload.get("summary")
    if isinstance(summary_blocks, list):
        summaries: list[str] = []
        for block in summary_blocks:
            if isinstance(block, dict):
                text = block.get("text")
                if text is None:
                    text = block.get("summary_text")
                if text is not None:
                    summaries.append(str(text))
            elif isinstance(block, str):
                summaries.append(block)
        return summaries
    text = payload.get("text")
    if isinstance(text, str):
        return [text]
    return []


def _extract_event_user_message(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if message is None:
        message = payload.get("text")
    if isinstance(message, dict):
        return _normalize_content_blocks(message.get("content"))
    if isinstance(message, list):
        return _normalize_content_blocks(message)
    if isinstance(message, str):
        return message
    return None


def _format_jsonish(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return value
            return json.dumps(parsed, indent=2, ensure_ascii=True)
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=True)
    return str(value)


def _make_preview(text: str, limit: int = 120) -> str:
    trimmed = " ".join(text.strip().split())
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[: limit - 3] + "..."


def extract_metadata_and_preview_fast(path: Path, max_lines: int = 500) -> tuple[_FastMeta, str | None, int]:
    meta = _FastMeta()
    preview: str | None = None
    warnings: list[str] = []
    seen_message_texts: set[str] = set()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_num, line in enumerate(handle, start=1):
                if line_num > max_lines:
                    break
                record, error = safe_json_loads(line)
                if error:
                    warnings.append(f"line {line_num}: invalid json")
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                payload = _unwrap_payload(record.get("payload"))
                if record_type == "session_meta" and isinstance(payload, dict):
                    meta.session_id = coerce_text(payload.get("id"))
                    meta.started_at = parse_timestamp(payload.get("timestamp"))
                    meta.cwd = coerce_text(payload.get("cwd"))
                    meta.originator = coerce_text(payload.get("originator"))
                    meta.cli_version = coerce_text(payload.get("cli_version"))
                    git = payload.get("git")
                    if isinstance(git, dict):
                        meta.repo_url = coerce_text(git.get("repository_url"))
                        meta.branch = coerce_text(git.get("branch"))
                elif record_type == "turn_context" and isinstance(payload, dict):
                    if meta.cwd is None:
                        meta.cwd = coerce_text(payload.get("cwd"))
                elif record_type == "response_item" and isinstance(payload, dict) and preview is None:
                    payload = _unwrap_payload(payload)
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        text = _extract_message_text(payload)
                        if text:
                            seen_message_texts.add(text)
                            preview = _make_preview(text)
                elif record_type == "event_msg" and isinstance(payload, dict) and preview is None:
                    if payload.get("type") == "user_message":
                        text = _extract_event_user_message(payload)
                        if text and text not in seen_message_texts:
                            preview = _make_preview(text)
    except OSError as exc:
        logger.warning("failed to read %s: %s", path, exc)
        warnings.append(f"failed to read file: {exc}")

    return meta, preview, len(warnings)


def build_session_info(path: Path) -> SessionInfo:
    meta, preview, warnings_count = extract_metadata_and_preview_fast(path)
    date_parts = parse_date_from_path(path)
    started_at = meta.started_at
    if started_at is None and date_parts:
        year, month, day = date_parts
        try:
            started_at = datetime(year, month, day)
        except ValueError:
            started_at = None

    year = date_parts[0] if date_parts else None
    month = date_parts[1] if date_parts else None
    day = date_parts[2] if date_parts else None

    return SessionInfo(
        path=path,
        year=year,
        month=month,
        day=day,
        session_id=meta.session_id,
        started_at=started_at,
        cwd=meta.cwd,
        repo_url=meta.repo_url,
        branch=meta.branch,
        preview=preview,
        warnings_count=warnings_count,
        originator=meta.originator,
    )


def parse_session(path: Path) -> Session:
    warnings: list[str] = []
    events: list[Any] = []
    tool_calls: dict[str, ToolEvent] = {}
    session_id: str | None = None
    started_at: datetime | None = None
    cwd: str | None = None
    repo_url: str | None = None
    branch: str | None = None
    commit_hash: str | None = None
    cli_version: str | None = None
    originator: str | None = None
    ghost_commit: str | None = None
    seen_message_texts: set[str] = set()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_num, line in enumerate(handle, start=1):
                record, error = safe_json_loads(line)
                if error:
                    warnings.append(f"line {line_num}: invalid json")
                    events.append(
                        MalformedEvent(
                            description=f"Invalid JSON at line {line_num}",
                            timestamp=None,
                            line_num=line_num,
                        )
                    )
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                timestamp = parse_timestamp(record.get("timestamp"))
                payload = _unwrap_payload(record.get("payload"))

                if record_type == "session_meta" and isinstance(payload, dict):
                    session_id = coerce_text(payload.get("id"))
                    started_at = parse_timestamp(payload.get("timestamp"))
                    cwd = coerce_text(payload.get("cwd"))
                    originator = coerce_text(payload.get("originator"))
                    cli_version = coerce_text(payload.get("cli_version"))
                    git = payload.get("git")
                    if isinstance(git, dict):
                        repo_url = coerce_text(git.get("repository_url"))
                        branch = coerce_text(git.get("branch"))
                        commit_hash = coerce_text(git.get("commit_hash"))
                        if commit_hash is None:
                            commit_hash = coerce_text(git.get("commit"))
                    continue

                if record_type == "turn_context" and isinstance(payload, dict):
                    if cwd is None:
                        cwd = coerce_text(payload.get("cwd"))
                    continue

                if record_type == "response_item":
                    if not isinstance(payload, dict):
                        warnings.append(f"line {line_num}: response_item payload not a dict")
                        events.append(
                            MalformedEvent(
                                description=f"Skipped malformed response_item at line {line_num}",
                                timestamp=timestamp,
                                line_num=line_num,
                            )
                        )
                        continue
                    payload = _unwrap_payload(payload)
                    if not isinstance(payload, dict):
                        warnings.append(f"line {line_num}: response_item payload not a dict")
                        events.append(
                            MalformedEvent(
                                description=f"Skipped malformed response_item at line {line_num}",
                                timestamp=timestamp,
                                line_num=line_num,
                            )
                        )
                        continue
                    item_type = payload.get("type")
                    if item_type == "message":
                        role = coerce_text(payload.get("role")) or "unknown"
                        text = _extract_message_text(payload)
                        if text:
                            if role == "user":
                                seen_message_texts.add(text)
                            events.append(
                                MessageEvent(
                                    role=role,
                                    text=text,
                                    source="response_item",
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                        else:
                            warnings.append(f"line {line_num}: message without text")
                            events.append(
                                MalformedEvent(
                                    description=f"Skipped empty message at line {line_num}",
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                    elif item_type == "function_call":
                        call_id = coerce_text(payload.get("call_id"))
                        name = coerce_text(payload.get("name"))
                        arguments = _format_jsonish(payload.get("arguments"))
                        tool_event = ToolEvent(
                            name=name,
                            arguments=arguments,
                            call_id=call_id,
                            output=None,
                            timestamp=timestamp,
                            line_num=line_num,
                        )
                        events.append(tool_event)
                        if call_id:
                            tool_calls[call_id] = tool_event
                    elif item_type == "function_call_output":
                        call_id = coerce_text(payload.get("call_id"))
                        output = _format_jsonish(payload.get("output"))
                        if call_id and call_id in tool_calls:
                            tool_event = tool_calls[call_id]
                            if tool_event.output:
                                tool_event.output += "\n\n---\n\n" + (output or "")
                            else:
                                tool_event.output = output
                            tool_event.output_timestamp = timestamp
                            tool_event.output_line = line_num
                        else:
                            warnings.append(f"line {line_num}: tool output without call")
                            events.append(
                                ToolEvent(
                                    name=None,
                                    arguments=None,
                                    call_id=call_id,
                                    output=output,
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                    elif item_type == "reasoning":
                        summary = _extract_reasoning_summary(payload)
                        if summary:
                            events.append(
                                ReasoningEvent(
                                    summary=summary,
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                    elif item_type == "ghost_snapshot":
                        ghost_commit = coerce_text(payload.get("ghost_commit"))
                    else:
                        # Ignore unknown response item types.
                        continue
                    continue

                if record_type == "event_msg":
                    if not isinstance(payload, dict):
                        continue
                    payload_type = payload.get("type")
                    if payload_type == "user_message":
                        text = _extract_event_user_message(payload)
                        if text and text not in seen_message_texts:
                            events.append(
                                MessageEvent(
                                    role="user",
                                    text=text,
                                    source="event_msg",
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                    elif payload_type == "agent_reasoning":
                        text = payload.get("text")
                        if isinstance(text, str):
                            events.append(
                                ReasoningEvent(
                                    summary=[text],
                                    timestamp=timestamp,
                                    line_num=line_num,
                                )
                            )
                        elif isinstance(text, list):
                            summary = [str(item) for item in text if item]
                            if summary:
                                events.append(
                                    ReasoningEvent(
                                        summary=summary,
                                        timestamp=timestamp,
                                        line_num=line_num,
                                    )
                                )
                    continue
    except OSError as exc:
        logger.warning("failed to read %s: %s", path, exc)
        warnings.append(f"failed to read file: {exc}")

    if session_id is None:
        warnings.append("session_meta missing")
    if started_at is None:
        date_parts = parse_date_from_path(path)
        if date_parts:
            try:
                started_at = datetime(*date_parts)
            except ValueError:
                started_at = None

    return Session(
        path=path,
        session_id=session_id,
        started_at=started_at,
        cwd=cwd,
        repo_url=repo_url,
        branch=branch,
        commit_hash=commit_hash,
        cli_version=cli_version,
        originator=originator,
        ghost_commit=ghost_commit,
        events=events,
        parse_warnings=warnings,
    )
