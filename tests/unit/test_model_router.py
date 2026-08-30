from typing import Any, Mapping, Sequence

import pytest

from nano_vibe.agent.state import AgentState
from nano_vibe.models.base import ModelResponse
from nano_vibe.models.router import ModelRouter, ModelRoutingError


class RecordingModel:
    def __init__(self, name: str, *, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    async def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> ModelResponse:
        del messages, tools
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ModelResponse(content=self.name)


def test_router_uses_state_route_then_active_model_as_default() -> None:
    default = RecordingModel("default")
    planner = RecordingModel("planner")
    router = ModelRouter(
        {"default": default, "planner": planner},
        active_model="default",
        state_models={"PLAN": "planner"},
    )

    assert router.route(AgentState.PLAN).name == "planner"
    assert router.route(AgentState.VERIFY).name == "default"
    assert router.candidate_names(AgentState.PLAN) == ["planner", "default"]


@pytest.mark.asyncio
async def test_router_falls_back_after_primary_model_failure() -> None:
    primary = RecordingModel("primary", error=RuntimeError("offline"))
    backup = RecordingModel("backup")
    router = ModelRouter(
        {"primary": primary, "backup": backup},
        active_model="primary",
        fallback_models=["backup"],
    )

    response = await router.complete(AgentState.IMPLEMENT, [], [])

    assert response.content == "backup"
    assert primary.calls == 1
    assert backup.calls == 1


@pytest.mark.asyncio
async def test_router_raises_with_all_attempts_when_fallbacks_fail() -> None:
    primary = RecordingModel("primary", error=RuntimeError("first"))
    backup = RecordingModel("backup", error=RuntimeError("second"))
    router = ModelRouter(
        {"primary": primary, "backup": backup},
        active_model="primary",
        fallback_models=["backup"],
    )

    with pytest.raises(ModelRoutingError) as caught:
        await router.complete("VERIFY", [], [])

    assert caught.value.attempts == [("primary", "first"), ("backup", "second")]
