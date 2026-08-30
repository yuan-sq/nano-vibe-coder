"""Interactive session assembly around the core agent loop."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from nano_vibe.agent.loop import AgentLoop, LoopResult
from nano_vibe.agent.state import StateMachine
from nano_vibe.config import AppConfig
from nano_vibe.models.base import Model
from nano_vibe.models.openai_compat import OpenAICompatibleModel
from nano_vibe.observability.trace import TraceWriter
from nano_vibe.tools.apply_patch import ApplyPatchTool
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.shell import ShellTool
from nano_vibe.tools.transition import TransitionTool
from nano_vibe.tools.update_agents import UpdateAgentsTool
from nano_vibe.tools.user_request import UserRequestTool
from nano_vibe.tools.web_search import WebSearchTool


class Session:
    def __init__(
        self,
        model: Model,
        workspace: str | Path,
        *,
        registry: ToolRegistry | None = None,
        machine: StateMachine | None = None,
        trace: TraceWriter | None = None,
        max_model_turns: int = 100,
        max_consecutive_tool_errors: int = 5,
        context_window: int = 128_000,
        compact_ratio: float = 0.75,
        compact_target_ratio: float = 0.50,
        user_request_callback: Any | None = None,
        on_tool: Any | None = None,
        shell_timeout_seconds: float = 300,
        shell_max_output_chars: int = 50_000,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.machine = machine or StateMachine()
        self.model = model
        self.trace = trace
        if registry is None:
            registry = ToolRegistry(
                [
                    ShellTool(
                        self.workspace,
                        timeout_seconds=shell_timeout_seconds,
                        max_output_chars=shell_max_output_chars,
                    ),
                    ApplyPatchTool(self.workspace),
                    UserRequestTool(user_request_callback),
                    TransitionTool(self.machine),
                    UpdateAgentsTool(self.workspace, self.machine),
                    WebSearchTool(),
                ]
            )
        self.registry = registry
        self.loop = AgentLoop(
            model,
            registry,
            self.machine,
            self.workspace,
            max_model_turns=max_model_turns,
            max_consecutive_tool_errors=max_consecutive_tool_errors,
            trace=trace,
            context_window=context_window,
            compact_ratio=compact_ratio,
            compact_target_ratio=compact_target_ratio,
            on_tool=on_tool,
        )

    async def handle_input(self, text: str) -> LoopResult:
        return await self.loop.handle_input(text)

    @classmethod
    def from_config(cls, config: AppConfig, workspace: str | Path, ui: Any) -> "Session":
        workspace_path = Path(workspace).resolve()
        project_root = Path(__file__).resolve().parents[2]
        workspace_id = hashlib.sha256(str(workspace_path).encode()).hexdigest()[:12]
        session_id = uuid.uuid4().hex[:12]
        trace = TraceWriter(project_root / "runs" / workspace_id / f"{session_id}.jsonl", session_id)
        model = OpenAICompatibleModel(
            config.active_model,
            retries=config.runtime.api_retries,
            on_text=ui.write_stream,
        )
        return cls(
            model,
            workspace_path,
            trace=trace,
            max_model_turns=config.runtime.max_model_turns,
            max_consecutive_tool_errors=config.runtime.max_consecutive_tool_errors,
            context_window=config.active_model.context_window,
            compact_ratio=config.runtime.compact_ratio,
            compact_target_ratio=config.runtime.compact_target_ratio,
            user_request_callback=ui.ask,
            on_tool=ui.tool_start,
            shell_timeout_seconds=config.runtime.shell_timeout_seconds,
            shell_max_output_chars=config.runtime.shell_max_output_chars,
        )
