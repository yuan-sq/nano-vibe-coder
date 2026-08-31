import subprocess
from collections.abc import Mapping, Sequence
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from nano_vibe.agent.loop import LoopStatus
from nano_vibe.models.base import ModelResponse, ToolCall
from nano_vibe.session import Session
from nano_vibe.session_store import SessionStore


class ScriptedModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        del messages, tools
        return self.responses.pop(0)


_ids = count()


def call(name: str, **arguments: Any) -> ModelResponse:
    return ModelResponse(
        content=f"I will run {name}.",
        tool_calls=[ToolCall(f"offline-{next(_ids)}", name, arguments)],
    )


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "hello.txt").write_text("old\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_offline_v2_session_runs_plan_permission_and_resume_flow(tmp_path: Path) -> None:
    init_repo(tmp_path)
    diff = """diff --git a/hello.txt b/hello.txt
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-old
+new
"""
    model = ScriptedModel(
        [
            call("transition_state", target_state="PLAN"),
            call(
                "update_plan",
                items=[
                    {"id": "change", "content": "Change file", "status": "in_progress"}
                ],
            ),
            call("transition_state", target_state="IMPLEMENT"),
            call("apply_patch", diff=diff),
            call(
                "update_plan",
                items=[
                    {"id": "change", "content": "Change file", "status": "completed"}
                ],
            ),
            call("transition_state", target_state="VERIFY"),
            call("shell", command='test "$(cat hello.txt)" = new'),
            call("update_agents", content="# Rules\n\nRun tests.\n"),
            call("transition_state", target_state="DONE"),
        ]
    )
    store = SessionStore(tmp_path / "snapshots")
    session = Session(
        model,
        tmp_path,
        session_id="offline-v2",
        session_store=store,
        permission_mode="full-access",
    )

    result = await session.handle_input("Change hello.txt")

    assert result.status is LoopStatus.COMPLETED
    assert session.machine.current.value == "DONE"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "new\n"
    assert store.load("offline-v2").permission_mode == "full-access"

    resumed = Session.resume(
        ScriptedModel([ModelResponse(content="ready")]),
        tmp_path,
        "offline-v2",
        session_store=store,
    )
    assert resumed.machine.current.value == "DONE"
