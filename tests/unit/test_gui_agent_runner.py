import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from nano_vibe.agent.loop import LoopResult, LoopStatus
from nano_vibe.config import AppConfig, ModelConfig, RuntimeConfig
from nano_vibe.gui.agent_runner import GuiAgentRunner, InteractionBroker
from nano_vibe.models.base import ModelResponse
from nano_vibe.session import Session
from nano_vibe.session_store import SessionSnapshot, SessionStore


class PlainModel:
    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelResponse:
        del messages, tools
        return ModelResponse(content="done")


@pytest.mark.asyncio
async def test_interaction_broker_preserves_explicit_approval_decision() -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(name: str, payload: dict[str, Any]) -> None:
        emitted.append((name, payload))

    broker = InteractionBroker(emit)
    pending = asyncio.create_task(broker.approve("apply_patch", {}))
    await asyncio.sleep(0)
    interaction_id = next(iter(broker.pending))

    assert await broker.resolve(interaction_id, "session") is True
    assert await pending == "session"


@pytest.mark.asyncio
async def test_session_grant_is_persisted_before_authorize_returns(tmp_path: Path) -> None:
    async def emit(_name: str, _payload: dict[str, Any]) -> None:
        return

    store = SessionStore(tmp_path / "sessions")
    broker = InteractionBroker(emit)
    session = Session(
        PlainModel(),
        tmp_path,
        session_id="session-1",
        session_store=store,
        permission_approve=broker.approve,
    )
    policy = session.registry.permission_policy
    assert policy is not None
    authorize = asyncio.create_task(policy.authorize("apply_patch", "write", {}))
    await asyncio.sleep(0)

    interaction_id = next(iter(broker.pending))
    assert await broker.resolve(interaction_id, "session") is True
    assert store.load("session-1").session_grants == ["apply_patch"]
    assert await authorize is True

    assert store.load("session-1").session_grants == ["apply_patch"]


@pytest.mark.asyncio
async def test_gui_runner_restores_real_session_state_and_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        active_model=ModelConfig("test", "http://example.test", "test"),
        models={"test": ModelConfig("test", "http://example.test", "test")},
        runtime=RuntimeConfig(permission_mode="normal"),
    )
    store = SessionStore(tmp_path / ".nano-vibe" / "sessions")
    seed = Session(
        PlainModel(),
        tmp_path,
        session_id="session-1",
        session_store=store,
        permission_mode="full-access",
    )
    seed.machine.current = seed.machine.current.PLAN
    seed.machine.plan.replace([{"id": "inspect", "content": "Inspect", "status": "in_progress"}])
    seed.loop.history = [{"role": "user", "content": "first"}]
    assert seed.registry.permission_policy is not None
    seed.registry.permission_policy.restore_session_grants(["apply_patch"])
    seed.save_snapshot()

    class StaticModel(PlainModel):
        def __init__(self, _config: ModelConfig, *, retries: int, on_text: Any) -> None:
            del retries, on_text

    monkeypatch.setattr("nano_vibe.session.OpenAICompatibleModel", StaticModel)
    runner = GuiAgentRunner(config, lambda _session_id: tmp_path)

    async def emit(_name: str, _payload: dict[str, Any]) -> None:
        return

    await runner("session-1", "second", emit, asyncio.Event())

    restored = store.load("session-1")
    assert restored.permission_mode == "full-access"
    assert restored.plan == [{"id": "inspect", "content": "Inspect", "status": "in_progress"}]
    assert restored.session_grants == ["apply_patch"]
    assert [item["content"] for item in restored.history if item.get("role") == "user"] == ["first", "second"]


@pytest.mark.asyncio
async def test_gui_runner_restores_snapshot_before_marking_session_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    snapshot = SessionSnapshot(
        session_id="session-1",
        workspace=str(tmp_path.resolve()),
        state="PLAN",
        plan=[{"id": "inspect", "content": "Inspect", "status": "in_progress"}],
        history=[{"role": "user", "content": "first"}],
        session_grants=["apply_patch"],
    )

    class FakeStore:
        def path_for(self, session_id: str) -> Path:
            del session_id
            return tmp_path / "session.json"

        def load(self, session_id: str) -> SessionSnapshot:
            del session_id
            calls.append("load")
            return snapshot

    (tmp_path / "session.json").write_text("{}", encoding="utf-8")

    class FakeSession:
        runtime_state = "IDLE"
        pending_interaction = None
        session_store = FakeStore()

        def restore_snapshot(self, restored: SessionSnapshot) -> None:
            assert restored is snapshot
            calls.append("restore")

        def save_snapshot(self) -> Path:
            calls.append(f"save:{self.runtime_state}")
            return tmp_path / "session.json"

        async def handle_input(self, text: str) -> LoopResult:
            assert text == "second"
            calls.append("handle")
            return LoopResult(LoopStatus.WAITING, "done", 1)

    monkeypatch.setattr(
        "nano_vibe.gui.agent_runner.Session.from_config",
        lambda *_args, **_kwargs: FakeSession(),
    )
    runner = GuiAgentRunner(cast(AppConfig, object()), lambda _session_id: tmp_path)

    async def emit(_name: str, _payload: dict[str, Any]) -> None:
        return

    await runner("session-1", "second", emit, asyncio.Event())

    assert calls[:3] == ["load", "restore", "save:RUNNING"]
