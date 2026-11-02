"""Thin adapter to the real standalone workflow; no agent or graph implementation."""

from typing import Any

from benchmark.evaluators.coverage_eval import normalize_dimensions
from benchmark.models import BenchmarkCase, RunConfig


def collect_dimensions(case: BenchmarkCase) -> list[str]:
    if case.collect_scope is not None:
        dims = ["user_personas" if d == "persona" else d for d in case.collect_scope]
        if "swot" in dims:
            raise ValueError("SWOT is an analysis output, not a Collector dimension")
        return list(dict.fromkeys(dims))
    requested = normalize_dimensions(case.required_dimensions, case.template)
    mapping = {"feature_tree": "features", "pricing": "pricing", "user_personas": "user_personas"}
    # SWOT requires underlying facts, not raw claims labelled 'swot'.
    if "swot" in requested:
        return ["pricing", "features", "user_personas"]
    return list(dict.fromkeys(mapping[d] for d in requested if d in mapping)) or [
        "pricing",
        "features",
        "user_personas",
    ]


async def run(
    case: BenchmarkCase,
    competitor: str,
    config: RunConfig,
    execution_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    from orchestrator.graph import run_pipeline

    scope = collect_dimensions(case)
    return await run_pipeline(
        competitor_name=competitor,
        collect_scope=scope,
        expected_dimensions=scope,
        target_urls=case.target_urls.get(competitor),
        max_iterations=config.max_iterations,
        enable_qa=config.enable_qa,
        execution_metadata=execution_metadata,
    )
