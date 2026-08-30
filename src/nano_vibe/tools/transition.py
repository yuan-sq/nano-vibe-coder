"""Tool used by the model to move the task state machine."""

from __future__ import annotations

from typing import Any, ClassVar

from nano_vibe.agent.state import StateMachine

from .base import Tool, ToolResult


class TransitionTool(Tool):
    name = "transition_state"
    description = "Move the task to a valid next or previous phase."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "target_state": {
                "type": "string",
                "enum": ["REQUIREMENTS", "PLAN", "IMPLEMENT", "VERIFY", "DONE"],
            }
        },
        "required": ["target_state"],
        "additionalProperties": False,
    }

    def __init__(self, machine: StateMachine) -> None:
        self.machine = machine

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        target = arguments.get("target_state")
        if not isinstance(target, str):
            return ToolResult.failure("target_state must be a string")
        try:
            current = self.machine.transition(target)
        except ValueError as exc:
            return ToolResult.failure(str(exc), state=self.machine.current.value)
        return ToolResult.success(f"State changed to {current.value}.", state=current.value)
