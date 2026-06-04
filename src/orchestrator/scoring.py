"""QA scoring helpers shared by graph runners."""

from __future__ import annotations

from typing import Any


def iteration_improvement_bonus(
    *,
    raw_score: float,
    previous_record: dict[str, Any] | None,
    issues_count: int,
    critical_issues: int,
    current_claims_count: int,
    previous_claims_count: int,
    resolved_fields_count: int,
    regressed_fields_count: int,
) -> float:
    """Reward real iteration progress without masking poor final quality."""
    if not previous_record:
        return 0.0

    bonus = 0.0
    previous_critical = int(previous_record.get("critical_issues", 0) or 0)
    previous_issues = int(previous_record.get("issues_count", 0) or 0)

    critical_reduced = max(0, previous_critical - critical_issues)
    issues_reduced = max(0, previous_issues - issues_count)
    claims_added = max(0, current_claims_count - previous_claims_count)
    net_resolved = max(0, resolved_fields_count - regressed_fields_count)

    bonus += min(0.03, critical_reduced * 0.01)
    bonus += min(0.02, issues_reduced * 0.002)
    bonus += min(0.02, net_resolved * 0.003)
    bonus += min(0.02, claims_added * 0.001)

    # Progress can be visible, but cannot turn a weak report into a pass.
    max_score = 0.69 if raw_score < 0.70 else 1.0
    return max(0.0, min(0.08, max_score - raw_score, bonus))
