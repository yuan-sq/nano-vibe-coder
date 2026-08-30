from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from nano_vibe.agent.loop import LoopStatus
from nano_vibe.models.base import ModelResponse
from nano_vibe.session import Session
from nano_vibe.session_store import SessionStore
from nano_vibe.tools.shell import ShellTool


class PlainModel:
    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        del messages, tools
        return ModelResponse(content="waiting for more input")


@pytest.mark.asyncio
async def test_session_delegates_user_input_to_agent_loop(tmp_path: Path) -> None:
    session = Session(PlainModel(), tmp_path)

    result = await session.handle_input("Inspect this repository")

    assert result.status is LoopStatus.WAITING
    assert result.message == "waiting for more input"


def test_session_applies_shell_runtime_limits(tmp_path: Path) -> None:
    session = Session(
        PlainModel(),
        tmp_path,
        shell_timeout_seconds=7,
        shell_max_output_chars=123,
    )

    shell = cast(ShellTool, session.registry._tools["shell"])
    assert shell.timeout_seconds == 7
    assert shell.max_output_chars == 123


@pytest.mark.asyncio
async def test_session_saves_json_snapshot_after_input(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = Session(
        PlainModel(),
        tmp_path,
        session_id="session-1",
        session_store=store,
    )

    await session.handle_input("Inspect this repository")

    snapshot = store.load("session-1")
    assert snapshot.workspace == str(tmp_path.resolve())
    assert snapshot.history[-1]["content"] == "waiting for more input"
    assert snapshot.state == "REQUIREMENTS"


@pytest.mark.asyncio
async def test_session_resume_restores_history_and_counters(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    original = Session(
        PlainModel(),
        tmp_path,
        session_id="session-1",
        session_store=store,
    )
    await original.handle_input("first")

    resumed = Session.resume(PlainModel(), tmp_path, "session-1", session_store=store)

    assert resumed.session_id == "session-1"
    assert resumed.loop.history == original.loop.history
    assert resumed.loop._turns == original.loop._turns
