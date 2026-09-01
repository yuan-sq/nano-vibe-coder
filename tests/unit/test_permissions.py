import asyncio
from typing import Any, ClassVar

import pytest

from nano_vibe.permissions import ApprovalDecision, PermissionMode, PermissionPolicy
from nano_vibe.tools.base import Tool, ToolError, ToolResult
from nano_vibe.tools.registry import ToolRegistry


class DangerousTool(Tool):
    name = "dangerous"
    description = "A tool that changes external state."
    permission_scope = "write"
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

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
async def test_session_approval_grants_only_the_same_tool() -> None:
    decisions = iter([ApprovalDecision.SESSION, ApprovalDecision.ONCE])
    asked: list[str] = []

    async def approve(name: str, arguments: dict[str, Any]) -> ApprovalDecision:
        del arguments
        asked.append(name)
        return next(decisions)

    policy = PermissionPolicy(PermissionMode.NORMAL, approve=approve)

    assert await policy.authorize("apply_patch", "write", {}) is True
    assert await policy.authorize("apply_patch", "write", {}) is True
    assert await policy.authorize("shell", "shell", {}) is True
    assert asked == ["apply_patch", "shell"]
    assert policy.session_grants == {"apply_patch"}


@pytest.mark.asyncio
async def test_concurrent_session_grants_wait_for_persistence_before_rechecking() -> None:
    approval_started = asyncio.Event()
    release_approval = asyncio.Event()
    persistence_started = asyncio.Event()
    release_persistence = asyncio.Event()

    async def approve(_name: str, _arguments: dict[str, Any]) -> ApprovalDecision:
        if not approval_started.is_set():
            approval_started.set()
            await release_approval.wait()
            return ApprovalDecision.SESSION
        return ApprovalDecision.DENY

    async def persist() -> None:
        persistence_started.set()
        await release_persistence.wait()
        raise RuntimeError("disk full")

    policy = PermissionPolicy(
        PermissionMode.NORMAL,
        approve=approve,
        on_session_grant=persist,
    )
    first = asyncio.create_task(policy.authorize("dangerous", "write", {}))
    await approval_started.wait()
    release_approval.set()
    await persistence_started.wait()

    second_entered = asyncio.Event()

    async def authorize_second() -> bool:
        second_entered.set()
        return await policy.authorize("dangerous", "write", {})

    second = asyncio.create_task(authorize_second())
    await second_entered.wait()
    assert not second.done()

    release_persistence.set()
    assert await first is False
    assert await second is False
    assert policy.session_grants == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "allowed"),
    [
        (ApprovalDecision.ONCE, True),
        (ApprovalDecision.DENY, False),
        (True, True),
        (False, False),
    ],
)
async def test_approval_decisions_and_bool_compatibility(
    decision: ApprovalDecision | bool, allowed: bool
) -> None:
    policy = PermissionPolicy(PermissionMode.NORMAL, approve=lambda _name, _args: decision)

    assert await policy.authorize("dangerous", "write", {}) is allowed


@pytest.mark.asyncio
async def test_registry_returns_structured_error_for_tool_exception() -> None:
    class BrokenTool(Tool):
        name = "broken"
        description = "Raises."
        parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

        async def execute(self, arguments: dict[str, Any]) -> ToolResult:
            del arguments
            raise RuntimeError("boom")

    result = await ToolRegistry([BrokenTool()]).execute("broken", {})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_exception"
    assert result.error.message == "boom"
