"""Pipeline运行器 - 包装run_pipeline，注入SSE事件回调

替换orchestrator/nodes.py中的print为事件发布，
让前端能实时看到每个agent的执行状态。
"""

from __future__ import annotations

import asyncio
import logging
import os
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
from orchestrator.routing import classify_no_profile_failure
from orchestrator.scoring import iteration_improvement_bonus
from orchestrator.state import FeedbackRecord, GraphState
from schemas.message import AgentMessage, MessageContext, MessageType

logger = logging.getLogger(__name__)


def _profile_to_preview_markdown(profile: dict[str, Any]) -> str:
    """将 CompetitorProfile dict 转为简要 Markdown 预览，供 Analyst 完成后立即展示。"""
    if not profile:
        return ""
    lines: list[str] = []
    name = profile.get("product_name") or profile.get("company_name") or "未知产品"
    one_liner = profile.get("one_liner") or ""
    lines.append(f"# {name} — 结构化分析（草稿）")
    if one_liner:
        lines.append(f"\n> {one_liner}\n")

    # 基本信息
    meta_parts: list[str] = []
    if profile.get("industry"):
        meta_parts.append(f"行业: {profile['industry']}")
    if profile.get("founded_year"):
        meta_parts.append(f"成立: {profile['founded_year']}")
    if profile.get("funding_stage"):
        meta_parts.append(f"融资: {profile['funding_stage']}")
    if profile.get("employee_count_range"):
        meta_parts.append(f"规模: {profile['employee_count_range']}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))
        lines.append("")

    # 功能树
    features = profile.get("feature_tree") or []
    if features:
        lines.append("## 核心功能")
        for f in features[:8]:
            fname = f.get("name", "")
            desc = ""
            if isinstance(f.get("description"), dict):
                desc = f["description"].get("claim", "")
            elif isinstance(f.get("description"), str):
                desc = f["description"]
            maturity = f.get("maturity") or ""
            tag = f" `{maturity}`" if maturity else ""
            lines.append(f"- **{fname}**{tag}: {desc[:80]}")
            for sf in (f.get("sub_features") or [])[:3]:
                sf_name = sf.get("name", "")
                lines.append(f"  - {sf_name}")
        if len(features) > 8:
            lines.append(f"- ...及其他 {len(features) - 8} 项功能")
        lines.append("")

    # 定价
    pricing = profile.get("pricing")
    if pricing and isinstance(pricing, dict):
        lines.append("## 定价模型")
        model_type = pricing.get("model_type", "")
        if model_type:
            lines.append(f"模式: {model_type}")
        for tier in (pricing.get("tiers") or [])[:5]:
            tier_name = tier.get("name", "")
            price = tier.get("price", "")
            cycle = tier.get("billing_cycle", "")
            lines.append(f"- **{tier_name}**: {price} / {cycle}")
            for feat in (tier.get("features") or [])[:3]:
                lines.append(f"  - {feat}")
        lines.append("")

    # SWOT
    swot = profile.get("swot") or []
    if swot:
        lines.append("## SWOT 分析")
        category_map = {"strength": "优势", "weakness": "劣势", "opportunity": "机会", "threat": "威胁"}
        for item in swot:
            cat = category_map.get(item.get("category", ""), item.get("category", ""))
            lines.append(f"### {cat}")
            for claim_obj in (item.get("items") or [])[:4]:
                claim_text = claim_obj.get("claim", "") if isinstance(claim_obj, dict) else str(claim_obj)
                lines.append(f"- {claim_text[:100]}")
        lines.append("")

    # 用户画像
    personas = profile.get("user_personas") or []
    if personas:
        lines.append("## 用户画像")
        for p in personas[:4]:
            p_name = p.get("name") or p.get("segment") or "用户群"
            lines.append(f"- **{p_name}**")
        lines.append("")

    score = profile.get("completeness_score")
    if score is not None:
        lines.append(f"---\n*完整度: {score:.0%} — Writer 正在生成完整报告...*")

    return "\n".join(lines)


# Per-task trace accumulator (avoids LangGraph state propagation issues)
_task_traces: dict[str, list[dict[str, Any]]] = {}

# Per-task HITL gate: when QA says revise, pipeline waits here until human decides
_hitl_gates: dict[str, asyncio.Event] = {}
_hitl_decisions: dict[str, dict[str, Any]] = {}


def _langfuse_trace_id(task_id: str) -> str:
    return task_id.replace("-", "")[:32]


def _langfuse_trace_url(task_id: str) -> str:
    """Build the real Langfuse trace URL with the SDK project id.

    The frontend must not hard-code Langfuse project ids or URL shape.
    """
    trace_id = _langfuse_trace_id(task_id)
    try:
        from langfuse import Langfuse

        return Langfuse(timeout=10).get_trace_url(trace_id=trace_id) or ""
    except Exception as exc:
        logger.warning("Langfuse SDK trace URL generation failed: %s", exc)

    project_id = os.getenv("LANGFUSE_PROJECT_ID", "").strip().strip('"')
    host = (
        (
            os.getenv("LANGFUSE_HOST")
            or os.getenv("LANGFUSE_BASE_URL")
            or "https://cloud.langfuse.com"
        )
        .strip()
        .strip('"')
        .rstrip("/")
    )
    if project_id:
        return f"{host}/project/{project_id}/traces/{trace_id}"

    logger.warning(
        "Langfuse trace URL unavailable: SDK could not resolve project id and "
        "LANGFUSE_PROJECT_ID is not set."
    )
    return ""


def _normalize_manual_urls(urls: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in urls or []:
        url = raw.strip()
        if not url.startswith(("http://", "https://")):
            continue
        if url not in normalized:
            normalized.append(url)
    return normalized


def hitl_resume(
    task_id: str,
    decision: str,
    urls: list[str] | None = None,
    reason: str = "",
) -> None:
    """Called by intervene API to unblock a paused pipeline."""
    _hitl_decisions[task_id] = {
        "decision": decision,
        "urls": _normalize_manual_urls(urls),
        "reason": reason,
    }
    gate = _hitl_gates.get(task_id)
    if gate:
        gate.set()


def _pop_hitl_payload(task_id: str, default_decision: str) -> dict[str, Any]:
    payload = _hitl_decisions.pop(task_id, None)
    if not payload:
        return {"decision": default_decision, "urls": [], "reason": ""}
    return {
        "decision": payload.get("decision", default_decision),
        "urls": _normalize_manual_urls(payload.get("urls", [])),
        "reason": payload.get("reason", ""),
    }


def _apply_manual_url_resume(
    update: dict[str, Any],
    payload: dict[str, Any],
    *,
    current_iteration: int,
    max_iterations: int,
) -> None:
    urls = payload.get("urls") or []
    if payload.get("decision") != "continue" or not urls:
        return

    update["target_urls"] = urls
    update["discovered_urls"] = urls
    update["collect_errors"] = []
    update["qa_target_agent"] = "collector"
    update["suggested_strategy"] = ""
    update["final_status"] = "running"

    next_iteration = update.get("iteration", current_iteration + 1)
    if next_iteration > max_iterations:
        update["max_iterations"] = next_iteration


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


def _usable_pre_fetched_content(content: str | None, min_chars: int = 500) -> str:
    """Return pre-fetched page content only when it is long enough to trust."""
    if not content:
        return ""
    cleaned = content.strip()
    if len(cleaned) < min_chars:
        return ""
    return cleaned


def _qa_field_catalog(industry: str) -> dict[str, str]:
    labels = {
        "pricing": "定价信息",
        "features": "核心功能",
        "integrations": "第三方集成",
        "ai_features": "AI 功能",
        "customers": "客户案例",
        "user_personas": "用户画像",
        "source": "数据来源",
        "sources": "数据来源",
        "snippet": "原文摘录",
        "confidence": "置信度",
        "profile": "分析档案",
        "report": "报告正文",
        "extensions": "行业扩展字段",
    }
    if industry:
        try:
            from schemas.extensions import load_template

            template = load_template(industry)
            for field in template.fields:
                description = field.description.split("（", 1)[0].split(":", 1)[0].strip()
                labels[field.field_name] = description or field.field_name
                labels[f"extensions.{field.field_name}"] = description or field.field_name
        except Exception:
            pass
    return labels


def _qa_field_label(field_path: str, labels: dict[str, str]) -> str:
    if not field_path:
        return "整体质量"
    normalized = field_path.replace("[", ".").replace("]", "")
    parts = [p for p in normalized.split(".") if p]
    if field_path in labels:
        return labels[field_path]
    if len(parts) >= 2 and parts[0] == "extensions":
        return labels.get(f"extensions.{parts[1]}", labels.get(parts[1], parts[1]))
    if parts:
        return labels.get(parts[-1], labels.get(parts[0], parts[-1]))
    return field_path


def _qa_reason_label(issue_type: str, target_agent: str) -> str:
    mapping = {
        "missing_source": "缺少可信来源或证据不足",
        "factual_error": "事实可能不可靠，需要重新核对来源",
        "outdated": "来源可能过旧，需要补充更新资料",
        "low_confidence": "分析置信度过低",
        "inconsistency": "分析结论前后不一致",
        "schema_violation": "输出结构不符合要求",
    }
    base = mapping.get(issue_type, "质量检查未通过")
    if target_agent == "collector" and issue_type in {
        "missing_source",
        "factual_error",
        "outdated",
    }:
        return f"{base}，所以打回 Collector 补数据"
    if target_agent == "analyst":
        return f"{base}，所以打回 Analyst 重做分析"
    if target_agent == "writer":
        return f"{base}，所以打回 Writer 重写报告"
    return base


def _qa_action_hint(issue: dict[str, Any], field_label: str, target_agent: str) -> str:
    issue_type = issue.get("issue_type", "")
    raw_suggestion = (issue.get("suggestion") or "").strip()
    field_path = issue.get("field_path", "")
    if target_agent == "collector":
        if "api" in field_path:
            return "补充开放平台、API 文档、开发者中心、SDK 文档等 URL。"
        if "export" in field_path:
            return "补充帮助中心里的导出/迁移/备份文档。"
        if "integration" in field_path:
            return "补充 integrations、marketplace、app directory 页面。"
        if issue_type == "missing_source":
            return f"补充能直接证明“{field_label}”的官方页面或可信第三方来源。"
        return raw_suggestion or "补充更直接的数据源后重新采集。"
    if target_agent == "analyst":
        return raw_suggestion or "用已有证据重新组织 profile，补齐置信度和证据映射。"
    if target_agent == "writer":
        return raw_suggestion or "按 profile 重新生成报告，保留来源引用。"
    return raw_suggestion or "按 QA 问题修复后继续迭代。"


def _enrich_qa_issue(
    issue: dict[str, Any],
    *,
    labels: dict[str, str],
    target_agent: str,
    persisted_fields: set[str] | None = None,
) -> dict[str, Any]:
    enriched = dict(issue)
    field_label = _qa_field_label(issue.get("field_path", ""), labels)
    reason_label = _qa_reason_label(issue.get("issue_type", ""), target_agent)
    enriched["field_label"] = field_label
    enriched["reason_label"] = reason_label
    enriched["action_hint"] = _qa_action_hint(issue, field_label, target_agent)
    if persisted_fields and issue.get("field_path") in persisted_fields:
        enriched["iteration_hint"] = (
            "上一轮已经存在，本轮仍未解决；继续只重复同样 URL 大概率不会改善。"
        )
    return enriched


def _brief_qa_issue(issue: dict[str, Any], max_len: int = 120) -> str:
    field = issue.get("field_label") or issue.get("field_path") or "(全局)"
    severity = issue.get("severity") or "minor"
    reason = issue.get("reason_label") or issue.get("issue_type") or "unknown"
    description = (issue.get("description") or "").strip()
    if len(description) > max_len:
        description = description[:max_len].rstrip() + "..."
    return f"[{severity}] {field}: {reason}；{description}"


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

    await _publish(
        task_id,
        EventType.AGENT_START,
        {
            "agent": "discovery",
            "iteration": 1,
        },
    )
    start = time.time()

    # 如果用户指定了URL，跳过discovery
    if target_urls:
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"用户指定了 {len(target_urls)} 个URL，跳过自动发现",
                "agent": "discovery",
            },
        )
        duration = time.time() - start
        await _publish(
            task_id,
            EventType.AGENT_END,
            {
                "agent": "discovery",
                "iteration": 1,
                "duration_ms": round(duration * 1000),
            },
        )
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
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"QA 反馈触发策略切换: {strategy} → {suggested}",
                "agent": "discovery",
            },
        )
        strategy = suggested

    result = await agent.discover(target, scope, strategy=strategy, trusted_domains=trusted_domains)

    path = result["path"]
    urls = result["urls"]
    domain = result.get("domain", "")
    queries = result.get("search_queries", [])
    duration = time.time() - start

    await _publish(
        task_id,
        EventType.LOG,
        {
            "message": f"Discovery [{path}]: 发现 {len(urls)} 个URL (domain: {domain})",
            "agent": "discovery",
        },
    )

    # 0 URL 时把搜索 query 和命中明细暴露到 SSE 流，便于定位
    # （搜索本身没出错但搜不到 vs 配额耗尽 vs 全被排除域名过滤掉）
    if not urls and queries:
        trusted_count = result.get("trusted_count", 0)
        other_count = result.get("other_count", 0)
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"⚠ Discovery 0 URL 详情: 已尝试 {len(queries)} 条 search query, "
                    f"trusted_hits={trusted_count}, other_hits={other_count}. "
                    f"Queries: {queries[:5]}{'...' if len(queries) > 5 else ''}"
                ),
                "agent": "discovery",
            },
        )
        if path == "open_search" and trusted_count == 0 and other_count == 0:
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": (
                        "💡 提示: open_search 策略 0 命中。常见原因：1) ENABLE_FIRECRAWL=false，"
                        "当前只做免费域名猜测和URL验证；2) Firecrawl 未配置、额度不足或搜索不可用；"
                        "3) 候选URL不可达、被站点拦截或 robots.txt 限制。"
                        "建议补充 2-3 个可直接访问的权威源，或在演示模式下开启受控付费抓取。"
                    ),
                    "agent": "discovery",
                },
            )

    await _publish(
        task_id,
        EventType.AGENT_END,
        {
            "agent": "discovery",
            "iteration": 1,
            "duration_ms": round(duration * 1000),
        },
    )

    _task_traces.setdefault(task_id, []).append(
        _build_trace_entry(
            agent="discovery",
            iteration=1,
            duration_ms=round(duration * 1000),
            model="none (logic + search API)",
            prompt_preview=f"发现 {target} 的数据源，scope: {scope}, strategy: {strategy}",
            output_preview=f"path={path}, domain={domain}, urls={len(urls)}",
        )
    )

    return {
        "discovered_urls": urls,
        "discovery_path": path,
        "discovery_domain": domain,
        "discovery_queries": result.get("search_queries", []),
        "discovery_strategy": strategy,
        "suggested_strategy": "",
        "pre_fetched_content": result.get("pre_fetched", {}),
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

    await _publish(
        task_id,
        EventType.AGENT_START,
        {
            "agent": "collector",
            "iteration": iteration,
            "scope": scope,
        },
    )
    start = time.time()

    agent = CollectorAgent()

    # 使用 Discovery 节点已发现的 URL（首轮），或补采时重新发现
    target = state["competitor_name"]
    discovered = state.get("discovered_urls", [])
    new_strategy = state.get("discovery_strategy", "official_only")
    manual_urls = _normalize_manual_urls(state.get("target_urls", []))
    pre_fetched_updates: dict[str, str] = {}

    # QA 自适应降级：上一轮建议切换策略 → 重跑 Discovery 拿新数据源
    if manual_urls:
        urls = manual_urls[:10]
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"使用人工补充的数据源: {len(urls)} 个URL",
                "agent": "collector",
            },
        )
    elif suggested and suggested != new_strategy:
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"QA 反馈触发策略降级: {new_strategy} → {suggested}，重新发现数据源",
                "agent": "collector",
            },
        )
        new_strategy = suggested
        rediscover = DiscoveryAgent()
        rediscover_result = await rediscover.discover(
            target,
            scope,
            strategy=new_strategy,
            trusted_domains=state.get("trusted_domains", []),
        )
        urls = rediscover_result["urls"][:10]
        pre_fetched_updates.update(rediscover_result.get("pre_fetched", {}))
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"新数据源 [{rediscover_result['path']}]: {len(urls)} 个URL",
                "agent": "collector",
            },
        )
    elif iteration > 1 and not state.get("claims"):
        # 上一轮无任何证据（URL全失败或Discovery找到0个URL）→ 重跑 Discovery
        failed_urls = set()
        for err in state.get("collect_errors", []):
            if ": " in err:
                failed_urls.add(err.split(": ", 1)[0])
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (f"上轮 0 条证据（失败URL: {len(failed_urls)}），重新搜索数据源"),
                "agent": "collector",
            },
        )
        rediscover = DiscoveryAgent()
        rediscover_result = await rediscover.discover(
            target,
            scope,
            strategy=new_strategy,
            trusted_domains=state.get("trusted_domains", []),
        )
        new_urls = [u for u in rediscover_result.get("urls", []) if u not in failed_urls]
        urls = new_urls[:10]
        pre_fetched_updates.update(rediscover_result.get("pre_fetched", {}))
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"重新发现 [{rediscover_result['path']}]: "
                    f"{len(urls)} 个URL（排除 {len(failed_urls)} 个死链）"
                ),
                "agent": "collector",
            },
        )
    elif iteration > 1 and missing:
        # 有claims但QA打回说缺维度 → 排除上轮已抓URL，重新发现新数据源
        already_tried = set(discovered)
        rediscover = DiscoveryAgent()
        rediscover_result = await rediscover.discover(
            target,
            scope,
            strategy=new_strategy,
            trusted_domains=state.get("trusted_domains", []),
        )
        new_urls = [u for u in rediscover_result.get("urls", []) if u not in already_tried]
        urls = (new_urls or discovered)[:10]
        pre_fetched_updates.update(rediscover_result.get("pre_fetched", {}))
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"缺少维度 {missing}，重新发现数据源: {len(new_urls)} 个新URL"
                    f"（排除 {len(already_tried)} 个已抓）"
                ),
                "agent": "collector",
            },
        )
    elif discovered:
        # Discovery 已发现 URL（首轮或补采），直接复用
        urls = discovered[:10]
    else:
        # 未知竞品 + Discovery 未给出 URL → 走 warm-path 兜底（仅已知竞品有效）
        urls = agent._get_default_urls(target, scope)[:10]
        if urls:
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": f"Warm-path 兜底: 命中已知竞品库，使用 {len(urls)} 个 URL",
                    "agent": "collector",
                },
            )
        else:
            # 未知竞品 + Discovery 无结果 → 不再自拼搜索端点，明确报错
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": (
                        f"⚠ Discovery 未发现可采集的 URL，"
                        f"且 {target!r} 不在已知竞品库中。"
                        f"建议：1) 切换 discovery_strategy 重试；"
                        f"2) 通过 target_urls 提供候选 URL；"
                        f"3) 该领域信息源可能不足以自动分析。"
                    ),
                    "agent": "collector",
                },
            )

    # 行业模板扩展字段注入采集指令
    industry_fields = state.get("industry_fields", [])
    extra_scope_hint = ""
    if industry_fields:
        extra_scope_hint = f" (行业扩展字段: {', '.join(industry_fields[:5])})"

    await _publish(
        task_id,
        EventType.LOG,
        {
            "message": f"Fan-out: 并行采集 {len(urls)} 个数据源{extra_scope_hint}",
            "agent": "collector",
        },
    )

    # Fan-out: 并行 fetch + extract
    semaphore = asyncio.Semaphore(10)
    fetch_errors: list[str] = []
    # Discovery 阶段搜索结果中的内容摘要（robots.txt 拦截时兜底）
    pre_fetched: dict[str, str] = {
        **state.get("pre_fetched_content", {}),
        **pre_fetched_updates,
    }

    async def process_url(url: str, sub_id: str) -> list[dict]:
        await _publish(
            task_id,
            EventType.SUB_AGENT_START,
            {
                "parent": "collector",
                "sub_id": sub_id,
                "url": url,
                "iteration": iteration,
            },
        )
        sub_start = time.time()

        async with semaphore:
            cached_content = _usable_pre_fetched_content(pre_fetched.get(url))
            if cached_content:
                await _publish(
                    task_id,
                    EventType.LOG,
                    {
                        "message": (
                            f"复用 Discovery 预抓取内容: {url} "
                            f"({len(cached_content)} 字符)，跳过重复抓取"
                        ),
                        "agent": "collector",
                    },
                )
                content = agent._truncate_content(cached_content, max_chars=12000)
                extracted = await agent._extract_info(
                    competitor_name=target,
                    dimensions=scope,
                    url=url,
                    title="",
                    content=content,
                    snapshot_hash="",
                    industry_fields=industry_fields,
                    priority_dimensions=missing if iteration > 1 else None,
                )
                await _publish(
                    task_id,
                    EventType.SUB_AGENT_END,
                    {
                        "parent": "collector",
                        "sub_id": sub_id,
                        "url": url,
                        "iteration": iteration,
                        "success": True,
                        "claims_count": len(extracted),
                        "duration_ms": round((time.time() - sub_start) * 1000),
                    },
                )
                return extracted

            fetch_result = await agent._fetch_url(url)

            if not fetch_result.success:
                # robots.txt 拦截：尝试用 Discovery 搜索结果中的内容兜底
                if fetch_result.robots_status == "disallowed" and url in pre_fetched:
                    fallback_content = _usable_pre_fetched_content(pre_fetched[url], min_chars=50)
                    if fallback_content:
                        await _publish(
                            task_id,
                            EventType.LOG,
                            {
                                "message": (
                                    f"⛔ robots.txt 禁止抓取: {url}，"
                                    f"使用搜索摘要兜底 ({len(fallback_content)} 字符)"
                                ),
                                "agent": "collector",
                            },
                        )
                        content = agent._truncate_content(fallback_content, max_chars=12000)
                        extracted = await agent._extract_info(
                            competitor_name=target,
                            dimensions=scope,
                            url=url,
                            title="",
                            content=content,
                            snapshot_hash="",
                            industry_fields=industry_fields,
                            priority_dimensions=missing if iteration > 1 else None,
                        )
                        await _publish(
                            task_id,
                            EventType.SUB_AGENT_END,
                            {
                                "parent": "collector",
                                "sub_id": sub_id,
                                "url": url,
                                "iteration": iteration,
                                "success": True,
                                "claims_count": len(extracted),
                                "duration_ms": round((time.time() - sub_start) * 1000),
                            },
                        )
                        return extracted

                fetch_errors.append(f"{url}: {fetch_result.error}")
                if fetch_result.robots_status == "disallowed":
                    await _publish(
                        task_id,
                        EventType.LOG,
                        {
                            "message": f"⛔ robots.txt 禁止抓取: {url}（已跳过）",
                            "agent": "collector",
                        },
                    )
                else:
                    # 抓取失败的真实错误也发到流，便于前端定位 quota / 网络 / 鉴权
                    await _publish(
                        task_id,
                        EventType.LOG,
                        {
                            "message": f"❌ 抓取失败: {url} — {fetch_result.error}",
                            "agent": "collector",
                        },
                    )
                await _publish(
                    task_id,
                    EventType.SUB_AGENT_END,
                    {
                        "parent": "collector",
                        "sub_id": sub_id,
                        "url": url,
                        "iteration": iteration,
                        "success": False,
                        "duration_ms": round((time.time() - sub_start) * 1000),
                        "claims_count": 0,
                        "error": fetch_result.error or "",
                    },
                )
                return []

            if fetch_result.pii_redactions:
                redact_summary = "、".join(
                    f"{k.strip('[]')}×{v}" for k, v in fetch_result.pii_redactions.items()
                )
                await _publish(
                    task_id,
                    EventType.LOG,
                    {
                        "message": f"🔒 PII 脱敏: {url} 已掩码 {redact_summary}",
                        "agent": "collector",
                    },
                )

            content = agent._truncate_content(fetch_result.content, max_chars=12000)
            extracted = await agent._extract_info(
                competitor_name=target,
                dimensions=scope,
                url=url,
                title=fetch_result.title,
                content=content,
                snapshot_hash=fetch_result.snapshot_hash,
                industry_fields=industry_fields,
                priority_dimensions=missing if iteration > 1 else None,
            )

            await _publish(
                task_id,
                EventType.SUB_AGENT_END,
                {
                    "parent": "collector",
                    "sub_id": sub_id,
                    "url": url,
                    "iteration": iteration,
                    "success": True,
                    "claims_count": len(extracted),
                    "duration_ms": round((time.time() - sub_start) * 1000),
                },
            )
            return extracted

    tasks = [process_url(url, f"fetch-{i}") for i, url in enumerate(urls)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_claims_this_iter: list[dict] = []
    for r in results:
        if isinstance(r, list):
            new_claims_this_iter.extend(r)
        elif isinstance(r, Exception):
            fetch_errors.append(str(r))

    # 累积模式：保留上一轮 claims 作为 grounding，新 claims 增量合并并去重
    # 防止迭代时 LLM 抽取随机性导致字段证据丢失，使分数倒退
    prev_claims = list(state.get("claims", []))

    def _claim_key(c: dict) -> tuple[str, str]:
        sources = c.get("sources") or []
        first_url = (sources[0].get("url") if sources else "") or ""
        claim_text = c.get("claim") or ""
        return (claim_text.strip(), first_url)

    seen: set[tuple[str, str]] = {_claim_key(c) for c in prev_claims}
    merged_claims: list[dict] = list(prev_claims)
    added = 0
    for c in new_claims_this_iter:
        key = _claim_key(c)
        if key in seen:
            continue
        seen.add(key)
        merged_claims.append(c)
        added += 1

    if iteration > 1:
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"增量累积: 旧证据 {len(prev_claims)} 条保留 + 本轮新增 {added} 条 "
                    f"(本轮抽到 {len(new_claims_this_iter)} 条，去重 {len(new_claims_this_iter) - added} 条)"
                ),
                "agent": "collector",
            },
        )

    all_claims = merged_claims
    duration = time.time() - start

    await _publish(
        task_id,
        EventType.AGENT_END,
        {
            "agent": "collector",
            "iteration": iteration,
            "duration_ms": round(duration * 1000),
        },
    )

    _task_traces.setdefault(task_id, []).append(
        _build_trace_entry(
            agent="collector",
            iteration=iteration,
            duration_ms=round(duration * 1000),
            model=agent.config.model,
            input_tokens=agent.token_usage["input"],
            output_tokens=agent.token_usage["output"],
            prompt_preview=f"采集 {target} 的 {scope} 维度数据，共 {len(urls)} 个URL",
            output_preview=(
                f"累计 {len(all_claims)} 条claims（本轮 +{added}），失败 {len(fetch_errors)} 个源"
            ),
        )
    )

    return {
        "claims": all_claims,
        "sources_fetched": len(urls) - len(fetch_errors),
        "sources_failed": len(fetch_errors),
        "collect_errors": fetch_errors,
        "collect_scope": scope,
        "missing_dimensions": [],
        "discovered_urls": urls,
        "target_urls": manual_urls,
        "discovery_strategy": new_strategy,
        "suggested_strategy": "",  # 消费完清空
        "pre_fetched_content": pre_fetched,
    }


