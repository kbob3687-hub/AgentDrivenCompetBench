"""DiscoveryAgent - 竞品URL发现与路由

双路径架构：
- Warm Path: 已知竞品从缓存直接返回精确URL
- Cold Path: 未知竞品通过 Firecrawl Search 发现官网域名，再构造维度URL

输出: discovered_urls 列表，供 Collector 直接采集
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("discovery")

# ---- Warm Path: 已知竞品URL缓存 ----
# key: 竞品标准名(lowercase), value: {domain, urls_by_dimension}
KNOWN_COMPETITORS: dict[str, dict[str, Any]] = {
    "notion": {
        "domain": "notion.so",
        "urls": {
            "pricing": ["https://www.notion.so/pricing"],
            "features": ["https://www.notion.so/product"],
            "integrations": ["https://www.notion.so/integrations"],
            "ai_features": ["https://www.notion.so/product/ai"],
            "customers": ["https://www.notion.so/customers"],
        },
    },
    "feishu": {
        "domain": "feishu.cn",
        "urls": {
            "pricing": ["https://www.feishu.cn/pricing"],
            "features": ["https://www.feishu.cn/product/docs"],
            "integrations": ["https://www.feishu.cn/ecosystem"],
            "ai_features": ["https://www.feishu.cn/product/ai"],
            "customers": ["https://www.feishu.cn/customers"],
        },
    },
    "clickup": {
        "domain": "clickup.com",
        "urls": {
            "pricing": ["https://clickup.com/pricing"],
            "features": ["https://clickup.com/features"],
            "integrations": ["https://clickup.com/integrations"],
            "ai_features": ["https://clickup.com/ai"],
            "customers": ["https://clickup.com/customers"],
        },
    },
    "monday": {
        "domain": "monday.com",
        "urls": {
            "pricing": ["https://monday.com/pricing"],
            "features": ["https://monday.com/work-management"],
            "integrations": ["https://monday.com/integrations"],
            "customers": ["https://monday.com/customers/all"],
        },
    },
}
ALIASES: dict[str, str] = {
    "飞书": "feishu",
    "lark": "feishu",
    "click up": "clickup",
    "monday.com": "monday",
}

# Cold Path 常见维度路径模式（用于从官网域名构造URL）
DIMENSION_PATH_PATTERNS: dict[str, list[str]] = {
    "pricing": ["/pricing", "/plans"],
    "features": ["/features", "/product"],
    "integrations": ["/integrations", "/apps"],
    "ai_features": ["/ai", "/product/ai"],
    "customers": ["/customers", "/customer-stories", "/case-studies"],
}

_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None

# 已知不可抓取的域名（robots.txt 禁止或需要登录）
_UNFETCHABLE_DOMAINS = (
    "mp.weixin.qq.com", "weixin.qq.com",
    "login.", "passport.",
    "book118.com", "docin.com",
)


async def _web_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """通过 Firecrawl Search API 获取结果 URL 列表。

    返回结构化搜索结果，无需解析 HTML。
    """
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        logger.warning("FIRECRAWL_API_KEY 未配置，搜索不可用")
        return []

    try:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: app.search(query=query, limit=8)
        )

        results: list[dict[str, Any]] = []

        # SearchData 对象: 结果在 response.web 列表里
        items: list[Any] = []
        if hasattr(response, "web") and response.web:
            items = response.web
        elif isinstance(response, list):
            items = response

        for item in items:
            url = ""
            title = ""
            if isinstance(item, dict):
                url = item.get("url", "")
                title = item.get("title", "")
            elif hasattr(item, "url"):
                url = getattr(item, "url", "")
                title = getattr(item, "title", "") or ""

            if not url:
                continue
            if any(skip in url for skip in _UNFETCHABLE_DOMAINS):
                continue

            results.append({"url": url, "title": title, "content": ""})

        logger.info("firecrawl_search: query=%r found %d URLs", query, len(results))
        return results

    except ImportError:
        logger.warning("firecrawl-py 未安装，搜索不可用")
        return []
    except Exception as e:
        logger.warning("firecrawl_search failed: query=%r error=%s", query, e)
        return []


class DiscoveryAgent:
    """URL发现Agent - 不调用LLM，纯逻辑+搜索API"""

    async def discover(
        self,
        competitor_name: str,
        dimensions: list[str],
        strategy: str = "official_only",
        trusted_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """发现竞品URL

        Args:
            competitor_name: 竞品名称
            dimensions: 采集维度列表
            strategy: discovery策略 - official_only(官网优先) / open_search(开放搜索)
            trusted_domains: open_search策略下的权威媒体白名单

        Returns:
            {
                "path": "warm" | "cold" | "open_search",
                "domain": str,  # 官网域名（open_search时可能为空）
                "urls": list[str],  # 发现的URL列表
                "search_queries": list[str],  # 搜索词（用于溯源）
            }
        """
        key = self._normalize_name(competitor_name)

        # 已知竞品始终走 warm path（URL已知，不依赖搜索）
        if key in KNOWN_COMPETITORS:
            return self._warm_path(key, dimensions)

        # 根据策略选择不同的发现方式
        if strategy == "open_search":
            return await self._open_search_path(competitor_name, dimensions, trusted_domains or [])
        else:
            return await self._cold_path(competitor_name, dimensions)

    def _normalize_name(self, name: str) -> str:
        key = name.lower().strip()
        return ALIASES.get(key, key)

    def _warm_path(self, key: str, dimensions: list[str]) -> dict[str, Any]:
        """Warm Path: 从缓存直接返回精确URL"""
        entry = KNOWN_COMPETITORS[key]
        urls: list[str] = []

        for dim in dimensions:
            urls.extend(entry["urls"].get(dim, []))

        # 始终注入客户案例页
        if "customers" not in dimensions:
            urls.extend(entry["urls"].get("customers", []))

        return {
            "path": "warm",
            "domain": entry["domain"],
            "urls": urls,
            "search_queries": [],
        }

    async def _cold_path(
        self, competitor_name: str, dimensions: list[str]
    ) -> dict[str, Any]:
        """Cold Path: Jina Search发现官网 → 域名过滤 → 构造维度URL"""
        search_queries: list[str] = []

        # Step 1: 搜索官网
        domain = await self._discover_domain(competitor_name)
        search_queries.append(f"{competitor_name} official site")

        if not domain:
            # 降级：直接用Jina搜索各维度
            return await self._fallback_search(competitor_name, dimensions)

        # Step 2: 从域名构造维度URL
        urls: list[str] = []
        base = f"https://{domain}"

        for dim in dimensions:
            patterns = DIMENSION_PATH_PATTERNS.get(dim, [f"/{dim}"])
            for pattern in patterns:
                urls.append(f"{base}{pattern}")

        # 始终加客户案例
        if "customers" not in dimensions:
            for pattern in DIMENSION_PATH_PATTERNS.get("customers", ["/customers"]):
                urls.append(f"{base}{pattern}")

        # Step 3: 并行验证URL可达性（HEAD请求，快速过滤404）
        valid_urls = await self._validate_urls(urls)

        # 如果验证后URL太少，补充搜索
        if len(valid_urls) < 2:
            extra = await self._search_dimension_urls(competitor_name, domain, dimensions)
            valid_urls.extend(extra)
            search_queries.extend(
                [f"{competitor_name} {dim}" for dim in dimensions]
            )

        return {
            "path": "cold",
            "domain": domain,
            "urls": valid_urls,
            "search_queries": search_queries,
        }

    async def _discover_domain(self, competitor_name: str) -> str | None:
        """通过Jina Search发现竞品官网域名"""
        query = f"{competitor_name} official website"
        try:
            async with httpx.AsyncClient(timeout=15.0, proxy=_PROXY) as client:
                results = await _web_search(client, query)
                if not results:
                    logger.info("discover_domain: no results for %r", competitor_name)
                    return None
                return self._extract_official_domain(competitor_name, results)
        except Exception as e:
            logger.warning("discover_domain failed: %r error=%s", competitor_name, e)
            return None

    def _extract_official_domain(
        self, competitor_name: str, results: list[dict]
    ) -> str | None:
        """从搜索结果中识别官网域名

        策略：
        1. 优先选择域名中包含竞品名的结果
        2. 排除已知聚合站（g2.com, capterra.com等）
        3. 取第一个匹配的结果
        """
        exclude_domains = {
            "g2.com", "capterra.com", "trustradius.com",
            "wikipedia.org", "crunchbase.com", "linkedin.com",
            "twitter.com", "x.com", "youtube.com", "github.com",
            "reddit.com", "medium.com", "techcrunch.com",
        }

        name_lower = competitor_name.lower().replace(" ", "")

        for result in results[:8]:
            url = result.get("url", "")
            if not url:
                continue

            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")

            if any(excl in domain for excl in exclude_domains):
                continue

            # 域名包含竞品名 → 高置信度
            domain_clean = domain.split(".")[0].replace("-", "")
            if name_lower in domain_clean or domain_clean in name_lower:
                return domain

        # 没有精确匹配，取第一个非排除域名
        for result in results[:5]:
            url = result.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            if not any(excl in domain for excl in exclude_domains):
                return domain

        return None

    async def _validate_urls(self, urls: list[str]) -> list[str]:
        """HEAD请求验证URL可达性，过滤404"""
        import asyncio

        valid: list[str] = []
        semaphore = asyncio.Semaphore(6)

        async def check(url: str) -> str | None:
            async with semaphore:
                try:
                    async with httpx.AsyncClient(
                        timeout=8.0, follow_redirects=True
                    ) as client:
                        resp = await client.head(url)
                        if resp.status_code < 400:
                            return url
                except Exception:
                    pass
                return None

        tasks = [check(u) for u in urls]
        results = await asyncio.gather(*tasks)
        valid = [r for r in results if r is not None]
        return valid

    async def _search_dimension_urls(
        self, competitor_name: str, domain: str, dimensions: list[str]
    ) -> list[str]:
        """用Jina搜索特定维度的页面，限定在官网域名内"""
        urls: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=15.0, proxy=_PROXY) as client:
                for dim in dimensions[:4]:
                    query = f"site:{domain} {dim.replace('_', ' ')}"
                    results = await _web_search(client, query)
                    for result in results[:2]:
                        url = result.get("url", "")
                        if url and domain in url:
                            urls.append(url)
        except Exception as e:
            logger.warning("search_dimension_urls failed: domain=%s error=%s", domain, e)
        return urls

    async def _open_search_path(
        self,
        competitor_name: str,
        dimensions: list[str],
        trusted_domains: list[str],
    ) -> dict[str, Any]:
        """Open Search策略：不限域名，搜索权威媒体内容

        适用于消费品/实体行业，情报分散在第三方行业报告、媒体、社交平台中。
        搜索结果按权威媒体白名单过滤，优先采信白名单内的来源。
        """
        search_queries: list[str] = []
        trusted_urls: list[str] = []
        other_urls: list[str] = []
        total_hits = 0

        def _absorb(results: list[dict[str, Any]]) -> int:
            count = 0
            for result in results:
                url = result.get("url", "")
                if not url:
                    continue
                if "/search?" in url:
                    continue
                if any(skip in url for skip in _UNFETCHABLE_DOMAINS):
                    continue
                if self._is_trusted_domain(url, trusted_domains):
                    if url not in trusted_urls:
                        trusted_urls.append(url)
                        count += 1
                else:
                    if url not in other_urls:
                        other_urls.append(url)
                        count += 1
            return count

        try:
            async with httpx.AsyncClient(timeout=15.0, proxy=_PROXY) as client:
                # 限制搜索次数：最多搜 6 个维度，避免 API 配额浪费
                for dim in dimensions[:6]:
                    dim_cn = self._dimension_to_chinese(dim)
                    query = f"{competitor_name} {dim_cn}"
                    search_queries.append(query)
                    results = await _web_search(client, query)
                    total_hits += _absorb(results[:4])

                for query in (
                    f"{competitor_name} 市场份额 2025",
                    f"{competitor_name} 行业分析报告",
                    f"{competitor_name} 客户案例 用户评价",
                ):
                    search_queries.append(query)
                    results = await _web_search(client, query)
                    total_hits += _absorb(results[:3])
        except Exception as e:
            logger.warning("open_search_path failed: %r error=%s", competitor_name, e)

        urls = (trusted_urls + other_urls)[:10]

        if not urls:
            logger.warning(
                "open_search_path: 0 URLs for %r after %d queries (total_hits=%d). "
                "Likely competitor not indexed in Chinese sources or search blocked.",
                competitor_name, len(search_queries), total_hits,
            )

        return {
            "path": "open_search",
            "domain": "",
            "urls": urls,
            "search_queries": search_queries,
            "trusted_count": len(trusted_urls),
            "other_count": len(other_urls),
        }

    def _dimension_to_chinese(self, dim: str) -> str:
        """维度名转中文搜索词，提高中文搜索命中率"""
        mapping = {
            "pricing": "价格 定价",
            "features": "功能 特性",
            "integrations": "集成 生态",
            "ai_features": "AI功能",
            "distribution_channels": "销售渠道 分销",
            "brand_sentiment": "口碑 评价 舆情",
            "market_share": "市场份额",
            "supply_chain": "供应链 代工",
            "supply_chain_model": "供应链 代工模式",
            "price_range": "价格区间 定位",
            "target_demographics": "目标用户 人群画像",
            "marketing_channels": "营销渠道 推广",
            "product_line_breadth": "产品线 SKU",
            "sustainability": "ESG 可持续发展",
            "sustainability_initiatives": "ESG 可持续发展",
        }
        return mapping.get(dim, dim.replace("_", " "))

    def _is_trusted_domain(self, url: str, trusted_domains: list[str]) -> bool:
        """检查URL是否属于权威媒体白名单"""
        if not trusted_domains:
            return False
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
            return any(trusted in domain for trusted in trusted_domains)
        except Exception:
            return False

    async def _fallback_search(
        self, competitor_name: str, dimensions: list[str]
    ) -> dict[str, Any]:
        """降级方案：无法确定域名时，直接搜索各维度"""
        urls: list[str] = []
        search_queries: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=15.0, proxy=_PROXY) as client:
                for dim in dimensions[:6]:
                    query = f"{competitor_name} {dim.replace('_', ' ')}"
                    search_queries.append(query)
                    results = await _web_search(client, query)
                    for result in results[:2]:
                        url = result.get("url", "")
                        if url:
                            urls.append(url)

                query = f"{competitor_name} customer stories case studies"
                search_queries.append(query)
                results = await _web_search(client, query)
                for result in results[:2]:
                    url = result.get("url", "")
                    if url:
                        urls.append(url)
        except Exception as e:
            logger.warning("fallback_search failed: %r error=%s", competitor_name, e)

        if not urls:
            logger.warning("fallback_search: 0 URLs for %r", competitor_name)

        return {
            "path": "cold",
            "domain": "",
            "urls": urls,
            "search_queries": search_queries,
        }
