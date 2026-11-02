"""Execution success, QA outcomes, actual rework, latency, and observed API usage."""

from benchmark.models import Metric, TaskRecord


def evaluate(record: TaskRecord) -> dict[str, Metric]:
    state = record.state
    events = record.execution_metadata
    nodes = [e for e in events if e.get("kind") == "node"]
    history = state.get("feedback_history") or []
    if not history:
        for node in nodes:
            history = node.get("state_update", {}).get("feedback_history") or history
    qa_nodes = [e for e in nodes if e.get("agent") == "qa"]
    retries = 0
    waiting_for_rework = False
    for node in nodes:
        if node.get("agent") == "qa":
            waiting_for_rework = node.get("state_update", {}).get("qa_verdict") in (
                "revise",
                "reject",
            )
        elif waiting_for_rework and node.get("agent") in ("collector", "analyst", "writer"):
            retries += 1
            waiting_for_rework = False
    if not nodes and history:
        retries = max(0, len(history) - 1)
    profile = state.get("profile")
    report = state.get("report_markdown")
    success = (
        record.outcome == "completed"
        and not record.error
        and not any(e.get("status") in ("error", "cancelled") for e in nodes)
        and not state.get("error")
        and isinstance(profile, dict)
        and bool(profile)
        and isinstance(report, str)
        and bool(report.strip())
    )
    final_verdict = state.get("qa_verdict")
    if final_verdict is None and history:
        final_verdict = history[-1].get("verdict")
    first = history[0].get("verdict") if history else None
    qa_reason = "qa_disabled" if not record.enable_qa else "qa_not_observed"
    calls = [e for e in events if e.get("kind") == "llm"]
    known = all(
        e.get("input_tokens") is not None and e.get("output_tokens") is not None for e in calls
    )
    known = known and bool(nodes) and record.outcome == "completed"
    input_tokens = sum(e.get("input_tokens") or 0 for e in calls)
    output_tokens = sum(e.get("output_tokens") or 0 for e in calls)
    return {
        "workflow_success": Metric(value=bool(success)),
        "qa_passed": Metric(
            value=final_verdict == "pass"
            if record.enable_qa and final_verdict is not None
            else None,
            reason=qa_reason if not record.enable_qa or final_verdict is None else None,
        ),
        "qa_first_pass": Metric(
            value=first == "pass" if record.enable_qa and first else None,
            reason=qa_reason if not record.enable_qa or not first else None,
        ),
        "qa_iterations": Metric(value=len(qa_nodes) if nodes else len(history)),
        "retry_count": Metric(value=retries),
        "latency": Metric(value=record.latency_seconds, details={"unit": "seconds"}),
        "token_usage": Metric(
            value=input_tokens + output_tokens if known else None,
            reason=None if known else "usage_unknown_or_incomplete",
            details={
                "input_tokens": input_tokens if known else None,
                "output_tokens": output_tokens if known else None,
                "observed_input_tokens": input_tokens,
                "observed_output_tokens": output_tokens,
                "llm_calls": len(calls),
                "scope": "reported_input_plus_output",
            },
        ),
    }
