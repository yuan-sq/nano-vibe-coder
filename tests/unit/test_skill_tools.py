from pathlib import Path

import pytest

from nano_vibe.skills import SkillManager
from nano_vibe.tools.skills import LoadSkillTool, ReadSkillTool, UnloadSkillTool


@pytest.mark.asyncio
async def test_skill_tools_load_read_and_unload(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A demo.\n---\ncontent\n", encoding="utf-8"
    )
    manager = SkillManager(tmp_path)

    loaded = await LoadSkillTool(manager).execute({"name": "demo"})
    read = await ReadSkillTool(manager).execute({"name": "demo", "path": "SKILL.md"})
    unloaded = await UnloadSkillTool(manager).execute({"name": "demo"})

    assert loaded.ok is True
    assert read.ok is True and "content" in read.output
    assert unloaded.ok is True
    assert manager.loaded_names == []
