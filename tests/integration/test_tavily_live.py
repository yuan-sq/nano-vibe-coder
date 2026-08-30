import os

import pytest

from nano_vibe.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_tavily_live_search_is_opt_in() -> None:
    if os.environ.get("NANO_VIBE_LIVE_TAVILY") != "1":
        pytest.skip("set NANO_VIBE_LIVE_TAVILY=1 to run live Tavily tests")
    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY is required for live Tavily tests")

    result = await WebSearchTool().execute({"query": "Python"})

    assert result.ok is True
