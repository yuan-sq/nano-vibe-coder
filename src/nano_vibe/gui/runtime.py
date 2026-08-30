"""Runtime state and process-safe coordination primitives for the GUI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - V3 currently targets Unix local hosts.
    fcntl = None  # type: ignore[assignment]


class RuntimeState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AWAITING_INPUT = "AWAITING_INPUT"
    STOPPING = "STOPPING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PendingInteraction:
    interaction_id: str
    kind: str
    content: str
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    capability: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"approval", "user_request"}:
            raise ValueError("pending interaction kind must be approval or user_request")

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "kind": self.kind,
            "content": self.content,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "capability": self.capability,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "options": list(self.options),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PendingInteraction:
        return cls(
            interaction_id=str(value["interaction_id"]),
            kind=str(value["kind"]),
            content=str(value["content"]),
            tool_name=str(value["tool_name"]) if value.get("tool_name") is not None else None,
            arguments=dict(value.get("arguments") or {}),
            capability=(
                str(value["capability"]) if value.get("capability") is not None else None
            ),
            reason=str(value["reason"]) if value.get("reason") is not None else None,
            idempotency_key=(
                str(value["idempotency_key"])
                if value.get("idempotency_key") is not None
                else None
            ),
            options=tuple(str(option) for option in value.get("options", [])),
        )

    @classmethod
    def from_json(cls, value: str) -> PendingInteraction:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("pending interaction JSON must contain an object")
        return cls.from_dict(decoded)


class LockAcquisitionError(RuntimeError):
    """Raised when another process already owns the global run lock."""


class GlobalRunLock:
    """Advisory cross-process lock that is released when its file descriptor closes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            raise LockAcquisitionError("run lock is already held by this instance")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is None:  # pragma: no cover - defensive for unsupported platforms.
                raise LockAcquisitionError("cross-process run locks require a Unix host")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockAcquisitionError("run lock is already held") from exc
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode())
            self._fd = fd
        except Exception:
            os.close(fd)
            raise

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> GlobalRunLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
