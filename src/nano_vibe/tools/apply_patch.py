"""Apply model-provided unified diffs safely in a Git workspace."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Validate and apply a unified diff in the target Git repository."
    parameters = {
        "type": "object",
        "properties": {"diff": {"type": "string"}},
        "required": ["diff"],
        "additionalProperties": False,
    }

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        diff = arguments.get("diff")
        if not isinstance(diff, str) or not diff.strip():
            return ToolResult.failure("patch diff must be a non-empty string", checked=False)

        check = await asyncio.to_thread(self._run_git_apply, diff, check=True)
        if check.returncode != 0:
            return ToolResult.failure(
                _command_output(check),
                checked=False,
                exit_code=check.returncode,
            )

        applied = await asyncio.to_thread(self._run_git_apply, diff, check=False)
        if applied.returncode != 0:
            return ToolResult.failure(
                _command_output(applied),
                checked=True,
                exit_code=applied.returncode,
            )
        return ToolResult.success("Patch applied successfully.", checked=True, exit_code=0)

    def _run_git_apply(self, diff: str, *, check: bool) -> subprocess.CompletedProcess[str]:
        args = ["git", "apply", "--recount"]
        if check:
            args.append("--check")
        return subprocess.run(
            args + ["-"],
            cwd=self.workspace,
            input=diff,
            capture_output=True,
            text=True,
            check=False,
        )


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "git apply failed").strip()
