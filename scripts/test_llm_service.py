"""Check whether the active model in a local nano-vibe config is reachable."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from nano_vibe.config import AppConfig, ConfigError, load_config
from nano_vibe.models.base import Model, ModelResponse
from nano_vibe.models.openai_compat import OpenAICompatibleModel

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
EXIT_OK = 0
EXIT_SERVICE_ERROR = 1
EXIT_CONFIG_ERROR = 2
REQUEST_TIMEOUT_SECONDS = 30.0
TEST_PROMPT = "请连接模型服务并只回复 OK。"


class ServiceCheckError(RuntimeError):
    """Raised when the configured model cannot complete the test request."""


def create_model(config: AppConfig) -> OpenAICompatibleModel:
    """Create one request client for the configured active model."""

    return OpenAICompatibleModel(config.active_model, retries=1)


async def check_service(
    config: AppConfig,
    model: Model | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> ModelResponse:
    """Send the minimal test request and return a non-empty model response."""

    try:
        selected_model = model or create_model(config)
        response = await asyncio.wait_for(
            selected_model.complete(
                [{"role": "user", "content": TEST_PROMPT}],
                [],
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise ServiceCheckError(
            f"模型请求超过 {timeout_seconds:g} 秒未完成"
        ) from exc
    except Exception as exc:
        raise ServiceCheckError(str(exc) or exc.__class__.__name__) from exc

    if not response.content or not response.content.strip():
        raise ServiceCheckError("模型返回了空响应")
    return response


def _safe_service_url(value: str) -> str:
    """Return URL location data without credentials, query strings, or fragments."""

    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname:
        return "<invalid-url>"
    try:
        host = parts.hostname
        if parts.port is not None:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "<invalid-url>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{host}{path}"


def _redact(value: str, config: AppConfig) -> str:
    redacted = value
    for model_config in config.models.values():
        if model_config.api_key:
            redacted = redacted.replace(model_config.api_key, "[REDACTED]")
    return redacted.replace("\n", " ").strip()


def _response_summary(response: ModelResponse, config: AppConfig) -> str:
    summary = _redact(" ".join(response.content.split()), config)
    if len(summary) <= 300:
        return summary
    return f"{summary[:297]}..."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测试 nano-vibe 配置中的 active_model 是否可用。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"TOML 配置路径（默认：{DEFAULT_CONFIG_PATH}）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = args.config.expanduser().resolve()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    service_url = _safe_service_url(config.active_model.url)
    print(f"测试 LLM 服务：{service_url}（模型：{config.active_model.model_name}）")
    started_at = time.monotonic()
    try:
        response = asyncio.run(check_service(config))
    except ServiceCheckError as exc:
        elapsed = time.monotonic() - started_at
        print(
            f"服务错误（{elapsed:.1f}s）：{_redact(str(exc), config)}",
            file=sys.stderr,
        )
        return EXIT_SERVICE_ERROR

    elapsed = time.monotonic() - started_at
    print(f"PASS（{elapsed:.1f}s）：{_response_summary(response, config)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
