from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from nano_vibe.agent.loop import AgentLoop, LoopStatus
from nano_vibe.agent.state import AgentState, StateMachine
from nano_vibe.models.base import ModelResponse, ToolCall
from nano_vibe.models.router import ModelRouter
from nano_vibe.skills import SkillManager
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.transition import TransitionTool


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
        if not tools and messages and "Summarize" in str(messages[0].get("content", "")):
            self.summary_calls += 1
            return ModelResponse(content="A compact handoff")
        return await super().complete(messages, tools)


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_and_pauses_on_plain_response(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})]),
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
            ModelResponse(tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})]),
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
            ModelResponse(tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})]),
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
            ModelResponse(tool_calls=[ToolCall("call-1", "transition_state", {"target_state": "PLAN"})]),
            ModelResponse(tool_calls=[ToolCall("call-2", "transition_state", {"target_state": "IMPLEMENT"})]),
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
                tool_calls=[ToolCall("same-call", "transition_state", {"target_state": "PLAN"})]
            ),
            ModelResponse(
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
