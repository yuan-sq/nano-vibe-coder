import json
import multiprocessing
from pathlib import Path
from typing import Any

import pytest

from nano_vibe.gui.events import SessionEventBuffer, UIEvent
from nano_vibe.gui.runtime import (
    GlobalRunLock,
    LockAcquisitionError,
    PendingInteraction,
    RuntimeState,
)


def test_ui_event_round_trips_as_versioned_json() -> None:
    event = UIEvent(
        session_id="session-1",
        run_id="run-1",
        seq=7,
        type="model_delta",
        timestamp="2026-08-31T00:00:00+00:00",
        payload={"text": "你好", "index": 1},
    )

    encoded = event.to_json()
    assert json.loads(encoded)["version"] == 1
    assert UIEvent.from_json(encoded) == event


def test_event_buffer_assigns_monotonic_sequence_per_session() -> None:
    buffer = SessionEventBuffer()

    first = buffer.append("session-1", "run-1", "run_started", {"ok": True})
    second = buffer.append("session-1", "run-1", "run_finished", {"ok": True})
    other = buffer.append("session-2", "run-2", "run_started", {})

    assert (first.seq, second.seq, other.seq) == (1, 2, 1)
    assert first.session_id == second.session_id == "session-1"


def test_event_buffer_evicts_old_events_at_count_limit() -> None:
    buffer = SessionEventBuffer(max_events=2, max_bytes=1024 * 1024)
    buffer.append("session-1", "run-1", "one", {})
    buffer.append("session-1", "run-1", "two", {})
    buffer.append("session-1", "run-1", "three", {})

    result = buffer.replay("session-1", 0)
    assert result.resync_required is True
    assert [event.seq for event in buffer.events("session-1")] == [2, 3]


def test_event_buffer_evicts_old_events_at_byte_limit() -> None:
    buffer = SessionEventBuffer(max_events=5000, max_bytes=500)
    buffer.append("session-1", "run-1", "one", {"text": "a" * 150})
    buffer.append("session-1", "run-1", "two", {"text": "b" * 150})
    buffer.append("session-1", "run-1", "three", {"text": "c" * 150})

    events = buffer.events("session-1")
    assert len(events) < 3
    assert buffer.size_bytes("session-1") <= 500


def test_event_buffer_replays_events_after_last_sequence() -> None:
    buffer = SessionEventBuffer()
    buffer.append("session-1", "run-1", "one", {})
    buffer.append("session-1", "run-1", "two", {})

    result = buffer.replay("session-1", 1)
    assert result.resync_required is False
    assert [event.seq for event in result.events] == [2]


def test_pending_interaction_round_trips_approval_json() -> None:
    interaction = PendingInteraction(
        interaction_id="interaction-1",
        kind="approval",
        content="允许执行命令吗？",
        tool_name="shell",
        arguments={"command": "git status"},
        capability="shell",
        reason="需要读取仓库状态",
        idempotency_key="approval:interaction-1",
    )

    assert PendingInteraction.from_json(interaction.to_json()) == interaction


def test_runtime_state_contains_gui_run_states() -> None:
    assert [state.value for state in RuntimeState] == [
        "IDLE",
        "RUNNING",
        "AWAITING_APPROVAL",
        "AWAITING_INPUT",
        "STOPPING",
        "PAUSED",
        "ERROR",
    ]


def test_global_run_lock_rejects_same_process_competition_and_reacquires(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    first = GlobalRunLock(path)
    second = GlobalRunLock(path)

    first.acquire()
    with pytest.raises(LockAcquisitionError, match="already held"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def _acquire_lock_in_child(path: str, result: Any) -> None:
    lock = GlobalRunLock(path)
    try:
        lock.acquire()
    except LockAcquisitionError:
        result.put(False)
    else:
        result.put(True)
        lock.release()


def test_global_run_lock_rejects_cross_process_competition(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    lock = GlobalRunLock(path)
    lock.acquire()
    try:
        context = multiprocessing.get_context("fork")
        result: multiprocessing.Queue[bool] = context.Queue()
        process = context.Process(target=_acquire_lock_in_child, args=(str(path), result))
        process.start()
        process.join(timeout=5)
        assert process.exitcode == 0
        assert result.get(timeout=1) is False
    finally:
        lock.release()
