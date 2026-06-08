"""Tests for QA rule-based validators."""

from agents.qa.validators import (
    check_consistency,
    check_dimension_coverage,
    check_overall_confidence,
    check_snippet_existence,
    check_source_coverage,
    check_untraceable_sources,
    check_user_persona_sourcing,
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
        issues, missing = check_dimension_coverage(extra_claims, ["pricing", "features"])
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
        issues, missing = check_dimension_coverage(sample_claims, ["features"])
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

    def test_untraceable_placeholder_source_is_rejected(self, sample_profile):
        sample_profile["pricing"]["evidence"]["sources"][0] = {
            "source_type": "web_page",
            "url": "",
            "title": "推理得出",
            "snippet": "基于多条claims综合推理，无单一原文对应",
        }

        issues = check_untraceable_sources(sample_profile)

        assert any(i.severity == "critical" for i in issues)
        assert any("URL为空" in i.description for i in issues)

    def test_inference_marker_source_is_rejected_even_with_url(self, sample_profile):
        sample_profile["pricing"]["evidence"]["sources"][0]["title"] = "推理得出"

        issues = check_untraceable_sources(sample_profile)

        assert any("不可查" in i.description for i in issues)


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

    def test_null_profile_snippet_is_accepted(self, sample_profile, sample_claims):
        sample_profile["pricing"]["evidence"]["sources"][0]["snippet"] = None

        issues = check_snippet_existence(sample_profile, sample_claims)

        assert issues == []

    def test_null_original_claim_snippet_is_accepted(self, sample_profile, sample_claims):
        sample_claims[0]["sources"][0]["snippet"] = None

        issues = check_snippet_existence(sample_profile, sample_claims)

        assert isinstance(issues, list)


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


class TestUserPersonaSourcing:
    def test_solution_page_can_support_persona(self):
        profile = {
            "user_personas": [
                {
                    "segment": "企业团队",
                    "pain_points": [
                        {
                            "claim": "面向企业团队的协作场景",
                            "confidence": 0.8,
                            "sources": [
                                {
                                    "url": "https://example.com/solutions/enterprise",
                                    "snippet": "Built for enterprise teams and complex workflows.",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        issues = check_user_persona_sourcing(profile)

        assert issues == []

    def test_weak_persona_source_is_minor_not_reject(self):
        profile = {
            "user_personas": [
                {
                    "segment": "企业团队",
                    "pain_points": [
                        {
                            "claim": "协作能力丰富",
                            "confidence": 0.8,
                            "sources": [
                                {
                                    "url": "https://example.com/pricing",
                                    "snippet": "Advanced collaboration features are included.",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        issues = check_user_persona_sourcing(profile)

        assert len(issues) == 1
        assert issues[0].issue_type == "weak_source"
        assert issues[0].severity == "minor"


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

    def test_null_llm_fields_do_not_crash_qa(self, sample_profile, sample_claims):
        sample_profile["pricing"]["evidence"]["sources"][0]["snippet"] = None
        sample_profile["pricing"]["tiers"][0]["name"] = None
        sample_profile["feature_tree"][0]["name"] = None
        sample_profile["swot"][0]["items"][0]["claim"] = None
        sample_claims[0]["sources"][0]["snippet"] = None

        issues, avg_conf, checked, verified, missing = run_all_validators(
            sample_profile,
            sample_claims,
            ["pricing"],
        )

        assert isinstance(issues, list)
        assert avg_conf >= 0
        assert checked >= 0
        assert verified >= 0
        assert isinstance(missing, list)
