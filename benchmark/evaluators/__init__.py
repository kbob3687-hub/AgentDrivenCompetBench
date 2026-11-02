"""Deterministic evaluators operate only on saved workflow outputs."""

from benchmark.evaluators.citation_eval import evaluate as citation_eval
from benchmark.evaluators.coverage_eval import evaluate as coverage_eval
from benchmark.evaluators.depth_eval import evaluate as depth_eval
from benchmark.evaluators.schema_eval import evaluate as schema_eval
from benchmark.evaluators.workflow_eval import evaluate as workflow_eval
from benchmark.models import BenchmarkCase, Metric, TaskRecord


def evaluate(record: TaskRecord, case: BenchmarkCase) -> dict[str, Metric]:
    profile = record.state.get("profile", {})
    return {
        "schema_valid": schema_eval(profile),
        **citation_eval(profile, case.template),
        **depth_eval(profile, case.template),
        "dimension_coverage": coverage_eval(profile, case.required_dimensions, case.template),
        **workflow_eval(record),
        "llm_judge_score": Metric(value=None, reason="disabled_in_v1"),
    }
