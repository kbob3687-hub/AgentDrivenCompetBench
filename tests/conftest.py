"""Shared test fixtures for the competitive analysis pipeline."""

import pytest


@pytest.fixture
def sample_claims():
    """Sample claims as returned by CollectorAgent."""
    return [
        {
            "claim": "Notion提供免费个人版，Pro版$10/月/用户",
            "confidence": 0.9,
            "reasoning": "从Notion定价页面提取",
            "dimension": "pricing",
            "sources": [
                {
                    "source_type": "web_page",
                    "url": "https://www.notion.so/pricing",
                    "title": "Notion Pricing",
                    "snippet": "Free for personal use. Pro: $10/month per user.",
                    "accessed_at": "2025-01-01T00:00:00",
                    "snapshot_hash": "abc123",
                }
            ],
        },
        {
            "claim": "Notion支持实时协作编辑",
            "confidence": 0.85,
            "reasoning": "从Notion产品页面提取",
            "dimension": "features",
            "sources": [
                {
                    "source_type": "web_page",
                    "url": "https://www.notion.so/product",
                    "title": "Notion Product",
                    "snippet": "Real-time collaboration for teams of any size.",
                    "accessed_at": "2025-01-01T00:00:00",
                    "snapshot_hash": "def456",
                }
            ],
        },
        {
            "claim": "Notion提供REST API和官方SDK",
            "confidence": 0.88,
            "reasoning": "从Notion集成页面提取",
            "dimension": "integrations",
            "sources": [
                {
                    "source_type": "web_page",
                    "url": "https://www.notion.so/integrations",
                    "title": "Notion Integrations",
                    "snippet": "Build with the Notion API. Official SDKs for Python, JS.",
                    "accessed_at": "2025-01-01T00:00:00",
                    "snapshot_hash": "ghi789",
                }
            ],
        },
        {
            "claim": "Notion支持与Slack、Google Drive等100+集成",
            "confidence": 0.82,
            "reasoning": "从Notion集成页面提取",
            "dimension": "integrations",
            "sources": [
                {
                    "source_type": "web_page",
                    "url": "https://www.notion.so/integrations",
                    "title": "Notion Integrations",
                    "snippet": "Connect with 100+ tools including Slack, Google Drive.",
                    "accessed_at": "2025-01-01T00:00:00",
                    "snapshot_hash": "ghi789",
                }
            ],
        },
    ]


@pytest.fixture
def sample_profile():
    """Sample CompetitorProfile dict as returned by AnalystAgent."""
    return {
        "competitor_name": "Notion",
        "pricing": {
            "tiers": [
                {"name": "Free", "price": "$0", "features": ["个人使用"]},
                {"name": "Pro", "price": "$10/月/用户", "features": ["团队协作", "无限存储"]},
            ],
            "evidence": {
                "claim": "Notion提供免费个人版，Pro版$10/月/用户",
                "confidence": 0.9,
                "sources": [
                    {
                        "source_type": "web_page",
                        "url": "https://www.notion.so/pricing",
                        "title": "Notion Pricing",
                        "snippet": "Free for personal use. Pro: $10/month per user.",
                        "accessed_at": "2025-01-01T00:00:00",
                        "snapshot_hash": "abc123",
                    }
                ],
            },
        },
        "feature_tree": [
            {
                "name": "实时协作",
                "description": {
                    "claim": "支持多人实时编辑同一文档",
                    "confidence": 0.85,
                    "sources": [
                        {
                            "source_type": "web_page",
                            "url": "https://www.notion.so/product",
                            "title": "Notion Product",
                            "snippet": "Real-time collaboration for teams of any size.",
                            "accessed_at": "2025-01-01T00:00:00",
                            "snapshot_hash": "def456",
                        }
                    ],
                },
            }
        ],
        "swot": [
            {
                "category": "strength",
                "items": [
                    {
                        "claim": "灵活的模块化设计",
                        "confidence": 0.8,
                        "sources": [
                            {
                                "source_type": "web_page",
                                "url": "https://www.notion.so/product",
                                "title": "Notion Product",
                                "snippet": "Build any workflow with blocks.",
                                "accessed_at": "2025-01-01T00:00:00",
                                "snapshot_hash": "def456",
                            }
                        ],
                    }
                ],
            },
            {
                "category": "weakness",
                "items": [
                    {
                        "claim": "离线功能有限",
                        "confidence": 0.75,
                        "sources": [
                            {
                                "source_type": "app_store_review",
                                "url": "https://apps.apple.com/notion",
                                "title": "App Store Reviews",
                                "snippet": "Offline mode is very limited.",
                                "accessed_at": "2025-01-01T00:00:00",
                                "snapshot_hash": "jkl012",
                            }
                        ],
                    }
                ],
            },
        ],
    }
