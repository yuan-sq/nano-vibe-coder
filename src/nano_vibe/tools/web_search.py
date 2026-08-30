"""Web search placeholder kept for the future tool extension."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information (not available in v1)."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        return ToolResult.failure("web search is not implemented in v1")
