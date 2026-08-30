import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from nano_vibe.agent.loop import AgentLoop
from nano_vibe.agent.state import StateMachine
from nano_vibe.gui.diff import GitDiffService
from nano_vibe.gui.shell import StreamingShellRunner
from nano_vibe.gui.trace import read_trace
from nano_vibe.models.base import ModelResponse, ToolCall
from nano_vibe.observability.trace import TraceWriter
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.transition import TransitionTool


@pytest.mark.asyncio
async def test_streaming_shell_emits_stdout_and_stderr_chunks(tmp_path: Path) -> None:
    chunks: list[tuple[str, str]] = []
    runner = StreamingShellRunner(tmp_path)
    result = await runner.run(
        f"{sys.executable} -c \"print('out'); print('err', file=__import__('sys').stderr)\"",
        lambda stream, text: chunks.append((stream, text)),
    )

    assert result.ok is True
    assert any(stream == "stdout" and "out" in text for stream, text in chunks)
    assert any(stream == "stderr" and "err" in text for stream, text in chunks)
    assert result.metadata["exit_code"] == 0


@pytest.mark.asyncio
async def test_streaming_shell_cancels_process_group(tmp_path: Path) -> None:
    cancel = asyncio.Event()
    runner = StreamingShellRunner(tmp_path)
    command = f"{sys.executable} -c \"import time; time.sleep(10)\""

    task = asyncio.create_task(runner.run(command, lambda _stream, _text: None, cancel_event=cancel))
    await asyncio.sleep(0.05)
    cancel.set()
    result = await task

    assert result.ok is False
    assert result.metadata["cancelled"] is True


def test_git_diff_service_marks_baseline_and_current_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init", "--quiet"],
        check=True,
    )
    service = GitDiffService(tmp_path)
    service.capture_baseline()
    tracked.write_text("after\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")

    snapshot = service.snapshot()
    by_path = {entry.path: entry for entry in snapshot.entries}
    assert by_path["tracked.txt"].status == "modified"
    assert by_path["tracked.txt"].task_changed is True
    assert by_path["new.txt"].status == "untracked"


def test_trace_reader_filters_events(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    writer = TraceWriter(path, "session-1")
    writer.record("model_request", state="PLAN")
    writer.record("tool_end", tool="shell")

    result = read_trace(path, event="tool_end")
    assert result.total == 1
    assert result.items[0]["tool"] == "shell"


class _Model:
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})]),
            ModelResponse(content="done"),
        ]

    async def complete(self, messages: Any, tools: Any) -> ModelResponse:
        del messages, tools
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_agent_loop_emits_gui_lifecycle_events(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def on_event(name: str, payload: dict[str, Any]) -> None:
        events.append((name, payload))

    machine = StateMachine()
    loop = AgentLoop(
        _Model(),
        ToolRegistry([TransitionTool(machine)]),
        machine,
        tmp_path,
        on_event=on_event,
    )
    await loop.handle_input("Inspect")

    names = [name for name, _payload in events]
    assert names[0] == "user_input"
    assert "model_request" in names
    assert "model_response" in names
    assert "tool_started" in names
    assert "tool_finished" in names
