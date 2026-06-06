"""行业模板热插拔机制 - 动态Schema扩展

支持从 templates/ 目录加载 YAML 模板文件，启动时自动扫描注册。
运行时可通过 API 创建/更新/删除模板，实现真正的动态 Schema 演化。
支持跨行业模板字段映射与版本追踪。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


class ExtensionFieldDef(BaseModel):
    """扩展字段定义 - 描述一个动态字段的元信息"""

    field_name: str = Field(description="字段名称（英文snake_case）")
    field_type: str = Field(description="字段类型: string/number/boolean/list/evidenced_claim")
    description: str = Field(description="字段描述（中文）")
    required: bool = Field(default=False, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    example: Any = Field(default=None, description="示例值")


class SchemaChangeRecord(BaseModel):
    """单次 Schema 变更记录"""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    action: str = Field(description="create / update / delete")
    details: str = Field(default="", description="变更描述")
    before: dict[str, Any] | None = Field(default=None)
    after: dict[str, Any] | None = Field(default=None)


class IndustryTemplate(BaseModel):
    """行业模板定义 - 预置扩展字段集合"""

    template_id: str = Field(description="模板唯一ID")
    industry: str = Field(description="行业标识")
    display_name: str = Field(description="模板显示名称")
    description: str = Field(description="模板适用说明")
    version: str = Field(default="1.0", description="模板版本")
    fields: list[ExtensionFieldDef] = Field(default_factory=list, description="扩展字段定义列表")
    recommended_sources: list[str] = Field(
        default_factory=list,
        description="推荐的数据采集源类型",
    )
    discovery_strategy: str = Field(
        default="official_only",
        description="Discovery策略: official_only / open_search",
    )
    trusted_domains: list[str] = Field(
        default_factory=list,
        description="open_search策略下的权威媒体白名单域名",
    )

    def get_required_fields(self) -> list[ExtensionFieldDef]:
        return [f for f in self.fields if f.required]

    def get_field_names(self) -> list[str]:
        return [f.field_name for f in self.fields]

    def validate_extensions(self, extensions: dict[str, Any]) -> list[str]:
        missing = []
        for field in self.fields:
            if field.required:
                val = extensions.get(field.field_name)
                if val is None or val == "" or val == []:
                    missing.append(field.field_name)
        return missing

    def to_prompt_section(self) -> str:
        """生成供 LLM 理解的扩展字段描述片段"""
        if not self.fields:
            return ""
        lines = [f"\n## 行业扩展字段（{self.display_name}）\n"]
        for f in self.fields:
            req_tag = "[必填]" if f.required else "[可选]"
            lines.append(f"- {req_tag} **{f.field_name}** ({f.field_type}): {f.description}")
            if f.example is not None:
                lines.append(f"  示例: `{f.example}`")
        lines.append("\n请在输出 JSON 的 `extensions` 字段中填充上述扩展字段。")
        return "\n".join(lines)


# ============================================================
# Registry + Changelog
# ============================================================

TEMPLATE_REGISTRY: dict[str, IndustryTemplate] = {}
_SCHEMA_CHANGELOG: list[SchemaChangeRecord] = []


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
# Public API - Read
# ============================================================


def load_template(industry: str) -> IndustryTemplate:
    template = TEMPLATE_REGISTRY.get(industry.lower())
    if not template:
        available = list(TEMPLATE_REGISTRY.keys())
        raise ValueError(f"Unknown industry '{industry}'. Available templates: {available}")
    return template


def list_templates() -> list[dict[str, str]]:
    return [
        {
            "template_id": t.template_id,
            "industry": t.industry,
            "display_name": t.display_name,
            "description": t.description,
            "field_count": str(len(t.fields)),
            "required_field_count": str(len(t.get_required_fields())),
            "discovery_strategy": t.discovery_strategy,
        }
        for t in TEMPLATE_REGISTRY.values()
    ]


def get_template_schema(industry: str) -> dict[str, Any]:
    template = load_template(industry)
    schema: dict[str, Any] = {
        "template_id": template.template_id,
        "industry": template.industry,
        "display_name": template.display_name,
        "description": template.description,
        "version": template.version,
        "discovery_strategy": template.discovery_strategy,
        "trusted_domains": template.trusted_domains,
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


# ============================================================
# Public API - Runtime CRUD (Dynamic Schema)
# ============================================================


def create_template(data: dict[str, Any]) -> IndustryTemplate:
    """运行时创建新行业模板"""
    template = IndustryTemplate(**data)
    industry = template.industry
    if industry in TEMPLATE_REGISTRY:
        raise ValueError(f"Template '{industry}' already exists.")
    TEMPLATE_REGISTRY[industry] = template
    _persist_yaml(template)
    _record_change("create", f"Created: {template.display_name}", after=template.model_dump())
    return template


def update_template(industry: str, updates: dict[str, Any]) -> IndustryTemplate:
    """运行时更新模板，自动升级 version"""
    template = load_template(industry)
    before = template.model_dump()

    if "display_name" in updates:
        template.display_name = updates["display_name"]
    if "description" in updates:
        template.description = updates["description"]
    if "discovery_strategy" in updates:
        template.discovery_strategy = updates["discovery_strategy"]
    if "trusted_domains" in updates:
        template.trusted_domains = updates["trusted_domains"]
    if "fields" in updates:
        template.fields = [ExtensionFieldDef(**f) for f in updates["fields"]]

    parts = template.version.split(".")
    minor = int(parts[-1]) + 1 if parts else 1
    template.version = ".".join(parts[:-1] + [str(minor)]) if len(parts) > 1 else f"1.{minor}"

    TEMPLATE_REGISTRY[industry] = template
    _persist_yaml(template)
    _record_change(
        "update",
        f"Updated: {industry} → v{template.version}",
        before=before,
        after=template.model_dump(),
    )
    return template


def delete_template(industry: str) -> bool:
    """删除模板"""
    template = load_template(industry)
    before = template.model_dump()
    TEMPLATE_REGISTRY.pop(industry, None)
    for ext in (".yaml", ".yml"):
        p = TEMPLATES_DIR / f"{industry}{ext}"
        if p.exists():
            p.unlink()
    _record_change("delete", f"Deleted: {template.display_name}", before=before)
    return True


# ============================================================
# Public API - Compare + Changelog
# ============================================================


def compare_templates(industry_a: str, industry_b: str) -> dict[str, Any]:
    """对比两个行业模板的字段差异"""
    ta = load_template(industry_a)
    tb = load_template(industry_b)
    fields_a = {f.field_name for f in ta.fields}
    fields_b = {f.field_name for f in tb.fields}
    shared = sorted(fields_a & fields_b)
    only_a = sorted(fields_a - fields_b)
    only_b = sorted(fields_b - fields_a)
    all_names = sorted(fields_a | fields_b)
    return {
        "template_a": {
            "industry": ta.industry,
            "display_name": ta.display_name,
            "version": ta.version,
        },
        "template_b": {
            "industry": tb.industry,
            "display_name": tb.display_name,
            "version": tb.version,
        },
        "shared_fields": shared,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "similarity_score": round(len(shared) / max(len(all_names), 1), 2),
    }


def get_changelog(limit: int = 50) -> list[dict[str, Any]]:
    """获取 Schema 变更历史"""
    return [r.model_dump() for r in _SCHEMA_CHANGELOG[-limit:]]


# ============================================================
# Internal helpers
# ============================================================


def _persist_yaml(template: IndustryTemplate) -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{template.industry}.yaml"
    data = template.model_dump(mode="json")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _record_change(
    action: str, details: str, before: dict | None = None, after: dict | None = None
) -> None:
    _SCHEMA_CHANGELOG.append(
        SchemaChangeRecord(action=action, details=details, before=before, after=after)
    )
    if len(_SCHEMA_CHANGELOG) > 200:
        _SCHEMA_CHANGELOG.pop(0)
