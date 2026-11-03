"""Single-call LLM baseline: same frozen pages in, one profile + report out.

The baseline consumes the exact same replay bundle as the multi-agent arm so
that any difference comes from the workflow, not from the sources. It never
browses, never searches, and never calls more than one LLM per task.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import load_dotenv

from agents.base import AgentConfig, BaseAgent
from benchmark.models import BenchmarkCase, RunConfig, TaskRecord
from benchmark.replay import SnapshotBundle
from schemas.competitor import CompetitorProfile
from schemas.message import AgentMessage, MessageType

PROMPT_TEMPLATE = """下面给出关于某个产品的若干网页快照原文（URL 与标题为头）。

仅依据这些文本完成两件事，并输出**一个** JSON 对象，不要输出其他文字。
外层格式必须是：{{"profile": <竞品画像对象>, "report_markdown": <中文Markdown报告字符串>}}
1. "profile": 符合下方 JSON Schema 的竞品画像对象；快照中没有的信息填 null 或省略，禁止编造。
2. "report_markdown": 一份中文 Markdown 竞品分析报告，关键结论用脚注标注来源 URL。

为在一次回复内输出完整，所有 "reasoning" 字段保持一句话（50 字以内）。

目标产品: {competitor}
需要覆盖的维度: {dimensions}

JSON Schema:
{schema}

