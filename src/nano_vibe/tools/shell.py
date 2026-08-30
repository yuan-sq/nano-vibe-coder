"""Shell command execution in a target workspace."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class ShellTool(Tool):
    name = "shell"
    description = "Run a shell command in the target repository."
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(
        self, workspace: str | Path, timeout_seconds: float = 300, max_output_chars: int = 50_000
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult.failure("shell command must be a non-empty string", exit_code=None)

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                ["/bin/sh", "-lc", command],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = _combine_output(exc.stdout, exc.stderr)
            return ToolResult.failure(
                _truncate(output, self.max_output_chars),
                exit_code=None,
                timed_out=True,
            )
        except OSError as exc:
            return ToolResult.failure(str(exc), exit_code=None, timed_out=False)

        output = _combine_output(completed.stdout, completed.stderr)
        return ToolResult(
            ok=completed.returncode == 0,
            output=_truncate(output, self.max_output_chars),
            metadata={"exit_code": completed.returncode, "timed_out": False},
        )


def _combine_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def decode(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    out, err = decode(stdout), decode(stderr)
    if out and err:
        return f"{out}\n{err}"
    return out or err


def _truncate(output: str, limit: int) -> str:
    if len(output) <= limit:
        return output
    marker = "\n...[output truncated]...\n"
    if limit <= len(marker):
        return marker[:limit]
    remaining = limit - len(marker)
    head = (remaining + 1) // 2
    tail = remaining // 2
    tail_text = output[-tail:] if tail else ""
    return output[:head] + marker + tail_text
