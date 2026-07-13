"""Tests for the main TUI app."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tui.app import CodingAgentApp


class TestCodingAgentApp:
    def test_init(self):
        app = CodingAgentApp(workspace=Path("."))
        assert app.workspace == Path(".")
        assert app.settings is not None

    def test_init_with_workspace(self):
        app = CodingAgentApp(workspace=Path("/tmp"))
        assert app.workspace == Path("/tmp")

    def test_has_agent_loop(self):
        app = CodingAgentApp()
        assert app.agent_loop is not None

    def test_has_llm_client(self):
        app = CodingAgentApp()
        assert app.llm_client is not None

    def test_has_permission_callback(self):
        app = CodingAgentApp()
        assert app._perm_callback is not None

    def test_stats_initialized(self):
        app = CodingAgentApp()
        assert app.prompt_tokens == 0
        assert app.completion_tokens == 0
        assert app.total_tokens == 0
        assert app.tool_count == 0


class TestAppCompose:
    def test_compose(self):
        app = CodingAgentApp()
        # Test that compose can be called
        result = app.compose()
        assert result is not None


class TestStreamHandler:
    def test_init(self):
        from coding_agent.tui.stream_handler import StreamHandler

        app = CodingAgentApp()
        handler = StreamHandler(app, app.agent_loop)
        assert handler.app is app
        assert handler.agent_loop is app.agent_loop
        assert handler._running is False
