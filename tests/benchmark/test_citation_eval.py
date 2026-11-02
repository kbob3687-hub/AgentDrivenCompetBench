from copy import deepcopy

import pytest

from benchmark.evaluators.citation_eval import evaluate, source_errors


def test_empty_is_unknown():
    result = evaluate({})
    assert result["citation_coverage"].value is None
    assert result["citation_coverage"].reason == "no_claims"
    assert result["citation_validity"].value is None
    assert result["citation_validity"].reason == "no_sources"


def test_coverage_and_validity_are_independent(evidence):
    evidence["sources"] = [{}]
    result = evaluate({"pricing": {"evidence": evidence}})
    assert result["citation_coverage"].value == 1
    assert result["citation_validity"].value == 0


def test_missing_evidence_is_in_denominator(evidence):
    result = evaluate(
        {"feature_tree": [{"name": "No description"}], "pricing": {"evidence": evidence}}
    )
    assert result["citation_coverage"].value == 0.5
    assert result["citation_coverage"].denominator == 2


def test_nested_features_personas_and_extensions(profile, evidence):
    profile["feature_tree"][0]["sub_features"] = [{"name": "nested", "description": evidence}]
    profile["user_personas"][0]["satisfaction_signals"] = [evidence]
    profile["extensions"] = {
        "ai_features": evidence,
        "integration_count": 12,
        "nested": {"claim": "Missing sources"},
    }
    result = evaluate(profile, "saas")
    assert result["citation_coverage"].denominator == 11
    assert result["citation_coverage"].numerator == 10
    assert result["citation_validity"].value == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "ftp://example.com"),
        ("url", "not-a-url"),
        ("url", "https://exa mple.com"),
        ("url", None),
        ("title", " "),
        ("snippet", None),
        ("source_type", "invented"),
    ],
)
def test_source_format_validation(evidence, field, value):
    source = deepcopy(evidence["sources"][0])
    source[field] = value
    assert source_errors(source)


def test_invalid_scalar_reference_not_dropped():
    result = evaluate({"pricing": {"evidence": {"sources": ["bad", {}]}}})
    assert result["citation_validity"].denominator == 2
    assert result["citation_validity"].value == 0


def test_no_sources_is_zero_coverage_null_validity():
    result = evaluate({"pricing": {"evidence": {"claim": "x"}}})
    assert result["citation_coverage"].value == 0
    assert result["citation_validity"].value is None


def test_malformed_parent_is_not_silently_discarded():
    result = evaluate({"feature_tree": ["invalid feature"], "pricing": "invalid pricing"})
    assert result["citation_coverage"].denominator == 2
    assert result["citation_coverage"].value == 0
