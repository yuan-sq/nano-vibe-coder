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

    machine.mark_agents_updated()
    machine.transition(AgentState.DONE)
    assert machine.current is AgentState.DONE


def test_tool_permissions_depend_on_current_state() -> None:
    machine = StateMachine()

    assert machine.allowed_tools() == {
        "shell",
        "user_request",
        "transition_state",
        "web_search",
    }
    machine.transition(AgentState.PLAN)
    assert "apply_patch" not in machine.allowed_tools()
    machine.transition(AgentState.IMPLEMENT)
    assert "apply_patch" in machine.allowed_tools()
    machine.transition(AgentState.VERIFY)
    assert "apply_patch" not in machine.allowed_tools()
    assert "update_agents" in machine.allowed_tools()
