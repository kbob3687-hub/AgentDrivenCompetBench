"""Tests for analyst profile construction helpers."""

import pytest

from agents.analyst.tools import build_competitor_profile, build_pricing_model


def test_build_pricing_model_defaults_null_model_type_and_currency(sample_claims):
    pricing = build_pricing_model(
        {
            "model_type": None,
            "currency": None,
            "tiers": [
                {
                    "name": "Free",
                    "price": "$0",
                    "billing_cycle": "monthly",
                    "features": ["Basic workspace"],
                    "limitations": [],
                }
            ],
            "evidence_claim_indices": [0],
            "confidence": 0.9,
        },
        sample_claims,
    )

    assert pricing is not None
    assert pricing.model_type == "subscription"
    assert pricing.currency == "USD"


def test_build_pricing_model_skips_when_no_real_source(sample_claims):
    sample_claims[0]["sources"] = []

    pricing = build_pricing_model(
        {
            "model_type": "subscription",
            "currency": "USD",
            "tiers": [{"name": "Free", "price": "$0"}],
            "evidence_claim_indices": [0],
            "confidence": 0.9,
        },
        sample_claims,
    )

    assert pricing is None


def test_build_pricing_model_uses_direct_claim_text(sample_claims):
    pricing = build_pricing_model(
        {
            "model_type": "subscription",
            "currency": "USD",
            "tiers": [{"name": "Free", "price": "$0"}],
            "evidence_claim_indices": [0],
            "confidence": 0.9,
        },
        sample_claims,
    )

    assert pricing is not None
    assert pricing.evidence.sources[0].url == "https://www.notion.so/pricing"
    assert "推理" not in pricing.evidence.reasoning
    assert pricing.evidence.claim == sample_claims[0]["claim"]


def test_profile_build_handles_null_optional_llm_arrays(sample_claims):
    profile = build_competitor_profile(
        "Notion",
        {
            "company_name": "Notion",
            "product_name": "Notion",
            "website": "https://www.notion.so",
            "industry": "software",
            "pricing": {
                "model_type": "subscription",
                "evidence_claim_indices": [0],
                "tiers": None,
            },
            "feature_tree": [
                {"name": "Collaboration", "evidence_claim_indices": [1], "sub_features": None}
            ],
            "user_personas": [
                {
                    "segment": "Teams",
                    "evidence_claim_indices": [1],
                    "pain_points": None,
                    "usage_scenarios": None,
                }
            ],
            "swot": {"strengths": None, "weaknesses": None},
        },
        sample_claims,
    )

    assert profile.pricing is not None
    assert profile.pricing.tiers == []
    assert len(profile.feature_tree) == 1
    assert profile.feature_tree[0].sub_features == []
    assert len(profile.user_personas) == 1
    assert profile.user_personas[0].usage_scenarios == []
    assert profile.swot == []


def test_null_evidence_indices_do_not_create_unsupported_pricing(sample_claims):
    pricing = build_pricing_model(
        {"model_type": "subscription", "tiers": None, "evidence_claim_indices": None},
        sample_claims,
    )

    assert pricing is None


def test_malformed_evidence_indices_have_specific_error(sample_claims):
    with pytest.raises(ValueError, match="evidence_claim_indices must be a list"):
        build_pricing_model(
            {"model_type": "subscription", "evidence_claim_indices": "0"}, sample_claims
        )
