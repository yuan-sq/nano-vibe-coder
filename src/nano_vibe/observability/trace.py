"""Append-only JSONL run tracing with basic secret redaction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {"api_key", "access_token", "authorization", "password", "secret"}


class TraceWriter:
    def __init__(self, path: str | Path, session_id: str) -> None:
        self.path = Path(path)
        self.session_id = session_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **fields: Any) -> None:
        if not event.strip():
            raise ValueError("event must not be empty")
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **{key: _redact(key, value) for key, value in fields.items()},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _redact(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {child_key: _redact(child_key, child_value) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_redact(key, child) for child in value]
    return value
