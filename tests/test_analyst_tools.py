"""Tests for analyst profile construction helpers."""

from agents.analyst.tools import build_pricing_model


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
