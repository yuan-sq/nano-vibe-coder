from types import SimpleNamespace
from typing import Any

import pytest

from nano_vibe.config import ModelConfig
from nano_vibe.models.openai_compat import OpenAICompatibleModel


def stream_chunk(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))],
        usage=None,
    )


class FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> Any:
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failures = 1

    async def create(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary")
        return FakeStream([stream_chunk("hello"), stream_chunk(" world")])


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


@pytest.mark.asyncio
async def test_openai_compatible_model_retries_and_streams_text() -> None:
    config = ModelConfig("demo", "https://example.test/v1", "model", api_key="secret")
    client = FakeClient()
    streamed: list[str] = []
    model = OpenAICompatibleModel(config, retries=2, on_text=streamed.append, client=client)

    response = await model.complete([{"role": "user", "content": "hi"}], [])

    assert response.content == "hello world"
    assert streamed == ["hello", " world"]
    assert len(client.chat.completions.calls) == 2
    assert client.chat.completions.calls[-1]["model"] == "model"
    assert client.chat.completions.calls[-1]["reasoning_effort"] == "medium"
