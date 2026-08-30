from pathlib import Path

import pytest

from nano_vibe.skills import SkillError, SkillManager


def write_skill(root: Path, name: str = "demo") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demonstrate a skill.\n---\n\n# Demo\n\nUse carefully.\n",
        encoding="utf-8",
    )
    (path / "reference.md").write_text("reference text", encoding="utf-8")
    return path


def test_skill_manager_discovers_codex_skill_metadata_and_loads_content(tmp_path: Path) -> None:
    root = tmp_path / ".agents" / "skills"
    write_skill(root)
    manager = SkillManager(tmp_path)

    discovered = manager.discover()
    loaded = manager.load("demo")

    assert discovered["demo"].description == "Demonstrate a skill."
    assert loaded.name == "demo"
    assert "Use carefully." in loaded.content
    assert manager.loaded_names == ["demo"]


def test_skill_manager_reads_only_files_inside_loaded_skill(tmp_path: Path) -> None:
    root = tmp_path / ".codex" / "skills"
    write_skill(root)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    manager = SkillManager(tmp_path)
    manager.load("demo")

    assert manager.read("demo", "reference.md") == "reference text"
    with pytest.raises(SkillError, match="outside"):
        manager.read("demo", "../outside.md")


def test_skill_manager_unloads_and_restores_loaded_names(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root)
    manager = SkillManager(tmp_path, skill_roots=[root])
    manager.load("demo")
    manager.unload("demo")

    assert manager.loaded_names == []
    manager.restore(["demo"])
    assert manager.loaded_names == ["demo"]


def test_skill_manager_rejects_unknown_skill(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="not found"):
        SkillManager(tmp_path).load("missing")
