import os
import subprocess
from pathlib import Path

import pytest

from nano_vibe.gui.security import (
    SecretStore,
    StartupToken,
    is_allowed_origin,
    validate_project_path,
)
from nano_vibe.gui.storage import AppStorage


def test_storage_registers_projects_and_sessions(tmp_path: Path) -> None:
    storage = AppStorage(tmp_path / "app")
    project = storage.add_project(tmp_path)

    assert project.path == str(tmp_path.resolve())
    assert storage.list_projects()[0].id == project.id

    session = storage.create_session(project.id, title="第一次运行")
    assert session.title == "第一次运行"
    assert storage.list_sessions(project.id)[0].session_id == session.session_id

    updated = storage.update_session(session.session_id, title="已重命名", archived=True)
    assert updated.title == "已重命名"
    assert updated.archived is True


def test_storage_rejects_duplicate_project_and_can_remove_registry_entry(tmp_path: Path) -> None:
    storage = AppStorage(tmp_path / "app")
    first = storage.add_project(tmp_path)
    second = storage.add_project(tmp_path)
    assert second.id == first.id

    storage.remove_project(first.id)
    assert storage.list_projects() == []


def test_secret_store_writes_0600_and_exposes_only_status(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    secrets = SecretStore(env_file)
    secrets.set("OPENAI_API_KEY", "secret-value")

    assert secrets.status(["OPENAI_API_KEY", "TAVILY_API_KEY", "MISSING"]) == {
        "OPENAI_API_KEY": True,
        "TAVILY_API_KEY": False,
        "MISSING": False,
    }
    assert secrets.read_value("OPENAI_API_KEY") == "secret-value"
    assert os.stat(env_file).st_mode & 0o777 == 0o600


def test_startup_token_is_single_use() -> None:
    token = StartupToken()
    value = token.value
    assert token.exchange(value) is True
    assert token.exchange(value) is False
    assert token.exchange("wrong") is False


def test_project_path_must_be_git_repo_under_home(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    assert validate_project_path(repo, home=tmp_path) == repo.resolve()

    outside = tmp_path.parent / "outside-nano-vibe"
    outside.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="inside the user home"):
        validate_project_path(outside, home=tmp_path)


def test_origin_must_match_local_gui_origin() -> None:
    assert is_allowed_origin("http://127.0.0.1:5173", "http://127.0.0.1:5173")
    assert not is_allowed_origin("http://evil.example", "http://127.0.0.1:5173")
    assert not is_allowed_origin(None, "http://127.0.0.1:5173")
