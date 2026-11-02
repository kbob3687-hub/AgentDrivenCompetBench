import pytest

from benchmark.models import TaskRecord


@pytest.fixture
def evidence():
    return {
        "claim": "Fixture claim",
        "confidence": 0.8,
        "reasoning": "Fixture only",
        "sources": [
            {
                "source_type": "web_page",
                "url": "https://example.com/test",
                "title": "Fixture",
                "snippet": "Fixture excerpt",
            }
        ],
    }


@pytest.fixture
def profile(evidence):
    return {
        "company_name": "Fixture",
        "product_name": "Fixture",
        "website": "https://example.com",
        "industry": "saas",
        "feature_tree": [{"name": "Feature", "description": evidence}],
        "pricing": {"model_type": "subscription", "evidence": evidence},
        "user_personas": [{"segment": "Teams", "pain_points": [evidence]}],
        "swot": [
            {"category": category, "items": [evidence]}
            for category in ("strength", "weakness", "opportunity", "threat")
        ],
    }


@pytest.fixture
def record(profile):
    return TaskRecord(
        task_id="fixture",
        case_id="fixture",
        competitor="Fixture",
        repeat=1,
        enable_qa=True,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:02Z",
        latency_seconds=2,
        outcome="completed",
        state={
            "profile": profile,
            "report_markdown": "Report",
            "qa_verdict": "reject",
            "final_status": "rejected(score=0.50)",
            "feedback_history": [{"verdict": "reject"}],
        },
    )
