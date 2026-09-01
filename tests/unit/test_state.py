import pytest

from nano_vibe.agent.state import AgentState, InvalidTransition, StateMachine


def test_state_machine_follows_forward_and_meaningful_backwards_paths() -> None:
    machine = StateMachine()

    assert machine.current is AgentState.REQUIREMENTS
    machine.transition(AgentState.PLAN)
    machine.transition(AgentState.IMPLEMENT)
    machine.transition(AgentState.PLAN)
    machine.transition(AgentState.IMPLEMENT)
    machine.transition(AgentState.VERIFY)
    machine.transition(AgentState.PLAN)

    assert machine.current is AgentState.PLAN


def test_state_machine_rejects_unrelated_transition() -> None:
    machine = StateMachine()

    with pytest.raises(InvalidTransition, match="REQUIREMENTS.*VERIFY"):
        machine.transition(AgentState.VERIFY)


def test_done_requires_agents_review() -> None:
    machine = StateMachine()
    for state in (AgentState.PLAN, AgentState.IMPLEMENT, AgentState.VERIFY):
        machine.transition(state)

    with pytest.raises(InvalidTransition, match="AGENTS"):
        machine.transition(AgentState.DONE)

    machine.plan.replace(
        [{"id": "verify", "content": "Run verification", "status": "completed"}]
    )
    machine.mark_agents_updated()
    machine.transition(AgentState.DONE)
    assert machine.current is AgentState.DONE


def test_tool_permissions_depend_on_current_state() -> None:
    machine = StateMachine()
    base_tools = {
        "shell",
        "list",
        "read",
        "user_request",
        "transition_state",
        "web_search",
        "web_extract",
        "load_skill",
        "read_skill",
        "unload_skill",
    }

    assert machine.allowed_tools() == base_tools
    machine.transition(AgentState.PLAN)
    assert machine.allowed_tools() == base_tools | {"update_plan"}
    machine.transition(AgentState.IMPLEMENT)
    assert machine.allowed_tools() == base_tools | {"apply_patch", "update_plan", "write"}
    machine.transition(AgentState.VERIFY)
    assert machine.allowed_tools() == base_tools | {"update_agents", "update_plan"}
