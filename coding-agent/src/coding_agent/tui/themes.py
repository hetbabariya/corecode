"""Theme definitions for the coding agent TUI.

Each theme defines a complete set of color tokens matching Claude Code's
visual language.  The active theme is loaded at startup and its tokens are
injected into the Textual CSS via ``theme.py``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# ── WCAG contrast helpers ─────────────────────────────────


def _srgb_to_linear(c: float) -> float:
    """Convert sRGB channel (0–1) to linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    """Compute relative luminance of a hex color string."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r, g, b = int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def _contrast_ratio(c1: str, c2: str) -> float:
    """Compute WCAG contrast ratio between two hex colors."""
    l1 = _relative_luminance(c1)
    l2 = _relative_luminance(c2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _parse_color_to_hex(color: str) -> str | None:
    """Best-effort parse of a color string to hex. Returns None if unparseable."""
    color = color.strip()
    if color.startswith("#") and len(color) in (4, 7):
        return color
    if color.startswith("rgb(") and color.endswith(")"):
        parts = color[4:-1].split(",")
        if len(parts) == 3:
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _compute_muted(fg: str, bg: str, min_ratio: float = 4.5) -> str:
    """Compute a muted foreground that meets min_ratio contrast against bg."""
    fg_hex = _parse_color_to_hex(fg)
    bg_hex = _parse_color_to_hex(bg)
    if not fg_hex or not bg_hex:
        return fg
    bg_lum = _relative_luminance(bg_hex)
    ratio = _contrast_ratio(fg_hex, bg_hex)
    if ratio >= min_ratio:
        return fg
    bg_linear = bg_lum
    if bg_linear < 0.5:
        target_lum = (min_ratio * (bg_linear + 0.05) - 0.05)
        target_lum = max(0, min(target_lum, 1.0))
    else:
        target_lum = (bg_linear + 0.05) / min_ratio - 0.05
        target_lum = max(0, min(target_lum, 1.0))
    lo, hi = 0.0, 1.0
    for _ in range(32):
        mid = (lo + hi) / 2
        if bg_linear < 0.5:
            test_lum = mid
        else:
            test_lum = 1.0 - mid
        test_hex = f"#{int(test_lum * 255):02x}{int(test_lum * 255):02x}{int(test_lum * 255):02x}"
        ratio = _contrast_ratio(test_hex, bg_hex)
        if ratio >= min_ratio:
            lo = mid
        else:
            hi = mid
    if bg_linear < 0.5:
        val = int(lo * 255)
    else:
        val = int((1.0 - lo) * 255)
    val = max(0, min(255, val))
    return f"#{val:02x}{val:02x}{val:02x}"


@dataclass(frozen=True)
class Theme:
    """A complete color palette for the TUI."""

    name: str

    # ── Core ──────────────────────────────────────────────
    background: str
    foreground: str
    surface: str

    # ── Messages ──────────────────────────────────────────
    user_message: str
    assistant_message: str
    error: str
    status: str

    # ── UI chrome ─────────────────────────────────────────
    accent: str
    border: str
    border_focus: str
    border_muted: str

    # ── Tool display ──────────────────────────────────────
    tool_border: str
    tool_result_ok: str
    tool_result_err: str

    # ── Permission ────────────────────────────────────────
    permission_border: str

    # ── Button foreground colours ─────────────────────────
    btn_success_fg: str = "white"
    btn_warning_fg: str = "black"
    btn_error_fg: str = "white"

    # ── Status bar ────────────────────────────────────────
    status_bar_bg: str = ""
    status_bar_border: str = ""

    # ── Chat message backgrounds ──────────────────────────
    chat_user_bg: str = "transparent"
    chat_user_border: str = "transparent"
    chat_assistant_bg: str = "transparent"
    chat_assistant_border: str = ""

    # ── Interaction ───────────────────────────────────────
    tool_call_border_hover: str = ""
    input_border_focus: str = ""

    # ── Scrollbar ─────────────────────────────────────────
    scrollbar_thumb: str = ""
    scrollbar_track: str = ""

    # ── Links ─────────────────────────────────────────────
    link: str = ""
    link_hover: str = ""

    # ── Semantic borders ──────────────────────────────────
    success_border: str = ""
    warning_border: str = ""
    info_border: str = ""

    # ── Diff ──────────────────────────────────────────────
    diff_add_bg: str = "transparent"
    diff_del_bg: str = "transparent"
    diff_ctx_fg: str = ""

    # ── Selection / cursor ────────────────────────────────
    selection_bg: str = ""
    cursor_color: str = ""

    # ── Tooltip ───────────────────────────────────────────
    tooltip_bg: str = ""
    tooltip_fg: str = ""

    # ── Badge ─────────────────────────────────────────────
    badge_bg: str = ""
    badge_fg: str = ""

    # ── Background variants ───────────────────────────────
    bg_subtle: str = ""
    bg_muted: str = ""
    bg_emphasized: str = ""

    # ── Muted foreground (computed for WCAG contrast) ─────
    muted_fg: str = ""


def _with_defaults(t: Theme) -> Theme:
    """Fill in empty string defaults from core tokens."""
    bg = t.background
    fg = t.foreground
    surface = t.surface
    border = t.border
    accent = t.accent
    return Theme(
        name=t.name,
        background=bg,
        foreground=fg,
        surface=surface,
        user_message=t.user_message,
        assistant_message=t.assistant_message,
        error=t.error,
        status=t.status,
        accent=accent,
        border=border,
        border_focus=t.border_focus,
        border_muted=t.border_muted,
        tool_border=t.tool_border,
        tool_result_ok=t.tool_result_ok,
        tool_result_err=t.tool_result_err,
        permission_border=t.permission_border,
        btn_success_fg=t.btn_success_fg,
        btn_warning_fg=t.btn_warning_fg,
        btn_error_fg=t.btn_error_fg,
        status_bar_bg=t.status_bar_bg or surface,
        status_bar_border=t.status_bar_border or border,
        chat_user_bg=t.chat_user_bg or "transparent",
        chat_user_border=t.chat_user_border or "transparent",
        chat_assistant_bg=t.chat_assistant_bg or "transparent",
        chat_assistant_border=t.chat_assistant_border or t.assistant_message,
        tool_call_border_hover=t.tool_call_border_hover or t.tool_border,
        input_border_focus=t.input_border_focus or t.border_focus,
        scrollbar_thumb=t.scrollbar_thumb or border,
        scrollbar_track=t.scrollbar_track or bg,
        link=t.link or t.assistant_message,
        link_hover=t.link_hover or t.assistant_message,
        success_border=t.success_border or t.tool_result_ok,
        warning_border=t.warning_border or t.tool_border,
        info_border=t.info_border or t.assistant_message,
        diff_add_bg=t.diff_add_bg or "transparent",
        diff_del_bg=t.diff_del_bg or "transparent",
        diff_ctx_fg=t.diff_ctx_fg or t.status,
        selection_bg=t.selection_bg or t.border_focus,
        cursor_color=t.cursor_color or t.border_focus,
        tooltip_bg=t.tooltip_bg or surface,
        tooltip_fg=t.tooltip_fg or fg,
        badge_bg=t.badge_bg or border,
        badge_fg=t.badge_fg or fg,
        bg_subtle=t.bg_subtle or surface,
        bg_muted=t.bg_muted or t.border_muted,
        bg_emphasized=t.bg_emphasized or border,
        muted_fg=t.muted_fg or _compute_muted(fg, bg, 4.5),
    )


# ── Dark theme (primary — matches Claude Code dark) ───────

DARK = _with_defaults(Theme(
    name="dark",
    background="#1e1e2e",
    foreground="#cdd6f4",
    surface="#181825",
    user_message="rgb(78,186,101)",
    assistant_message="#89b4fa",
    error="rgb(240,80,100)",
    status="#8890a4",
    accent="rgb(215,119,87)",
    border="#45475a",
    border_focus="rgb(0,165,149)",
    border_muted="#313244",
    tool_border="#f9e2af",
    tool_result_ok="rgb(78,186,101)",
    tool_result_err="rgb(240,80,100)",
    permission_border="#f9e2af",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))

# ── Light theme ───────────────────────────────────────────

LIGHT = _with_defaults(Theme(
    name="light",
    background="#eff1f5",
    foreground="#4c4f69",
    surface="#e6e9ef",
    user_message="rgb(20,120,50)",
    assistant_message="#1a5ad0",
    error="rgb(200,10,50)",
    status="#556068",
    accent="rgb(180,75,30)",
    border="#ccd0da",
    border_focus="rgb(0,140,130)",
    border_muted="#bcc0cc",
    tool_border="#df8e1d",
    tool_result_ok="rgb(20,120,50)",
    tool_result_err="rgb(200,10,50)",
    permission_border="#df8e1d",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))

# ── Dark ANSI (fallback for 16-colour terminals) ──────────

DARK_ANSI = _with_defaults(Theme(
    name="dark-ansi",
    background="black",
    foreground="white",
    surface="black",
    user_message="green",
    assistant_message="blue",
    error="red",
    status="gray",
    accent="yellow",
    border="gray",
    border_focus="cyan",
    border_muted="gray",
    tool_border="yellow",
    tool_result_ok="green",
    tool_result_err="red",
    permission_border="yellow",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))

# ── Light ANSI ────────────────────────────────────────────

LIGHT_ANSI = _with_defaults(Theme(
    name="light-ansi",
    background="white",
    foreground="black",
    surface="white",
    user_message="green",
    assistant_message="blue",
    error="red",
    status="gray",
    accent="darkyellow",
    border="gray",
    border_focus="darkcyan",
    border_muted="gray",
    tool_border="darkyellow",
    tool_result_ok="green",
    tool_result_err="red",
    permission_border="darkyellow",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))

# ── Dark Daltonized (colorblind-friendly) ─────────────────

DARK_DALTONIZED = _with_defaults(Theme(
    name="dark-daltonized",
    background="#1b1b2f",
    foreground="#d6deeb",
    surface="#15152a",
    user_message="rgb(78,186,101)",
    assistant_message="#7fbcdc",
    error="rgb(240,90,90)",
    status="#8890a4",
    accent="rgb(230,170,100)",
    border="#45475a",
    border_focus="rgb(100,180,180)",
    border_muted="#313244",
    tool_border="rgb(230,200,100)",
    tool_result_ok="rgb(78,186,101)",
    tool_result_err="rgb(240,90,90)",
    permission_border="rgb(230,200,100)",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))

# ── Light Daltonized (colorblind-friendly) ────────────────

LIGHT_DALTONIZED = _with_defaults(Theme(
    name="light-daltonized",
    background="#f5f5f5",
    foreground="#333333",
    surface="#e8e8e8",
    user_message="rgb(0,90,150)",
    assistant_message="rgb(0,90,150)",
    error="rgb(180,70,0)",
    status="#555555",
    accent="rgb(180,70,0)",
    border="#cccccc",
    border_focus="rgb(86,180,200)",
    border_muted="#dddddd",
    tool_border="rgb(200,180,40)",
    tool_result_ok="rgb(0,90,150)",
    tool_result_err="rgb(180,70,0)",
    permission_border="rgb(200,180,40)",
    btn_success_fg="white",
    btn_warning_fg="black",
    btn_error_fg="white",
))


# ── Registry ──────────────────────────────────────────────

THEMES: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "dark-ansi": DARK_ANSI,
    "light-ansi": LIGHT_ANSI,
    "dark-daltonized": DARK_DALTONIZED,
    "light-daltonized": LIGHT_DALTONIZED,
}

DEFAULT_THEME_NAME = "dark"


# ── Terminal background detection ──────────────────────────

def _detect_terminal_bg() -> str:
    """Heuristic: detect whether terminal background is dark or light."""
    # Check COLORFGBG (common in vim/rxvt)
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg and ";" in colorfgbg:
        parts = colorfgbg.split(";")
        bg = parts[-1].strip().lower()
        if bg in ("15", "white", "light"):
            return "light"
        if bg in ("0", "black", "dark"):
            return "dark"

    # Check terminal program env vars
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program in ("apple_terminal", "iterm.app", "hyper"):
        # These often default to dark, but we can't know for sure
        pass

    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        # Modern terminal — still can't determine bg, fall through
        pass

    # Check Windows Terminal
    if os.environ.get("WT_SESSION"):
        return "dark"

    # Check TERMINAL_EMULATOR
    if os.environ.get("TERMINAL_EMULATOR_BG_COLOR"):
        return "dark"

    return "dark"


def resolve_auto_theme() -> Theme:
    """Resolve the 'auto' theme by detecting terminal background."""
    bg = _detect_terminal_bg()
    return DARK if bg == "dark" else LIGHT


# ── Theme persistence ──────────────────────────────────────

_CONFIG_DIR = Path("~/.coding-agent").expanduser()
_CONFIG_FILE = _CONFIG_DIR / "config.json"


def _load_config() -> dict:
    """Load config from ~/.coding-agent/config.json."""
    if _CONFIG_FILE.is_file():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_config(config: dict) -> None:
    """Save config to ~/.coding-agent/config.json."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_config()
    existing.update(config)
    _CONFIG_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_theme_preference(name: str) -> None:
    """Persist the user's theme choice."""
    _save_config({"theme": name})


