"""Adapter that runs the existing V2 Session behind GUI events."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nano_vibe.config import AppConfig
from nano_vibe.gui.diff import GitDiffService
from nano_vibe.gui.runtime import GlobalRunLock, LockAcquisitionError, PendingInteraction
from nano_vibe.permissions import ApprovalDecision
from nano_vibe.session import Session, session_store_for_config
from nano_vibe.session_store import SessionStoreError


class StalePendingCleanupError(RuntimeError):
    """Raised when a stale interaction cannot be persisted as cleared."""

    code = "stale_pending_cleanup_failed"


class InteractionBroker:
    """Bridge blocking V2 callbacks to WebSocket-resolvable interactions."""

    def __init__(self, emit: Callable[[str, dict[str, Any]], Awaitable[None]]) -> None:
        self.emit = emit
        self.on_pending: Callable[[PendingInteraction], Any] | None = None
        self.on_resolved: Callable[[PendingInteraction, str], Any] | None = None
        self.on_before_resolve: Callable[[PendingInteraction, str], Any] | None = None
        self.pending: dict[str, PendingInteraction] = {}
        self._futures: dict[str, asyncio.Future[str]] = {}

    async def approve(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ApprovalDecision:
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
        return ApprovalDecision.parse(await self._wait(interaction))

    async def ask(self, question: str, options: list[str]) -> str:
        interaction = PendingInteraction(
            interaction_id=uuid.uuid4().hex[:12],
            kind="user_request",
            content=question,
            options=tuple(options),
        )
        result = await self._wait(interaction)
        return str(result)

    def set_before_resolve_callback(self, callback: Callable[[PendingInteraction, str], Any]) -> None:
        self.on_before_resolve = callback

    async def _wait(self, interaction: PendingInteraction) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self.pending[interaction.interaction_id] = interaction
        self._futures[interaction.interaction_id] = future
        if self.on_pending is not None:
            callback_result = self.on_pending(interaction)
            if inspect.isawaitable(callback_result):
                await callback_result
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
        if self.on_before_resolve is not None:
            try:
                callback_result = self.on_before_resolve(interaction, decision)
                if inspect.isawaitable(callback_result):
                    await callback_result
            except Exception:  # noqa: BLE001 - persistence failures reject the interaction
                return False
        future.set_result(decision)
        if self.on_resolved is not None:
            callback_result = self.on_resolved(interaction, decision)
            if inspect.isawaitable(callback_result):
                await callback_result
        await self.emit(
            "approval_resolved" if interaction.kind == "approval" else "user_request_resolved",
            {"interaction_id": interaction_id, "decision": decision},
        )
        return True


class GuiUI:
    def __init__(self, emit: Callable[[str, dict[str, Any]], Awaitable[None]], broker: InteractionBroker) -> None:
        self.emit = emit
        self.broker = broker

    async def write_stream(self, text: str) -> None:
        await self.emit("assistant_delta", {"text": text})

    def tool_start(self, _name: str, _arguments: dict[str, Any]) -> None:
        return

    def set_before_resolve_callback(self, callback: Callable[[PendingInteraction, str], Any]) -> None:
        self.broker.on_before_resolve = callback

    async def on_event(self, name: str, payload: dict[str, Any]) -> None:
        await self.emit(name, payload)

    async def approve(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ApprovalDecision:
        return await self.broker.approve(tool_name, arguments)

    async def ask(self, question: str, options: list[str]) -> str:
        return await self.broker.ask(question, options)


class GuiAgentRunner:
    handles_runtime_state = True

    def __init__(
        self,
        config: AppConfig,
        workspace_for_session: Callable[[str], Path],
        *,
        run_lock_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.workspace_for_session = workspace_for_session
        self.run_lock_path = Path(run_lock_path).expanduser().resolve() if run_lock_path else None
        self.brokers: dict[str, InteractionBroker] = {}

    async def __call__(
        self,
        session_id: str,
        text: str,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        workspace = self.workspace_for_session(session_id)
        GitDiffService(workspace, session_id).ensure_baseline()
        holder: dict[str, Session] = {}

        async def on_pending(interaction: PendingInteraction) -> None:
            session = holder.get("session")
            if session is None:
                return
            session.runtime_state = (
                "AWAITING_APPROVAL" if interaction.kind == "approval" else "AWAITING_INPUT"
            )
            session.pending_interaction = interaction.to_dict()
            session.save_snapshot()

        async def on_resolved(interaction: PendingInteraction, _decision: str) -> None:
            session = holder.get("session")
            if session is None:
                return
            session.runtime_state = "RUNNING"
            session.pending_interaction = None
            session.save_snapshot()

        broker = InteractionBroker(emit)
        broker.on_pending = on_pending
        broker.on_resolved = on_resolved
        self.brokers[session_id] = broker
        ui = GuiUI(emit, broker)
        session = Session.from_config(self.config, workspace, ui, session_id=session_id)
        holder["session"] = session
        snapshot_path = session.session_store.path_for(session_id)
        if snapshot_path.is_file():
            session.restore_snapshot(session.session_store.load(session_id))
        session.runtime_state = "RUNNING"
        session.save_snapshot()
        await emit("runtime_state", {"state": "RUNNING"})
        agent_task = asyncio.create_task(session.handle_input(text))
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {agent_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done and not agent_task.done():
                agent_task.cancel()
                await asyncio.gather(agent_task, return_exceptions=True)
                session.runtime_state = "PAUSED"
                session.save_snapshot()
                await emit("runtime_state", {"state": "PAUSED"})
            else:
                result = await agent_task
                session.runtime_state = "IDLE"
                session.pending_interaction = None
                session.save_snapshot()
                await emit("message_completed", {"content": result.message, "status": result.status.value})
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            self.brokers.pop(session_id, None)

    async def resolve(self, session_id: str, interaction_id: str, decision: str) -> bool:
        broker = self.brokers.get(session_id)
        if broker is None:
            await self._clear_stale_pending(session_id, interaction_id)
            return False
        return await broker.resolve(interaction_id, decision)

    async def _clear_stale_pending(self, session_id: str, interaction_id: str) -> None:
        """Drop a persisted interaction that has no in-process broker future."""

        workspace: Path | None = None
        cleanup_lock: GlobalRunLock | None = None
        try:
            workspace = self.workspace_for_session(session_id)
            lock_path = self.run_lock_path or workspace / ".nano-vibe" / "run.lock"
            cleanup_lock = GlobalRunLock(lock_path)
            try:
                cleanup_lock.acquire()
            except LockAcquisitionError:
                return
            store = session_store_for_config(self.config, workspace)
            snapshot = store.load(session_id)
            pending = snapshot.pending_interaction
            if pending is None or pending.get("interaction_id") != interaction_id:
                return
            snapshot.pending_interaction = None
            snapshot.runtime_state = "PAUSED"
            try:
                store.save(snapshot)
            except Exception as exc:
                raise StalePendingCleanupError(
                    f"could not persist stale interaction cleanup: {exc}"
                ) from exc
        except (KeyError, OSError, SessionStoreError):
            return
        finally:
            if cleanup_lock is not None:
                cleanup_lock.release()
