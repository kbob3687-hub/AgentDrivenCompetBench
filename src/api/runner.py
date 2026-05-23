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

# Per-task trace accumulator (avoids LangGraph state propagation issues)
_task_traces: dict[str, list[dict[str, Any]]] = {}

# Per-task HITL gate: when QA says revise, pipeline waits here until human decides
_hitl_gates: dict[str, asyncio.Event] = {}
_hitl_decisions: dict[str, str] = {}  # task_id -> "continue" | "force_pass" | "abort"


def hitl_resume(task_id: str, decision: str) -> None:
    """Called by intervene API to unblock a paused pipeline."""
    _hitl_decisions[task_id] = decision
    gate = _hitl_gates.get(task_id)
    if gate:
        gate.set()


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


def _build_trace_entry(
    agent: str,
    iteration: int,
    duration_ms: int,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    prompt_preview: str = "",
    output_preview: str = "",
) -> dict[str, Any]:
    return {
        "agent": agent,
        "iteration": iteration,
        "duration_ms": duration_ms,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "prompt_preview": prompt_preview[:200],
        "output_preview": output_preview[:300],
        "timestamp": datetime.now().isoformat(),
    }


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

    # 行业模板扩展字段注入采集指令
    industry_fields = state.get("industry_fields", [])
    extra_scope_hint = ""
    if industry_fields:
        extra_scope_hint = f" (行业扩展字段: {', '.join(industry_fields[:5])})"

    await _publish(task_id, EventType.LOG, {
        "message": f"Fan-out: 并行采集 {len(urls)} 个数据源{extra_scope_hint}", "agent": "collector",
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
                industry_fields=industry_fields,
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

    _task_traces.setdefault(task_id, []).append(_build_trace_entry(
        agent="collector",
        iteration=iteration,
        duration_ms=round(duration * 1000),
        model=agent.config.model,
        input_tokens=len(all_claims) * 800,
        output_tokens=len(all_claims) * 200,
        prompt_preview=f"采集 {target} 的 {scope} 维度数据，共 {len(urls)} 个URL",
        output_preview=f"提取 {len(all_claims)} 条claims，失败 {len(fetch_errors)} 个源",
    ))

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
            "industry_fields": state.get("industry_fields", []),
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

    _task_traces.setdefault(task_id, []).append(_build_trace_entry(
        agent="analyst",
        iteration=iteration,
        duration_ms=round(duration * 1000),
        model=agent.config.model,
        input_tokens=len(str(claims)) // 4,
        output_tokens=len(str(args.get("profile", {}))) // 4,
        prompt_preview=f"分析 {len(claims)} 条claims，维度: {state.get('collect_scope', [])}",
        output_preview=f"生成 CompetitorProfile，完整度 {args.get('completeness_score', 0):.0%}",
    ))

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

    _task_traces.setdefault(task_id, []).append(_build_trace_entry(
        agent="writer",
        iteration=iteration,
        duration_ms=round(duration * 1000),
        model=agent.config.model,
        input_tokens=len(str(state.get("profile", {}))) // 4,
        output_tokens=len(args.get("report_markdown", "")) // 4,
        prompt_preview=f"将 {state['competitor_name']} 的 profile 转为 Markdown 报告",
        output_preview=f"生成报告 {args.get('report_length', 0)} 字，{args.get('footnote_count', 0)} 个脚注",
    ))

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
            "industry": state.get("industry", ""),
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

    _task_traces.setdefault(task_id, []).append(_build_trace_entry(
        agent="qa",
        iteration=iteration,
        duration_ms=round(duration * 1000),
        model=agent.config.model,
        input_tokens=len(str(profile)) // 4 + len(report_markdown) // 4,
        output_tokens=500,
        prompt_preview=f"质检 {state['competitor_name']} profile + 报告，期望维度: {state.get('expected_dimensions', [])}",
        output_preview=f"verdict={verdict}, score={score:.2f}, issues={issues_count}, missing={missing_dims}",
    ))

    max_iter = state.get("max_iterations", 3)
    if verdict == "pass":
        # HITL: pause for human confirmation before completing
        await _publish(task_id, EventType.HITL_PAUSE, {
            "iteration": iteration,
            "score": score,
            "verdict": verdict,
            "missing_dimensions": [],
            "message": f"QA通过(score={score:.2f})，等待人工确认发布...",
        })
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        decision = _hitl_decisions.pop(task_id, "force_pass")
        await _publish(task_id, EventType.HITL_RESUME, {
            "decision": decision, "iteration": iteration,
        })

        if decision == "abort":
            update["qa_verdict"] = "reject"
            update["final_status"] = "human_abort"
        elif decision == "continue":
            # 人工要求重跑
            update["final_status"] = "running"
            update.pop("iteration", None)
            update["iteration"] = iteration + 1
        else:
            update["final_status"] = "completed"
        update["completed_at"] = datetime.now().isoformat()

    elif verdict == "reject":
        update["final_status"] = f"rejected(score={score:.2f})"
        update["completed_at"] = datetime.now().isoformat()
    elif iteration >= max_iter:
        update["final_status"] = f"max_iterations_reached(last_verdict={verdict})"
        update["completed_at"] = datetime.now().isoformat()
    elif verdict == "revise":
        # HITL: pause and wait for human decision
        await _publish(task_id, EventType.HITL_PAUSE, {
            "iteration": iteration,
            "score": score,
            "verdict": verdict,
            "missing_dimensions": missing_dims,
            "message": "QA打回，等待人工审核决策...",
        })
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        decision = _hitl_decisions.pop(task_id, "continue")
        await _publish(task_id, EventType.HITL_RESUME, {
            "decision": decision, "iteration": iteration,
        })

        if decision == "force_pass":
            update["qa_verdict"] = "pass"
            update["final_status"] = "human_force_pass"
            update["completed_at"] = datetime.now().isoformat()
        elif decision == "abort":
            update["qa_verdict"] = "reject"
            update["final_status"] = "human_abort"
            update["completed_at"] = datetime.now().isoformat()
        # else "continue" → pipeline proceeds to collector as normal

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
    industry: str = "saas",
    max_iterations: int = 3,
    target_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full analysis pipeline with SSE event publishing.

    Args:
        task_id: Unique task identifier (used as trace_id for event routing)
        competitor_name: Name of the competitor to analyze
        dimensions: Analysis dimensions, defaults to ["pricing", "features"]
        industry: Industry template to apply (saas/consumer/hardware)
        max_iterations: Max QA feedback loops

    Returns:
        Final GraphState dict
    """
    from schemas.extensions import load_template, TEMPLATE_REGISTRY

    dims = dimensions or ["pricing", "features"]

    # Load industry template and inject extra dimensions
    industry_fields: list[str] = []
    if industry in TEMPLATE_REGISTRY:
        template = load_template(industry)
        industry_fields = template.get_field_names()
        await _publish(task_id, EventType.LOG, {
            "message": f"已加载行业模板: {template.display_name} ({len(template.fields)}个扩展字段)",
            "agent": "collector",
        })

    # expected_dimensions 包含完整维度集，确保 QA 能检查覆盖度
    all_dimensions = ["pricing", "features", "integrations"]
    expected = list(set(all_dimensions) | set(dims))

    try:
        app = build_sse_graph()

        initial_state: GraphState = {
            "competitor_name": competitor_name,
            "collect_scope": dims,
            "target_urls": target_urls or [],
            "expected_dimensions": expected,
            "industry": industry,
            "industry_fields": industry_fields,
            "iteration": 1,
            "max_iterations": max_iterations,
            "feedback_history": [],
            "missing_dimensions": [],
            "trace_id": task_id,
            "started_at": datetime.now().isoformat(),
            "final_status": "running",
            "agent_traces": [],
        }

        _task_traces[task_id] = []
        config = {"recursion_limit": max_iterations * 5}
        final_state = await app.ainvoke(initial_state, config=config)

        if "completed_at" not in final_state:
            final_state["completed_at"] = datetime.now().isoformat()
        if final_state.get("final_status") == "running":
            final_state["final_status"] = "ended"

        traces = _task_traces.pop(task_id, [])
        final_state["agent_traces"] = traces

        await _publish(task_id, EventType.COMPLETE, {
            "final_status": final_state.get("final_status", "ended"),
            "qa_score": final_state.get("qa_score", 0.0),
            "report_markdown": final_state.get("report_markdown", ""),
            "feedback_history": final_state.get("feedback_history", []),
            "agent_traces": traces,
            "trace_id": task_id,
        })

        return final_state

    except Exception as e:
        await _publish(task_id, EventType.ERROR, {"message": str(e)})
        raise
    finally:
        _task_traces.pop(task_id, None)
        await event_bus.close(task_id)
