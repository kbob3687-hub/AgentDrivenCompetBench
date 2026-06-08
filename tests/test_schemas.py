"""Tests for Pydantic schemas and industry templates."""

import pytest

from schemas.competitor import (
    EvidencedClaim,
    SourceReference,
    SourceType,
)
from schemas.extensions import (
    TEMPLATE_REGISTRY,
    get_template_schema,
    list_templates,
    load_template,
)
from schemas.message import AgentMessage, MessageContext, MessageType


class TestEvidencedClaim:
    def test_valid_claim_creation(self):
        claim = EvidencedClaim(
            claim="Notion Pro costs $10/month",
            confidence=0.9,
            reasoning="Extracted from pricing page",
            sources=[
                SourceReference(
                    source_type=SourceType.WEB_PAGE,
                    url="https://notion.so/pricing",
                    title="Pricing",
                    snippet="Pro: $10/month per user",
                    accessed_at="2025-01-01T00:00:00",
                )
            ],
        )
        assert claim.confidence == 0.9
        assert len(claim.sources) == 1

    def test_claim_requires_at_least_one_source(self):
        with pytest.raises(Exception):
            EvidencedClaim(
                claim="No source claim",
                confidence=0.5,
                sources=[],
            )


class TestSourceReference:
    def test_source_type_enum(self):
        assert SourceType.WEB_PAGE.value == "web_page"
        assert SourceType.APP_STORE_REVIEW.value == "app_store_review"
        assert SourceType.OFFICIAL_DOC.value == "official_doc"

    def test_source_reference_creation(self):
        ref = SourceReference(
            source_type=SourceType.TECH_BLOG,
            url="https://blog.example.com/review",
            title="Product Review",
            snippet="Great product with solid features.",
            accessed_at="2025-06-01T12:00:00",
        )
        assert ref.url == "https://blog.example.com/review"


class TestIndustryTemplates:
    def test_three_templates_registered(self):
        assert len(TEMPLATE_REGISTRY) == 3
        assert "saas" in TEMPLATE_REGISTRY
        assert "consumer" in TEMPLATE_REGISTRY
        assert "hardware" in TEMPLATE_REGISTRY

    def test_load_template_saas(self):
        template = load_template("saas")
        assert template.industry == "saas"
        assert len(template.fields) == 10
        required = template.get_required_fields()
        assert len(required) >= 5

    def test_load_template_case_insensitive(self):
        template = load_template("SaaS")
        assert template.industry == "saas"

    def test_load_template_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown industry"):
            load_template("fintech")

    def test_list_templates_returns_all(self):
        templates = list_templates()
        assert len(templates) == 3
        assert all("template_id" in t for t in templates)
        assert all("industry" in t for t in templates)

    def test_get_template_schema(self):
        schema = get_template_schema("hardware")
        assert "fields" in schema
        assert "core_specs" in schema["fields"]
        assert schema["fields"]["core_specs"]["required"] is True

    def test_validate_extensions_missing_fields(self):
        template = load_template("saas")
        missing = template.validate_extensions({})
        required_names = [f.field_name for f in template.get_required_fields()]
        assert set(missing) == set(required_names)

    def test_validate_extensions_all_present(self):
        template = load_template("saas")
        extensions = {f.field_name: "test_value" for f in template.fields}
        missing = template.validate_extensions(extensions)
        assert missing == []


class TestAgentMessage:
    def test_message_creation(self):
        msg = AgentMessage(
            message_id="test-123",
            trace_id="trace-456",
            message_type=MessageType.TASK_ASSIGN,
            from_agent="orchestrator",
            to_agent="collector",
            function_name="collect_competitor_data",
            arguments={"target": "Notion", "scope": ["pricing"]},
            context=MessageContext(
                competitor_name="Notion",
                iteration=1,
                max_iterations=3,
            ),
        )
        assert msg.to_agent == "collector"
        assert msg.context.competitor_name == "Notion"

    def test_message_type_enum(self):
        assert MessageType.TASK_ASSIGN.value == "task_assign"
        assert MessageType.TASK_RESULT.value == "task_result"
        assert MessageType.FEEDBACK.value == "feedback"
