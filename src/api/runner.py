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
from agents.discovery.agent import DiscoveryAgent
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


async def discovery_node(state: GraphState) -> dict[str, Any]:
    """Discovery节点 - URL发现与路由（Warm/Cold Path），带SSE事件发布"""
    task_id = state.get("trace_id", "")
    target = state["competitor_name"]
    scope = state.get("collect_scope", ["pricing", "features"])
    target_urls = state.get("target_urls", [])

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "discovery", "iteration": 1,
    })
    start = time.time()

    # 如果用户指定了URL，跳过discovery
    if target_urls:
        await _publish(task_id, EventType.LOG, {
            "message": f"用户指定了 {len(target_urls)} 个URL，跳过自动发现",
            "agent": "discovery",
        })
        duration = time.time() - start
        await _publish(task_id, EventType.AGENT_END, {
            "agent": "discovery", "iteration": 1, "duration_ms": round(duration * 1000),
        })
        return {
            "discovered_urls": target_urls,
            "discovery_path": "user_specified",
            "discovery_domain": "",
            "discovery_queries": [],
        }

    agent = DiscoveryAgent()
    strategy = state.get("discovery_strategy", "official_only")
    trusted_domains = state.get("trusted_domains", [])

    # QA 自适应降级：上一轮 QA 建议切换策略
    suggested = state.get("suggested_strategy", "")
    if suggested and suggested != strategy:
        await _publish(task_id, EventType.LOG, {
            "message": f"QA 反馈触发策略切换: {strategy} → {suggested}",
            "agent": "discovery",
        })
        strategy = suggested

    result = await agent.discover(target, scope, strategy=strategy, trusted_domains=trusted_domains)

    path = result["path"]
    urls = result["urls"]
    domain = result.get("domain", "")
    duration = time.time() - start

    await _publish(task_id, EventType.LOG, {
        "message": f"Discovery [{path}]: 发现 {len(urls)} 个URL (domain: {domain})",
        "agent": "discovery",
    })
    await _publish(task_id, EventType.AGENT_END, {
        "agent": "discovery", "iteration": 1, "duration_ms": round(duration * 1000),
    })

    _task_traces.setdefault(task_id, []).append(_build_trace_entry(
        agent="discovery",
        iteration=1,
        duration_ms=round(duration * 1000),
        model="none (logic + search API)",
        prompt_preview=f"发现 {target} 的数据源，scope: {scope}, strategy: {strategy}",
        output_preview=f"path={path}, domain={domain}, urls={len(urls)}",
    ))

    return {
        "discovered_urls": urls,
        "discovery_path": path,
        "discovery_domain": domain,
        "discovery_queries": result.get("search_queries", []),
        "discovery_strategy": strategy,
        "suggested_strategy": "",
    }


