import pytest

from benchmark.gold import content_metrics


@pytest.fixture
def gold():
    return {
        "kind": "formal_gold_slots",
        "status": "frozen",
        "slot_selection_rule": "test",
        "cases": {
            "case-a": {
                "snapshot_bundle": "benchmark/replay_bundles/case-a-c1",
                "slots": [
                    {
                        "slot_id": "case-a-s1",
                        "slot_type": "pricing_fact",
                        "claim_zh": "结论一",
                        "claim_en": "claim one",
                        "quote": "quote one",
                        "url": "https://example.com/a",
                        "content_sha256": "a" * 64,
                    },
                    {
                        "slot_id": "case-a-s2",
                        "slot_type": "feature_scale_fact",
                        "claim_zh": "结论二",
                        "claim_en": "claim two",
                        "quote": "quote two",
                        "url": "https://example.com/b",
                        "content_sha256": "b" * 64,
                    },
                    {
                        "slot_id": "case-a-s3",
                        "slot_type": "missing_dimension",
                        "claim_zh": "快照缺安全认证信息。",
                        "missing_keywords": [{"keyword": "SOC 2", "hits_expected": 0}],
                        "urls_searched": ["https://example.com/a"],
                    },
                ],
            }
        },
    }


def _judgment(slot_id, arm, run_id, verdict):
    return {
        "slot_id": slot_id,
        "arm": arm,
        "run_id": run_id,
        "verdict": verdict,
        "evidence": "报告第 3 段",
        "reason": "原文可对照",
    }


def _judgments(entries):
    return {
        "kind": "formal_gold_output_review",
        "status": "human_reviewed",
        "reviewed_by": "硝酸铜",
        "reviewed_at": "2026-11-10T10:00:00+08:00",
        "judgments": entries,
    }


def test_compute_reports_all_six_metrics_with_numerators(gold):
    judgments = _judgments(
        [
            _judgment("case-a-s1", "multi_agent_qa_fixed", "run-1", "supported"),
            _judgment("case-a-s2", "multi_agent_qa_fixed", "run-1", "partial"),
            _judgment("case-a-s3", "multi_agent_qa_fixed", "run-1", "honest_unknown"),
        ]
    )
    summary = content_metrics.compute(gold, judgments)
    arm = summary["arms"]["multi_agent_qa_fixed"]
    metrics = arm["metrics"]
    assert metrics["gold_coverage"]["numerator"] == 2
    assert metrics["gold_coverage"]["denominator"] == 3
    assert metrics["gold_coverage"]["value"] == pytest.approx(2 / 3)
    assert metrics["full_support_rate"]["value"] == pytest.approx(0.5)
    assert metrics["unsupported_rate"]["value"] == 0.0
    assert metrics["partial_rate"]["value"] == pytest.approx(0.5)
    assert metrics["honest_unknown_rate"]["value"] == 1.0
    assert metrics["missing_rate"]["value"] == 0.0
    assert arm["complete_matrix"] is True
    assert arm["verdict_counts"]["supported"] == 1


def test_compute_scales_denominators_with_judged_runs(gold):
    judgments = _judgments(
        [
            _judgment("case-a-s1", "single_llm", "run-1", "supported"),
            _judgment("case-a-s2", "single_llm", "run-2", "missing"),
            _judgment("case-a-s3", "single_llm", "run-2", "honest_unknown"),
        ]
    )
    summary = content_metrics.compute(gold, judgments)
    arm = summary["arms"]["single_llm"]
    metrics = arm["metrics"]
    assert arm["runs_judged"] == 2
    assert metrics["gold_coverage"]["denominator"] == 6
    assert metrics["honest_unknown_rate"]["denominator"] == 2


def test_compute_zero_denominator_yields_null_value(gold):
    judgments = _judgments(
        [
            _judgment(f"case-a-s{i}", "multi_agent_no_qa", "run-1", "missing")
            for i in (1, 2, 3)
        ]
    )
    summary = content_metrics.compute(gold, judgments)
    metrics = summary["arms"]["multi_agent_no_qa"]["metrics"]
    assert metrics["full_support_rate"]["denominator"] == 0
    assert metrics["full_support_rate"]["value"] is None


def test_compute_keeps_arms_separate(gold):
    judgments = _judgments(
        [
            _judgment("case-a-s1", "multi_agent_qa_fixed", "run-1", "supported"),
            _judgment("case-a-s1", "single_llm", "run-1", "unsupported"),
        ]
    )
    summary = content_metrics.compute(gold, judgments)
    assert summary["arms"]["multi_agent_qa_fixed"]["metrics"]["full_support_rate"]["value"] == 1.0
    assert summary["arms"]["single_llm"]["metrics"]["unsupported_rate"]["value"] == 1.0
    assert summary["arms"]["single_llm"]["complete_matrix"] is False


def test_compute_rejects_honest_unknown_on_truth_slot(gold):
    judgments = _judgments([_judgment("case-a-s1", "single_llm", "run-1", "honest_unknown")])
    with pytest.raises(ValueError, match="missing_dimension"):
        content_metrics.compute(gold, judgments)


def test_compute_rejects_duplicate_slot_arm_run(gold):
    judgments = _judgments(
        [
            _judgment("case-a-s1", "single_llm", "run-1", "supported"),
            _judgment("case-a-s1", "single_llm", "run-1", "partial"),
        ]
    )
    with pytest.raises(ValueError, match="Duplicate judgment"):
        content_metrics.compute(gold, judgments)


def test_compute_rejects_unknown_slot(gold):
    judgments = _judgments([_judgment("nope", "single_llm", "run-1", "supported")])
    with pytest.raises(ValueError, match="Unknown slot_id"):
        content_metrics.compute(gold, judgments)


def test_compute_requires_reviewer_header(gold):
    judgments = _judgments([_judgment("case-a-s1", "single_llm", "run-1", "supported")])
    judgments["reviewed_at"] = "2026-11-10T10:00:00"
    with pytest.raises(ValueError, match="timezone"):
        content_metrics.compute(gold, judgments)
