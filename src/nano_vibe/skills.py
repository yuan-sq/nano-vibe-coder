"""Safe loader for Codex-compatible ``SKILL.md`` skill packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class SkillError(ValueError):
    """Raised when a skill cannot be discovered, loaded, or read safely."""


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    front_matter: Mapping[str, str]


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    path: Path
    content: str
    full_content: str

    def context_entry(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }


class SkillManager:
    """Discover and manage read-only skill packages below approved roots."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        skill_roots: Iterable[str | Path] | None = None,
        max_skill_chars: int = 100_000,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        roots = skill_roots if skill_roots is not None else (
            self.workspace / ".agents" / "skills",
            self.workspace / ".codex" / "skills",
        )
        self.skill_roots = tuple(Path(root).expanduser().resolve() for root in roots)
        if max_skill_chars <= 0:
            raise ValueError("max_skill_chars must be positive")
        self.max_skill_chars = max_skill_chars
        self._loaded: dict[str, LoadedSkill] = {}

    @property
    def loaded_names(self) -> list[str]:
        return list(self._loaded)

    @property
    def loaded(self) -> Mapping[str, LoadedSkill]:
        return dict(self._loaded)

    def discover(self) -> dict[str, SkillMetadata]:
        result: dict[str, SkillMetadata] = {}
        for root in self.skill_roots:
            if not root.is_dir():
                continue
            candidates = [root] if (root / "SKILL.md").is_file() else sorted(root.iterdir())
            for candidate in candidates:
                if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                    metadata = self._metadata(candidate)
                    result.setdefault(metadata.name, metadata)
        return result

    def metadata(self, name: str) -> SkillMetadata:
        metadata = self.discover().get(name)
        if metadata is None:
            raise SkillError(f"skill not found: {name}")
        return metadata

    def load(self, name: str) -> LoadedSkill:
        if name in self._loaded:
            return self._loaded[name]
        metadata = self.metadata(name)
        skill_file = metadata.path / "SKILL.md"
        try:
            full_content = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"could not read skill {name}: {exc}") from exc
        if len(full_content) > self.max_skill_chars:
            raise SkillError(f"skill {name} exceeds the maximum size")
        _, content = _parse_skill_file(full_content, metadata.path.name)
        loaded = LoadedSkill(
            name=metadata.name,
            description=metadata.description,
            path=metadata.path,
            content=content,
            full_content=full_content,
        )
        self._loaded[name] = loaded
        return loaded

    def read(self, name: str, relative_path: str = "SKILL.md") -> str:
        skill = self._loaded.get(name) or self.load(name)
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise SkillError("skill path must be a non-empty relative path")
        requested = Path(relative_path)
        if requested.is_absolute():
            raise SkillError("skill path is outside the skill package")
        candidate = (skill.path / requested).resolve()
        try:
            candidate.relative_to(skill.path)
        except ValueError as exc:
            raise SkillError("skill path is outside the skill package") from exc
        if not candidate.is_file():
            raise SkillError(f"skill file not found: {relative_path}")
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"could not read skill file: {exc}") from exc
        if len(content) > self.max_skill_chars:
            raise SkillError("skill file exceeds the maximum size")
        return content

    def unload(self, name: str) -> bool:
        return self._loaded.pop(name, None) is not None

    def restore(self, names: Iterable[str]) -> None:
        self._loaded.clear()
        for name in names:
            if not isinstance(name, str):
                raise SkillError("loaded skill names must be strings")
            self.load(name)

    def context_entries(self) -> list[dict[str, str]]:
        return [skill.context_entry() for skill in self._loaded.values()]

    def _metadata(self, directory: Path) -> SkillMetadata:
        skill_file = directory / "SKILL.md"
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"could not inspect skill: {exc}") from exc
        front_matter, _ = _parse_skill_file(raw, directory.name)
        name = front_matter.get("name", directory.name).strip()
        description = front_matter.get("description", "").strip()
        if not name:
            raise SkillError(f"skill name is empty: {directory}")
        return SkillMetadata(name, description, directory.resolve(), front_matter)


_FRONT_MATTER_LINE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$")


def _parse_skill_file(raw: str, fallback_name: str) -> tuple[dict[str, str], str]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return ({"name": fallback_name, "description": ""}, raw)
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return ({"name": fallback_name, "description": ""}, raw)
    front_matter: dict[str, str] = {}
    for line in lines[1:end]:
        match = _FRONT_MATTER_LINE.match(line.rstrip("\r\n"))
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            front_matter[match.group(1)] = value
    return front_matter, "".join(lines[end + 1 :])
