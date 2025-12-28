from __future__ import annotations

from dataclasses import dataclass
import calendar
import os
from pathlib import Path
import subprocess
from typing import Iterable

from .config import Settings, configure_logging
from .discover import discover_sessions
from .export_md import ExportOptions, export_session_markdown
from .filters import filter_sessions, sort_sessions
from .models import Session, SessionInfo
from .parser import parse_session
from .utils import format_timestamp

logger = configure_logging()



@dataclass
class TuiState:
    sessions: list[SessionInfo]
    settings: Settings


def run_tui() -> int:
    settings = Settings()
    sessions = discover_sessions()
    state = TuiState(sessions=sessions, settings=settings)

    while True:
        try:
            result = _main_menu(state)
        except Exception:
            logger.exception("unexpected TUI error")
            print("Something went wrong; returning to main menu.")
            continue
        if result == "quit":
            return 0


def _main_menu(state: TuiState) -> str:
    while True:
        _print_header(["Main"])
        print(f"Sessions found: {len(state.sessions)}")
        print("1. Browse by date")
        print("2. Browse by working directory")
        print("3. Search")
        print("4. Export last N sessions")
        print("5. Settings")
        print("6. Quit")
        choice = _prompt_choice(6)
        if choice == "quit":
            return "quit"
        if choice == "back":
            continue
        if choice == 1:
            result = _browse_by_date(state)
        elif choice == 2:
            result = _browse_by_cwd(state)
        elif choice == 3:
            result = _search_sessions(state)
        elif choice == 4:
            result = _export_last_n(state)
        elif choice == 5:
            result = _settings_menu(state)
        elif choice == 6:
            return "quit"
        else:
            result = None
        if result == "quit":
            return "quit"


def _browse_by_date(state: TuiState) -> str | None:
    if not state.sessions:
        _print_header(["Date"])
        print("No sessions found.")
        return "back"
    year_groups: dict[str, list[SessionInfo]] = {}
    for session in state.sessions:
        if session.year is None:
            key = "Unknown"
        else:
            key = str(session.year)
        year_groups.setdefault(key, []).append(session)

    years = sorted(year_groups.keys(), key=lambda y: (y == "Unknown", y))
    while True:
        _print_header(["Date"])
        for idx, year in enumerate(years, start=1):
            print(f"{idx}. {year} ({len(year_groups[year])})")
        choice = _prompt_choice(len(years))
        if choice in ("back", "quit"):
            return choice
        selected = years[choice - 1]
        sessions = year_groups[selected]
        if selected == "Unknown":
            result = _session_list_menu(state, sessions, ["Date", "Unknown"])
        else:
            result = _browse_by_month(state, int(selected), sessions)
        if result == "quit":
            return "quit"


def _browse_by_month(state: TuiState, year: int, sessions: list[SessionInfo]) -> str | None:
    month_groups: dict[int, list[SessionInfo]] = {}
    for session in sessions:
        if session.month is None:
            continue
        month_groups.setdefault(session.month, []).append(session)
    months = sorted(month_groups.keys())
    while True:
        _print_header(["Date", str(year)])
        if not months:
            print("No sessions for this year.")
            return "back"
        for idx, month in enumerate(months, start=1):
            name = calendar.month_name[month]
            print(f"{idx}. {name} ({len(month_groups[month])})")
        choice = _prompt_choice(len(months))
        if choice in ("back", "quit"):
            return choice
        month = months[choice - 1]
        name = calendar.month_name[month]
        result = _session_list_menu(state, month_groups[month], ["Date", str(year), name])
        if result == "quit":
            return "quit"


def _browse_by_cwd(state: TuiState) -> str | None:
    if not state.sessions:
        _print_header(["Working directory"])
        print("No sessions found.")
        return "back"
    cwd_groups: dict[str, list[SessionInfo]] = {}
    for session in state.sessions:
        key = session.cwd or "Unknown"
        cwd_groups.setdefault(key, []).append(session)
    cwds = sorted(cwd_groups.keys(), key=lambda value: value.lower())

    while True:
        _print_header(["Working directory"])
        for idx, cwd in enumerate(cwds, start=1):
            label = _shorten_text(cwd, 60)
            count = len(cwd_groups[cwd])
            print(f"{idx}. {label} ({count})")
        choice = _prompt_choice(len(cwds))
        if choice in ("back", "quit"):
            return choice
        cwd = cwds[choice - 1]
        result = _session_list_menu(state, cwd_groups[cwd], ["Working directory", cwd])
        if result == "quit":
            return "quit"


