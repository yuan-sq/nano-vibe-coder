"""FastAPI application and native WebSocket protocol for the local GUI."""

from __future__ import annotations

import asyncio
import inspect
import secrets
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nano_vibe.config import AppConfig
from nano_vibe.observability.trace import trace_path
from nano_vibe.session import session_store_for_config
from nano_vibe.session_store import SessionSnapshot, SessionStore, SessionStoreError

from .agent_runner import GuiAgentRunner, StalePendingCleanupError
from .diff import GitDiffService
from .events import SessionEventBuffer
from .project_picker import ProjectPickerCancelled, ProjectPickerUnavailable, choose_directory
from .runtime import GlobalRunLock, LockAcquisitionError
from .security import SecretStore, StartupToken, is_allowed_origin, validate_project_path
from .storage import AppStorage, ProjectRecord, SessionMetadata
from .trace import read_trace

Runner = Callable[[str, str, Callable[[str, dict[str, Any]], Awaitable[None]], asyncio.Event], Any]


class ExchangeRequest(BaseModel):
    token: str


class ProjectCreate(BaseModel):
    path: str
    name: str | None = None


class SessionCreate(BaseModel):
    title: str = "新建 Session"


class SessionUpdate(BaseModel):
    title: str | None = None
    archived: bool | None = None


class PermissionModeUpdate(BaseModel):
    permission_mode: Literal["normal", "full-access"]


class MessageCreate(BaseModel):
    text: str = Field(min_length=1)


class ConfigUpdate(BaseModel):
    scope: str = "global"
    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class RunConflict(RuntimeError):
    def __init__(self, active_run_id: str | None) -> None:
        super().__init__("another Agent run is already active")
        self.active_run_id = active_run_id


class WebSocketSender(Protocol):
    async def send_json(self, data: Any) -> None:
        ...


@dataclass
class ActiveRun:
    run_id: str
    session_id: str
    task: asyncio.Task[Any]
    stop_event: asyncio.Event


class EventHub:
    def __init__(self, event_buffer: SessionEventBuffer) -> None:
        self.event_buffer = event_buffer
        self._subscribers: dict[str, set[WebSocketSender]] = defaultdict(set)
        self._session_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def subscribe(
        self, session_id: str, websocket: WebSocketSender, last_seq: int | None
    ) -> None:
        """Subscribe and replay while publish is serialized for this session."""

        async with self._session_locks[session_id]:
            self._subscribers[session_id].add(websocket)
            replay = self.event_buffer.replay(session_id, last_seq)
            try:
                if replay.resync_required:
                    await websocket.send_json(
                        {"type": "resync_required", "latest_seq": replay.latest_seq}
                    )
                else:
                    for event in replay.events:
                        await websocket.send_json(
                            {"type": "event", "event": event.to_dict()}
                        )
            except Exception:
                self.unsubscribe(session_id, websocket)
                raise

    def unsubscribe(self, session_id: str, websocket: WebSocketSender) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(websocket)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    async def publish(
        self, session_id: str, run_id: str | None, event_type: str, payload: dict[str, Any]
    ) -> None:
        async with self._session_locks[session_id]:
            event = self.event_buffer.append(session_id, run_id, event_type, payload)
            message = {"type": "event", "event": event.to_dict()}
            for websocket in tuple(self._subscribers.get(session_id, ())):
                try:
                    await websocket.send_json(message)
                except Exception:  # noqa: BLE001 - disconnects are cleaned up lazily.
                    self.unsubscribe(session_id, websocket)


