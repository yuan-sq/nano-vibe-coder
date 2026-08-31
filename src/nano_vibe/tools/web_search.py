"""Tavily-backed web search tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult

try:  # Keep offline installation and unit tests independent of the extra SDK.
    from tavily import AsyncTavilyClient
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    AsyncTavilyClient = None  # type: ignore[assignment,misc]


def load_env_file(path: str | Path | None) -> dict[str, str]:
    """Read only the explicitly selected dotenv file.

    We intentionally do not search parent directories or implicitly load a
    project-wide ``.env``.  The caller chooses the exact file via config.
    """

    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


class _TavilyTool(Tool):
    def __init__(
        self,
        *,
        client: Any | None = None,
        env_file: str | Path = ".env",
        workspace: str | Path | None = None,
        api_key: str | None = None,
    ) -> None:
        self.client = client
        env_path = Path(env_file).expanduser()
        if workspace is not None and not env_path.is_absolute():
            env_path = Path(workspace).resolve() / env_path
        self.env_file = env_path
        self.api_key = api_key

    def _client_or_error(self) -> tuple[Any | None, ToolResult | None]:
        if self.client is not None:
            return self.client, None
        file_values = load_env_file(self.env_file)
        key = self.api_key or os.environ.get("TAVILY_API_KEY") or file_values.get("TAVILY_API_KEY")
        if not key:
            return None, ToolResult.failure(
                f"Tavily web search is not configured: set TAVILY_API_KEY in {self.env_file} or in the process environment",
                code="tavily_not_configured",
                details={"env_file": str(self.env_file)},
            )
        if AsyncTavilyClient is None:
            return None, ToolResult.failure(
                "Tavily SDK is not installed",
                code="tavily_dependency_missing",
                retryable=False,
            )
        return AsyncTavilyClient(api_key=key), None


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web with Tavily using basic search and at most five results."
    permission_scope = "network"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        client: Any | None = None,
        env_file: str | Path = ".env",
        workspace: str | Path | None = None,
        api_key: str | None = None,
    ) -> None:
        self._tavily = _TavilyTool(
            client=client,
            env_file=env_file,
            workspace=workspace,
            api_key=api_key,
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.failure("query must be a non-empty string", code="invalid_query")
        client, error = self._tavily._client_or_error()
        if error is not None:
            return error
        assert client is not None
        try:
            data = await client.search(query=query, search_depth="basic", max_results=5)
        except Exception as exc:  # noqa: BLE001 - normalize provider failures
            return ToolResult.failure(
                str(exc) or exc.__class__.__name__,
                code="tavily_search_failed",
                details={"operation": "search"},
                retryable=True,
            )
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = {**data, "results": data["results"][:5]}
        output = json.dumps(data, ensure_ascii=False, default=str)
        return ToolResult.success(output, provider="tavily", search_depth="basic", max_results=5)
