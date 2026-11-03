from copy import deepcopy

import pytest

from benchmark.evaluators.depth_eval import canonical_url, evaluate


def test_counts_core_nested_and_extension_evidence(profile, evidence):
    profile["feature_tree"][0]["sub_features"] = [{"name": "Nested", "description": evidence}]
    profile["user_personas"][0]["satisfaction_signals"] = [evidence]
    profile["extensions"] = {"ai_features": evidence}
    profile["pricing"]["tiers"] = [
        {"name": "Free", "price": "$0"},
        {"name": "Pro", "price": "$10"},
    ]
    result = evaluate(profile, "saas")
    assert result["feature_evidence_count"].value == 2
    assert result["pricing_evidence_count"].value == 1
    assert result["persona_evidence_count"].value == 2
    assert result["swot_evidence_count"].value == 4
    assert result["evidence_count"].value == 10  # Includes extension evidence.
    assert result["unique_source_count"].value == 1
    for dimension in ("feature", "pricing", "persona", "swot"):
        assert result[f"{dimension}_unique_source_count"].value == 1
    assert result["pricing_tier_count"].value == 2
    assert result["pricing_has_tiers"].value is True


def test_url_normalization_deduplicates_host_port_and_fragment(profile, evidence):
    alternate = deepcopy(evidence)
    alternate["sources"][0]["url"] = "HTTPS://EXAMPLE.COM:443/test#section"
    profile["feature_tree"][0]["sub_features"] = [{"name": "Nested", "description": alternate}]
    result = evaluate(profile)
    assert result["feature_evidence_count"].value == 2
    assert result["feature_unique_source_count"].value == 1
    assert canonical_url("https://EXAMPLE.com") == "https://example.com/"
    assert canonical_url("https://example.com/A?b=1&a=2") != canonical_url(
        "https://example.com/a?a=2&b=1"
    )


def test_invalid_citations_do_not_count_as_evidence(profile):
    profile["feature_tree"][0]["description"] = deepcopy(profile["feature_tree"][0]["description"])
    profile["feature_tree"][0]["description"]["sources"][0]["snippet"] = " "
    result = evaluate(profile)
    assert result["feature_evidence_count"].value == 0
    assert result["feature_unique_source_count"].value == 0
    assert result["evidence_count"].value == 6


def test_empty_containers_are_zero_and_empty_tiers_are_known(profile):
    profile["feature_tree"] = []
    profile["user_personas"] = []
    profile["swot"] = []
    profile["pricing"]["tiers"] = []
    result = evaluate(profile)
    for dimension in ("feature", "persona", "swot"):
        assert result[f"{dimension}_evidence_count"].value == 0
        assert result[f"{dimension}_unique_source_count"].value == 0
    assert result["pricing_tier_count"].value == 0
    assert result["pricing_has_tiers"].value is False


def test_missing_profile_is_unknown():
    result = evaluate(None)
    assert all(metric.value is None and metric.reason == "no_profile" for metric in result.values())


def test_missing_dimension_is_unknown_not_zero(profile):
    del profile["feature_tree"]
    result = evaluate(profile)
    assert result["feature_evidence_count"].value is None
    assert result["feature_evidence_count"].reason == "feature_tree_missing"
    assert result["evidence_count"].value is None
    assert result["unique_source_count"].details["missing_or_invalid"] == ["feature_tree_missing"]


@pytest.mark.parametrize(
    "tiers,reason",
    [
        (None, "pricing_tiers_invalid"),
        ("bad", "pricing_tiers_invalid"),
        ([{"name": "Free"}], "pricing_tiers_invalid"),
    ],
)
def test_invalid_tiers_are_unknown(profile, tiers, reason):
    profile["pricing"]["tiers"] = tiers
    result = evaluate(profile)
    assert result["pricing_tier_count"].value is None
    assert result["pricing_has_tiers"].value is None
    assert result["pricing_tier_count"].reason == reason


def test_missing_tiers_are_unknown(profile):
    result = evaluate(profile)
    assert result["pricing_tier_count"].value is None
    assert result["pricing_tier_count"].reason == "pricing_tiers_missing"
    assert result["pricing_has_tiers"].value is None


def test_malformed_dimension_does_not_crash(profile):
    profile["user_personas"] = "bad"
    result = evaluate(profile)
    assert result["persona_evidence_count"].value is None
    assert result["persona_unique_source_count"].reason == "user_personas_invalid"
    assert result["evidence_count"].value is None