class TaskCoordinator:
    def __init__(self, storage: AppStorage, hub: EventHub, runner: Runner | None) -> None:
        self.hub = hub
        self.runner = runner or self._unconfigured_runner
        self._guard = asyncio.Lock()
        self._active: ActiveRun | None = None
        self._run_lock = GlobalRunLock(storage.root / "run.lock")

    @property
    def active(self) -> ActiveRun | None:
        return self._active

    async def start(
        self,
        session_id: str,
        text: str,
        *,
        before_run: Callable[[], Any] | None = None,
    ) -> str:
        async with self._guard:
            if self._active is not None and not self._active.task.done():
                raise RunConflict(self._active.run_id)
            try:
                self._run_lock.acquire()
            except LockAcquisitionError as exc:
                raise RunConflict(None) from exc
            try:
                if before_run is not None:
                    result = before_run()
                    if inspect.isawaitable(result):
                        await result
            except BaseException:
                self._run_lock.release()
                raise
            run_id = uuid.uuid4().hex[:12]
            stop_event = asyncio.Event()
            task = asyncio.create_task(self._run(run_id, session_id, text, stop_event))
            self._active = ActiveRun(run_id, session_id, task, stop_event)
            return run_id

    async def run_if_session_idle(
        self, session_id: str, operation: Callable[[], Any]
    ) -> Any:
        """Run a session mutation without racing a new task for that session."""

        async with self._guard:
            active = self._active
            if active is not None and not active.task.done() and active.session_id == session_id:
                raise RunConflict(active.run_id)
            result = operation()
            if inspect.isawaitable(result):
                return await result
            return result

    async def _run(
        self, run_id: str, session_id: str, text: str, stop_event: asyncio.Event
    ) -> None:
        async def emit(event_type: str, payload: dict[str, Any]) -> None:
            await self.hub.publish(session_id, run_id, event_type, payload)

        try:
            if not getattr(self.runner, "handles_runtime_state", False):
                await emit("runtime_state", {"state": "RUNNING"})
            result = self.runner(session_id, text, emit, stop_event)
            if inspect.isawaitable(result):
                await result
            if not stop_event.is_set():
                await emit("run_completed", {"status": "completed"})
        except asyncio.CancelledError:
            await emit("run_completed", {"status": "paused"})
            raise
        except Exception as exc:  # noqa: BLE001 - untrusted model/tool boundary.
            await emit("error", {"message": str(exc), "code": "run_error"})
        finally:
            self._run_lock.release()
            if self._active is not None and self._active.run_id == run_id:
                self._active = None

    async def stop(self, run_id: str) -> bool:
        active = self._active
        if active is None or active.run_id != run_id:
            return False
        active.stop_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(active.task), timeout=3)
        except asyncio.TimeoutError:
            active.task.cancel()
            await asyncio.gather(active.task, return_exceptions=True)
        return True

    async def resolve(self, session_id: str, interaction_id: str, decision: str) -> bool:
        resolver = getattr(self.runner, "resolve", None)
        if resolver is None:
            return False
        result = resolver(session_id, interaction_id, decision)
        return bool(await result) if inspect.isawaitable(result) else bool(result)

    @staticmethod
    async def _unconfigured_runner(
        _session_id: str,
        _text: str,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
        _stop_event: asyncio.Event,
    ) -> None:
        raise RuntimeError("Agent runtime is not configured")


@dataclass
class GuiState:
    storage: AppStorage
    event_buffer: SessionEventBuffer
    hub: EventHub
    coordinator: TaskCoordinator
    startup_token: StartupToken
    cookie_value: str
    require_auth: bool
    frontend_origin: str
    home: Path
    secret_store: SecretStore
    agent_config: AppConfig | None


def _project_dict(project: ProjectRecord) -> dict[str, Any]:
    return {
        "id": project.id,
        "path": project.path,
        "name": project.name,
        "created_at": project.created_at,
        "last_opened_at": project.last_opened_at,
    }


def _session_dict(session: SessionMetadata) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "title": session.title,
        "archived": session.archived,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _capture_diff_baseline(workspace: Path, session_id: str) -> None:
    GitDiffService(workspace, session_id).ensure_baseline()


def _snapshot_diff(workspace: Path, session_id: str) -> dict[str, object]:
    return GitDiffService(workspace, session_id).snapshot().to_dict()


