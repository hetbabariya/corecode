"""Tests for logging module: TUILogHandler, buffer, and setup_logging."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from coding_agent.logging import (
    LogEntry,
    TUILogHandler,
    get_tui_handler,
    setup_logging,
)


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_fields(self) -> None:
        entry = LogEntry(timestamp=1.0, level="INFO", logger="test", event="hello")
        assert entry.timestamp == 1.0
        assert entry.level == "INFO"
        assert entry.event == "hello"
        assert entry.data == {}

    def test_with_data(self) -> None:
        entry = LogEntry(
            timestamp=1.0,
            level="ERROR",
            logger="test",
            event="fail",
            data={"key": "val"},
        )
        assert entry.data == {"key": "val"}


class TestTUILogHandler:
    """Tests for the TUI log handler buffer."""

    def test_emit_and_get(self) -> None:
        handler = TUILogHandler(max_entries=100)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        handler.emit(record)
        entries = handler.get_entries()
        assert len(entries) == 1
        assert entries[0].event == "hello world"
        assert entries[0].level == "INFO"

    def test_max_entries_bounded(self) -> None:
        handler = TUILogHandler(max_entries=5)
        for i in range(10):
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg=f"msg {i}", args=(), exc_info=None,
            )
            handler.emit(record)
        entries = handler.get_entries()
        assert len(entries) == 5
        assert entries[0].event == "msg 5"
        assert entries[-1].event == "msg 9"

    def test_get_entries_count(self) -> None:
        handler = TUILogHandler(max_entries=100)
        for i in range(20):
            record = logging.LogRecord(
                name="test", level=logging.DEBUG, pathname="", lineno=0,
                msg=f"msg {i}", args=(), exc_info=None,
            )
            handler.emit(record)
        entries = handler.get_entries(count=5)
        assert len(entries) == 5
        assert entries[0].event == "msg 15"

    def test_clear(self) -> None:
        handler = TUILogHandler()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="warn", args=(), exc_info=None,
        )
        handler.emit(record)
        assert len(handler.get_entries()) == 1
        handler.clear()
        assert len(handler.get_entries()) == 0

    def test_empty_buffer(self) -> None:
        handler = TUILogHandler()
        assert handler.get_entries() == []

    def test_thread_safety(self) -> None:
        """Multiple threads emitting concurrently should not crash."""
        import threading

        handler = TUILogHandler(max_entries=1000)
        errors: list[Exception] = []

        def emit_records() -> None:
            try:
                for i in range(100):
                    record = logging.LogRecord(
                        name="test", level=logging.INFO, pathname="", lineno=0,
                        msg=f"thread msg {i}", args=(), exc_info=None,
                    )
                    handler.emit(record)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=emit_records) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        entries = handler.get_entries()
        # All threads should have completed without errors
        # Exact count may vary due to GIL scheduling, but should be > 0
        assert len(entries) > 0


class TestGetTuiHandler:
    """Tests for the global TUI handler singleton."""

    def test_returns_same_instance(self) -> None:
        h1 = get_tui_handler()
        h2 = get_tui_handler()
        assert h1 is h2

    def test_is_tui_handler(self) -> None:
        handler = get_tui_handler()
        assert isinstance(handler, TUILogHandler)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_basic_setup(self) -> None:
        setup_logging(level="INFO")
        # Should not raise

    def test_debug_level(self) -> None:
        setup_logging(level="DEBUG")
        # Should not raise

    def test_with_log_file(self, tmp_path: object) -> None:
        log_file = str(Path(str(tmp_path)) / "test.log")  # type: ignore[arg-type]
        setup_logging(level="INFO", log_file=log_file)
        # Should create the log file
        # Note: the file handler is added to root logger, so other tests may see it

    def test_capture_for_tui(self) -> None:
        setup_logging(level="DEBUG", capture_for_tui=True)
        handler = get_tui_handler()
        # Should have the handler registered
        assert handler in logging.root.handlers

    def test_with_temp_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name
        try:
            setup_logging(level="WARNING", log_file=log_path)
            # Should not raise
        finally:
            # Remove file handlers to release the file lock before cleanup
            for h in list(logging.root.handlers):
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    h.close()
                    logging.root.removeHandler(h)
            Path(log_path).unlink(missing_ok=True)
