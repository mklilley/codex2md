from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os

LOG_FILE_NAME = "latest.log"


@dataclass
class Settings:
    include_tools: bool = True
    messages_only: bool = False
    include_reasoning: bool = False
    redact_paths: bool = False
    output_dir: Path | None = None


def get_codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex"


def get_sessions_root() -> Path:
    return get_codex_home() / "sessions"


def get_app_home() -> Path:
    return Path.home() / ".codex2md"


def get_log_dir() -> Path:
    return get_app_home() / "logs"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("codex2md")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_dir = get_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back to stderr only if log directory fails.
        logging.basicConfig(level=logging.INFO)
        return logger

    log_path = log_dir / LOG_FILE_NAME
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
