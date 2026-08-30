"""Versioned, atomic JSON persistence for interactive sessions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CURRENT_SNAPSHOT_VERSION = 1
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SENSITIVE_KEYS = {"api_key", "access_token", "authorization", "password", "secret"}


class SessionStoreError(ValueError):
    """Raised when a session snapshot cannot be safely loaded or written."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SessionStoreError(f"session snapshot {field_name} must be a non-negative integer")
    return value


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(child_key): _redact_value(str(child_key), child_value) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


@dataclass
class SessionSnapshot:
    session_id: str
    workspace: str = ""
    permission_mode: str = "normal"
    state: str = "REQUIREMENTS"
    agents_updated: bool = False
    plan: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    summary: str | None = None
    turns: int = 0
    tool_errors: int = 0
    idempotency_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    loaded_skills: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_timestamp)
    version: int = CURRENT_SNAPSHOT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "workspace": self.workspace,
            "permission_mode": self.permission_mode,
            "state": self.state,
            "agents_updated": self.agents_updated,
            "plan": [_redact_value("plan", dict(item)) for item in self.plan],
            "history": [_redact_value("history", dict(message)) for message in self.history],
            "summary": self.summary,
            "turns": self.turns,
            "tool_errors": self.tool_errors,
            "idempotency_records": {
                str(key): _redact_value("record", dict(value))
                for key, value in self.idempotency_records.items()
            },
            "loaded_skills": list(self.loaded_skills),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionSnapshot:
        version = value.get("version", CURRENT_SNAPSHOT_VERSION)
        if version != CURRENT_SNAPSHOT_VERSION:
            raise SessionStoreError(f"unsupported session snapshot version: {version}")
        session_id = value.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise SessionStoreError("session_id must be a safe non-empty identifier")
        workspace = value.get("workspace", "")
        permission_mode = value.get("permission_mode", "normal")
        state = value.get("state", "REQUIREMENTS")
        if not all(isinstance(item, str) for item in (workspace, permission_mode, state)):
            raise SessionStoreError("session snapshot has invalid string fields")
        plan = value.get("plan", [])
        history = value.get("history", [])
        records = value.get("idempotency_records", {})
        loaded_skills = value.get("loaded_skills", [])
        agents_updated = value.get("agents_updated", False)
        summary = value.get("summary")
        if not isinstance(plan, list) or not isinstance(history, list):
            raise SessionStoreError("session snapshot plan and history must be arrays")
        if not isinstance(records, Mapping) or not isinstance(loaded_skills, list):
            raise SessionStoreError("session snapshot has invalid persisted records")
        if not isinstance(agents_updated, bool):
            raise SessionStoreError("session snapshot agents_updated must be boolean")
        if summary is not None and not isinstance(summary, str):
            raise SessionStoreError("session snapshot summary must be a string or null")
        if any(not isinstance(item, Mapping) for item in plan + history):
            raise SessionStoreError("session snapshot plan and history items must be objects")
        if any(not isinstance(item, str) for item in loaded_skills):
            raise SessionStoreError("session snapshot loaded_skills must contain strings")
        if any(not isinstance(item, Mapping) for item in records.values()):
            raise SessionStoreError("session snapshot idempotency records must be objects")
        return cls(
            version=version,
            session_id=session_id,
            workspace=workspace,
            permission_mode=permission_mode,
            state=state,
            agents_updated=agents_updated,
            plan=[dict(item) for item in plan if isinstance(item, Mapping)],
            history=[dict(item) for item in history if isinstance(item, Mapping)],
            summary=summary,
            turns=_snapshot_int(value.get("turns", 0), "turns"),
            tool_errors=_snapshot_int(value.get("tool_errors", 0), "tool_errors"),
            idempotency_records={
                str(key): dict(item)
                for key, item in records.items()
                if isinstance(item, Mapping)
            },
            loaded_skills=[str(item) for item in loaded_skills if isinstance(item, str)],
            updated_at=str(value.get("updated_at", _timestamp())),
        )

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


class SessionStore:
    """Persist snapshots beneath a caller-selected directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve()

    def path_for(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise SessionStoreError("invalid session id")
        return self.directory / f"{session_id}.json"

    def save(self, snapshot: SessionSnapshot | Mapping[str, Any]) -> Path:
        if isinstance(snapshot, SessionSnapshot):
            data = snapshot.to_dict()
        elif isinstance(snapshot, Mapping):
            data = SessionSnapshot.from_dict(snapshot).to_dict()
        else:
            raise SessionStoreError("snapshot must be a SessionSnapshot or mapping")
        parsed = SessionSnapshot.from_dict(data)
        target = self.path_for(parsed.session_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{parsed.session_id}.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(parsed.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return target

    save_session = save

    def load(self, session_id: str) -> SessionSnapshot:
        path = self.path_for(session_id)
        if not path.is_file():
            raise SessionStoreError(f"session snapshot not found: {session_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                raise SessionStoreError(f"invalid JSON in session snapshot: {session_id}") from exc
            raise SessionStoreError(f"could not read session snapshot: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise SessionStoreError("session snapshot root must be an object")
        snapshot = SessionSnapshot.from_dict(raw)
        if snapshot.session_id != session_id:
            raise SessionStoreError("session id does not match snapshot filename")
        return snapshot

    load_session = load

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                snapshot = self.load(path.stem)
            except SessionStoreError:
                continue
            result.append(
                {
                    "session_id": snapshot.session_id,
                    "workspace": snapshot.workspace,
                    "permission_mode": snapshot.permission_mode,
                    "state": snapshot.state,
                    "updated_at": snapshot.updated_at,
                    "version": snapshot.version,
                }
            )
        return result

    def delete(self, session_id: str) -> None:
        path = self.path_for(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return
