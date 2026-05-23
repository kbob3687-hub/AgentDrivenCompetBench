"""AnalystAgent分析工具 - Claims聚合与Profile构建"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.competitor import (
    CompetitorProfile,
    EvidencedClaim,
    FeatureNode,
    PricingModel,
    PricingTier,
    SourceReference,
    SourceType,
    SWOTItem,
    UserPersona,
)


def group_claims_by_dimension(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """将claims按dimension字段分组"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        dim = claim.get("dimension", "unknown")
        groups.setdefault(dim, []).append(claim)
    return groups


def average_confidence(claims: list[dict[str, Any]]) -> float:
    """计算一组claims的平均置信度"""
    if not claims:
        return 0.0
    total = sum(c.get("confidence", 0.5) for c in claims)
    return round(total / len(claims), 2)


def build_pricing_model(
    llm_pricing: dict[str, Any],
    original_claims: list[dict[str, Any]],
) -> PricingModel | None:
    """从LLM分析结果构建PricingModel对象"""
    if not llm_pricing:
        return None

    indices = llm_pricing.get("evidence_claim_indices", [])
    supporting_claims = [original_claims[i] for i in indices if i < len(original_claims)]
    confidence = llm_pricing.get("confidence", average_confidence(supporting_claims))

    tiers = []
    for tier_data in llm_pricing.get("tiers", []):
        tiers.append(PricingTier(
            name=tier_data.get("name", ""),
            price=tier_data.get("price", ""),
            billing_cycle=tier_data.get("billing_cycle"),
            features=tier_data.get("features", []),
            limitations=tier_data.get("limitations", []),
        ))

    sources = _collect_sources(supporting_claims)

    evidence = EvidencedClaim(
        claim=f"定价模式为{llm_pricing.get('model_type', 'unknown')}，共{len(tiers)}个层级",
        confidence=confidence,
        sources=sources if sources else [_placeholder_source()],
        reasoning=f"基于{len(supporting_claims)}条原始claims综合分析",
    )

    return PricingModel(
        model_type=llm_pricing.get("model_type", "subscription"),
        tiers=tiers,
        currency=llm_pricing.get("currency", "USD"),
        evidence=evidence,
    )


def build_feature_tree(
    llm_features: list[dict[str, Any]] | None,
    original_claims: list[dict[str, Any]],
) -> list[FeatureNode]:
    """从LLM分析结果构建FeatureNode列表"""
    if not llm_features:
        return []
    nodes = []
    for feat in llm_features:
        indices = feat.get("evidence_claim_indices", [])
        supporting_claims = [original_claims[i] for i in indices if i < len(original_claims)]
        confidence = feat.get("confidence", average_confidence(supporting_claims))
        sources = _collect_sources(supporting_claims)

        sub_features = []
        for sub in feat.get("sub_features", []):
            sub_evidence = EvidencedClaim(
                claim=sub.get("description", sub.get("name", "")),
                confidence=confidence,
                sources=sources if sources else [_placeholder_source()],
                reasoning="从父功能claims继承",
            )
            sub_features.append(FeatureNode(
                name=sub.get("name", ""),
                description=sub_evidence,
                maturity=sub.get("maturity"),
                category=sub.get("category"),
            ))

        description_claim = EvidencedClaim(
            claim=feat.get("description", feat.get("name", "")),
            confidence=confidence,
            sources=sources if sources else [_placeholder_source()],
            reasoning=f"基于{len(supporting_claims)}条claims归纳",
        )

        nodes.append(FeatureNode(
            name=feat.get("name", ""),
            description=description_claim,
            sub_features=sub_features,
            maturity=feat.get("maturity"),
            category=feat.get("category"),
        ))

    return nodes


