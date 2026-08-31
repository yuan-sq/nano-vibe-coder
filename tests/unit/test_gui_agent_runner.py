import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from nano_vibe.agent.loop import LoopResult, LoopStatus
from nano_vibe.agent.state import AgentState
from nano_vibe.config import AppConfig
from nano_vibe.gui.agent_runner import GuiAgentRunner, InteractionBroker
from nano_vibe.session_store import SessionSnapshot


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
            return LoopResult(LoopStatus.WAITING, "done", AgentState.PLAN)

    monkeypatch.setattr(
        "nano_vibe.gui.agent_runner.Session.from_config",
        lambda *_args, **_kwargs: FakeSession(),
    )
    runner = GuiAgentRunner(cast(AppConfig, object()), lambda _session_id: tmp_path)

    async def emit(_name: str, _payload: dict[str, Any]) -> None:
        return

    await runner("session-1", "second", emit, asyncio.Event())

    assert calls[:3] == ["load", "restore", "save:RUNNING"]
