"""QAAgent验证器 - 四项规则检查（不依赖LLM）"""

from __future__ import annotations

from typing import Any

from agents.analyst.persona_sources import can_support_user_persona
from schemas.message import QAIssue

UNTRACEABLE_SOURCE_MARKERS = (
    "推理得出",
    "基于多条claims",
    "基于多条 claims",
    "综合推理",
    "无单一原文对应",
)


def _as_text(value: Any) -> str:
    """Return a stripped string for loose LLM-produced fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    """Treat missing/null list fields as empty instead of crashing QA."""
    return value if isinstance(value, list) else []


def _iter_sources(profile: dict[str, Any]):
    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("sources"), list):
                for i, src in enumerate(obj["sources"]):
                    yield_path = f"{path}.sources[{i}]" if path else f"sources[{i}]"
                    yield yield_path, src
            for key, value in obj.items():
                next_path = f"{path}.{key}" if path else str(key)
                yield from _walk(value, next_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                yield from _walk(item, f"{path}[{i}]")

    yield from _walk(profile, "")


def check_dimension_coverage(
    claims: list[dict[str, Any]],
    expected_dimensions: list[str],
) -> tuple[list[QAIssue], list[str]]:
    """检查5：维度覆盖完整性 + 单维度深度

    业务逻辑：
    1. 期望维度必须有数据（缺失→critical，触发revise补采）
    2. 已覆盖维度的claims数量必须≥3（深度不足→major，建议补采）

    Returns:
        (issues, missing_dimensions)
    """
    issues: list[QAIssue] = []
    missing: list[str] = []
    MIN_CLAIMS_PER_DIM = 3

    if not expected_dimensions:
        return issues, missing

    # 按维度分组统计 claims
    dim_counts: dict[str, int] = {}
    for c in claims:
        dim = _as_text(c.get("dimension"))
        if dim:
            dim_counts[dim] = dim_counts.get(dim, 0) + 1

    covered_dims = set(dim_counts.keys())

    for dim in expected_dimensions:
        if dim not in covered_dims:
            # 完全缺失
            missing.append(dim)
            issues.append(
                QAIssue(
                    field_path=f"dimensions.{dim}",
                    issue_type="missing_source",
                    severity="critical",
                    description=f"期望维度'{dim}'完全缺失，profile数据不完整",
                    suggestion=f"需要补充采集'{dim}'维度的数据来源",
                    evidence=f"已覆盖: {sorted(covered_dims)}, 缺失: {dim}",
                )
            )
        elif dim_counts[dim] < MIN_CLAIMS_PER_DIM:
            # 维度覆盖了但深度不足 → 加入 missing 触发补采
            missing.append(dim)
            issues.append(
                QAIssue(
                    field_path=f"dimensions.{dim}",
                    issue_type="missing_source",
                    severity="major",
                    description=f"维度'{dim}'数据不充分，仅{dim_counts[dim]}条claim（要求≥{MIN_CLAIMS_PER_DIM}）",
                    suggestion=f"补充采集'{dim}'维度更多数据来源以提高分析深度",
                    evidence=f"dim={dim}, count={dim_counts[dim]}, threshold={MIN_CLAIMS_PER_DIM}",
                )
            )

    return issues, missing


def check_extensions_coverage(
    profile: dict[str, Any],
    industry: str,
) -> tuple[list[QAIssue], list[str]]:
    """检查6：行业模板扩展字段填充完整性

    根据行业模板定义的 required 字段，检查 profile.extensions 是否已填充。
    未填充的必填字段会触发 revise 补采。

    Returns:
        (issues, missing_extension_fields)
    """
    issues: list[QAIssue] = []
    missing: list[str] = []

    if not industry:
        return issues, missing

    try:
        from schemas.extensions import load_template

        template = load_template(industry)
    except (ValueError, ImportError):
        return issues, missing

    extensions = profile.get("extensions") or {}
    missing = template.validate_extensions(extensions)

    for field_name in missing:
        field_def = next((f for f in template.fields if f.field_name == field_name), None)
        desc = field_def.description if field_def else field_name
        issues.append(
            QAIssue(
                field_path=f"extensions.{field_name}",
                issue_type="missing_source",
                severity="major",
                description=f"行业模板必填扩展字段'{field_name}'未填充: {desc}",
                suggestion=f"补充采集'{field_name}'相关数据并在分析时填充该字段",
                evidence=f"industry={industry}, field={field_name}, required=True",
            )
        )

    return issues, missing


def check_user_persona_sourcing(
    profile: dict[str, Any],
    original_claims: list[dict[str, Any]] | None = None,
) -> list[QAIssue]:
    """检查7：UserPersona 必须有明确用户/场景来源支撑

    每个 persona 的 pain_points 必须有 sources，且 source URL 或 claim
    应明确描述用户群体、客户类型、使用场景、评价或案例。
    """
    issues: list[QAIssue] = []
    personas = _as_list(profile.get("user_personas"))

    if not personas:
        return issues

    for i, persona in enumerate(personas):
        if not isinstance(persona, dict):
            continue
        segment = _as_text(persona.get("segment")) or f"persona_{i}"
        pain_points = _as_list(persona.get("pain_points"))

        if not pain_points:
            issues.append(
                QAIssue(
                    field_path=f"user_personas[{i}].pain_points",
                    issue_type="missing_source",
                    severity="major",
                    description=f"用户画像'{segment}'缺少痛点数据",
                    suggestion="补充该用户群体的可溯源痛点、场景或评价信息",
                    evidence=f"segment={segment}, pain_points=[]",
                )
            )
            continue

        has_source = False
        has_persona_source = False
        for pp in pain_points:
            if isinstance(pp, dict):
                sources = _as_list(pp.get("sources"))
                if sources:
                    has_source = True
                    claim_text = _as_text(pp.get("claim"))
                    for source in sources:
                        if not isinstance(source, dict):
                            continue
                        source_url = _as_text(source.get("url"))
                        snippet = _as_text(source.get("snippet"))
                        if can_support_user_persona(source_url, f"{claim_text} {snippet}"):
                            has_persona_source = True
                            break
                if has_persona_source:
                    break

        if not has_source:
            issues.append(
                QAIssue(
                    field_path=f"user_personas[{i}].pain_points",
                    issue_type="missing_source",
                    severity="minor",
                    description=f"用户画像'{segment}'的痛点缺少溯源来源",
                    suggestion="确保痛点数据引用了明确描述用户/场景的原始内容",
                    evidence=f"segment={segment}, no sources found in pain_points",
                )
            )
        elif not has_persona_source:
            issues.append(
                QAIssue(
                    field_path=f"user_personas[{i}].pain_points",
                    issue_type="weak_source",
                    severity="minor",
                    description=f"用户画像'{segment}'的来源未明确指向用户群体或使用场景",
                    suggestion="优先使用客户案例、解决方案、use case、评论/评测或产品页中明确目标用户的来源",
                    evidence=f"segment={segment}, sources exist but persona relevance is weak",
                )
            )

    return issues


def check_source_coverage(profile: dict[str, Any]) -> list[QAIssue]:
    """检查1：每条claim的sources数量>=1，不够则记录问题

    注：生产环境建议>=2做交叉验证，demo阶段放宽到>=1避免过度惩罚。
    """
    issues: list[QAIssue] = []

    # 检查pricing evidence
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence") or {}
        sources = _as_list(evidence.get("sources"))
        if len(sources) < 1:
            issues.append(
                QAIssue(
                    field_path="pricing.evidence.sources",
                    issue_type="missing_source",
                    severity="major",
                    description="定价信息没有任何来源支撑",
                    suggestion="补充定价数据来源（如官网定价页、第三方评测等）",
                    evidence=f"当前sources数量: {len(sources)}",
                )
            )

    # 检查feature_tree
    for i, node in enumerate(_as_list(profile.get("feature_tree"))):
        if not isinstance(node, dict):
            continue
        desc = node.get("description") or {}
        sources = _as_list(desc.get("sources"))
        if len(sources) < 1:
            issues.append(
                QAIssue(
                    field_path=f"feature_tree[{i}].description.sources",
                    issue_type="missing_source",
                    severity="minor",
                    description=f"功能'{_as_text(node.get('name'))}'没有来源支撑",
                    suggestion="补充来源以提高可信度",
                    evidence=f"当前sources数量: {len(sources)}",
                )
            )

    # 检查SWOT
    for i, swot_item in enumerate(_as_list(profile.get("swot"))):
        if not isinstance(swot_item, dict):
            continue
        for j, item in enumerate(_as_list(swot_item.get("items"))):
            if not isinstance(item, dict):
                continue
            sources = _as_list(item.get("sources"))
            if len(sources) < 1:
                issues.append(
                    QAIssue(
                        field_path=f"swot[{i}].items[{j}].sources",
                        issue_type="missing_source",
                        severity="minor",
                        description=f"SWOT条目'{_as_text(item.get('claim'))[:50]}'缺少来源",
                        suggestion="补充支撑证据或降低该条目置信度",
                        evidence=f"category={_as_text(swot_item.get('category'))}, sources={len(sources)}",
                    )
                )

    return issues


def check_untraceable_sources(profile: dict[str, Any]) -> list[QAIssue]:
    """Reject placeholder/inference sources that cannot be clicked and verified."""
    issues: list[QAIssue] = []

    for path, src in _iter_sources(profile):
        if not isinstance(src, dict):
            issues.append(
                QAIssue(
                    field_path=path,
                    issue_type="missing_source",
                    severity="critical",
                    description="来源结构无效，无法核查",
                    suggestion="删除该结论或补充真实可点击URL来源",
                    evidence=f"{path} is not an object",
                )
            )
            continue

        url = _as_text(src.get("url"))
        title = _as_text(src.get("title"))
        snippet = _as_text(src.get("snippet"))
        combined = f"{title} {snippet}"

        if not url:
            issues.append(
                QAIssue(
                    field_path=f"{path}.url",
                    issue_type="missing_source",
                    severity="critical",
                    description="来源URL为空，最终报告不可查",
                    suggestion="删除该结论或补充真实可点击URL来源",
                    evidence=f"path={path}, title={title!r}",
                )
            )
            continue

        marker = next((m for m in UNTRACEABLE_SOURCE_MARKERS if m in combined), "")
        if marker:
            issues.append(
                QAIssue(
                    field_path=path,
                    issue_type="missing_source",
                    severity="critical",
                    description=f"来源包含不可查的推理占位文案: {marker}",
                    suggestion="删除该结论；比赛版本只允许直接来自真实URL的结论",
                    evidence=f"path={path}, url={url}",
                )
            )

    return issues


def check_snippet_existence(
    profile: dict[str, Any],
    original_claims: list[dict[str, Any]],
) -> list[QAIssue]:
    """检查2：snippet必须在原始采集文本中真实存在"""
    issues: list[QAIssue] = []

    # 收集所有原始snippets作为参考
    original_snippets: set[str] = set()
    for claim in original_claims:
        if not isinstance(claim, dict):
            continue
        for src in _as_list(claim.get("sources")):
            if not isinstance(src, dict):
                continue
            snippet = _as_text(src.get("snippet"))
            if snippet:
                original_snippets.add(snippet)

    # 检查profile中的snippets是否能在原始数据中找到
    def _check_sources(sources: list[dict], path: str) -> None:
        for k, src in enumerate(sources):
            if not isinstance(src, dict):
                continue
            snippet = _as_text(src.get("snippet"))
            if not snippet:
                continue
            # 宽松匹配：取snippet前20字符做子串搜索（LLM会paraphrase，严格匹配必然失败）
            found = any(
                snippet[:20] in orig or orig[:20] in snippet for orig in original_snippets if orig
            )
            if not found:
                issues.append(
                    QAIssue(
                        field_path=f"{path}[{k}].snippet",
                        issue_type="factual_error",
                        severity="minor",
                        description="snippet无法在原始采集数据中找到对应文本",
                        suggestion="核实该snippet是否来自实际采集内容；不可查的推理型来源必须删除",
                        evidence=f"snippet: '{snippet[:80]}...'",
                    )
                )

    # 遍历pricing
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence") or {}
        _check_sources(_as_list(evidence.get("sources")), "pricing.evidence.sources")

    # 遍历feature_tree
    for i, node in enumerate(_as_list(profile.get("feature_tree"))):
        if not isinstance(node, dict):
            continue
        desc = node.get("description") or {}
        _check_sources(_as_list(desc.get("sources")), f"feature_tree[{i}].description.sources")

    return issues


def check_consistency(profile: dict[str, Any]) -> list[QAIssue]:
    """检查3：同产品数据前后不矛盾"""
    issues: list[QAIssue] = []

    # 检查定价一致性：tiers中的价格是否与evidence描述一致
    pricing = profile.get("pricing")
    if pricing:
        tiers = _as_list(pricing.get("tiers"))
        tier_names = [_as_text(t.get("name")).lower() for t in tiers if isinstance(t, dict)]

        # 检查是否有重复层级名
        seen: set[str] = set()
        for i, name in enumerate(tier_names):
            if name in seen:
                issues.append(
                    QAIssue(
                        field_path=f"pricing.tiers[{i}].name",
                        issue_type="inconsistency",
                        severity="major",
                        description=f"定价层级名称'{name}'重复出现",
                        suggestion="合并重复层级或修正名称",
                        evidence=f"重复的tier name: {name}",
                    )
                )
            seen.add(name)

        # 检查价格是否为空
        for i, tier in enumerate(tiers):
            if not isinstance(tier, dict):
                continue
            price = _as_text(tier.get("price"))
            if not price or price == "N/A":
                issues.append(
                    QAIssue(
                        field_path=f"pricing.tiers[{i}].price",
                        issue_type="schema_violation",
                        severity="major",
                        description=f"层级'{_as_text(tier.get('name'))}'缺少价格信息",
                        suggestion="补充该层级的具体定价",
                        evidence="price field is empty or N/A",
                    )
                )

    # 检查SWOT中strengths和weaknesses是否矛盾
    swot_items = _as_list(profile.get("swot"))
    strengths_text = ""
    weaknesses_text = ""
    for item in swot_items:
        if not isinstance(item, dict):
            continue
        cat = _as_text(item.get("category"))
        claims_text = " ".join(
            _as_text(c.get("claim")) for c in _as_list(item.get("items")) if isinstance(c, dict)
        )
        if cat == "strength":
            strengths_text = claims_text
        elif cat == "weakness":
            weaknesses_text = claims_text

    # 简单矛盾检测：如果同一个关键词同时出现在优势和劣势中
    if strengths_text and weaknesses_text:
        keywords = ["免费", "定价", "AI", "协作", "集成"]
        for kw in keywords:
            if kw in strengths_text and kw in weaknesses_text:
                issues.append(
                    QAIssue(
                        field_path="swot",
                        issue_type="inconsistency",
                        severity="minor",
                        description=f"'{kw}'同时出现在优势和劣势中，需确认是否为不同角度的合理分析",
                        suggestion=f"检查关于'{kw}'的优势和劣势描述是否从不同角度阐述，如是则保留并补充说明",
                        evidence=f"keyword '{kw}' appears in both strengths and weaknesses",
                    )
                )

    return issues


def check_overall_confidence(profile: dict[str, Any]) -> tuple[float, list[QAIssue]]:
    """检查4：计算整体confidence，<0.75触发打回"""
    issues: list[QAIssue] = []
    confidences: list[float] = []

    # 收集所有confidence值
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence") or {}
        conf = evidence.get("confidence", 0)
        if conf:
            confidences.append(conf)

    for node in _as_list(profile.get("feature_tree")):
        if not isinstance(node, dict):
            continue
        desc = node.get("description") or {}
        conf = desc.get("confidence", 0)
        if conf:
            confidences.append(conf)

    for swot_item in _as_list(profile.get("swot")):
        if not isinstance(swot_item, dict):
            continue
        for item in _as_list(swot_item.get("items")):
            if not isinstance(item, dict):
                continue
            conf = item.get("confidence", 0)
            if conf:
                confidences.append(conf)

    for persona in _as_list(profile.get("user_personas")):
        if not isinstance(persona, dict):
            continue
        for claim in _as_list(persona.get("pain_points")):
            if not isinstance(claim, dict):
                continue
            conf = claim.get("confidence", 0)
            if conf:
                confidences.append(conf)
        for claim in _as_list(persona.get("satisfaction_signals")):
            if not isinstance(claim, dict):
                continue
            conf = claim.get("confidence", 0)
            if conf:
                confidences.append(conf)

    for _key, val in (profile.get("extensions") or {}).items():
        if isinstance(val, dict):
            conf = val.get("confidence", 0)
            if conf:
                confidences.append(conf)

    if not confidences:
        issues.append(
            QAIssue(
                field_path="*",
                issue_type="schema_violation",
                severity="critical",
                description="无法计算整体置信度，profile中没有任何confidence字段",
                suggestion="确保所有EvidencedClaim都包含confidence评分",
                evidence="confidences list is empty",
            )
        )
        return 0.0, issues

    avg_confidence = sum(confidences) / len(confidences)

    if avg_confidence < 0.75:
        issues.append(
            QAIssue(
                field_path="*",
                issue_type="low_confidence",
                severity="critical",
                description=f"整体平均置信度{avg_confidence:.2f}低于阈值0.75",
                suggestion="补充更多数据来源以提高置信度，或移除低置信度的不确定结论",
                evidence=f"avg_confidence={avg_confidence:.2f}, total_claims={len(confidences)}",
            )
        )

    return avg_confidence, issues


def run_all_validators(
    profile: dict[str, Any],
    original_claims: list[dict[str, Any]] | None = None,
    expected_dimensions: list[str] | None = None,
    industry: str | None = None,
) -> tuple[list[QAIssue], float, int, int, list[str]]:
    """运行所有验证器，返回(issues, avg_confidence, checked_count, verified_count, missing_dimensions)"""
    all_issues: list[QAIssue] = []
    missing_dimensions: list[str] = []

    # 检查5（优先）：维度覆盖完整性
    if expected_dimensions and original_claims is not None:
        dim_issues, missing_dimensions = check_dimension_coverage(
            original_claims, expected_dimensions
        )
        all_issues.extend(dim_issues)

    # 检查6：行业模板扩展字段填充（只影响分数，不强制打回）
    if industry:
        ext_issues, _missing_ext = check_extensions_coverage(profile, industry)
        all_issues.extend(ext_issues)
        # 扩展字段缺失不加入 missing_dimensions，避免强制 revise

    # 检查1：来源覆盖
    all_issues.extend(check_source_coverage(profile))
    all_issues.extend(check_untraceable_sources(profile))

    # 检查7：UserPersona溯源
    all_issues.extend(check_user_persona_sourcing(profile, original_claims))

    # 检查2：snippet真实性
    if original_claims:
        all_issues.extend(check_snippet_existence(profile, original_claims))

    # 检查3：一致性
    all_issues.extend(check_consistency(profile))

    # 检查4：整体confidence
    avg_confidence, conf_issues = check_overall_confidence(profile)
    all_issues.extend(conf_issues)

    # 统计
    checked = _count_claims(profile)
    critical_count = sum(1 for i in all_issues if i.severity == "critical")
    major_count = sum(1 for i in all_issues if i.severity == "major")
    verified = checked - critical_count - major_count

    return all_issues, avg_confidence, checked, max(0, verified), missing_dimensions


def _count_claims(profile: dict[str, Any]) -> int:
    """统计profile中的claim总数"""
    count = 0
    if profile.get("pricing"):
        count += 1
    count += len(_as_list(profile.get("feature_tree")))
    for swot_item in _as_list(profile.get("swot")):
        if not isinstance(swot_item, dict):
            continue
        count += len(_as_list(swot_item.get("items")))
    count += len(_as_list(profile.get("user_personas")))
    for _key, val in (profile.get("extensions") or {}).items():
        if val is not None:
            count += 1
    return max(count, 1) if profile.get("company_name") else count