async def analyst_node(state: GraphState) -> dict[str, Any]:
    """Analyst节点 - 分析claims生成CompetitorProfile"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)
    claims = state.get("claims", [])

    await _publish(
        task_id,
        EventType.AGENT_START,
        {
            "agent": "analyst",
            "iteration": iteration,
            "claims_count": len(claims),
        },
    )
    start = time.time()

    agent = AnalystAgent()

    if not claims:
        await _publish(
            task_id,
            EventType.AGENT_END,
            {
                "agent": "analyst",
                "iteration": iteration,
                "duration_ms": 0,
            },
        )
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

    await _publish(
        task_id,
        EventType.AGENT_END,
        {
            "agent": "analyst",
            "iteration": iteration,
            "duration_ms": round(duration * 1000),
            "report_preview": _profile_to_preview_markdown(args.get("profile", {})),
        },
    )

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

    _task_traces.setdefault(task_id, []).append(
        _build_trace_entry(
            agent="analyst",
            iteration=iteration,
            duration_ms=round(duration * 1000),
            model=agent.config.model,
            input_tokens=agent.token_usage["input"],
            output_tokens=agent.token_usage["output"],
            prompt_preview=f"分析 {len(claims)} 条claims，维度: {state.get('collect_scope', [])}",
            output_preview=f"生成 CompetitorProfile，完整度 {args.get('completeness_score', 0):.0%}",
        )
    )

    return {
        "profile": args.get("profile", {}),
        "completeness_score": args.get("completeness_score", 0.0),
        "dimensions_analyzed": args.get("dimensions_analyzed", []),
    }


async def writer_node(state: GraphState) -> dict[str, Any]:
    """Writer节点 - 将profile转为Markdown报告"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)

    await _publish(
        task_id,
        EventType.AGENT_START,
        {
            "agent": "writer",
            "iteration": iteration,
        },
    )
    start = time.time()

    agent = WriterAgent()
    profile = state.get("profile", {})

    if not profile:
        await _publish(
            task_id,
            EventType.AGENT_END,
            {
                "agent": "writer",
                "iteration": iteration,
                "duration_ms": 0,
            },
        )
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

    report_md = args.get("report_markdown", "")
    await _publish(
        task_id,
        EventType.AGENT_END,
        {
            "agent": "writer",
            "iteration": iteration,
            "duration_ms": round(duration * 1000),
            "report_preview": report_md,
        },
    )

    if args.get("error"):
        return {"error": args["error"], "report_markdown": ""}

    _task_traces.setdefault(task_id, []).append(
        _build_trace_entry(
            agent="writer",
            iteration=iteration,
            duration_ms=round(duration * 1000),
            model=agent.config.model,
            input_tokens=agent.token_usage["input"],
            output_tokens=agent.token_usage["output"],
            prompt_preview=f"将 {state['competitor_name']} 的 profile 转为 Markdown 报告",
            output_preview=f"生成报告 {args.get('report_length', 0)} 字，{args.get('footnote_count', 0)} 个脚注",
        )
    )

    return {
        "report_markdown": args.get("report_markdown", ""),
        "report_length": args.get("report_length", 0),
        "footnote_count": args.get("footnote_count", 0),
    }


