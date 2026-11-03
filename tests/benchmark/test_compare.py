import json

import pytest

from benchmark import compare, runner, workflow
from benchmark.models import BenchmarkCase, RunConfig


async def make_run(tmp_path, name, monkeypatch, profile, enable_qa):
    async def fake_run(case, competitor, config, execution_metadata):
        return {"profile": profile, "report_markdown": "Fixture only"}

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(id="pair", competitors=["A"], required_dimensions=["features"])
    return await runner.run_benchmark(
        [case], RunConfig(enable_qa=enable_qa, capture_sources=True), tmp_path / name
    )


async def test_compare_pairs_tasks_and_reports_deltas(tmp_path, monkeypatch, profile):
    run_a = await make_run(tmp_path, "a", monkeypatch, profile, True)
    empty = {}

    async def broken_run(case, competitor, config, execution_metadata):
        return {"profile": empty, "report_markdown": ""}

    monkeypatch.setattr(workflow, "run", broken_run)
    case = BenchmarkCase(id="pair", competitors=["A"], required_dimensions=["features"])
    run_b = await runner.run_benchmark(
        [case], RunConfig(enable_qa=False, capture_sources=True), tmp_path / "b"
    )
    manifest_a, metrics_a = compare.load_run(run_a)
    manifest_b, metrics_b = compare.load_run(run_b)
    compare.assert_comparable(manifest_a, manifest_b)
    result = compare.compare(manifest_a, metrics_a, manifest_b, metrics_b)
    assert result["paired_tasks"] == 1
    assert result["metrics"]["workflow_success"]["mean_delta_b_minus_a"] == -1
    assert result["all_tasks_summary"]["a"]["workflow_success"]["mean"] == 1
    assert result["all_tasks_summary"]["b"]["workflow_success"]["mean"] == 0
    markdown = compare.render(manifest_a, manifest_b, result)
    assert "配对任务数: 1" in markdown
    assert "全任务质量口径" in markdown


async def test_compare_requires_source_snapshots(tmp_path, monkeypatch, profile):
    run = await make_run(tmp_path, "a", monkeypatch, profile, True)
    import shutil

    shutil.rmtree(run / "source_snapshots")
    with pytest.raises(ValueError, match="source_snapshots"):
        compare.require_source_snapshots(run)


def test_assert_comparable_rejects_config_drift():
    manifest = {
        "cases": [{"id": "a"}],
        "models": {"CollectorAgent": {}},
        "git": {"commit": "abc"},
        "config": {"repeat": 3, "workflow_id": "standalone"},
    }
    drifted = json.loads(json.dumps(manifest))
    drifted["config"]["repeat"] = 5
    with pytest.raises(ValueError, match="repeat"):
        compare.assert_comparable(manifest, drifted)
