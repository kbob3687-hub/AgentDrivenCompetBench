"""Pipeline运行器 - 包装run_pipeline，注入SSE事件回调

替换orchestrator/nodes.py中的print为事件发布，
让前端能实时看到每个agent的执行状态。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

from langgraph.graph import END, StateGraph

from agents.analyst.agent import AnalystAgent
from agents.collector.agent import CollectorAgent
from agents.qa.agent import QAAgent
from agents.writer.agent import WriterAgent
from api.events import EventType, SSEEvent, event_bus
from orchestrator.edges import qa_routing
from orchestrator.state import FeedbackRecord, GraphState
from schemas.message import AgentMessage, MessageContext, MessageType


def _make_message(
    to_agent: str,
    function_name: str,
    arguments: dict[str, Any],
    state: GraphState,
) -> AgentMessage:
    iteration = state.get("iteration", 1)
    feedback_history = state.get("feedback_history", [])
    previous_feedback = [
        r.get("feedback_summary", "") for r in feedback_history if r.get("feedback_summary")
    ]
    return AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=state.get("trace_id", str(uuid.uuid4())),
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent=to_agent,
        function_name=function_name,
        arguments=arguments,
        context=MessageContext(
            competitor_name=state.get("competitor_name", ""),
            iteration=iteration,
            max_iterations=state.get("max_iterations", 3),
            previous_feedback=previous_feedback,
        ),
    )


async def _publish(task_id: str, event_type: EventType, data: dict[str, Any]) -> None:
    await event_bus.publish(task_id, SSEEvent(event_type=event_type, data=data))


async def collector_node(state: GraphState) -> dict[str, Any]:
    """Collector节点 - 并行采集竞品数据（fan-out sub-agents），带SSE事件发布"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)
    scope = state.get("collect_scope", ["pricing"])
    missing = state.get("missing_dimensions", [])

    if missing:
        scope = list(set(scope + missing))

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "collector", "iteration": iteration, "scope": scope,
    })
    start = time.time()

    agent = CollectorAgent()

    # 确定 URL 列表
    target = state["competitor_name"]
    target_urls = state.get("target_urls", [])
    urls = target_urls if target_urls else agent._get_default_urls(target, scope)
    urls = urls[:10]

    await _publish(task_id, EventType.LOG, {
        "message": f"Fan-out: 并行采集 {len(urls)} 个数据源", "agent": "collector",
    })

    # Fan-out: 并行 fetch + extract
    semaphore = asyncio.Semaphore(4)
    all_claims: list[dict] = []
    fetch_errors: list[str] = []

    async def process_url(url: str, sub_id: str) -> list[dict]:
        await _publish(task_id, EventType.SUB_AGENT_START, {
            "parent": "collector", "sub_id": sub_id, "url": url, "iteration": iteration,
        })
        sub_start = time.time()

        async with semaphore:
            fetch_result = await agent._fetch_url(url)

            if not fetch_result.success:
                fetch_errors.append(f"{url}: {fetch_result.error}")
                await _publish(task_id, EventType.SUB_AGENT_END, {
                    "parent": "collector", "sub_id": sub_id, "url": url,
                    "iteration": iteration, "success": False,
                    "duration_ms": round((time.time() - sub_start) * 1000),
                    "claims_count": 0,
                })
                return []

            content = agent._truncate_content(fetch_result.content, max_chars=12000)
            extracted = await agent._extract_info(
                competitor_name=target,
                dimensions=scope,
                url=url,
                title=fetch_result.title,
                content=content,
                snapshot_hash=fetch_result.snapshot_hash,
            )

            await _publish(task_id, EventType.SUB_AGENT_END, {
                "parent": "collector", "sub_id": sub_id, "url": url,
                "iteration": iteration, "success": True,
                "claims_count": len(extracted),
                "duration_ms": round((time.time() - sub_start) * 1000),
            })
            return extracted

    tasks = [process_url(url, f"fetch-{i}") for i, url in enumerate(urls)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, list):
            all_claims.extend(r)
        elif isinstance(r, Exception):
            fetch_errors.append(str(r))

    duration = time.time() - start

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "collector", "iteration": iteration, "duration_ms": round(duration * 1000),
    })

    return {
        "claims": all_claims,
        "sources_fetched": len(urls) - len(fetch_errors),
        "sources_failed": len(fetch_errors),
        "collect_errors": fetch_errors,
        "collect_scope": scope,
        "missing_dimensions": [],
    }


