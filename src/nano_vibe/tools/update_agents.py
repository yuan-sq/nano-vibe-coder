"""Foreground project-guide review performed before entering DONE."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from nano_vibe.agent.state import AgentState, InvalidTransition, StateMachine

from .base import Tool, ToolResult


class UpdateAgentsTool(Tool):
    name = "update_agents"
    description = "Review and write the complete AGENTS.md for the target repository."
    permission_scope = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
        "additionalProperties": False,
    }

    def __init__(self, workspace: str | Path, machine: StateMachine) -> None:
        self.workspace = Path(workspace).resolve()
        self.machine = machine

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self.machine.current is not AgentState.VERIFY:
            return ToolResult.failure("AGENTS.md can only be reviewed during VERIFY")
        content = arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolResult.failure("AGENTS.md content must be a non-empty string")

        target = self.workspace / "AGENTS.md"
        try:
            old_content = target.read_text(encoding="utf-8") if target.exists() else None
            await asyncio.to_thread(_atomic_write, target, content)
            self.machine.mark_agents_updated()
        except (OSError, InvalidTransition) as exc:
            return ToolResult.failure(f"could not update AGENTS.md: {exc}")
        return ToolResult.success(
            "AGENTS.md reviewed successfully.",
            changed=old_content != content,
            path=str(target),
        )


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".AGENTS.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
