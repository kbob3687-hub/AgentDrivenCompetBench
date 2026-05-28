"""Tests for Discovery Agent (Warm Path / Cold Path URL resolution)."""

import pytest

from agents.discovery.agent import (
    DiscoveryAgent,
    KNOWN_COMPETITORS,
    ALIASES,
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
