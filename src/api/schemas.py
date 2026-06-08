"""API请求/响应模型"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    competitor_name: str = Field(description="竞品名称")
    dimensions: list[str] = Field(
        default=["pricing", "features", "user_personas"],
        description="分析维度列表",
    )
    industry: str = Field(default="saas", description="行业模板: saas/consumer/hardware")
    max_iterations: int = Field(default=3, ge=1, le=10, description="最大迭代次数")
    target_urls: list[str] = Field(default_factory=list, description="人工指定的种子URL列表")


class InterveneRequest(BaseModel):
    action: str = Field(description="人工介入动作: force_pass / continue / abort")
    urls: list[str] = Field(default_factory=list, description="补充的URL列表")
    reason: str = Field(default="", description="介入原因")


class AnalyzeResponse(BaseModel):
    task_id: str = Field(description="任务ID")
    status: str = Field(description="任务状态")


class TaskStatus(BaseModel):
    task_id: str
    status: str = Field(description="running / completed / failed")
    result: dict[str, Any] | None = Field(default=None, description="完成后的结果")


class HistoryItem(BaseModel):
    task_id: str
    competitor_name: str
    industry: str
    status: str
    qa_score: float | None = None
    qa_verdict: str | None = None
    iteration: int = 1
    report_length: int = 0
    sources_fetched: int = 0
    started_at: str | None = None
    completed_at: str | None = None


class PaginatedHistory(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class CompareRequest(BaseModel):
    task_ids: list[str] = Field(min_length=2, max_length=5, description="要对比的任务ID列表(2-5个)")


class ComparePricingTier(BaseModel):
    name: str
    price: str


class ComparePricing(BaseModel):
    model_type: str
    tiers: list[ComparePricingTier]
    currency: str


class CompareFeature(BaseModel):
    name: str
    category: str | None = None
    maturity: str | None = None


class ComparePersona(BaseModel):
    segment: str
    usage_scenarios: list[str]


class CompareExtensionField(BaseModel):
    field_name: str
    label: str
    field_type: str
    required: bool = False
    description: str = ""


class CompareSWOT(BaseModel):
    strength: list[str] = Field(default_factory=list)
    weakness: list[str] = Field(default_factory=list)
    opportunity: list[str] = Field(default_factory=list)
    threat: list[str] = Field(default_factory=list)


class CompareProfile(BaseModel):
    one_liner: str | None = None
    pricing: ComparePricing | None = None
    feature_tree: list[CompareFeature] = Field(default_factory=list)
    swot: CompareSWOT = Field(default_factory=CompareSWOT)
    user_personas: list[ComparePersona] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class CompareCompetitor(BaseModel):
    task_id: str
    company_name: str
    product_name: str
    industry: str
    qa_score: float
    profile: CompareProfile


class CompareResponse(BaseModel):
    competitors: list[CompareCompetitor]
    dimensions: list[str] = Field(description="有数据的维度列表")
    common_industry: str | None = None
    mixed_industries: bool = False
    extension_fields: list[CompareExtensionField] = Field(default_factory=list)
    whitespace_analysis: str = Field(default="", description="市场白地分析（LLM生成）")
