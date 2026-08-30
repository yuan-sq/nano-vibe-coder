import subprocess
from pathlib import Path

import pytest

from nano_vibe.tools.apply_patch import ApplyPatchTool


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def replacement_diff(old: str, new: str) -> str:
    return f"""diff --git a/hello.txt b/hello.txt
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-{old}
+{new}
"""


@pytest.mark.asyncio
async def test_apply_patch_checks_and_applies_unified_diff(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "hello.txt").write_text("old\n", encoding="utf-8")

    result = await ApplyPatchTool(tmp_path).execute({"diff": replacement_diff("old", "new")})

    assert result.ok is True
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "new\n"
    assert result.metadata["checked"] is True


@pytest.mark.asyncio
async def test_apply_patch_does_not_modify_workspace_when_check_fails(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "hello.txt").write_text("old\n", encoding="utf-8")

    result = await ApplyPatchTool(tmp_path).execute({"diff": replacement_diff("wrong", "new")})

    assert result.ok is False
    assert result.metadata["checked"] is False
    assert result.error is not None
    assert result.error.code == "patch_check_failed"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_apply_patch_rejects_absolute_paths(tmp_path: Path) -> None:
    init_repo(tmp_path)
    diff = """diff --git a/etc/passwd b/etc/passwd
--- /etc/passwd
+++ /etc/passwd
@@ -1 +1 @@
-old
+new
"""

    result = await ApplyPatchTool(tmp_path).execute({"diff": diff})

    assert result.ok is False
    assert result.metadata["checked"] is False
    assert not (tmp_path / "etc" / "passwd").exists()
