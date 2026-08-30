"""Tavily Extract tool with bounded URL count and output size."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

from .base import Tool, ToolResult
from .web_search import _TavilyTool

MAX_URLS = 5
MAX_OUTPUT_CHARS = 30_000


class WebExtractTool(Tool):
    name = "web_extract"
    description = "Extract content from up to five URLs with a 30000-character output limit."
    permission_scope = "network"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "urls": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["urls"],
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
        urls = arguments.get("urls")
        if not isinstance(urls, list) or not urls or len(urls) > MAX_URLS:
            return ToolResult.failure(
                "urls must contain between 1 and 5 URLs",
                code="invalid_extract_urls",
                details={"max_urls": MAX_URLS},
            )
        if not all(isinstance(url, str) and _is_http_url(url) for url in urls):
            return ToolResult.failure(
                "urls must contain only http(s) URLs", code="invalid_extract_urls"
            )
        client, error = self._tavily._client_or_error()
        if error is not None:
            return error
        assert client is not None
        try:
            data = await client.extract(urls=urls)
        except Exception as exc:  # noqa: BLE001 - normalize provider failures
            return ToolResult.failure(
                str(exc) or exc.__class__.__name__,
                code="tavily_extract_failed",
                details={"operation": "extract"},
                retryable=True,
            )
        output, truncated = _bounded_json(data)
        return ToolResult.success(
            output,
            provider="tavily",
            source_count=len(urls),
            truncated=truncated,
            max_chars=MAX_OUTPUT_CHARS,
        )


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _bounded_json(data: Any) -> tuple[str, bool]:
    """Serialize extraction data without splitting JSON or exceeding the cap."""

    if isinstance(data, dict):
        source_results = data.get("results", [])
        failed = data.get("failed_results", [])
    elif isinstance(data, list):
        source_results, failed = data, []
    else:
        source_results, failed = [], []
    results = source_results if isinstance(source_results, list) else []
    payload: dict[str, Any] = {"results": [], "failed_results": failed}
    truncated = False
    for item in results:
        if not isinstance(item, dict):
            item = {"content": str(item)}
        candidate = dict(item)
        content_key = "raw_content" if "raw_content" in candidate else "content"
        raw_content = candidate.get(content_key, "")
        if raw_content is not None and not isinstance(raw_content, str):
            raw_content = str(raw_content)
        candidate[content_key] = raw_content or ""
        payload["results"].append(candidate)
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) > MAX_OUTPUT_CHARS:
            overflow = len(encoded) - MAX_OUTPUT_CHARS
            current = candidate[content_key]
            keep = max(0, len(current) - overflow)
            candidate[content_key] = current[:keep]
            truncated = True
            encoded = json.dumps(payload, ensure_ascii=False, default=str)
            if len(encoded) > MAX_OUTPUT_CHARS:
                payload["results"].pop()
                break
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) > MAX_OUTPUT_CHARS:
        # Provider metadata can itself be unexpectedly large. Keep source URLs
        # and a valid bounded response rather than returning invalid JSON.
        compact_results = []
        for item in payload["results"]:
            if isinstance(item, dict) and "url" in item:
                compact_results.append({"url": str(item["url"])})
        payload = {"results": compact_results, "failed_results": [], "truncated": True}
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        truncated = True
    if len(encoded) > MAX_OUTPUT_CHARS:
        encoded = json.dumps({"results": [], "truncated": True})
        truncated = True
    return encoded, truncated


TavilyExtractTool = WebExtractTool
