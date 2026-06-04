"""Tests for QA score adjustment helpers."""

from orchestrator.scoring import iteration_improvement_bonus


def test_iteration_improvement_bonus_rewards_objective_progress():
    previous = {
        "score": 0.50,
        "issues_count": 23,
        "critical_issues": 12,
        "claims_count": 7,
    }

    bonus = iteration_improvement_bonus(
        raw_score=0.47,
        previous_record=previous,
        issues_count=17,
        critical_issues=8,
        current_claims_count=59,
        previous_claims_count=7,
        resolved_fields_count=22,
        regressed_fields_count=16,
    )

    assert bonus > 0
    assert round(0.47 + bonus, 2) > 0.47


def test_iteration_improvement_bonus_does_not_force_pass():
    previous = {
        "score": 0.80,
        "issues_count": 100,
        "critical_issues": 50,
        "claims_count": 0,
    }

    bonus = iteration_improvement_bonus(
        raw_score=0.68,
        previous_record=previous,
        issues_count=1,
        critical_issues=0,
        current_claims_count=200,
        previous_claims_count=0,
        resolved_fields_count=99,
        regressed_fields_count=0,
    )

    assert 0.68 + bonus <= 0.69


def test_iteration_improvement_bonus_requires_previous_record():
    bonus = iteration_improvement_bonus(
        raw_score=0.47,
        previous_record=None,
        issues_count=17,
        critical_issues=8,
        current_claims_count=59,
        previous_claims_count=7,
        resolved_fields_count=22,
        regressed_fields_count=16,
    )

    assert bonus == 0.0
