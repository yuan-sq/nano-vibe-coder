import json
import subprocess
from pathlib import Path

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
