import pytest

from nano_vibe.agent.state import AgentState, StateMachine
from nano_vibe.tools.transition import TransitionTool
from nano_vibe.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_transition_tool_moves_state() -> None:
    machine = StateMachine()
    result = await TransitionTool(machine).execute({"target_state": "PLAN"})

    assert result.ok is True
    assert result.output == "State changed to PLAN."
    assert machine.current is AgentState.PLAN


@pytest.mark.asyncio
async def test_transition_tool_returns_invalid_transition_as_failure() -> None:
    result = await TransitionTool(StateMachine()).execute({"target_state": "VERIFY"})

    assert result.ok is False
    assert "REQUIREMENTS" in result.output


@pytest.mark.asyncio
async def test_web_search_is_an_explicit_placeholder() -> None:
    result = await WebSearchTool().execute({"query": "python"})

    assert result.ok is False
    assert "not implemented" in result.output.lower()
