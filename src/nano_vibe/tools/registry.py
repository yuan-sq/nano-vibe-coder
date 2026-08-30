"""Registration and phase-level filtering for local tools."""

from __future__ import annotations

from typing import Any, Iterable

from .base import Tool, ToolResult


class ToolUnavailable(LookupError):
    """Raised when a tool is not registered or not allowed in the current phase."""


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not getattr(tool, "name", "").strip():
            raise ValueError("tool name must not be empty")
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> set[str]:
        return set(self._tools)

    def definitions(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        selected = self._tools.values() if allowed is None else (
            tool for name, tool in self._tools.items() if name in allowed
        )
        return [tool.definition for tool in selected]

    async def execute(
        self, name: str, arguments: dict[str, Any], allowed: set[str] | None = None
    ) -> ToolResult:
        if name not in self._tools or (allowed is not None and name not in allowed):
            raise ToolUnavailable(f"tool is not available in the current phase: {name}")
        return await self._tools[name].execute(arguments)
