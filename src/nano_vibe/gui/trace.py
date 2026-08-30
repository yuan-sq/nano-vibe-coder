"""Bounded, filterable reads of append-only V2 trace JSONL files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TracePage:
    items: list[dict[str, Any]]
    total: int


def read_trace(
    path: str | Path,
    *,
    event: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> TracePage:
    if offset < 0 or limit < 1:
        raise ValueError("offset must be non-negative and limit must be positive")
    matches: list[dict[str, Any]] = []
    total = 0
    trace_path = Path(path)
    if not trace_path.exists():
        return TracePage([], 0)
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if event is not None and value.get("event") != event:
            continue
        if total >= offset and len(matches) < limit:
            matches.append(value)
        total += 1
    return TracePage(matches, total)
