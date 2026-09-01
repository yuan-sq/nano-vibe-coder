import asyncio
import json
import os
import stat
from pathlib import Path

import pytest

import nano_vibe.tools.filesystem as filesystem_module
from nano_vibe.tools.base import ToolResult
from nano_vibe.tools.filesystem import ListTool, ReadTool, WriteTool


def _error_code(result: ToolResult) -> str:
    error = result.error
    assert error is not None
    return error.code


@pytest.mark.asyncio
async def test_list_defaults_to_workspace_and_returns_sorted_one_level_entries(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "z.txt")

    result = await ListTool(tmp_path).execute({})

    assert result.ok is True
    assert json.loads(result.output) == [
        {"name": ".hidden", "path": ".hidden", "type": "file"},
        {"name": "a-dir", "path": "a-dir", "type": "directory"},
        {"name": "link", "path": "link", "type": "symlink"},
        {"name": "z.txt", "path": "z.txt", "type": "file"},
    ]
    assert result.metadata == {"path": ".", "count": 4, "total": 4, "truncated": False}


@pytest.mark.asyncio
async def test_list_truncates_after_one_thousand_entries(tmp_path: Path) -> None:
    for index in range(1005):
        (tmp_path / f"item-{index:04d}.txt").write_text("", encoding="utf-8")

    result = await ListTool(tmp_path).execute({"path": "."})

    assert result.ok is True
    entries = json.loads(result.output)
    assert len(entries) == 1000
    assert entries[0]["name"] == "item-0000.txt"
    assert entries[-1]["name"] == "item-0999.txt"
    assert result.metadata == {"path": ".", "count": 1000, "total": 1005, "truncated": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", "/tmp", "../outside"])
async def test_list_rejects_invalid_paths(tmp_path: Path, path: str) -> None:
    result = await ListTool(tmp_path).execute({"path": path})

    assert result.ok is False
    assert _error_code(result) == "invalid_path"


@pytest.mark.asyncio
async def test_list_rejects_missing_file_and_non_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")
    tool = ListTool(tmp_path)

    missing = await tool.execute({"path": "missing"})
    not_directory = await tool.execute({"path": "file.txt"})

    assert _error_code(missing) == "path_not_found"
    assert _error_code(not_directory) == "not_a_directory"


@pytest.mark.asyncio
async def test_list_rejects_symlink_directory_without_following_it(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "linked").symlink_to(target, target_is_directory=True)

    result = await ListTool(tmp_path).execute({"path": "linked"})

    assert result.ok is False
    assert _error_code(result) == "symlink_not_allowed"


@pytest.mark.asyncio
async def test_read_returns_utf8_text_and_supports_empty_files(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("你好\nworld", encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    tool = ReadTool(tmp_path)

    text = await tool.execute({"path": "hello.txt"})
    empty = await tool.execute({"path": "empty.txt"})

    assert text.ok is True
    assert text.output == "你好\nworld"
    assert text.metadata == {"path": "hello.txt", "chars": 8}
    assert empty.ok is True
    assert empty.output == ""
    assert empty.metadata == {"path": "empty.txt", "chars": 0}


@pytest.mark.asyncio
async def test_read_rejects_directory_missing_path_invalid_utf8_and_too_large(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "invalid.bin").write_bytes(b"\xff")
    (tmp_path / "large.txt").write_text("x" * 100001, encoding="utf-8")
    tool = ReadTool(tmp_path)

    results = await asyncio.gather(
        tool.execute({"path": "directory"}),
        tool.execute({"path": "missing.txt"}),
        tool.execute({"path": "invalid.bin"}),
        tool.execute({"path": "large.txt"}),
    )

    assert [_error_code(result) for result in results] == [
        "not_a_file",
        "path_not_found",
        "invalid_utf8",
        "file_too_large",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/tmp/file.txt", "../file.txt"])
async def test_read_rejects_absolute_and_parent_traversal_paths(tmp_path: Path, path: str) -> None:
    result = await ReadTool(tmp_path).execute({"path": path})

    assert result.ok is False
    assert _error_code(result) == "invalid_path"


@pytest.mark.asyncio
async def test_read_rejects_symlink_file_and_symlink_parent(tmp_path: Path) -> None:
    (tmp_path / "target.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    tool = ReadTool(tmp_path)

    direct = await tool.execute({"path": "link.txt"})
    parent = await tool.execute({"path": "linked/nested.txt"})

    assert _error_code(direct) == "symlink_not_allowed"
    assert _error_code(parent) == "symlink_not_allowed"


@pytest.mark.asyncio
async def test_write_creates_overwrites_and_allows_empty_content(tmp_path: Path) -> None:
    tool = WriteTool(tmp_path)

    created = await tool.execute({"path": "new.txt", "content": "first"})
    overwritten = await tool.execute({"path": "new.txt", "content": "second"})
    emptied = await tool.execute({"path": "new.txt", "content": ""})

    assert created.ok is True
    assert created.output == "Wrote new.txt"
    assert created.metadata == {"path": "new.txt", "chars": 5, "created": True, "overwritten": False}
    assert overwritten.metadata == {"path": "new.txt", "chars": 6, "created": False, "overwritten": True}
    assert emptied.ok is True
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_write_preserves_existing_permissions(tmp_path: Path) -> None:
    target = tmp_path / "mode.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    result = await WriteTool(tmp_path).execute({"path": "mode.txt", "content": "new"})

    assert result.ok is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/tmp/file.txt", "../file.txt", "missing/file.txt"])
async def test_write_rejects_invalid_or_missing_parent_paths(tmp_path: Path, path: str) -> None:
    result = await WriteTool(tmp_path).execute({"path": path, "content": "content"})

    assert result.ok is False
    assert _error_code(result) in {"invalid_path", "parent_not_found"}


@pytest.mark.asyncio
async def test_write_rejects_directory_symlink_and_oversized_targets(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "target.txt").write_text("target", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    tool = WriteTool(tmp_path)

    directory = await tool.execute({"path": "directory", "content": "content"})
    symlink = await tool.execute({"path": "link.txt", "content": "content"})
    oversized = await tool.execute({"path": "large.txt", "content": "x" * 100001})

    assert _error_code(directory) == "not_a_file"
    assert _error_code(symlink) == "symlink_not_allowed"
    assert _error_code(oversized) == "content_too_large"


@pytest.mark.asyncio
async def test_write_rejects_symlink_parent_without_touching_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested.txt").write_text("old", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    result = await WriteTool(tmp_path).execute({"path": "linked/nested.txt", "content": "new"})

    assert _error_code(result) == "symlink_not_allowed"
    assert (outside / "nested.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_write_cleans_temporary_file_when_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source: str | bytes | os.PathLike[str], _destination: str | bytes | os.PathLike[str]) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(filesystem_module.os, "replace", fail_replace)
    result = await WriteTool(tmp_path).execute({"path": "existing.txt", "content": "new"})

    assert _error_code(result) == "write_error"
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]
