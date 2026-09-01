"""Read-only Git working-tree snapshots for the GUI Diff panel."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INTERNAL_DIRS = {".git", ".nano-vibe"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DiffBaseline:
    captured_at: str
    is_git: bool
    head: str | None
    statuses: dict[str, str] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class DiffEntry:
    path: str
    status: str
    git_status: str
    staged: bool
    unstaged: bool
    deleted: bool
    task_changed: bool
    pre_existing: bool
    binary: bool = False
    too_large: bool = False
    size: int = 0
    staged_patch: str | None = None
    unstaged_patch: str | None = None
    # Kept for compatibility with the original GUI diff response.
    content: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "git_status": self.git_status,
            "staged": self.staged,
            "unstaged": self.unstaged,
            "deleted": self.deleted,
            "task_changed": self.task_changed,
            "pre_existing": self.pre_existing,
            "binary": self.binary,
            "too_large": self.too_large,
            "size": self.size,
            "staged_patch": self.staged_patch,
            "unstaged_patch": self.unstaged_patch,
            "content": self.content,
        }


@dataclass(frozen=True)
class DiffSnapshot:
    is_git: bool
    head: str | None
    baseline_captured_at: str
    entries: list[DiffEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "is_git": self.is_git,
            "head": self.head,
            "baseline_captured_at": self.baseline_captured_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class GitDiffService:
    def __init__(
        self,
        workspace: str | Path,
        session_id: str | None = None,
        *,
        max_file_bytes: int = 1_000_000,
    ) -> None:
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        self.workspace = Path(workspace).resolve()
        self.session_id = session_id
        self.max_file_bytes = max_file_bytes
        self._baseline: DiffBaseline | None = None

    @property
    def baseline_path(self) -> Path | None:
        if self.session_id is None:
            return None
        return self.workspace / ".nano-vibe" / "gui" / self.session_id / "diff-baseline.json"

    def ensure_baseline(self) -> DiffBaseline:
        if self._baseline is not None:
            return self._baseline
        path = self.baseline_path
        if path is not None and path.is_file():
            try:
                self._baseline = self._decode_baseline(json.loads(path.read_text(encoding="utf-8")))
                return self._baseline
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # A partial or old file must not make the read-only panel fail forever.
                pass
        self._baseline = self._capture_baseline()
        if path is not None:
            self._write_baseline(path, self._baseline)
        return self._baseline

    def capture_baseline(self) -> None:
        """Capture the current work tree, preserving the V2 API."""
        self._baseline = self._capture_baseline()
        path = self.baseline_path
        if path is not None:
            self._write_baseline(path, self._baseline)

    def snapshot(self) -> DiffSnapshot:
        baseline = self.ensure_baseline()
        if not baseline.is_git:
            return DiffSnapshot(False, None, baseline.captured_at)

        current = self._file_summaries()
        statuses = self._git_status()
        paths = set(baseline.files) | set(current) | set(statuses)
        entries: list[DiffEntry] = []
        for path in sorted(paths):
            before = baseline.files.get(path)
            after = current.get(path)
            git_status = statuses.get(path, "")
            before_digest = before.get("sha256") if before else None
            after_digest = after.get("sha256") if after else None
            task_changed = before_digest != after_digest
            if not task_changed and not git_status:
                continue

            xy = git_status if len(git_status) == 2 else ""
            staged = bool(xy and xy[0] not in {" ", "?"})
            unstaged = bool(xy and xy[1] not in {" ", "?"})
            if git_status == "??":
                unstaged = True
            deleted = (after is None) or "D" in xy
            status = self._entry_status(path, before, after, git_status)
            source_bytes = self._source_bytes(path, before, after, staged, unstaged, deleted)
            binary = any(b"\x00" in value for value in source_bytes)
            too_large = any(len(value) > self.max_file_bytes for value in source_bytes)
            size = int(after.get("size", 0)) if after else int(before.get("size", 0)) if before else 0
            staged_patch = self._patch(path, staged=True, untracked=False) if staged else None
            unstaged_patch = self._patch(
                path,
                staged=False,
                untracked=git_status == "??",
            ) if unstaged else None
            if binary or too_large:
                staged_patch = None
                unstaged_patch = None
            content = None
            if after is not None and not binary and not too_large:
                try:
                    content = (self.workspace / path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = None
            entries.append(
                DiffEntry(
                    path=path,
                    status=status,
                    git_status=git_status,
                    staged=staged,
                    unstaged=unstaged,
                    deleted=deleted,
                    task_changed=task_changed,
                    pre_existing=path in baseline.statuses and bool(baseline.statuses[path]),
                    binary=binary,
                    too_large=too_large,
                    size=size,
                    staged_patch=staged_patch,
                    unstaged_patch=unstaged_patch,
                    content=content,
                )
            )
        return DiffSnapshot(True, baseline.head, baseline.captured_at, entries)

    def _capture_baseline(self) -> DiffBaseline:
        is_git = self._is_git()
        head = self._head() if is_git else None
        statuses = self._git_status() if is_git else {}
        files = self._file_summaries() if is_git else {}
        return DiffBaseline(_now(), is_git, head, statuses, files)

    def _decode_baseline(self, value: object) -> DiffBaseline:
        if not isinstance(value, dict):
            raise TypeError("baseline must be an object")
        captured_at = value.get("captured_at")
        if not isinstance(captured_at, str) or not captured_at:
            raise ValueError("baseline captured_at is missing")
        is_git = value.get("is_git")
        if not isinstance(is_git, bool):
            raise TypeError("baseline is_git is invalid")
        head = value.get("head")
        if head is not None and not isinstance(head, str):
            raise ValueError("baseline head is invalid")
        statuses_value = value.get("initial_status", {})
        files_value = value.get("files", {})
        if not isinstance(statuses_value, dict) or not isinstance(files_value, dict):
            raise TypeError("baseline summaries are invalid")
        statuses = {str(path): str(status) for path, status in statuses_value.items()}
        files: dict[str, dict[str, Any]] = {}
        for path, summary in files_value.items():
            if not isinstance(summary, dict) or not isinstance(summary.get("sha256"), str):
                raise TypeError("baseline file summary is invalid")
            files[str(path)] = {
                "sha256": summary["sha256"],
                "size": int(summary.get("size", 0)),
                "binary": bool(summary.get("binary", False)),
            }
        return DiffBaseline(captured_at, is_git, head, statuses, files)

    @staticmethod
    def _write_baseline(path: Path, baseline: DiffBaseline) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "captured_at": baseline.captured_at,
            "is_git": baseline.is_git,
            "head": baseline.head,
            "initial_status": baseline.statuses,
            "files": baseline.files,
        }
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _is_git(self) -> bool:
        result = self._run_git("rev-parse", "--is-inside-work-tree")
        return result.returncode == 0 and result.stdout.decode(errors="replace").strip() == "true"

    def _head(self) -> str | None:
        result = self._run_git("rev-parse", "--verify", "HEAD")
        return result.stdout.decode(errors="replace").strip() if result.returncode == 0 else None

    def _file_summaries(self) -> dict[str, dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        result = self._run_git("ls-files", "-co", "--exclude-standard", "-z")
        if result.returncode != 0:
            return summaries
        relative_paths = result.stdout.split(b"\0")
        for raw_path in relative_paths:
            if not raw_path:
                continue
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            if self._is_internal_relative(relative):
                continue
            path = self.workspace / relative
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            summaries[relative] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "binary": b"\x00" in raw,
            }
        return summaries

    def _git_status(self) -> dict[str, str]:
        result = self._run_git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if result.returncode != 0:
            return {}
        statuses: dict[str, str] = {}
        fields = result.stdout.split(b"\0")
        index = 0
        while index < len(fields):
            field = fields[index]
            index += 1
            if not field or len(field) < 3:
                continue
            xy = field[:2].decode("ascii", errors="replace")
            path_bytes = field[3:]
            path = path_bytes.decode("utf-8", errors="surrogateescape")
            if ("R" in xy or "C" in xy) and index < len(fields):
                # Porcelain -z puts the destination after the source for renames/copies.
                path = fields[index].decode("utf-8", errors="surrogateescape")
                index += 1
            if not self._is_internal_relative(path):
                statuses[path] = xy
        return statuses

    def _source_bytes(
        self,
        path: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        staged: bool,
        unstaged: bool,
        deleted: bool,
    ) -> list[bytes]:
        values: list[bytes] = []
        if after is not None:
            try:
                values.append((self.workspace / path).read_bytes())
            except OSError:
                pass
        if before is not None and (deleted or not after):
            if before.get("binary"):
                values.append(b"\x00")
            values.append(b"x" * min(int(before.get("size", 0)), self.max_file_bytes + 1))
        if staged:
            value = self._git_blob(path, "HEAD")
            if value is not None:
                values.append(value)
        if unstaged and not deleted:
            value = self._git_blob(path, ":")
            if value is not None:
                values.append(value)
        return values

    def _git_blob(self, path: str, ref: str) -> bytes | None:
        result = self._run_git("show", f"{ref}:{path}")
        return result.stdout if result.returncode == 0 else None

    def _patch(self, path: str, *, staged: bool, untracked: bool) -> str | None:
        if untracked:
            result = subprocess.run(
                ["git", "-C", str(self.workspace), "diff", "--no-index", "--no-ext-diff", "--no-color", "/dev/null", path],
                capture_output=True,
                check=False,
            )
        else:
            arguments = ["diff", "--no-ext-diff", "--no-color", "--full-index"]
            if staged:
                arguments.append("--cached")
            arguments.extend(["--", path])
            result = subprocess.run(
                ["git", "-C", str(self.workspace), *arguments],
                capture_output=True,
                check=False,
            )
        if result.returncode not in (0, 1):
            return None
        return result.stdout.decode("utf-8", errors="replace") or None

    def _entry_status(
        self,
        path: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        git_status: str,
    ) -> str:
        if after is None or "D" in git_status:
            return "deleted"
        if git_status == "??":
            return "untracked"
        if before is None:
            return "added"
        return "modified"

    def _run_git(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "-C", str(self.workspace), *arguments],
            capture_output=True,
            check=False,
        )
        return result

    def _is_internal(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.workspace).parts
        except ValueError:
            return True
        return any(part in _INTERNAL_DIRS for part in relative_parts)

    @staticmethod
    def _is_internal_relative(path: str) -> bool:
        return any(part in _INTERNAL_DIRS for part in Path(path).parts)
