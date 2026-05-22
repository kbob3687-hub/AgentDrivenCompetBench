"""API请求/响应模型"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    competitor_name: str = Field(description="竞品名称")
    dimensions: list[str] = Field(
        default=["pricing", "features"],
        description="分析维度列表",
    )
    industry: str = Field(default="saas", description="行业模板: saas/consumer/hardware")
    max_iterations: int = Field(default=3, ge=1, le=10, description="最大迭代次数")


class AnalyzeResponse(BaseModel):
    task_id: str = Field(description="任务ID")
    status: str = Field(description="任务状态")


class TaskStatus(BaseModel):
    task_id: str
    status: str = Field(description="running / completed / failed")
    result: dict[str, Any] | None = Field(default=None, description="完成后的结果")
