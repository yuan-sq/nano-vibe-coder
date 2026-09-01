
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from nano_vibe.cli import app
from nano_vibe.session_store import SessionSnapshot, SessionStore


def test_cli_help_exposes_v2_session_and_permission_options() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--resume" in result.stdout
    assert "--full-access" in result.stdout


def test_cli_repl_command_names_are_documented() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    # Keep the slash commands discoverable without starting a configured model.
    assert "/plan" in result.stdout or "REPL" in result.stdout


def test_cli_full_access_resume_explicitly_overrides_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
active_model = "default"
[models.default]
name = "default"
url = "http://example.test/v1"
model_name = "demo"
""",
        encoding="utf-8",
    )
    store = SessionStore(tmp_path / ".nano-vibe" / "sessions")
    store.save(
        SessionSnapshot(
            session_id="session-1",
            workspace=str(tmp_path.resolve()),
            permission_mode="normal",
        )
    )
    captured: dict[str, object] = {}

    async def fake_run_repl(session: object, _ui: object) -> None:
        captured["session"] = session

    monkeypatch.setattr("nano_vibe.cli._run_repl", fake_run_repl)
    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "--config",
            str(config_path),
            "--resume",
            "session-1",
            "--full-access",
        ],
    )

    assert result.exit_code == 0, result.stdout
    session = cast(Any, captured["session"])
    assert session.permission_mode == "full-access"
