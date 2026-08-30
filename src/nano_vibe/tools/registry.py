"""Registration, permission filtering, and idempotent execution for tools."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from nano_vibe.permissions import PermissionPolicy

from .base import Tool, ToolError, ToolResult


class ToolUnavailable(LookupError):
    """Raised when a tool is not registered or not allowed in the current phase."""


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        permission_policy: PermissionPolicy | None = None,
        idempotency_records: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.permission_policy = permission_policy
        self._idempotency: dict[str, dict[str, Any]] = {
            str(key): dict(value) for key, value in (idempotency_records or {}).items()
        }
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
        self,
        name: str,
        arguments: dict[str, Any],
        allowed: set[str] | None = None,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        if name not in self._tools or (allowed is not None and name not in allowed):
            raise ToolUnavailable(f"tool is not available in the current phase: {name}")
        tool_arguments = dict(arguments)
        key = idempotency_key or _string_key(tool_arguments.pop("idempotency_key", None))
        cache_key = f"{name}:{key}" if key else None
        arguments_digest = _arguments_digest(tool_arguments)
        if cache_key is not None and cache_key in self._idempotency:
            record = self._idempotency[cache_key]
            if record.get("arguments_digest") != arguments_digest:
                return ToolResult.failure(
                    "idempotency key was reused with different arguments",
                    code="idempotency_conflict",
                    details={"tool": name, "idempotency_key": key},
                )
            raw_result = record.get("result")
            if isinstance(raw_result, Mapping):
                return ToolResult.from_dict(raw_result)

        tool = self._tools[name]
        if self.permission_policy is not None:
            permission_error = await self.permission_policy.check(
                name, getattr(tool, "permission_scope", "read"), tool_arguments
            )
            if permission_error is not None:
                return ToolResult.failure(permission_error)
        try:
            result = await tool.execute(tool_arguments)
        except Exception as exc:
            result = ToolResult.failure(
                str(exc) or exc.__class__.__name__,
                code="tool_exception",
                details={"exception_type": exc.__class__.__name__},
                retryable=True,
            )
        if not isinstance(result, ToolResult):
            result = ToolResult.failure(
                "tool returned an invalid result", code="invalid_tool_result"
            )
        if cache_key is not None:
            self._idempotency[cache_key] = {
                "tool": name,
                "idempotency_key": key,
                "arguments_digest": arguments_digest,
                "result": result.to_dict(),
            }
        return result

    @property
    def idempotency_records(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._idempotency.items()}

    def restore_idempotency(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        self._idempotency = {str(key): dict(value) for key, value in records.items()}


def _string_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _arguments_digest(arguments: Mapping[str, Any]) -> str:
    return json.dumps(dict(arguments), ensure_ascii=False, sort_keys=True, default=str)
