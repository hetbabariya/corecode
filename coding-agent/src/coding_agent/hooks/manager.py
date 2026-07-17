"""Hook manager — loads, validates, and executes hooks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from coding_agent.hooks.executor import run_hook
from coding_agent.hooks.types import HookConfig, HookEvent, HookResult
from coding_agent.logging import logger


class HookManager:
    """Loads hooks from a JSON config and executes them at lifecycle events."""

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path or "~/.coding-agent/hooks.json"
        self._hooks: dict[HookEvent, list[HookConfig]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load hooks from JSON config file."""
        path = Path(self._config_path).expanduser()
        if not path.is_file():
            logger.debug("hooks_config_not_found", path=str(path))
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("hooks_config_error", path=str(path), error=str(exc))
            return

        hooks_dict = raw.get("hooks", {})
        for event_name, entries in hooks_dict.items():
            try:
                event = HookEvent(event_name)
            except ValueError:
                logger.warning("hooks_unknown_event", event=event_name)
                continue

            for entry in entries:
                matcher = entry.get("matcher", "")
                for hook_def in entry.get("hooks", []):
                    command = hook_def.get("command", "")
                    if not command:
                        continue
                    timeout = hook_def.get("timeout", 10_000)
                    env = hook_def.get("env", {})
                    config = HookConfig(
                        matcher=matcher,
                        command=command,
                        timeout_ms=timeout,
                        env=env,
                    )
                    self._hooks.setdefault(event, []).append(config)

        total = sum(len(v) for v in self._hooks.values())
        if total:
            logger.info("hooks_loaded", count=total, path=str(path))

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _matching_hooks(
        self, event: HookEvent, tool_name: str
    ) -> list[HookConfig]:
        """Return hooks for *event* whose matcher regex matches *tool_name*."""
        hooks = self._hooks.get(event, [])
        matched = []
        for h in hooks:
            if re.search(h.matcher, tool_name):
                matched.append(h)
        return matched

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_pre_hooks(
        self,
        event: HookEvent,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        workspace: str = "",
    ) -> list[HookResult]:
        """Run pre-execution hooks. Returns all results."""
        hooks = self._matching_hooks(event, tool_name)
        results = []
        for h in hooks:
            result = await run_hook(
                h, event, tool_name, tool_args, workspace=workspace
            )
            results.append(result)
        return results

    async def run_post_hooks(
        self,
        event: HookEvent,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        tool_output: str = "",
        workspace: str = "",
    ) -> list[HookResult]:
        """Run post-execution hooks. Returns all results."""
        hooks = self._matching_hooks(event, tool_name)
        results = []
        for h in hooks:
            result = await run_hook(
                h, event, tool_name, tool_args, tool_output, workspace
            )
            results.append(result)
        return results
