"""Structured logging with structlog, TUI buffer, and file rotation."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog


@dataclass
class LogEntry:
    """A single log entry for the TUI buffer."""

    timestamp: str
    level: str
    logger: str
    event: str
    data: dict[str, Any] = field(default_factory=dict)


class TUILogHandler(logging.Handler):
    """Logging handler that stores entries in a bounded in-memory buffer.

    The buffer is thread-safe and can be read by the TUI log viewer
    to display recent log entries in real time.
    """

    def __init__(self, max_entries: int = 500) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """Store a log record in the buffer."""
        try:
            entry = LogEntry(
                timestamp=record.created,
                level=record.levelname,
                logger=record.name,
                event=record.getMessage(),
                data=getattr(record, "struct_data", {}),
            )
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            pass

    def get_entries(self, count: int = 100) -> list[LogEntry]:
        """Return the last *count* log entries (thread-safe)."""
        with self._lock:
            return list(self._buffer)[-count:]

    def clear(self) -> None:
        """Clear all entries from the buffer."""
        with self._lock:
            self._buffer.clear()


# Global TUI log handler instance (created once, shared across the app)
_tui_handler: TUILogHandler | None = None


def get_tui_handler() -> TUILogHandler:
    """Return the global TUI log handler, creating it if needed."""
    global _tui_handler
    if _tui_handler is None:
        _tui_handler = TUILogHandler()
    return _tui_handler


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    capture_for_tui: bool = False,
) -> None:
    """Configure structured logging with structlog.

    Parameters
    ----------
    level:
        Log level (DEBUG, INFO, WARNING, ERROR).
    log_file:
        Optional file path for log output. Uses RotatingFileHandler
        (5MB max, 3 backups).
    capture_for_tui:
        If True, also captures logs into the TUI buffer for display
        in the log viewer panel.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Suppress noisy third-party loggers even when root is at DEBUG
    _noisy_loggers = [
        "markdown_it",   # markdown parser state machine debug spam
        "httpcore",      # HTTP connection lifecycle details
        "httpx",         # HTTP request/response details
        "asyncio",       # event loop proactor debug info
        "urllib3",       # connection pool details
        "aiosqlite",     # per-SQL-statement debug logging
    ]
    for logger_name in _noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Configure structlog to use stdlib logging (so file handlers work)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Console renderer for stderr (when TTY)
    console_renderer = (
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer()
    )

    # Set up stdlib handlers
    root = logging.root
    root.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for h in list(root.handlers):
        root.removeHandler(h)

    # Stderr handler (human-readable) — skip when TUI owns the terminal
    if not capture_for_tui:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(log_level)
        stderr_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=console_renderer,
                foreign_pre_chain=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            )
        )
        root.addHandler(stderr_handler)

    # File handler (JSON format for structured logs)
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            )
        )
        root.addHandler(file_handler)

    # TUI buffer handler
    if capture_for_tui:
        tuih = get_tui_handler()
        tuih.setLevel(log_level)
        tuih.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            )
        )
        root.addHandler(tuih)


logger = structlog.get_logger()
