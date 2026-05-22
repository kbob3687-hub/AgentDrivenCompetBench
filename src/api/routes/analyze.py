"""分析任务路由 - POST创建 / GET状态 / GET SSE流"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.events import event_bus
from api.runner import run_analysis
from api.schemas import AnalyzeRequest, AnalyzeResponse, TaskStatus
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
    except Exception as e:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["result"] = {"error": str(e)}


@router.post("", response_model=AnalyzeResponse)
async def create_analysis(req: AnalyzeRequest) -> AnalyzeResponse:
    """创建竞品分析任务，后台异步执行"""
    task_id = str(uuid.uuid4())
    event_bus.create_task(task_id)
    task = asyncio.create_task(_run_task(task_id, req))
    _tasks[task_id] = {"status": "running", "result": None, "asyncio_task": task}
    return AnalyzeResponse(task_id=task_id, status="running")


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
    """查询任务状态和结果"""
    task_info = _tasks.get(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatus(
        task_id=task_id,
        status=task_info["status"],
        result=task_info["result"],
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
