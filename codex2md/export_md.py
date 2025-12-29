from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .models import MalformedEvent, MessageEvent, ReasoningEvent, Session, ToolEvent
from .utils import build_export_basename, clean_user_message, format_timestamp


@dataclass
class ExportOptions:
    include_tools: bool = False
    include_reasoning: bool = True
    include_diagnostics: bool = False
    redact_paths: bool = False


def _redact_text(text: str, home: Path) -> str:
    if not text:
        return text
    return text.replace(str(home), "~")


def _format_header(
    session: Session,
    options: ExportOptions,
    title_override: str | None = None,
) -> list[str]:
    lines: list[str] = []
    session_label = title_override or build_export_basename(session.started_at, session.cwd)
    lines.append(f"# {session_label}")
    lines.append("")

    started = format_timestamp(session.started_at)
    if started:
        lines.append(f"- Started: {started}")
    if session.cwd:
        cwd = session.cwd
        if options.redact_paths:
            cwd = _redact_text(cwd, Path.home())
        lines.append(f"- Folder: {cwd}")
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

    source_path = str(session.path)
    if options.redact_paths:
        source_path = _redact_text(source_path, Path.home())
    lines.append(f"- Source: {source_path}")
    if options.include_diagnostics and session.parse_warnings:
        lines.append(f"- Warnings: {len(session.parse_warnings)}")
    lines.append("")
    return lines


_REASONING_SPLIT_RE = re.compile(r"^([^:]{1,80})\s*:\s*(.+)$")


def _format_message(event: MessageEvent, options: ExportOptions) -> list[str] | None:
    header = event.role.title()
    text = event.text
    if event.role == "user":
        cleaned = clean_user_message(text, include_files=True)
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


def session_to_markdown(
    session: Session,
    options: ExportOptions,
    title_override: str | None = None,
) -> str:
    lines: list[str] = []
    lines.extend(_format_header(session, options, title_override=title_override))

    current_message_role: str | None = None
    pending_reasoning: list[str] = []
    pending_reasoning_for_next_assistant: list[str] = []

    def flush_reasoning_block() -> None:
        nonlocal pending_reasoning
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

        if isinstance(event, ToolEvent):
            if options.include_tools:
                lines.extend(_format_tool_event(event, options))
            continue
        if isinstance(event, MalformedEvent):
            if options.include_diagnostics:
                lines.extend(_format_malformed(event))
            continue

    if current_message_role == "assistant":
        flush_reasoning_block()

    return "\n".join(lines).rstrip() + "\n"


def export_session_markdown(session: Session, options: ExportOptions, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = session_to_markdown(session, options, title_override=out_path.stem)
    out_path.write_text(content, encoding="utf-8")
    return out_path
