"""Versioned UI events and bounded per-session replay buffers."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UIEvent:
    """A versioned event sent from the GUI service to a browser client."""

    session_id: str
    run_id: str | None
    seq: int
    type: str
    timestamp: str = field(default_factory=_now)
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> UIEvent:
        if value.get("version") != 1:
            raise ValueError(f"unsupported UI event version: {value.get('version')!r}")
        required = ("session_id", "run_id", "seq", "type", "timestamp", "payload")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"missing UI event fields: {', '.join(missing)}")
        return cls(
            session_id=str(value["session_id"]),
            run_id=str(value["run_id"]) if value.get("run_id") is not None else None,
            seq=int(value["seq"]),
            type=str(value["type"]),
            timestamp=str(value["timestamp"]),
            payload=dict(value["payload"]),
            version=1,
        )

    @classmethod
    def from_json(cls, value: str) -> UIEvent:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise TypeError("UI event JSON must contain an object")
        return cls.from_dict(decoded)


@dataclass(frozen=True)
class EventReplay:
    events: tuple[UIEvent, ...] = ()
    resync_required: bool = False


class SessionEventBuffer:
    """Bounded in-memory event history with independent session sequences."""

    def __init__(self, *, max_events: int = 5_000, max_bytes: int = 10 * 1024 * 1024) -> None:
        if max_events < 1 or max_bytes < 1:
            raise ValueError("event buffer limits must be positive")
        self.max_events = max_events
        self.max_bytes = max_bytes
        self._events: dict[str, deque[UIEvent]] = defaultdict(deque)
        self._bytes: dict[str, int] = defaultdict(int)
        self._next_seq: dict[str, int] = defaultdict(lambda: 1)

    def append(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> UIEvent:
        seq = self._next_seq[session_id]
        event = UIEvent(session_id, run_id, seq, event_type, payload=payload)
        self._next_seq[session_id] = seq + 1
        queue = self._events[session_id]
        queue.append(event)
        self._bytes[session_id] += self._event_size(event)
        while len(queue) > self.max_events or self._bytes[session_id] > self.max_bytes:
            removed = queue.popleft()
            self._bytes[session_id] -= self._event_size(removed)
        return event

    def events(self, session_id: str) -> tuple[UIEvent, ...]:
        return tuple(self._events.get(session_id, ()))

    def size_bytes(self, session_id: str) -> int:
        return self._bytes.get(session_id, 0)

    def replay(self, session_id: str, last_seq: int | None) -> EventReplay:
        events = self._events.get(session_id)
        if not events:
            return EventReplay()
        oldest = events[0].seq
        requested = 0 if last_seq is None else last_seq
        if requested < oldest - 1:
            return EventReplay(resync_required=True)
        return EventReplay(tuple(event for event in events if event.seq > requested))

    @staticmethod
    def _event_size(event: UIEvent) -> int:
        return len(event.to_json().encode("utf-8"))
