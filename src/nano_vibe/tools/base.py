"""Base types shared by local tools.

The tool protocol deliberately keeps errors in-band.  A model can therefore
inspect a failure and decide whether to retry without having to parse an
exception string produced by a particular Python implementation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar


TOOL_EXPLANATION_INSTRUCTION = (
    "Before calling this tool, include a brief user-facing explanation "
    "in the assistant content."
)


@dataclass(frozen=True)
class ToolError:
    """Serializable error information returned by a tool."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("tool error code must not be empty")
        if not self.message.strip():
            raise ValueError("tool error message must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ToolError:
        details = value.get("details", {})
        return cls(
            code=str(value.get("code", "tool_error")),
            message=str(value.get("message", "tool failed")),
            details=dict(details) if isinstance(details, Mapping) else {},
            retryable=bool(value.get("retryable", False)),
        )


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: ToolError | None = None

    def __post_init__(self) -> None:
        # Keep the in-band error contract even for older/custom tools that
        # construct ``ToolResult(ok=False, ...)`` directly.
        if not self.ok and self.error is None:
            object.__setattr__(
                self,
                "error",
                ToolError(
                    code="tool_error",
                    message=self.output.strip() or "tool failed",
                ),
            )

    @classmethod
    def success(cls, output: str, **metadata: Any) -> ToolResult:
        return cls(ok=True, output=output, metadata=metadata)

    @classmethod
    def failure(
        cls,
        output: str | ToolError,
        *,
        error: ToolError | None = None,
        code: str = "tool_error",
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
        **metadata: Any,
    ) -> ToolResult:
        if isinstance(output, ToolError):
            error = output
            message = output.message
        else:
            message = output
            error = error or ToolError(
                code=code,
                message=message.strip() or code,
                details=dict(details or {}),
                retryable=retryable,
            )
        return cls(ok=False, output=message, metadata=metadata, error=error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "metadata": dict(self.metadata),
            "error": self.error.to_dict() if self.error is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ToolResult:
        raw_error = value.get("error")
        error = ToolError.from_dict(raw_error) if isinstance(raw_error, Mapping) else None
        return cls(
            ok=bool(value.get("ok", False)),
            output=str(value.get("output", "")),
            metadata=dict(value.get("metadata", {}))
            if isinstance(value.get("metadata", {}), Mapping)
            else {},
            error=error,
        )

    def as_json(self) -> str:
        """Return a stable JSON representation for a session snapshot."""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class Tool:
    """Small interface for a model-callable local tool."""

    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[Mapping[str, Any]]
    permission_scope: ClassVar[str] = "read"

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"{self.description} {TOOL_EXPLANATION_INSTRUCTION}",
                "parameters": dict(self.parameters),
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
