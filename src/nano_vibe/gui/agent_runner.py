"""Adapter that runs the existing V2 Session behind GUI events."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nano_vibe.config import AppConfig
from nano_vibe.gui.runtime import PendingInteraction
from nano_vibe.session import Session


class InteractionBroker:
    """Bridge blocking V2 callbacks to WebSocket-resolvable interactions."""

    def __init__(self, emit: Callable[[str, dict[str, Any]], Awaitable[None]]) -> None:
        self.emit = emit
        self.pending: dict[str, PendingInteraction] = {}
        self._futures: dict[str, asyncio.Future[str | bool]] = {}

    async def approve(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        interaction = PendingInteraction(
            interaction_id=uuid.uuid4().hex[:12],
            kind="approval",
            content=f"允许执行工具 {tool_name} 吗？",
            tool_name=tool_name,
            arguments=arguments,
            capability=tool_name,
            reason="该工具需要权限确认",
            idempotency_key=f"approval:{uuid.uuid4().hex[:12]}",
            options=("once", "session", "deny"),
        )
        result = await self._wait(interaction)
        return result is True or result in {"once", "session", "allow", "approved"}

    async def ask(self, question: str, options: list[str]) -> str:
        interaction = PendingInteraction(
            interaction_id=uuid.uuid4().hex[:12],
            kind="user_request",
            content=question,
            options=tuple(options),
        )
        result = await self._wait(interaction)
        return str(result)

    async def _wait(self, interaction: PendingInteraction) -> str | bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | bool] = loop.create_future()
        self.pending[interaction.interaction_id] = interaction
        self._futures[interaction.interaction_id] = future
        await self.emit(
            "approval_requested" if interaction.kind == "approval" else "user_request",
            interaction.to_dict(),
        )
        try:
            return await future
        finally:
            self.pending.pop(interaction.interaction_id, None)
            self._futures.pop(interaction.interaction_id, None)

    async def resolve(self, interaction_id: str, decision: str) -> bool:
        future = self._futures.get(interaction_id)
        interaction = self.pending.get(interaction_id)
        if future is None or interaction is None or future.done():
            return False
        future.set_result(decision if interaction.kind == "user_request" else decision in {"once", "session", "allow", "approved"})
        await self.emit(
            "approval_resolved" if interaction.kind == "approval" else "user_request_resolved",
            {"interaction_id": interaction_id, "decision": decision},
        )
        return True


class GuiUI:
    def __init__(self, emit: Callable[[str, dict[str, Any]], Awaitable[None]], broker: InteractionBroker) -> None:
        self.emit = emit
        self.broker = broker

    def write_stream(self, text: str) -> None:
        asyncio.ensure_future(self.emit("assistant_delta", {"text": text}))

    def tool_start(self, _name: str, _arguments: dict[str, Any]) -> None:
        return

    async def on_event(self, name: str, payload: dict[str, Any]) -> None:
        await self.emit(name, payload)

    async def approve(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        return await self.broker.approve(tool_name, arguments)

    async def ask(self, question: str, options: list[str]) -> str:
        return await self.broker.ask(question, options)


class GuiAgentRunner:
    def __init__(self, config: AppConfig, workspace_for_session: Callable[[str], Path]) -> None:
        self.config = config
        self.workspace_for_session = workspace_for_session
        self.brokers: dict[str, InteractionBroker] = {}

    async def __call__(
        self,
        session_id: str,
        text: str,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        broker = InteractionBroker(emit)
        self.brokers[session_id] = broker
        workspace = self.workspace_for_session(session_id)
        ui = GuiUI(emit, broker)
        session = Session.from_config(self.config, workspace, ui, session_id=session_id)
        agent_task = asyncio.create_task(session.handle_input(text))
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {agent_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done and not agent_task.done():
                agent_task.cancel()
                await asyncio.gather(agent_task, return_exceptions=True)
                await emit("runtime_state", {"state": "PAUSED"})
            else:
                result = await agent_task
                await emit("message_completed", {"content": result.message, "status": result.status.value})
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            self.brokers.pop(session_id, None)

    async def resolve(self, session_id: str, interaction_id: str, decision: str) -> bool:
        broker = self.brokers.get(session_id)
        if broker is None:
            return False
        return await broker.resolve(interaction_id, decision)