def build_swot(
    llm_swot: dict[str, Any] | None,
    original_claims: list[dict[str, Any]],
) -> list[SWOTItem]:
    """从LLM分析结果构建SWOT列表"""
    if not llm_swot:
        return []
    swot_items = []
    category_map = {
        "strengths": "strength",
        "weaknesses": "weakness",
        "opportunities": "opportunity",
        "threats": "threat",
    }

    for key, category in category_map.items():
        items_data = llm_swot.get(key, [])
        evidenced_claims = []

        for item in items_data:
            indices = item.get("evidence_claim_indices", [])
            supporting = [original_claims[i] for i in indices if i < len(original_claims)]
            confidence = item.get("confidence", 0.5)
            sources = _collect_sources(supporting)

            evidenced_claims.append(EvidencedClaim(
                claim=item.get("item", ""),
                confidence=confidence,
                sources=sources if sources else [_placeholder_source()],
                reasoning=f"SWOT分析推理，基于{len(supporting)}条claims",
            ))

        if evidenced_claims:
            swot_items.append(SWOTItem(category=category, items=evidenced_claims))

    return swot_items


def build_user_personas(
    llm_personas: list[dict[str, Any]] | None,
    original_claims: list[dict[str, Any]],
) -> list[UserPersona]:
    """从LLM分析结果构建UserPersona列表"""
    if not llm_personas:
        return []
    personas = []
    for p in llm_personas:
        indices = p.get("evidence_claim_indices", [])
        supporting = [original_claims[i] for i in indices if i < len(original_claims)]
        confidence = p.get("confidence", average_confidence(supporting))
        sources = _collect_sources(supporting)

        pain_claims = []
        for pain in p.get("pain_points", []):
            pain_claims.append(EvidencedClaim(
                claim=pain if isinstance(pain, str) else pain.get("claim", ""),
                confidence=confidence,
                sources=sources if sources else [_placeholder_source()],
                reasoning="基于用户相关claims推断",
            ))

        personas.append(UserPersona(
            segment=p.get("segment", "未知用户群"),
            pain_points=pain_claims,
            usage_scenarios=p.get("usage_scenarios", []),
        ))
    return personas


def build_competitor_profile(
    competitor_name: str,
    llm_output: dict[str, Any],
    original_claims: list[dict[str, Any]],
) -> CompetitorProfile:
    """从LLM分析结果构建完整的CompetitorProfile"""
    pricing = build_pricing_model(llm_output.get("pricing"), original_claims)
    feature_tree = build_feature_tree(llm_output.get("feature_tree") or [], original_claims)
    swot = build_swot(llm_output.get("swot") or {}, original_claims)
    user_personas = build_user_personas(llm_output.get("user_personas") or [], original_claims)

    profile = CompetitorProfile(
        company_name=llm_output.get("company_name", competitor_name),
        product_name=llm_output.get("product_name", competitor_name),
        website=llm_output.get("website", ""),
        industry=llm_output.get("industry", "project_management_saas"),
        one_liner=llm_output.get("one_liner"),
        feature_tree=feature_tree,
        pricing=pricing,
        swot=swot,
        user_personas=user_personas,
    )
    profile.calculate_completeness()
    return profile


def _collect_sources(claims: list[dict[str, Any]]) -> list[SourceReference]:
    """从claims中收集所有SourceReference"""
    sources = []
    seen_urls: set[str] = set()

    for claim in claims:
        for src in claim.get("sources", []):
            url = src.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append(SourceReference(
                    source_type=SourceType(src.get("source_type", "web_page")),
                    url=url,
                    title=src.get("title", ""),
                    snippet=src.get("snippet", ""),
                    accessed_at=src.get("accessed_at", datetime.now().isoformat()),
                ))
    return sources


def _placeholder_source() -> SourceReference:
    """当没有可用source时的占位符"""
    return SourceReference(
        source_type=SourceType.WEB_PAGE,
        url="",
        title="推理得出",
        snippet="基于多条claims综合推理，无单一原文对应",
        accessed_at=datetime.now(),
    )
