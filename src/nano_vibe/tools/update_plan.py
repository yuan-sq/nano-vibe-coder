"""Model-callable tool for replacing the structured task plan."""

from __future__ import annotations

from typing import Any, ClassVar

from nano_vibe.agent.state import AgentState, StateMachine

from .base import Tool, ToolResult


class UpdatePlanTool(Tool):
    name = "update_plan"
    description = (
        "维护结构化执行计划。请及时调用本工具：开始每个逻辑单元前将对应 Todo 标为 "
        "in_progress，完成后立即标为 completed，并将下一项推进为 in_progress；计划、范围、"
        "阻塞或验证结果发生变化时也要同步更新，进入 VERIFY 或 DONE 前确保计划状态准确。"
    )
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
            },
            "updates": {
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
                    "required": ["id"],
                    "additionalProperties": False,
                },
            },
            "replace": {"type": "boolean", "default": True},
        },
        "required": [],
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
        incremental = "updates" in arguments
        items = arguments.get(
            "updates" if incremental else "items",
            arguments.get("todos", arguments.get("plan")),
        )
        if not isinstance(items, list):
            return ToolResult.failure(
                "items must be a list of plan objects", code="invalid_plan"
            )
        try:
            if incremental or arguments.get("replace") is False:
                plan = self.machine.plan.update(items)
            else:
                plan = self.machine.plan.replace(items)
        except ValueError as exc:
            return ToolResult.failure(str(exc), code="invalid_plan", retryable=False)
        return ToolResult.success(
            "Plan updated successfully.",
            plan=[item.to_dict() for item in plan],
        )
