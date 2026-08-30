"""Tools exposing the read-only Codex skill lifecycle to the model."""

from __future__ import annotations

from typing import Any, ClassVar

from nano_vibe.skills import SkillError, SkillManager

from .base import Tool, ToolResult


class LoadSkillTool(Tool):
    name = "load_skill"
    description = "Load a Codex-compatible SKILL.md package into the task context."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, manager: SkillManager) -> None:
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult.failure("skill name must be a non-empty string", code="invalid_skill")
        try:
            skill = self.manager.load(name)
        except SkillError as exc:
            return ToolResult.failure(str(exc), code="skill_load_error")
        return ToolResult.success(
            f"Skill loaded: {skill.name}",
            name=skill.name,
            description=skill.description,
            path=str(skill.path),
        )


class ReadSkillTool(Tool):
    name = "read_skill"
    description = "Read a file from a previously discoverable skill package."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "path": {"type": "string", "default": "SKILL.md"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, manager: SkillManager) -> None:
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name")
        relative_path = arguments.get("path", "SKILL.md")
        if not isinstance(name, str) or not isinstance(relative_path, str):
            return ToolResult.failure("skill name and path must be strings", code="invalid_skill")
        try:
            content = self.manager.read(name, relative_path)
        except SkillError as exc:
            return ToolResult.failure(str(exc), code="skill_read_error")
        return ToolResult.success(content, name=name, path=relative_path)


class UnloadSkillTool(Tool):
    name = "unload_skill"
    description = "Remove a loaded skill from the task context without deleting files."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, manager: SkillManager) -> None:
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult.failure("skill name must be a non-empty string", code="invalid_skill")
        removed = self.manager.unload(name)
        return ToolResult.success(
            f"Skill {'unloaded' if removed else 'was not loaded'}: {name}",
            name=name,
            unloaded=removed,
        )


SkillLoadTool = LoadSkillTool
SkillReadTool = ReadSkillTool
SkillUnloadTool = UnloadSkillTool
