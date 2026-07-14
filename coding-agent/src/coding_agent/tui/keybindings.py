"""Custom keybindings loader ΓÇö reads ~/.coding-agent/keybindings.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from textual.binding import Binding

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path("~/.coding-agent").expanduser()
_KEYBINDINGS_FILE = _CONFIG_DIR / "keybindings.json"


def load_custom_bindings() -> list[Binding]:
    """Load custom keybindings from ~/.coding-agent/keybindings.json.

    File format::

        {
            "quit": "ctrl+q",
            "clear": "ctrl+k",
            "cancel": "escape",
            "amend": "tab",
            "scroll_up": "pageup",
            "scroll_down": "pagedown"
        }

    Returns a list of Binding objects.  Unknown action names are silently
    skipped.  Malformed entries are logged and skipped.
    """
    if not _KEYBINDINGS_FILE.is_file():
        return []

    try:
        raw = json.loads(_KEYBINDINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load keybindings: %s", exc)
        return []

    if not isinstance(raw, dict):
        logger.warning("keybindings.json must be a JSON object")
        return []

    bindings: list[Binding] = []
    for action, key in raw.items():
        if not isinstance(action, str) or not isinstance(key, str):
            continue
        try:
            bindings.append(Binding(key, action, show=False))
        except Exception as exc:
            logger.warning("Invalid binding %s=%s: %s", action, key, exc)

    return bindings


def get_config_dir() -> Path:
    """Return the ~/.coding-agent config directory, creating it if needed."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return _CONFIG_DIR
