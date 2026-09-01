"""Safe, bounded file-system tools rooted in the current workspace."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult

MAX_LIST_ENTRIES = 1_000
MAX_TEXT_CHARS = 100_000


class _FilesystemError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _WorkspacePaths:
    """Resolve relative paths without following workspace symlinks."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    def resolve(self, value: Any, *, allow_workspace: bool = False) -> tuple[Path, str]:
        if not isinstance(value, str) or not value.strip():
            raise _FilesystemError("invalid_path", "path must be a non-empty relative path")
        if "\x00" in value:
            raise _FilesystemError("invalid_path", "path contains an invalid character")
        requested = Path(value)
        if requested.is_absolute() or any(part == ".." for part in requested.parts):
            raise _FilesystemError("invalid_path", "path must stay inside the workspace")
        if not allow_workspace and requested in {Path("."), Path("")}:
            raise _FilesystemError("invalid_path", "path must name a file")

        current = self.workspace
        for part in requested.parts:
            if part in {"", "."}:
                continue
            current = current / part
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                break
            except (OSError, ValueError) as exc:
                raise _FilesystemError("path_error", f"could not inspect path: {exc}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise _FilesystemError("symlink_not_allowed", "symbolic links are not allowed")

        candidate = self.workspace / requested
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise _FilesystemError("path_outside_workspace", "path is outside the workspace") from exc
        except (OSError, RuntimeError) as exc:
            raise _FilesystemError("path_error", f"could not resolve path: {exc}") from exc
        relative = resolved.relative_to(self.workspace).as_posix() or "."
        return resolved, relative


def _failure(error: _FilesystemError) -> ToolResult:
    return ToolResult.failure(error.message, code=error.code)


def _path_error(path: Path, operation: str) -> ToolResult | None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return ToolResult.failure(f"path does not exist: {path}", code="path_not_found")
    except OSError as exc:
        return ToolResult.failure(f"could not {operation} path: {exc}", code=f"{operation}_error")
    if stat.S_ISLNK(metadata.st_mode):
        return ToolResult.failure("symbolic links are not allowed", code="symlink_not_allowed")
    return None


class ListTool(Tool):
    name = "list"
    description = "List one level of files and directories in the workspace."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
        "additionalProperties": False,
    }

    def __init__(self, workspace: str | Path) -> None:
        self.paths = _WorkspacePaths(workspace)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            directory, relative = self.paths.resolve(arguments.get("path", "."), allow_workspace=True)
        except _FilesystemError as exc:
            return _failure(exc)
        path_error = _path_error(directory, "list")
        if path_error is not None:
            return path_error
        try:
            metadata = os.lstat(directory)
            if not stat.S_ISDIR(metadata.st_mode):
                return ToolResult.failure("path is not a directory", code="not_a_directory")
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
            items: list[dict[str, str]] = []
            for entry in entries[:MAX_LIST_ENTRIES]:
                entry_metadata = os.lstat(entry)
                if stat.S_ISLNK(entry_metadata.st_mode):
                    entry_type = "symlink"
                elif stat.S_ISREG(entry_metadata.st_mode):
                    entry_type = "file"
                elif stat.S_ISDIR(entry_metadata.st_mode):
                    entry_type = "directory"
                else:
                    entry_type = "other"
                items.append(
                    {
                        "name": entry.name,
                        "path": entry.relative_to(self.paths.workspace).as_posix(),
                        "type": entry_type,
                    }
                )
        except FileNotFoundError as exc:
            return ToolResult.failure(f"path disappeared while listing: {exc}", code="path_not_found")
        except OSError as exc:
            return ToolResult.failure(f"could not list directory: {exc}", code="list_error")

        total = len(entries)
        return ToolResult.success(
            json.dumps(items, ensure_ascii=False),
            path=relative,
            count=len(items),
            total=total,
            truncated=total > MAX_LIST_ENTRIES,
        )


class ReadTool(Tool):
    name = "read"
    description = "Read a bounded UTF-8 text file from the workspace."
    permission_scope = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workspace: str | Path) -> None:
        self.paths = _WorkspacePaths(workspace)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            file_path, relative = self.paths.resolve(arguments.get("path"))
        except _FilesystemError as exc:
            return _failure(exc)
        path_error = _path_error(file_path, "read")
        if path_error is not None:
            return path_error
        try:
            metadata = os.lstat(file_path)
            if not stat.S_ISREG(metadata.st_mode):
                return ToolResult.failure("path is not a regular file", code="not_a_file")
            with file_path.open("r", encoding="utf-8") as handle:
                content = handle.read(MAX_TEXT_CHARS + 1)
        except UnicodeDecodeError as exc:
            return ToolResult.failure(f"file is not valid UTF-8: {exc}", code="invalid_utf8")
        except FileNotFoundError as exc:
            return ToolResult.failure(f"path disappeared while reading: {exc}", code="path_not_found")
        except OSError as exc:
            return ToolResult.failure(f"could not read file: {exc}", code="read_error")
        if len(content) > MAX_TEXT_CHARS:
            return ToolResult.failure(
                f"file exceeds the {MAX_TEXT_CHARS}-character limit",
                code="file_too_large",
            )
        return ToolResult.success(content, path=relative, chars=len(content))


class WriteTool(Tool):
    name = "write"
    description = "Create or overwrite a bounded UTF-8 text file in the workspace."
    permission_scope = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, workspace: str | Path) -> None:
        self.paths = _WorkspacePaths(workspace)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content")
        if not isinstance(content, str):
            return ToolResult.failure("content must be a string", code="invalid_content")
        if len(content) > MAX_TEXT_CHARS:
            return ToolResult.failure(
                f"content exceeds the {MAX_TEXT_CHARS}-character limit",
                code="content_too_large",
            )
        try:
            file_path, relative = self.paths.resolve(arguments.get("path"))
        except _FilesystemError as exc:
            return _failure(exc)

        parent_error = _path_error(file_path.parent, "write")
        if parent_error is not None:
            if parent_error.error is not None and parent_error.error.code == "path_not_found":
                return ToolResult.failure("parent directory does not exist", code="parent_not_found")
            return parent_error
        try:
            parent_metadata = os.lstat(file_path.parent)
            if not stat.S_ISDIR(parent_metadata.st_mode):
                return ToolResult.failure("parent path is not a directory", code="parent_not_directory")
            target_metadata = os.lstat(file_path)
        except FileNotFoundError:
            target_metadata = None
        except OSError as exc:
            return ToolResult.failure(f"could not inspect file: {exc}", code="write_error")

        created = target_metadata is None
        if target_metadata is not None:
            if stat.S_ISLNK(target_metadata.st_mode):
                return ToolResult.failure("symbolic links are not allowed", code="symlink_not_allowed")
            if not stat.S_ISREG(target_metadata.st_mode):
                return ToolResult.failure("path is not a regular file", code="not_a_file")

        try:
            _atomic_write(
                file_path,
                content,
                mode=(stat.S_IMODE(target_metadata.st_mode) if target_metadata is not None else 0o644),
            )
        except OSError as exc:
            return ToolResult.failure(f"could not write file: {exc}", code="write_error")
        return ToolResult.success(
            f"Wrote {relative}",
            path=relative,
            chars=len(content),
            created=created,
            overwritten=not created,
        )


def _atomic_write(target: Path, content: str, *, mode: int) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
