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
import re
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
    "insta360": {
        "domain": "insta360.com",
        "urls": {
            "pricing": ["https://store.insta360.com/product/x5"],
            "features": ["https://www.insta360.com/product/insta360-x5"],
            "integrations": ["https://www.insta360.com/download/insta360-x5"],
            "core_specs": [
                "https://www.insta360.com/product/insta360-x5",
                "https://onlinemanual.insta360.com/x5/en-us/faq/specs/hardware",
            ],
            "ecosystem_lock_in": [
                "https://www.insta360.com/download/insta360-x5",
            ],
            "repairability_score": [
                "https://onlinemanual.insta360.com/service/en-us/service/service-policy",
            ],
            "certifications": [
                "https://www.insta360.com/product/insta360-x5",
            ],
            "manufacturing_origin": [
                "https://www.insta360.com/about",
            ],
            "update_policy": [
                "https://www.insta360.com/download/insta360-x5",
            ],
            "connectivity": [
                "https://onlinemanual.insta360.com/x5/en-us/faq/specs/hardware",
            ],
            "battery_life": [
                "https://www.insta360.com/product/insta360-x5",
            ],
            "after_sales_policy": [
                "https://onlinemanual.insta360.com/service/en-us/service/service-policy",
                "https://www.insta360.com/support",
            ],
            "customers": ["https://www.insta360.com/explore"],
        },
    },
}
ALIASES: dict[str, str] = {
    "飞书": "feishu",
    "lark": "feishu",
    "click up": "clickup",
    "monday.com": "monday",
    "arashi vision": "insta360",
}

# Cold Path 常见维度路径模式（用于从官网域名构造URL）
DIMENSION_PATH_PATTERNS: dict[str, list[str]] = {
    "pricing": ["/pricing", "/plans"],
    "features": ["/features", "/product"],
    "integrations": ["/integrations", "/apps"],
    "ai_features": ["/ai", "/product/ai"],
    "customers": ["/customers", "/customer-stories", "/case-studies"],
    "core_specs": ["/product", "/products", "/support", "/download"],
    "ecosystem_lock_in": ["/download", "/apps", "/support"],
    "repairability_score": ["/support", "/service", "/warranty"],
    "certifications": ["/product", "/support", "/manual"],
    "manufacturing_origin": ["/about", "/company"],
    "update_policy": ["/download", "/support", "/firmware"],
    "connectivity": ["/product", "/support", "/manual"],
    "battery_life": ["/product", "/support", "/manual"],
    "after_sales_policy": ["/support", "/service", "/warranty"],
}

COMMON_SITE_PATHS = [
    "",
    "/product",
    "/products",
    "/store",
    "/support",
    "/download",
    "/downloads",
    "/service",
    "/warranty",
    "/about",
]

DOMAIN_GUESS_SUFFIXES = (
    ".com",
    ".cn",
    ".com.cn",
    ".io",
    ".ai",
    ".app",
    ".co",
    ".net",
)

SEARCH_EXCLUDE_DOMAINS = {
    "g2.com", "capterra.com", "trustradius.com",
    "wikipedia.org", "crunchbase.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "github.com",
    "reddit.com", "medium.com", "techcrunch.com",
}

_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None