async def analyst_node(state: GraphState) -> dict[str, Any]:
    """Analyst节点 - 分析claims生成CompetitorProfile"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)
    claims = state.get("claims", [])

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "analyst", "iteration": iteration, "claims_count": len(claims),
    })
    start = time.time()

    agent = AnalystAgent()

    if not claims:
        await _publish(task_id, EventType.AGENT_END, {
            "agent": "analyst", "iteration": iteration, "duration_ms": 0,
        })
        return {"error": "no claims available for analysis", "profile": {}}

    message = _make_message(
        to_agent="analyst",
        function_name="analyze_competitor",
        arguments={
            "competitor_name": state["competitor_name"],
            "claims": claims,
            "dimensions_requested": state.get("collect_scope", ["pricing", "features"]),
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments
    duration = time.time() - start

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "analyst", "iteration": iteration, "duration_ms": round(duration * 1000),
    })

    if args.get("error"):
        return {"error": args["error"], "profile": {}}

    return {
        "profile": args.get("profile", {}),
        "completeness_score": args.get("completeness_score", 0.0),
        "dimensions_analyzed": args.get("dimensions_analyzed", []),
    }


async def writer_node(state: GraphState) -> dict[str, Any]:
    """Writer节点 - 将profile转为Markdown报告"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "writer", "iteration": iteration,
    })
    start = time.time()

    agent = WriterAgent()
    profile = state.get("profile", {})

    if not profile:
        await _publish(task_id, EventType.AGENT_END, {
            "agent": "writer", "iteration": iteration, "duration_ms": 0,
        })
        return {"error": "no profile available for writing", "report_markdown": ""}

    message = _make_message(
        to_agent="writer",
        function_name="write_report",
        arguments={
            "competitor_name": state["competitor_name"],
            "profile": profile,
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments
    duration = time.time() - start

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "writer", "iteration": iteration, "duration_ms": round(duration * 1000),
    })

    if args.get("error"):
        return {"error": args["error"], "report_markdown": ""}

    return {
        "report_markdown": args.get("report_markdown", ""),
        "report_length": args.get("report_length", 0),
        "footnote_count": args.get("footnote_count", 0),
    }


