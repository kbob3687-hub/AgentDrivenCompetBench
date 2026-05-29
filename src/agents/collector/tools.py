"""CollectorAgent采集工具 - Jina Reader + Playwright + 直接HTTP抓取

降级链：Jina Reader → 直接HTTP抓取 → Playwright（JS渲染页面）
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("collector.tools")


class FetchResult(BaseModel):
    """采集结果"""

    url: str
    title: str = ""
    content: str = ""
    accessed_at: datetime = Field(default_factory=datetime.now)
    snapshot_hash: str = ""
    success: bool = True
    error: str | None = None
    robots_status: str = ""
    pii_redactions: dict[str, int] = Field(default_factory=dict)
    fetch_method: str = ""  # 记录实际使用的抓取方法


async def jina_reader(url: str, timeout: float = 45.0, max_retries: int = 2) -> FetchResult:
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
    import os

    jina_url = f"https://r.jina.ai/{url}"

    headers = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
    }
    api_key = os.getenv("JINA_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

    last_error = ""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, proxy=proxy
            ) as client:
                response = await client.get(jina_url, headers=headers)
                response.raise_for_status()

                content = response.text
                # 检查 Jina 返回的错误消息（如配额耗尽）
                if "InsufficientBalanceError" in content or "Account balance not enough" in content:
                    logger.warning("Jina Reader 配额耗尽: url=%s", url)
                    return FetchResult(
                        url=url,
                        success=False,
                        error="Jina API 配额耗尽 (InsufficientBalanceError)",
                        fetch_method="jina_reader",
                    )

                title = _extract_title(content)
                snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                return FetchResult(
                    url=url,
                    title=title,
                    content=content,
                    accessed_at=datetime.now(),
                    snapshot_hash=snapshot_hash,
                    success=True,
                    fetch_method="jina_reader",
                )

        except httpx.TimeoutException:
            last_error = f"Timeout after {timeout}s"
            logger.warning("Jina Reader 超时: url=%s, timeout=%ss", url, timeout)
        except httpx.HTTPStatusError as e:
            last_error = (
                f"HTTP {e.response.status_code} {e.response.reason_phrase}: "
                f"{e.response.text[:200]}"
            )
            logger.warning(
                "Jina Reader HTTP错误: url=%s, status=%d, body=%s",
                url, e.response.status_code, e.response.text[:100],
            )
            # 4xx 通常重试无意义（401/403/402 配额或鉴权），429 除外
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                break
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning("Jina Reader 异常: url=%s, error=%s", url, last_error)

        if attempt < max_retries - 1:
            await asyncio.sleep(2 * (attempt + 1))

    return FetchResult(
        url=url,
        success=False,
        error=f"Jina Reader 失败 ({max_retries}次尝试): {last_error}",
        fetch_method="jina_reader",
    )


async def firecrawl_fetch(url: str, timeout: float = 60.0) -> FetchResult:
    """通过 Firecrawl 获取网页的干净 Markdown 内容

    Firecrawl 是 Jina Reader 的替代方案：
    - 自动去广告、导航等噪音
    - 返回干净的 Markdown
    - 支持 JS 渲染页面
    - 可自托管（开源）

    Args:
        url: 目标网页URL
        timeout: 请求超时时间（秒）

    Returns:
        FetchResult包含干净的Markdown内容
    """
    import os

    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        logger.warning("FIRECRAWL_API_KEY 未配置，跳过 Firecrawl")
        return FetchResult(
            url=url,
            success=False,
            error="FIRECRAWL_API_KEY 未配置",
            fetch_method="firecrawl",
        )

    try:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)

        # 同步调用包装为异步
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: app.scrape_url(url)
        )

        # Firecrawl v4 返回 Document 对象，不是字典
        if not result or not hasattr(result, 'markdown') or not result.markdown:
            logger.warning("Firecrawl 返回空内容: url=%s", url)
            return FetchResult(
                url=url,
                success=False,
                error="Firecrawl 返回空内容",
                fetch_method="firecrawl",
            )

        content = result.markdown
        # 获取 metadata 中的 title
        title = ""
        if hasattr(result, 'metadata') and result.metadata:
            title = getattr(result.metadata, 'title', '') or ""
        if not title:
            title = _extract_title(content)

        snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        logger.info("Firecrawl 抓取成功: url=%s, len=%d", url, len(content))
        return FetchResult(
            url=url,
            title=title,
            content=content,
            accessed_at=datetime.now(),
            snapshot_hash=snapshot_hash,
            success=True,
            fetch_method="firecrawl",
        )

    except ImportError:
        logger.warning("firecrawl-py 未安装，跳过 Firecrawl")
        return FetchResult(
            url=url,
            success=False,
            error="firecrawl-py 未安装 (pip install firecrawl-py)",
            fetch_method="firecrawl",
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.warning("Firecrawl 抓取失败: url=%s, error=%s", url, error_msg)
        return FetchResult(
            url=url,
            success=False,
            error=error_msg,
            fetch_method="firecrawl",
        )


async def direct_http_fetch(url: str, timeout: float = 30.0) -> FetchResult:
    """直接HTTP抓取网页内容（不依赖Jina或Playwright）

    作为Jina Reader和Playwright之间的降级方案。
    使用httpx直接获取HTML，然后提取正文文本。

    Args:
        url: 目标网页URL
        timeout: 请求超时时间（秒）

    Returns:
        FetchResult包含网页文本内容
    """
    import os

    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, proxy=proxy
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            html = response.text
            content = _html_to_text(html)
            title = _extract_title_from_html(html) or _extract_title(content)
            snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            if len(content.strip()) < 50:
                logger.warning("直接HTTP抓取内容过短: url=%s, len=%d", url, len(content))
                return FetchResult(
                    url=url,
                    success=False,
                    error=f"内容过短 ({len(content)} 字符)，可能需要JS渲染",
                    fetch_method="direct_http",
                )

            logger.info("直接HTTP抓取成功: url=%s, len=%d", url, len(content))
            return FetchResult(
                url=url,
                title=title,
                content=content,
                accessed_at=datetime.now(),
                snapshot_hash=snapshot_hash,
                success=True,
                fetch_method="direct_http",
            )

    except httpx.TimeoutException:
        logger.warning("直接HTTP抓取超时: url=%s", url)
        return FetchResult(
            url=url,
            success=False,
            error=f"HTTP 抓取超时 ({timeout}s)",
            fetch_method="direct_http",
        )
    except httpx.HTTPStatusError as e:
        logger.warning("直接HTTP抓取HTTP错误: url=%s, status=%d", url, e.response.status_code)
        return FetchResult(
            url=url,
            success=False,
            error=f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            fetch_method="direct_http",
        )
    except Exception as e:
        logger.warning("直接HTTP抓取异常: url=%s, error=%s", url, str(e))
        return FetchResult(
            url=url,
            success=False,
            error=f"{type(e).__name__}: {str(e)}",
            fetch_method="direct_http",
        )


def _html_to_text(html: str) -> str:
    """从HTML中提取纯文本（简单实现，去除标签和脚本）"""
    # 移除 script 和 style 标签及其内容
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 注释
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', html)
    # 清理空白字符
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r' +', ' ', text)
    # 去除首尾空白
    text = text.strip()
    return text


def _extract_title_from_html(html: str) -> str:
    """从HTML中提取title标签内容"""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


async def playwright_fetch(url: str, timeout: float = 30000) -> FetchResult:
    """通过Playwright获取需要JS渲染的页面

    适用于：SaaS定价页、动态加载内容等需要JavaScript执行的页面。

    Args:
        url: 目标网页URL
        timeout: 页面加载超时（毫秒）

    Returns:
        FetchResult包含渲染后的页面文本
    """
    import os

    # 解决中文用户名路径问题：将浏览器安装到纯英文路径
    if not os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
        # 尝试使用项目目录下的 .playwright 目录
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        browsers_path = os.path.join(project_dir, ".playwright-browsers")
        if os.path.isdir(browsers_path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

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
                fetch_method="playwright",
            )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.warning("Playwright 抓取失败: url=%s, error=%s", url, error_msg)
        return FetchResult(
            url=url,
            success=False,
            error=error_msg,
            fetch_method="playwright",
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
