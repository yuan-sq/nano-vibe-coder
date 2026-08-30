"""Static state-based model selection with deterministic fallbacks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .base import Model, ModelResponse


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    model: Model


class ModelRoutingError(RuntimeError):
    """Raised when every model candidate for a state fails."""

    def __init__(self, state: str, attempts: list[tuple[str, str]]) -> None:
        self.state = state
        self.attempts = attempts
        details = "; ".join(f"{name}: {message}" for name, message in attempts)
        super().__init__(f"all models failed for {state}: {details}")


class ModelRouter:
    """Resolve one static candidate list per agent state.

    The route is derived only from the current state and configuration.  A
    failed request may move to the next configured candidate, but model output
    never changes the route itself.
    """

    def __init__(
        self,
        models: Mapping[str, Model],
        active_model: str | Model,
        *,
        state_models: Mapping[str, str | Model] | None = None,
        fallback_models: Sequence[str | Model] = (),
        state_fallbacks: Mapping[str, Sequence[str | Model]] | None = None,
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.models = dict(models)
        self.active_name = self._resolve_name(active_model, "active_model")
        self.state_models = {
            str(state).upper(): self._resolve_name(value, f"state_models.{state}")
            for state, value in (state_models or {}).items()
        }
        self.fallback_models = tuple(
            self._resolve_name(value, "fallback_models") for value in fallback_models
        )
        self.state_fallbacks = {
            str(state).upper(): tuple(
                self._resolve_name(value, f"state_fallbacks.{state}") for value in values
            )
            for state, values in (state_fallbacks or {}).items()
        }

    def _resolve_name(self, value: str | Model, field: str) -> str:
        if isinstance(value, str):
            if value not in self.models:
                raise ValueError(f"{field} references unknown model: {value}")
            return value
        for name, model in self.models.items():
            if model is value:
                return name
        raise ValueError(f"{field} must reference a registered model")

    @staticmethod
    def _state_name(state: Any) -> str:
        return str(getattr(state, "value", state)).upper()

    def candidate_names(self, state: Any) -> list[str]:
        state_name = self._state_name(state)
        primary = self.state_models.get(state_name, self.active_name)
        configured = self.state_fallbacks.get(state_name, self.fallback_models)
        names: list[str] = []
        for name in (primary, *configured, self.active_name):
            if name not in names:
                names.append(name)
        return names

    def candidates(self, state: Any) -> list[ModelCandidate]:
        return [ModelCandidate(name, self.models[name]) for name in self.candidate_names(state)]

    def route(self, state: Any) -> Model:
        """Return the primary model for a state without performing a request."""

        return self.models[self.candidate_names(state)[0]]

    def model_for_state(self, state: Any) -> Model:
        return self.route(state)

    async def complete(
        self,
        state: Any,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelResponse:
        state_name = self._state_name(state)
        attempts: list[tuple[str, str]] = []
        for candidate in self.candidates(state_name):
            try:
                return await candidate.model.complete(messages, tools)
            except Exception as exc:  # noqa: BLE001 - provider boundary requires fallback
                message = str(exc) or exc.__class__.__name__
                attempts.append((candidate.name, message))
        raise ModelRoutingError(state_name, attempts)
