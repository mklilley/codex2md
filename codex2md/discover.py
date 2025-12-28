from __future__ import annotations

from pathlib import Path

from .config import configure_logging, get_sessions_root
from .models import SessionInfo
from .parser import build_session_info

logger = configure_logging()


def find_rollout_files(sessions_root: Path | None = None) -> list[Path]:
    root = sessions_root or get_sessions_root()
    if not root.exists():
        logger.info("sessions root not found: %s", root)
        return []
    return sorted(root.rglob("rollout-*.jsonl"))


def discover_sessions(sessions_root: Path | None = None) -> list[SessionInfo]:
    sessions: list[SessionInfo] = []
    for path in find_rollout_files(sessions_root):
        sessions.append(build_session_info(path))
    return sessions
