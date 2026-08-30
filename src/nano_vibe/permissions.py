"""Application-level permission policies for model-callable tools.

This module intentionally does not attempt to sandbox processes.  ``normal``
uses an approval callback for restricted operations while ``full-access``
allows the registered tools to run subject to their normal validation and
state-machine permissions.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum
from typing import Any

from nano_vibe.tools.base import ToolError


class PermissionMode(str, Enum):
    NORMAL = "normal"
    FULL_ACCESS = "full-access"

    @classmethod
    def parse(cls, value: PermissionMode | str) -> PermissionMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError("permission mode must be 'normal' or 'full-access'") from exc


ApprovalCallback = Callable[[str, Any], bool | Awaitable[bool]]


class PermissionPolicy:
    """Decide whether a tool may execute under the selected application mode."""

    restricted_scopes = frozenset({"write", "shell", "network"})

    def __init__(
        self,
        mode: PermissionMode | str = PermissionMode.NORMAL,
        *,
        approve: ApprovalCallback | None = None,
    ) -> None:
        self.mode = PermissionMode.parse(mode)
        self.approve = approve

    def requires_approval(self, scope: str) -> bool:
        return self.mode is PermissionMode.NORMAL and scope in self.restricted_scopes

    async def check(
        self, tool_name: str, scope: str, arguments: Mapping[str, Any]
    ) -> ToolError | None:
        if not self.requires_approval(scope):
            return None
        if self.approve is None:
            return ToolError(
                code="permission_denied",
                message=f"permission denied for tool: {tool_name}",
                details={"tool": tool_name, "scope": scope, "mode": self.mode.value},
                retryable=False,
            )
        try:
            approved = self.approve(tool_name, arguments)
            if inspect.isawaitable(approved):
                approved = await approved
        except Exception as exc:  # noqa: BLE001 - approval callbacks are user integrations
            return ToolError(
                code="permission_approval_error",
                message=str(exc) or "permission approval failed",
                details={"tool": tool_name, "scope": scope},
                retryable=True,
            )
        if not approved:
            return ToolError(
                code="permission_denied",
                message=f"permission denied for tool: {tool_name}",
                details={"tool": tool_name, "scope": scope, "mode": self.mode.value},
                retryable=False,
            )
        return None

    async def authorize(
        self, tool_name: str, scope: str, arguments: Mapping[str, Any]
    ) -> bool:
        """Boolean convenience API for callers that do not need error details."""

        return await self.check(tool_name, scope, arguments) is None


# A descriptive alias keeps integrations that call the component a manager
# source-compatible without creating a second permission implementation.
PermissionManager = PermissionPolicy
