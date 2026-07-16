"""Checkpoint tools for undo/redo functionality."""

from __future__ import annotations

from coding_agent.sandbox.checkpoint import CheckpointManager
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool


@tool(name="create_checkpoint", description="Create a checkpoint of current workspace state")
async def create_checkpoint(label: str) -> ToolResult:
    """Create a checkpoint by committing current changes."""
    try:
        manager = CheckpointManager(".")
        checkpoint = manager.create_checkpoint(label)
        return ToolResult(
            success=True,
            output=f"Checkpoint created: {checkpoint.id} - {checkpoint.label}",
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(name="restore_checkpoint", description="Restore workspace to a previous checkpoint")
async def restore_checkpoint(checkpoint_id: str) -> ToolResult:
    """Restore to a specific checkpoint."""
    try:
        manager = CheckpointManager(".")
        if manager.restore_checkpoint(checkpoint_id):
            return ToolResult(
                success=True,
                output=f"Restored to checkpoint: {checkpoint_id}",
            )
        else:
            return ToolResult(
                success=False,
                error=f"Checkpoint not found: {checkpoint_id}",
            )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(name="list_checkpoints", description="List available checkpoints")
async def list_checkpoints(limit: int = 20) -> ToolResult:
    """List recent checkpoints."""
    try:
        manager = CheckpointManager(".")
        checkpoints = manager.list_checkpoints(limit)
        if not checkpoints:
            return ToolResult(success=True, output="No checkpoints found")

        lines = []
        for cp in checkpoints:
            lines.append(f"{cp.id} - {cp.label}")

        return ToolResult(success=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(name="undo", description="Undo the last change by restoring to previous checkpoint")
async def undo() -> ToolResult:
    """Undo the last change."""
    try:
        manager = CheckpointManager(".")
        checkpoint = manager.undo()
        if checkpoint:
            return ToolResult(
                success=True,
                output=f"Undone to checkpoint: {checkpoint.id} - {checkpoint.label}",
            )
        else:
            return ToolResult(
                success=False,
                error="Nothing to undo",
            )
    except Exception as e:
        return ToolResult(success=False, error=str(e))
