"""Read-only Git working-tree snapshots for the GUI Diff panel."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DiffEntry:
    path: str
    status: str
    git_status: str
    task_changed: bool
    pre_existing: bool
    binary: bool = False
    size: int = 0
    content: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "git_status": self.git_status,
            "task_changed": self.task_changed,
            "pre_existing": self.pre_existing,
            "binary": self.binary,
            "size": self.size,
            "content": self.content,
        }


@dataclass(frozen=True)
class DiffSnapshot:
    entries: list[DiffEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"entries": [entry.to_dict() for entry in self.entries]}


class GitDiffService:
    def __init__(self, workspace: str | Path, *, max_file_bytes: int = 1_000_000) -> None:
        self.workspace = Path(workspace).resolve()
        self.max_file_bytes = max_file_bytes
        self._baseline: dict[str, str] = {}
        self._pre_existing: set[str] = set()

    def capture_baseline(self) -> None:
        self._baseline = self._file_digests()
        self._pre_existing = set(self._git_status())

    def snapshot(self) -> DiffSnapshot:
        if not self._baseline:
            self.capture_baseline()
        current = self._file_digests()
        statuses = self._git_status()
        entries: list[DiffEntry] = []
        for path in sorted(set(self._baseline) | set(current)):
            before = self._baseline.get(path)
            after = current.get(path)
            git_status = statuses.get(path, "")
            if before == after and not git_status:
                continue
            if after is None:
                status = "deleted"
                size = 0
                binary = False
                content = None
            else:
                file_path = self.workspace / path
                raw = file_path.read_bytes()
                size = len(raw)
                binary = b"\x00" in raw or size > self.max_file_bytes
                status = "untracked" if git_status == "??" else ("added" if before is None else "modified")
                content = None if binary else raw.decode("utf-8", errors="replace")
            entries.append(
                DiffEntry(
                    path=path,
                    status=status,
                    git_status=git_status,
                    task_changed=before != after,
                    pre_existing=path in self._pre_existing,
                    binary=binary,
                    size=size,
                    content=content,
                )
            )
        return DiffSnapshot(entries)

    def _file_digests(self) -> dict[str, str]:
        result = subprocess.run(
            ["git", "-C", str(self.workspace), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
        )
        digests: dict[str, str] = {}
        for raw_path in result.stdout.split(b"\0"):
            if not raw_path:
                continue
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            path = self.workspace / relative
            if path.is_file():
                digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digests

    def _git_status(self) -> dict[str, str]:
        result = subprocess.run(
            ["git", "-C", str(self.workspace), "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            check=True,
        )
        statuses: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            statuses[line[3:]] = line[:2].strip() or line[:2]
        return statuses
