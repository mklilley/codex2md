from __future__ import annotations

from dataclasses import dataclass
import calendar
import os
from pathlib import Path
import pydoc
from typing import Iterable, Sequence

from .config import Settings, configure_logging
from .discover import discover_sessions
from .export_md import ExportOptions, export_session_markdown, session_to_markdown
from .filters import filter_sessions, sort_sessions
from .models import Session, SessionInfo
from .parser import parse_session
from .utils import format_timestamp

logger = configure_logging()

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit
    from prompt_toolkit.widgets import Label, RadioList
    from prompt_toolkit.shortcuts import prompt

    HAS_PROMPT_TOOLKIT = True
except Exception:
    HAS_PROMPT_TOOLKIT = False



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
        options = [
            ("date", "Browse by date"),
            ("cwd", "Browse by working directory"),
            ("search", "Search"),
            ("export_last", "Export last N sessions"),
            ("settings", "Settings"),
            ("quit", "Quit"),
        ]
        choice = _prompt_choice(
            "Main",
            options,
            allow_back=False,
            allow_quit=True,
            header_lines=[f"Sessions found: {len(state.sessions)}"],
        )
        if choice == "quit":
            return "quit"
        if choice == "date":
            result = _browse_by_date(state)
        elif choice == "cwd":
            result = _browse_by_cwd(state)
        elif choice == "search":
            result = _search_sessions(state)
        elif choice == "export_last":
            result = _export_last_n(state)
        elif choice == "settings":
            result = _settings_menu(state)
        else:
            result = None
        if result == "quit":
            return "quit"


def _browse_by_date(state: TuiState) -> str | None:
    if not state.sessions:
        _show_message("Date", "No sessions found.")
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
        options = [(year, f"{year} ({len(year_groups[year])})") for year in years]
        choice = _prompt_choice("Date", options)
        if choice in ("back", "quit"):
            return choice
        selected = choice
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
        if not months:
            _show_message(f"Date > {year}", "No sessions for this year.")
            return "back"
        options = [
            (month, f"{calendar.month_name[month]} ({len(month_groups[month])})") for month in months
        ]
        choice = _prompt_choice(f"Date > {year}", options)
        if choice in ("back", "quit"):
            return choice
        month = choice
        name = calendar.month_name[month]
        result = _session_list_menu(state, month_groups[month], ["Date", str(year), name])
        if result == "quit":
            return "quit"


def _browse_by_cwd(state: TuiState) -> str | None:
    if not state.sessions:
        _show_message("Working directory", "No sessions found.")
        return "back"
    cwd_groups: dict[str, list[SessionInfo]] = {}
    for session in state.sessions:
        key = session.cwd or "Unknown"
        cwd_groups.setdefault(key, []).append(session)
    cwds = sorted(cwd_groups.keys(), key=lambda value: value.lower())

    while True:
        options = [
            (cwd, f"{_shorten_text(cwd, 60)} ({len(cwd_groups[cwd])})") for cwd in cwds
        ]
        choice = _prompt_choice("Working directory", options)
        if choice in ("back", "quit"):
            return choice
        cwd = choice
        result = _session_list_menu(state, cwd_groups[cwd], ["Working directory", cwd])
        if result == "quit":
            return "quit"


def _search_sessions(state: TuiState) -> str | None:
    if not state.sessions:
        _show_message("Search", "No sessions found.")
        return "back"
    while True:
        query = _prompt_text("Search", "Search term")
        if query in ("back", "quit"):
            return query
        if not query:
            _show_message("Search", "Enter a search term or use 'b' to go back.")
            continue
        results = filter_sessions(state.sessions, query=query)
        if not results:
            _show_message("Search", "No matches. Try another query.")
            continue
        result = _session_list_menu(state, results, ["Search", query])
        if result == "quit":
            return "quit"


def _export_last_n(state: TuiState) -> str | None:
    while True:
        raw = _prompt_text("Export > Last N", "How many sessions to export?")
        if raw in ("back", "quit"):
            return raw
        if not raw or not raw.isdigit():
            _show_message("Export > Last N", "Enter a number.")
            continue
        count = int(raw)
        if count <= 0:
            _show_message("Export > Last N", "Enter a positive number.")
            continue
        sessions = sort_sessions(state.sessions)[:count]
        if not sessions:
            _show_message("Export > Last N", "No sessions available.")
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
        _show_message("Export > Last N", f"Exported {exported} sessions to {out_dir_path}")
        return "back"


def _settings_menu(state: TuiState) -> str | None:
    settings = state.settings
    while True:
        options = [
            ("tools", f"Include tools: {settings.include_tools}"),
            ("reasoning", f"Include reasoning summary: {settings.include_reasoning}"),
            (
                "diagnostics",
                f"Include diagnostics (warnings + skipped events): {settings.include_diagnostics}",
            ),
            ("redact", f"Redact paths: {settings.redact_paths}"),
            ("output_dir", f"Default output directory: {settings.output_dir or Path.cwd()}"),
        ]
        choice = _prompt_choice("Settings", options)
        if choice in ("back", "quit"):
            return choice
        if choice == "tools":
            settings.include_tools = not settings.include_tools
        elif choice == "reasoning":
            settings.include_reasoning = not settings.include_reasoning
        elif choice == "diagnostics":
            settings.include_diagnostics = not settings.include_diagnostics
        elif choice == "redact":
            settings.redact_paths = not settings.redact_paths
        elif choice == "output_dir":
            result = _prompt_output_dir(settings)
            if result == "quit":
                return "quit"


