import json
from pathlib import Path

import pytest

from nano_vibe.session_store import (
    CURRENT_SNAPSHOT_VERSION,
    SessionSnapshot,
    SessionStore,
    SessionStoreError,
)


def test_session_store_round_trips_json_snapshot(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    snapshot = SessionSnapshot(
        session_id="session-1",
        workspace=str(tmp_path / "repo"),
        permission_mode="normal",
        state="PLAN",
        plan=[{"id": "one", "content": "Inspect", "status": "completed"}],
        history=[{"role": "user", "content": "hello"}],
        summary="handoff",
        turns=2,
        tool_errors=0,
        idempotency_records={"shell:call-1": {"result": {"ok": True}}},
        runtime_state="AWAITING_APPROVAL",
        pending_interaction={"interaction_id": "a-1", "kind": "approval"},
    )

    path = store.save(snapshot)
    loaded = store.load("session-1")

    assert path == tmp_path / "sessions" / "session-1.json"
    assert loaded["version"] == CURRENT_SNAPSHOT_VERSION
    assert loaded["plan"][0]["status"] == "completed"
    assert loaded["history"] == snapshot.history
    assert loaded.runtime_state == "AWAITING_APPROVAL"
    assert loaded.pending_interaction == {"interaction_id": "a-1", "kind": "approval"}


def test_session_snapshot_redacts_sensitive_mapping_keys() -> None:
    snapshot = SessionSnapshot(
        session_id="secret-test",
        history=[{"role": "tool", "api_key": "do-not-store"}],
        idempotency_records={"key": {"authorization": "Bearer secret"}},
    )

    data = snapshot.to_dict()

    assert data["history"][0]["api_key"] == "[REDACTED]"
    assert data["idempotency_records"]["key"]["authorization"] == "[REDACTED]"


def test_session_store_rejects_corrupt_and_unknown_version(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "bad.json").write_text("not json", encoding="utf-8")

    with pytest.raises(SessionStoreError, match="invalid JSON"):
        store.load("bad")

    (tmp_path / "sessions" / "future.json").write_text(
        json.dumps({"version": CURRENT_SNAPSHOT_VERSION + 1}), encoding="utf-8"
    )
    with pytest.raises(SessionStoreError, match="version"):
        store.load("future")

    (tmp_path / "sessions" / "fields.json").write_text(
        json.dumps({"version": CURRENT_SNAPSHOT_VERSION, "session_id": "fields", "turns": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(SessionStoreError, match="turns"):
        store.load("fields")


def test_session_store_lists_only_valid_snapshot_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(SessionSnapshot(session_id="one", workspace=str(tmp_path), state="PLAN"))

    sessions = store.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "one"
    assert sessions[0]["state"] == "PLAN"


def test_session_store_compatibility_method_names_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    snapshot = SessionSnapshot(session_id="one", workspace=str(tmp_path))

    store.save_session(snapshot)
    loaded = store.load_session("one")

    assert loaded.session_id == "one"
