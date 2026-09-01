"""Read-only Git working-tree snapshots for the GUI Diff panel."""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import stat as stat_module
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Any

_INTERNAL_DIRS = {".git", ".nano-vibe"}
_GIT_TIMEOUT_SECONDS = 10.0
_READ_CHUNK_BYTES = 64 * 1024
_BASELINE_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_text(value: str) -> str:
    """Escape lone surrogates while preserving normal Unicode for JSON APIs."""

    return "".join(
        f"\\u{ord(char):04x}" if 0xD800 <= ord(char) <= 0xDFFF else char
        for char in value
    )


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
    task_patch: str | None = None
    # Kept for compatibility with the original GUI diff response.
    content: str | None = None
    symlink: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": _safe_json_text(self.path),
            "status": self.status,
            "git_status": self.git_status,
            "staged": self.staged,
            "unstaged": self.unstaged,
            "deleted": self.deleted,
            "task_changed": self.task_changed,
            "pre_existing": self.pre_existing,
            "binary": self.binary,
            "too_large": self.too_large,
            "symlink": self.symlink,
            "size": self.size,
            "staged_patch": self.staged_patch,
            "unstaged_patch": self.unstaged_patch,
            "task_patch": self.task_patch,
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
        self._baseline_contents: dict[str, str] = {}
        self._git_unavailable = False

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
                value = json.loads(path.read_text(encoding="utf-8"))
                self._baseline, self._baseline_contents = self._decode_persisted_baseline(
                    value, path
                )
                return self._baseline
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # A partial or incomplete file is recaptured as one atomic payload.
                pass
        self._baseline = self._capture_baseline()
        if path is not None:
            try:
                self._write_baseline(path, self._baseline, self._baseline_contents)
            except OSError:
                # Diff remains available even when its optional persistence location is
                # not writable (for example, a read-only checkout).
                pass
        return self._baseline

    def capture_baseline(self) -> None:
        """Capture the current work tree, preserving the V2 API."""
        self._baseline = self._capture_baseline()
        path = self.baseline_path
        if path is not None:
            try:
                self._write_baseline(path, self._baseline, self._baseline_contents)
            except OSError:
                pass

    def snapshot(self) -> DiffSnapshot:
        baseline = self.ensure_baseline()
        if not baseline.is_git:
            return DiffSnapshot(False, None, baseline.captured_at)
        if not self._is_git():
            return DiffSnapshot(False, None, baseline.captured_at)

        current = self._file_summaries()
        statuses = self._git_status()
        paths = set(baseline.files) | set(current) | set(statuses)
        entries: list[DiffEntry] = []
        patch_bytes = 0
        max_total_patch_bytes = max(self.max_file_bytes * 16, 256 * 1024)
        for path in sorted(paths):
            before = baseline.files.get(path)
            after = current.get(path)
            git_status = statuses.get(path, "")
            before_digest = before.get("sha256") if before else None
            after_digest = after.get("sha256") if after else None
            status_changed = baseline.statuses.get(path, "") != git_status
            mode_changed = bool(
                before is not None
                and after is not None
                and before.get("mode") is not None
                and before.get("mode") != after.get("mode")
            )
            task_changed = before_digest != after_digest or status_changed or mode_changed
            if not task_changed and not git_status:
                continue

            xy = git_status if len(git_status) == 2 else ""
            staged = bool(xy and xy[0] not in {" ", "?"})
            unstaged = bool(xy and xy[1] not in {" ", "?"})
            if git_status == "??":
                unstaged = True
            deleted = (after is None) or "D" in xy
            status = self._entry_status(path, before, after, git_status)
            index_summary = self._git_blob_summary(path, ":") if (staged or unstaged) else None
            head_summary = self._git_blob_summary(path, "HEAD") if staged else None
            summaries = [summary for summary in (before, after, index_summary, head_summary) if summary]
            binary = any(bool(summary.get("binary")) for summary in summaries)
            too_large = any(
                int(summary.get("size", 0)) > self.max_file_bytes for summary in summaries
            )
            symlink = any(bool(summary.get("symlink")) for summary in summaries)
            unsupported = binary or too_large or symlink
            size = (
                int(after.get("size", 0))
                if after
                else int(before.get("size", 0))
                if before
                else int(index_summary.get("size", 0))
                if index_summary
                else 0
            )
            staged_patch = None
            unstaged_patch = None
            if not unsupported and patch_bytes < max_total_patch_bytes:
                if staged:
                    staged_patch = self._patch(path, staged=True, untracked=False)
                    if staged_patch:
                        patch_bytes += len(staged_patch.encode("utf-8", errors="replace"))
                if unstaged and patch_bytes < max_total_patch_bytes:
                    unstaged_patch = self._patch(
                        path,
                        staged=False,
                        untracked=git_status == "??",
                    )
                    if unstaged_patch:
                        patch_bytes += len(unstaged_patch.encode("utf-8", errors="replace"))
            task_patch = (
                None
                if unsupported
                else self._task_patch(path, before, after, binary, too_large)
            )
            content = None
            if after is not None and not unsupported:
                content = self._read_current_text(path)
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
                    symlink=symlink,
                    size=size,
                    staged_patch=staged_patch,
                    unstaged_patch=unstaged_patch,
                    task_patch=task_patch,
                    content=content,
                )
            )
        return DiffSnapshot(True, baseline.head, baseline.captured_at, entries)

    def _capture_baseline(self) -> DiffBaseline:
        is_git = self._is_git()
        head = self._head() if is_git else None
        statuses = self._git_status() if is_git else {}
        files = self._file_summaries() if is_git else {}
        self._baseline_contents = self._capture_baseline_contents(files, statuses)
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
                "symlink": bool(summary.get("symlink", False)),
                "mode": summary.get("mode"),
            }
        return DiffBaseline(captured_at, is_git, head, statuses, files)

    def _decode_persisted_baseline(
        self, value: object, path: Path
    ) -> tuple[DiffBaseline, dict[str, str]]:
        baseline = self._decode_baseline(value)
        if not isinstance(value, dict):
            raise TypeError("baseline must be an object")
        if "contents" in value:
            contents_value = value["contents"]
            if not isinstance(contents_value, dict):
                raise TypeError("baseline contents are invalid")
            contents = self._decode_contents(contents_value)
            if not self._legacy_contents_complete(baseline, contents):
                raise ValueError("baseline contents are incomplete")
        else:
            # Version 1 stored this part in a sidecar.  Keep reading that format,
            # but reject an incomplete pair rather than silently producing a bad
            # task patch.
            contents = self._read_baseline_contents(path)
            if not self._legacy_contents_complete(baseline, contents):
                raise ValueError("legacy baseline contents are incomplete")
        return baseline, contents

    @staticmethod
    def _decode_contents(value: dict[object, object]) -> dict[str, str]:
        contents: dict[str, str] = {}
        for relative, content in value.items():
            if not isinstance(relative, str) or not isinstance(content, str):
                raise TypeError("baseline content entry is invalid")
            contents[relative] = content
        return contents

    def _legacy_contents_complete(
        self, baseline: DiffBaseline, contents: dict[str, str]
    ) -> bool:
        for path, status in baseline.statuses.items():
            summary = baseline.files.get(path)
            if not status or summary is None:
                continue
            if summary.get("binary") or summary.get("symlink"):
                continue
            if int(summary.get("size", 0)) > self.max_file_bytes:
                continue
            if path not in contents:
                return False
        return True

    @staticmethod
    def _write_baseline(
        path: Path, baseline: DiffBaseline, contents: dict[str, str] | None = None
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _BASELINE_VERSION,
            "captured_at": baseline.captured_at,
            "is_git": baseline.is_git,
            "head": baseline.head,
            "initial_status": baseline.statuses,
            "files": baseline.files,
            "contents": contents or {},
        }
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _read_baseline_contents(self, path: Path) -> dict[str, str]:
        content_path = path.with_name("diff-baseline-content.json")
        if not content_path.is_file():
            return {}
        try:
            value = json.loads(content_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        files = value.get("files", {}) if isinstance(value, dict) else {}
        return {
            str(relative): str(content)
            for relative, content in files.items()
            if isinstance(relative, str) and isinstance(content, str)
        } if isinstance(files, dict) else {}

    def _capture_baseline_contents(
        self,
        files: dict[str, dict[str, Any]],
        statuses: dict[str, str],
    ) -> dict[str, str]:
        contents: dict[str, str] = {}
        for path, summary in files.items():
            if (
                not statuses.get(path)
                or summary.get("binary")
                or summary.get("symlink")
                or int(summary.get("size", 0)) > self.max_file_bytes
            ):
                continue
            content = self._read_current_text(path)
            if content is not None:
                contents[path] = content
        return contents

    def _is_git(self) -> bool:
        if self._git_unavailable:
            return False
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
            summary = self._file_summary(path)
            if summary is not None:
                summaries[relative] = summary
        return summaries

    def _file_summary(self, path: Path) -> dict[str, Any] | None:
        """Hash a work-tree file incrementally without following symlinks."""

        try:
            metadata = path.lstat()
        except OSError:
            return None
        if stat_module.S_ISLNK(metadata.st_mode):
            try:
                target = os.readlink(path)
                target_bytes = target.encode("utf-8", errors="surrogateescape")
            except (OSError, UnicodeError):
                return None
            return {
                "sha256": hashlib.sha256(target_bytes).hexdigest(),
                "size": len(target_bytes),
                "binary": False,
                "symlink": True,
                "mode": metadata.st_mode & 0o7777,
            }
        if not stat_module.S_ISREG(metadata.st_mode):
            return None

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, os.O_RDONLY | nofollow)
        except OSError:
            return None
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                actual = os.fstat(handle.fileno())
                if not stat_module.S_ISREG(actual.st_mode) or (
                    actual.st_dev,
                    actual.st_ino,
                ) != (metadata.st_dev, metadata.st_ino):
                    return None
                digest = hashlib.sha256()
                decoder = codecs.getincrementaldecoder("utf-8")("strict")
                saw_nul = False
                invalid_utf8 = False
                size = 0
                while True:
                    chunk = handle.read(_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
                    saw_nul = saw_nul or b"\x00" in chunk
                    if not invalid_utf8:
                        try:
                            decoder.decode(chunk, final=False)
                        except UnicodeDecodeError:
                            invalid_utf8 = True
                if not invalid_utf8:
                    try:
                        decoder.decode(b"", final=True)
                    except UnicodeDecodeError:
                        invalid_utf8 = True
        except OSError:
            return None
        finally:
            if descriptor != -1:
                os.close(descriptor)
        return {
            "sha256": digest.hexdigest(),
            "size": size,
            "binary": saw_nul or invalid_utf8,
            "symlink": False,
            "mode": actual.st_mode & 0o7777,
        }

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
            if "R" in xy or "C" in xy:
                # With -z porcelain v1 emits the destination first, then the source.
                # Keep the destination as the status key and consume the source.
                if index >= len(fields):
                    continue
                index += 1
            if not self._is_internal_relative(path):
                statuses[path] = xy
        return statuses

    def _git_blob(self, path: str, ref: str) -> bytes | None:
        size = self._git_blob_size(path, ref)
        if size is None or size > self.max_file_bytes:
            return None
        result = self._run_git("show", self._git_object_name(path, ref))
        if result.returncode != 0 or len(result.stdout) > self.max_file_bytes:
            return None
        return result.stdout

    def _git_blob_size(self, path: str, ref: str) -> int | None:
        result = self._run_git("cat-file", "-s", self._git_object_name(path, ref))
        if result.returncode != 0:
            return None
        try:
            size = int(result.stdout.decode("ascii", errors="strict").strip())
        except (UnicodeDecodeError, ValueError):
            return None
        return size if size >= 0 else None

    @staticmethod
    def _git_object_name(path: str, ref: str) -> str:
        return f":{path}" if ref == ":" else f"{ref}:{path}"

    def _git_blob_summary(self, path: str, ref: str) -> dict[str, Any] | None:
        size = self._git_blob_size(path, ref)
        if size is None:
            return None
        mode = self._git_blob_mode(path, ref)
        if size > self.max_file_bytes:
            return {
                "sha256": "",
                "size": size,
                "binary": False,
                "symlink": mode == 0o120000,
                "mode": mode,
            }
        blob = self._git_blob(path, ref)
        if blob is None:
            return None
        if mode == 0o120000:
            return {
                "sha256": hashlib.sha256(blob).hexdigest(),
                "size": len(blob),
                "binary": False,
                "symlink": True,
                "mode": mode,
            }
        summary = self._inspect_bytes(blob, size=size)
        summary["mode"] = mode
        return summary

    def _git_blob_mode(self, path: str, ref: str) -> int | None:
        if ref == ":":
            result = self._run_git("ls-files", "--stage", "-z", "--", path)
        else:
            result = self._run_git("ls-tree", "-z", ref, "--", path)
        if result.returncode != 0:
            return None
        record = result.stdout.split(b"\0", 1)[0]
        if len(record) < 6:
            return None
        try:
            return int(record[:6], 8)
        except ValueError:
            return None

    @staticmethod
    def _inspect_bytes(raw: bytes, *, size: int | None = None) -> dict[str, Any]:
        invalid_utf8 = False
        try:
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            invalid_utf8 = True
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw) if size is None else size,
            "binary": b"\x00" in raw or invalid_utf8,
            "symlink": False,
            "mode": None,
        }

    def _read_current_text(self, path: str) -> str | None:
        """Read known-small regular files without following a replaced symlink."""

        file_path = self.workspace / path
        try:
            metadata = file_path.lstat()
        except OSError:
            return None
        if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_size > self.max_file_bytes:
            return None
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(file_path, os.O_RDONLY | nofollow)
        except OSError:
            return None
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                actual = os.fstat(handle.fileno())
                if not stat_module.S_ISREG(actual.st_mode) or (
                    actual.st_dev,
                    actual.st_ino,
                ) != (metadata.st_dev, metadata.st_ino):
                    return None
                raw = handle.read(self.max_file_bytes + 1)
        except OSError:
            return None
        finally:
            if descriptor != -1:
                os.close(descriptor)
        if len(raw) > self.max_file_bytes:
            return None
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None

    def _task_patch(
        self,
        path: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        binary: bool,
        too_large: bool,
    ) -> str | None:
        if binary or too_large:
            return None
        if path in self._baseline_contents:
            baseline = self._baseline_contents[path].encode("utf-8")
        elif self._baseline and self._baseline.head:
            baseline = self._git_blob(path, self._baseline.head) or b""
        else:
            baseline = b""
        if len(baseline) > self.max_file_bytes:
            return None
        if after is None:
            current = b""
        else:
            current = self._read_current_bytes(path)
            if current is None:
                return None
        if len(current) > self.max_file_bytes or current == baseline:
            return None
        try:
            old_lines = baseline.decode("utf-8", errors="strict").splitlines(keepends=True)
            new_lines = current.decode("utf-8", errors="strict").splitlines(keepends=True)
        except UnicodeDecodeError:
            return None
        patch = "".join(
            unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            )
        )
        return patch or None

    def _read_current_bytes(self, path: str) -> bytes | None:
        file_path = self.workspace / path
        try:
            metadata = file_path.lstat()
        except OSError:
            return None
        if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_size > self.max_file_bytes:
            return None
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(file_path, os.O_RDONLY | nofollow)
        except OSError:
            return None
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                actual = os.fstat(handle.fileno())
                if not stat_module.S_ISREG(actual.st_mode) or (
                    actual.st_dev,
                    actual.st_ino,
                ) != (metadata.st_dev, metadata.st_ino):
                    return None
                raw = handle.read(self.max_file_bytes + 1)
        except OSError:
            return None
        finally:
            if descriptor != -1:
                os.close(descriptor)
        return raw if len(raw) <= self.max_file_bytes else None

    def _patch(self, path: str, *, staged: bool, untracked: bool) -> str | None:
        if untracked:
            arguments = [
                "diff",
                "--no-index",
                "--no-ext-diff",
                "--no-color",
                "--",
                "/dev/null",
                path,
            ]
        else:
            arguments = ["diff", "--no-ext-diff", "--no-color", "--full-index"]
            if staged:
                arguments.append("--cached")
            arguments.extend(["--", path])
        result = self._run_git(*arguments)
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
        command = ["git", "-C", str(self.workspace), *arguments]
        try:
            return subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            self._git_unavailable = True
            return subprocess.CompletedProcess(
                command,
                returncode=127,
                stdout=b"",
                stderr=str(exc).encode("utf-8", errors="replace"),
            )

    def _is_internal(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.workspace).parts
        except ValueError:
            return True
        return any(part in _INTERNAL_DIRS for part in relative_parts)

    @staticmethod
    def _is_internal_relative(path: str) -> bool:
        return any(part in _INTERNAL_DIRS for part in Path(path).parts)
