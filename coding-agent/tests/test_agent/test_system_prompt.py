"""Tests for agent.system_prompt module."""

from pathlib import Path

from coding_agent.agent.system_prompt import (
    DYNAMIC_BOUNDARY,
    build_static_prompt,
    build_system_prompt,
)


class TestBuildStaticPrompt:
    def test_returns_string(self):
        result = build_static_prompt()
        assert isinstance(result, str)

    def test_contains_identity(self):
        result = build_static_prompt()
        assert "coding agent" in result.lower()

    def test_contains_tool_rules(self):
        result = build_static_prompt()
        assert "read_file" in result
        assert "search_content" in result

    def test_contains_core_principles(self):
        result = build_static_prompt()
        assert "Think first" in result
        assert "Minimal changes" in result

    def test_contains_safety(self):
        result = build_static_prompt()
        assert "Read operations" in result
        assert "Write operations" in result

    def test_contains_communication(self):
        result = build_static_prompt()
        assert "Concise" in result
        assert "Preambles" in result

    def test_contains_error_handling(self):
        result = build_static_prompt()
        assert "Errors" in result
        assert "File not found" in result


class TestBuildSystemPrompt:
    def test_no_dynamic_without_workspace(self):
        result = build_system_prompt(model="gemini-2.5-flash", provider="gemini")
        assert DYNAMIC_BOUNDARY not in result

    def test_dynamic_boundary_with_workspace(self, tmp_path: object):
        result = build_system_prompt(
            model="gemini-2.5-flash",
            provider="gemini",
            workspace=Path(str(tmp_path)),
        )
        assert DYNAMIC_BOUNDARY in result

    def test_contains_model_info(self, tmp_path: object):
        result = build_system_prompt(
            model="gemini-2.5-flash",
            provider="gemini",
            workspace=Path(str(tmp_path)),
        )
        assert "gemini-2.5-flash" in result
        assert "gemini" in result

    def test_loads_readme_if_exists(self, tmp_path: object):
        readme = Path(str(tmp_path)) / "README.md"
        readme.write_text("# My Project\nA test project.")
        result = build_system_prompt(
            model="test-model",
            provider="test",
            workspace=Path(str(tmp_path)),
        )
        assert "My Project" in result

    def test_loads_agents_md_if_exists(self, tmp_path: object):
        agents_md = Path(str(tmp_path)) / "AGENTS.md"
        agents_md.write_text("Always use snake_case.")
        result = build_system_prompt(
            model="test-model",
            provider="test",
            workspace=Path(str(tmp_path)),
        )
        assert "Always use snake_case" in result

    def test_no_readme_no_agents(self, tmp_path: object):
        result = build_system_prompt(
            model="test-model",
            provider="test",
            workspace=Path(str(tmp_path)),
        )
        assert DYNAMIC_BOUNDARY in result
        assert "README.md" not in result
        assert "AGENTS.md" not in result

    def test_memory_content(self, tmp_path: object):
        result = build_system_prompt(
            model="test-model",
            provider="test",
            workspace=Path(str(tmp_path)),
            memory_content="User prefers dark mode.",
        )
        assert "User prefers dark mode" in result
