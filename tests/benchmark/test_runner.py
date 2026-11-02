import asyncio
import json

from benchmark import report, runner, workflow
from benchmark.models import BenchmarkCase, RunConfig


def test_all_tasks_summary_counts_unfinished_tasks_as_zero():
    rows = [{"metrics": {"workflow_success": {"value": True}}}]
    summary = report.aggregate_all_tasks(rows, 2)
    assert summary["workflow_success"] == {
        "mean": 0.5,
        "available": 1,
        "missing": 1,
        "tasks": 2,
    }


async def test_runner_splits_competitors_and_saves_failures(tmp_path, monkeypatch, profile):
    calls = []

    async def fake_run(case, competitor, config, execution_metadata):
        calls.append(competitor)
        if competitor == "Broken":
            raise RuntimeError("fixture failure")
        return {
            "profile": profile,
            "report_markdown": "Fixture only",
            "qa_verdict": "revise",
            "final_status": "source_limited",
            "rework_blocked_reason": "no_new_urls_within_target_urls",
            "missing_dimensions": ["pricing"],
        }

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(
        id="fixture", competitors=["Good", "Broken"], required_dimensions=["features", "swot"]
    )
    directory = await runner.run_benchmark([case], RunConfig(), tmp_path)
    assert calls == ["Good", "Broken"]
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    assert manifest["workflow_id"] == "standalone"
    assert manifest["cases"][0]["competitors"] == calls
    assert "models" in manifest and "dirty" in manifest["git"]
    metrics = json.loads((directory / "metrics.json").read_text("utf-8"))
    assert metrics["summary"]["workflow_success"]["mean"] == 0.5
    assert metrics["task_counts"] == {"completed": 1, "error": 1, "timeout": 0, "planned": 2}
    assert metrics["all_tasks_summary"]["workflow_success"]["mean"] == 0.5
    assert metrics["cases"]["fixture"]["task_counts"]["planned"] == 2
    assert metrics["cases"]["fixture"]["all_workflows_succeeded"] is False
    assert len(list((directory / "raw").glob("*.json"))) == 2
    assert (directory / "report.md").exists()
    report = (directory / "report.md").read_text("utf-8")
    assert "final_status: source_limited" in report
    assert "指定的 URL 均已采集" in report
    assert "no_new_urls_within_target_urls" in report
    assert "未补齐维度: pricing" in report
    assert "QA 未通过；当前报告是待补证据的草稿。" in report
    original = (directory / "metrics.json").read_bytes()
    runner.rescore(directory)
    assert (directory / "metrics.json").read_bytes() == original
    assert (directory / "metrics.rescored.json").exists()


async def test_timeout_preserves_attempt_and_continues(tmp_path, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(1)

    monkeypatch.setattr(workflow, "run", slow)
    case = BenchmarkCase(id="timeout", competitors=["A", "B"], required_dimensions=["features"])
    directory = await runner.run_benchmark([case], RunConfig(timeout_seconds=0.01), tmp_path)
    rows = json.loads((directory / "metrics.json").read_text("utf-8"))["tasks"]
    assert len(rows) == 2
    assert all(row["outcome"] == "timeout" for row in rows)
    assert all(row["metrics"]["workflow_success"]["value"] is False for row in rows)


async def test_adapter_calls_real_entry_with_qa_switch(monkeypatch):
    import orchestrator.graph as graph

    observed = {}

    async def pipeline(**kwargs):
        observed.update(kwargs)
        return {}

    monkeypatch.setattr(graph, "run_pipeline", pipeline)
    case = BenchmarkCase(id="test", competitors=["A"], required_dimensions=["swot"])
    await workflow.run(case, "A", RunConfig(enable_qa=False), [])
    assert observed["competitor_name"] == "A"
    assert observed["enable_qa"] is False
    assert "swot" not in observed["expected_dimensions"]


async def test_source_capture_persists_observed_collector_content(tmp_path, monkeypatch, profile):
    from agents.collector.agent import source_fetch_observer
    from agents.collector.tools import FetchResult

    async def fake_run(case, competitor, config, execution_metadata):
        observer = source_fetch_observer.get()
        assert observer is not None
        observer(
            FetchResult(
                url="https://example.com/pricing",
                content="Observed redacted page text",
                title="Pricing",
                fetch_method="direct_http",
            )
        )
        return {"profile": profile, "report_markdown": "Fixture only"}

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(id="capture", competitors=["A"], required_dimensions=["pricing"])
    directory = await runner.run_benchmark([case], RunConfig(capture_sources=True), tmp_path)
    snapshots = directory / "source_snapshots" / "capture-r1-c1"
    index = json.loads((snapshots / "index.json").read_text("utf-8"))
    assert index[0]["capture_kind"] == "collector_fetch_exact_redacted_text"
    assert (snapshots / index[0]["content_path"]).read_text("utf-8") == (
        "Observed redacted page text"
    )
    assert source_fetch_observer.get() is None


async def test_task_concurrency_caps_in_flight_tasks(tmp_path, monkeypatch, profile):
    in_flight = 0
    peak = 0

    async def fake_run(case, competitor, config, execution_metadata):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return {"profile": profile, "report_markdown": "Fixture only"}

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(
        id="conc", competitors=["A", "B", "C", "D"], required_dimensions=["pricing"]
    )
    directory = await runner.run_benchmark([case], RunConfig(task_concurrency=2), tmp_path)
    assert peak == 2
    assert in_flight == 0
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    assert manifest["config"]["task_concurrency"] == 2
    metrics = json.loads((directory / "metrics.json").read_text("utf-8"))
    assert metrics["task_counts"]["planned"] == 4


async def test_default_config_runs_tasks_serially(tmp_path, monkeypatch, profile):
    in_flight = 0
    peak = 0

    async def fake_run(case, competitor, config, execution_metadata):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return {"profile": profile, "report_markdown": "Fixture only"}

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(id="serial", competitors=["A", "B"], required_dimensions=["pricing"])
    await runner.run_benchmark([case], RunConfig(), tmp_path)
    assert peak == 1


async def test_concurrent_metrics_keep_plan_order(tmp_path, monkeypatch, profile):
    async def fake_run(case, competitor, config, execution_metadata):
        # Later competitors finish first, so completion order is the reverse of the plan.
        await asyncio.sleep(0.05 if competitor == "A" else 0.01)
        return {"profile": profile, "report_markdown": "Fixture only"}

    monkeypatch.setattr(workflow, "run", fake_run)
    case = BenchmarkCase(id="order", competitors=["A", "B"], required_dimensions=["pricing"])
    directory = await runner.run_benchmark([case], RunConfig(task_concurrency=2), tmp_path)
    metrics = json.loads((directory / "metrics.json").read_text("utf-8"))
    assert [row["task_id"] for row in metrics["tasks"]] == ["order-r1-c1", "order-r1-c2"]
