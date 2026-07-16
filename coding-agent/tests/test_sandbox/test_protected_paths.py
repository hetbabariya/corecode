"""Tests for protected path detection."""

from __future__ import annotations

import pytest

from coding_agent.sandbox.protected_paths import is_protected_path


class TestProtectedPathDetection:
    """Test the is_protected_path function."""

    def test_gitconfig(self) -> None:
        assert is_protected_path("~/.gitconfig").is_protected

    def test_bashrc(self) -> None:
        assert is_protected_path("~/.bashrc").is_protected

    def test_zshrc(self) -> None:
        assert is_protected_path("~/.zshrc").is_protected

    def test_profile(self) -> None:
        assert is_protected_path("~/.profile").is_protected

    def test_env_files(self) -> None:
        assert is_protected_path(".env").is_protected
        assert is_protected_path(".env.local").is_protected
        assert is_protected_path(".env.production").is_protected
        assert is_protected_path("/path/to/.env").is_protected

    def test_ssh_keys(self) -> None:
        assert is_protected_path("~/.ssh/authorized_keys").is_protected
        assert is_protected_path("~/.ssh/id_rsa").is_protected
        assert is_protected_path("~/.ssh/id_ed25519").is_protected
        assert is_protected_path("~/.ssh/config").is_protected

    def test_pem_files(self) -> None:
        assert is_protected_path("cert.pem").is_protected
        assert is_protected_path("key.pem").is_protected
        assert is_protected_path("/path/to/cert.pem").is_protected

    def test_git_directory(self) -> None:
        assert is_protected_path(".git/config").is_protected
        assert is_protected_path(".git/HEAD").is_protected
        assert is_protected_path("/repo/.git/objects").is_protected

    def test_ide_directories(self) -> None:
        assert is_protected_path(".vscode/settings.json").is_protected
        assert is_protected_path(".idea/workspace.xml").is_protected
        assert is_protected_path(".claude/config.json").is_protected

    def test_node_modules(self) -> None:
        assert is_protected_path("node_modules/package/index.js").is_protected

    def test_venv(self) -> None:
        assert is_protected_path(".venv/lib/python3.11/site.py").is_protected
        assert is_protected_path("venv/bin/python").is_protected

    def test_pycache(self) -> None:
        assert is_protected_path("__pycache__/module.pyc").is_protected

    def test_safe_files_pass(self) -> None:
        assert not is_protected_path("src/main.py").is_protected
        assert not is_protected_path("README.md").is_protected
        assert not is_protected_path("config/settings.py").is_protected
        assert not is_protected_path("tests/test_main.py").is_protected
        assert not is_protected_path("package.json").is_protected

    def test_path_normalization(self) -> None:
        # Relative paths
        assert is_protected_path("./.env").is_protected
        assert is_protected_path("../.git/config").is_protected

        # Absolute paths
        assert is_protected_path("/home/user/.gitconfig").is_protected
        assert is_protected_path("/root/.ssh/authorized_keys").is_protected

    def test_case_insensitive(self) -> None:
        assert is_protected_path("~/.GITCONFIG").is_protected
        assert is_protected_path("~/.SSH/authorized_keys").is_protected
        assert is_protected_path(".ENV").is_protected

    def test_returns_reason(self) -> None:
        result = is_protected_path("~/.gitconfig")
        assert result.is_protected
        assert "gitconfig" in result.reason.lower()

    def test_safe_returns_empty_reason(self) -> None:
        result = is_protected_path("src/main.py")
        assert not result.is_protected
        assert result.reason == ""
