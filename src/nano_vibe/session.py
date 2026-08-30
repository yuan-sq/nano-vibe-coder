"""Interactive session assembly around the core agent loop."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nano_vibe.agent.loop import AgentLoop, LoopResult
from nano_vibe.agent.state import StateMachine
from nano_vibe.config import AppConfig
from nano_vibe.models.base import Model
from nano_vibe.models.openai_compat import OpenAICompatibleModel
from nano_vibe.models.router import ModelRouter
from nano_vibe.observability.trace import TraceWriter
from nano_vibe.permissions import PermissionMode, PermissionPolicy
from nano_vibe.session_store import SessionSnapshot, SessionStore, SessionStoreError
from nano_vibe.skills import SkillManager
from nano_vibe.tools.apply_patch import ApplyPatchTool
from nano_vibe.tools.registry import ToolRegistry
from nano_vibe.tools.shell import ShellTool
from nano_vibe.tools.skills import LoadSkillTool, ReadSkillTool, UnloadSkillTool
from nano_vibe.tools.transition import TransitionTool
from nano_vibe.tools.update_agents import UpdateAgentsTool
from nano_vibe.tools.update_plan import UpdatePlanTool
from nano_vibe.tools.user_request import UserRequestTool
from nano_vibe.tools.web_extract import WebExtractTool
from nano_vibe.tools.web_search import WebSearchTool


class Session:
    def __init__(
        self,
        model: Model | ModelRouter,
        workspace: str | Path,
        *,
        registry: ToolRegistry | None = None,
        machine: StateMachine | None = None,
        trace: TraceWriter | None = None,
        session_id: str | None = None,
        session_store: SessionStore | None = None,
        permission_mode: PermissionMode | str = PermissionMode.NORMAL,
        permission_approve: Any | None = None,
        permission_policy: PermissionPolicy | None = None,
        skill_manager: SkillManager | None = None,
        skill_roots: Iterable[str | Path] | None = None,
        max_model_turns: int = 100,
        max_consecutive_tool_errors: int = 5,
        context_window: int = 128_000,
        compact_ratio: float = 0.75,
        compact_target_ratio: float = 0.50,
        user_request_callback: Any | None = None,
        on_tool: Any | None = None,
        on_event: Any | None = None,
        shell_timeout_seconds: float = 300,
        shell_max_output_chars: int = 50_000,
        tavily_env_file: str | Path = ".env",
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.machine = machine or StateMachine()
        self.model = model
        self.trace = trace
        self.runtime_state = "IDLE"
        self.pending_interaction: dict[str, Any] | None = None
        self.permission_mode = PermissionMode.parse(permission_mode)
        self.session_store = session_store or SessionStore(self.workspace / ".nano-vibe" / "sessions")
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.session_store.path_for(self.session_id)
        self.skill_manager = skill_manager or SkillManager(
            self.workspace,
            skill_roots=skill_roots,
        )
        permission_policy = permission_policy or PermissionPolicy(
            self.permission_mode,
            approve=permission_approve,
        )
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
                    UpdatePlanTool(self.machine),
                    LoadSkillTool(self.skill_manager),
                    ReadSkillTool(self.skill_manager),
                    UnloadSkillTool(self.skill_manager),
                    WebSearchTool(workspace=self.workspace, env_file=tavily_env_file),
                    WebExtractTool(workspace=self.workspace, env_file=tavily_env_file),
                ],
                permission_policy=permission_policy,
            )
        elif permission_policy is not None:
            registry.permission_policy = permission_policy
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
            on_event=on_event,
            skill_manager=self.skill_manager,
            on_checkpoint=self.save_snapshot,
        )

    async def handle_input(self, text: str) -> LoopResult:
        self.save_snapshot()
        try:
            return await self.loop.handle_input(text)
        finally:
            self.save_snapshot()

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            workspace=str(self.workspace),
            permission_mode=self.permission_mode.value,
            state=self.machine.current.value,
            agents_updated=self.machine.agents_updated,
            plan=self.machine.plan.to_list(),
            history=[dict(message) for message in self.loop.history],
            summary=self.loop.summary,
            turns=self.loop._turns,
            tool_errors=self.loop._tool_errors,
            idempotency_records=self.registry.idempotency_records,
            loaded_skills=self.skill_manager.loaded_names,
            runtime_state=self.runtime_state,
            pending_interaction=(dict(self.pending_interaction) if self.pending_interaction else None),
        )

    def save_snapshot(self) -> Path:
        return self.session_store.save(self.snapshot())

    save = save_snapshot

    def restore_snapshot(self, snapshot: SessionSnapshot) -> None:
        if snapshot.workspace and Path(snapshot.workspace).resolve() != self.workspace:
            raise SessionStoreError(
                f"session workspace does not match current workspace: {snapshot.workspace}"
            )
        try:
            self.machine.current = type(self.machine.current)(snapshot.state)
        except ValueError as exc:
            raise SessionStoreError(f"invalid state in session snapshot: {snapshot.state}") from exc
        self.machine.agents_updated = snapshot.agents_updated
        self.machine.plan.replace(snapshot.plan)
        self.loop.history = [dict(message) for message in snapshot.history]
        self.loop.summary = snapshot.summary
        self.loop._turns = snapshot.turns
        self.loop._tool_errors = snapshot.tool_errors
        self.registry.restore_idempotency(snapshot.idempotency_records)
        self.skill_manager.restore(snapshot.loaded_skills)
        self.runtime_state = snapshot.runtime_state
        self.pending_interaction = (
            dict(snapshot.pending_interaction) if snapshot.pending_interaction is not None else None
        )

    @classmethod
    def resume(
        cls,
        model: Model | ModelRouter,
        workspace: str | Path,
        session_id: str,
        *,
        session_store: SessionStore | None = None,
        **kwargs: Any,
    ) -> Session:
        workspace_path = Path(workspace).resolve()
        store = session_store or SessionStore(workspace_path / ".nano-vibe" / "sessions")
        snapshot = store.load(session_id)
        mode = kwargs.pop("permission_mode", snapshot.permission_mode)
        session = cls(
            model,
            workspace_path,
            session_id=session_id,
            session_store=store,
            permission_mode=mode,
            **kwargs,
        )
        session.restore_snapshot(snapshot)
        return session

    from_snapshot = resume

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        workspace: str | Path,
        ui: Any,
        *,
        session_id: str | None = None,
        permission_mode: PermissionMode | str | None = None,
    ) -> Session:
        workspace_path = Path(workspace).resolve()
        project_root = Path(__file__).resolve().parents[2]
        workspace_id = hashlib.sha256(str(workspace_path).encode()).hexdigest()[:12]
        session_id = session_id or uuid.uuid4().hex[:12]
        trace = TraceWriter(project_root / "runs" / workspace_id / f"{session_id}.jsonl", session_id)
        model_instances = {
            name: OpenAICompatibleModel(
                model_config,
                retries=config.runtime.api_retries,
                on_text=ui.write_stream,
            )
            for name, model_config in config.models.items()
        }

        def config_key(model_config: Any) -> str:
            for name, configured in config.models.items():
                if configured is model_config or configured == model_config:
                    return name
            raise ValueError(f"model is not present in config: {model_config}")

        active_key = config_key(config.active_model)
        router = ModelRouter(
            model_instances,
            active_model=active_key,
            state_models={
                state: config_key(model_config)
                for state, model_config in config.state_models.items()
            },
            fallback_models=config.fallback_models,
            state_fallbacks=config.state_fallbacks,
        )
        return cls(
            router,
            workspace_path,
            trace=trace,
            session_id=session_id,
            session_store=SessionStore(
                Path(config.runtime.session_dir)
                if Path(config.runtime.session_dir).is_absolute()
                else workspace_path / config.runtime.session_dir
            ),
            permission_mode=permission_mode or config.runtime.permission_mode,
            permission_approve=getattr(ui, "approve", None),
            skill_roots=config.skill_roots or None,
            max_model_turns=config.runtime.max_model_turns,
            max_consecutive_tool_errors=config.runtime.max_consecutive_tool_errors,
            context_window=config.active_model.context_window,
            compact_ratio=config.runtime.compact_ratio,
            compact_target_ratio=config.runtime.compact_target_ratio,
            user_request_callback=ui.ask,
            on_tool=ui.tool_start,
            on_event=getattr(ui, "on_event", None),
            shell_timeout_seconds=config.runtime.shell_timeout_seconds,
            shell_max_output_chars=config.runtime.shell_max_output_chars,
            tavily_env_file=config.tavily.env_file,
        )
