"""Hooks system — deterministic code injection at lifecycle events."""

from coding_agent.hooks.manager import HookManager
from coding_agent.hooks.types import HookConfig, HookEvent, HookResult

__all__ = ["HookManager", "HookConfig", "HookEvent", "HookResult"]
