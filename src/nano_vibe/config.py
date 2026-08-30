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
    permission_mode: str = "normal"
    session_dir: str = ".nano-vibe/sessions"


@dataclass(frozen=True)
class AppConfig:
    active_model: ModelConfig
    models: Mapping[str, ModelConfig]
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    state_models: Mapping[str, ModelConfig] = field(default_factory=dict)
    fallback_models: tuple[str, ...] = ()
    tavily: "TavilyConfig" = field(default_factory=lambda: TavilyConfig())


@dataclass(frozen=True)
class TavilyConfig:
    """Settings for the optional Tavily Search/Extract integration."""

    env_file: str = ".env"
    search_depth: str = "basic"
    max_results: int = 5
    max_extract_urls: int = 5
    max_extract_chars: int = 30_000


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

    permission_mode = values.get("permission_mode", "normal")
    if permission_mode not in {"normal", "full-access"}:
        raise ConfigError("runtime.permission_mode must be 'normal' or 'full-access'")
    session_dir = values.get("session_dir", ".nano-vibe/sessions")
    if not isinstance(session_dir, str) or not session_dir.strip():
        raise ConfigError("runtime.session_dir must be a non-empty string")

    return RuntimeConfig(
        max_model_turns=max_model_turns,
        max_consecutive_tool_errors=max_tool_errors,
        api_retries=api_retries,
        shell_timeout_seconds=shell_timeout,
        shell_max_output_chars=shell_output,
        compact_ratio=float(compact_ratio),
        compact_target_ratio=float(compact_target_ratio),
        permission_mode=permission_mode,
        session_dir=session_dir,
    )


def _string_list(value: Any, key: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ConfigError(f"{key} must be a list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ConfigError(f"{key} must be a list of strings")
    return tuple(value)


def _tavily_from_values(values: Mapping[str, Any]) -> TavilyConfig:
    env_file = values.get("env_file", ".env")
    if not isinstance(env_file, str) or not env_file.strip():
        raise ConfigError("tavily.env_file must be a non-empty string")
    search_depth = values.get("search_depth", "basic")
    if search_depth not in {"basic", "advanced"}:
        raise ConfigError("tavily.search_depth must be 'basic' or 'advanced'")
    max_results = _positive_int(values, "max_results", 5, "tavily")
    max_extract_urls = _positive_int(values, "max_extract_urls", 5, "tavily")
    max_extract_chars = _positive_int(values, "max_extract_chars", 30_000, "tavily")
    return TavilyConfig(
        env_file=env_file,
        search_depth=search_depth,
        max_results=max_results,
        max_extract_urls=max_extract_urls,
        max_extract_chars=max_extract_chars,
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
    raw_routing = raw.get("routing", {})
    if raw_routing is None:
        raw_routing = {}
    if not isinstance(raw_routing, Mapping):
        raise ConfigError("routing must be a table")
    raw_state_models = raw.get("state_models", {})
    if raw_state_models is None:
        raw_state_models = {}
    if not isinstance(raw_state_models, Mapping):
        raise ConfigError("state_models must be a table")
    nested_states = raw_routing.get("states", {})
    if nested_states is None:
        nested_states = {}
    if not isinstance(nested_states, Mapping):
        raise ConfigError("routing.states must be a table")
    state_names: dict[str, Any] = {}
    state_names.update(dict(raw_state_models))
    state_names.update(dict(nested_states))
    for name, value in raw_routing.items():
        if str(name).upper() in {"REQUIREMENTS", "PLAN", "IMPLEMENT", "VERIFY", "DONE"}:
            state_names[str(name).upper()] = value
    state_models: dict[str, ModelConfig] = {}
    for state, model_name in state_names.items():
        if not isinstance(state, str) or not isinstance(model_name, str):
            raise ConfigError("state model routes must map state names to model names")
        if model_name not in models:
            raise ConfigError(f"state model '{model_name}' is not defined in models")
        state_models[state.upper()] = models[model_name]

    fallback_value = raw.get("fallback_models", raw_routing.get("fallback", []))
    fallback_models = _string_list(fallback_value, "fallback_models")
    for model_name in fallback_models:
        if model_name not in models:
            raise ConfigError(f"fallback model '{model_name}' is not defined in models")

    raw_tavily = raw.get("tavily", {})
    if not isinstance(raw_tavily, Mapping):
        raise ConfigError("tavily must be a table")
    return AppConfig(
        active_model=models[active_name],
        models=models,
        runtime=_runtime_from_values(raw_runtime),
        state_models=state_models,
        fallback_models=fallback_models,
        tavily=_tavily_from_values(raw_tavily),
    )
