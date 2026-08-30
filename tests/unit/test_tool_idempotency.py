from typing import Any, ClassVar

import pytest

from nano_vibe.tools.base import Tool, ToolResult
from nano_vibe.tools.registry import ToolRegistry


class CountingTool(Tool):
    name = "count"
    description = "Count executions."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
    }

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls += 1
        return ToolResult.success(f"call {self.calls}: {arguments.get('value')}")


@pytest.mark.asyncio
async def test_registry_executes_same_idempotency_key_only_once() -> None:
    tool = CountingTool()
    registry = ToolRegistry([tool])

    first = await registry.execute("count", {"value": 1}, idempotency_key="call-1")
    second = await registry.execute("count", {"value": 1}, idempotency_key="call-1")

    assert first.output == second.output == "call 1: 1"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_registry_rejects_reused_key_with_different_arguments() -> None:
    registry = ToolRegistry([CountingTool()])
    await registry.execute("count", {"value": 1}, idempotency_key="call-1")

    result = await registry.execute("count", {"value": 2}, idempotency_key="call-1")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "idempotency_conflict"


@pytest.mark.asyncio
async def test_registry_can_clear_idempotency_between_tasks() -> None:
    tool = CountingTool()
    registry = ToolRegistry([tool])
    await registry.execute("count", {"value": 1}, idempotency_key="call-1")

    registry.clear_idempotency()
    result = await registry.execute("count", {"value": 2}, idempotency_key="call-1")

    assert result.ok is True
    assert tool.calls == 2
