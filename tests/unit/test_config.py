from pathlib import Path

import pytest

from nano_vibe.config import ConfigError, load_config


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_selects_active_model_and_runtime_defaults(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        active_model = "local"

        [models.local]
        name = "local"
        url = "https://example.test/v1"
        api_key = "test-key"
        model_name = "demo-model"
        reasoning_level = "medium"
        description = "test model"
        context_window = 128000
        """,
    )

    config = load_config(path)

    assert config.active_model.name == "local"
    assert config.active_model.url == "https://example.test/v1"
    assert config.active_model.model_name == "demo-model"
    assert config.runtime.max_model_turns == 100
    assert config.runtime.max_consecutive_tool_errors == 5
    assert config.runtime.api_retries == 5


def test_load_config_rejects_unknown_active_model(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        active_model = "missing"

        [models.local]
        name = "local"
        url = "https://example.test/v1"
        api_key = "test-key"
        model_name = "demo-model"
        reasoning_level = "medium"
        description = "test model"
        context_window = 128000
        """,
    )

    with pytest.raises(ConfigError, match="active_model"):
        load_config(path)
