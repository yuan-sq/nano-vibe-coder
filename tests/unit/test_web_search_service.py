from pathlib import Path
from typing import Any

from nano_vibe.tools.base import ToolResult
from scripts.test_web_search import SearchCheckError, main


def write_config(tmp_path: Path, api_key: str = "config-key") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
active_model = "default"

[models.default]
name = "default"
url = "https://llm.example.test/v1"
model_name = "demo"

[tavily]
api_key = "{api_key}"
""",
        encoding="utf-8",
    )
    return path


def test_main_reports_configured_without_network(tmp_path: Path, capsys: Any) -> None:
    config_path = write_config(tmp_path)

    assert main(["--config", str(config_path)]) == 0

    assert "CONFIGURED" in capsys.readouterr().out


def test_main_runs_live_check_only_when_requested(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    config_path = write_config(tmp_path)
    calls: list[str] = []

    async def fake_check_service(config: Any, query: str, **_: Any) -> ToolResult:
        del config
        calls.append(query)
        return ToolResult.success('{"results": [{"title": "ok"}]}')

    monkeypatch.setattr("scripts.test_web_search.check_service", fake_check_service)

    assert main(["--config", str(config_path), "--query", "python", "--live"]) == 0
    assert calls == ["python"]
    assert "PASS" in capsys.readouterr().out


def test_main_returns_service_error_without_leaking_config_key(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    config_path = write_config(tmp_path)

    async def fake_check_service(*_: Any, **__: Any) -> ToolResult:
        raise SearchCheckError("request failed with config-key")

    monkeypatch.setattr("scripts.test_web_search.check_service", fake_check_service)

    assert main(["--config", str(config_path), "--live"]) == 1
    captured = capsys.readouterr()
    assert "config-key" not in captured.err
    assert "[REDACTED]" in captured.err


def test_main_returns_config_error_for_missing_file(tmp_path: Path, capsys: Any) -> None:
    result = main(["--config", str(tmp_path / "missing.toml")])

    assert result == 2
    assert "配置" in capsys.readouterr().err
