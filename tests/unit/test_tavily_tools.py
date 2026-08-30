from pathlib import Path
from typing import Any

import pytest

from nano_vibe.tools.web_extract import WebExtractTool
from nano_vibe.tools.web_search import WebSearchTool


class FakeTavilyClient:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.extract_calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.search_calls.append(kwargs)
        return {"results": [{"title": "Result", "url": "https://example.test"}]}

    async def extract(self, **kwargs: Any) -> dict[str, Any]:
        self.extract_calls.append(kwargs)
        return {
            "results": [
                {"url": url, "raw_content": "x" * 20_000} for url in kwargs["urls"]
            ]
        }


@pytest.mark.asyncio
async def test_web_search_uses_tavily_basic_depth_and_five_results(tmp_path: Path) -> None:
    client = FakeTavilyClient()
    env_file = tmp_path / ".env.test"
    env_file.write_text("TAVILY_API_KEY=from-file\n", encoding="utf-8")
    tool = WebSearchTool(client=client, env_file=env_file)

    result = await tool.execute({"query": "python"})

    assert result.ok is True
    assert client.search_calls == [
        {"query": "python", "search_depth": "basic", "max_results": 5}
    ]
    assert result.metadata["provider"] == "tavily"


@pytest.mark.asyncio
async def test_web_extract_limits_urls_and_total_output(tmp_path: Path) -> None:
    client = FakeTavilyClient()
    tool = WebExtractTool(client=client, env_file=tmp_path / ".env")
    urls = [f"https://example.test/{index}" for index in range(6)]

    too_many = await tool.execute({"urls": urls})
    limited = await tool.execute({"urls": urls[:5]})

    assert too_many.ok is False
    assert too_many.error is not None and too_many.error.code == "invalid_extract_urls"
    assert limited.ok is True
    assert len(limited.output) <= 30_000
    assert limited.metadata["truncated"] is True
    assert client.extract_calls == [{"urls": urls[:5]}]


@pytest.mark.asyncio
async def test_tavily_requires_explicit_env_file_when_client_not_injected(tmp_path: Path) -> None:
    tool = WebSearchTool(env_file=tmp_path / "missing.env")

    result = await tool.execute({"query": "python"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code in {"tavily_not_configured", "tavily_dependency_missing"}


@pytest.mark.asyncio
async def test_web_search_rejects_empty_query() -> None:
    result = await WebSearchTool(client=FakeTavilyClient()).execute({"query": " "})

    assert result.ok is False
    assert result.error is not None and result.error.code == "invalid_query"
