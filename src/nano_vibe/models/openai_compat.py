"""OpenAI-compatible streaming model adapter."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Callable

from openai import AsyncOpenAI

from nano_vibe.config import ModelConfig

from .base import ModelResponse, ToolCall


class ModelError(RuntimeError):
    """Raised after all model request attempts fail."""


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def assemble_stream(chunks: Iterable[Any]) -> ModelResponse:
    """Combine streamed text and tool-call deltas into one response."""

    content_parts: list[str] = []
    tool_data: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"id": "", "name": "", "arguments": ""}
    )
    usage: Mapping[str, int] | None = None

    for chunk in chunks:
        chunk_usage = _value(chunk, "usage")
        if chunk_usage is not None:
            usage = {
                key: int(_value(chunk_usage, key, 0))
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if _value(chunk_usage, key) is not None
            }
        choices = _value(chunk, "choices", []) or []
        if not choices:
            continue
        delta = _value(choices[0], "delta")
        if delta is None:
            continue
        text = _value(delta, "content")
        if text:
            content_parts.append(text)
        for call_delta in _value(delta, "tool_calls", []) or []:
            index = int(_value(call_delta, "index", 0))
            function = _value(call_delta, "function")
            if function is None:
                continue
            item = tool_data[index]
            item["id"] += _value(call_delta, "id", "") or ""
            item["name"] += _value(function, "name", "") or ""
            item["arguments"] += _value(function, "arguments", "") or ""

    calls: list[ToolCall] = []
    for index in sorted(tool_data):
        item = tool_data[index]
        raw_arguments = item["arguments"] or "{}"
        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
            parse_error = None
        except (TypeError, ValueError) as exc:
            arguments = {}
            parse_error = str(exc)
        calls.append(
            ToolCall(
                id=item["id"] or f"call-{index}",
                name=item["name"],
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return ModelResponse(content="".join(content_parts), tool_calls=calls, usage=usage)


class OpenAICompatibleModel:
    """Use an OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        config: ModelConfig,
        retries: int = 5,
        on_text: Callable[[str], None] | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self.retries = max(1, retries)
        self.on_text = on_text
        self.client = client or AsyncOpenAI(api_key=config.api_key or None, base_url=config.url)

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                return await self._complete_once(messages, tools)
            except Exception as exc:  # provider errors are intentionally retried
                last_error = exc
                if attempt + 1 < self.retries:
                    await asyncio.sleep(min(2**attempt, 8))
        raise ModelError(f"model request failed after {self.retries} attempts: {last_error}") from last_error

    async def _complete_once(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": list(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = list(tools)
        if self.config.reasoning_level:
            request["reasoning_effort"] = self.config.reasoning_level
        stream = await self.client.chat.completions.create(**request)
        chunks: list[Any] = []
        async for chunk in stream:
            chunks.append(chunk)
            choices = _value(chunk, "choices", []) or []
            if self.on_text is not None and choices:
                delta = _value(choices[0], "delta")
                text = _value(delta, "content", "")
                if text:
                    self.on_text(text)
        return assemble_stream(chunks)
