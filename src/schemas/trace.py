"""可观测性数据模型 - Trace/Span/Feedback记录"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SpanKind(str, Enum):
    """Span类型 - 对齐Langfuse的span分类"""

    AGENT_INVOCATION = "agent_invocation"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    VALIDATION = "validation"
    FEEDBACK_LOOP = "feedback_loop"
    RETRIEVAL = "retrieval"
    SERIALIZATION = "serialization"


class TraceSpan(BaseModel):
    """单个操作的追踪记录

    对齐Langfuse数据模型，每个span代表一次原子操作。
    span之间通过parent_span_id构成树形结构。
    """

    # ---- 标识 ----
    trace_id: str = Field(description="顶层任务ID，贯穿整个分析流程")
    span_id: str = Field(description="当前操作的唯一ID")
    parent_span_id: str | None = Field(default=None, description="父操作ID，构成树形追踪结构")

    # ---- 描述 ----
    name: str = Field(description="操作名称，如'collector.scrape_pricing'")
    kind: SpanKind = Field(description="操作类型")
    agent_role: str = Field(
        description="产生此span的Agent角色: collector/analyst/writer/qa/orchestrator"
    )

    # ---- 时间 ----
    start_time: datetime = Field(description="开始时间")
    end_time: datetime | None = Field(default=None, description="结束时间")
    duration_ms: int | None = Field(default=None, ge=0, description="耗时（毫秒）")

    # ---- 输入输出（完整记录，支持决策回放） ----
    input_data: dict[str, Any] = Field(default_factory=dict, description="操作输入")
    output_data: dict[str, Any] = Field(default_factory=dict, description="操作输出")

    # ---- LLM调用详情 ----
    model: str | None = Field(
        default=None, description="使用的模型，如'claude-sonnet-4-6-20250514'"
    )
    prompt_tokens: int | None = Field(default=None, ge=0, description="输入token数")
    completion_tokens: int | None = Field(default=None, ge=0, description="输出token数")
    total_cost_usd: float | None = Field(default=None, ge=0, description="本次调用成本（美元）")

    # ---- 状态 ----
    status: str = Field(
        default="running",
        description="状态: running/completed/failed/retried",
    )
    error: str | None = Field(default=None, description="错误信息（如果失败）")
    retry_count: int = Field(default=0, ge=0, description="重试次数")

    # ---- 元数据 ----
    metadata: dict[str, Any] = Field(default_factory=dict, description="自定义元数据")

    def complete(self, output: dict[str, Any] | None = None) -> None:
        """标记span完成"""
        self.end_time = datetime.now()
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_ms = int(delta.total_seconds() * 1000)
        self.status = "completed"
        if output:
            self.output_data = output

    def fail(self, error: str) -> None:
        """标记span失败"""
        self.end_time = datetime.now()
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_ms = int(delta.total_seconds() * 1000)
        self.status = "failed"
        self.error = error


class FeedbackRecord(BaseModel):
    """反馈闭环记录

    这是证明QA打回机制真实有效的关键数据结构。
    记录了：谁打回了谁、为什么打回、修正前后的内容对比、改善程度。
    答辩时展示这个数据结构的实例，证明闭环非伪造。
    """

    feedback_id: str = Field(description="反馈记录唯一ID")
    trace_id: str = Field(description="关联的任务追踪ID")
    from_agent: str = Field(description="发起反馈的Agent（通常是qa）")
    to_agent: str = Field(description="被打回的Agent")

    # ---- 问题描述 ----
    issue_type: str = Field(
        description="问题类型: missing_source/low_confidence/schema_violation/factual_error/inconsistency"
    )
    issue_description: str = Field(description="问题详细描述")
    severity: str = Field(default="major", description="严重程度: critical/major/minor")

    # ---- 修正前后对比（核心：证明改善） ----
    original_content: dict[str, Any] = Field(description="修正前的内容")
    revised_content: dict[str, Any] | None = Field(
        default=None, description="修正后的内容（resolved后填充）"
    )
    improvement_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="修正前后质量对比分，>0.5表示有改善",
    )

    # ---- 状态 ----
    resolved: bool = Field(default=False, description="是否已解决")
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: datetime | None = Field(default=None, description="解决时间")
    iteration: int = Field(default=1, description="第几轮反馈")

    def resolve(self, revised_content: dict[str, Any], improvement_score: float) -> None:
        """标记反馈已解决"""
        self.revised_content = revised_content
        self.improvement_score = improvement_score
        self.resolved = True
        self.resolved_at = datetime.now()


class TaskTrace(BaseModel):
    """一次完整竞品分析任务的追踪记录

    顶层追踪对象，包含所有span和反馈记录。
    对应Langfuse中的一个trace。
    """

    trace_id: str = Field(description="任务唯一ID")
    task_name: str = Field(description="任务名称，如'Notion vs Feishu vs ClickUp竞品分析'")
    target_competitors: list[str] = Field(description="目标竞品列表")
    industry: str = Field(description="所属行业")

    # ---- 时间 ----
    initiated_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(default=None, description="完成时间")

    # ---- 状态 ----
    status: str = Field(
        default="running",
        description="任务状态: pending/running/completed/failed/cancelled",
    )

    # ---- 追踪数据 ----
    spans: list[TraceSpan] = Field(default_factory=list, description="所有操作span")
    feedback_loops: list[FeedbackRecord] = Field(
        default_factory=list, description="所有反馈闭环记录"
    )

    # ---- 统计 ----
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="总成本")
    total_tokens: int = Field(default=0, ge=0, description="总token消耗")
    total_llm_calls: int = Field(default=0, ge=0, description="LLM调用总次数")
    total_feedback_rounds: int = Field(default=0, ge=0, description="反馈闭环触发总次数")

    def add_span(self, span: TraceSpan) -> None:
        """添加span并更新统计"""
        self.spans.append(span)
        if span.prompt_tokens:
            self.total_tokens += span.prompt_tokens
        if span.completion_tokens:
            self.total_tokens += span.completion_tokens
        if span.total_cost_usd:
            self.total_cost_usd += span.total_cost_usd
        if span.kind == SpanKind.LLM_CALL:
            self.total_llm_calls += 1

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        """添加反馈记录"""
        self.feedback_loops.append(feedback)
        self.total_feedback_rounds += 1

    def complete(self) -> None:
        """标记任务完成"""
        self.completed_at = datetime.now()
        self.status = "completed"

    @property
    def duration_seconds(self) -> float | None:
        """任务总耗时（秒）"""
        if self.completed_at:
            return (self.completed_at - self.initiated_at).total_seconds()
        return None
