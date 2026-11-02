"""Offline A/B facts mining operates only on落盘记录, never调用 LLM."""

from benchmark import mine_ab_facts as mine


def _task(case, repeat, *, verdict="pass", score=0.8, blocked=None, latency=100.0, tokens=None):
    history = []
    if verdict:
        record = {
            "iteration": 1,
            "verdict": verdict,
            "raw_score": score,
            "improvement_bonus": 0.0,
            "issues": [
                {"severity": "critical", "issue_type": "missing_source", "field_path": "swot"}
            ],
            "resolved_fields": [],
            "regressed_fields": [],
            "persisted_fields": [],
        }
        history.append(record)
    llm_events = [
        {"kind": "llm", "input_tokens": tk[0], "output_tokens": tk[1]} for tk in tokens or []
    ]
    return {
        "task_id": f"{case}-r{repeat}",
        "case_id": case,
        "repeat": repeat,
        "latency_seconds": latency,
        "state": {"feedback_history": history, "rework_blocked_reason": blocked},
        "execution_metadata": llm_events,
    }


def _run(tasks, commit):
    metrics_tasks = []
    for t in tasks:
        metrics_tasks.append(
            {
                "case_id": t["case_id"],
                "repeat": t["repeat"],
                "metrics": {
                    "schema_valid": {"value": True},
                    "citation_coverage": {"value": 0.9},
                    "dimension_coverage": {"value": 1.0},
                    "workflow_success": {"value": True},
                    "retry_count": {"value": 0},
                },
            }
        )
    return {
        "dir": "run-x",
        "manifest": {"git": {"commit": commit, "dirty": False}, "config": {"enable_qa": True}},
        "metrics": {"tasks": metrics_tasks},
        "tasks": {t["task_id"]: t for t in tasks},
    }


def test_blocked_rework_is_counted_not_as_effective_fix():
    tasks_a = [
        _task("notion", 1, verdict="pass"),
        _task(
            "notion", 2, verdict="revise", blocked="discovery_found_no_new_urls", tokens=[(10, 5)]
        ),
    ]
    stats = mine._rework_block_reasons({t["task_id"]: t for t in tasks_a})
    assert stats == {"discovery_found_no_new_urls": 1}


def test_token_totals_sum_only_llm_events():
    tasks = [_task("notion", 1, tokens=[(100, 20), (50, 30)]), _task("notion", 2, tokens=[(10, 5)])]
    totals = mine._token_totals({t["task_id"]: t for t in tasks})
    assert totals["input_tokens"] == 160
    assert totals["output_tokens"] == 55
    assert totals["total_tokens"] == 215
    assert totals["llm_calls"] == 3
    assert totals["mean_tokens_per_task"] == 108


def test_same_commit_pairing_and_delta():
    commit = "deadbeef"
    task_a = _task("notion", 1, verdict="pass")
    task_b = _task("notion", 1, verdict="")
    facts = mine.mine(_run([task_a], commit), _run([task_b], commit))
    assert facts["provenance"]["same_commit"] is True
    assert facts["paired_structural_metrics"]["schema_valid"]["paired_repeats"] == 1
    assert facts["paired_structural_metrics"]["schema_valid"]["delta_b_minus_a"] == 0.0


def test_markdown_lists_no_effective_rework_claim():
    commit = "cafe0000"
    facts = mine.mine(
        _run([_task("notion", 1, verdict="pass")], commit),
        _run([_task("notion", 1, verdict="")], commit),
    )
    text = mine.render_markdown(facts)
    assert "不可宣称清单" in text
    assert "同 commit 对比: True" in text
