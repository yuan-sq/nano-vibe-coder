import pytest

from nano_vibe.agent.plan import PlanTodoList, TodoStatus
from nano_vibe.agent.state import AgentState, StateMachine, InvalidTransition
from nano_vibe.tools.update_plan import UpdatePlanTool


def in_verify(machine: StateMachine | None = None) -> StateMachine:
    machine = machine or StateMachine()
    machine.transition(AgentState.PLAN)
    machine.transition(AgentState.IMPLEMENT)
    machine.transition(AgentState.VERIFY)
    return machine


def complete_plan(machine: StateMachine) -> None:
    machine.plan.replace(
        [
            {"id": "verify", "content": "Run verification", "status": "completed"},
        ]
    )
    machine.mark_agents_updated()


def test_plan_rejects_multiple_in_progress_items() -> None:
    plan = PlanTodoList()

    with pytest.raises(ValueError, match="in_progress"):
        plan.replace(
            [
                {"id": "one", "content": "One", "status": "in_progress"},
                {"id": "two", "content": "Two", "status": "in_progress"},
            ]
        )


def test_plan_rejects_unknown_status_and_empty_plan_cannot_complete() -> None:
    plan = PlanTodoList()

    with pytest.raises(ValueError, match="status"):
        plan.replace([{"id": "one", "content": "One", "status": "blocked"}])
    plan.replace([])
    assert plan.all_completed is False


@pytest.mark.asyncio
async def test_update_plan_tool_updates_structured_plan() -> None:
    machine = StateMachine()
    machine.transition(AgentState.PLAN)

    result = await UpdatePlanTool(machine).execute(
        {
            "items": [
                {"id": "inspect", "content": "Inspect code", "status": "in_progress"},
                {"id": "test", "content": "Run tests", "status": "pending"},
            ]
        }
    )

    assert result.ok is True
    assert machine.plan.items[0].status is TodoStatus.IN_PROGRESS
    assert result.metadata["plan"][1]["id"] == "test"


def test_done_requires_all_plan_items_completed() -> None:
    machine = in_verify()
    machine.plan.replace([{"id": "verify", "content": "Run tests", "status": "pending"}])
    machine.mark_agents_updated()

    with pytest.raises(InvalidTransition, match="Plan"):
        machine.transition(AgentState.DONE)

    machine.plan.replace(
        [{"id": "verify", "content": "Run tests", "status": "completed"}]
    )
    machine.transition(AgentState.DONE)
    assert machine.current is AgentState.DONE


def test_done_still_requires_agents_review_before_plan_check() -> None:
    machine = in_verify()
    complete_plan(machine)
    machine.agents_updated = False

    with pytest.raises(InvalidTransition, match="AGENTS"):
        machine.transition(AgentState.DONE)
