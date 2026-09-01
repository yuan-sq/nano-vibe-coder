import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nano_vibe.gui.app import EventHub, create_app
from nano_vibe.gui.events import SessionEventBuffer
from nano_vibe.gui.security import StartupToken
from nano_vibe.gui.storage import AppStorage


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path


def test_project_and_session_rest_api(tmp_path: Path) -> None:
    project = _repo(tmp_path / "repo")
    app = create_app(
        storage=AppStorage(tmp_path / "app"),
        require_auth=False,
        home=tmp_path,
    )
    client = TestClient(app)

    created = client.post("/api/v1/projects", json={"path": str(project)})
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert client.get("/api/v1/projects").json()[0]["path"] == str(project.resolve())

    session = client.post(
        f"/api/v1/projects/{project_id}/sessions", json={"title": "GUI 任务"}
    )
    assert session.status_code == 201
    session_id = session.json()["session_id"]
    renamed = client.patch(
        f"/api/v1/sessions/{session_id}", json={"title": "已重命名", "archived": True}
    )
    assert renamed.status_code == 200
    assert renamed.json()["archived"] is True


def test_auth_exchange_is_origin_checked_and_single_use(tmp_path: Path) -> None:
    token = StartupToken()
    app = create_app(
        storage=AppStorage(tmp_path / "app"),
        require_auth=True,
        startup_token=token,
        frontend_origin="http://127.0.0.1:5173",
        home=tmp_path,
    )
    client = TestClient(app)

    assert client.get("/api/v1/bootstrap").status_code == 401
    response = client.post(
        "/api/v1/auth/exchange",
        json={"token": token.value},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/bootstrap").status_code == 200

    second = TestClient(app)
    rejected = second.post(
        "/api/v1/auth/exchange",
        json={"token": token.value},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert rejected.status_code == 401


def test_config_api_persists_values_and_only_secret_status(tmp_path: Path) -> None:
    app = create_app(storage=AppStorage(tmp_path / "app"), require_auth=False, home=tmp_path)
    client = TestClient(app)

    response = client.put(
        "/api/v1/config",
        json={"scope": "project:repo", "values": {"permission_mode": "normal"}, "secrets": {"OPENAI_API_KEY": "hidden"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["values"]["permission_mode"] == "normal"
    assert body["secrets"]["OPENAI_API_KEY"] is True
    assert "hidden" not in response.text
    assert client.get("/api/v1/config?scope=project:repo").json()["values"]["permission_mode"] == "normal"


def test_websocket_replays_events_and_reports_resync(tmp_path: Path) -> None:
    app = create_app(
        storage=AppStorage(tmp_path / "app"),
        require_auth=False,
        event_buffer=SessionEventBuffer(max_events=1),
        home=tmp_path,
    )
    event_buffer = app.state.gui.event_buffer
    event_buffer.append("session-1", "run-1", "one", {"value": 1})
    event_buffer.append("session-1", "run-1", "two", {"value": 2})

    with TestClient(app).websocket_connect("/api/v1/ws/session-1") as websocket:
        websocket.send_json({"type": "subscribe", "last_seq": 1})
        assert websocket.receive_json()["type"] == "event"

    with TestClient(app).websocket_connect("/api/v1/ws/session-1") as websocket:
        websocket.send_json({"type": "subscribe", "last_seq": 0})
        message = websocket.receive_json()
        assert message["type"] == "resync_required"
        assert message["latest_seq"] == 2

    with TestClient(app).websocket_connect("/api/v1/ws/session-1") as websocket:
        websocket.send_json({"type": "subscribe", "last_seq": "invalid"})
        assert websocket.receive_json() == {
            "type": "error",
            "code": "invalid_last_seq",
            "message": "last_seq must be an integer",
        }


@pytest.mark.asyncio
async def test_event_hub_serializes_replay_before_live_events() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []
            self.replay_started = asyncio.Event()
            self.release_replay = asyncio.Event()

        async def send_json(self, data: dict[str, object]) -> None:
            self.messages.append(data)
            event = data.get("event")
            if isinstance(event, dict) and event.get("seq") == 1:
                self.replay_started.set()
                await self.release_replay.wait()

    buffer = SessionEventBuffer()
    buffer.append("session-1", "run-1", "replayed", {})
    hub = EventHub(buffer)
    websocket = FakeWebSocket()

    subscribe = asyncio.create_task(hub.subscribe("session-1", websocket, 0))
    await websocket.replay_started.wait()
    publish = asyncio.create_task(hub.publish("session-1", "run-1", "live", {}))
    await asyncio.sleep(0)
    assert not publish.done()

    websocket.release_replay.set()
    await subscribe
    await publish

    assert [message["event"]["seq"] for message in websocket.messages] == [1, 2]  # type: ignore[index]


async def _holding_runner(session_id: str, text: str, emit, stop_event: asyncio.Event) -> None:
    await emit("run_started", {"text": text})
    await stop_event.wait()
    await emit("run_completed", {"status": "paused"})


def test_second_run_is_rejected_while_first_is_active(tmp_path: Path) -> None:
    project = _repo(tmp_path / "repo")
    storage = AppStorage(tmp_path / "app")
    app = create_app(
        storage=storage,
        require_auth=False,
        runner=_holding_runner,
        home=tmp_path,
    )
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"path": str(project)}).json()["id"]
        session_id = client.post(
            f"/api/v1/projects/{project_id}/sessions", json={}
        ).json()["session_id"]

        first = client.post(f"/api/v1/sessions/{session_id}/messages", json={"text": "第一项"})
        assert first.status_code == 202
        second = client.post(
            f"/api/v1/sessions/{session_id}/messages", json={"text": "第二项"}
        )
        assert second.status_code == 409
        stopped = client.post(f"/api/v1/runs/{first.json()['run_id']}/stop")
        assert stopped.status_code == 202


def test_first_message_captures_diff_baseline_and_diff_api_reuses_it(tmp_path: Path) -> None:
    project = _repo(tmp_path / "repo")
    (project / "tracked.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "-c", "user.name=Tests", "-c", "user.email=t@example.test", "commit", "--quiet", "-m", "initial"],
        check=True,
    )
    storage = AppStorage(tmp_path / "app")
    app = create_app(storage=storage, require_auth=False, runner=_holding_runner, home=tmp_path)

    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"path": str(project)}).json()["id"]
        session_id = client.post(f"/api/v1/projects/{project_id}/sessions", json={}).json()["session_id"]
        response = client.post(f"/api/v1/sessions/{session_id}/messages", json={"text": "修改"})
        baseline_path = project / ".nano-vibe" / "gui" / session_id / "diff-baseline.json"

        assert response.status_code == 202
        assert baseline_path.is_file()
        captured_at = json.loads(baseline_path.read_text(encoding="utf-8"))["captured_at"]
        (project / "tracked.txt").write_text("changed\n", encoding="utf-8")
        body = client.get(f"/api/v1/sessions/{session_id}/diff").json()
        assert body["baseline_captured_at"] == captured_at
        assert body["entries"][0]["task_changed"] is True
        client.post(f"/api/v1/runs/{response.json()['run_id']}/stop")


def test_trace_api_reads_only_requested_session_trace(tmp_path: Path) -> None:
    project = _repo(tmp_path / "repo")
    storage = AppStorage(tmp_path / "app")
    app = create_app(storage=storage, require_auth=False, runner=_holding_runner, home=tmp_path)

    from nano_vibe.observability.trace import TraceWriter, trace_path

    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"path": str(project)}).json()["id"]
        first = client.post(f"/api/v1/projects/{project_id}/sessions", json={}).json()["session_id"]
        second = client.post(f"/api/v1/projects/{project_id}/sessions", json={}).json()["session_id"]
        TraceWriter(trace_path(project, first), first).record("first_event", secret="value")
        TraceWriter(trace_path(project, second), second).record("second_event")

        response = client.get(f"/api/v1/sessions/{first}/trace?limit=1")

        assert response.status_code == 200
        assert response.json()["items"][0]["event"] == "first_event"
        assert response.json()["items"][0]["secret"] == "[REDACTED]"
