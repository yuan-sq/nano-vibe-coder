"""Native project-directory selection for the local macOS GUI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class ProjectPickerCancelled(RuntimeError):
    """The user dismissed the native folder picker."""


class ProjectPickerUnavailable(RuntimeError):
    """The native folder picker could not be used."""


def choose_directory() -> Path:
    """Open the macOS folder picker and return the selected absolute path."""

    if sys.platform != "darwin":
        raise ProjectPickerUnavailable("macOS folder picker is unavailable")
    try:
        completed = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "选择项目目录")',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProjectPickerUnavailable("osascript is unavailable") from exc
    if completed.returncode != 0:
        if "cancel" in completed.stderr.lower() or "-128" in completed.stderr:
            raise ProjectPickerCancelled("project selection cancelled")
        raise ProjectPickerUnavailable("macOS folder picker failed")
    selected = completed.stdout.strip()
    if not selected:
        raise ProjectPickerUnavailable("macOS folder picker returned no directory")
    return Path(selected).expanduser().resolve()
