
import pytest

from nano_vibe.tools.user_request import UserRequestTool


@pytest.mark.asyncio
async def test_user_request_returns_callback_answer_and_options() -> None:
    seen: list[tuple[str, list[str]]] = []

    async def ask(question: str, options: list[str]) -> str:
        seen.append((question, options))
        return "custom answer"

    tool = UserRequestTool(ask)
    result = await tool.execute({"question": "Which?", "options": ["A", "B"]})

    assert result.ok is True
    assert result.output == "custom answer"
    assert result.metadata["question"] == "Which?"
    assert seen == [("Which?", ["A", "B"])]


@pytest.mark.asyncio
async def test_user_request_rejects_invalid_option_count() -> None:
    async def ask(_: str, __: list[str]) -> str:
        raise AssertionError("callback must not run")

    tool = UserRequestTool(ask)
    result = await tool.execute({"question": "Which?", "options": ["A"]})

    assert result.ok is False
    assert "2" in result.output and "4" in result.output
