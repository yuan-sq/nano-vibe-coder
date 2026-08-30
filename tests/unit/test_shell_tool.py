import sys
from pathlib import Path

import pytest

from nano_vibe.tools.shell import ShellTool


@pytest.mark.asyncio
async def test_shell_runs_command_in_workspace(tmp_path: Path) -> None:
    result = await ShellTool(tmp_path).execute({"command": "pwd"})

    assert result.ok is True
    assert Path(result.output.strip()) == tmp_path
    assert result.metadata["exit_code"] == 0


@pytest.mark.asyncio
async def test_shell_returns_nonzero_exit_and_stderr(tmp_path: Path) -> None:
    result = await ShellTool(tmp_path).execute({"command": "echo boom >&2; exit 7"})

    assert result.ok is False
    assert "boom" in result.output
    assert result.metadata["exit_code"] == 7


@pytest.mark.asyncio
async def test_shell_marks_timeout(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(1)"'
    result = await ShellTool(tmp_path, timeout_seconds=0.05).execute({"command": command})

    assert result.ok is False
    assert result.metadata["timed_out"] is True


@pytest.mark.asyncio
async def test_shell_truncates_long_output_by_preserving_head_and_tail(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "print(\'A\' * 100); print(\'Z\' * 100)"'
    result = await ShellTool(tmp_path, max_output_chars=40).execute({"command": command})

    assert result.ok is True
    assert len(result.output) <= 40
    assert "[output truncated]" in result.output
    assert "A" in result.output and "Z" in result.output


@pytest.mark.asyncio
async def test_shell_truncation_never_exceeds_limit_when_only_one_payload_character_fits(
    tmp_path: Path,
) -> None:
    result = await ShellTool(tmp_path, max_output_chars=30).execute({"command": "printf 123456"})

    assert len(result.output) <= 30
