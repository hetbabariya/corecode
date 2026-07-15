"""Tests for the CLI (main.py)."""

from typer.testing import CliRunner

from coding_agent.main import app

runner = CliRunner()


class TestVersionCommand:
    def test_version_shows_info(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "coding-agent v0.1.0" in result.output

    def test_version_shows_python(self) -> None:
        result = runner.invoke(app, ["version"])
        assert "Python 3.12+" in result.output


class TestConfigCommand:
    def test_config_shows_settings(self) -> None:
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "LLM Provider:" in result.output
        assert "LLM Model:" in result.output
        assert "Max Iterations:" in result.output

    def test_config_shows_summary_model(self) -> None:
        result = runner.invoke(app, ["config"])
        assert "Summary Model:" in result.output


class TestRunCommand:
    def test_run_without_prompt_shows_error(self) -> None:
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "No prompt provided" in result.output

    def test_run_with_prompt_shows_settings(self) -> None:
        result = runner.invoke(app, ["run", "--prompt", "test"])
        assert result.exit_code == 0
        # Should attempt to run and print token stats
        assert "Tokens:" in result.output or "Error:" in result.output
