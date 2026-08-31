from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from nano_vibe.agent.loop import LoopStatus
from nano_vibe.config import load_config
from nano_vibe.models.base import ModelResponse
from nano_vibe.permissions import ApprovalDecision, PermissionMode
from nano_vibe.session import Session
from nano_vibe.session_store import SessionSnapshot, SessionStore
from nano_vibe.tools.shell import ShellTool
from nano_vibe.tools.web_search import WebSearchTool


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


def test_session_propagates_tavily_api_key_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
active_model = "default"
[models.default]
name = "default"
url = "https://example.test/v1"
model_name = "demo"
[tavily]
api_key = "config-key"
""",
        encoding="utf-8",
    )

    class UI:
        async def write_stream(self, _: str) -> None:
            pass

        async def ask(self, _: str, __: list[str]) -> str:
            return "answer"

        async def approve(self, _: str, __: dict[str, Any]) -> bool:
            return True

        def tool_start(self, _: str, __: dict[str, Any]) -> None:
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "model-key")
    config = load_config(config_path)
    session = Session.from_config(config, tmp_path, UI())
    tool = cast(WebSearchTool, session.registry._tools["web_search"])

    assert tool._tavily.api_key == "config-key"
    assert "config-key" not in repr(config.tavily)


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


@pytest.mark.asyncio
async def test_session_resume_restores_tool_specific_session_grants(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    original = Session(
        PlainModel(),
        tmp_path,
        session_id="session-1",
        session_store=store,
        permission_approve=lambda _name, _arguments: ApprovalDecision.SESSION,
    )
    policy = original.registry.permission_policy
    assert policy is not None
    assert await policy.authorize("apply_patch", "write", {}) is True
    original.save_snapshot()

    approvals: list[str] = []
    resumed = Session.resume(
        PlainModel(),
        tmp_path,
        "session-1",
        session_store=store,
        permission_approve=lambda name, _arguments: approvals.append(name) or False,
    )
    resumed_policy = resumed.registry.permission_policy
    assert resumed_policy is not None

    assert await resumed_policy.authorize("apply_patch", "write", {}) is True
    assert await resumed_policy.authorize("shell", "shell", {}) is False
    assert approvals == ["shell"]


@pytest.mark.parametrize(
    ("configured_mode", "snapshot_mode"),
    [
        (PermissionMode.FULL_ACCESS, PermissionMode.NORMAL),
        (PermissionMode.NORMAL, PermissionMode.FULL_ACCESS),
    ],
)
def test_restore_snapshot_restores_immutable_session_permission_mode(
    tmp_path: Path,
    configured_mode: PermissionMode,
    snapshot_mode: PermissionMode,
) -> None:
    session = Session(PlainModel(), tmp_path, permission_mode=configured_mode)

    session.restore_snapshot(
        SessionSnapshot(
            session_id=session.session_id,
            workspace=str(tmp_path.resolve()),
            permission_mode=snapshot_mode.value,
        )
    )

    assert session.permission_mode is snapshot_mode
    assert session.registry.permission_policy is not None
    assert session.registry.permission_policy.mode is snapshot_mode
