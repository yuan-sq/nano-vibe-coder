from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from nano_vibe.agent.loop import AgentLoop, LoopStatus
from nano_vibe.agent.state import AgentState, StateMachine
from nano_vibe.models.base import ModelResponse, ToolCall
from nano_vibe.models.router import ModelRouter
from nano_vibe.skills import SkillManager
from nano_vibe.tools.filesystem import WriteTool
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.transition import TransitionTool
from nano_vibe.tools.update_plan import UpdatePlanTool


class ScriptedModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]] = []

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        self.requests.append((messages, tools))
        return self.responses.pop(0)


class CompactingModel(ScriptedModel):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(responses)
        self.summary_calls = 0

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        if not tools and messages and "总结" in str(messages[0].get("content", "")):
            self.summary_calls += 1
            return ModelResponse(content="A compact handoff")
        return await super().complete(messages, tools)


@pytest.mark.asyncio
async def test_successful_update_plan_emits_plan_updated_with_current_state(
    tmp_path: Path,
) -> None:
    machine = StateMachine()
    machine.current = AgentState.PLAN
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        ScriptedModel([]),
        ToolRegistry([UpdatePlanTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop._execute_tool(
        ToolCall(
            "plan-1",
            "update_plan",
            {"items": [{"id": "inspect", "content": "检查代码", "status": "in_progress"}]},
        )
    )

    assert result.ok is True
    assert ("plan_updated", {"plan": machine.plan.to_list(), "state": "PLAN"}) in events


@pytest.mark.asyncio
async def test_failed_update_plan_does_not_emit_plan_updated(tmp_path: Path) -> None:
    machine = StateMachine()
    machine.current = AgentState.PLAN
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        ScriptedModel([]),
        ToolRegistry([UpdatePlanTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop._execute_tool(
        ToolCall("plan-1", "update_plan", {"items": [{"id": "bad"}]})
    )

    assert result.ok is False
    assert not any(name == "plan_updated" for name, _payload in events)


@pytest.mark.asyncio
async def test_successful_write_tool_emits_diff_updated(tmp_path: Path) -> None:
    class WritePlanTool(UpdatePlanTool):
        permission_scope = "write"

    machine = StateMachine()
    machine.current = AgentState.PLAN
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        ScriptedModel([]),
        ToolRegistry([WritePlanTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    await loop._execute_tool(ToolCall("plan-1", "update_plan", {"items": []}))

    assert ("diff_updated", {"tool": "update_plan"}) in events


@pytest.mark.asyncio
async def test_successful_shell_tool_emits_diff_updated(tmp_path: Path) -> None:
    class ShellPlanTool(UpdatePlanTool):
        permission_scope = "shell"

    machine = StateMachine()
    machine.current = AgentState.PLAN
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        ScriptedModel([]),
        ToolRegistry([ShellPlanTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    await loop._execute_tool(ToolCall("shell-1", "update_plan", {"items": []}))

    assert ("diff_updated", {"tool": "update_plan"}) in events


@pytest.mark.asyncio
async def test_successful_file_write_emits_diff_updated(tmp_path: Path) -> None:
    machine = StateMachine()
    machine.current = AgentState.IMPLEMENT
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        ScriptedModel([]),
        ToolRegistry([WriteTool(tmp_path)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop._execute_tool(
        ToolCall("write-1", "write", {"path": "hello.txt", "content": "hello"})
    )

    assert result.ok is True
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    assert ("diff_updated", {"tool": "write"}) in events


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_and_pauses_on_plain_response(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(content="I have prepared the plan."),
        ]
    )
    machine = StateMachine()
    registry = ToolRegistry([TransitionTool(machine)])
    loop = AgentLoop(model, registry, machine, tmp_path)

    result = await loop.handle_input("Fix the bug")

    assert result.status is LoopStatus.WAITING
    assert result.message == "I have prepared the plan."
    assert machine.current.value == "PLAN"
    assert len(model.requests) == 2
    assert any(message.get("role") == "tool" for message in loop.history)


@pytest.mark.asyncio
async def test_agent_loop_notifies_before_executing_tool(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(content="ready"),
        ]
    )
    machine = StateMachine()
    registry = ToolRegistry([TransitionTool(machine)])
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(model, registry, machine, tmp_path, on_tool=lambda name, args: events.append((name, args)))

    await loop.handle_input("Inspect")

    assert events == [("transition_state", {"target_state": "PLAN"})]


@pytest.mark.asyncio
async def test_agent_loop_compacts_history_before_next_model_turn(tmp_path: Path) -> None:
    model = CompactingModel(
        [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(content="Plan is ready."),
        ]
    )
    machine = StateMachine()
    registry = ToolRegistry([TransitionTool(machine)])
    loop = AgentLoop(
        model,
        registry,
        machine,
        tmp_path,
        context_window=40,
        compact_ratio=0.5,
        compact_target_ratio=0.25,
    )

    result = await loop.handle_input("A very long task description " * 4)

    assert result.status is LoopStatus.WAITING
    assert model.summary_calls == 1
    assert loop.summary == "Previous context summary:\nA compact handoff"


@pytest.mark.asyncio
async def test_agent_loop_resets_turn_limit_for_a_new_task_after_done(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(
                content="I will move into implementation.",
                tool_calls=[ToolCall("call-2", "transition_state", {"target_state": "IMPLEMENT"})],
            ),
            ModelResponse(content="continuing"),
        ]
    )
    machine = StateMachine()
    machine.current = AgentState.DONE
    machine.agents_updated = True
    registry = ToolRegistry([TransitionTool(machine)])
    loop = AgentLoop(model, registry, machine, tmp_path, max_model_turns=3)
    loop._turns = 3

    result = await loop.handle_input("Start another task")

    assert result.status is LoopStatus.WAITING
    assert machine.current is AgentState.IMPLEMENT


@pytest.mark.asyncio
async def test_agent_loop_uses_model_route_for_current_state(tmp_path: Path) -> None:
    default = ScriptedModel([ModelResponse(content="default response")])
    planner = ScriptedModel([ModelResponse(content="planner response")])
    machine = StateMachine()
    machine.current = AgentState.PLAN
    router = ModelRouter(
        {"default": default, "planner": planner},
        active_model="default",
        state_models={"PLAN": "planner"},
    )
    loop = AgentLoop(router, ToolRegistry(), machine, tmp_path)

    result = await loop.handle_input("Plan this")

    assert result.message == "planner response"
    assert len(planner.requests) == 1
    assert len(default.requests) == 0


@pytest.mark.asyncio
async def test_agent_loop_replays_same_tool_call_id_without_second_side_effect(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("same-call", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
                content="I will move into planning again.",
                tool_calls=[ToolCall("same-call", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(content="continued"),
        ]
    )
    machine = StateMachine()
    loop = AgentLoop(model, ToolRegistry([TransitionTool(machine)]), machine, tmp_path)

    result = await loop.handle_input("Inspect")

    assert result.message == "continued"
    assert machine.current is AgentState.PLAN


@pytest.mark.asyncio
async def test_agent_loop_injects_loaded_skill_into_model_context(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A demo.\n---\nUse this skill.\n", encoding="utf-8"
    )
    skill_manager = SkillManager(tmp_path)
    skill_manager.load("demo")
    model = ScriptedModel([ModelResponse(content="seen")])
    loop = AgentLoop(
        model,
        ToolRegistry(),
        StateMachine(),
        tmp_path,
        skill_manager=skill_manager,
    )

    await loop.handle_input("Inspect")

    system_message = model.requests[0][0][0]["content"]
    assert "Use this skill." in system_message


@pytest.mark.asyncio
async def test_agent_loop_retries_tool_call_without_explanation(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                tool_calls=[ToolCall("rejected-call", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
                content="I will move into planning.",
                tool_calls=[ToolCall("accepted-call", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(content="The planning state is ready."),
        ]
    )
    machine = StateMachine()
    registry = ToolRegistry([TransitionTool(machine)])
    events: list[tuple[str, dict[str, Any]]] = []
    executed_tools: list[str] = []
    loop = AgentLoop(
        model,
        registry,
        machine,
        tmp_path,
        on_tool=lambda name, _arguments: executed_tools.append(name),
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop.handle_input("Plan this")

    assert result.message == "The planning state is ready."
    assert machine.current is AgentState.PLAN
    assert len(model.requests) == 3
    tool_started = [payload for event, payload in events if event == "tool_started"]
    assert len(tool_started) == 1
    assert tool_started[0]["tool_call_id"] == "accepted-call"
    assert executed_tools == ["transition_state"]
    assert not any(
        message.get("role") == "assistant" and not str(message.get("content") or "").strip()
        for message in loop.history
    )
    assistant_tool_call_ids = [
        call["id"]
        for message in loop.history
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    assert assistant_tool_call_ids == ["accepted-call"]
    assert "rejected-call" not in assistant_tool_call_ids
    tool_history_ids = [
        message["tool_call_id"] for message in loop.history if message.get("role") == "tool"
    ]
    assert tool_history_ids == ["accepted-call"]
    retry_payload = next(payload for event, payload in events if event == "model_explanation_retry")
    assert retry_payload == {
        "attempt": 1,
        "max_retries": 3,
        "tool_names": ["transition_state"],
    }
    correction = model.requests[1][0][-1]
    assert correction["role"] == "system"
    assert "brief user-facing explanation" in correction["content"]


@pytest.mark.asyncio
async def test_agent_loop_falls_back_after_three_explanation_retries(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                tool_calls=[ToolCall("rejected-call-1", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
                tool_calls=[ToolCall("rejected-call-2", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
                tool_calls=[ToolCall("rejected-call-3", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
                content="   ",
                tool_calls=[ToolCall("accepted-fallback-call", "transition_state", {"target_state": "PLAN"})],
            ),
            ModelResponse(content="The planning state is ready."),
        ]
    )
    machine = StateMachine()
    registry = ToolRegistry([TransitionTool(machine)])
    events: list[tuple[str, dict[str, Any]]] = []
    executed_tools: list[str] = []
    loop = AgentLoop(
        model,
        registry,
        machine,
        tmp_path,
        on_tool=lambda name, _arguments: executed_tools.append(name),
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop.handle_input("Plan this")

    assert result.message == "The planning state is ready."
    assert machine.current is AgentState.PLAN
    assert len(model.requests) == 5
    tool_started = [payload for event, payload in events if event == "tool_started"]
    assert len(tool_started) == 1
    assert tool_started[0]["tool_call_id"] == "accepted-fallback-call"
    assert executed_tools == ["transition_state"]
    assistant_tool_call_ids = [
        call["id"]
        for message in loop.history
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    assert assistant_tool_call_ids == ["accepted-fallback-call"]
    assert not {"rejected-call-1", "rejected-call-2", "rejected-call-3"}.intersection(assistant_tool_call_ids)
    tool_history_ids = [
        message["tool_call_id"] for message in loop.history if message.get("role") == "tool"
    ]
    assert tool_history_ids == ["accepted-fallback-call"]
    retries = [payload for event, payload in events if event == "model_explanation_retry"]
    assert len(retries) == 3
    for request in model.requests[1:4]:
        assert request[0][-1]["role"] == "system"
        corrections = [
            message
            for message in request[0]
            if str(message.get("content", "")).startswith("Your previous response contained only tool calls")
        ]
        assert len(corrections) == 1
    fallback_payload = next(payload for event, payload in events if event == "model_explanation_fallback")
    assert fallback_payload == {"attempts": 4, "tool_names": ["transition_state"]}