def load_theme_preference() -> str | None:
    """Load the saved theme name, or None if not set."""
    config = _load_config()
    return config.get("theme")


# ── Public API ─────────────────────────────────────────────

def get_theme(name: str | None = None) -> Theme:
    """Return a theme by name, falling back to the default.

    ``"auto"`` triggers terminal background detection.
    """
    if name is None:
        saved = load_theme_preference()
        name = saved or DEFAULT_THEME_NAME
    if name == "auto":
        return resolve_auto_theme()
    return THEMES.get(name, DARK)


def list_themes() -> list[str]:
    """Return sorted theme names."""
    _load_custom_themes()
    return sorted(THEMES) + ["auto"]


# ── Custom theme loading ───────────────────────────────────

_THEMES_DIR = Path("~/.coding-agent/themes").expanduser()


def _load_custom_themes() -> None:
    """Scan ~/.coding-agent/themes/*.json for user-defined themes."""
    if not _THEMES_DIR.is_dir():
        return
    for path in _THEMES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "name" not in data:
                continue
            theme = Theme(
                name=data["name"],
                background=data.get("background", "#1e1e2e"),
                foreground=data.get("foreground", "#cdd6f4"),
                surface=data.get("surface", "#181825"),
                user_message=data.get("user_message", "rgb(78,186,101)"),
                assistant_message=data.get("assistant_message", "#89b4fa"),
                error=data.get("error", "rgb(171,43,63)"),
                status=data.get("status", "#6c7086"),
                accent=data.get("accent", "rgb(215,119,87)"),
                border=data.get("border", "#45475a"),
                border_focus=data.get("border_focus", "rgb(0,165,149)"),
                border_muted=data.get("border_muted", "#313244"),
                tool_border=data.get("tool_border", "#f9e2af"),
                tool_result_ok=data.get("tool_result_ok", "rgb(78,186,101)"),
                tool_result_err=data.get("tool_result_err", "rgb(171,43,63)"),
                permission_border=data.get("permission_border", "#f9e2af"),
            )
            THEMES[theme.name] = _with_defaults(theme)
        except (json.JSONDecodeError, OSError, KeyError):
            continue


