"""行业模板热插拔机制 - 动态Schema扩展

支持从 templates/ 目录加载 YAML 模板文件，启动时自动扫描注册。
运行时可通过 reload_templates() 重新加载，实现真正的热插拔。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


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
    industry: str = Field(description="行业标识")
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
            if field.required:
                val = extensions.get(field.field_name)
                if val is None or val == "" or val == []:
                    missing.append(field.field_name)
        return missing


# ============================================================
# YAML 模板加载
# ============================================================

TEMPLATE_REGISTRY: dict[str, IndustryTemplate] = {}


def _load_yaml_template(path: Path) -> IndustryTemplate | None:
    """从单个 YAML 文件加载模板"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return IndustryTemplate(**data)
    except Exception as e:
        logger.warning(f"Failed to load template {path.name}: {e}")
        return None


def reload_templates() -> int:
    """扫描 templates/ 目录，重新加载所有 YAML 模板。返回加载成功的数量。"""
    TEMPLATE_REGISTRY.clear()
    count = 0

    if not TEMPLATES_DIR.exists():
        logger.warning(f"Templates directory not found: {TEMPLATES_DIR}")
        return 0

    for yaml_file in sorted(TEMPLATES_DIR.glob("*.yaml")):
        template = _load_yaml_template(yaml_file)
        if template:
            TEMPLATE_REGISTRY[template.industry] = template
            count += 1
            logger.info(f"Loaded template: {template.display_name} ({yaml_file.name})")

    for yml_file in sorted(TEMPLATES_DIR.glob("*.yml")):
        template = _load_yaml_template(yml_file)
        if template:
            TEMPLATE_REGISTRY[template.industry] = template
            count += 1
            logger.info(f"Loaded template: {template.display_name} ({yml_file.name})")

    return count


# 模块导入时自动加载
reload_templates()


# ============================================================
# 公共 API
# ============================================================


def load_template(industry: str) -> IndustryTemplate:
    """根据行业标识加载对应模板"""
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
        "display_name": template.display_name,
        "description": template.description,
        "version": template.version,
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
