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
    supporting_claims = _claims_with_sources(supporting_claims)
    if not supporting_claims:
        return None
    confidence = llm_pricing.get("confidence") or average_confidence(supporting_claims)
    model_type = llm_pricing.get("model_type") or "subscription"
    currency = llm_pricing.get("currency") or "USD"

    tiers = []
    for tier_data in llm_pricing.get("tiers", []):
        tiers.append(
            PricingTier(
                name=tier_data.get("name", ""),
                price=tier_data.get("price", ""),
                billing_cycle=tier_data.get("billing_cycle"),
                features=tier_data.get("features", []),
                limitations=tier_data.get("limitations", []),
            )
        )

    evidence = EvidencedClaim(
        claim=_claim_text(supporting_claims),
        confidence=confidence,
        sources=_collect_sources(supporting_claims),
        reasoning="direct_claim_evidence",
    )

    return PricingModel(
        model_type=model_type,
        tiers=tiers,
        currency=currency,
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
        supporting_claims = _claims_with_sources(supporting_claims)
        if not supporting_claims:
            continue
        confidence = feat.get("confidence", average_confidence(supporting_claims))
        sources = _collect_sources(supporting_claims)

        sub_features = []
        for sub in feat.get("sub_features", []):
            sub_evidence = EvidencedClaim(
                claim=sub.get("description", sub.get("name", "")),
                confidence=confidence,
                sources=sources,
                reasoning="direct_claim_evidence",
            )
            sub_features.append(
                FeatureNode(
                    name=sub.get("name", ""),
                    description=sub_evidence,
                    maturity=sub.get("maturity"),
                    category=sub.get("category"),
                )
            )

        description_claim = EvidencedClaim(
            claim=_claim_text(supporting_claims),
            confidence=confidence,
            sources=sources,
            reasoning="direct_claim_evidence",
        )

        nodes.append(
            FeatureNode(
                name=feat.get("name", ""),
                description=description_claim,
                sub_features=sub_features,
                maturity=feat.get("maturity"),
                category=feat.get("category"),
            )
        )

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
            supporting = _claims_with_sources(supporting)
            if not supporting:
                continue
            confidence = item.get("confidence", 0.5)
            sources = _collect_sources(supporting)

            evidenced_claims.append(
                EvidencedClaim(
                    claim=_claim_text(supporting),
                    confidence=confidence,
                    sources=sources,
                    reasoning="direct_claim_evidence",
                )
            )

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
        supporting = _claims_with_sources(supporting)
        if not supporting:
            continue
        confidence = p.get("confidence", average_confidence(supporting))
        sources = _collect_sources(supporting)

        pain_claims = []
        for pain in p.get("pain_points", []):
            pain_claims.append(
                EvidencedClaim(
                    claim=pain if isinstance(pain, str) else pain.get("claim", ""),
                    confidence=confidence,
                    sources=sources,
                    reasoning="direct_claim_evidence",
                )
            )

        personas.append(
            UserPersona(
                segment=p.get("segment", "未知用户群"),
                pain_points=pain_claims,
                usage_scenarios=p.get("usage_scenarios", []),
            )
        )
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

    # 从LLM输出或原始claims中提取行业扩展字段
    extensions = _build_extensions(llm_output, original_claims)

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
        extensions=extensions,
    )
    profile.calculate_completeness()
    return profile


def _build_extensions(
    llm_output: dict[str, Any],
    original_claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """从LLM输出和原始claims中提取行业扩展字段

    优先取LLM输出中的extensions字段，
    否则从原始claims中按dimension分组提取行业相关claims。
    """
    # LLM直接输出了extensions
    llm_ext = llm_output.get("extensions", {})
    if llm_ext:
        return llm_ext

    # 从原始claims中按dimension分组，提取非核心维度的claims作为扩展字段
    core_dims = {"pricing", "features", "integrations", "ai_features", "user_personas", "unknown"}
    extensions: dict[str, Any] = {}

    dim_groups: dict[str, list[dict]] = {}
    for claim in original_claims:
        dim = claim.get("dimension", "unknown")
        if dim not in core_dims:
            dim_groups.setdefault(dim, []).append(claim)

    for dim, claims in dim_groups.items():
        if len(claims) == 1:
            extensions[dim] = {
                "claim": claims[0].get("claim", ""),
                "confidence": claims[0].get("confidence", 0.5),
                "source_url": claims[0].get("sources", [{}])[0].get("url", "")
                if claims[0].get("sources")
                else "",
            }
        else:
            extensions[dim] = [
                {
                    "claim": c.get("claim", ""),
                    "confidence": c.get("confidence", 0.5),
                    "source_url": c.get("sources", [{}])[0].get("url", "")
                    if c.get("sources")
                    else "",
                }
                for c in claims
            ]

    return extensions


def _claims_with_sources(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only claims that have at least one real, clickable source URL."""
    return [claim for claim in claims if _collect_sources([claim])]


def _claim_text(claims: list[dict[str, Any]]) -> str:
    """Use direct collected claim text instead of analyst-generated inference."""
    texts: list[str] = []
    for claim in claims:
        text = str(claim.get("claim") or "").strip()
        if text and text not in texts:
            texts.append(text)
    return "；".join(texts)


def _collect_sources(claims: list[dict[str, Any]]) -> list[SourceReference]:
    """从claims中收集所有SourceReference"""
    sources = []
    seen_urls: set[str] = set()

    for claim in claims:
        for src in claim.get("sources", []):
            url = src.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append(
                    SourceReference(
                        source_type=SourceType(src.get("source_type", "web_page")),
                        url=url,
                        title=src.get("title", ""),
                        snippet=src.get("snippet", ""),
                        accessed_at=src.get("accessed_at", datetime.now().isoformat()),
                    )
                )
    return sources
