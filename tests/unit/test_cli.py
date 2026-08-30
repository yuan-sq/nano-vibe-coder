
from typer.testing import CliRunner

from nano_vibe.cli import app


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
