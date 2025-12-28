from __future__ import annotations

from typing import Iterable

from .models import SessionInfo


def _match_text(value: str | None, needle: str) -> bool:
    if not value:
        return False
    return needle.lower() in value.lower()


def filter_sessions(
    sessions: Iterable[SessionInfo],
    *,
    year: int | None = None,
    month: int | None = None,
    cwd: str | None = None,
    repo: str | None = None,
    query: str | None = None,
) -> list[SessionInfo]:
    results: list[SessionInfo] = []
    for session in sessions:
        if year is not None and session.year != year:
            continue
        if month is not None and session.month != month:
            continue
        if cwd and not _match_text(session.cwd, cwd):
            continue
        if repo:
            if not (_match_text(session.repo_url, repo) or _match_text(session.cwd, repo)):
                continue
        if query:
            combined = " ".join(
                [
                    session.preview or "",
                    session.cwd or "",
                    session.repo_url or "",
                ]
            )
            if query.lower() not in combined.lower():
                continue
        results.append(session)
    return results


def sort_sessions(sessions: Iterable[SessionInfo]) -> list[SessionInfo]:
    def sort_key(item: SessionInfo) -> tuple[int, float]:
        if item.started_at is None:
            return (1, 0.0)
        return (0, -item.started_at.timestamp())

    return sorted(sessions, key=sort_key)
