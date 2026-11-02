"""Run real standalone tasks, persist raw artifacts, then evaluate independently."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import load_dotenv

from benchmark import workflow
from benchmark.evaluators import evaluate
from benchmark.evaluators.coverage_eval import normalize_dimensions
from benchmark.gold.live_capture import SourceCapture
from benchmark.models import BenchmarkCase, RunConfig, TaskRecord
from benchmark.replay import SnapshotBundle
from benchmark.report import build_metrics, render

ROOT = Path(__file__).resolve().parent.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    # Artifacts are generated data, never input to the live workflow.
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def git_metadata() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return (
                subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)
                .decode("utf-8")
                .strip()
            )
        except (OSError, subprocess.CalledProcessError):
            return None

    status = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def model_configs() -> dict[str, Any]:
    from agents.analyst.agent import AnalystAgent
    from agents.collector.agent import CollectorAgent
    from agents.qa.agent import QAAgent
    from agents.writer.agent import WriterAgent

    # default_config is pure; no clients, API calls or credential-bearing objects are created.
    return {
        cls.__name__: cls.default_config(None).model_dump(mode="json")
        for cls in (CollectorAgent, AnalystAgent, WriterAgent, QAAgent)
    }


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases = [BenchmarkCase.model_validate(item) for item in json.loads(path.read_text("utf-8"))]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Cases must be nonempty and have unique IDs")
    for case in cases:
        normalize_dimensions(case.required_dimensions, case.template)
        workflow.collect_dimensions(case)
        if set(case.target_urls) - set(case.competitors):
            raise ValueError(f"Unknown competitors in target_urls: {case.id}")
    return cases


def manifest_for(cases: list[BenchmarkCase], config: RunConfig, run_id: str) -> dict[str, Any]:
    from schemas.extensions import load_template

    source_paths = (
        sorted((ROOT / "src").rglob("*.py"))
        + sorted((ROOT / "benchmark").rglob("*.py"))
        + sorted((ROOT / "templates").glob("*.yaml"))
    )
    dependencies = {}
    for package in ("pydantic", "langgraph", "openai", "anthropic", "langfuse", "httpx"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    return {
        "run_id": run_id,
        "workflow_id": "standalone",
        "metric_version": "1.1",
        "provenance": "live_workflow",
        "started_at": now(),
        "completed_at": None,
        "config": config.model_dump(mode="json"),
        "enable_qa": config.enable_qa,
        "cases": [case.model_dump(mode="json") for case in cases],
        "resolved_collect_scope": {case.id: workflow.collect_dimensions(case) for case in cases},
        "templates": {
            case.template: load_template(case.template).model_dump(mode="json")
            for case in cases
            if case.template
        },
        "models": model_configs(),
        "git": git_metadata(),
        "python": sys.version,
        "dependencies": dependencies,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
        "environment": {
            "firecrawl_configured": bool(os.getenv("FIRECRAWL_API_KEY")),
            "enable_jina": os.getenv("ENABLE_JINA", "false"),
            "custom_llm_endpoint": bool(os.getenv("DEEPSEEK_BASE_URL")),
            "proxy_configured": bool(os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")),
        },
    }


def load_replay_bundles(cases: list[BenchmarkCase], config: RunConfig) -> dict[str, SnapshotBundle]:
    """Load one frozen bundle per (case, competitor) and pin target_urls to it.

    Runs fail loudly here if a bundle is missing, and every fetch of an unknown
    URL fails at task time - replay never falls back to the network.
    """
    if not config.replay_root:
        return {}
    root = Path(config.replay_root)
    bundles: dict[str, SnapshotBundle] = {}
    for case in cases:
        for index, competitor in enumerate(case.competitors, 1):
            key = f"{case.id}-c{index}"
            path = root / key
            if not (path / "index.json").exists():
                raise FileNotFoundError(f"Replay bundle missing for {key}: {path}")
            bundle = SnapshotBundle.load(path)
            bundles[key] = bundle
        case.target_urls = {
            competitor: bundles[f"{case.id}-c{index}"].urls
            for index, competitor in enumerate(case.competitors, 1)
        }
    return bundles


async def run_benchmark(
    cases: list[BenchmarkCase],
    config: RunConfig,
    output_root: Path = ROOT / "benchmark" / "results",
) -> Path:
    bundles = load_replay_bundles(cases, config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = output_root / run_id
    (directory / "raw").mkdir(parents=True, exist_ok=False)
    manifest = manifest_for(cases, config, run_id)
    if config.replay_root:
        manifest["provenance"] = "replayed_workflow"
    write_json(directory / "manifest.json", manifest)

    plan = [
        (case, repetition, index, competitor, f"{case.id}-r{repetition}-c{index}")
        for case in cases
        for repetition in range(1, config.repeat + 1)
        for index, competitor in enumerate(case.competitors, 1)
    ]
    order = {task_id: i for i, (_, _, _, _, task_id) in enumerate(plan)}
    case_by_id = {case.id: case for case in cases}
    records: dict[str, TaskRecord] = {}
    semaphore = asyncio.Semaphore(config.task_concurrency)

    async def run_one(
        case: BenchmarkCase, repetition: int, index: int, competitor: str, task_id: str
    ) -> None:
        async with semaphore:
            print(f"[benchmark] {task_id}: {competitor}", flush=True)
            started_at = now()
            started = perf_counter()
            events: list[dict[str, Any]] = []
            state: dict[str, Any] = {}
            outcome = "completed"
            error = None
            capture = None
            observer_token = None
            replay_token = None
            try:
                if config.replay_root:
                    from agents.collector.agent import snapshot_replay_provider

                    replay_token = snapshot_replay_provider.set(
                        bundles[f"{case.id}-c{index}"].fetch
                    )
                if config.capture_sources:
                    from agents.collector.agent import source_fetch_observer

                    capture = SourceCapture(directory / "source_snapshots" / task_id)
                    observer_token = source_fetch_observer.set(capture.observe)
                state = await asyncio.wait_for(
                    workflow.run(case, competitor, config, events), config.timeout_seconds
                )
            except TimeoutError:
                outcome, error = "timeout", f"Task exceeded {config.timeout_seconds} seconds"
            except Exception as exc:
                outcome, error = "error", f"{type(exc).__name__}: {exc}"
            finally:
                if observer_token is not None:
                    source_fetch_observer.reset(observer_token)
                if replay_token is not None:
                    from agents.collector.agent import snapshot_replay_provider

                    snapshot_replay_provider.reset(replay_token)
            elapsed = perf_counter() - started
            # Keep audit records once in the envelope; preserve all returned state fields.
            state = dict(state)
            events = state.pop("execution_metadata", events)
            record = TaskRecord(
                task_id=task_id,
                case_id=case.id,
                competitor=competitor,
                repeat=repetition,
                enable_qa=config.enable_qa,
                started_at=started_at,
                completed_at=now(),
                latency_seconds=elapsed,
                outcome=outcome,
                state=state,
                execution_metadata=events,
                error=error,
            )
            write_json(directory / "raw" / f"{task_id}.json", record.model_dump(mode="json"))
            if state.get("report_markdown"):
                (directory / "raw" / f"{task_id}.md").write_text(
                    state["report_markdown"], encoding="utf-8"
                )
            records[task_id] = record
            ordered = [records[t] for t in sorted(records, key=lambda x: order[x])]
            evaluated = [evaluate(r, case_by_id[r.case_id]) for r in ordered]
            metrics = build_metrics(ordered, cases, evaluated, config.repeat)
            write_json(directory / "metrics.json", metrics)
            (directory / "report.md").write_text(render(manifest, metrics), encoding="utf-8")
            print(f"[benchmark] {task_id}: {outcome}, {elapsed:.1f}s", flush=True)

    await asyncio.gather(
        *(
            run_one(case, repetition, index, competitor, task_id)
            for case, repetition, index, competitor, task_id in plan
        )
    )
    manifest["completed_at"] = now()
    write_json(directory / "manifest.json", manifest)
    return directory


def rescore(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    if manifest.get("provenance") not in ("live_workflow", "replayed_workflow") or (
        manifest.get("workflow_id") != "standalone"
    ):
        raise ValueError("Only saved standalone workflow runs can be rescored")
    cases = [BenchmarkCase.model_validate(case) for case in manifest["cases"]]
    by_id = {case.id: case for case in cases}
    records = [
        TaskRecord.model_validate_json(path.read_text("utf-8"))
        for path in sorted((directory / "raw").glob("*.json"))
    ]
    if not records:
        raise ValueError("No raw records")
    metrics = build_metrics(
        records,
        cases,
        [evaluate(r, by_id[r.case_id]) for r in records],
        manifest["config"].get("repeat"),
    )
    metrics["reevaluation"] = {
        "evaluated_at": now(),
        "git": git_metadata(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in (ROOT / "benchmark", ROOT / "src/schemas")
            for path in sorted(folder.rglob("*.py"))
        },
    }
    # Keep original results and manifest immutable during reevaluation.
    write_json(directory / "metrics.rescored.json", metrics)
    (directory / "report.rescored.md").write_text(render(manifest, metrics), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmark/cases/cases.json")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--enable-qa", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument(
        "--task-concurrency",
        type=int,
        default=1,
        help="Run at most N tasks in parallel (1 = serial, safest for endpoint limits)",
    )
    parser.add_argument(
        "--capture-sources", action="store_true", help="Save exact Collector source text"
    )
    parser.add_argument(
        "--replay-root",
        type=Path,
        help="Directory of frozen bundles <case_id>-c<index>/; no live fetches",
    )
    parser.add_argument("--model", help="Set DEEPSEEK_MODEL for this process before agent creation")
    parser.add_argument("--rescore", type=Path)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    if args.rescore:
        rescore(args.rescore.resolve())
        print(f"Rescored: {args.rescore}")
        return
    if args.model:
        os.environ["DEEPSEEK_MODEL"] = args.model
    cases = load_cases(args.cases)
    if args.case_ids:
        unknown = set(args.case_ids) - {case.id for case in cases}
        if unknown:
            parser.error(f"Unknown case IDs: {sorted(unknown)}")
        cases = [case for case in cases if case.id in args.case_ids]
    config = RunConfig(
        enable_qa=args.enable_qa,
        max_iterations=args.max_iterations,
        repeat=args.repeat,
        timeout_seconds=args.timeout,
        capture_sources=args.capture_sources,
        task_concurrency=args.task_concurrency,
        replay_root=str(args.replay_root) if args.replay_root else None,
    )
    print(asyncio.run(run_benchmark(cases, config)))


if __name__ == "__main__":
    main()
