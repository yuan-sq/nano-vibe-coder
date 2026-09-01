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
from nano_vibe.observability.trace import TraceWriter, trace_path
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


def test_trace_writer_uses_shared_session_path(tmp_path: Path) -> None:
    path = trace_path(tmp_path, "session-1")
    writer = TraceWriter(path, "session-1")
    writer.record("model_request", state="PLAN")

    assert path == tmp_path / ".nano-vibe" / "traces" / "session-1.jsonl"
    assert path.is_file()


def test_trace_reader_paginates_and_ignores_corrupt_tail(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    writer = TraceWriter(path, "session-1")
    for index in range(3):
        writer.record("model_request", index=index, password="secret")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "incomplete"')

    first = read_trace(path, offset=0, limit=2)
    second = read_trace(path, offset=2, limit=2)
    assert first.total == 3
    assert first.next_offset == 2
    assert first.has_more is True
    assert len(first.items) == 2
    assert second.next_offset == 3
    assert second.has_more is False
    assert second.items[0]["password"] == "[REDACTED]"


def test_trace_reader_tail_returns_latest_bounded_page(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    writer = TraceWriter(path, "session-1")
    for index in range(205):
        writer.record("model_request", index=index)

    result = read_trace(path, tail=True, limit=100)

    assert result.total == 205
    assert [item["index"] for item in result.items] == list(range(105, 205))
    assert result.next_offset == 205
    assert result.has_more is False


def test_trace_reader_tail_filters_before_retaining_latest_page(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    writer = TraceWriter(path, "session-1")
    for index in range(205):
        writer.record("tool_end" if index % 2 else "model_request", index=index)

    result = read_trace(path, event="tool_end", tail=True, limit=3)

    assert result.total == 102
    assert [item["index"] for item in result.items] == [199, 201, 203]
    assert result.next_offset == 102
    assert result.has_more is False


class _Model:
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})],
            ),
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
    started = next(payload for name, payload in events if name == "tool_started")
    finished = next(payload for name, payload in events if name == "tool_finished")
    assert started["arguments"] == {"target_state": "PLAN"}
    assert finished["state"] == "PLAN"
    tool_history = next(message for message in loop.history if message.get("role") == "tool")
    assert tool_history["arguments"] == {"target_state": "PLAN"}
