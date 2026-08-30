"""FastAPI application and native WebSocket protocol for the local GUI."""

from __future__ import annotations

import asyncio
import inspect
import secrets
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nano_vibe.config import AppConfig

from .agent_runner import GuiAgentRunner
from .diff import GitDiffService
from .events import SessionEventBuffer
from .runtime import GlobalRunLock, LockAcquisitionError
from .security import StartupToken, is_allowed_origin, validate_project_path
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


class MessageCreate(BaseModel):
    text: str = Field(min_length=1)


class RunConflict(RuntimeError):
    def __init__(self, active_run_id: str | None) -> None:
        super().__init__("another Agent run is already active")
        self.active_run_id = active_run_id


@dataclass
class ActiveRun:
    run_id: str
    session_id: str
    task: asyncio.Task[Any]
    stop_event: asyncio.Event


class EventHub:
    def __init__(self, event_buffer: SessionEventBuffer) -> None:
        self.event_buffer = event_buffer
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)

    def subscribe(self, session_id: str, websocket: WebSocket) -> None:
        self._subscribers[session_id].add(websocket)

    def unsubscribe(self, session_id: str, websocket: WebSocket) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(websocket)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    async def publish(
        self, session_id: str, run_id: str | None, event_type: str, payload: dict[str, Any]
    ) -> None:
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

    async def start(self, session_id: str, text: str) -> str:
        async with self._guard:
            if self._active is not None and not self._active.task.done():
                raise RunConflict(self._active.run_id)
            try:
                self._run_lock.acquire()
            except LockAcquisitionError as exc:
                raise RunConflict(None) from exc
            run_id = uuid.uuid4().hex[:12]
            stop_event = asyncio.Event()
            task = asyncio.create_task(self._run(run_id, session_id, text, stop_event))
            self._active = ActiveRun(run_id, session_id, task, stop_event)
            return run_id

    async def _run(
        self, run_id: str, session_id: str, text: str, stop_event: asyncio.Event
    ) -> None:
        async def emit(event_type: str, payload: dict[str, Any]) -> None:
            await self.hub.publish(session_id, run_id, event_type, payload)

        try:
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
        )
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

    @app.post("/api/v1/sessions/{session_id}/messages", status_code=202, dependencies=[Depends(auth)])
    async def send_message(session_id: str, payload: MessageCreate) -> dict[str, Any]:
        try:
            state.storage.get_session(session_id)
            run_id = await state.coordinator.start(session_id, payload.text)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"}) from exc
        except RunConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "run_conflict", "active_run_id": exc.active_run_id},
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
        return GitDiffService(workspace).snapshot().to_dict()

    @app.get("/api/v1/sessions/{session_id}/trace", dependencies=[Depends(auth)])
    async def session_trace(
        session_id: str,
        event: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        workspace = _session_workspace(session_id)
        trace_root = workspace / "runs"
        candidates = sorted(trace_root.glob("**/*.jsonl")) if trace_root.is_dir() else []
        page = read_trace(candidates[-1], event=event, offset=offset, limit=limit) if candidates else read_trace(trace_root / "missing.jsonl")
        return {"items": page.items, "total": page.total}

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
        hub.subscribe(session_id, websocket)
        try:
            while True:
                command = await websocket.receive_json()
                command_type = command.get("type")
                if command_type == "subscribe":
                    replay = buffer.replay(session_id, command.get("last_seq"))
                    if replay.resync_required:
                        await websocket.send_json({"type": "resync_required"})
                    else:
                        for event in replay.events:
                            await websocket.send_json({"type": "event", "event": event.to_dict()})
                elif command_type == "stop":
                    run_id = str(command.get("run_id", ""))
                    await websocket.send_json(
                        {"type": "stop_result", "ok": await state.coordinator.stop(run_id)}
                    )
                elif command_type in {"resolve_approval", "resolve_user_request"}:
                    ok = await state.coordinator.resolve(
                        session_id,
                        str(command.get("interaction_id", "")),
                        str(command.get("decision", "")),
                    )
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
