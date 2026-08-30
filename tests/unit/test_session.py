from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from nano_vibe.agent.loop import LoopStatus
from nano_vibe.models.base import ModelResponse
from nano_vibe.session import Session


class PlainModel:
    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        del messages, tools
        return ModelResponse(content="waiting for more input")


@pytest.mark.asyncio
async def test_session_delegates_user_input_to_agent_loop(tmp_path: Path) -> None:
    session = Session(PlainModel(), tmp_path)

    result = await session.handle_input("Inspect this repository")

    assert result.status is LoopStatus.WAITING
    assert result.message == "waiting for more input"


def test_session_applies_shell_runtime_limits(tmp_path: Path) -> None:
    session = Session(
        PlainModel(),
        tmp_path,
        shell_timeout_seconds=7,
        shell_max_output_chars=123,
    )

    shell = session.registry._tools["shell"]
    assert shell.timeout_seconds == 7
    assert shell.max_output_chars == 123
