"""Test fetch fallback chain.

Tests the collector's fetch fallback chain:
1. Jina Reader
2. Firecrawl
3. Direct HTTP fetch
4. Playwright

Usage:
    python scripts/test_fetch_fallback.py
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load .env
from dotenv import load_dotenv
load_dotenv()

from src.agents.collector.tools import jina_reader, firecrawl_fetch, direct_http_fetch, playwright_fetch


async def test_url(url: str):
    """Test all fetch methods for a URL."""
    print(f"\n{'='*60}")
    print(f"Testing: {url}")
    print('='*60)

    # Test Jina Reader
    print("\n[1] Testing Jina Reader...")
    result = await jina_reader(url, timeout=15.0, max_retries=1)
    if result.success:
        print(f"  SUCCESS: {len(result.content)} chars, title: {result.title[:50]}")
    else:
        print(f"  FAILED: {result.error}")

    # Test Firecrawl
    print("\n[2] Testing Firecrawl...")
    result = await firecrawl_fetch(url, timeout=30.0)
    if result.success:
        print(f"  SUCCESS: {len(result.content)} chars, title: {result.title[:50]}")
    else:
        print(f"  FAILED: {result.error}")

    # Test Direct HTTP
    print("\n[3] Testing Direct HTTP fetch...")
    result = await direct_http_fetch(url, timeout=15.0)
    if result.success:
        print(f"  SUCCESS: {len(result.content)} chars, title: {result.title[:50]}")
    else:
        print(f"  FAILED: {result.error}")

    # Test Playwright
    print("\n[4] Testing Playwright...")
    result = await playwright_fetch(url, timeout=15000)
    if result.success:
        print(f"  SUCCESS: {len(result.content)} chars, title: {result.title[:50]}")
    else:
        print(f"  FAILED: {result.error}")


async def main():
    test_urls = [
        "https://www.baidu.com",
        "https://finance.sina.com.cn/wm/2026-04-28/doc-inhvyzkp1843557.shtml",
        "https://www.163.com/dy/article/K583D5QK0511D2LM.html",
    ]

    for url in test_urls:
        await test_url(url)


if __name__ == "__main__":
    asyncio.run(main())
