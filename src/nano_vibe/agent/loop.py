"""Model/tool orchestration for one interactive coding task."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from nano_vibe.models.base import Model, ModelResponse, ToolCall
from nano_vibe.models.router import ModelRouter, ModelRoutingError
from nano_vibe.observability.trace import TraceWriter
from nano_vibe.skills import SkillManager
from nano_vibe.tools.base import ToolResult
from nano_vibe.tools.registry import ToolRegistry

from .compaction import ApproximateTokenizer, ContextCompactor, Tokenizer
from .context import build_context
from .state import AgentState, StateMachine

_MAX_TOOL_EXPLANATION_RETRIES = 3
_TOOL_EXPLANATION_CORRECTION = (
    "Your previous response contained only tool calls without a user-facing explanation. "
    "Please return the intended tool calls again and include one brief user-facing "
    "explanation in the assistant content; do not reveal hidden chain-of-thought."
)


class LoopStatus(str, Enum):
    COMPLETED = "completed"
    WAITING = "waiting"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass(frozen=True)
class LoopResult:
    status: LoopStatus
    message: str
    turns: int = 0


class AgentLoop:
    def __init__(
        self,
        model: Model | ModelRouter,
        registry: ToolRegistry,
        machine: StateMachine,
        workspace: str | Path,
        *,
        max_model_turns: int = 100,
        max_consecutive_tool_errors: int = 5,
        trace: TraceWriter | None = None,
        context_window: int = 128_000,
        compact_ratio: float = 0.75,
        compact_target_ratio: float = 0.50,
        tokenizer: Tokenizer | None = None,
        on_tool: Callable[[str, dict[str, Any]], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], Any] | None = None,
        skill_manager: SkillManager | None = None,
        on_checkpoint: Callable[[], Any] | None = None,
    ) -> None:
        self.model = model
        self.router = model if isinstance(model, ModelRouter) else None
        self.registry = registry
        self.machine = machine
        self.workspace = Path(workspace).resolve()
        self.max_model_turns = max_model_turns
        self.max_consecutive_tool_errors = max_consecutive_tool_errors
        self.trace = trace
        self.history: list[dict[str, Any]] = []
        self.summary: str | None = None
        self._turns = 0
        self._tool_errors = 0
        self.on_tool = on_tool
        self.on_event = on_event
        self.skill_manager = skill_manager
        self.on_checkpoint = on_checkpoint
        self.compactor = ContextCompactor(
            tokenizer or ApproximateTokenizer(),
            context_window=context_window,
            compact_ratio=compact_ratio,
            target_ratio=compact_target_ratio,
        )

    async def handle_input(self, user_text: str) -> LoopResult:
        if not user_text.strip():
            return LoopResult(LoopStatus.WAITING, "Please enter a task.", self._turns)
        if self.machine.current is AgentState.DONE:
            self.machine.reset_for_task()
            self._turns = 0
            self._tool_errors = 0
            self.registry.clear_idempotency()
        self.history.append({"role": "user", "content": user_text})
        self._trace("user_input", content=user_text, state=self.machine.current.value)
        await self._emit_event("user_input", {"content": user_text, "state": self.machine.current.value})
        await self._checkpoint()
        return await self._run_until_pause()

    async def _run_until_pause(self) -> LoopResult:
        while self._turns < self.max_model_turns:
            self._turns += 1
            await self._compact_history_if_needed()
            messages = build_context(
                system_prompt=self._load_prompt(
                    "system.md",
                    "You are a coding agent operating in a local Git repository.",
                ),
                stage_prompt=self._stage_prompt(),
                agents_content=self._read_agents(),
                state=self.machine.current.value,
                history=self.history,
                summary=self.summary,
                plan=self.machine.plan.to_list(),
                skills=(self.skill_manager.context_entries() if self.skill_manager else None),
            )
            allowed = self.machine.allowed_tools()
            self._trace("model_request", state=self.machine.current.value, tool_count=len(allowed))
            await self._emit_event("model_request", {"state": self.machine.current.value, "tool_count": len(allowed)})
            try:
                response = await self._complete_with_tool_explanation(
                    messages, self.registry.definitions(allowed)
                )
            except Exception as exc:  # noqa: BLE001 - model providers are untrusted boundaries
                self._trace("model_error", state=self.machine.current.value, error=str(exc))
                return LoopResult(LoopStatus.ERROR, f"Model request failed: {exc}", self._turns)

            self._append_assistant_response(response)
            self._trace(
                "model_response",
                state=self.machine.current.value,
                tool_count=len(response.tool_calls),
                usage=dict(response.usage or {}),
            )
            await self._emit_event(
                "model_response",
                {
                    "state": self.machine.current.value,
                    "content": response.content,
                    "tool_count": len(response.tool_calls),
                    "usage": dict(response.usage or {}),
                },
            )
            if not response.tool_calls:
                status = LoopStatus.COMPLETED if self.machine.current is AgentState.DONE else LoopStatus.WAITING
                return LoopResult(status, response.content, self._turns)

            for call in response.tool_calls:
                result = await self._execute_tool(call)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "content": result.output,
                        **({"tool_error": result.error.to_dict()} if result.error else {}),
                    }
                )
                await self._checkpoint()
                if not result.ok:
                    self._tool_errors += 1
                    if self._tool_errors >= self.max_consecutive_tool_errors:
                        return LoopResult(
                            LoopStatus.ABORTED,
                            "Stopped after too many consecutive tool errors.",
                            self._turns,
                        )
                else:
                    self._tool_errors = 0
                if self.machine.current is AgentState.DONE:
                    return LoopResult(
                        LoopStatus.COMPLETED,
                        response.content or "Task completed.",
                        self._turns,
                    )
        return LoopResult(LoopStatus.ABORTED, "Stopped after reaching the model turn limit.", self._turns)

    async def _complete_with_tool_explanation(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelResponse:
        response = await self._complete(messages, tools)
        if not response.tool_calls or str(response.content or "").strip():
            return response

        for attempt in range(1, _MAX_TOOL_EXPLANATION_RETRIES + 1):
            tool_names = [call.name for call in response.tool_calls]
            payload = {
                "attempt": attempt,
                "max_retries": _MAX_TOOL_EXPLANATION_RETRIES,
                "tool_names": tool_names,
            }
            self._trace("model_explanation_retry", **payload)
            await self._emit_event("model_explanation_retry", payload)
            response = await self._complete(
                [
                    *messages,
                    {"role": "system", "content": _TOOL_EXPLANATION_CORRECTION},
                ],
                tools,
            )
            if not response.tool_calls or str(response.content or "").strip():
                return response

        tool_names = [call.name for call in response.tool_calls]
        payload = {
            "attempts": _MAX_TOOL_EXPLANATION_RETRIES + 1,
            "tool_names": tool_names,
        }
        self._trace("model_explanation_fallback", **payload)
        await self._emit_event("model_explanation_fallback", payload)
        return response

    async def _execute_tool(self, call: ToolCall) -> ToolResult:
        if self.on_tool is not None:
            self.on_tool(call.name, call.arguments)
        await self._emit_event(
            "tool_started",
            {
                "tool": call.name,
                "arguments": call.arguments,
                "tool_call_id": call.id,
                "state": self.machine.current.value,
            },
        )
        if call.parse_error:
            result = ToolResult.failure(f"Could not parse tool arguments: {call.parse_error}")
        else:
            try:
                result = await self.registry.execute(
                    call.name,
                    call.arguments,
                    self.machine.allowed_tools(),
                    idempotency_key=call.id or None,
                )
            except Exception as exc:  # noqa: BLE001 - convert every tool failure to ToolResult
                result = ToolResult.failure(str(exc))
        self._trace(
            "tool_end",
            state=self.machine.current.value,
            tool=call.name,
            ok=result.ok,
            metadata=dict(result.metadata),
        )
        await self._emit_event(
            "tool_finished",
            {
                "tool": call.name,
                "tool_call_id": call.id,
                "state": self.machine.current.value,
                **result.to_dict(),
            },
        )
        return result

    def _append_assistant_response(self, response: ModelResponse) -> None:
        message: dict[str, Any] = {"role": "assistant", "content": response.content or None}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ]
        self.history.append(message)

    async def _compact_history_if_needed(self) -> None:
        async def summarize(older: list[dict[str, Any]]) -> str:
            prompt = {
                "role": "system",
                "content": self._load_prompt(
                    "compact.md",
                    "Summarize older context into a concise handoff with decisions, failures, and next steps.",
                ),
            }
            response = await self._complete([prompt, *older], [])
            return response.content or "(No summary was produced.)"

        compacted = await self.compactor.maybe_compact(self.history, summarize)
        if compacted == self.history:
            return
        if compacted and compacted[0].get("role") == "system":
            self.summary = str(compacted[0].get("content", ""))
            self.history = compacted[1:]
        else:
            self.history = compacted
        self._trace("context_compacted", state=self.machine.current.value)

    def _stage_prompt(self) -> str:
        content = self._load_prompt(
            "stages.md", f"You are in the {self.machine.current.value} stage."
        )
        for line in content.splitlines():
            if line.startswith(f"{self.machine.current.value}:"):
                return line.split(":", 1)[1].strip()
        return f"You are in the {self.machine.current.value} stage."

    def _load_prompt(self, filename: str, fallback: str) -> str:
        path = Path(__file__).resolve().parents[1] / "prompts" / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return fallback

    def _read_agents(self) -> str:
        path = self.workspace / "AGENTS.md"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _trace(self, event: str, **fields: Any) -> None:
        if self.trace is not None:
            self.trace.record(event, turn=self._turns, **fields)

    async def _complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelResponse:
        if self.router is not None:
            try:
                response = await self.router.complete(self.machine.current, messages, tools)
            except ModelRoutingError as exc:
                self._trace(
                    "model_fallback_exhausted",
                    state=self.machine.current.value,
                    attempts=list(exc.attempts),
                )
                raise
            self._trace(
                "model_selected",
                state=self.machine.current.value,
                model=self.router.last_selected
                or self.router.candidate_names(self.machine.current)[0],
                fallback_attempts=list(self.router.last_attempts),
            )
            return response
        return await self.model.complete(messages, tools)  # type: ignore[union-attr]

    async def _checkpoint(self) -> None:
        if self.on_checkpoint is None:
            return
        result = self.on_checkpoint()
        if inspect.isawaitable(result):
            await result

    async def _emit_event(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        result = self.on_event(event, payload)
        if inspect.isawaitable(result):
            await result
