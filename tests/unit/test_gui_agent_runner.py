import asyncio
import multiprocessing
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from nano_vibe.agent.loop import LoopResult, LoopStatus
from nano_vibe.config import AppConfig, ModelConfig, RuntimeConfig
from nano_vibe.gui.agent_runner import (
    GuiAgentRunner,
    InteractionBroker,
    StalePendingCleanupError,
)
from nano_vibe.gui.runtime import GlobalRunLock
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


def _runner_config() -> AppConfig:
    return AppConfig(
        active_model=ModelConfig("test", "http://example.test", "test"),
        models={"test": ModelConfig("test", "http://example.test", "test")},
        runtime=RuntimeConfig(permission_mode="normal"),
    )


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
async def test_resolve_clears_stale_pending_interaction_without_a_broker(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".nano-vibe" / "sessions")
    store.save(
        SessionSnapshot(
            session_id="session-1",
            workspace=str(tmp_path.resolve()),
            runtime_state="AWAITING_APPROVAL",
            pending_interaction={
                "interaction_id": "stale-1",
                "kind": "approval",
                "tool_name": "apply_patch",
            },
        )
    )
    runner = GuiAgentRunner(_runner_config(), lambda _session_id: tmp_path)

    assert await runner.resolve("session-1", "stale-1", "session") is False

    snapshot = store.load("session-1")
    assert snapshot.pending_interaction is None
    assert snapshot.runtime_state == "PAUSED"


def _hold_run_lock(path: str, ready: Any, release: Any) -> None:
    lock = GlobalRunLock(path)
    lock.acquire()
    ready.set()
    release.wait(5)
    lock.release()


@pytest.mark.asyncio
async def test_resolve_does_not_clear_pending_owned_by_another_process(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".nano-vibe" / "sessions")
    store.save(
        SessionSnapshot(
            session_id="session-1",
            workspace=str(tmp_path.resolve()),
            runtime_state="AWAITING_APPROVAL",
            pending_interaction={
                "interaction_id": "owned-1",
                "kind": "approval",
                "tool_name": "apply_patch",
            },
        )
    )
    lock_path = tmp_path / "app" / "run.lock"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_run_lock, args=(str(lock_path), ready, release))
    process.start()
    try:
        assert ready.wait(5)
        runner = GuiAgentRunner(
            _runner_config(), lambda _session_id: tmp_path, run_lock_path=lock_path
        )

        assert await runner.resolve("session-1", "owned-1", "session") is False

        snapshot = store.load("session-1")
        assert snapshot.pending_interaction is not None
        assert snapshot.pending_interaction["interaction_id"] == "owned-1"
        assert snapshot.runtime_state == "AWAITING_APPROVAL"
    finally:
        release.set()
        process.join(timeout=5)
        assert process.exitcode == 0


@pytest.mark.asyncio
async def test_resolve_reports_stale_pending_persistence_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path / ".nano-vibe" / "sessions")
    store.save(
        SessionSnapshot(
            session_id="session-1",
            workspace=str(tmp_path.resolve()),
            runtime_state="AWAITING_APPROVAL",
            pending_interaction={
                "interaction_id": "stale-1",
                "kind": "approval",
                "tool_name": "apply_patch",
            },
        )
    )

    def fail_save(_store: SessionStore, _snapshot: SessionSnapshot) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(SessionStore, "save", fail_save)
    runner = GuiAgentRunner(_runner_config(), lambda _session_id: tmp_path)

    with pytest.raises(StalePendingCleanupError, match="disk full"):
        await runner.resolve("session-1", "stale-1", "session")


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
async def test_gui_session_grant_resolve_and_authorize_persist_once(tmp_path: Path) -> None:
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

    original_save = store.save
    save_calls = 0

    def fail_on_second_save(snapshot: SessionSnapshot) -> Path:
        nonlocal save_calls
        save_calls += 1
        if save_calls > 1:
            raise RuntimeError("unexpected second save")
        return original_save(snapshot)

    store.save = fail_on_second_save  # type: ignore[method-assign]
    interaction_id = next(iter(broker.pending))

    assert await broker.resolve(interaction_id, "session") is True
    assert await authorize is True
    assert save_calls == 1
    assert policy.session_grants == {"apply_patch"}
    assert store.load("session-1").session_grants == ["apply_patch"]


@pytest.mark.asyncio
async def test_failed_session_grant_persistence_rolls_back_before_resolve_returns(tmp_path: Path) -> None:
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
    session.save_snapshot = lambda: (_ for _ in ()).throw(RuntimeError("disk full"))  # type: ignore[method-assign]

    interaction_id = next(iter(broker.pending))
    assert await broker.resolve(interaction_id, "session") is False
    assert policy.session_grants == set()
    authorize.cancel()
    await asyncio.gather(authorize, return_exceptions=True)


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
async def test_gui_runner_emits_running_only_after_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    snapshot = SessionSnapshot(session_id="session-1", workspace=str(tmp_path.resolve()))

    class FakeStore:
        def path_for(self, _session_id: str) -> Path:
            return tmp_path / "session.json"

        def load(self, _session_id: str) -> SessionSnapshot:
            return snapshot

    class FakeSession:
        runtime_state = "IDLE"
        pending_interaction = None
        session_store = FakeStore()

        def restore_snapshot(self, _snapshot: SessionSnapshot) -> None:
            calls.append("restore")

        def save_snapshot(self) -> Path:
            calls.append(f"save:{self.runtime_state}")
            return tmp_path / "session.json"

        async def handle_input(self, _text: str) -> LoopResult:
            return LoopResult(LoopStatus.WAITING, "done", 1)

    monkeypatch.setattr("nano_vibe.gui.agent_runner.Session.from_config", lambda *_args, **_kwargs: FakeSession())
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")
    runner = GuiAgentRunner(cast(AppConfig, object()), lambda _session_id: tmp_path)
    events: list[str] = []

    async def emit(name: str, _payload: dict[str, Any]) -> None:
        events.append(name)
        if name == "runtime_state":
            assert "restore" in calls

    await runner("session-1", "second", emit, asyncio.Event())
    assert events[0] == "runtime_state"


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
