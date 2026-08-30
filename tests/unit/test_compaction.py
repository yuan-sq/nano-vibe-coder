import pytest

from nano_vibe.agent.compaction import ContextCompactor


class CharacterTokenizer:
    def count(self, messages: list[dict[str, str]]) -> int:
        return sum(len(message.get("content", "")) for message in messages)


@pytest.mark.asyncio
async def test_compactor_leaves_short_history_unchanged() -> None:
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}]
    calls: list[list[dict[str, str]]] = []

    async def summarize(older: list[dict[str, str]]) -> str:
        calls.append(older)
        return "summary"

    compactor = ContextCompactor(CharacterTokenizer(), context_window=100)
    result = await compactor.maybe_compact(messages, summarize)

    assert result == messages
    assert calls == []


@pytest.mark.asyncio
async def test_compactor_summarizes_old_messages_and_keeps_system_and_recent_context() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old requirement " * 4},
        {"role": "assistant", "content": "old plan " * 4},
        {"role": "user", "content": "latest question"},
    ]
    calls: list[list[dict[str, str]]] = []

    async def summarize(older: list[dict[str, str]]) -> str:
        calls.append(older)
        return "A concise handoff."

    compactor = ContextCompactor(
        CharacterTokenizer(), context_window=100, compact_ratio=0.75, target_ratio=0.5
    )
    result = await compactor.maybe_compact(messages, summarize)

    assert len(calls) == 1
    assert result[0] == messages[0]
    assert result[1]["role"] == "system"
    assert "A concise handoff." in result[1]["content"]
    assert result[-1] == messages[-1]
    assert result[-1] not in calls[0]
