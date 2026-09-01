from pathlib import Path
from subprocess import CompletedProcess

import pytest

from nano_vibe.gui import project_picker


def test_choose_directory_returns_selected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_picker.sys, "platform", "darwin")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, "/Users/me/repo\n", "")

    monkeypatch.setattr(project_picker.subprocess, "run", fake_run)

    assert project_picker.choose_directory() == Path("/Users/me/repo")
    assert calls[0][0][0] == "osascript"
    assert "choose folder" in calls[0][0][-1]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True


def test_choose_directory_reports_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_picker.sys, "platform", "darwin")
    monkeypatch.setattr(
        project_picker.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "", "User canceled."),
    )

    with pytest.raises(project_picker.ProjectPickerCancelled):
        project_picker.choose_directory()


def test_choose_directory_is_macos_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_picker.sys, "platform", "linux")

    with pytest.raises(project_picker.ProjectPickerUnavailable):
        project_picker.choose_directory()
