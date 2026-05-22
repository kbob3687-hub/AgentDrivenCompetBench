"""QAAgent验证器 - 四项规则检查（不依赖LLM）"""

from __future__ import annotations

from typing import Any

from schemas.message import QAIssue


def check_dimension_coverage(
    claims: list[dict[str, Any]],
    expected_dimensions: list[str],
) -> tuple[list[QAIssue], list[str]]:
    """检查5：维度覆盖完整性 - 是否所有期望维度都有数据

    这是真实业务逻辑：如果用户期望分析pricing+features+integrations，
    但Collector只采了pricing，QA应该打回要求补采。

    Returns:
        (issues, missing_dimensions)
    """
    issues: list[QAIssue] = []
    missing: list[str] = []

    if not expected_dimensions:
        return issues, missing

    covered_dims = set(c.get("dimension", "") for c in claims if c.get("dimension"))

    for dim in expected_dimensions:
        if dim not in covered_dims:
            missing.append(dim)
            issues.append(QAIssue(
                field_path=f"dimensions.{dim}",
                issue_type="missing_source",
                severity="critical",
                description=f"期望维度'{dim}'完全缺失，profile数据不完整",
                suggestion=f"需要补充采集'{dim}'维度的数据来源",
                evidence=f"已覆盖: {sorted(covered_dims)}, 缺失: {dim}",
            ))

    return issues, missing


def check_source_coverage(profile: dict[str, Any]) -> list[QAIssue]:
    """检查1：每条claim的sources数量>=1，不够则记录问题

    注：生产环境建议>=2做交叉验证，demo阶段放宽到>=1避免过度惩罚。
    """
    issues: list[QAIssue] = []

    # 检查pricing evidence
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence", {})
        sources = evidence.get("sources", [])
        if len(sources) < 1:
            issues.append(QAIssue(
                field_path="pricing.evidence.sources",
                issue_type="missing_source",
                severity="major",
                description=f"定价信息没有任何来源支撑",
                suggestion="补充定价数据来源（如官网定价页、第三方评测等）",
                evidence=f"当前sources数量: {len(sources)}",
            ))

    # 检查feature_tree
    for i, node in enumerate(profile.get("feature_tree", [])):
        desc = node.get("description", {})
        sources = desc.get("sources", [])
        if len(sources) < 1:
            issues.append(QAIssue(
                field_path=f"feature_tree[{i}].description.sources",
                issue_type="missing_source",
                severity="minor",
                description=f"功能'{node.get('name', '')}'没有来源支撑",
                suggestion="补充来源以提高可信度",
                evidence=f"当前sources数量: {len(sources)}",
            ))

    # 检查SWOT
    for i, swot_item in enumerate(profile.get("swot", [])):
        for j, item in enumerate(swot_item.get("items", [])):
            sources = item.get("sources", [])
            if len(sources) < 1:
                issues.append(QAIssue(
                    field_path=f"swot[{i}].items[{j}].sources",
                    issue_type="missing_source",
                    severity="minor",
                    description=f"SWOT条目'{item.get('claim', '')[:50]}'缺少来源",
                    suggestion="补充支撑证据或降低该条目置信度",
                    evidence=f"category={swot_item.get('category')}, sources={len(sources)}",
                ))

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
        for src in claim.get("sources", []):
            snippet = src.get("snippet", "").strip()
            if snippet:
                original_snippets.add(snippet)

    # 检查profile中的snippets是否能在原始数据中找到
    def _check_sources(sources: list[dict], path: str) -> None:
        for k, src in enumerate(sources):
            snippet = src.get("snippet", "").strip()
            if not snippet:
                continue
            # 检查snippet是否在任何原始snippet中出现（子串匹配）
            found = any(
                snippet[:30] in orig or orig[:30] in snippet
                for orig in original_snippets
                if orig
            )
            if not found and snippet != "基于多条claims综合推理，无单一原文对应":
                issues.append(QAIssue(
                    field_path=f"{path}[{k}].snippet",
                    issue_type="factual_error",
                    severity="major",
                    description=f"snippet无法在原始采集数据中找到对应文本",
                    suggestion="核实该snippet是否来自实际采集内容，或标记为推理得出",
                    evidence=f"snippet: '{snippet[:80]}...'",
                ))

    # 遍历pricing
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence", {})
        _check_sources(evidence.get("sources", []), "pricing.evidence.sources")

    # 遍历feature_tree
    for i, node in enumerate(profile.get("feature_tree", [])):
        desc = node.get("description", {})
        _check_sources(desc.get("sources", []), f"feature_tree[{i}].description.sources")

    return issues


