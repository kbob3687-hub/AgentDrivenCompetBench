"""Tests for Discovery Agent (Warm Path / Cold Path URL resolution)."""

import pytest

from agents.discovery import agent as discovery_module
from agents.discovery.agent import (
    DiscoveryAgent,
    KNOWN_COMPETITORS,
)


class TestDiscoveryWarmPath:
    """Test Warm Path: known competitors get instant URL resolution."""

    @pytest.fixture
    def agent(self):
        return DiscoveryAgent()

    @pytest.mark.asyncio
    async def test_notion_warm_path(self, agent):
        result = await agent.discover("Notion", ["pricing", "features"])
        assert result["path"] == "warm"
        assert result["domain"] == "notion.so"
        assert any("pricing" in u for u in result["urls"])
        assert any("product" in u or "features" in u for u in result["urls"])
        # customers always injected
        assert any("customers" in u for u in result["urls"])

    @pytest.mark.asyncio
    async def test_feishu_alias(self, agent):
        result = await agent.discover("飞书", ["pricing"])
        assert result["path"] == "warm"
        assert result["domain"] == "feishu.cn"
        assert any("pricing" in u for u in result["urls"])

    @pytest.mark.asyncio
    async def test_clickup_case_insensitive(self, agent):
        result = await agent.discover("ClickUp", ["integrations"])
        assert result["path"] == "warm"
        assert result["domain"] == "clickup.com"
        assert any("integrations" in u for u in result["urls"])

    @pytest.mark.asyncio
    async def test_user_specified_urls_bypass(self, agent):
        """When target_urls are provided, discovery is skipped."""
        # This tests the node-level logic, not the agent directly
        # The agent itself doesn't handle this — the node does
        pass

    def test_normalize_name(self, agent):
        assert agent._normalize_name("Notion") == "notion"
        assert agent._normalize_name("  ClickUp  ") == "clickup"
        assert agent._normalize_name("飞书") == "feishu"
        assert agent._normalize_name("Lark") == "feishu"
        assert agent._normalize_name("Click Up") == "clickup"

    @pytest.mark.asyncio
    async def test_customers_always_injected(self, agent):
        """Even if scope doesn't include customers, they're added."""
        result = await agent.discover("monday", ["pricing"])
        assert any("customers" in u for u in result["urls"])

    @pytest.mark.asyncio
    async def test_insta360_mixed_chinese_english_alias(self, agent):
        result = await agent.discover(
            "影石insta360",
            ["pricing", "features", "core_specs", "after_sales_policy"],
            strategy="open_search",
        )

        assert result["path"] == "warm"
        assert result["domain"] == "insta360.com"
        assert result["search_queries"] == []
        assert any("store.insta360.com/product/x5" in u for u in result["urls"])
        assert any("insta360-x5" in u for u in result["urls"])
        assert any("service-policy" in u for u in result["urls"])
        assert len(result["urls"]) == len(set(result["urls"]))

    def test_insta360_normalize_variants(self, agent):
        assert agent._normalize_name("Insta360") == "insta360"
        assert agent._normalize_name("影石Insta360") == "insta360"
        assert agent._normalize_name("影石insta360") == "insta360"


class TestDiscoveryColdPath:
    """Test Cold Path logic (without actual network calls)."""

    @pytest.fixture
    def agent(self):
        return DiscoveryAgent()

    def test_extract_official_domain_exact_match(self, agent):
        results = [
            {"url": "https://www.asana.com/product"},
            {"url": "https://g2.com/products/asana"},
        ]
        domain = agent._extract_official_domain("asana", results)
        assert domain == "asana.com"

    def test_extract_official_domain_excludes_aggregators(self, agent):
        results = [
            {"url": "https://www.g2.com/products/linear"},
            {"url": "https://www.capterra.com/p/linear"},
            {"url": "https://linear.app/features"},
        ]
        domain = agent._extract_official_domain("linear", results)
        assert domain == "linear.app"

    def test_extract_official_domain_no_match(self, agent):
        results = [
            {"url": "https://www.g2.com/products/xyz"},
            {"url": "https://www.capterra.com/p/xyz"},
        ]
        domain = agent._extract_official_domain("xyz", results)
        assert domain is None

    def test_unknown_competitor_triggers_cold_path(self, agent):
        key = agent._normalize_name("Asana")
        assert key not in KNOWN_COMPETITORS

    def test_brand_variants_extract_latin_brand_from_mixed_name(self, agent):
        variants = agent._brand_variants("影石Insta360")

        assert "影石Insta360" in variants
        assert "insta360" in variants

    def test_domain_guesses_strip_company_suffixes(self, agent):
        guesses = agent._guess_domains("Acme Technologies Ltd")

        assert "acme.com" in guesses
        assert "acmetechnologiesltd.com" in guesses

    @pytest.mark.asyncio
    async def test_open_search_uses_guessed_domain_when_search_returns_zero(
        self, agent, monkeypatch
    ):
        queries: list[str] = []

        async def fake_web_search(client, query):
            queries.append(query)
            return []

        async def fake_validate_urls(urls):
            return [
                url for url in urls
                if url in {
                    "https://acme.com",
                    "https://acme.com/product",
                    "https://www.acme.com/support",
                }
            ]

        monkeypatch.setattr(discovery_module, "_web_search", fake_web_search)
        monkeypatch.setattr(agent, "_validate_urls", fake_validate_urls)

        result = await agent.discover(
            "Acme Technologies Ltd",
            ["features", "after_sales_policy"],
            strategy="open_search",
        )

        assert result["path"] == "open_search"
        assert result["domain"] == "acme.com"
        assert "https://acme.com" in result["urls"]
        assert "https://acme.com/product" in result["urls"]
        assert "https://www.acme.com/support" in result["urls"]
        assert any("Acme Technologies Ltd official website" in q for q in queries)
        assert any(q == "acme official website" for q in queries)

    @pytest.mark.asyncio
    async def test_open_search_carries_prefetched_content_from_search_results(
        self, agent, monkeypatch
    ):
        async def fake_web_search(client, query):
            if "official website" not in query:
                return []
            return [{
                "url": "https://www.acmex.com/product",
                "title": "Acme X Product",
                "content": "Acme X product page markdown with enough source text.",
            }]

        async def fake_validate_urls(urls):
            return []

        monkeypatch.setattr(discovery_module, "_web_search", fake_web_search)
        monkeypatch.setattr(agent, "_validate_urls", fake_validate_urls)

        result = await agent.discover(
            "Acme X",
            ["features"],
            strategy="open_search",
        )

        assert result["urls"] == ["https://www.acmex.com/product"]
        assert result["domain"] == "acmex.com"
        assert result["pre_fetched"] == {
            "https://www.acmex.com/product": (
                "Acme X product page markdown with enough source text."
            )
        }
