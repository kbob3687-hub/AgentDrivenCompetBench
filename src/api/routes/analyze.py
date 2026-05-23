"""分析任务路由 - POST创建 / GET状态 / GET SSE流 / GET历史"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.events import event_bus
from api.runner import run_analysis
from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HistoryItem,
    PaginatedHistory,
    TaskStatus,
)
from schemas.extensions import list_templates, get_template_schema, TEMPLATE_REGISTRY

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

# In-memory task store: task_id -> {status, result, asyncio_task}
_tasks: dict[str, dict[str, Any]] = {}


async def _run_task(task_id: str, req: AnalyzeRequest) -> None:
    """Background wrapper that updates task store on completion/failure."""
    try:
        result = await run_analysis(
            task_id=task_id,
            competitor_name=req.competitor_name,
            dimensions=req.dimensions,
            industry=req.industry,
            max_iterations=req.max_iterations,
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
    task = asyncio.create_task(_run_task(task_id, req))
    _tasks[task_id] = {"status": "running", "result": None, "asyncio_task": task}
    return AnalyzeResponse(task_id=task_id, status="running")


@router.get("/history", response_model=PaginatedHistory)
async def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    competitor_name: str | None = Query(None),
    industry: str | None = Query(None),
) -> PaginatedHistory:
    """查询历史分析记录（分页）"""
    from storage.crud import list_runs

    items, total = await list_runs(page, page_size, competitor_name, industry)
    return PaginatedHistory(
        items=[HistoryItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


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
