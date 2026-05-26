"""DiscoveryAgent - 竞品URL发现与路由

双路径架构：
- Warm Path: 已知竞品从缓存直接返回精确URL
- Cold Path: 未知竞品通过Jina Search发现官网域名，再构造维度URL

输出: discovered_urls 列表，供 Collector 直接采集
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

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

JINA_SEARCH_URL = "https://s.jina.ai/"


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
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{JINA_SEARCH_URL}{query}",
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                results = data.get("data", [])
                if not results:
                    return None

                # 从搜索结果中提取最可能的官网域名
                return self._extract_official_domain(competitor_name, results)
        except Exception:
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
        EXCLUDE_DOMAINS = {
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

            if any(excl in domain for excl in EXCLUDE_DOMAINS):
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
            if not any(excl in domain for excl in EXCLUDE_DOMAINS):
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
            async with httpx.AsyncClient(timeout=15.0) as client:
                for dim in dimensions[:4]:
                    query = f"site:{domain} {dim.replace('_', ' ')}"
                    resp = await client.get(
                        f"{JINA_SEARCH_URL}{query}",
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for result in data.get("data", [])[:2]:
                        url = result.get("url", "")
                        if url and domain in url:
                            urls.append(url)
        except Exception:
            pass

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
        urls: list[str] = []
        search_queries: list[str] = []
        trusted_urls: list[str] = []
        other_urls: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for dim in dimensions:
                    # 构造搜索词：竞品名 + 维度 + 补充关键词
                    dim_cn = self._dimension_to_chinese(dim)
                    query = f"{competitor_name} {dim_cn}"
                    search_queries.append(query)

                    resp = await client.get(
                        f"{JINA_SEARCH_URL}{query}",
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for result in data.get("data", [])[:4]:
                        url = result.get("url", "")
                        if not url:
                            continue
                        # 按白名单分桶
                        if self._is_trusted_domain(url, trusted_domains):
                            if url not in trusted_urls:
                                trusted_urls.append(url)
                        else:
                            if url not in other_urls:
                                other_urls.append(url)

                # 补充搜索：市场份额、行业报告
                extra_queries = [
                    f"{competitor_name} 市场份额 2025",
                    f"{competitor_name} 行业分析报告",
                ]
                for query in extra_queries:
                    search_queries.append(query)
                    resp = await client.get(
                        f"{JINA_SEARCH_URL}{query}",
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for result in data.get("data", [])[:3]:
                        url = result.get("url", "")
                        if not url:
                            continue
                        if self._is_trusted_domain(url, trusted_domains):
                            if url not in trusted_urls:
                                trusted_urls.append(url)
                        else:
                            if url not in other_urls:
                                other_urls.append(url)

        except Exception:
            pass

        # 白名单内的 URL 优先，补充其他 URL，总共最多 10 个
        urls = trusted_urls + other_urls
        urls = urls[:10]

        return {
            "path": "open_search",
            "domain": "",
            "urls": urls,
            "search_queries": search_queries,
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
            "price_range": "价格区间 定位",
            "target_demographics": "目标用户 人群画像",
            "marketing_channels": "营销渠道 推广",
            "product_line_breadth": "产品线 SKU",
            "sustainability": "ESG 可持续发展",
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
            async with httpx.AsyncClient(timeout=15.0) as client:
                for dim in dimensions:
                    query = f"{competitor_name} {dim.replace('_', ' ')}"
                    search_queries.append(query)
                    resp = await client.get(
                        f"{JINA_SEARCH_URL}{query}",
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for result in data.get("data", [])[:2]:
                        url = result.get("url", "")
                        if url:
                            urls.append(url)

                # 补充客户案例搜索
                query = f"{competitor_name} customer stories case studies"
                search_queries.append(query)
                resp = await client.get(
                    f"{JINA_SEARCH_URL}{query}",
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for result in data.get("data", [])[:2]:
                        url = result.get("url", "")
                        if url:
                            urls.append(url)
        except Exception:
            pass

        return {
            "path": "cold",
            "domain": "",
            "urls": urls,
            "search_queries": search_queries,
        }
