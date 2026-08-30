"""Model-callable tool for replacing the structured task plan."""

from __future__ import annotations

from typing import Any, ClassVar

from nano_vibe.agent.state import AgentState, StateMachine

from .base import Tool, ToolResult


class UpdatePlanTool(Tool):
    name = "update_plan"
    description = "Replace the structured plan with pending, in_progress, or completed todo items."
    permission_scope = "plan"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["id", "content", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    def __init__(self, machine: StateMachine) -> None:
        self.machine = machine

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self.machine.current not in {
            AgentState.PLAN,
            AgentState.IMPLEMENT,
            AgentState.VERIFY,
        }:
            return ToolResult.failure(
                "plan can only be updated during PLAN, IMPLEMENT, or VERIFY",
                code="plan_state_forbidden",
                details={"state": self.machine.current.value},
            )
        items = arguments.get("items", arguments.get("todos", arguments.get("plan")))
        if not isinstance(items, list):
            return ToolResult.failure(
                "items must be a list of plan objects", code="invalid_plan"
            )
        try:
            plan = self.machine.plan.replace(items)
        except ValueError as exc:
            return ToolResult.failure(str(exc), code="invalid_plan", retryable=False)
        return ToolResult.success(
            "Plan updated successfully.",
            plan=[item.to_dict() for item in plan],
        )
