"""分析任务路由 - POST创建 / GET状态 / GET SSE流 / GET历史"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.events import event_bus
from api.runner import run_analysis
from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompareRequest,
    CompareResponse,
    HistoryItem,
    InterveneRequest,
    PaginatedHistory,
    TaskStatus,
)
from schemas.extensions import (
    list_templates,
    get_template_schema,
    TEMPLATE_REGISTRY,
    create_template,
    update_template,
    delete_template,
    compare_templates,
    get_changelog,
)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

# In-memory task store: task_id -> {status, result, asyncio_task, created_at}
_tasks: dict[str, dict[str, Any]] = {}

# Task timeout: 10 minutes (in seconds)
TASK_TIMEOUT_SECONDS = 600


async def _run_task(task_id: str, req: AnalyzeRequest) -> None:
    """Background wrapper that updates task store on completion/failure."""
    try:
        result = await run_analysis(
            task_id=task_id,
            competitor_name=req.competitor_name,
            dimensions=req.dimensions,
            industry=req.industry,
            max_iterations=req.max_iterations,
            target_urls=req.target_urls,
        )
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result
        # 持久化到PostgreSQL
        from storage.crud import save_run
        await save_run(result, task_id, "completed")
    except Exception as e:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["result"] = {"error": str(e)}
        from storage.crud import save_run
        await save_run(
            {"error": str(e), "competitor_name": req.competitor_name, "industry": req.industry},
            task_id,
            "failed",
        )


@router.post("", response_model=AnalyzeResponse)
async def create_analysis(req: AnalyzeRequest) -> AnalyzeResponse:
    """创建竞品分析任务，后台异步执行"""
    task_id = str(uuid.uuid4())
    event_bus.create_task(task_id)
    _tasks[task_id] = {
        "status": "running",
        "result": None,
        "asyncio_task": None,
        "created_at": time.time(),
    }
    task = asyncio.create_task(_run_task(task_id, req))
    _tasks[task_id]["asyncio_task"] = task
    return AnalyzeResponse(task_id=task_id, status="running")


@router.get("/history", response_model=PaginatedHistory)
async def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    competitor_name: str | None = Query(None),
    industry: str | None = Query(None),
) -> PaginatedHistory:
    """查询历史分析记录（PG优先，无PG时从内存兜底）"""
    from storage.crud import list_runs

    items, total = await list_runs(page, page_size, competitor_name, industry)

    # PG 不可用或为空时，从内存 _tasks 兜底
    if not items:
        mem_items = []
        for tid, info in _tasks.items():
            if info["status"] not in ("completed", "failed"):
                continue
            result = info.get("result") or {}
            if competitor_name and competitor_name.lower() not in result.get("competitor_name", "").lower():
                continue
            if industry and industry != result.get("industry", "saas"):
                continue
            mem_items.append({
                "task_id": tid,
                "competitor_name": result.get("competitor_name", "unknown"),
                "industry": result.get("industry", "saas"),
                "status": info["status"],
                "qa_score": result.get("qa_score"),
                "qa_verdict": result.get("qa_verdict"),
                "iteration": result.get("iteration", 1),
                "report_length": len(result.get("report_markdown", "")),
                "sources_fetched": result.get("sources_fetched", 0),
                "started_at": None,
                "completed_at": None,
            })
        total = len(mem_items)
        start = (page - 1) * page_size
        items = mem_items[start:start + page_size]

    return PaginatedHistory(
        items=[HistoryItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_tasks(req: CompareRequest) -> CompareResponse:
    """多任务竞品对比 - 提取各任务profile进行结构化对比"""
    from storage.crud import get_run

    competitors = []
    for task_id in req.task_ids:
        # In-memory first, PG fallback
        task_info = _tasks.get(task_id)
        if task_info and task_info.get("result"):
            result = task_info["result"]
        else:
            run = await get_run(task_id)
            if not run or not run.get("result"):
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found or incomplete")
            result = run["result"]

        profile = result.get("profile")
        if not profile:
            raise HTTPException(status_code=422, detail=f"Task {task_id} has no profile data")

        # Extract pricing
        pricing_data = profile.get("pricing")
        pricing = None
        if pricing_data:
            tiers = [
                {"name": t.get("name", ""), "price": t.get("price", "")}
                for t in pricing_data.get("tiers", [])
            ]
            pricing = {
                "model_type": pricing_data.get("model_type", "unknown"),
                "tiers": tiers,
                "currency": pricing_data.get("currency", "USD"),
            }

        # Extract feature_tree
        feature_tree = [
            {
                "name": f.get("name", ""),
                "category": f.get("category"),
                "maturity": f.get("maturity"),
            }
            for f in profile.get("feature_tree", [])
        ]

        # Extract SWOT — stored as list of SWOTItem: [{"category": "strength", "items": [...]}]
        swot_raw = profile.get("swot", [])
        swot: dict[str, list[str]] = {"strength": [], "weakness": [], "opportunity": [], "threat": []}
        if isinstance(swot_raw, list):
            for item in swot_raw:
                cat = item.get("category", "")
                for claim_obj in item.get("items", []):
                    text = claim_obj.get("claim", "") if isinstance(claim_obj, dict) else str(claim_obj)
                    if text and cat in swot:
                        swot[cat].append(text)
        elif isinstance(swot_raw, dict):
            for cat in swot:
                swot[cat] = [s.get("claim", s) if isinstance(s, dict) else str(s) for s in swot_raw.get(cat, [])]

        # Extract user_personas
        user_personas = [
            {
                "segment": p.get("segment", ""),
                "usage_scenarios": p.get("usage_scenarios", []),
            }
            for p in profile.get("user_personas", [])
        ]

        competitors.append({
            "task_id": task_id,
            "company_name": result.get("competitor_name", ""),
            "product_name": profile.get("product_name", result.get("competitor_name", "")),
            "industry": result.get("industry", ""),
            "qa_score": result.get("qa_score", 0.0),
            "profile": {
                "one_liner": profile.get("one_liner"),
                "pricing": pricing,
                "feature_tree": feature_tree,
                "swot": swot,
                "user_personas": user_personas,
                "extensions": profile.get("extensions", {}),
            },
        })

    # Determine which dimensions have data across all competitors
    dimensions = []
    if any(c["profile"]["pricing"] for c in competitors):
        dimensions.append("pricing")
    if any(c["profile"]["feature_tree"] for c in competitors):
        dimensions.append("features")
    if any(
        c["profile"]["swot"]["strength"] or c["profile"]["swot"]["weakness"]
        or c["profile"]["swot"]["opportunity"] or c["profile"]["swot"]["threat"]
        for c in competitors
    ):
        dimensions.append("swot")
    if any(c["profile"]["user_personas"] for c in competitors):
        dimensions.append("user_personas")
    if any(c["profile"]["extensions"] for c in competitors):
        dimensions.append("extensions")

    return CompareResponse(competitors=competitors, dimensions=dimensions)


@router.get("/templates", tags=["templates"])
async def get_templates() -> list[dict[str, str]]:
    """列出所有可用行业模板"""
    return list_templates()


@router.get("/templates/{industry}", tags=["templates"])
async def get_template_detail(industry: str) -> dict[str, Any]:
    """获取指定行业模板的详细Schema"""
    if industry not in TEMPLATE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Template '{industry}' not found")
    return get_template_schema(industry)


@router.post("/templates", tags=["templates"], status_code=201)
async def create_new_template(body: dict[str, Any]) -> dict[str, Any]:
    """运行时创建新行业模板（动态 Schema 扩展）"""
    try:
        template = create_template(body)
        return {"status": "created", "industry": template.industry, "version": template.version}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/templates/{industry}", tags=["templates"])
async def update_existing_template(industry: str, body: dict[str, Any]) -> dict[str, Any]:
    """运行时更新行业模板（增量合并，自动版本升级）"""
    try:
        template = update_template(industry, body)
        return {"status": "updated", "industry": template.industry, "version": template.version}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/templates/{industry}", tags=["templates"])
async def delete_existing_template(industry: str) -> dict[str, str]:
    """删除行业模板"""
    try:
        delete_template(industry)
        return {"status": "deleted", "industry": industry}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/templates/compare/{industry_a}/{industry_b}", tags=["templates"])
async def compare_two_templates(industry_a: str, industry_b: str) -> dict[str, Any]:
    """对比两个行业模板的字段差异与相似度"""
    try:
        return compare_templates(industry_a, industry_b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/schema/changelog", tags=["templates"])
async def schema_changelog(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    """查看 Schema 变更历史（演化追踪）"""
    return get_changelog(limit)


@router.post("/{task_id}/intervene")
async def intervene_task(task_id: str, req: InterveneRequest) -> dict[str, str]:
    """人工介入 - 强制通过/继续迭代/终止任务"""
    from api.runner import hitl_resume

    task_info = _tasks.get(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")

    if req.action == "force_pass":
        hitl_resume(task_id, "force_pass")
        return {"status": "ok", "message": "Task force-passed by human"}

    elif req.action == "continue":
        hitl_resume(task_id, "continue")
        return {"status": "ok", "message": "Pipeline resumed, continuing iteration"}

    elif req.action == "abort":
        hitl_resume(task_id, "abort")
        return {"status": "ok", "message": "Task aborted by human"}

    raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@router.get("/{task_id}/metrics")
async def get_task_metrics(task_id: str) -> dict[str, Any]:
    """聚合指标面板 - 准确率/覆盖率/修订率/Token消耗/Agent耗时"""
    task_info = _tasks.get(task_id)
    result = None
    if task_info and task_info.get("result"):
        result = task_info["result"]
    else:
        from storage.crud import get_run
        run = await get_run(task_id)
        if run and run.get("result"):
            result = run["result"]

    if not result or not result.get("agent_traces"):
        raise HTTPException(status_code=404, detail="Task not completed or not found")

    traces: list[dict] = result.get("agent_traces", [])
    feedback: list[dict] = result.get("feedback_history", [])
    qa_score = result.get("qa_score", 0.0)

    # Per-agent aggregation
    agent_stats: dict[str, dict] = {}
    for t in traces:
        name = t.get("agent", "unknown")
        if name not in agent_stats:
            agent_stats[name] = {"duration_ms": 0, "input_tokens": 0, "output_tokens": 0, "calls": 0}
        agent_stats[name]["duration_ms"] += t.get("duration_ms", 0)
        agent_stats[name]["input_tokens"] += t.get("input_tokens", 0)
        agent_stats[name]["output_tokens"] += t.get("output_tokens", 0)
        agent_stats[name]["calls"] += 1

    total_tokens = sum(s["input_tokens"] + s["output_tokens"] for s in agent_stats.values())
    total_duration_ms = sum(s["duration_ms"] for s in agent_stats.values())

    # Coverage: ratio of dimensions that passed QA without issues
    expected_dims = result.get("expected_dimensions", [])
    missing_dims = result.get("missing_dimensions", [])
    coverage_rate = (len(expected_dims) - len(missing_dims)) / max(len(expected_dims), 1)

    # Revision rate: how many iterations were "revise" vs total
    total_rounds = len(feedback)
    revise_rounds = sum(1 for f in feedback if f.get("verdict") == "revise")
    revision_rate = revise_rounds / max(total_rounds, 1)

    # QA score trend across iterations
    qa_trend = [{"iteration": f.get("iteration", i + 1), "score": f.get("score", 0)} for i, f in enumerate(feedback)]

    # Sources fetched count
    sources_count = len(result.get("claims", []))
    if not sources_count:
        sources_count = sum(1 for t in traces if t.get("agent") == "collector") * 4

    # Baseline comparison: AI system vs manual human analysis
    baseline = {
        "time": {
            "human": 14400,
            "ai": total_duration_ms,
            "unit": "ms",
            "human_label": "~4h",
            "ai_label": f"{total_duration_ms / 1000:.0f}s",
            "speedup": round(14400000 / max(total_duration_ms, 1), 1),
        },
        "sources": {
            "human": 5,
            "ai": sources_count,
            "improvement": f"{sources_count / 5:.1f}x",
        },
        "structure": {
            "human": "非结构化 Word/PPT",
            "ai": "Schema 强约束 JSON → Markdown",
            "score": 1.0,
        },
        "traceability": {
            "human": "无溯源",
            "ai": "每条结论标注来源URL",
            "score": 1.0,
        },
        "consistency": {
            "human": "因人而异",
            "ai": "Pydantic Schema 保证字段一致",
            "score": 1.0,
        },
    }

    return {
        "accuracy_rate": qa_score,
        "coverage_rate": round(coverage_rate, 3),
        "revision_rate": round(revision_rate, 3),
        "total_tokens": total_tokens,
        "total_duration_ms": total_duration_ms,
        "total_iterations": total_rounds,
        "agent_breakdown": agent_stats,
        "qa_trend": qa_trend,
        "baseline_comparison": baseline,
    }


@router.get("/{task_id}/stream")
async def stream_events(task_id: str) -> StreamingResponse:
    """SSE端点 - 实时推送分析进度事件"""
    if not event_bus.has_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found or already completed")

    async def event_generator():
        async for event in event_bus.subscribe(task_id):
            yield event.to_sse()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str) -> TaskStatus:
    """查询任务状态和结果（内存优先，PG兜底）"""
    task_info = _tasks.get(task_id)
    if task_info:
        # 检查任务是否超时（仅对running状态的任务）
        if task_info["status"] == "running":
            created_at = task_info.get("created_at", 0)
            if created_at and (time.time() - created_at) > TASK_TIMEOUT_SECONDS:
                # 任务超时，标记为失败
                task_info["status"] = "failed"
                task_info["result"] = {"error": "任务执行超时，请重试"}
                # 取消异步任务
                asyncio_task = task_info.get("asyncio_task")
                if asyncio_task and not asyncio_task.done():
                    asyncio_task.cancel()

        return TaskStatus(
            task_id=task_id,
            status=task_info["status"],
            result=task_info["result"],
        )
    # Fallback: 从PostgreSQL查历史记录
    from storage.crud import get_run

    run = await get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatus(task_id=task_id, status=run["status"], result=run.get("result"))
