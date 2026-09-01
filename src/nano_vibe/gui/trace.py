"""Bounded, filterable reads of append-only V2 trace JSONL files."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TracePage:
    items: list[dict[str, Any]]
    total: int
    next_offset: int = 0
    has_more: bool = False


MAX_TRACE_PAGE_SIZE = 200


def read_trace(
    path: str | Path,
    *,
    event: str | None = None,
    offset: int = 0,
    limit: int = 100,
    tail: bool = False,
) -> TracePage:
    if offset < 0 or limit < 1:
        raise ValueError("offset must be non-negative and limit must be positive")
    page_limit = min(limit, MAX_TRACE_PAGE_SIZE)
    if tail:
        matches_tail: deque[dict[str, Any]] = deque(maxlen=page_limit)
        total = 0
        trace_path = Path(path)
        if not trace_path.exists():
            return TracePage([], 0, offset, False)
        with trace_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    # TraceWriter appends one line at a time; an interrupted final
                    # write is therefore safe to ignore on the next read.
                    continue
                if not isinstance(value, dict):
                    continue
                if event is not None and value.get("event") != event:
                    continue
                matches_tail.append(value)
                total += 1
        return TracePage(list(matches_tail), total, total, False)
    matches: list[dict[str, Any]] = []
    total = 0
    trace_path = Path(path)
    if not trace_path.exists():
        return TracePage([], 0, offset, False)
    with trace_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # TraceWriter appends one line at a time; an interrupted final
                # write is therefore safe to ignore on the next read.
                continue
            if not isinstance(value, dict):
                continue
            if event is not None and value.get("event") != event:
                continue
            if total >= offset and len(matches) < page_limit:
                matches.append(value)
            total += 1
    next_offset = offset + len(matches)
    return TracePage(matches, total, next_offset, next_offset < total)
