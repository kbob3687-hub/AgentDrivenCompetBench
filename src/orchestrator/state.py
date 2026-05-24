"""GraphState定义 - LangGraph StateGraph的状态容器

包含整个pipeline的共享状态，所有node通过读写state通信。
FeedbackRecord记录每轮QA反馈，用于答辩展示协作轨迹。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class FeedbackRecord(BaseModel):
    """单轮QA反馈记录 - 用于展示多Agent协作轨迹"""

    iteration: int = Field(description="第几轮迭代")
    verdict: str = Field(description="QA判定: pass/revise/reject")
    score: float = Field(description="质量评分")
    issues_count: int = Field(description="发现问题数")
    critical_issues: int = Field(default=0, description="严重问题数")
    action_taken: str = Field(description="采取的动作: 打回Collector/打回Analyst/通过")
    feedback_summary: str = Field(default="", description="反馈摘要")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class GraphState(TypedDict, total=False):
    """LangGraph StateGraph的状态定义

    所有node通过读写这个dict通信，避免Agent间直接耦合。
    注：agent_traces 实际由 api/runner.py 中的模块级 _task_traces 累积，
    不依赖 LangGraph 的 state reducer（早期试过 Annotated[list, operator.add]
    在 TypedDict 上不稳定，最终改为外部累加）。
    """

    # ---- 输入参数 ----
    competitor_name: str
    collect_scope: list[str]
    target_urls: list[str]
    expected_dimensions: list[str]
    industry: str
    industry_fields: list[str]

    # ---- Discovery输出 ----
    discovered_urls: list[str]
    discovery_path: str  # "warm" | "cold"
    discovery_domain: str
    discovery_queries: list[str]

    # ---- Collector输出 ----
    claims: list[dict[str, Any]]
    sources_fetched: int
    sources_failed: int
    collect_errors: list[str]

    # ---- Analyst输出 ----
    profile: dict[str, Any]
    completeness_score: float
    dimensions_analyzed: list[str]

    # ---- Writer输出 ----
    report_markdown: str
    report_length: int
    footnote_count: int

    # ---- QA输出 ----
    qa_verdict: str
    qa_score: float
    qa_issues: list[dict[str, Any]]
    qa_feedback_summary: str
    missing_dimensions: list[str]
    qa_target_agent: str

    # ---- 迭代控制 ----
    iteration: int
    max_iterations: int
    feedback_history: list[dict[str, Any]]

    # ---- 流程元数据 ----
    trace_id: str
    started_at: str
    completed_at: str
    final_status: str
    error: str
    agent_traces: list[dict[str, Any]]
