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
async def test_web_search_reports_missing_tavily_configuration() -> None:
    result = await WebSearchTool().execute({"query": "python"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code in {"tavily_not_configured", "tavily_dependency_missing"}
