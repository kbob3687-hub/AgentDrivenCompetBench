"""Tests for fan-out sub-agent pattern (parallel URL fetching)."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from agents.collector.tools import FetchResult


class TestFanOutSubAgent:
    """Test the parallel URL fetching pattern used in the SSE runner."""

    @pytest.fixture
    def collector(self):
        with patch("agents.base.Langfuse"), \
             patch("agents.base.anthropic.AsyncAnthropic"), \
             patch("agents.base.AsyncOpenAI"):
            from agents.collector.agent import CollectorAgent
            return CollectorAgent()

    def test_get_default_urls_notion(self, collector):
        urls = collector._get_default_urls("Notion", ["pricing", "features"])
        assert len(urls) >= 2
        assert any("pricing" in u for u in urls)
        assert any("product" in u for u in urls)

    def test_get_default_urls_unknown_competitor(self, collector):
        urls = collector._get_default_urls("UnknownProduct", ["pricing"])
        assert len(urls) >= 1
        assert "s.jina.ai" in urls[0]

    def test_truncate_content_short(self, collector):
        content = "Short content"
        assert collector._truncate_content(content) == content

    def test_truncate_content_long(self, collector):
        content = "x" * 20000
        truncated = collector._truncate_content(content, max_chars=12000)
        assert len(truncated) < 20000
        assert "省略" in truncated

    def test_parse_llm_output_valid_json(self, collector):
        result = collector._parse_llm_output('{"collected_items": []}')
        assert result == {"collected_items": []}

    def test_parse_llm_output_code_block(self, collector):
        text = 'Some text\n```json\n{"collected_items": [{"claim": "test"}]}\n```\nMore text'
        result = collector._parse_llm_output(text)
        assert result is not None
        assert "collected_items" in result

    def test_parse_llm_output_brace_extraction(self, collector):
        text = 'Here is the result: {"collected_items": []} and some trailing text'
        result = collector._parse_llm_output(text)
        assert result is not None

    def test_parse_llm_output_invalid(self, collector):
        result = collector._parse_llm_output("no json here at all")
        assert result is None

    @pytest.mark.asyncio
    async def test_fan_out_parallel_execution(self):
        """Verify that multiple URLs are fetched concurrently with semaphore."""
        fetch_count = 0
        fetch_order = []

        async def mock_fetch(url: str) -> FetchResult:
            nonlocal fetch_count
            fetch_count += 1
            fetch_order.append(url)
            await asyncio.sleep(0.01)
            return FetchResult(
                url=url,
                success=True,
                content=f"Content from {url}",
                title=f"Title for {url}",
                snapshot_hash="hash123",
            )

        urls = [f"https://example.com/page{i}" for i in range(6)]
        semaphore = asyncio.Semaphore(4)
        results = []

        async def process_url(url: str):
            async with semaphore:
                return await mock_fetch(url)

        tasks = [process_url(url) for url in urls]
        results = await asyncio.gather(*tasks)

        assert len(results) == 6
        assert all(r.success for r in results)
        assert fetch_count == 6

    @pytest.mark.asyncio
    async def test_fan_out_handles_failures_gracefully(self):
        """Verify that one URL failure doesn't crash the entire fan-out."""
        call_count = 0

        async def mock_fetch(url: str) -> FetchResult:
            nonlocal call_count
            call_count += 1
            if "fail" in url:
                return FetchResult(
                    url=url,
                    success=False,
                    content="",
                    title="",
                    snapshot_hash="",
                    error="Connection timeout",
                )
            return FetchResult(
                url=url,
                success=True,
                content="Valid content",
                title="Valid Page",
                snapshot_hash="hash456",
            )

        urls = [
            "https://example.com/good1",
            "https://example.com/fail",
            "https://example.com/good2",
        ]

        semaphore = asyncio.Semaphore(4)
        successes = []
        failures = []

        async def process_url(url: str):
            async with semaphore:
                result = await mock_fetch(url)
                if result.success:
                    successes.append(url)
                else:
                    failures.append(url)
                return result

        tasks = [process_url(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=True)

        assert len(successes) == 2
        assert len(failures) == 1
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Verify semaphore actually limits concurrent executions."""
        max_concurrent = 0
        current_concurrent = 0

        async def mock_fetch(url: str):
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return FetchResult(
                url=url, success=True, content="ok", title="ok", snapshot_hash="h"
            )

        urls = [f"https://example.com/{i}" for i in range(8)]
        semaphore = asyncio.Semaphore(4)

        async def process_url(url: str):
            async with semaphore:
                return await mock_fetch(url)

        tasks = [process_url(url) for url in urls]
        await asyncio.gather(*tasks)

        assert max_concurrent <= 4