def check_consistency(profile: dict[str, Any]) -> list[QAIssue]:
    """检查3：同产品数据前后不矛盾"""
    issues: list[QAIssue] = []

    # 检查定价一致性：tiers中的价格是否与evidence描述一致
    pricing = profile.get("pricing")
    if pricing:
        tiers = pricing.get("tiers", [])
        tier_names = [t.get("name", "").lower() for t in tiers]

        # 检查是否有重复层级名
        seen: set[str] = set()
        for i, name in enumerate(tier_names):
            if name in seen:
                issues.append(QAIssue(
                    field_path=f"pricing.tiers[{i}].name",
                    issue_type="inconsistency",
                    severity="major",
                    description=f"定价层级名称'{name}'重复出现",
                    suggestion="合并重复层级或修正名称",
                    evidence=f"重复的tier name: {name}",
                ))
            seen.add(name)

        # 检查价格是否为空
        for i, tier in enumerate(tiers):
            price = tier.get("price", "")
            if not price or price == "N/A":
                issues.append(QAIssue(
                    field_path=f"pricing.tiers[{i}].price",
                    issue_type="schema_violation",
                    severity="major",
                    description=f"层级'{tier.get('name', '')}'缺少价格信息",
                    suggestion="补充该层级的具体定价",
                    evidence=f"price field is empty or N/A",
                ))

    # 检查SWOT中strengths和weaknesses是否矛盾
    swot_items = profile.get("swot", [])
    strengths_text = ""
    weaknesses_text = ""
    for item in swot_items:
        cat = item.get("category", "")
        claims_text = " ".join(c.get("claim", "") for c in item.get("items", []))
        if cat == "strength":
            strengths_text = claims_text
        elif cat == "weakness":
            weaknesses_text = claims_text

    # 简单矛盾检测：如果同一个关键词同时出现在优势和劣势中
    if strengths_text and weaknesses_text:
        keywords = ["免费", "定价", "AI", "协作", "集成"]
        for kw in keywords:
            if kw in strengths_text and kw in weaknesses_text:
                issues.append(QAIssue(
                    field_path="swot",
                    issue_type="inconsistency",
                    severity="minor",
                    description=f"'{kw}'同时出现在优势和劣势中，需确认是否为不同角度的合理分析",
                    suggestion=f"检查关于'{kw}'的优势和劣势描述是否从不同角度阐述，如是则保留并补充说明",
                    evidence=f"keyword '{kw}' appears in both strengths and weaknesses",
                ))

    return issues


def check_overall_confidence(profile: dict[str, Any]) -> tuple[float, list[QAIssue]]:
    """检查4：计算整体confidence，<0.75触发打回"""
    issues: list[QAIssue] = []
    confidences: list[float] = []

    # 收集所有confidence值
    pricing = profile.get("pricing")
    if pricing:
        evidence = pricing.get("evidence", {})
        conf = evidence.get("confidence", 0)
        if conf:
            confidences.append(conf)

    for node in profile.get("feature_tree", []):
        desc = node.get("description", {})
        conf = desc.get("confidence", 0)
        if conf:
            confidences.append(conf)

    for swot_item in profile.get("swot", []):
        for item in swot_item.get("items", []):
            conf = item.get("confidence", 0)
            if conf:
                confidences.append(conf)

    if not confidences:
        issues.append(QAIssue(
            field_path="*",
            issue_type="schema_violation",
            severity="critical",
            description="无法计算整体置信度，profile中没有任何confidence字段",
            suggestion="确保所有EvidencedClaim都包含confidence评分",
            evidence="confidences list is empty",
        ))
        return 0.0, issues

    avg_confidence = sum(confidences) / len(confidences)

    if avg_confidence < 0.75:
        issues.append(QAIssue(
            field_path="*",
            issue_type="low_confidence",
            severity="critical",
            description=f"整体平均置信度{avg_confidence:.2f}低于阈值0.75",
            suggestion="补充更多数据来源以提高置信度，或移除低置信度的不确定结论",
            evidence=f"avg_confidence={avg_confidence:.2f}, total_claims={len(confidences)}",
        ))

    return avg_confidence, issues


def run_all_validators(
    profile: dict[str, Any],
    original_claims: list[dict[str, Any]] | None = None,
    expected_dimensions: list[str] | None = None,
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

    # 检查1：来源覆盖
    all_issues.extend(check_source_coverage(profile))

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
    count += len(profile.get("feature_tree", []))
    for swot_item in profile.get("swot", []):
        count += len(swot_item.get("items", []))
    return count
