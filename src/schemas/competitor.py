"""竞品知识Schema - 竞品档案的核心数据结构定义"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """数据来源类型"""

    WEB_PAGE = "web_page"
    APP_STORE_REVIEW = "app_store_review"
    OFFICIAL_DOC = "official_doc"
    NEWS_ARTICLE = "news_article"
    USER_INTERVIEW = "user_interview"
    SURVEY = "survey"
    SEC_FILING = "sec_filing"
    SOCIAL_MEDIA = "social_media"
    TECH_BLOG = "tech_blog"


class SourceReference(BaseModel):
    """数据来源引用 - 溯源的最小单元"""

    source_type: SourceType
    url: str | None = None
    title: str = Field(default="", description="来源标题")
    snippet: str = Field(default="", description="原文摘录，用于溯源核查")
    accessed_at: datetime = Field(default_factory=datetime.now, description="访问时间")
    snapshot_hash: str | None = Field(
        default=None, description="网页快照SHA256 hash，防止源头篡改后无法验证"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "source_type": "web_page",
                "url": "https://www.notion.so/pricing",
                "title": "Notion Pricing Page",
                "snippet": "Plus plan: $10/user/month billed annually",
                "accessed_at": "2026-05-21T10:00:00Z",
                "snapshot_hash": "a1b2c3d4e5f6...",
            }
        }


class EvidencedClaim(BaseModel):
    """带溯源的分析结论 - 整个系统的核心原子单元

    每条分析结论必须携带至少一个数据来源，
    确保所有输出可追溯、可验证。
    """

    claim: str = Field(description="分析结论/事实陈述")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度，0-1")
    sources: list[SourceReference] = Field(
        min_length=1, description="数据来源列表，至少1个"
    )
    reasoning: str = Field(description="推理过程简述")
    verified_by: str | None = Field(
        default=None, description="质检Agent验证标记（agent role name）"
    )
    verified_at: datetime | None = Field(default=None, description="验证时间")

    class Config:
        json_schema_extra = {
            "example": {
                "claim": "Notion的Plus方案定价为$10/用户/月（年付）",
                "confidence": 0.95,
                "sources": [
                    {
                        "source_type": "web_page",
                        "url": "https://www.notion.so/pricing",
                        "title": "Notion Pricing",
                        "snippet": "Plus: $10 per user/month billed annually",
                        "accessed_at": "2026-05-21T10:00:00Z",
                    }
                ],
                "reasoning": "直接从官方定价页面获取，信息明确无歧义",
                "verified_by": "qa",
                "verified_at": "2026-05-21T10:05:00Z",
            }
        }


class FeatureNode(BaseModel):
    """功能树节点 - 支持层级嵌套"""

    name: str = Field(description="功能名称")
    description: EvidencedClaim = Field(description="功能描述（带溯源）")
    sub_features: list[FeatureNode] = Field(
        default_factory=list, description="子功能列表"
    )
    maturity: str | None = Field(
        default=None, description="成熟度: mvp/growing/mature/declining"
    )
    category: str | None = Field(
        default=None, description="功能分类: core/advanced/experimental"
    )


class PricingTier(BaseModel):
    """定价层级"""

    name: str = Field(description="层级名称，如Free/Plus/Business/Enterprise")
    price: str = Field(description="价格描述，如'$10/user/month'")
    billing_cycle: str | None = Field(
        default=None, description="计费周期: monthly/annually/one_time"
    )
    features: list[str] = Field(
        default_factory=list, description="该层级包含的功能列表"
    )
    limitations: list[str] = Field(
        default_factory=list, description="该层级的限制"
    )


class PricingModel(BaseModel):
    """定价模型"""

    model_config = {"protected_namespaces": ()}

    model_type: str = Field(
        description="定价模式: freemium/subscription/usage_based/one_time/hybrid"
    )
    tiers: list[PricingTier] = Field(default_factory=list, description="定价层级列表")
    currency: str = Field(default="USD", description="货币单位")
    evidence: EvidencedClaim = Field(description="定价信息来源（带溯源）")


class UserPersona(BaseModel):
    """用户画像"""

    segment: str = Field(description="用户群体名称，如'个人用户'/'中小团队'/'企业客户'")
    demographics: dict[str, Any] = Field(
        default_factory=dict, description="人口统计特征"
    )
    pain_points: list[EvidencedClaim] = Field(
        default_factory=list, description="痛点列表（带溯源）"
    )
    usage_scenarios: list[str] = Field(
        default_factory=list, description="使用场景"
    )
    satisfaction_signals: list[EvidencedClaim] = Field(
        default_factory=list, description="满意度信号（来自评论/访谈）"
    )


class SWOTItem(BaseModel):
    """SWOT分析条目"""

    category: str = Field(
        description="SWOT类别: strength/weakness/opportunity/threat"
    )
    items: list[EvidencedClaim] = Field(description="该类别下的分析条目（带溯源）")


class CompetitorProfile(BaseModel):
    """竞品档案 - 主Schema

    这是整个系统的核心输出物，所有Agent的协作目标
    就是填充和完善这个Schema。
    """

    # ---- 基础信息 ----
    company_name: str = Field(description="公司名称")
    product_name: str = Field(description="产品名称")
    website: str = Field(description="官网URL")
    industry: str = Field(description="所属行业")
    one_liner: str | None = Field(
        default=None, description="一句话产品定位"
    )
    founded_year: int | None = Field(default=None, description="成立年份")
    headquarters: str | None = Field(default=None, description="总部所在地")
    funding_stage: str | None = Field(
        default=None,
        description="融资阶段: seed/series_a/series_b/.../public",
    )
    employee_count_range: str | None = Field(
        default=None, description="员工规模: 1-10/11-50/51-200/201-1000/1000+"
    )

    # ---- 结构化分析（核心产出） ----
    feature_tree: list[FeatureNode] = Field(
        default_factory=list, description="功能树"
    )
    pricing: PricingModel | None = Field(default=None, description="定价模型")
    user_personas: list[UserPersona] = Field(
        default_factory=list, description="用户画像"
    )
    swot: list[SWOTItem] = Field(default_factory=list, description="SWOT分析")

    # ---- 动态扩展字段（行业模板注入） ----
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="动态扩展字段，由行业模板注入，value为EvidencedClaim或基础类型",
    )

    # ---- 元数据 ----
    schema_version: str = Field(default="1.0", description="Schema版本号")
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    completeness_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Schema填充完整度，自动计算",
    )

    def calculate_completeness(self) -> float:
        """计算Schema填充完整度"""
        total_fields = 0
        filled_fields = 0

        core_checks = [
            self.feature_tree,
            self.pricing,
            self.user_personas,
            self.swot,
            self.one_liner,
            self.founded_year,
            self.funding_stage,
        ]
        total_fields += len(core_checks)
        filled_fields += sum(1 for f in core_checks if f)

        if self.extensions:
            total_fields += len(self.extensions)
            filled_fields += sum(
                1 for v in self.extensions.values() if v is not None
            )

        self.completeness_score = (
            filled_fields / total_fields if total_fields > 0 else 0.0
        )
        return self.completeness_score
