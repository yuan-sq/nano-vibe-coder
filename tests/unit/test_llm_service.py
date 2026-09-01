from pathlib import Path
from typing import Any

from nano_vibe.models.base import ModelResponse
from scripts.test_llm_service import main


def write_config(path: Path, api_key: str = "secret-key") -> None:
    path.write_text(
        """
active_model = "default"

[models.default]
name = "default"
url = "https://llm.example.test/v1"
model_name = "demo"
api_key = "__API_KEY__"
""".replace("__API_KEY__", api_key),
        encoding="utf-8",
    )


def test_main_reports_pass_for_a_non_empty_model_response(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    class FakeModel:
        async def complete(self, messages: Any, tools: Any) -> ModelResponse:
            assert messages[-1]["content"]
            assert tools == []
            return ModelResponse(content="OK")

    monkeypatch.setattr("scripts.test_llm_service.create_model", lambda config: FakeModel())

    assert main(["--config", str(config_path)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_main_returns_config_error_for_missing_file(tmp_path: Path, capsys: Any) -> None:
    result = main(["--config", str(tmp_path / "missing.toml")])

    captured = capsys.readouterr()
    assert result == 2
    assert "配置" in captured.err


def test_main_redacts_api_key_when_service_fails(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    class FailingModel:
        async def complete(self, messages: Any, tools: Any) -> ModelResponse:
            raise RuntimeError("request failed with secret-key")

    monkeypatch.setattr("scripts.test_llm_service.create_model", lambda config: FailingModel())

    assert main(["--config", str(config_path)]) == 1
    captured = capsys.readouterr()
    assert "服务" in captured.err
    assert "secret-key" not in captured.err
    assert "[REDACTED]" in captured.err