def create_app(
    *,
    storage: AppStorage | None = None,
    event_buffer: SessionEventBuffer | None = None,
    runner: Runner | None = None,
    agent_config: AppConfig | None = None,
    require_auth: bool = True,
    startup_token: StartupToken | None = None,
    frontend_origin: str = "http://127.0.0.1:5173",
    home: str | Path | None = None,
) -> FastAPI:
    app_storage = storage or AppStorage()
    buffer = event_buffer or SessionEventBuffer()
    hub = EventHub(buffer)
    selected_runner = runner
    if selected_runner is None and agent_config is not None:
        selected_runner = GuiAgentRunner(
            agent_config,
            lambda session_id: Path(
                app_storage.get_project(app_storage.get_session(session_id).project_id).path
            ),
            run_lock_path=app_storage.root / "run.lock",
        )
    if isinstance(selected_runner, GuiAgentRunner) and selected_runner.run_lock_path is None:
        selected_runner.run_lock_path = app_storage.root / "run.lock"
    selected_config = agent_config or getattr(selected_runner, "config", None)
    state = GuiState(
        storage=app_storage,
        event_buffer=buffer,
        hub=hub,
        coordinator=TaskCoordinator(app_storage, hub, selected_runner),
        startup_token=startup_token or StartupToken(),
        cookie_value=secrets.token_urlsafe(32),
        require_auth=require_auth,
        frontend_origin=frontend_origin,
        home=Path(home).expanduser().resolve() if home is not None else Path.home().resolve(),
        secret_store=SecretStore(app_storage.root / ".env"),
        agent_config=selected_config,
    )
    app = FastAPI(title="nano-vibe GUI", version="3")
    app.state.gui = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    async def auth(request: Request) -> None:
        if state.require_auth and request.cookies.get("nano_vibe_session") != state.cookie_value:
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    def websocket_authorized(websocket: WebSocket) -> bool:
        if not state.require_auth:
            return True
        return websocket.cookies.get("nano_vibe_session") == state.cookie_value

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/auth/exchange")
    async def exchange(payload: ExchangeRequest, request: Request) -> JSONResponse:
        if not is_allowed_origin(request.headers.get("origin"), state.frontend_origin):
            raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})
        if not state.startup_token.exchange(payload.token):
            raise HTTPException(status_code=401, detail={"code": "invalid_startup_token"})
        response = {"authenticated": True, "protocol_version": 1}
        result = JSONResponse(response)
        result.set_cookie(
            "nano_vibe_session",
            state.cookie_value,
            httponly=True,
            samesite="strict",
            secure=False,
        )
        return result

    @app.get("/api/v1/bootstrap", dependencies=[Depends(auth)])
    async def bootstrap() -> dict[str, Any]:
        active = state.coordinator.active
        return {
            "protocol_version": 1,
            "frontend_origin": state.frontend_origin,
            "active_run": (
                {"run_id": active.run_id, "session_id": active.session_id}
                if active is not None and not active.task.done()
                else None
            ),
        }

    @app.get("/api/v1/config", dependencies=[Depends(auth)])
    async def get_config(scope: str = "global") -> dict[str, Any]:
        values = state.storage.get_config(scope)
        keys = ("OPENAI_API_KEY", "TAVILY_API_KEY")
        return {"scope": scope, "values": values, "secrets": state.secret_store.status(keys)}

    @app.put("/api/v1/config", dependencies=[Depends(auth)])
    async def update_config(payload: ConfigUpdate) -> dict[str, Any]:
        if payload.scope.strip() == "":
            raise HTTPException(status_code=400, detail={"code": "invalid_config_scope"})
        state.storage.set_config(payload.scope, payload.values)
        for key, value in payload.secrets.items():
            state.secret_store.set(key, value)
        keys = ("OPENAI_API_KEY", "TAVILY_API_KEY")
        return {
            "scope": payload.scope,
            "values": state.storage.get_config(payload.scope),
            "secrets": state.secret_store.status(keys),
        }

    @app.get("/api/v1/projects", dependencies=[Depends(auth)])
    async def list_projects() -> list[dict[str, Any]]:
        return [_project_dict(project) for project in state.storage.list_projects()]

    @app.post("/api/v1/projects", status_code=201, dependencies=[Depends(auth)])
    async def add_project(payload: ProjectCreate) -> dict[str, Any]:
        try:
            path = validate_project_path(payload.path, home=state.home)
            return _project_dict(state.storage.add_project(path, name=payload.name))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_project", "message": str(exc)}) from exc

    @app.post("/api/v1/projects/select", status_code=201, dependencies=[Depends(auth)])
    async def select_project() -> dict[str, Any]:
        try:
            selected = await asyncio.to_thread(choose_directory)
        except ProjectPickerCancelled as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "project_selection_cancelled"},
            ) from exc
        except ProjectPickerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "project_picker_unavailable", "message": str(exc)},
            ) from exc
        try:
            path = validate_project_path(selected, home=state.home)
            return _project_dict(state.storage.add_project(path))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_project", "message": str(exc)},
            ) from exc

    @app.delete(
        "/api/v1/projects/{project_id}",
        status_code=204,
        response_model=None,
        dependencies=[Depends(auth)],
    )
    async def remove_project(project_id: str) -> None:
        try:
            state.storage.remove_project(project_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc

    @app.get("/api/v1/projects/{project_id}/sessions", dependencies=[Depends(auth)])
    async def list_sessions(project_id: str) -> list[dict[str, Any]]:
        try:
            return [_session_dict(item) for item in state.storage.list_sessions(project_id)]
        except Exception as exc:
            raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc

    @app.post("/api/v1/projects/{project_id}/sessions", status_code=201, dependencies=[Depends(auth)])
    async def create_session(project_id: str, payload: SessionCreate) -> dict[str, Any]:
        try:
            return _session_dict(state.storage.create_session(project_id, title=payload.title))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc

    @app.patch("/api/v1/sessions/{session_id}", dependencies=[Depends(auth)])
    async def update_session(session_id: str, payload: SessionUpdate) -> dict[str, Any]:
        try:
            return _session_dict(
                state.storage.update_session(session_id, title=payload.title, archived=payload.archived)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc

    @app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(auth)])
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            metadata = state.storage.get_session(session_id)
            workspace = Path(state.storage.get_project(metadata.project_id).path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc
        snapshot = None
        try:
            store = (
                session_store_for_config(state.agent_config, workspace)
                if state.agent_config is not None
                else SessionStore(workspace / ".nano-vibe" / "sessions")
            )
            snapshot = store.load(session_id).to_dict()
        except SessionStoreError:
            pass
        default_mode = (
            state.agent_config.runtime.permission_mode
            if state.agent_config is not None
            else "normal"
        )
        return {
            "metadata": _session_dict(metadata),
            "snapshot": snapshot,
            "permission_mode": snapshot["permission_mode"] if snapshot is not None else default_mode,
        }

    @app.patch("/api/v1/sessions/{session_id}/permission-mode", dependencies=[Depends(auth)])
    async def update_permission_mode(
        session_id: str, payload: PermissionModeUpdate
    ) -> dict[str, str]:
        try:
            metadata = state.storage.get_session(session_id)
            workspace = Path(state.storage.get_project(metadata.project_id).path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc

        def update_snapshot() -> SessionSnapshot:
            store = (
                session_store_for_config(state.agent_config, workspace)
                if state.agent_config is not None
                else SessionStore(workspace / ".nano-vibe" / "sessions")
            )
            snapshot_path = store.path_for(session_id)
            if snapshot_path.is_file():
                try:
                    snapshot = store.load(session_id)
                except SessionStoreError as exc:
                    raise HTTPException(
                        status_code=503,
                        detail={"code": "session_snapshot_unavailable", "message": str(exc)},
                    ) from exc
            else:
                snapshot = SessionSnapshot(
                    session_id=session_id,
                    workspace=str(workspace.resolve()),
                    permission_mode=(
                        state.agent_config.runtime.permission_mode
                        if state.agent_config is not None
                        else "normal"
                    ),
                )
            if snapshot.runtime_state != "IDLE":
                raise HTTPException(
                    status_code=409,
                    detail={"code": "session_not_idle", "runtime_state": snapshot.runtime_state},
                )
            snapshot.permission_mode = payload.permission_mode
            snapshot.updated_at = datetime.now(timezone.utc).isoformat()
            try:
                store.save(snapshot)
            except (OSError, SessionStoreError) as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "permission_mode_persist_failed", "message": str(exc)},
                ) from exc
            return snapshot

        try:
            await state.coordinator.run_if_session_idle(session_id, update_snapshot)
        except RunConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "run_conflict", "active_run_id": exc.active_run_id},
            ) from exc
        return {"session_id": session_id, "permission_mode": payload.permission_mode}

    @app.post("/api/v1/sessions/{session_id}/messages", status_code=202, dependencies=[Depends(auth)])
    async def send_message(session_id: str, payload: MessageCreate) -> dict[str, Any]:
        try:
            workspace = _session_workspace(session_id)
            run_id = await state.coordinator.start(
                session_id,
                payload.text,
                before_run=lambda: asyncio.to_thread(
                    _capture_diff_baseline, workspace, session_id
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc
        except RunConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "run_conflict", "active_run_id": exc.active_run_id},
            ) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "diff_unavailable", "message": str(exc)},
            ) from exc
        return {"run_id": run_id, "status": "RUNNING"}

    @app.post("/api/v1/runs/{run_id}/stop", status_code=202, dependencies=[Depends(auth)])
    async def stop_run(run_id: str) -> dict[str, Any]:
        if not await state.coordinator.stop(run_id):
            raise HTTPException(status_code=404, detail={"code": "run_not_found"})
        return {"run_id": run_id, "status": "PAUSED"}

    def _session_workspace(session_id: str) -> Path:
        try:
            session = state.storage.get_session(session_id)
            return Path(state.storage.get_project(session.project_id).path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc

    @app.get("/api/v1/sessions/{session_id}/diff", dependencies=[Depends(auth)])
    async def session_diff(session_id: str) -> dict[str, object]:
        workspace = _session_workspace(session_id)
        try:
            return await asyncio.to_thread(_snapshot_diff, workspace, session_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "diff_unavailable", "message": str(exc)},
            ) from exc

    @app.get("/api/v1/sessions/{session_id}/trace", dependencies=[Depends(auth)])
    async def session_trace(
        session_id: str,
        event: str | None = None,
        offset: int = 0,
        limit: int = 100,
        tail: bool = False,
    ) -> dict[str, object]:
        workspace = _session_workspace(session_id)
        try:
            page = read_trace(
                trace_path(workspace, session_id),
                event=event,
                offset=offset,
                limit=limit,
                tail=tail,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_trace_pagination", "message": str(exc)},
            ) from exc
        return {
            "items": page.items,
            "next_offset": page.next_offset,
            "has_more": page.has_more,
            "total": page.total,
        }

    @app.websocket("/api/v1/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
        if not websocket_authorized(websocket):
            await websocket.close(code=4401)
            return
        if state.require_auth and not is_allowed_origin(
            websocket.headers.get("origin"), state.frontend_origin
        ):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            while True:
                command = await websocket.receive_json()
                command_type = command.get("type")
                if command_type == "subscribe":
                    last_seq = command.get("last_seq")
                    if last_seq is not None and (
                        isinstance(last_seq, bool) or not isinstance(last_seq, int)
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "invalid_last_seq",
                                "message": "last_seq must be an integer",
                            }
                        )
                        continue
                    await hub.subscribe(session_id, websocket, last_seq)
                elif command_type == "stop":
                    run_id = str(command.get("run_id", ""))
                    await websocket.send_json(
                        {"type": "stop_result", "ok": await state.coordinator.stop(run_id)}
                    )
                elif command_type in {"resolve_approval", "resolve_user_request"}:
                    try:
                        ok = await state.coordinator.resolve(
                            session_id,
                            str(command.get("interaction_id", "")),
                            str(command.get("decision", "")),
                        )
                    except StalePendingCleanupError as exc:
                        await websocket.send_json(
                            {"type": "error", "code": exc.code, "message": str(exc)}
                        )
                    else:
                        await websocket.send_json({"type": "interaction_result", "ok": ok})
                else:
                    await websocket.send_json(
                        {"type": "error", "code": "unknown_command", "message": str(command_type)}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(session_id, websocket)

    return app
