"""Pipeline运行器 - 包装run_pipeline，注入SSE事件回调

替换orchestrator/nodes.py中的print为事件发布，
让前端能实时看到每个agent的执行状态。
"""

from __future__ import annotations

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
    """Collector节点 - 采集竞品数据，带SSE事件发布"""
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
    message = _make_message(
        to_agent="collector",
        function_name="collect_competitor_data",
        arguments={
            "target": state["competitor_name"],
            "collect_type": "web_scrape",
            "scope": scope,
            "depth": "standard",
            "max_sources": 10,
            "target_urls": state.get("target_urls", []),
            "language": "zh",
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments
    duration = time.time() - start

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "collector", "iteration": iteration, "duration_ms": round(duration * 1000),
    })

    if args.get("error"):
        return {"error": args["error"], "claims": []}

    return {
        "claims": args.get("claims", []),
        "sources_fetched": args.get("sources_fetched", 0),
        "sources_failed": args.get("sources_failed", 0),
        "collect_errors": args.get("errors", []),
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

    try:
        app = build_sse_graph()

        initial_state: GraphState = {
            "competitor_name": competitor_name,
            "collect_scope": dims,
            "target_urls": [],
            "expected_dimensions": dims,
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
