"""Tests for QA rule-based validators."""

import pytest

from agents.qa.validators import (
    check_consistency,
    check_dimension_coverage,
    check_overall_confidence,
    check_snippet_existence,
    check_source_coverage,
    run_all_validators,
)


class TestDimensionCoverage:
    def test_all_dimensions_covered(self, sample_claims):
        # "integrations" has 2 claims in fixture, which is < 3 threshold
        # Only test dimensions that have >= 3 claims
        # Add extra claims to meet threshold
        extra_claims = [
            {"claim": f"pricing claim {i}", "dimension": "pricing", "sources": [{"snippet": "x"}]}
            for i in range(3)
        ] + [
            {"claim": f"features claim {i}", "dimension": "features", "sources": [{"snippet": "x"}]}
            for i in range(3)
        ]
        issues, missing = check_dimension_coverage(
            extra_claims, ["pricing", "features"]
        )
        assert missing == []
        assert len(issues) == 0

    def test_missing_dimension_detected(self, sample_claims):
        issues, missing = check_dimension_coverage(
            sample_claims, ["pricing", "features", "ai_features"]
        )
        assert "ai_features" in missing
        assert any(i.severity == "critical" for i in issues)

    def test_shallow_dimension_triggers_supplement(self, sample_claims):
        # "features" has only 1 claim, threshold is 3
        issues, missing = check_dimension_coverage(
            sample_claims, ["features"]
        )
        assert "features" in missing
        assert any("不充分" in i.description for i in issues)

    def test_empty_expected_dimensions(self, sample_claims):
        issues, missing = check_dimension_coverage(sample_claims, [])
        assert issues == []
        assert missing == []


class TestSourceCoverage:
    def test_profile_with_sources_passes(self, sample_profile):
        issues = check_source_coverage(sample_profile)
        assert len(issues) == 0

    def test_missing_pricing_source(self, sample_profile):
        sample_profile["pricing"]["evidence"]["sources"] = []
        issues = check_source_coverage(sample_profile)
        assert any("定价" in i.description for i in issues)

    def test_missing_feature_source(self, sample_profile):
        sample_profile["feature_tree"][0]["description"]["sources"] = []
        issues = check_source_coverage(sample_profile)
        assert any("功能" in i.description or "实时协作" in i.description for i in issues)


class TestSnippetExistence:
    def test_valid_snippets_pass(self, sample_profile, sample_claims):
        issues = check_snippet_existence(sample_profile, sample_claims)
        assert len(issues) == 0

    def test_fabricated_snippet_detected(self, sample_profile, sample_claims):
        sample_profile["pricing"]["evidence"]["sources"][0]["snippet"] = (
            "This is a completely fabricated snippet that does not exist anywhere"
        )
        issues = check_snippet_existence(sample_profile, sample_claims)
        assert len(issues) > 0
        assert any(i.issue_type == "factual_error" for i in issues)


class TestConsistency:
    def test_no_issues_on_clean_profile(self, sample_profile):
        issues = check_consistency(sample_profile)
        # Minor keyword overlap is acceptable
        assert all(i.severity != "major" for i in issues)

    def test_duplicate_tier_name_detected(self, sample_profile):
        sample_profile["pricing"]["tiers"].append(
            {"name": "Free", "price": "$0", "features": ["重复"]}
        )
        issues = check_consistency(sample_profile)
        assert any("重复" in i.description for i in issues)

    def test_empty_price_detected(self, sample_profile):
        sample_profile["pricing"]["tiers"][0]["price"] = ""
        issues = check_consistency(sample_profile)
        assert any("缺少价格" in i.description for i in issues)


class TestOverallConfidence:
    def test_high_confidence_passes(self, sample_profile):
        avg, issues = check_overall_confidence(sample_profile)
        assert avg >= 0.75
        assert len(issues) == 0

    def test_low_confidence_triggers_issue(self, sample_profile):
        sample_profile["pricing"]["evidence"]["confidence"] = 0.3
        sample_profile["feature_tree"][0]["description"]["confidence"] = 0.4
        sample_profile["swot"][0]["items"][0]["confidence"] = 0.3
        sample_profile["swot"][1]["items"][0]["confidence"] = 0.3
        avg, issues = check_overall_confidence(sample_profile)
        assert avg < 0.75
        assert any(i.severity == "critical" for i in issues)


class TestRunAllValidators:
    def test_returns_five_tuple(self, sample_profile, sample_claims):
        result = run_all_validators(
            sample_profile, sample_claims, ["pricing", "features", "integrations"]
        )
        assert len(result) == 5
        issues, avg_conf, checked, verified, missing = result
        assert isinstance(issues, list)
        assert isinstance(avg_conf, float)
        assert checked >= 0
        assert verified >= 0
        assert isinstance(missing, list)
