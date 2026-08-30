"""Task state machine and phase-level tool permissions."""

from __future__ import annotations

from enum import Enum

from .plan import PlanTodoList


class AgentState(str, Enum):
    REQUIREMENTS = "REQUIREMENTS"
    PLAN = "PLAN"
    IMPLEMENT = "IMPLEMENT"
    VERIFY = "VERIFY"
    DONE = "DONE"


class InvalidTransition(ValueError):
    """Raised when a state transition is not allowed."""


_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.REQUIREMENTS: frozenset({AgentState.PLAN}),
    AgentState.PLAN: frozenset({AgentState.IMPLEMENT}),
    AgentState.IMPLEMENT: frozenset({AgentState.PLAN, AgentState.VERIFY}),
    AgentState.VERIFY: frozenset({AgentState.PLAN, AgentState.IMPLEMENT, AgentState.DONE}),
    AgentState.DONE: frozenset(),
}

_TOOLS_BY_STATE: dict[AgentState, frozenset[str]] = {
    AgentState.REQUIREMENTS: frozenset(
        {
            "shell",
            "user_request",
            "transition_state",
            "web_search",
            "load_skill",
            "read_skill",
            "unload_skill",
        }
    ),
    AgentState.PLAN: frozenset(
        {
            "shell",
            "user_request",
            "transition_state",
            "update_plan",
            "web_search",
            "load_skill",
            "read_skill",
            "unload_skill",
        }
    ),
    AgentState.IMPLEMENT: frozenset(
        {
            "shell",
            "apply_patch",
            "user_request",
            "transition_state",
            "update_plan",
            "web_search",
            "load_skill",
            "read_skill",
            "unload_skill",
        }
    ),
    AgentState.VERIFY: frozenset(
        {
            "shell",
            "user_request",
            "transition_state",
            "update_agents",
            "update_plan",
            "web_search",
            "load_skill",
            "read_skill",
            "unload_skill",
        }
    ),
    AgentState.DONE: frozenset(),
}


class StateMachine:
    """Track the current task phase and enforce meaningful transitions."""

    def __init__(self, plan: PlanTodoList | None = None) -> None:
        self.current = AgentState.REQUIREMENTS
        self.agents_updated = False
        self.plan = plan or PlanTodoList()

    def transition(self, target: AgentState | str) -> AgentState:
        try:
            target_state = target if isinstance(target, AgentState) else AgentState(target)
        except ValueError as exc:
            raise InvalidTransition(f"unknown target state: {target}") from exc

        if target_state not in _TRANSITIONS[self.current]:
            raise InvalidTransition(
                f"cannot transition from {self.current.value} to {target_state.value}"
            )
        if target_state is AgentState.DONE and not self.agents_updated:
            raise InvalidTransition("AGENTS.md must be reviewed before entering DONE")
        if target_state is AgentState.DONE and not self.plan.all_completed:
            raise InvalidTransition("Plan Todo must be complete before entering DONE")

        if target_state is AgentState.VERIFY or self.current is AgentState.VERIFY:
            self.agents_updated = False
        self.current = target_state
        return self.current

    def mark_agents_updated(self) -> None:
        if self.current is not AgentState.VERIFY:
            raise InvalidTransition("AGENTS.md can only be reviewed during VERIFY")
        self.agents_updated = True

    def allowed_tools(self) -> set[str]:
        return set(_TOOLS_BY_STATE[self.current])

    def reset_for_task(self) -> None:
        if self.current is not AgentState.DONE:
            raise InvalidTransition("only a completed task can be reset")
        self.current = AgentState.REQUIREMENTS
        self.agents_updated = False
        self.plan = PlanTodoList()
