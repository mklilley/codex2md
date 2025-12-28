from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import MalformedEvent, MessageEvent, ReasoningEvent, Session, ToolEvent
from .utils import format_timestamp


@dataclass
class ExportOptions:
    include_tools: bool = True
    messages_only: bool = False
    include_reasoning: bool = False
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


def _format_message(event: MessageEvent, options: ExportOptions) -> list[str]:
    header = event.role.title()
    text = event.text
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


def _format_reasoning(event: ReasoningEvent) -> list[str]:
    lines: list[str] = ["<details>", "<summary>Reasoning summary</summary>", ""]
    for item in event.summary:
        lines.append(f"- {item}")
    lines.append("</details>")
    lines.append("")
    return lines


def _format_malformed(event: MalformedEvent) -> list[str]:
    return [f"> [Skipped malformed event: {event.description}]", ""]


def session_to_markdown(session: Session, options: ExportOptions) -> str:
    lines: list[str] = []
    lines.extend(_format_header(session, options))

    for event in session.events:
        if isinstance(event, MessageEvent):
            lines.extend(_format_message(event, options))
            continue
        if options.messages_only:
            continue
        if isinstance(event, ToolEvent):
            if options.include_tools:
                lines.extend(_format_tool_event(event, options))
            continue
        if isinstance(event, ReasoningEvent):
            if options.include_reasoning:
                lines.extend(_format_reasoning(event))
            continue
        if isinstance(event, MalformedEvent):
            lines.extend(_format_malformed(event))
            continue

    return "\n".join(lines).rstrip() + "\n"


def export_session_markdown(session: Session, options: ExportOptions, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = session_to_markdown(session, options)
    out_path.write_text(content, encoding="utf-8")
    return out_path
