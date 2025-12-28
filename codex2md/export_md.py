from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .models import MalformedEvent, MessageEvent, ReasoningEvent, Session, ToolEvent
from .utils import format_timestamp


@dataclass
class ExportOptions:
    include_tools: bool = False
    messages_only: bool = False
    include_reasoning: bool = True
    redact_paths: bool = False


def _redact_text(text: str, home: Path) -> str:
    if not text:
        return text
    return text.replace(str(home), "~")


def _format_header(session: Session, options: ExportOptions) -> list[str]:
    lines: list[str] = []
    session_label = session.session_id or session.path.name
    lines.append(f"# Codex session {session_label}")
    lines.append("")

    started = format_timestamp(session.started_at)
    if started:
        lines.append(f"- Started: {started}")
    if session.cwd:
        cwd = session.cwd
        if options.redact_paths:
            cwd = _redact_text(cwd, Path.home())
        lines.append(f"- CWD: {cwd}")
    if session.repo_url:
        repo = session.repo_url
        if options.redact_paths:
            repo = _redact_text(repo, Path.home())
        if session.branch:
            lines.append(f"- Repo: {repo} (branch: {session.branch})")
        else:
            lines.append(f"- Repo: {repo}")
    if session.commit_hash:
        lines.append(f"- Commit: {session.commit_hash}")
    if session.originator:
        lines.append(f"- Originator: {session.originator}")
    if session.cli_version:
        lines.append(f"- CLI version: {session.cli_version}")
    if session.ghost_commit:
        lines.append(f"- Ghost commit: {session.ghost_commit}")

    source_path = str(session.path)
    if options.redact_paths:
        source_path = _redact_text(source_path, Path.home())
    lines.append(f"- Source: {source_path}")
    if session.parse_warnings:
        lines.append(f"- Warnings: {len(session.parse_warnings)}")
    lines.append("")
    return lines


_REQUEST_HEADING_RE = re.compile(r"^#{1,6}\s*My request for Codex\s*:?\s*$", re.IGNORECASE)
_FILES_MENTIONED_HEADING_RE = re.compile(r"^#{1,6}\s*Files mentioned by the user\s*:?\s*$", re.IGNORECASE)
_ENVIRONMENT_CONTEXT_BLOCK_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL | re.IGNORECASE)
_REASONING_SPLIT_RE = re.compile(r"^([^:]{1,80})\s*:\s*(.+)$")


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


def _cleanup_user_message(text: str) -> str | None:
    cleaned = text
    stripped = cleaned.strip()
    if stripped.startswith("<environment_context>") and "</environment_context>" not in stripped:
        return None
    cleaned = _ENVIRONMENT_CONTEXT_BLOCK_RE.sub("", cleaned).strip()
    if not cleaned:
        return None
    cleaned = _cleanup_ide_context_user_message(cleaned).strip()
    if not cleaned:
        return None
    return cleaned


def _cleanup_ide_context_user_message(text: str) -> str:
    lines = text.splitlines()
    request_idx: int | None = None
    for idx, line in enumerate(lines):
        if _REQUEST_HEADING_RE.match(line.strip()):
            request_idx = idx
            break
    if request_idx is None:
        return text

    files: list[str] = []
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
    if files:
        if output_lines:
            output_lines.append("")
        rendered = ", ".join(f"`{item}`" for item in files)
        output_lines.append(f"Files: {rendered}")

    return "\n".join(output_lines).rstrip() or text


def _format_message(event: MessageEvent, options: ExportOptions) -> list[str] | None:
    header = event.role.title()
    text = event.text
    if event.role == "user":
        cleaned = _cleanup_user_message(text)
        if cleaned is None:
            return None
        text = cleaned
    if options.redact_paths:
        text = _redact_text(text, Path.home())
    return [f"## {header}", text, ""]


def _format_tool_event(event: ToolEvent, options: ExportOptions) -> list[str]:
    lines: list[str] = []
    name = event.name or "unknown"
    lines.append(f"### Tool call: {name}")
    if event.arguments:
        args = event.arguments
        if options.redact_paths:
            args = _redact_text(args, Path.home())
        lang = "json" if args.lstrip().startswith(("{", "[")) else "text"
        lines.append(f"```{lang}")
        lines.append(args)
        lines.append("```")
    else:
        lines.append("```text")
        lines.append("[no arguments]")
        lines.append("```")

    if event.output is not None:
        output = event.output
        if options.redact_paths:
            output = _redact_text(output, Path.home())
        lines.append("")
        lines.append("### Tool output")
        lines.append("```text")
        lines.append(output)
        lines.append("```")
    lines.append("")
    return lines


def _dedupe_reasoning_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in items:
        cleaned = " ".join(str(raw).strip().split())
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique


def _format_reasoning_block(items: list[str]) -> list[str]:
    lines: list[str] = ["<details>", "<summary>Reasoning</summary>", ""]
    unique = _dedupe_reasoning_items(items)
    step_num = 1
    for item in unique:
        text = item
        if text.startswith(("- ", "* ")):
            text = text[2:].strip()
        match = _REASONING_SPLIT_RE.match(text)
        if match:
            title = match.group(1).strip().rstrip(":").strip()
            rest = match.group(2).strip()
            if title and rest:
                lines.append(f"- **{title}:** {rest}")
                continue
        lines.append(f"- **Step {step_num}:** {text}")
        step_num += 1
    lines.append("</details>")
    lines.append("")
    return lines


def _format_malformed(event: MalformedEvent) -> list[str]:
    return [f"> [Skipped malformed event: {event.description}]", ""]


def session_to_markdown(session: Session, options: ExportOptions) -> str:
    lines: list[str] = []
    lines.extend(_format_header(session, options))

    current_message_role: str | None = None
    pending_reasoning: list[str] = []
    pending_reasoning_for_next_assistant: list[str] = []

    def flush_reasoning_block() -> None:
        nonlocal pending_reasoning
        if options.messages_only:
            pending_reasoning = []
            return
        if not options.include_reasoning:
            pending_reasoning = []
            return
        if not pending_reasoning:
            return
        lines.extend(_format_reasoning_block(pending_reasoning))
        pending_reasoning = []

    for event in session.events:
        if isinstance(event, MessageEvent):
            if current_message_role == "assistant":
                flush_reasoning_block()
            current_message_role = event.role
            if event.role == "assistant" and pending_reasoning_for_next_assistant:
                pending_reasoning.extend(pending_reasoning_for_next_assistant)
                pending_reasoning_for_next_assistant = []
            formatted = _format_message(event, options)
            if formatted:
                lines.extend(formatted)
            continue

        if isinstance(event, ReasoningEvent):
            if options.include_reasoning:
                target = pending_reasoning if current_message_role == "assistant" else pending_reasoning_for_next_assistant
                target.extend(event.summary)
            continue

        if options.messages_only:
            continue
        if isinstance(event, ToolEvent):
            if options.include_tools:
                lines.extend(_format_tool_event(event, options))
            continue
        if isinstance(event, MalformedEvent):
            lines.extend(_format_malformed(event))
            continue

    if current_message_role == "assistant":
        flush_reasoning_block()

    return "\n".join(lines).rstrip() + "\n"


def export_session_markdown(session: Session, options: ExportOptions, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = session_to_markdown(session, options)
    out_path.write_text(content, encoding="utf-8")
    return out_path