网页快照:
{pages}
"""


def build_pages_text(
    bundle: SnapshotBundle, max_chars_per_page: int = 12000
) -> tuple[str, list[str]]:
    """Same per-page budget the multi-agent Collector uses, so inputs stay comparable."""
    parts: list[str] = []
    sent_urls: list[str] = []
    for url in bundle.urls:
        entry = bundle._by_url[url]
        if not entry.get("success"):
            continue
        header = f"### URL: {url}\n标题: {entry.get('title') or ''}\n"
        parts.append(header + entry["_text"][:max_chars_per_page] + "\n\n")
        sent_urls.append(url)
    return "".join(parts), sent_urls


def parse_profile_report(text: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Extract {"profile": ..., "report_markdown": ...} from a model reply."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None, None, "no JSON object in baseline reply"
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        return None, None, f"baseline reply is not valid JSON: {exc}"
    profile = payload.get("profile")
    report = payload.get("report_markdown")
    if not isinstance(profile, dict) and ("company_name" in payload or "product_name" in payload):
        # Tolerate a flattened reply: the payload itself is the profile.
        profile = {k: v for k, v in payload.items() if k not in ("report_markdown", "report")}
    if not isinstance(report, str) or not report.strip():
        report = payload.get("report") if isinstance(payload.get("report"), str) else report
    if not isinstance(profile, dict):
        return None, None, "baseline reply missing 'profile' object"
    if not isinstance(report, str) or not report.strip():
        return None, None, "baseline reply missing 'report_markdown'"
    return profile, report, None


class SingleLLMBaselineAgent(BaseAgent):
    """One LLM call per task; same provider/model family as the Collector."""

    def default_config(self) -> AgentConfig:
        return AgentConfig(
            provider="openai_compat",
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            max_tokens=32768,
            temperature=0.0,
        )

    @property
    def role(self) -> str:
        return "single_llm_baseline"

    @property
    def system_prompt(self) -> str:
        return "你是竞品分析助手。回复只包含一个 JSON 对象。"

    async def run(self, message: AgentMessage) -> AgentMessage:
        schema = json.dumps(CompetitorProfile.model_json_schema(), ensure_ascii=False)
        prompt = PROMPT_TEMPLATE.format(
            competitor=message.arguments["competitor_name"],
            dimensions="、".join(message.arguments["dimensions"]),
            schema=schema,
            pages=message.arguments["pages_text"],
        )
        response = await self.call_llm([{"role": "user", "content": prompt}])
        profile, report, error = parse_profile_report(response.text)
        return self.build_message(
            to_agent="orchestrator",
            function_name="single_llm_result",
            arguments={
                "profile": profile,
                "report_markdown": report,
                "error": error,
                "reply_head": response.text[:600] if error else None,
                "usage": {
                    "input_tokens": response.input_tokens if response.usage_known else None,
                    "output_tokens": response.output_tokens if response.usage_known else None,
                    "usage_known": response.usage_known,
                    "model": response.model,
                },
            },
            trace_id=message.trace_id,
            message_type=MessageType.TASK_RESULT,
            parent_message_id=message.message_id,
            context=message.context,
        )


async def run_case(
    case: BenchmarkCase,
    competitor: str,
    bundle: SnapshotBundle,
    agent: SingleLLMBaselineAgent | None = None,
    *,
    repeat: int = 1,
) -> TaskRecord:
    """Execute one baseline task against a frozen bundle; never touches network."""
    agent = agent or SingleLLMBaselineAgent()
    task_id = f"{case.id}-r{repeat}-single"
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    state: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    outcome = "completed"
    error: str | None = None
    pages_text, sent_urls = build_pages_text(bundle)
    try:
        message = AgentMessage(
            message_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            message_type=MessageType.TASK_ASSIGN,
            from_agent="orchestrator",
            to_agent=agent.role,
            function_name="analyze_from_snapshots",
            arguments={
                "competitor_name": competitor,
                "dimensions": case.required_dimensions,
                "pages_text": pages_text,
                "replay_bundle": str(bundle.directory),
            },
        )
        result = await agent.execute(message)
        args = result.arguments
        events = [
            {
                "kind": "node",
                "agent": agent.role,
                "iteration": 1,
                "status": "completed" if not args.get("error") else "error",
                "state_update": {"profile_present": bool(args.get("profile"))},
            },
            {
                "kind": "llm",
                "agent": agent.role,
                "iteration": 1,
                "status": "completed",
                "input_tokens": (args.get("usage") or {}).get("input_tokens"),
                "output_tokens": (args.get("usage") or {}).get("output_tokens"),
            },
        ]
        if args.get("error"):
            outcome = "error"
            error = args["error"]
            state = {"error": args["error"], "reply_head": args.get("reply_head")}
        else:
            state = {
                "profile": args["profile"],
                "report_markdown": args["report_markdown"],
                "final_status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "replay_bundle": str(bundle.directory),
                "pages_urls": sent_urls,
            }
    except Exception as exc:  # noqa: BLE001 - a failed baseline is still a record
        outcome = "error"
        error = f"{type(exc).__name__}: {exc}"
        state = {"error": error}
    elapsed = perf_counter() - started
    return TaskRecord(
        task_id=task_id,
        case_id=case.id,
        competitor=competitor,
        repeat=repeat,
        enable_qa=False,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        latency_seconds=elapsed,
        outcome=outcome,  # type: ignore[arg-type]
        state=state,
        execution_metadata=events,
        error=error,
    )


async def run_benchmark(
    cases: list[BenchmarkCase],
    config: RunConfig,
    output_root: Path,
) -> Path:
    from benchmark.evaluators import evaluate
    from benchmark.report import build_metrics, render
    from benchmark.runner import load_replay_bundles, manifest_for, write_json

    bundles = load_replay_bundles(cases, config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = output_root / run_id
    (directory / "raw").mkdir(parents=True, exist_ok=False)
    manifest = manifest_for(cases, config, run_id)
    manifest["provenance"] = "replayed_single_llm_baseline"
    manifest["baseline"] = "single_llm_one_call"
    write_json(directory / "manifest.json", manifest)

    records: list[TaskRecord] = []
    case_by_id = {case.id: case for case in cases}
    for repetition in range(1, config.repeat + 1):
        for case in cases:
            for index, competitor in enumerate(case.competitors, 1):
                bundle = bundles[f"{case.id}-c{index}"]
                print(f"[baseline] {case.id}-r{repetition}-c{index}: {competitor}", flush=True)
                record = await run_case(case, competitor, bundle, repeat=repetition)
                write_json(
                    directory / "raw" / f"{record.task_id}.json", record.model_dump(mode="json")
                )
                if record.state.get("report_markdown"):
                    (directory / "raw" / f"{record.task_id}.md").write_text(
                        record.state["report_markdown"], encoding="utf-8"
                    )
                records.append(record)
                metrics = build_metrics(
                    records,
                    cases,
                    [evaluate(r, case_by_id[r.case_id]) for r in records],
                    config.repeat,
                )
                write_json(directory / "metrics.json", metrics)
                (directory / "report.md").write_text(render(manifest, metrics), encoding="utf-8")
                print(f"[baseline] {record.task_id}: {record.outcome}", flush=True)

    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(directory / "manifest.json", manifest)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default="benchmark/cases/cases.json")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument(
        "--replay-root",
        type=Path,
        required=True,
        help="Directory of frozen bundles; pass the identical string as the workflow arm",
    )
    # Defaults mirror benchmark/runner.py so compare.py pairing guards stay satisfied.
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--task-concurrency", type=int, default=1)
    parser.add_argument("--model")
    parser.add_argument("--out-root", type=Path, default="benchmark/results")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=False)
    if args.model:
        os.environ["DEEPSEEK_MODEL"] = args.model

    from benchmark.runner import load_cases

    cases = load_cases(args.cases if args.cases.is_absolute() else root / args.cases)
    if args.case_ids:
        cases = [case for case in cases if case.id in set(args.case_ids)]
        if not cases:
            parser.error("No matching case IDs")
    config = RunConfig(
        enable_qa=False,
        max_iterations=args.max_iterations,
        repeat=args.repeat,
        timeout_seconds=args.timeout,
        task_concurrency=args.task_concurrency,
        replay_root=str(args.replay_root),
    )
    out_root = args.out_root if args.out_root.is_absolute() else root / args.out_root
    print(asyncio.run(run_benchmark(cases, config, out_root)))


if __name__ == "__main__":
    main()