def _search_sessions(state: TuiState) -> str | None:
    if not state.sessions:
        _print_header(["Search"])
        print("No sessions found.")
        return "back"
    while True:
        _print_header(["Search"])
        _print_nav_hint()
        query = input("Search term (or 'b' to go back): ").strip()
        if not query:
            print("Enter a search term or 'b' to go back.")
            continue
        if query.lower() == "b":
            return "back"
        if query.lower() == "q":
            return "quit"
        results = filter_sessions(state.sessions, query=query)
        if not results:
            print("No matches. Try another query.")
            continue
        result = _session_list_menu(state, results, ["Search", query])
        if result == "quit":
            return "quit"


def _export_last_n(state: TuiState) -> str | None:
    while True:
        _print_header(["Export", "Last N"])
        _print_nav_hint()
        raw = input("How many sessions to export? ").strip()
        if raw.lower() in ("b", "back"):
            return "back"
        if raw.lower() in ("q", "quit"):
            return "quit"
        if not raw.isdigit():
            print("Enter a number.")
            continue
        count = int(raw)
        if count <= 0:
            print("Enter a positive number.")
            continue
        sessions = sort_sessions(state.sessions)[:count]
        if not sessions:
            print("No sessions available.")
            return "back"
        out_dir = _prompt_output_dir(state.settings)
        if out_dir in (None, "back"):
            return "back"
        if out_dir == "quit":
            return "quit"
        out_dir_path = Path(out_dir)
        options = ExportOptions(
            include_tools=state.settings.include_tools,
            include_reasoning=state.settings.include_reasoning,
            include_diagnostics=state.settings.include_diagnostics,
            redact_paths=state.settings.redact_paths,
        )
        exported = 0
        for session_info in sessions:
            session = parse_session(session_info.path)
            out_path = out_dir_path / _make_export_filename(session)
            export_session_markdown(session, options, out_path)
            exported += 1
        print(f"Exported {exported} sessions to {out_dir_path}")
        return "back"


def _settings_menu(state: TuiState) -> str | None:
    settings = state.settings
    while True:
        _print_header(["Settings"])
        print(f"1. Include tools: {settings.include_tools}")
        print(f"2. Include reasoning summary: {settings.include_reasoning}")
        print(f"3. Include diagnostics (warnings + skipped events): {settings.include_diagnostics}")
        print(f"4. Redact paths: {settings.redact_paths}")
        print(f"5. Default output directory: {settings.output_dir or Path.cwd()}")
        print("6. Back")
        choice = _prompt_choice(6)
        if choice in ("back", "quit"):
            return choice
        if choice == 1:
            settings.include_tools = not settings.include_tools
        elif choice == 2:
            settings.include_reasoning = not settings.include_reasoning
        elif choice == 3:
            settings.include_diagnostics = not settings.include_diagnostics
        elif choice == 4:
            settings.redact_paths = not settings.redact_paths
        elif choice == 5:
            result = _prompt_output_dir(settings)
            if result == "quit":
                return "quit"
        elif choice == 6:
            return "back"


def _session_list_menu(state: TuiState, sessions: Iterable[SessionInfo], breadcrumb: list[str]) -> str | None:
    session_list = sort_sessions(list(sessions))
    while True:
        _print_header(breadcrumb)
        if not session_list:
            print("No sessions found.")
            return "back"
        for idx, session in enumerate(session_list, start=1):
            print(f"{idx}. {_format_session_line(session)}")
        choice = _prompt_choice(len(session_list))
        if choice in ("back", "quit"):
            return choice
        selected = session_list[choice - 1]
        label = selected.session_id or selected.path.name
        result = _session_action_menu(state, selected, breadcrumb + [label])
        if result == "quit":
            return "quit"


