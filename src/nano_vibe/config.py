"""Application configuration loaded from a local TOML file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigError(ValueError):
    """Raised when the application configuration is missing or invalid."""


@dataclass(frozen=True)
class ModelConfig:
    name: str
    url: str
    model_name: str
    reasoning_level: str = "medium"
    description: str = ""
    context_window: int = 128_000
    api_key: str = field(default="", repr=False)


@dataclass(frozen=True)
class RuntimeConfig:
    max_model_turns: int = 100
    max_consecutive_tool_errors: int = 5
    api_retries: int = 5
    shell_timeout_seconds: int = 300
    shell_max_output_chars: int = 50_000
    compact_ratio: float = 0.75
    compact_target_ratio: float = 0.50


@dataclass(frozen=True)
class AppConfig:
    active_model: ModelConfig
    models: Mapping[str, ModelConfig]
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)


def _required_string(values: Mapping[str, Any], key: str, section: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value


def _positive_int(values: Mapping[str, Any], key: str, default: int, section: str) -> int:
    value = values.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{section}.{key} must be a positive integer")
    return value


def _model_from_values(name: str, values: Mapping[str, Any]) -> ModelConfig:
    section = f"models.{name}"
    api_key = values.get("api_key", "")
    if not isinstance(api_key, str):
        raise ConfigError(f"{section}.api_key must be a string")

    reasoning_level = values.get("reasoning_level", "medium")
    description = values.get("description", "")
    if not isinstance(reasoning_level, str) or not reasoning_level.strip():
        raise ConfigError(f"{section}.reasoning_level must be a non-empty string")
    if not isinstance(description, str):
        raise ConfigError(f"{section}.description must be a string")

    context_window = _positive_int(values, "context_window", 128_000, section)
    return ModelConfig(
        name=_required_string(values, "name", section),
        url=_required_string(values, "url", section),
        model_name=_required_string(values, "model_name", section),
        reasoning_level=reasoning_level,
        description=description,
        context_window=context_window,
        api_key=api_key,
    )


def _runtime_from_values(values: Mapping[str, Any]) -> RuntimeConfig:
    max_model_turns = _positive_int(values, "max_model_turns", 100, "runtime")
    max_tool_errors = _positive_int(
        values, "max_consecutive_tool_errors", 5, "runtime"
    )
    api_retries = _positive_int(values, "api_retries", 5, "runtime")
    shell_timeout = _positive_int(values, "shell_timeout_seconds", 300, "runtime")
    shell_output = _positive_int(values, "shell_max_output_chars", 50_000, "runtime")

    compact_ratio = values.get("compact_ratio", 0.75)
    compact_target_ratio = values.get("compact_target_ratio", 0.50)
    if not isinstance(compact_ratio, (int, float)) or not 0 < compact_ratio < 1:
        raise ConfigError("runtime.compact_ratio must be between 0 and 1")
    if not isinstance(compact_target_ratio, (int, float)) or not 0 < compact_target_ratio < 1:
        raise ConfigError("runtime.compact_target_ratio must be between 0 and 1")
    if compact_target_ratio >= compact_ratio:
        raise ConfigError("runtime.compact_target_ratio must be smaller than compact_ratio")

    return RuntimeConfig(
        max_model_turns=max_model_turns,
        max_consecutive_tool_errors=max_tool_errors,
        api_retries=api_retries,
        shell_timeout_seconds=shell_timeout,
        shell_max_output_chars=shell_output,
        compact_ratio=float(compact_ratio),
        compact_target_ratio=float(compact_target_ratio),
    )


def load_config(path: str | Path) -> AppConfig:
    """Load and validate an application TOML configuration."""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"configuration file not found: {config_path}")
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"could not read configuration: {exc}") from exc

    active_name = raw.get("active_model")
    if not isinstance(active_name, str) or not active_name.strip():
        raise ConfigError("active_model must be a non-empty string")
    raw_models = raw.get("models")
    if not isinstance(raw_models, Mapping) or not raw_models:
        raise ConfigError("models must contain at least one model")

    models: dict[str, ModelConfig] = {}
    for name, values in raw_models.items():
        if not isinstance(name, str) or not isinstance(values, Mapping):
            raise ConfigError("each models entry must be a table")
        models[name] = _model_from_values(name, values)
    if active_name not in models:
        raise ConfigError(f"active_model '{active_name}' is not defined in models")

    raw_runtime = raw.get("runtime", {})
    if not isinstance(raw_runtime, Mapping):
        raise ConfigError("runtime must be a table")
    return AppConfig(
        active_model=models[active_name],
        models=models,
        runtime=_runtime_from_values(raw_runtime),
    )
