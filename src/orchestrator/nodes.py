"""Node函数 - 每个node包装一个Agent，负责state↔AgentMessage转换

LangGraph的node是普通函数(state) -> state_update。
这里每个node：
1. 从state读取输入
2. 构造AgentMessage调用对应Agent
3. 将Agent返回的结果写回state
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from agents.analyst.agent import AnalystAgent
from agents.collector.agent import CollectorAgent
from agents.discovery.agent import DiscoveryAgent
from agents.qa.agent import QAAgent
from agents.writer.agent import WriterAgent
from orchestrator.state import FeedbackRecord, GraphState
from schemas.message import AgentMessage, MessageContext, MessageType


def _make_message(
    to_agent: str,
    function_name: str,
    arguments: dict[str, Any],
    state: GraphState,
) -> AgentMessage:
    """构造AgentMessage，从state中提取公共字段"""
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


async def discovery_node(state: GraphState) -> dict[str, Any]:
    """Discovery节点 - URL发现与路由（Warm/Cold/Open Search Path）"""
    target = state["competitor_name"]
    scope = state.get("collect_scope", ["pricing", "features"])
    target_urls = state.get("target_urls", [])
    strategy = state.get("discovery_strategy", "official_only")
    trusted_domains = state.get("trusted_domains", [])

    # 如果用户指定了URL，跳过discovery
    if target_urls:
        print(f"\n[Discovery] 用户指定了 {len(target_urls)} 个URL，跳过自动发现")
        return {
            "discovered_urls": target_urls,
            "discovery_path": "user_specified",
            "discovery_domain": "",
            "discovery_queries": [],
        }

    print(f"\n[Discovery] 发现 {target} 的数据源URL (策略: {strategy})...")
    agent = DiscoveryAgent()
    result = await agent.discover(target, scope, strategy=strategy, trusted_domains=trusted_domains)

    path = result["path"]
    urls = result["urls"]
    print(f"  [Discovery] {path} path → 发现 {len(urls)} 个URL (domain: {result['domain']})")

    return {
        "discovered_urls": urls,
        "discovery_path": path,
        "discovery_domain": result["domain"],
        "discovery_queries": result.get("search_queries", []),
    }


async def collector_node(state: GraphState) -> dict[str, Any]:
    """Collector节点 - 采集竞品数据"""
    iteration = state.get("iteration", 1)
    scope = state.get("collect_scope", ["pricing"])
    missing = state.get("missing_dimensions", [])

    if missing:
        expanded = list(set(scope + missing))
        print(f"\n[Collector] 第{iteration}轮 - 补采缺失维度 {missing}，当前scope: {expanded}")
        scope = expanded
    else:
        print(f"\n[Collector] 第{iteration}轮 - 开始采集 {state['competitor_name']}，scope: {scope}")

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
            "target_urls": state.get("discovered_urls", state.get("target_urls", [])),
            "language": "zh",
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments

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
    iteration = state.get("iteration", 1)
    claims = state.get("claims", [])
    print(f"\n[Analyst] 第{iteration}轮 - 分析 {len(claims)} 条claims...")
    agent = AnalystAgent()

    if not claims:
        return {"error": "no claims available for analysis", "profile": {}}

    message = _make_message(
        to_agent="analyst",
        function_name="analyze_competitor",
        arguments={
            "competitor_name": state["competitor_name"],
            "claims": claims,
            "dimensions_requested": state.get("collect_scope", ["pricing", "features"]),
            "industry": state.get("industry", ""),
        },
        state=state,
    )

    result = await agent.execute(message)
    args = result.arguments

    if args.get("error"):
        return {"error": args["error"], "profile": {}}

    return {
        "profile": args.get("profile", {}),
        "completeness_score": args.get("completeness_score", 0.0),
        "dimensions_analyzed": args.get("dimensions_analyzed", []),
    }


async def writer_node(state: GraphState) -> dict[str, Any]:
    """Writer节点 - 将profile转为Markdown报告"""
    print(f"\n[Writer] 生成Markdown报告...")
    agent = WriterAgent()

    profile = state.get("profile", {})
    if not profile:
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

    if args.get("error"):
        return {"error": args["error"], "report_markdown": ""}

    return {
        "report_markdown": args.get("report_markdown", ""),
        "report_length": args.get("report_length", 0),
        "footnote_count": args.get("footnote_count", 0),
    }


async def qa_node(state: GraphState) -> dict[str, Any]:
    """QA节点 - 质检profile和报告，决定pass/revise/reject"""
    iteration = state.get("iteration", 1)
    print(f"\n[QA] 第{iteration}轮 - 质量检查中...")
    agent = QAAgent()

    profile = state.get("profile", {})
    report_markdown = state.get("report_markdown", "")

    if not profile:
        iteration = state.get("iteration", 1)
        history = list(state.get("feedback_history", []))
        record = FeedbackRecord(
            iteration=iteration,
            verdict="reject",
            score=0.0,
            issues_count=0,
            critical_issues=0,
            action_taken="打回Collector重采（无profile）",
            feedback_summary="no profile to check",
        )
        history.append(record.model_dump(mode="json"))

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

    # 检测错误响应
    if args.get("error"):
        print(f"  [QA] ERROR: {args.get('error')}")
        print(f"  [QA] error_type: {args.get('error_type')}")

    verdict = args.get("verdict", "reject")
    score = args.get("overall_score", 0.0)
    issues_count = args.get("issues_count", 0)
    critical_issues = args.get("critical_issues", 0)
    feedback = args.get("feedback", {})
    summary = feedback.get("summary", "") if isinstance(feedback, dict) else ""
    missing_dims = args.get("missing_dimensions", [])
    target_agent = (feedback.get("target_agent", "collector") if isinstance(feedback, dict) else "collector")

    print(f"  [QA] verdict={verdict}, score={score:.2f}, issues={issues_count}, target={target_agent}, missing_dims={missing_dims}")

    # 记录FeedbackRecord
    iteration = state.get("iteration", 1)
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

    # 如果通过、reject、或达到最大迭代次数，标记完成
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
