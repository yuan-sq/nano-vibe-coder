from pathlib import Path

import pytest

from nano_vibe.agent.state import AgentState, StateMachine
from nano_vibe.tools.update_agents import UpdateAgentsTool


def in_verify() -> StateMachine:
    machine = StateMachine()
    machine.transition(AgentState.PLAN)
    machine.transition(AgentState.IMPLEMENT)
    machine.transition(AgentState.VERIFY)
    return machine


@pytest.mark.asyncio
async def test_update_agents_creates_file_and_marks_review(tmp_path: Path) -> None:
    machine = in_verify()
    content = "# Project rules\n\nRun pytest before committing.\n"

    result = await UpdateAgentsTool(tmp_path, machine).execute({"content": content})

    assert result.ok is True
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == content
    assert machine.agents_updated is True


@pytest.mark.asyncio
async def test_update_agents_allows_unchanged_review(tmp_path: Path) -> None:
    machine = in_verify()
    content = "# Existing\n"
    (tmp_path / "AGENTS.md").write_text(content, encoding="utf-8")

    result = await UpdateAgentsTool(tmp_path, machine).execute({"content": content})

    assert result.ok is True
    assert result.metadata["changed"] is False
    assert machine.agents_updated is True


@pytest.mark.asyncio
async def test_update_agents_is_rejected_outside_verify(tmp_path: Path) -> None:
    result = await UpdateAgentsTool(tmp_path, StateMachine()).execute(
        {"content": "# Rules\n"}
    )

    assert result.ok is False
    assert "VERIFY" in result.output
