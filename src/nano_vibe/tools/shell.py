"""Shell command execution in a target workspace."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult


class ShellTool(Tool):
    name = "shell"
    description = "Run a shell command in the target repository."
    permission_scope = "shell"
    parameters: ClassVar[dict[str, Any]] = {
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
            return ToolResult.failure(
                "shell command must be a non-empty string",
                code="invalid_shell_command",
                exit_code=None,
            )

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
                code="shell_timeout",
                details={"timeout_seconds": self.timeout_seconds},
                retryable=True,
                exit_code=None,
                timed_out=True,
            )
        except OSError as exc:
            return ToolResult.failure(
                str(exc),
                code="shell_error",
                details={"exception_type": exc.__class__.__name__},
                retryable=True,
                exit_code=None,
                timed_out=False,
            )

        output = _combine_output(completed.stdout, completed.stderr)
        if completed.returncode != 0:
            return ToolResult.failure(
                _truncate(output, self.max_output_chars),
                code="shell_exit",
                details={"exit_code": completed.returncode},
                exit_code=completed.returncode,
                timed_out=False,
            )
        return ToolResult(
            ok=True,
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
