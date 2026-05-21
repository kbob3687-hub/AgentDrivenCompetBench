"""CollectorAgent采集工具 - Jina Reader + Playwright"""

from __future__ import annotations

import hashlib
from datetime import datetime

import httpx
from pydantic import BaseModel, Field


class FetchResult(BaseModel):
    """采集结果"""

    url: str
    title: str = ""
    content: str = ""
    accessed_at: datetime = Field(default_factory=datetime.now)
    snapshot_hash: str = ""
    success: bool = True
    error: str | None = None


async def jina_reader(url: str, timeout: float = 60.0, max_retries: int = 3) -> FetchResult:
    """通过Jina Reader获取网页的干净文本

    Jina Reader会自动：
    - 去除广告、导航等噪音
    - 提取正文内容
    - 返回Markdown格式的干净文本

    Args:
        url: 目标网页URL
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数

    Returns:
        FetchResult包含干净文本内容
    """
    import asyncio

    jina_url = f"https://r.jina.ai/{url}"

    headers = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
    }

    last_error = ""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(jina_url, headers=headers)
                response.raise_for_status()

                content = response.text
                title = _extract_title(content)
                snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                return FetchResult(
                    url=url,
                    title=title,
                    content=content,
                    accessed_at=datetime.now(),
                    snapshot_hash=snapshot_hash,
                    success=True,
                )

        except httpx.TimeoutException:
            last_error = f"Timeout after {timeout}s"
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"

        if attempt < max_retries - 1:
            await asyncio.sleep(2 * (attempt + 1))

    return FetchResult(
        url=url,
        success=False,
        error=f"Failed after {max_retries} attempts: {last_error}",
    )


async def playwright_fetch(url: str, timeout: float = 30000) -> FetchResult:
    """通过Playwright获取需要JS渲染的页面

    适用于：SaaS定价页、动态加载内容等需要JavaScript执行的页面。

    Args:
        url: 目标网页URL
        timeout: 页面加载超时（毫秒）

    Returns:
        FetchResult包含渲染后的页面文本
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            await page.goto(url, wait_until="networkidle", timeout=timeout)
            await page.wait_for_timeout(2000)

            title = await page.title()
            content = await page.inner_text("body")
            snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            await browser.close()

            return FetchResult(
                url=url,
                title=title,
                content=content,
                accessed_at=datetime.now(),
                snapshot_hash=snapshot_hash,
                success=True,
            )

    except Exception as e:
        return FetchResult(
            url=url,
            success=False,
            error=f"{type(e).__name__}: {str(e)}",
        )


def _extract_title(markdown_content: str) -> str:
    """从Markdown内容中提取标题"""
    for line in markdown_content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line.startswith("Title:"):
            return line[6:].strip()
    return ""
