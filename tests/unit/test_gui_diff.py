import json
import os
import subprocess
from pathlib import Path

import pytest

from nano_vibe.gui.diff import GitDiffService


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.email", "tests@example.test")
    _git(path, "config", "user.name", "Tests")
    return path


def _commit_all(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "initial")


def test_diff_baseline_is_persisted_and_reused_across_service_instances(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("pre-existing\n", encoding="utf-8")

    first = GitDiffService(repo, "session-1")
    baseline = first.ensure_baseline()
    initial = first.snapshot().to_dict()
    baseline_path = repo / ".nano-vibe" / "gui" / "session-1" / "diff-baseline.json"

    assert baseline_path.is_file()
    assert json.loads(baseline_path.read_text(encoding="utf-8"))["captured_at"] == baseline.captured_at
    assert initial["entries"][0]["pre_existing"] is True  # type: ignore[index]
    assert initial["entries"][0]["task_changed"] is False  # type: ignore[index]

    tracked.write_text("task change\n", encoding="utf-8")
    second = GitDiffService(repo, "session-1")
    reused = second.ensure_baseline()
    changed = second.snapshot().to_dict()

    assert reused.captured_at == baseline.captured_at
    assert changed["entries"][0]["task_changed"] is True  # type: ignore[index]


def test_diff_reports_git_kinds_metadata_and_real_unified_patches(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    for name in ("unstaged.txt", "staged.txt", "deleted.txt", "binary.bin", "large.txt"):
        (repo / name).write_text(f"old {name}\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1", max_file_bytes=20)
    service.ensure_baseline()

    (repo / "unstaged.txt").write_text("new unstaged\n", encoding="utf-8")
    (repo / "staged.txt").write_text("new staged\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "deleted.txt").unlink()
    (repo / "untracked.txt").write_text("brand new\n", encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"old\x00new")
    (repo / "large.txt").write_text("x" * 30, encoding="utf-8")

    body = service.snapshot().to_dict()
    entries = {entry["path"]: entry for entry in body["entries"]}  # type: ignore[index]

    assert entries["staged.txt"]["staged"] is True
    assert "@@" in entries["staged.txt"]["staged_patch"]
    assert "+new staged" in entries["staged.txt"]["staged_patch"]
    assert entries["unstaged.txt"]["unstaged"] is True
    assert "-old unstaged.txt" in entries["unstaged.txt"]["unstaged_patch"]
    assert entries["untracked.txt"]["status"] == "untracked"
    assert "+++ b/untracked.txt" in entries["untracked.txt"]["unstaged_patch"]
    assert entries["deleted.txt"]["deleted"] is True
    assert entries["binary.bin"]["binary"] is True
    assert entries["binary.bin"]["unstaged_patch"] is None
    assert entries["large.txt"]["too_large"] is True
    assert entries["large.txt"]["unstaged_patch"] is None


def test_diff_is_stable_for_non_git_and_unborn_repositories(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    non_git = GitDiffService(plain, "session-1")
    baseline = non_git.ensure_baseline()

    assert non_git.snapshot().to_dict() == {
        "is_git": False,
        "head": None,
        "baseline_captured_at": baseline.captured_at,
        "entries": [],
    }

    unborn = _repo(tmp_path / "unborn")
    (unborn / "new.txt").write_text("new\n", encoding="utf-8")
    service = GitDiffService(unborn, "session-2")
    body = service.snapshot().to_dict()

    assert body["is_git"] is True
    assert body["head"] is None
    assert body["entries"][0]["status"] == "untracked"  # type: ignore[index]


def test_task_changed_tracks_status_and_mode_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("same\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()

    tracked.chmod(0o755)
    entry = {item["path"]: item for item in service.snapshot().to_dict()["entries"]}["tracked.txt"]  # type: ignore[index]
    assert entry["task_changed"] is True
    _git(repo, "add", "tracked.txt")
    tracked.chmod(0o644)
    entry = {item["path"]: item for item in service.snapshot().to_dict()["entries"]}["tracked.txt"]  # type: ignore[index]
    assert entry["task_changed"] is True


def test_task_patch_survives_a_task_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("old\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()

    tracked.write_text("new\n", encoding="utf-8")
    _commit_all(repo)
    entry = service.snapshot().to_dict()["entries"][0]  # type: ignore[index]
    assert entry["task_changed"] is True
    assert "-old" in entry["task_patch"]
    assert "+new" in entry["task_patch"]


def test_rename_status_uses_destination_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    original = repo / "old.txt"
    original.write_text("content\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()

    _git(repo, "mv", "old.txt", "new.txt")

    entries = {item["path"]: item for item in service.snapshot().to_dict()["entries"]}  # type: ignore[index]
    assert entries["new.txt"]["git_status"] == "R "
    assert entries["old.txt"]["deleted"] is True


def test_symlink_snapshot_never_reads_external_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    external = tmp_path / "external-secret.txt"
    external.write_text("TOP SECRET v1\n", encoding="utf-8")
    link = repo / "external.txt"
    link.symlink_to(external)
    _commit_all(repo)

    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()
    external.write_text("TOP SECRET v2\n", encoding="utf-8")

    body = service.snapshot().to_dict()
    encoded = json.dumps(body, ensure_ascii=False)
    assert "TOP SECRET" not in encoded
    assert body["entries"] == []

    link.unlink()
    link.symlink_to(tmp_path / "other.txt")
    changed = service.snapshot().to_dict()["entries"][0]  # type: ignore[index]
    assert changed["symlink"] is True
    assert changed["content"] is None
    assert changed["task_patch"] is None
    assert changed["unstaged_patch"] is None


def test_invalid_utf8_file_is_binary_and_json_path_is_safe(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("requires Unix byte paths")
    repo = _repo(tmp_path / "repo")
    invalid_name = os.fsdecode(b"invalid-\xff.txt")
    invalid = repo / invalid_name
    try:
        fd = os.open(
            os.fsencode(invalid), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
        )
    except OSError:
        pytest.skip("filesystem does not support invalid UTF-8 names")
    with os.fdopen(fd, "wb") as handle:
        handle.write(b"not utf8: \xff\n")

    body = GitDiffService(repo, "session-1").snapshot().to_dict()
    entry = body["entries"][0]  # type: ignore[index]
    assert entry["binary"] is True
    assert entry["content"] is None
    assert entry["unstaged_patch"] is None
    json.dumps(body, ensure_ascii=False)
    assert "\\udcff" in entry["path"]


def test_large_file_is_classified_before_patch_capture(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo")
    large = repo / "large.txt"
    large.write_text("x" * 128, encoding="utf-8")
    service = GitDiffService(repo, "session-1", max_file_bytes=16)
    service.ensure_baseline()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("large file must not invoke git diff")

    monkeypatch.setattr(service, "_patch", fail_if_called)
    body = service.snapshot().to_dict()
    entry = body["entries"][0]  # type: ignore[index]
    assert entry["too_large"] is True
    assert entry["unstaged_patch"] is None


def test_large_index_blob_is_classified_before_unstaged_patch(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("small\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1", max_file_bytes=16)
    service.ensure_baseline()

    tracked.write_text("x" * 128, encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    tracked.write_text("small again\n", encoding="utf-8")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("large index blob must not invoke git diff")

    monkeypatch.setattr(service, "_patch", fail_if_called)
    entry = service.snapshot().to_dict()["entries"][0]  # type: ignore[index]
    assert entry["too_large"] is True
    assert entry["unstaged_patch"] is None


def test_leading_dash_filename_has_a_unified_patch(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    leading_dash = repo / "-file.txt"
    leading_dash.write_text("content\n", encoding="utf-8")

    entry = GitDiffService(repo, "session-1").snapshot().to_dict()["entries"][0]  # type: ignore[index]
    assert entry["path"] == "-file.txt"
    assert "+content" in entry["unstaged_patch"]


def test_git_unavailable_and_timeout_are_stable(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)
    service = GitDiffService(repo, "session-1")
    assert service.snapshot().to_dict()["is_git"] is False

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(subprocess, "run", timed_out)
    assert GitDiffService(repo, "session-2").snapshot().to_dict()["is_git"] is False


def test_git_becoming_unavailable_does_not_report_every_baseline_file_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _commit_all(repo)
    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)
    body = GitDiffService(repo, "session-1").snapshot().to_dict()
    assert body["is_git"] is False
    assert body["entries"] == []


def test_baseline_payload_atomically_contains_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("pre-existing\n", encoding="utf-8")

    service = GitDiffService(repo, "session-1")
    service.ensure_baseline()
    baseline_path = repo / ".nano-vibe" / "gui" / "session-1" / "diff-baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["version"] >= 2
    assert payload["contents"]["tracked.txt"] == "pre-existing\n"
    assert not baseline_path.with_name("diff-baseline-content.json").exists()


def test_incomplete_baseline_payload_is_not_silently_reused(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("pre-existing\n", encoding="utf-8")

    first = GitDiffService(repo, "session-1")
    baseline = first.ensure_baseline()
    baseline_path = repo / ".nano-vibe" / "gui" / "session-1" / "diff-baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["contents"] = {}
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    second = GitDiffService(repo, "session-1")
    assert second.ensure_baseline().captured_at != baseline.captured_at
