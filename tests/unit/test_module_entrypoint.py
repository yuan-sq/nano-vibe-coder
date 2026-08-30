import os
import subprocess
import sys


def test_module_entrypoint_exposes_cli_help() -> None:
    env = {**os.environ, "PYTHONPATH": "src"}
    result = subprocess.run(
        [sys.executable, "-m", "nano_vibe", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "coding-agent session" in result.stdout
