"""Agent间通信协议 - function calling风格的结构化消息"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """消息类型"""

    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    FEEDBACK = "feedback"
    REVISION = "revision"
    STATUS_UPDATE = "status_update"


class MessageContext(BaseModel):
    """消息上下文 - 携带共享状态，避免Agent间信息丢失"""

    competitor_name: str | None = Field(
        default=None, description="当前处理的竞品名称"
    )
    schema_version: str = Field(default="1.0", description="当前使用的Schema版本")
    iteration: int = Field(default=1, ge=1, description="当前迭代轮次")
    max_iterations: int = Field(
        default=3, ge=1, description="最大迭代次数，防止死循环"
    )
    constraints: list[str] = Field(
        default_factory=list, description="约束条件列表"
    )
    previous_feedback: list[str] = Field(
        default_factory=list, description="历史反馈摘要，避免重复犯错"
    )


class AgentMessage(BaseModel):
    """Agent间通信的标准消息格式

    设计为function calling风格：
    - function_name: 要求目标Agent执行的操作
    - arguments: 操作参数
    这样所有通信可序列化、可回放、可审计。
    """

    # ---- 路由信息 ----
    message_id: str = Field(description="消息唯一ID")
    trace_id: str = Field(description="关联的任务追踪ID，贯穿整个分析流程")
    message_type: MessageType = Field(description="消息类型")
    from_agent: str = Field(description="发送方Agent角色: collector/analyst/writer/qa/orchestrator")
    to_agent: str = Field(description="接收方Agent角色")
    timestamp: datetime = Field(default_factory=datetime.now)

    # ---- function calling 载荷 ----
    function_name: str = Field(description="要求目标Agent执行的操作名称")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="操作参数，对应各Request模型"
    )

    # ---- 上下文 ----
    context: MessageContext = Field(default_factory=MessageContext)
    priority: int = Field(default=0, ge=0, le=10, description="优先级，0最低10最高")

    # ---- 溯源链 ----
    parent_message_id: str | None = Field(
        default=None, description="上游消息ID，构成消息链"
    )
    retry_of: str | None = Field(
        default=None, description="如果是重试，指向原始消息ID"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "msg_001",
                "trace_id": "trace_abc123",
                "message_type": "task_assign",
                "from_agent": "orchestrator",
                "to_agent": "collector",
                "function_name": "collect_competitor_data",
                "arguments": {
                    "target": "Notion",
                    "collect_type": "web_scrape",
                    "scope": ["pricing", "features", "integrations"],
                },
                "context": {
                    "competitor_name": "Notion",
                    "iteration": 1,
                    "max_iterations": 3,
                },
                "priority": 5,
            }
        }


# ============================================================
# 预定义的 function calling 操作参数模型
# ============================================================


class CollectRequest(BaseModel):
    """采集Agent的任务请求参数"""

    target: str = Field(description="目标竞品名称")
    collect_type: str = Field(
        description="采集类型: web_scrape/app_review/news/pricing/social_media"
    )
    scope: list[str] = Field(
        description="需要采集的具体维度，如['pricing', 'features', 'user_reviews']"
    )
    depth: str = Field(
        default="standard",
        description="采集深度: quick(仅首页)/standard(主要页面)/deep(全站)",
    )
    max_sources: int = Field(
        default=10, ge=1, le=50, description="最大采集源数量"
    )
    target_urls: list[str] = Field(
        default_factory=list,
        description="指定采集的URL列表（可选，为空则自动发现）",
    )
    language: str = Field(
        default="zh", description="优先采集的语言: zh/en/auto"
    )


class AnalyzeRequest(BaseModel):
    """分析Agent的任务请求参数"""

    analysis_type: str = Field(
        description="分析类型: feature_compare/swot/user_persona/pricing_analysis/full"
    )
    input_data_refs: list[str] = Field(
        description="输入数据的引用ID列表（指向Collector的输出）"
    )
    focus_dimensions: list[str] = Field(
        default_factory=list,
        description="重点关注的维度，如['ai_features', 'collaboration']",
    )
    our_product: str | None = Field(
        default=None, description="我方产品名称，用于对比分析"
    )
    competitors: list[str] = Field(
        default_factory=list, description="参与对比的竞品列表"
    )
    output_format: str = Field(
        default="competitor_profile",
        description="输出格式: competitor_profile/comparison_matrix/swot_only",
    )


class WriteRequest(BaseModel):
    """撰写Agent的任务请求参数"""

    report_type: str = Field(
        description="报告类型: full_report/executive_summary/comparison_table/section"
    )
    sections: list[str] = Field(
        default_factory=list,
        description="需要包含的章节，如['overview', 'feature_comparison', 'pricing', 'swot', 'recommendation']",
    )
    tone: str = Field(
        default="professional",
        description="报告语气: professional/executive/technical",
    )
    max_length: int | None = Field(
        default=None, description="最大字数限制（可选）"
    )
    language: str = Field(default="zh", description="报告语言: zh/en")
    include_charts: bool = Field(
        default=True, description="是否包含对比图表（Markdown表格）"
    )


class QAIssue(BaseModel):
    """质检发现的单个问题"""

    field_path: str = Field(
        description="问题字段的路径，如'feature_tree[0].description'或'pricing.tiers[1].price'"
    )
    issue_type: str = Field(
        description="问题类型: missing_source/low_confidence/schema_violation/factual_error/inconsistency/outdated"
    )
    description: str = Field(description="问题描述")
    severity: str = Field(description="严重程度: critical/major/minor")
    suggestion: str | None = Field(
        default=None, description="修改建议"
    )
    evidence: str | None = Field(
        default=None, description="发现问题的依据"
    )


class QAFeedback(BaseModel):
    """质检Agent的反馈结果"""

    target_agent: str = Field(
        description="反馈目标Agent: collector/analyst/writer"
    )
    issues: list[QAIssue] = Field(description="发现的问题列表")
    overall_score: float = Field(
        ge=0.0, le=1.0, description="整体质量评分"
    )
    pass_threshold: float = Field(
        default=0.7, description="通过阈值"
    )
    verdict: str = Field(
        description="判定结果: pass/revise/reject"
    )
    summary: str = Field(
        default="", description="质检总结"
    )
    checked_claims_count: int = Field(
        default=0, description="本次检查的claim总数"
    )
    verified_claims_count: int = Field(
        default=0, description="验证通过的claim数"
    )

    @property
    def verification_rate(self) -> float:
        """验证通过率"""
        if self.checked_claims_count == 0:
            return 0.0
        return self.verified_claims_count / self.checked_claims_count
