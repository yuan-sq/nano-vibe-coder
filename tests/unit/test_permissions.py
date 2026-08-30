from typing import Any

import pytest

from nano_vibe.permissions import PermissionMode, PermissionPolicy
from nano_vibe.tools.base import Tool, ToolError, ToolResult
from nano_vibe.tools.registry import ToolRegistry


class DangerousTool(Tool):
    name = "dangerous"
    description = "A tool that changes external state."
    permission_scope = "write"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        return ToolResult.success("changed")


@pytest.mark.asyncio
async def test_normal_policy_denies_restricted_tool_without_approval() -> None:
    registry = ToolRegistry(
        [DangerousTool()], permission_policy=PermissionPolicy(PermissionMode.NORMAL)
    )

    result = await registry.execute("dangerous", {})

    assert result.ok is False
    assert isinstance(result.error, ToolError)
    assert result.error.code == "permission_denied"


@pytest.mark.asyncio
async def test_full_access_policy_allows_restricted_tool() -> None:
    registry = ToolRegistry(
        [DangerousTool()], permission_policy=PermissionPolicy("full-access")
    )

    result = await registry.execute("dangerous", {})

    assert result.ok is True


@pytest.mark.asyncio
async def test_normal_policy_can_ask_async_approval() -> None:
    asked: list[tuple[str, dict[str, Any]]] = []

    async def approve(name: str, arguments: dict[str, Any]) -> bool:
        asked.append((name, arguments))
        return True

    registry = ToolRegistry(
        [DangerousTool()],
        permission_policy=PermissionPolicy(PermissionMode.NORMAL, approve=approve),
    )

    result = await registry.execute("dangerous", {"answer": 42})

    assert result.ok is True
    assert asked == [("dangerous", {"answer": 42})]


@pytest.mark.asyncio
async def test_registry_returns_structured_error_for_tool_exception() -> None:
    class BrokenTool(Tool):
        name = "broken"
        description = "Raises."
        parameters = {"type": "object", "properties": {}}

        async def execute(self, arguments: dict[str, Any]) -> ToolResult:
            del arguments
            raise RuntimeError("boom")

    result = await ToolRegistry([BrokenTool()]).execute("broken", {})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_exception"
    assert result.error.message == "boom"
