"""Base types shared by local tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, output: str, **metadata: Any) -> "ToolResult":
        return cls(ok=True, output=output, metadata=metadata)

    @classmethod
    def failure(cls, output: str, **metadata: Any) -> "ToolResult":
        return cls(ok=False, output=output, metadata=metadata)


class Tool:
    """Small interface for a model-callable local tool."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
