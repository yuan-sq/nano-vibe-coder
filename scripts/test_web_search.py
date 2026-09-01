"""Check whether the configured Tavily web search is available."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from nano_vibe.config import AppConfig, ConfigError, load_config
from nano_vibe.tools.base import ToolResult
from nano_vibe.tools.web_search import WebSearchTool, load_env_file

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
EXIT_OK = 0
EXIT_SERVICE_ERROR = 1
EXIT_CONFIG_ERROR = 2
REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_QUERY = "nano-vibe"


class SearchCheckError(RuntimeError):
    """Raised when the configured Tavily service cannot complete a check."""


def create_tool(config: AppConfig, workspace: Path) -> WebSearchTool:
    """Create a Tavily tool using the selected configuration and workspace."""

    return WebSearchTool(
        api_key=config.tavily.api_key or None,
        env_file=config.tavily.env_file,
        workspace=workspace,
    )


def _redact(value: str, config: AppConfig, workspace: Path) -> str:
    """Remove configured Tavily secrets from text before it reaches the terminal."""

    secrets = [config.tavily.api_key, os.environ.get("TAVILY_API_KEY", "")]
    env_path = Path(config.tavily.env_file).expanduser()
    if not env_path.is_absolute():
        env_path = workspace / env_path
    secrets.append(load_env_file(env_path).get("TAVILY_API_KEY", ""))
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted.replace("\n", " ").strip()


def _configuration_error(config: AppConfig, workspace: Path) -> str | None:
    """Return a safe local configuration error, or None when the SDK is ready."""

    tool = create_tool(config, workspace)
    _client, error = tool._tavily._client_or_error()
    if error is None:
        return None
    return error.output


async def check_service(
    config: AppConfig,
    query: str,
    *,
    workspace: Path | None = None,
    tool: WebSearchTool | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> ToolResult:
    """Send one real Tavily search request and return its structured result."""

    selected_workspace = workspace or Path.cwd()
    selected_tool = tool or create_tool(config, selected_workspace)
    try:
        result = await asyncio.wait_for(
            selected_tool.execute({"query": query}), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        raise SearchCheckError(f"Tavily 请求超过 {timeout_seconds:g} 秒未完成") from exc
    except Exception as exc:
        raise SearchCheckError(str(exc) or exc.__class__.__name__) from exc
    if not result.ok:
        raise SearchCheckError(result.output)
    return result


def _result_count(result: ToolResult) -> int | None:
    try:
        payload = result.output
        if not isinstance(payload, str):
            return None
        import json

        decoded = json.loads(payload)
    except (ValueError, TypeError):
        return None
    results = decoded.get("results") if isinstance(decoded, dict) else None
    return len(results) if isinstance(results, list) else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查 nano-vibe 配置中的 Tavily web_search 是否可用。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"TOML 配置路径（默认：{DEFAULT_CONFIG_PATH}）",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"真实检查使用的查询词（默认：{DEFAULT_QUERY}）",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="发起一次真实 Tavily 网络请求；不指定时只检查本地配置和 SDK",
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

    workspace = config_path.parent
    local_error = _configuration_error(config, workspace)
    if local_error is not None:
        print(f"配置错误：{_redact(local_error, config, workspace)}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if not args.live:
        print(f"CONFIGURED：Tavily SDK 和密钥配置有效（配置：{config_path}）")
        print("提示：加上 --live 才会发起真实搜索请求。")
        return EXIT_OK

    try:
        result = asyncio.run(
            check_service(config, args.query, workspace=workspace)
        )
    except SearchCheckError as exc:
        print(
            f"服务错误：{_redact(str(exc), config, workspace)}",
            file=sys.stderr,
        )
        return EXIT_SERVICE_ERROR
    count = _result_count(result)
    suffix = f"（{count} 条结果）" if count is not None else ""
    print(f"PASS：Tavily 搜索成功{suffix}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