# ── Validation ─────────────────────────────────────────────

def _validate_theme(theme: Theme) -> list[str]:
    """Check WCAG contrast for key foreground/background pairs.

    Returns a list of warning strings.  Empty means all pairs pass.
    """
    warnings: list[str] = []
    pairs: list[tuple[str, str, str, float]] = [
        ("foreground", theme.foreground, theme.background, 4.5),
        ("muted_fg", theme.muted_fg, theme.background, 4.5),
        ("user_message", theme.user_message, theme.background, 4.5),
        ("assistant_message", theme.assistant_message, theme.background, 4.5),
        ("error", theme.error, theme.background, 4.5),
        ("status", theme.status, theme.background, 4.5),
        ("accent", theme.accent, theme.background, 4.5),
        ("tool_result_ok", theme.tool_result_ok, theme.background, 3.0),
        ("tool_result_err", theme.tool_result_err, theme.background, 3.0),
    ]
    for label, fg, bg, min_ratio in pairs:
        fg_hex = _parse_color_to_hex(fg)
        bg_hex = _parse_color_to_hex(bg)
        if fg_hex and bg_hex:
            ratio = _contrast_ratio(fg_hex, bg_hex)
            if ratio < min_ratio:
                warnings.append(
                    f"{theme.name}: {label} ({fg}) on {bg} = {ratio:.1f}:1 "
                    f"(min {min_ratio}:1)"
                )
    return warnings


def validate_all_themes() -> list[str]:
    """Validate all built-in themes. Returns combined warnings."""
    all_warnings: list[str] = []
    for theme in THEMES.values():
        all_warnings.extend(_validate_theme(theme))
    return all_warnings
