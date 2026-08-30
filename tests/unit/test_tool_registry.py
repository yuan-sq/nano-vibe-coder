import pytest

from nano_vibe.tools.base import Tool, ToolResult
from nano_vibe.tools.registry import ToolRegistry, ToolUnavailable


class EchoTool(Tool):
    name = "echo"
    description = "Echo a value."
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        return ToolResult.success(str(arguments["value"]))


@pytest.mark.asyncio
async def test_registry_filters_tools_and_executes_structured_result() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.names() == {"echo"}
    assert registry.definitions({"echo"})[0]["function"]["name"] == "echo"
    result = await registry.execute("echo", {"value": "hello"}, {"echo"})

    assert result.ok is True
    assert result.output == "hello"


@pytest.mark.asyncio
async def test_registry_rejects_tool_outside_phase_permissions() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(ToolUnavailable, match="echo"):
        await registry.execute("echo", {"value": "hello"}, set())