def _session_list_menu(state: TuiState, sessions: Iterable[SessionInfo], breadcrumb: list[str]) -> str | None:
    session_list = sort_sessions(list(sessions))
    while True:
        if not session_list:
            _show_message(_format_breadcrumb(breadcrumb), "No sessions found.")
            return "back"
        options = [(idx, _format_session_line(session)) for idx, session in enumerate(session_list)]
        choice = _prompt_choice(_format_breadcrumb(breadcrumb), options)
        if choice in ("back", "quit"):
            return choice
        selected = session_list[choice]
        label = selected.session_id or selected.path.name
        result = _session_action_menu(state, selected, breadcrumb + [label])
        if result == "quit":
            return "quit"


def _session_action_menu(state: TuiState, session_info: SessionInfo, breadcrumb: list[str]) -> str | None:
    while True:
        options = [
            ("export_default", "Export Markdown"),
            ("preview", "Show Markdown preview"),
        ]
        choice = _prompt_choice(_format_breadcrumb(breadcrumb), options)
        if choice in ("back", "quit"):
            return choice
        if choice == "export_default":
            session = parse_session(session_info.path)
            options = _resolve_export_options(state.settings)
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
            _show_message(_format_breadcrumb(breadcrumb), f"Exported to {out_path}")
            continue
        if choice == "preview":
            session = parse_session(session_info.path)
            options = _resolve_export_options(state.settings)
            _show_markdown_preview(_format_breadcrumb(breadcrumb), session, options)
            continue


def _resolve_export_options(settings: Settings) -> ExportOptions:
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
    raw = _prompt_text("Output directory", "Output directory", default=str(default_dir))
    if raw in ("back", "quit"):
        return raw
    if raw is None:
        return None
    chosen = Path(raw).expanduser()
    settings.output_dir = chosen
    return chosen


def _confirm_overwrite(path: Path) -> bool:
    while True:
        raw = input(f"{path} exists. Overwrite? (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def _show_markdown_preview(title: str, session: Session, options: ExportOptions) -> None:
    content = session_to_markdown(session, options)
    _clear_screen()
    print(title)
    print("")
    pydoc.pager(content)


def _clear_screen() -> None:
    print("\033[2J\033[H", end="")


def _format_breadcrumb(breadcrumb: Sequence[str] | str) -> str:
    if isinstance(breadcrumb, str):
        return breadcrumb
    return " > ".join(breadcrumb)


def _nav_hint(allow_back: bool, allow_quit: bool) -> str:
    if allow_back and allow_quit:
        return "b = back | q = quit"
    if allow_back:
        return "b = back"
    if allow_quit:
        return "q = quit"
    return ""


def _show_message(title: Sequence[str] | str, message: str) -> None:
    _clear_screen()
    print(_format_breadcrumb(title))
    print("")
    print(message)
    input("Press Enter to continue...")


def _prompt_text(
    title: Sequence[str] | str,
    prompt_text: str,
    *,
    default: str | None = None,
    allow_back: bool = True,
    allow_quit: bool = True,
) -> str | None:
    title_text = _format_breadcrumb(title)
    hint = _nav_hint(allow_back, allow_quit)
    prompt_label = prompt_text
    if default:
        prompt_label += f" [{default}]"
    prompt_label += ": "
    while True:
        _clear_screen()
        print(title_text)
        if hint:
            print("")
            print(hint)
        try:
            if HAS_PROMPT_TOOLKIT:
                raw = prompt(prompt_label)
            else:
                raw = input(prompt_label)
        except (EOFError, KeyboardInterrupt):
            return "quit"
        raw = raw.strip()
        if not raw and default is not None:
            raw = str(default)
        lowered = raw.lower()
        if allow_back and lowered in ("b", "back"):
            return "back"
        if allow_quit and lowered in ("q", "quit"):
            return "quit"
        return raw


def _prompt_choice(
    title: Sequence[str] | str,
    options: list[tuple[object, str]],
    *,
    allow_back: bool = True,
    allow_quit: bool = True,
    header_lines: list[str] | None = None,
) -> object | str:
    if not options:
        return "back"
    title_text = _format_breadcrumb(title)
    hint = _nav_hint(allow_back, allow_quit)
    if HAS_PROMPT_TOOLKIT:
        radio = RadioList(options)
        kb = KeyBindings()

        @kb.add("enter", eager=True)
        def _select(event) -> None:
            radio._handle_enter()
            event.app.exit(result=radio.current_value)

        if allow_back:
            @kb.add("b", eager=True)
            @kb.add("escape", eager=True)
            def _go_back(event) -> None:
                event.app.exit(result="back")

        if allow_quit:
            @kb.add("q", eager=True)
            @kb.add("c-c", eager=True)
            def _go_quit(event) -> None:
                event.app.exit(result="quit")

        rows: list[Label | RadioList] = [Label(title_text)]
        for line in header_lines or []:
            rows.append(Label(line))
        rows.append(Label(""))
        rows.append(radio)
        if hint:
            rows.append(Label(""))
            rows.append(Label(hint))
        app = Application(layout=Layout(HSplit(rows)), key_bindings=kb, full_screen=True)
        return app.run()

    _clear_screen()
    print(title_text)
    for line in header_lines or []:
        print(line)
    for idx, (_, label) in enumerate(options, start=1):
        print(f"{idx}. {label}")
    if hint:
        print("")
        print(hint)
    while True:
        raw = input("Select: ").strip()
        if not raw:
            print("Enter a number or use the navigation keys.")
            continue
        lowered = raw.lower()
        if allow_back and lowered in ("b", "back"):
            return "back"
        if allow_quit and lowered in ("q", "quit"):
            return "quit"
        if raw.isdigit():
            value = int(raw)
            if 1 <= value <= len(options):
                return options[value - 1][0]
        print("Invalid input. Enter a valid option.")


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
