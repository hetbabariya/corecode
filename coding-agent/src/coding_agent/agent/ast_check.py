"""AST-aware validation for code edits.

Provides lightweight syntax validation for Python and other languages
using tree-sitter when available, with a fallback to basic bracket/paren
matching and ast.parse for Python files.
"""

from __future__ import annotations

import ast
from pathlib import Path

from coding_agent.logging import logger

# Try to import tree-sitter for richer AST validation
try:
    import tree_sitter_languages  # type: ignore[import-untyped]

    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


def validate_syntax(code: str, file_path: str = "") -> tuple[bool, str]:
    """Validate that code is syntactically valid.

    Uses tree-sitter for supported languages, falls back to Python's
    ast.parse for .py files, and basic bracket matching for others.

    Returns (is_valid, error_message). error_message is empty if valid.
    """
    suffix = Path(file_path).suffix.lower() if file_path else ""

    # Python: use ast.parse (most accurate)
    if suffix == ".py" or (not suffix and _looks_like_python(code)):
        return _validate_python(code)

    # tree-sitter for other languages
    if _HAS_TREE_SITTER and suffix:
        lang = _suffix_to_language(suffix)
        if lang:
            return _validate_tree_sitter(code, lang)

    # Fallback: basic bracket matching
    return _validate_brackets(code)


def _validate_python(code: str) -> tuple[bool, str]:
    """Validate Python syntax using ast.parse."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        msg = f"Python syntax error at line {e.lineno}: {e.msg}"
        return False, msg
    except Exception as e:
        return False, f"Python parse error: {e}"


def _validate_tree_sitter(code: str, language: str) -> tuple[bool, str]:
    """Validate syntax using tree-sitter."""
    try:
        parser = tree_sitter_languages.get_parser(language)
        tree = parser.parse(code.encode("utf-8"))

        # Check for ERROR nodes in the parse tree
        errors = _find_error_nodes(tree.root_node)
        if errors:
            first = errors[0]
            return False, f"Syntax error at row {first.start_point[0] + 1}: {first.text!r}"

        return True, ""
    except Exception as e:
        logger.debug("tree_sitter_parse_failed", language=language, error=str(e))
        return _validate_brackets(code)


def _find_error_nodes(node: object) -> list[object]:
    """Recursively find ERROR and MISSING nodes in a tree-sitter tree."""
    errors: list[object] = []
    if hasattr(node, "type"):
        if node.type == "ERROR" or node.type == "MISSING":  # type: ignore[union-attr]
            errors.append(node)
    if hasattr(node, "children"):
        for child in node.children:  # type: ignore[union-attr]
            errors.extend(_find_error_nodes(child))
    return errors


def _validate_brackets(code: str) -> tuple[bool, str]:
    """Basic bracket/paren/brace matching validation."""
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_string = False
    string_char = ""
    escape = False

    for i, ch in enumerate(code):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue

        if in_string:
            if ch == string_char:
                in_string = False
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            continue

        if ch in ("(", "[", "{"):
            stack.append((ch, i))
        elif ch in (")", "]", "}"):
            if not stack:
                return False, f"Unexpected '{ch}' at position {i}"
            open_ch, _ = stack.pop()
            if open_ch != pairs[ch]:
                return False, f"Mismatched '{open_ch}' and '{ch}' at position {i}"

    if stack:
        open_ch, pos = stack[-1]
        return False, f"Unclosed '{open_ch}' at position {pos}"

    return True, ""


def _looks_like_python(code: str) -> bool:
    """Heuristic: check if code looks like Python."""
    indicators = ("def ", "import ", "from ", "class ", "if __name__", "elif ", "else:")
    return any(ind in code for ind in indicators)


def _suffix_to_language(suffix: str) -> str | None:
    """Map file extension to tree-sitter language name."""
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".html": "html",
        ".css": "css",
        ".sh": "bash",
        ".bash": "bash",
    }
    return mapping.get(suffix)