# 已知不可抓取的域名（robots.txt 禁止或需要登录）
_UNFETCHABLE_DOMAINS = (
    "mp.weixin.qq.com", "weixin.qq.com",
    "login.", "passport.",
    "book118.com", "docin.com",
)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def _web_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """通过 Firecrawl Search API 获取搜索结果，含完整页面 markdown。

    使用 scrape_options 在搜索的同时抓取页面内容，无需单独 fetch，
    也不受 robots.txt 限制（Firecrawl 服务端处理合规）。
    返回的 content 字段包含完整页面 markdown，可直接供 Collector 提取 claim。
    """
    if not _env_flag("ENABLE_FIRECRAWL"):
        logger.info("ENABLE_FIRECRAWL=false，跳过 Firecrawl Search: query=%r", query)
        return []

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
            lambda: app.search(
                query=query,
                limit=8,
                scrape_options={"formats": ["markdown"]},
            ),
        )

        results: list[dict[str, Any]] = []

        # scrape_options 时返回 Document 对象列表，url 在 metadata.url
        items: list[Any] = []
        if hasattr(response, "web") and response.web:
            items = response.web
        elif isinstance(response, list):
            items = response

        for item in items:
            url = ""
            title = ""
            content = ""

            # scrape_options 模式：Document 对象，url 在 metadata
            if hasattr(item, "metadata") and item.metadata:
                md = item.metadata
                url = getattr(md, "url", "") or getattr(md, "source_url", "") or ""
                title = getattr(md, "title", "") or ""
                content = getattr(item, "markdown", "") or ""
            elif hasattr(item, "url"):
                # 无 scrape_options 的 SearchResultWeb 对象
                url = getattr(item, "url", "")
                title = getattr(item, "title", "") or ""
                content = getattr(item, "description", "") or ""
            elif isinstance(item, dict):
                url = item.get("url", "")
                title = item.get("title", "")
                content = item.get("markdown", "") or item.get("description", "") or ""

            if not url:
                continue
            if any(skip in url for skip in _UNFETCHABLE_DOMAINS):
                continue

            results.append({"url": url, "title": title, "content": content})

        logger.info(
            "firecrawl_search: query=%r found %d results (with_content=%d)",
            query, len(results), sum(1 for r in results if r["content"]),
        )
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
        if "insta360" in key or "\u5f71\u77f3" in key:
            return "insta360"
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

        urls = list(dict.fromkeys(urls))

        return {
            "path": "warm",
            "domain": entry["domain"],
            "urls": urls,
            "search_queries": [],
        }

    def _brand_variants(self, competitor_name: str) -> list[str]:
        variants: list[str] = []

        def add(value: str) -> None:
            value = value.strip()
            if value and value not in variants:
                variants.append(value)

        raw = competitor_name.strip()
        add(raw)
        add(raw.lower())

        normalized = self._normalize_name(raw)
        if normalized != raw.lower():
            add(normalized)

        latin_tokens = re.findall(r"[A-Za-z0-9]+", raw)
        if latin_tokens:
            tokens = [t.lower() for t in latin_tokens]
            add(" ".join(tokens))

            company_words = {
                "inc", "llc", "ltd", "limited", "co", "corp", "corporation",
                "company", "group", "tech", "technology", "technologies",
            }
            business_tokens = [t for t in tokens if t not in company_words]
            if business_tokens and business_tokens != tokens:
                add(" ".join(business_tokens))
                add("".join(business_tokens))
                add("-".join(business_tokens))
            add("".join(tokens))
            add("-".join(tokens))

        return variants[:8]

    def _domain_slugs(self, competitor_name: str) -> list[str]:
        slugs: list[str] = []

        def add(value: str) -> None:
            value = value.strip("-._").lower()
            if value and len(value) >= 2 and value not in slugs:
                slugs.append(value)

        company_words = {
            "inc", "llc", "ltd", "limited", "co", "corp", "corporation",
            "company", "group", "tech", "technology", "technologies",
        }
        for variant in self._brand_variants(competitor_name):
            if re.fullmatch(r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", variant.lower()):
                add(variant.lower())
                continue

            tokens = [
                token.lower()
                for token in re.findall(r"[A-Za-z0-9]+", variant)
                if token.lower() not in company_words
            ]
            if not tokens:
                continue
            add("".join(tokens))
            if len(tokens) > 1:
                add("-".join(tokens))

        return slugs[:6]

    def _guess_domains(self, competitor_name: str) -> list[str]:
        domains: list[str] = []
        for slug in self._domain_slugs(competitor_name):
            if "." in slug:
                candidates = [slug]
            else:
                candidates = [f"{slug}{suffix}" for suffix in DOMAIN_GUESS_SUFFIXES]
            for domain in candidates:
                if domain not in domains:
                    domains.append(domain)
        return domains[:40]

    def _build_domain_root_urls(self, domains: list[str]) -> list[str]:
        urls: list[str] = []
        for domain in domains:
            hosts = [domain]
            if not domain.startswith("www."):
                hosts.append(f"www.{domain}")
            for host in hosts:
                url = f"https://{host}"
                if url not in urls:
                    urls.append(url)
        return urls

    def _candidate_urls_for_bases(
        self, base_urls: list[str], dimensions: list[str]
    ) -> list[str]:
        paths: list[str] = []

        def add_path(path: str) -> None:
            if not path:
                path = ""
            elif not path.startswith("/"):
                path = f"/{path}"
            if path not in paths:
                paths.append(path)

        for path in COMMON_SITE_PATHS:
            add_path(path)
        for dim in dimensions:
            for path in DIMENSION_PATH_PATTERNS.get(dim, [f"/{dim}"]):
                add_path(path)
        if "customers" not in dimensions:
            for path in DIMENSION_PATH_PATTERNS.get("customers", ["/customers"]):
                add_path(path)

        urls: list[str] = []
        for base in base_urls:
            base = base.rstrip("/")
            for path in paths:
                url = f"{base}{path}"
                if url not in urls:
                    urls.append(url)
        return urls[:80]

    def _domain_from_url(self, url: str) -> str:
        return urlparse(url).netloc.lower().replace("www.", "")

    def _is_excluded_search_domain(self, domain: str) -> bool:
        domain = domain.lower().replace("www.", "")
        return any(
            domain == excluded or domain.endswith(f".{excluded}")
            for excluded in SEARCH_EXCLUDE_DOMAINS
        )

    def _result_domain_matches(
        self, url: str, domains: list[str]
    ) -> bool:
        domain = self._domain_from_url(url)
        return any(domain == d or domain.endswith(f".{d}") for d in domains)

    def _open_search_queries(
        self,
        competitor_name: str,
        dimensions: list[str],
        trusted_domains: list[str],
    ) -> list[str]:
        variants = self._brand_variants(competitor_name)
        primary = variants[:3] or [competitor_name]
        queries: list[str] = []

        def add(query: str) -> None:
            query = " ".join(query.split())
            if query and query not in queries:
                queries.append(query)

        for variant in primary:
            add(f"{variant} official website")
            add(f"{variant} 官网")

        for dim in dimensions[:6]:
            dim_cn = self._dimension_to_chinese(dim)
            dim_en = dim.replace("_", " ")
            for variant in primary[:2]:
                add(f"{variant} {dim_cn}")
                add(f"{variant} {dim_en}")

        for variant in primary[:2]:
            add(f"{variant} 行业分析 报告")
            add(f"{variant} 客户案例 用户评价")
            add(f"{variant} review product specs")

        for trusted in trusted_domains[:6]:
            for variant in primary[:2]:
                add(f"site:{trusted} {variant}")

        return queries[:24]

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
        slugs = self._domain_slugs(competitor_name)

        for result in results[:8]:
            url = result.get("url", "")
            if not url:
                continue

            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")

            if self._is_excluded_search_domain(domain):
                continue

            # 域名包含竞品名 → 高置信度
            domain_clean = domain.split(".")[0].replace("-", "")
            if any(slug in domain_clean or domain_clean in slug for slug in slugs):
                return domain

        # 没有精确匹配，取第一个非排除域名
        for result in results[:5]:
            url = result.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            if not self._is_excluded_search_domain(domain):
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
                        if resp.status_code in (403, 405):
                            resp = await client.get(url)
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

        同时保留搜索结果中的内容摘要（pre_fetched），供 Collector 在
        robots.txt 拦截时直接使用，避免因无法抓取而丢失高质量数据。
        """
        search_queries: list[str] = self._open_search_queries(
            competitor_name, dimensions, trusted_domains
        )
        trusted_urls: list[str] = []
        official_urls: list[str] = []
        other_urls: list[str] = []
        # URL → 搜索结果中的内容摘要（Firecrawl Search 返回的 description/snippet）
        pre_fetched: dict[str, str] = {}
        total_hits = 0

        def _append_unique(bucket: list[str], url: str) -> bool:
            if url not in bucket:
                bucket.append(url)
                return True
            return False

        def _clean_url(url: str) -> str:
            return url.strip().split("#", 1)[0]

        def _is_usable_url(url: str) -> bool:
            if not url.startswith(("http://", "https://")):
                return False
            if "/search?" in url:
                return False
            if any(skip in url for skip in _UNFETCHABLE_DOMAINS):
                return False
            return True

        def _absorb(results: list[dict[str, Any]], official_domains: list[str]) -> int:
            count = 0
            for result in results:
                url = _clean_url(result.get("url", ""))
                if not _is_usable_url(url):
                    continue
                # 保留搜索结果中的内容摘要
                content = result.get("content", "")
                if content and url not in pre_fetched:
                    pre_fetched[url] = content
                if official_domains and self._result_domain_matches(url, official_domains):
                    if _append_unique(official_urls, url):
                        count += 1
                elif self._is_trusted_domain(url, trusted_domains):
                    if _append_unique(trusted_urls, url):
                        count += 1
                else:
                    domain = self._domain_from_url(url)
                    if self._is_excluded_search_domain(domain):
                        continue
                    if _append_unique(other_urls, url):
                        count += 1
            return count

        all_search_results: list[dict[str, Any]] = []
        official_domains: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=15.0, proxy=_PROXY) as client:
                search_tasks = [
                    asyncio.create_task(_web_search(client, query))
                    for query in search_queries
                ]
                guessed_roots = self._build_domain_root_urls(
                    self._guess_domains(competitor_name)
                )
                root_task = asyncio.create_task(self._validate_urls(guessed_roots))

                search_batches = await asyncio.gather(
                    *search_tasks, return_exceptions=True
                )
                for batch in search_batches:
                    if isinstance(batch, Exception):
                        logger.warning("open_search fanout task failed: %s", batch)
                        continue
                    total_hits += len(batch)
                    all_search_results.extend(batch[:6])

                discovered_domain = self._extract_official_domain(
                    competitor_name, all_search_results
                )
                if discovered_domain:
                    official_domains.append(discovered_domain)

                valid_roots = await root_task
                for root in valid_roots:
                    domain = self._domain_from_url(root)
                    if domain and domain not in official_domains:
                        official_domains.append(domain)
                    _append_unique(official_urls, root)

                if official_domains:
                    base_urls: list[str] = []
                    for domain in official_domains:
                        base_urls.append(f"https://{domain}")
                        if not domain.startswith("www."):
                            base_urls.append(f"https://www.{domain}")
                    candidate_urls = self._candidate_urls_for_bases(
                        list(dict.fromkeys(base_urls)), dimensions
                    )
                    valid_candidates = await self._validate_urls(candidate_urls)
                    for url in valid_candidates:
                        if self._result_domain_matches(url, official_domains):
                            _append_unique(official_urls, url)

                _absorb(all_search_results, official_domains)
        except Exception as e:
            logger.warning("open_search_path failed: %r error=%s", competitor_name, e)

        urls: list[str] = []
        for bucket in (official_urls, trusted_urls, other_urls):
            for url in bucket:
                if url not in urls:
                    urls.append(url)
        urls = urls[:10]

        if not urls:
            logger.warning(
                "open_search_path: 0 URLs for %r after %d queries (total_hits=%d). "
                "Likely competitor not indexed in Chinese sources or search blocked.",
                competitor_name, len(search_queries), total_hits,
            )

        # 只保留被选中 URL 的 pre_fetched 内容
        selected_pre_fetched = {u: pre_fetched[u] for u in urls if u in pre_fetched}

        return {
            "path": "open_search",
            "domain": official_domains[0] if official_domains else "",
            "urls": urls,
            "search_queries": search_queries,
            "trusted_count": len(trusted_urls),
            "other_count": len(other_urls),
            "official_count": len(official_urls),
            "pre_fetched": selected_pre_fetched,
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