async def qa_node(state: GraphState) -> dict[str, Any]:
    """QA节点 - 质检profile和报告"""
    task_id = state.get("trace_id", "")
    iteration = state.get("iteration", 1)

    await _publish(
        task_id,
        EventType.AGENT_START,
        {
            "agent": "qa",
            "iteration": iteration,
        },
    )
    start = time.time()

    profile = state.get("profile", {})
    report_markdown = state.get("report_markdown", "")

    if not profile:
        failure = classify_no_profile_failure(state)
        target_agent = failure["target_agent"]
        missing_dimensions = failure["missing_dimensions"]
        history = list(state.get("feedback_history", []))
        record = FeedbackRecord(
            iteration=iteration,
            verdict="reject",
            score=0.0,
            issues_count=0,
            critical_issues=0,
            action_taken=f"reject(no profile) -> {target_agent}",
            feedback_summary=failure["summary"],
        )
        history.append(record.model_dump(mode="json"))
        await _publish(task_id, EventType.ITERATION_SUMMARY, record.model_dump(mode="json"))

        duration = time.time() - start
        await _publish(
            task_id,
            EventType.AGENT_END,
            {
                "agent": "qa",
                "iteration": iteration,
                "duration_ms": round(duration * 1000),
            },
        )
        await _publish(
            task_id,
            EventType.QA_VERDICT,
            {
                "verdict": "reject",
                "score": 0.0,
                "iteration": iteration,
            },
        )

        max_iter = state.get("max_iterations", 3)
        suggested_strategy = failure.get("suggested_strategy", "")
        update: dict[str, Any] = {
            "qa_verdict": "reject",
            "qa_score": 0.0,
            "qa_issues": [],
            "qa_feedback_summary": failure["summary"],
            "feedback_history": history,
            "iteration": iteration + 1,
            "qa_target_agent": target_agent,
            "missing_dimensions": missing_dimensions,
            "suggested_strategy": suggested_strategy,
        }

        # 即使没有 profile，也必须经过人工审核（不能静默终止）
        score_trend = [r.get("score", 0.0) for r in history]
        failure_message = failure.get("message") or failure["summary"]
        error_samples = failure.get("error_samples", [])
        if error_samples:
            failure_message += " 失败样例：" + "；".join(error_samples[:2])
        pause_issues = [
            {
                "field_path": "collector.fetch",
                "severity": "major",
                "issue_type": failure.get("reason", "collector_failed"),
                "description": sample,
                "suggestion": "补充可直接访问的数据源，或修复本地抓取/开启受控付费抓取后重试。",
            }
            for sample in error_samples[:3]
        ]
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await _publish(
            task_id,
            EventType.HITL_PAUSE,
            {
                "verdict": "reject",
                "score": 0.0,
                "iteration": iteration,
                "missing_dimensions": missing_dimensions,
                "message": f"{failure_message}（第 {iteration}/{max_iter} 轮）。",
                "issues": pause_issues,
                "score_trend": score_trend,
                "suggested_strategy": suggested_strategy,
                "current_strategy": state.get("discovery_strategy", "official_only"),
                "reason": failure["reason"],
                "report_preview": "",
                "iterations_left": max(0, max_iter - iteration),
                "target_agent": target_agent,
                "resolved_fields": [],
                "regressed_fields": [],
            },
        )
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        hitl_payload = _pop_hitl_payload(task_id, "abort")
        decision = hitl_payload["decision"]
        _apply_manual_url_resume(
            update,
            hitl_payload,
            current_iteration=iteration,
            max_iterations=max_iter,
        )
        await _publish(
            task_id,
            EventType.HITL_RESUME,
            {
                "decision": decision,
                "iteration": iteration,
                "urls_count": len(hitl_payload.get("urls", [])),
            },
        )

        if decision == "abort" or iteration >= max_iter:
            if decision == "continue" and hitl_payload.get("urls"):
                update.pop("completed_at", None)
            else:
                update["final_status"] = (
                    "human_abort" if decision == "abort" else "max_iterations_reached(no_profile)"
                )
                update["completed_at"] = datetime.now().isoformat()
        elif decision == "force_pass":
            # 强制通过 + 空 profile 没意义，按 abort 处理
            update["final_status"] = "human_abort"
            update["completed_at"] = datetime.now().isoformat()
        # else continue → 流程继续

        return update

    agent = QAAgent()
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

    if args.get("error"):
        error_message = args.get("error", "unknown QA error")
        error_type = args.get("error_type", "QAError")
        await _publish(
            task_id,
            EventType.AGENT_END,
            {
                "agent": "qa",
                "iteration": iteration,
                "duration_ms": round(duration * 1000),
            },
        )
        await _publish(
            task_id,
            EventType.ERROR,
            {
                "message": (
                    f"QA 质检自身失败，不是 Collector 数据质量不达标: {error_type}: {error_message}"
                )
            },
        )
        _task_traces.setdefault(task_id, []).append(
            _build_trace_entry(
                agent="qa",
                iteration=iteration,
                duration_ms=round(duration * 1000),
                model=agent.config.model,
                input_tokens=agent.token_usage["input"],
                output_tokens=agent.token_usage["output"],
                prompt_preview=f"质检 {state['competitor_name']} profile + 报告",
                output_preview=f"QA failed: {error_type}: {error_message}",
            )
        )
        return {
            "qa_verdict": "reject",
            "qa_score": 0.0,
            "qa_issues": [],
            "qa_feedback_summary": f"QA 质检自身失败: {error_type}: {error_message}",
            "qa_target_agent": "qa",
            "missing_dimensions": [],
            "error": f"QA failed: {error_type}: {error_message}",
            "final_status": "qa_failed",
            "completed_at": datetime.now().isoformat(),
        }

    verdict = args.get("verdict", "reject")
    raw_score = args.get("overall_score", 0.0)
    score = raw_score
    issues_count = args.get("issues_count", 0)
    critical_issues = args.get("critical_issues", 0)
    feedback = args.get("feedback", {})
    summary = feedback.get("summary", "") if isinstance(feedback, dict) else ""
    missing_dims = args.get("missing_dimensions", [])
    target_agent = (
        feedback.get("target_agent", "collector") if isinstance(feedback, dict) else "collector"
    )

    await _publish(
        task_id,
        EventType.AGENT_END,
        {
            "agent": "qa",
            "iteration": iteration,
            "duration_ms": round(duration * 1000),
        },
    )
    await _publish(
        task_id,
        EventType.QA_VERDICT,
        {
            "verdict": verdict,
            "score": score,
            "iteration": iteration,
            "issues_count": issues_count,
            "missing_dimensions": missing_dims,
            "target_agent": target_agent,
        },
    )

    # Build feedback record
    if missing_dims:
        action = f"打回collector补采{missing_dims}"
    elif verdict == "pass":
        action = "通过"
    elif verdict == "reject":
        action = f"打回{target_agent}重做（质量不达标）"
    else:
        action = f"打回{target_agent}重做"

    # 抽取本轮 issue 明细（field 级），供 FeedbackRecord 与 HITL payload 复用
    qa_issues_list: list[dict[str, Any]] = []
    if isinstance(feedback, dict):
        for issue in feedback.get("issues", []):
            if isinstance(issue, dict):
                qa_issues_list.append(
                    {
                        "field_path": issue.get("field_path", ""),
                        "severity": issue.get("severity", "minor"),
                        "issue_type": issue.get("issue_type", ""),
                        "description": issue.get("description", ""),
                        "suggestion": issue.get("suggestion") or "",
                    }
                )

    # 与上一轮做 field_path 级 diff，标记 resolved / regressed / persisted
    prev_history = state.get("feedback_history", [])
    prev_fields: set[str] = set()
    previous_record = (
        prev_history[-1] if prev_history and isinstance(prev_history[-1], dict) else None
    )
    if prev_history:
        last = prev_history[-1]
        if isinstance(last, dict):
            for it in last.get("issues", []):
                if isinstance(it, dict) and it.get("field_path"):
                    prev_fields.add(it["field_path"])
    curr_fields = {i["field_path"] for i in qa_issues_list if i.get("field_path")}
    resolved_fields = sorted(prev_fields - curr_fields)
    regressed_fields = sorted(curr_fields - prev_fields)
    persisted_fields = sorted(curr_fields & prev_fields)
    field_labels = _qa_field_catalog(state.get("industry", ""))
    qa_issues_list = [
        _enrich_qa_issue(
            issue,
            labels=field_labels,
            target_agent=target_agent,
            persisted_fields=set(persisted_fields),
        )
        for issue in qa_issues_list
    ]

    previous_claims_count = (
        int(previous_record.get("claims_count", 0) or 0) if previous_record else 0
    )
    current_claims_count = len(state.get("claims", []))
    improvement_bonus = iteration_improvement_bonus(
        raw_score=raw_score,
        previous_record=previous_record,
        issues_count=issues_count,
        critical_issues=critical_issues,
        current_claims_count=current_claims_count,
        previous_claims_count=previous_claims_count,
        resolved_fields_count=len(resolved_fields),
        regressed_fields_count=len(regressed_fields),
    )
    if improvement_bonus:
        score = round(raw_score + improvement_bonus, 2)
        if isinstance(feedback, dict):
            feedback["overall_score"] = score
            summary = (
                f"{summary} 迭代改善奖励 +{improvement_bonus:.2f}"
                f"（严重问题 {previous_record.get('critical_issues', 0)}→{critical_issues}，"
                f"问题数 {previous_record.get('issues_count', 0)}→{issues_count}）。"
            )
            feedback["summary"] = summary
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"QA 迭代改善奖励: 原始分 {raw_score:.2f} → 展示分 {score:.2f}；"
                    f"严重问题 {previous_record.get('critical_issues', 0)}→{critical_issues}，"
                    f"问题数 {previous_record.get('issues_count', 0)}→{issues_count}，"
                    f"claims {previous_claims_count}→{current_claims_count}"
                ),
                "agent": "qa",
            },
        )

    if verdict != "pass":
        route_reason = (
            "还有关键维度没有足够证据，所以需要 Collector 补数据"
            if missing_dims
            else "QA 判断主要问题属于当前打回对象负责"
        )
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": (
                    f"QA 打回 {target_agent}: {route_reason}；"
                    f"score={score:.2f}；issues={issues_count}；critical={critical_issues}"
                ),
                "agent": "qa",
            },
        )
        if missing_dims:
            missing_labels = [_qa_field_label(dim, field_labels) for dim in missing_dims]
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": f"Collector 质量不达标: 缺少/不足 {', '.join(missing_labels)} 的可验证证据",
                    "agent": "qa",
                },
            )
        for issue in sorted(
            qa_issues_list,
            key=lambda i: {"critical": 0, "major": 1, "minor": 2}.get(i.get("severity", ""), 9),
        )[:3]:
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": f"QA 主要问题: {_brief_qa_issue(issue)}",
                    "agent": "qa",
                },
            )
        if iteration > 1:
            unresolved = [_qa_field_label(field, field_labels) for field in persisted_fields[:5]]
            await _publish(
                task_id,
                EventType.LOG,
                {
                    "message": (
                        f"QA 迭代变化: 已解决 {len(resolved_fields)} 个，"
                        f"新增 {len(regressed_fields)} 个，仍未解决 {len(persisted_fields)} 个"
                        + (f"（仍卡在: {', '.join(unresolved)}）" if unresolved else "")
                    ),
                    "agent": "qa",
                },
            )

    record = FeedbackRecord(
        iteration=iteration,
        verdict=verdict,
        score=score,
        issues_count=issues_count,
        critical_issues=critical_issues,
        action_taken=action,
        feedback_summary=summary,
        raw_score=raw_score,
        improvement_bonus=improvement_bonus,
        claims_count=current_claims_count,
        issues=qa_issues_list,
        resolved_fields=resolved_fields,
        regressed_fields=regressed_fields,
        persisted_fields=persisted_fields,
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
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"QA 触发策略降级建议: {current_strategy} → {suggested_strategy}（下一轮 Collector 重新发现数据源）",
                "agent": "qa",
            },
        )

    _task_traces.setdefault(task_id, []).append(
        _build_trace_entry(
            agent="qa",
            iteration=iteration,
            duration_ms=round(duration * 1000),
            model=agent.config.model,
            input_tokens=agent.token_usage["input"],
            output_tokens=agent.token_usage["output"],
            prompt_preview=f"质检 {state['competitor_name']} profile + 报告，期望维度: {state.get('expected_dimensions', [])}",
            output_preview=f"verdict={verdict}, score={score:.2f}, issues={issues_count}, missing={missing_dims}",
        )
    )

    max_iter = state.get("max_iterations", 3)

    # 构造 HITL 决策依据：让人工审核时不用盲选（qa_issues_list 在前文已提取）
    score_trend = [r.get("score", 0.0) for r in history if isinstance(r, dict)]
    report_preview = state.get("report_markdown") or ""
    iterations_left = max(0, max_iter - iteration)

    def _hitl_payload(msg: str) -> dict[str, Any]:
        reason = "qa_pass" if verdict == "pass" else f"qa_{verdict}"
        return {
            "iteration": iteration,
            "score": score,
            "verdict": verdict,
            "missing_dimensions": missing_dims if verdict != "pass" else [],
            "message": msg,
            "reason": reason,
            "issues": qa_issues_list,
            "score_trend": score_trend,
            "suggested_strategy": suggested_strategy,
            "current_strategy": current_strategy,
            "report_preview": report_preview,
            "iterations_left": iterations_left,
            "target_agent": target_agent,
            "resolved_fields": resolved_fields,
            "regressed_fields": regressed_fields,
        }

    if verdict == "pass":
        # HITL: pause for human confirmation before completing
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await _publish(
            task_id,
            EventType.HITL_PAUSE,
            _hitl_payload(f"QA通过(score={score:.2f})，等待人工确认发布..."),
        )
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        hitl_payload = _pop_hitl_payload(task_id, "force_pass")
        decision = hitl_payload["decision"]
        _apply_manual_url_resume(
            update,
            hitl_payload,
            current_iteration=iteration,
            max_iterations=max_iter,
        )
        await _publish(
            task_id,
            EventType.HITL_RESUME,
            {
                "decision": decision,
                "iteration": iteration,
                "urls_count": len(hitl_payload.get("urls", [])),
            },
        )

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
        if update.get("final_status") == "running":
            update.pop("completed_at", None)
        else:
            update["completed_at"] = datetime.now().isoformat()

    elif iteration >= max_iter:
        # 达到最大迭代次数，仍需人工审核（不能静默终止）
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await _publish(
            task_id,
            EventType.HITL_PAUSE,
            _hitl_payload(
                f"已达最大迭代次数({max_iter}轮)，最终 score={score:.2f}，等待人工决策..."
            ),
        )
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        hitl_payload = _pop_hitl_payload(task_id, "abort")
        decision = hitl_payload["decision"]
        _apply_manual_url_resume(
            update,
            hitl_payload,
            current_iteration=iteration,
            max_iterations=max_iter,
        )
        await _publish(
            task_id,
            EventType.HITL_RESUME,
            {
                "decision": decision,
                "iteration": iteration,
                "urls_count": len(hitl_payload.get("urls", [])),
            },
        )

        if decision == "force_pass":
            update["qa_verdict"] = "pass"
            update["final_status"] = "human_force_pass"
        elif decision == "continue" and hitl_payload.get("urls"):
            update.pop("completed_at", None)
        elif decision == "abort":
            update["qa_verdict"] = "reject"
            update["final_status"] = "human_abort"
        else:
            update["final_status"] = f"max_iterations_reached(last_verdict={verdict})"
        if update.get("final_status") == "running":
            update.pop("completed_at", None)
        else:
            update["completed_at"] = datetime.now().isoformat()
    elif verdict in ("revise", "reject"):
        # HITL: pause and wait for human decision
        # reject 也必须经过人工审核，不能直接终止任务
        pause_msg = (
            f"QA 严重不达标(score={score:.2f})，等待人工决策..."
            if verdict == "reject"
            else "QA打回，等待人工审核决策..."
        )
        gate = asyncio.Event()
        _hitl_gates[task_id] = gate
        _hitl_decisions.pop(task_id, None)
        await _publish(task_id, EventType.HITL_PAUSE, _hitl_payload(pause_msg))
        await gate.wait()
        _hitl_gates.pop(task_id, None)

        hitl_payload = _pop_hitl_payload(task_id, "continue")
        decision = hitl_payload["decision"]
        _apply_manual_url_resume(
            update,
            hitl_payload,
            current_iteration=iteration,
            max_iterations=max_iter,
        )
        await _publish(
            task_id,
            EventType.HITL_RESUME,
            {
                "decision": decision,
                "iteration": iteration,
                "urls_count": len(hitl_payload.get("urls", [])),
            },
        )

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
        dimensions: Analysis dimensions, defaults to ["pricing", "features", "user_personas"]
        industry: Industry template to apply (saas/consumer/hardware)
        max_iterations: Max QA feedback loops

    Returns:
        Final GraphState dict
    """
    from schemas.extensions import TEMPLATE_REGISTRY, load_template

    dims = dimensions or ["pricing", "features", "user_personas"]

    # Load industry template and inject extra dimensions
    industry_fields: list[str] = []
    discovery_strategy = "official_only"
    trusted_domains: list[str] = []
    if industry in TEMPLATE_REGISTRY:
        template = load_template(industry)
        industry_fields = template.get_field_names()
        discovery_strategy = template.discovery_strategy
        trusted_domains = template.trusted_domains
        # 行业模板的扩展字段也加入 collect_scope，让 Discovery 搜索词匹配行业
        # 例如消费品模板: distribution_channels, brand_sentiment, market_share 等
        dims = list(set(dims) | set(industry_fields))
        await _publish(
            task_id,
            EventType.LOG,
            {
                "message": f"已加载行业模板: {template.display_name} ({len(template.fields)}个扩展字段, 策略: {discovery_strategy})",
                "agent": "collector",
            },
        )

    # expected_dimensions 只含核心维度，行业扩展字段由 check_extensions_coverage 单独检查
    all_dimensions = ["pricing", "features", "integrations", "user_personas"]
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
        config = {"recursion_limit": max_iterations * 8 + 8}
        final_state = await app.ainvoke(initial_state, config=config)

        if "completed_at" not in final_state:
            final_state["completed_at"] = datetime.now().isoformat()
        if final_state.get("final_status") == "running":
            final_state["final_status"] = "ended"

        traces = _task_traces.pop(task_id, [])
        final_state["agent_traces"] = traces
        langfuse_trace_id = _langfuse_trace_id(task_id)
        langfuse_trace_url = _langfuse_trace_url(task_id)
        final_state["langfuse_trace_id"] = langfuse_trace_id
        final_state["langfuse_trace_url"] = langfuse_trace_url

        await _publish(
            task_id,
            EventType.COMPLETE,
            {
                "final_status": final_state.get("final_status", "ended"),
                "competitor_name": final_state.get("competitor_name", competitor_name),
                "industry": final_state.get("industry", industry),
                "qa_score": final_state.get("qa_score", 0.0),
                "report_markdown": final_state.get("report_markdown", ""),
                "feedback_history": final_state.get("feedback_history", []),
                "agent_traces": traces,
                "trace_id": task_id,
                "langfuse_trace_id": langfuse_trace_id,
                "langfuse_trace_url": langfuse_trace_url,
            },
        )

        return final_state

    except Exception as e:
        await _publish(task_id, EventType.ERROR, {"message": str(e)})
        raise
    finally:
        _task_traces.pop(task_id, None)
        await event_bus.close(task_id)
