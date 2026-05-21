"""行业模板热插拔机制 - 动态Schema扩展

内置三套行业模板：SaaS/消费品/硬件。
Orchestrator根据用户输入的industry字段自动选择模板，
将模板定义的扩展字段注入到CompetitorProfile.extensions中。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExtensionFieldDef(BaseModel):
    """扩展字段定义 - 描述一个动态字段的元信息"""

    field_name: str = Field(description="字段名称（英文snake_case）")
    field_type: str = Field(
        description="字段类型: string/number/boolean/list/evidenced_claim"
    )
    description: str = Field(description="字段描述（中文）")
    required: bool = Field(default=False, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    example: Any = Field(default=None, description="示例值")


class IndustryTemplate(BaseModel):
    """行业模板定义 - 预置扩展字段集合"""

    template_id: str = Field(description="模板唯一ID")
    industry: str = Field(description="行业标识: saas/consumer/hardware")
    display_name: str = Field(description="模板显示名称")
    description: str = Field(description="模板适用说明")
    version: str = Field(default="1.0", description="模板版本")
    fields: list[ExtensionFieldDef] = Field(description="扩展字段定义列表")
    recommended_sources: list[str] = Field(
        default_factory=list,
        description="推荐的数据采集源类型",
    )

    def get_required_fields(self) -> list[ExtensionFieldDef]:
        """获取所有必填扩展字段"""
        return [f for f in self.fields if f.required]

    def get_field_names(self) -> list[str]:
        """获取所有字段名"""
        return [f.field_name for f in self.fields]

    def validate_extensions(self, extensions: dict[str, Any]) -> list[str]:
        """校验extensions是否满足模板要求，返回缺失的必填字段列表"""
        missing = []
        for field in self.fields:
            if field.required and field.field_name not in extensions:
                missing.append(field.field_name)
        return missing


# ============================================================
# 内置行业模板
# ============================================================

SAAS_TEMPLATE = IndustryTemplate(
    template_id="saas_v1",
    industry="saas",
    display_name="项目管理/SaaS产品模板",
    description="适用于SaaS协作工具、项目管理、文档协作类产品（如Notion、飞书、ClickUp）",
    version="1.0",
    fields=[
        ExtensionFieldDef(
            field_name="api_openness",
            field_type="evidenced_claim",
            description="API开放程度与开发者生态（公开API数量、SDK支持、文档质量）",
            required=True,
            example="Notion提供完整的REST API，支持数据库查询、页面创建等操作，有官方SDK覆盖Python/JS/Go",
        ),
        ExtensionFieldDef(
            field_name="integration_count",
            field_type="number",
            description="第三方集成/插件数量",
            required=True,
            example=150,
        ),
        ExtensionFieldDef(
            field_name="integration_highlights",
            field_type="list",
            description="重点集成伙伴列表",
            required=False,
            example=["Slack", "Google Drive", "GitHub", "Figma"],
        ),
        ExtensionFieldDef(
            field_name="deployment_options",
            field_type="list",
            description="部署方式: cloud_only/self_hosted/hybrid/on_premise",
            required=True,
            example=["cloud_only"],
        ),
        ExtensionFieldDef(
            field_name="data_export_formats",
            field_type="list",
            description="数据导出格式支持",
            required=False,
            example=["Markdown", "CSV", "PDF", "HTML"],
        ),
        ExtensionFieldDef(
            field_name="collaboration_features",
            field_type="list",
            description="协作特性列表: real_time_editing/comments/mentions/permissions/version_history",
            required=True,
            example=["real_time_editing", "comments", "mentions", "granular_permissions"],
        ),
        ExtensionFieldDef(
            field_name="ai_features",
            field_type="evidenced_claim",
            description="AI功能集成情况（AI写作、AI搜索、AI自动化等）",
            required=True,
            example="Notion AI支持文本生成、摘要、翻译、问答，基于GPT-4，需额外付费$10/用户/月",
        ),
        ExtensionFieldDef(
            field_name="mobile_experience",
            field_type="evidenced_claim",
            description="移动端体验评价（App Store评分、功能完整度）",
            required=False,
            example="iOS 4.7分，Android 4.3分，移动端功能覆盖桌面端约80%",
        ),
        ExtensionFieldDef(
            field_name="template_marketplace",
            field_type="evidenced_claim",
            description="模板市场/社区生态",
            required=False,
            example="官方模板库1000+，社区贡献模板5000+，支持一键复制",
        ),
        ExtensionFieldDef(
            field_name="security_compliance",
            field_type="list",
            description="安全合规认证: SOC2/ISO27001/GDPR/等保",
            required=False,
            example=["SOC2 Type II", "ISO 27001", "GDPR"],
        ),
    ],
    recommended_sources=[
        "official_doc",
        "web_page",
        "app_store_review",
        "tech_blog",
    ],
)

CONSUMER_TEMPLATE = IndustryTemplate(
    template_id="consumer_v1",
    industry="consumer",
    display_name="消费品模板",
    description="适用于消费电子、快消品、零售、DTC品牌类产品",
    version="1.0",
    fields=[
        ExtensionFieldDef(
            field_name="distribution_channels",
            field_type="list",
            description="销售渠道分布: online_direct/marketplace/retail/wholesale",
            required=True,
            example=["天猫旗舰店", "京东自营", "线下专柜", "品牌官网"],
        ),
        ExtensionFieldDef(
            field_name="brand_sentiment",
            field_type="evidenced_claim",
            description="品牌舆情与口碑（社交媒体声量、NPS、用户评价趋势）",
            required=True,
            example="小红书品牌声量月均10万+笔记，正面情感占比72%",
        ),
        ExtensionFieldDef(
            field_name="market_share",
            field_type="evidenced_claim",
            description="市场份额数据（需标注数据来源和统计口径）",
            required=False,
            example="2025年Q4中国市场份额23.5%（数据来源：IDC）",
        ),
        ExtensionFieldDef(
            field_name="supply_chain_model",
            field_type="string",
            description="供应链模式: dtc/franchise/distributor/hybrid/oem",
            required=True,
            example="hybrid",
        ),
        ExtensionFieldDef(
            field_name="price_range",
            field_type="string",
            description="价格带定位: budget/mid_range/premium/luxury",
            required=True,
            example="mid_range",
        ),
        ExtensionFieldDef(
            field_name="target_demographics",
            field_type="evidenced_claim",
            description="核心目标人群画像（年龄、性别、城市线级、消费能力）",
            required=True,
            example="25-35岁女性，一二线城市，月可支配收入8000+",
        ),
        ExtensionFieldDef(
            field_name="marketing_channels",
            field_type="list",
            description="主要营销渠道: social_media/kol/tv/outdoor/search",
            required=False,
            example=["小红书种草", "抖音直播", "微信私域"],
        ),
        ExtensionFieldDef(
            field_name="product_line_breadth",
            field_type="number",
            description="产品线SKU数量",
            required=False,
            example=45,
        ),
        ExtensionFieldDef(
            field_name="sustainability_initiatives",
            field_type="evidenced_claim",
            description="ESG/可持续发展举措",
            required=False,
            example="2025年实现包装100%可回收，碳中和认证",
        ),
    ],
    recommended_sources=[
        "web_page",
        "news_article",
        "social_media",
        "app_store_review",
    ],
)

HARDWARE_TEMPLATE = IndustryTemplate(
    template_id="hardware_v1",
    industry="hardware",
    display_name="硬件/智能设备模板",
    description="适用于智能硬件、IoT设备、消费电子、机器人等产品",
    version="1.0",
    fields=[
        ExtensionFieldDef(
            field_name="core_specs",
            field_type="list",
            description="核心硬件参数列表（处理器/内存/存储/传感器等关键规格）",
            required=True,
            example=[
                {"spec": "处理器", "value": "Apple M3 Pro"},
                {"spec": "内存", "value": "18GB统一内存"},
                {"spec": "存储", "value": "512GB SSD"},
            ],
        ),
        ExtensionFieldDef(
            field_name="ecosystem_lock_in",
            field_type="evidenced_claim",
            description="生态锁定程度（与其他设备/服务的绑定深度、迁移成本）",
            required=True,
            example="深度绑定Apple生态：iCloud、AirDrop、Handoff、Universal Control，迁移到Windows/Android成本极高",
        ),
        ExtensionFieldDef(
            field_name="repairability_score",
            field_type="number",
            description="可维修性评分（1-10，参考iFixit标准）",
            required=False,
            example=4,
        ),
        ExtensionFieldDef(
            field_name="certifications",
            field_type="list",
            description="认证与合规: FCC/CE/3C/IP等级/MIL-STD等",
            required=True,
            example=["FCC", "CE", "3C", "IP68", "MIL-STD-810H"],
        ),
        ExtensionFieldDef(
            field_name="manufacturing_origin",
            field_type="string",
            description="制造产地/代工厂信息",
            required=False,
            example="中国大陆（富士康/和硕代工）",
        ),
        ExtensionFieldDef(
            field_name="update_policy",
            field_type="evidenced_claim",
            description="软件/固件更新策略（更新频率、支持年限）",
            required=True,
            example="承诺5年系统更新+3年安全更新，月度安全补丁",
        ),
        ExtensionFieldDef(
            field_name="connectivity",
            field_type="list",
            description="连接方式: wifi/bluetooth/usb_c/thunderbolt/nfc/5g/zigbee",
            required=True,
            example=["WiFi 6E", "Bluetooth 5.3", "USB-C (Thunderbolt 4)", "NFC"],
        ),
        ExtensionFieldDef(
            field_name="battery_life",
            field_type="evidenced_claim",
            description="续航表现（官方标称 vs 实测）",
            required=False,
            example="官方标称18小时，实测混合使用约14小时（来源：Tom's Hardware评测）",
        ),
        ExtensionFieldDef(
            field_name="after_sales_policy",
            field_type="evidenced_claim",
            description="售后政策（保修期限、维修网络、退换货政策）",
            required=False,
            example="1年有限保修，可购买AppleCare+延长至3年，全国500+授权服务点",
        ),
    ],
    recommended_sources=[
        "official_doc",
        "tech_blog",
        "web_page",
        "news_article",
    ],
)


# ============================================================
# 模板注册表
# ============================================================

TEMPLATE_REGISTRY: dict[str, IndustryTemplate] = {
    "saas": SAAS_TEMPLATE,
    "consumer": CONSUMER_TEMPLATE,
    "hardware": HARDWARE_TEMPLATE,
}


def load_template(industry: str) -> IndustryTemplate:
    """根据行业标识加载对应模板

    Args:
        industry: 行业标识，支持 saas/consumer/hardware

    Returns:
        对应的行业模板

    Raises:
        ValueError: 未知的行业标识
    """
    template = TEMPLATE_REGISTRY.get(industry.lower())
    if not template:
        available = list(TEMPLATE_REGISTRY.keys())
        raise ValueError(
            f"Unknown industry '{industry}'. Available templates: {available}"
        )
    return template


def list_templates() -> list[dict[str, str]]:
    """列出所有可用模板的摘要信息"""
    return [
        {
            "template_id": t.template_id,
            "industry": t.industry,
            "display_name": t.display_name,
            "description": t.description,
            "field_count": str(len(t.fields)),
            "required_field_count": str(len(t.get_required_fields())),
        }
        for t in TEMPLATE_REGISTRY.values()
    ]


def get_template_schema(industry: str) -> dict[str, Any]:
    """获取模板的JSON Schema表示（用于前端展示）"""
    template = load_template(industry)
    schema: dict[str, Any] = {
        "template_id": template.template_id,
        "industry": template.industry,
        "fields": {},
    }
    for field in template.fields:
        schema["fields"][field.field_name] = {
            "type": field.field_type,
            "description": field.description,
            "required": field.required,
            "example": field.example,
        }
    return schema
