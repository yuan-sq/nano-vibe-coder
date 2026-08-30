"""Token-budget based conversation compaction."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol


class Tokenizer(Protocol):
    def count(self, messages: Any) -> int: ...


class ApproximateTokenizer:
    """Portable fallback used until a model-specific tokenizer is configured."""

    def count(self, messages: Sequence[dict[str, Any]]) -> int:
        serialized = json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))
        return max(1, len(serialized) // 4)


Summarizer = Callable[[list[dict[str, Any]]], Awaitable[str]]


class ContextCompactor:
    def __init__(
        self,
        tokenizer: Tokenizer,
        context_window: int,
        compact_ratio: float = 0.75,
        target_ratio: float = 0.50,
    ) -> None:
        if context_window <= 0:
            raise ValueError("context_window must be positive")
        if not 0 < target_ratio < compact_ratio < 1:
            raise ValueError("target_ratio must be smaller than compact_ratio and both below 1")
        self.tokenizer = tokenizer
        self.context_window = context_window
        self.compact_ratio = compact_ratio
        self.target_ratio = target_ratio

    async def maybe_compact(
        self, messages: Sequence[dict[str, Any]], summarize: Summarizer
    ) -> list[dict[str, Any]]:
        current = list(messages)
        if self.tokenizer.count(current) < self.context_window * self.compact_ratio:
            return current

        system = current[:1] if current and current[0].get("role") == "system" else []
        body = current[1:] if system else current
        target_tokens = max(1, int(self.context_window * self.target_ratio))

        keep: list[dict[str, Any]] = []
        for message in reversed(body):
            candidate = system + list(reversed([message, *keep]))
            if keep and self.tokenizer.count(candidate) > target_tokens:
                break
            if not keep or self.tokenizer.count(candidate) <= target_tokens:
                keep.insert(0, message)
        if not keep and body:
            keep = [body[-1]]

        older_count = len(body) - len(keep)
        if older_count <= 0:
            return current
        older = body[:older_count]
        summary = await summarize(older)
        summary_message = {
            "role": "system",
            "content": f"Previous context summary:\n{summary}",
        }
        return system + [summary_message] + keep
