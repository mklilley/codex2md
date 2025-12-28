from __future__ import annotations

import argparse
from pathlib import Path

from .config import configure_logging
from .discover import discover_sessions
from .export_md import ExportOptions, export_session_markdown
from .filters import filter_sessions, sort_sessions
from .models import SessionInfo
from .parser import parse_session
from .tui import run_tui
from .utils import format_timestamp

logger = configure_logging()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex2md", description="Export Codex sessions to Markdown")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List sessions")
    list_parser.add_argument("--year", type=int, help="Filter by year")
    list_parser.add_argument("--month", type=int, help="Filter by month")
    list_parser.add_argument("--cwd", type=str, help="Filter by working directory (substring)")
    list_parser.add_argument("--repo", type=str, help="Filter by repo URL or cwd (substring)")
    list_parser.add_argument("--query", type=str, help="Search term")
    list_parser.add_argument("--limit", type=int, default=50, help="Limit results")

    export_parser = subparsers.add_parser("export", help="Export sessions to Markdown")
    export_parser.add_argument("--file", type=str, help="Path to rollout JSONL")
    export_parser.add_argument("--session-id", type=str, help="Session id to export")
    export_parser.add_argument("--year", type=int, help="Filter by year")
    export_parser.add_argument("--month", type=int, help="Filter by month")
    export_parser.add_argument("--cwd", type=str, help="Filter by working directory (substring)")
    export_parser.add_argument("--repo", type=str, help="Filter by repo URL or cwd (substring)")
    export_parser.add_argument("--query", type=str, help="Search term")
    export_parser.add_argument("--limit", type=int, help="Limit sessions")
    export_parser.add_argument("--out", type=str, help="Output Markdown file")
    export_parser.add_argument("--out-dir", type=str, help="Output directory for multiple sessions")
    export_parser.add_argument(
        "--include-tools",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include tool calls and outputs",
    )
    export_parser.add_argument("--messages-only", action="store_true", help="Export messages only")
    export_parser.add_argument(
        "--include-reasoning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include reasoning summary",
    )
    export_parser.add_argument("--redact-paths", action="store_true", help="Redact home paths")

    subparsers.add_parser("tui", help="Launch interactive menu")

    args = parser.parse_args(argv)

    if args.command in (None, "tui"):
        return run_tui()
    if args.command == "list":
        return _list_cmd(args)
    if args.command == "export":
        return _export_cmd(args)

    parser.print_help()
    return 0


def _list_cmd(args: argparse.Namespace) -> int:
    sessions = discover_sessions()
    results = filter_sessions(
        sessions,
        year=args.year,
        month=args.month,
        cwd=args.cwd,
        repo=args.repo,
        query=args.query,
    )
    results = sort_sessions(results)
    if args.limit:
        results = results[: args.limit]

    if not results:
        print("No sessions found.")
        return 0

    for session in results:
        print(_format_session_line(session))
    return 0


def _export_cmd(args: argparse.Namespace) -> int:
    targets: list[Path] = []

    if args.file:
        targets = [Path(args.file).expanduser()]
    else:
        sessions = discover_sessions()
        if args.session_id:
            matches = [s for s in sessions if s.session_id == args.session_id]
            targets = [s.path for s in matches]
        else:
            matches = filter_sessions(
                sessions,
                year=args.year,
                month=args.month,
                cwd=args.cwd,
                repo=args.repo,
                query=args.query,
            )
            if args.limit:
                matches = matches[: args.limit]
            targets = [s.path for s in matches]

    if not targets:
        print("No matching sessions to export.")
        return 1

    options = ExportOptions(
        include_tools=args.include_tools,
        messages_only=args.messages_only,
        include_reasoning=args.include_reasoning,
        redact_paths=args.redact_paths,
    )

    out_path = Path(args.out).expanduser() if args.out else None
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None

    if out_path and len(targets) > 1:
        print("--out can only be used with a single session.")
        return 2

    if not out_dir:
        out_dir = Path.cwd()

    exported = 0
    for path in targets:
        session = parse_session(path)
        if out_path:
            target_path = out_path
        else:
            target_path = out_dir / _make_export_filename(session)
        export_session_markdown(session, options, target_path)
        exported += 1
        print(f"Exported {path} -> {target_path}")

    return 0


def _format_session_line(session: SessionInfo) -> str:
    timestamp = format_timestamp(session.started_at) or "unknown"
    label = session.session_id or session.path.name
    cwd = session.cwd or "unknown"
    preview = session.preview or ""
    warning = f" !{session.warnings_count}" if session.warnings_count else ""
    return f"{timestamp} | {label} | {cwd} | {preview}{warning}"


def _make_export_filename(session) -> str:
    label = session.session_id or session.path.stem
    safe = "".join(ch for ch in label if ch.isalnum() or ch in ("-", "_"))
    if not safe:
        safe = "session"
    return f"{safe}.md"


if __name__ == "__main__":
    raise SystemExit(main())
