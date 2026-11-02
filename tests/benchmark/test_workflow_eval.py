from benchmark.evaluators.workflow_eval import evaluate


def test_reject_is_execution_success(record):
    metrics = evaluate(record)
    assert metrics["workflow_success"].value is True
    assert metrics["qa_passed"].value is False
    assert metrics["retry_count"].value == 0
    assert metrics["qa_iterations"].value == 1


def test_source_limited_revise_keeps_execution_success_without_retry(record):
    record.state["final_status"] = "source_limited"
    record.state["qa_verdict"] = "revise"
    record.state["rework_blocked_reason"] = "no_new_urls_within_target_urls"
    record.execution_metadata = [
        {
            "kind": "node",
            "agent": "qa",
            "status": "completed",
            "state_update": {"qa_verdict": "revise"},
        },
        {"kind": "node", "agent": "discovery", "status": "completed"},
    ]

    metrics = evaluate(record)
    assert metrics["workflow_success"].value is True
    assert metrics["qa_passed"].value is False
    assert metrics["qa_iterations"].value == 1
    assert metrics["retry_count"].value == 0


def test_revise_then_pass(record):
    record.state["feedback_history"] = [{"verdict": "revise"}, {"verdict": "pass"}]
    record.state["qa_verdict"] = "pass"
    metrics = evaluate(record)
    assert metrics["qa_first_pass"].value is False
    assert metrics["qa_passed"].value is True
    assert metrics["retry_count"].value == 1


def test_timeout_and_error_fail_even_with_profile(record):
    record.outcome = "timeout"
    assert evaluate(record)["workflow_success"].value is False
    record.outcome = "completed"
    record.state["error"] = "internal code error"
    assert evaluate(record)["workflow_success"].value is False


def test_no_qa_is_not_fake_pass(record):
    record.enable_qa = False
    record.state.pop("qa_verdict")
    record.state["feedback_history"] = []
    result = evaluate(record)
    assert result["workflow_success"].value is True
    assert result["qa_passed"].value is None
    assert result["qa_first_pass"].reason == "qa_disabled"
    assert result["qa_iterations"].value == result["retry_count"].value == 0


def test_retry_counts_started_rework_on_later_failure(record):
    record.outcome = "error"
    record.execution_metadata = [
        {"kind": "node", "agent": "qa", "state_update": {"qa_verdict": "revise"}},
        {"kind": "node", "agent": "analyst", "status": "error"},
    ]
    assert evaluate(record)["retry_count"].value == 1


def test_token_unknown_not_zero_and_known_calls_sum(record):
    assert evaluate(record)["token_usage"].value is None
    record.execution_metadata = [
        {"kind": "node", "agent": "writer", "status": "completed"},
        {"kind": "llm", "input_tokens": 12, "output_tokens": 3},
        {"kind": "llm", "input_tokens": 5, "output_tokens": 2},
    ]
    assert evaluate(record)["token_usage"].value == 22
    record.execution_metadata[-1]["input_tokens"] = None
    result = evaluate(record)["token_usage"]
    assert result.value is None
    assert result.details["observed_input_tokens"] == 12


def test_empty_report_fails(record):
    record.state["report_markdown"] = " "
    assert evaluate(record)["workflow_success"].value is False


def test_first_pass_true(record):
    record.state["qa_verdict"] = "pass"
    record.state["feedback_history"] = [{"verdict": "pass"}]
    result = evaluate(record)
    assert result["qa_first_pass"].value is True
    assert result["retry_count"].value == 0
