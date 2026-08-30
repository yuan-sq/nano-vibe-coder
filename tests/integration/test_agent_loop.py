import subprocess
from itertools import count
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from nano_vibe.agent.loop import AgentLoop, LoopStatus
from nano_vibe.agent.state import AgentState, StateMachine
from nano_vibe.models.base import ModelResponse, ToolCall
from nano_vibe.tools.apply_patch import ApplyPatchTool
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.shell import ShellTool
from nano_vibe.tools.transition import TransitionTool
from nano_vibe.tools.update_plan import UpdatePlanTool
from nano_vibe.tools.update_agents import UpdateAgentsTool


class ScriptedModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        del messages, tools
        return self.responses.pop(0)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "hello.txt").write_text("old\n", encoding="utf-8")


_call_ids = count()


def call(name: str, **arguments: Any) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall(f"call-{name}-{next(_call_ids)}", name, arguments)])


@pytest.mark.asyncio
async def test_agent_loop_completes_full_task_and_updates_agents(tmp_path: Path) -> None:
    init_repo(tmp_path)
    machine = StateMachine()
    registry = ToolRegistry(
        [
            ShellTool(tmp_path, timeout_seconds=5),
            ApplyPatchTool(tmp_path),
            TransitionTool(machine),
            UpdatePlanTool(machine),
            UpdateAgentsTool(tmp_path, machine),
        ]
    )
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
                    {"id": "change", "content": "Change hello.txt", "status": "completed"}
                ],
            ),
            call("transition_state", target_state="IMPLEMENT"),
            call("apply_patch", diff=diff),
            call("transition_state", target_state="VERIFY"),
            call("shell", command="test \"$(cat hello.txt)\" = new"),
            call("update_agents", content="# Project rules\n\nRun tests.\n"),
            call("transition_state", target_state="DONE"),
        ]
    )
    loop = AgentLoop(model, registry, machine, tmp_path, max_model_turns=20)

    result = await loop.handle_input("Change hello.txt")

    assert result.status is LoopStatus.COMPLETED
    assert machine.current is AgentState.DONE
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "AGENTS.md").exists()
