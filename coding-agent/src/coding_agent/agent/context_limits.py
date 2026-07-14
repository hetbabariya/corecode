"""Tool result truncation and large-file handling for context management."""

from __future__ import annotations

from coding_agent.llm.tokens import count_tokens

# Configurable limits
MAX_TOOL_RESULT_TOKENS: int = 8000
MAX_TOOL_RESULT_LINES: int = 500
PRESERVED_HEAD_LINES: int = 50
PRESERVED_TAIL_LINES: int = 50

# Large-file instruction thresholds
LARGE_FILE_LINES: int = 200
LARGE_FILE_INSTRUCTION = (
    "IMPORTANT: This file is {total} lines. You are viewing lines {start}-{end}. "
    "Use offset and limit parameters to read other sections. "
    "Do NOT attempt to read or edit the entire file at once."
)


def truncate_tool_result(
    output: str,
    tool_name: str = "",
    max_tokens: int = MAX_TOOL_RESULT_TOKENS,
    max_lines: int = MAX_TOOL_RESULT_LINES,
    head_lines: int = PRESERVED_HEAD_LINES,
    tail_lines: int = PRESERVED_TAIL_LINES,
) -> str:
    """Truncate a tool result to fit within context budget.

    Strategy:
    1. If output is short enough, return as-is.
    2. Otherwise, keep first *head_lines* and last *tail_lines*,
       inserting a truncation notice in the middle.

    For search results, limit the number of results shown.
    For command output, limit to max_lines.
    """
    if not output:
        return output

    token_count = count_tokens(output)
    lines = output.split("\n")
    line_count = len(lines)

    # Check if truncation is needed
    needs_token_truncation = token_count > max_tokens
    needs_line_truncation = line_count > max_lines

    if not needs_token_truncation and not needs_line_truncation:
        return output

    # Calculate how many lines to preserve
    if needs_line_truncation:
        keep_head = head_lines
        keep_tail = tail_lines
    elif needs_token_truncation:
        # Token-based: estimate lines to keep proportionally
        ratio = max_tokens / max(token_count, 1)
        target_lines = max(int(line_count * ratio), head_lines + tail_lines)
        target_lines = min(target_lines, line_count)
        keep_head = min(head_lines, target_lines // 2)
        keep_tail = min(tail_lines, target_lines - keep_head)
    else:
        keep_head = head_lines
        keep_tail = tail_lines

    # Ensure we at least show something meaningful
    keep_head = max(keep_head, 10)
    keep_tail = max(keep_tail, 10)

    if keep_head + keep_tail >= line_count:
        return output

    head = lines[:keep_head]
    tail = lines[-keep_tail:]
    omitted = line_count - keep_head - keep_tail

    notice = f"\n\n[... truncated: {omitted} lines omitted, {token_count} total tokens ...]\n\n"

    return "\n".join(head) + notice + "\n".join(tail)


def truncate_search_results(
    output: str,
    max_results: int = 20,
) -> str:
    """Limit search result output to a maximum number of results."""
    if not output:
        return output

    lines = output.split("\n")
    if len(lines) <= max_results:
        return output

    truncated = lines[:max_results]
    omitted = len(lines) - max_results
    truncated.append(f"\n[... {omitted} more results omitted ...]")
    return "\n".join(truncated)


def large_file_instruction(total_lines: int, returned_lines: int) -> str:
    """Generate an instruction for the LLM when reading large files.

    Returns an instruction string if the file is large and only a portion
    was returned, empty string otherwise.
    """
    if total_lines <= LARGE_FILE_LINES:
        return ""
    if returned_lines >= total_lines:
        return ""

    return LARGE_FILE_INSTRUCTION.format(
        total=total_lines,
        start=1,
        end=returned_lines,
    )