async def qa_node(state: GraphState) -> dict[str, Any]:
    """QA节点 - 质检profile和报告"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "qa", "iteration": iteration,
    })
    start = time.time()

    agent = QAAgent()
    profile = state.get("profile", {})
    report_markdown = state.get("report_markdown", "")

    if not profile:
        history = list(state.get("feedback_history", []))
        record = FeedbackRecord(
            iteration=iteration,
            verdict="reject",
            score=0.0,
            issues_count=0,
            critical_issues=0,
            action_taken="reject(no profile)",
            feedback_summary="no profile to check",
        )
        history.append(record.model_dump(mode="json"))
        await _publish(task_id, EventType.ITERATION_SUMMARY, record.model_dump(mode="json"))

        duration = time.time() - start
        await _publish(task_id, EventType.AGENT_END, {
            "agent": "qa", "iteration": iteration, "duration_ms": round(duration * 1000),
        })
        await _publish(task_id, EventType.QA_VERDICT, {
            "verdict": "reject", "score": 0.0, "iteration": iteration,
        })

        max_iter = state.get("max_iterations", 3)
        final = {}
        if iteration >= max_iter:
            final = {
                "final_status": "max_iterations_reached(last_verdict=reject)",
                "completed_at": datetime.now().isoformat(),
            }

        return {
            "qa_verdict": "reject",
            "qa_score": 0.0,
            "qa_issues": [],
            "qa_feedback_summary": "no profile to check",
            "feedback_history": history,
            "iteration": iteration + 1,
            **final,
        }

    message = _make_message(
        to_agent="qa",
        function_name="quality_check",
        arguments={
            "competitor_name": state["competitor_name"],
            "profile": profile,
            "report_markdown": report_markdown,
            "original_claims": state.get("claims", []),
            "expected_dimensions": state.get("expected_dimensions", []),
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments
    duration = time.time() - start

    verdict = args.get("verdict", "reject")
    score = args.get("overall_score", 0.0)
    issues_count = args.get("issues_count", 0)
    critical_issues = args.get("critical_issues", 0)
    feedback = args.get("feedback", {})
    summary = feedback.get("summary", "") if isinstance(feedback, dict) else ""
    missing_dims = args.get("missing_dimensions", [])

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "qa", "iteration": iteration, "duration_ms": round(duration * 1000),
    })
    await _publish(task_id, EventType.QA_VERDICT, {
        "verdict": verdict, "score": score, "iteration": iteration,
        "issues_count": issues_count, "missing_dimensions": missing_dims,
    })

    # Build feedback record
    if missing_dims:
        action = f"revise: missing {missing_dims}"
    else:
        action_map = {"reject": "reject", "revise": "revise", "pass": "pass"}
        action = action_map.get(verdict, "unknown")

    record = FeedbackRecord(
        iteration=iteration,
        verdict=verdict,
        score=score,
        issues_count=issues_count,
        critical_issues=critical_issues,
        action_taken=action,
        feedback_summary=summary,
    )

    history = list(state.get("feedback_history", []))
    history.append(record.model_dump(mode="json"))
    await _publish(task_id, EventType.ITERATION_SUMMARY, record.model_dump(mode="json"))

    update: dict[str, Any] = {
        "qa_verdict": verdict,
        "qa_score": score,
        "qa_issues": feedback.get("issues", []) if isinstance(feedback, dict) else [],
        "qa_feedback_summary": summary,
        "feedback_history": history,
        "iteration": iteration + 1,
        "missing_dimensions": missing_dims,
    }

    max_iter = state.get("max_iterations", 3)
    if verdict == "pass":
        update["final_status"] = "completed"
        update["completed_at"] = datetime.now().isoformat()
    elif verdict == "reject":
        update["final_status"] = f"rejected(score={score:.2f})"
        update["completed_at"] = datetime.now().isoformat()
    elif iteration >= max_iter:
        update["final_status"] = f"max_iterations_reached(last_verdict={verdict})"
        update["completed_at"] = datetime.now().isoformat()

    return update


def build_sse_graph() -> Any:
    """Build the LangGraph StateGraph with SSE-enabled nodes."""
    graph = StateGraph(GraphState)

    graph.add_node("collector", collector_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("qa", qa_node)

    graph.add_edge("collector", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "qa")

    graph.add_conditional_edges(
        "qa",
        qa_routing,
        {"end": END, "collector": "collector"},
    )

    graph.set_entry_point("collector")
    return graph.compile()


async def run_analysis(
    task_id: str,
    competitor_name: str,
    dimensions: list[str] | None = None,
    max_iterations: int = 3,
) -> dict[str, Any]:
    """Run the full analysis pipeline with SSE event publishing.

    Args:
        task_id: Unique task identifier (used as trace_id for event routing)
        competitor_name: Name of the competitor to analyze
        dimensions: Analysis dimensions, defaults to ["pricing", "features"]
        max_iterations: Max QA feedback loops

    Returns:
        Final GraphState dict
    """
    dims = dimensions or ["pricing", "features"]

    # expected_dimensions 比初始 collect_scope 更宽，确保 QA 能发现缺失维度触发 revise
    all_dimensions = ["pricing", "features", "integrations"]
    expected = list(set(all_dimensions) | set(dims))
    # 第一轮只采集用户指定的维度（窄范围），QA 会发现缺失并打回
    initial_scope = dims[:2] if len(dims) > 2 else dims[:1]

    try:
        app = build_sse_graph()

        initial_state: GraphState = {
            "competitor_name": competitor_name,
            "collect_scope": initial_scope,
            "target_urls": [],
            "expected_dimensions": expected,
            "iteration": 1,
            "max_iterations": max_iterations,
            "feedback_history": [],
            "missing_dimensions": [],
            "trace_id": task_id,
            "started_at": datetime.now().isoformat(),
            "final_status": "running",
        }

        config = {"recursion_limit": max_iterations * 5}
        final_state = await app.ainvoke(initial_state, config=config)

        if "completed_at" not in final_state:
            final_state["completed_at"] = datetime.now().isoformat()
        if final_state.get("final_status") == "running":
            final_state["final_status"] = "ended"

        await _publish(task_id, EventType.COMPLETE, {
            "final_status": final_state.get("final_status", "ended"),
            "qa_score": final_state.get("qa_score", 0.0),
            "report_markdown": final_state.get("report_markdown", ""),
            "feedback_history": final_state.get("feedback_history", []),
        })

        return final_state

    except Exception as e:
        await _publish(task_id, EventType.ERROR, {"message": str(e)})
        raise
    finally:
        await event_bus.close(task_id)