async def collector_node(state: GraphState) -> dict[str, Any]:
    """Collector节点 - 并行采集竞品数据（fan-out sub-agents），带SSE事件发布"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)
    scope = state.get("collect_scope", ["pricing"])
    missing = state.get("missing_dimensions", [])
    suggested = state.get("suggested_strategy", "")

    if missing:
        scope = list(set(scope + missing))

    await _publish(task_id, EventType.AGENT_START, {
        "agent": "collector", "iteration": iteration, "scope": scope,
    })
    start = time.time()

    agent = CollectorAgent()

    # 使用 Discovery 节点已发现的 URL（首轮），或补采时重新发现
    target = state["competitor_name"]
    discovered = state.get("discovered_urls", [])
    new_strategy = state.get("discovery_strategy", "official_only")

    # QA 自适应降级：上一轮建议切换策略 → 重跑 Discovery 拿新数据源
    if suggested and suggested != new_strategy and not state.get("target_urls"):
        await _publish(task_id, EventType.LOG, {
            "message": f"QA 反馈触发策略降级: {new_strategy} → {suggested}，重新发现数据源",
            "agent": "collector",
        })
        new_strategy = suggested
        rediscover = DiscoveryAgent()
        rediscover_result = await rediscover.discover(
            target, scope,
            strategy=new_strategy,
            trusted_domains=state.get("trusted_domains", []),
        )
        urls = rediscover_result["urls"][:10]
        await _publish(task_id, EventType.LOG, {
            "message": f"新数据源 [{rediscover_result['path']}]: {len(urls)} 个URL",
            "agent": "collector",
        })
    elif discovered and not missing:
        urls = discovered[:10]
    else:
        # QA打回补采时，对缺失维度重新生成URL
        urls = agent._get_default_urls(target, scope)[:10]

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
                if fetch_result.robots_status == "disallowed":
                    await _publish(task_id, EventType.LOG, {
                        "message": f"⛔ robots.txt 禁止抓取: {url}（已跳过）",
                        "agent": "collector",
                    })
                await _publish(task_id, EventType.SUB_AGENT_END, {
                    "parent": "collector", "sub_id": sub_id, "url": url,
                    "iteration": iteration, "success": False,
                    "duration_ms": round((time.time() - sub_start) * 1000),
                    "claims_count": 0,
                })
                return []

            if fetch_result.pii_redactions:
                redact_summary = "、".join(
                    f"{k.strip('[]')}×{v}" for k, v in fetch_result.pii_redactions.items()
                )
                await _publish(task_id, EventType.LOG, {
                    "message": f"🔒 PII 脱敏: {url} 已掩码 {redact_summary}",
                    "agent": "collector",
                })

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
        "discovered_urls": urls,
        "discovery_strategy": new_strategy,
        "suggested_strategy": "",  # 消费完清空
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
            "industry": state.get("industry", ""),
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
        print(f"  [Analyst][iter={iteration}] ERROR: {args.get('error')}")
        if args.get("raw_output"):
            print(f"  [Analyst] raw_output[:500]: {args['raw_output'][:500]}")
        return {"error": args["error"], "profile": {}}

    # Debug: 检查 profile 是否为空
    profile_data = args.get("profile", {})
    if not profile_data or not profile_data.get("company_name"):
        print(f"  [Analyst][iter={iteration}] WARNING: profile is empty or incomplete")
        print(f"  [Analyst] args keys: {list(args.keys())}")
        print(f"  [Analyst] profile keys: {list(profile_data.keys()) if profile_data else 'None'}")
        # 尝试返回部分数据
        if not profile_data:
            return {"error": "analyst returned empty profile", "profile": {}}

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
            "discovery_strategy": state.get("discovery_strategy", "official_only"),
            "iteration": iteration,
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
    target_agent = (feedback.get("target_agent", "collector") if isinstance(feedback, dict) else "collector")

    await _publish(task_id, EventType.AGENT_END, {
        "agent": "qa", "iteration": iteration, "duration_ms": round(duration * 1000),
    })
    await _publish(task_id, EventType.QA_VERDICT, {
        "verdict": verdict, "score": score, "iteration": iteration,
        "issues_count": issues_count, "missing_dimensions": missing_dims,
        "target_agent": target_agent,
    })

    # Build feedback record
    if missing_dims:
        action = f"打回collector补采{missing_dims}"
    elif verdict == "pass":
        action = "通过"
    elif verdict == "reject":
        action = f"打回{target_agent}重做（质量不达标）"
    else:
        action = f"打回{target_agent}重做"

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
        "qa_target_agent": target_agent,
    }

    # 自适应策略降级：QA 建议下一轮换数据源
    suggested_strategy = args.get("suggested_strategy", "")
    current_strategy = state.get("discovery_strategy", "official_only")
    if suggested_strategy and suggested_strategy != current_strategy:
        update["suggested_strategy"] = suggested_strategy
        await _publish(task_id, EventType.LOG, {
            "message": f"QA 触发策略降级建议: {current_strategy} → {suggested_strategy}（下一轮 Collector 重新发现数据源）",
            "agent": "qa",
        })

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

    graph.add_node("discovery", discovery_node)
    graph.add_node("collector", collector_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("qa", qa_node)

    graph.add_edge("discovery", "collector")
    graph.add_edge("collector", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "qa")

    graph.add_conditional_edges(
        "qa",
        qa_routing,
        {
            "end": END,
            "collector": "collector",
            "analyst": "analyst",
            "writer": "writer",
        },
    )

    graph.set_entry_point("discovery")
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
    discovery_strategy = "official_only"
    trusted_domains: list[str] = []
    if industry in TEMPLATE_REGISTRY:
        template = load_template(industry)
        industry_fields = template.get_field_names()
        discovery_strategy = template.discovery_strategy
        trusted_domains = template.trusted_domains
        await _publish(task_id, EventType.LOG, {
            "message": f"已加载行业模板: {template.display_name} ({len(template.fields)}个扩展字段, 策略: {discovery_strategy})",
            "agent": "collector",
        })

    # expected_dimensions 只含核心维度，行业扩展字段由 check_extensions_coverage 单独检查
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
            "discovery_strategy": discovery_strategy,
            "trusted_domains": trusted_domains,
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
        config = {"recursion_limit": max_iterations * 6}
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