def _session_action_menu(state: TuiState, session_info: SessionInfo, breadcrumb: list[str]) -> str | None:
    while True:
        _print_header(breadcrumb)
        print("1. Export Markdown (default)")
        print("2. Export Markdown (with tools)")
        print("3. Export Markdown (include diagnostics)")
        print("4. Open source JSONL in editor")
        print("5. Show metadata")
        print("6. Back")
        choice = _prompt_choice(6)
        if choice in ("back", "quit"):
            return choice
        if choice == 6:
            return "back"
        if choice in (1, 2, 3):
            session = parse_session(session_info.path)
            options = _resolve_export_options(state.settings, choice)
            out_dir = _prompt_output_dir(state.settings)
            if out_dir in (None, "back"):
                continue
            if out_dir == "quit":
                return "quit"
            out_dir_path = Path(out_dir)
            out_path = out_dir_path / _make_export_filename(session)
            if out_path.exists() and not _confirm_overwrite(out_path):
                continue
            export_session_markdown(session, options, out_path)
            print(f"Exported to {out_path}")
            continue
        if choice == 4:
            _open_in_editor(session_info.path)
            continue
        if choice == 5:
            session = parse_session(session_info.path)
            _print_session_metadata(session)
            continue


def _resolve_export_options(settings: Settings, choice: int) -> ExportOptions:
    if choice == 2:
        return ExportOptions(
            include_tools=True,
            include_reasoning=settings.include_reasoning,
            include_diagnostics=settings.include_diagnostics,
            redact_paths=settings.redact_paths,
        )
    if choice == 3:
        return ExportOptions(
            include_tools=settings.include_tools,
            include_reasoning=settings.include_reasoning,
            include_diagnostics=True,
            redact_paths=settings.redact_paths,
        )
    return ExportOptions(
        include_tools=settings.include_tools,
        include_reasoning=settings.include_reasoning,
        include_diagnostics=settings.include_diagnostics,
        redact_paths=settings.redact_paths,
    )


def _make_export_filename(session: Session) -> str:
    label = session.session_id or session.path.stem
    safe = "".join(ch for ch in label if ch.isalnum() or ch in ("-", "_"))
    if not safe:
        safe = "session"
    return f"{safe}.md"


def _prompt_output_dir(settings: Settings) -> Path | str | None:
    default_dir = settings.output_dir or Path.cwd()
    raw = input(f"Output directory [{default_dir}]: ").strip()
    if raw.lower() in ("b", "back"):
        return "back"
    if raw.lower() in ("q", "quit"):
        return "quit"
    if raw:
        chosen = Path(raw).expanduser()
        settings.output_dir = chosen
        return chosen
    return default_dir


def _confirm_overwrite(path: Path) -> bool:
    while True:
        raw = input(f"{path} exists. Overwrite? (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def _open_in_editor(path: Path) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        editor = "vi"
    try:
        subprocess.run([editor, str(path)], check=False)
    except Exception as exc:
        logger.warning("failed to open editor: %s", exc)
        print(f"Failed to open editor: {exc}")


def _print_session_metadata(session: Session) -> None:
    print(f"Session: {session.session_id or session.path.name}")
    print(f"Started: {format_timestamp(session.started_at) or 'unknown'}")
    print(f"CWD: {session.cwd or 'unknown'}")
    if session.repo_url:
        print(f"Repo: {session.repo_url}")
    if session.branch:
        print(f"Branch: {session.branch}")
    if session.commit_hash:
        print(f"Commit: {session.commit_hash}")
    if session.originator:
        print(f"Originator: {session.originator}")
    if session.cli_version:
        print(f"CLI version: {session.cli_version}")
    if session.ghost_commit:
        print(f"Ghost commit: {session.ghost_commit}")
    if session.parse_warnings:
        print("Warnings:")
        for warning in session.parse_warnings[:10]:
            print(f"- {warning}")
        if len(session.parse_warnings) > 10:
            print("- ...")
    input("Press Enter to continue...")


def _prompt_choice(max_index: int) -> int | str:
    _print_nav_hint()
    while True:
        raw = input("Select: ").strip()
        if not raw:
            print("Enter a number, 'b' to go back, or 'q' to quit.")
            continue
        lowered = raw.lower()
        if lowered in ("b", "back"):
            return "back"
        if lowered in ("q", "quit"):
            return "quit"
        if raw.isdigit():
            value = int(raw)
            if 1 <= value <= max_index:
                return value
        print("Invalid input. Enter a valid option.")


def _print_header(breadcrumb: list[str]) -> None:
    print("\n" + " > ".join(breadcrumb))


def _print_nav_hint() -> None:
    print("")
    print("b = back | q = quit")


def _format_session_line(session: SessionInfo) -> str:
    timestamp = format_timestamp(session.started_at) or "unknown"
    cwd = _shorten_text(session.cwd or "unknown", 60)
    preview = session.preview or ""
    warning = f" !{session.warnings_count}" if session.warnings_count else ""
    return f"{timestamp} | {cwd} | {preview}{warning}"


def _shorten_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
