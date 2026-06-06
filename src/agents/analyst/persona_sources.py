"""Helpers for deciding whether a claim can support user personas."""

from __future__ import annotations

PERSONA_SOURCE_URL_KEYWORDS = (
    "/customers",
    "/customer-stories",
    "/case-studies",
    "/case-study",
    "/success-stories",
    "/stories",
    "/solutions",
    "/use-cases",
    "/usecases",
    "/reviews",
    "/testimonials",
    "/community",
    "/explore",
)

PERSONA_CLAIM_KEYWORDS = (
    "用户",
    "客户",
    "团队",
    "企业",
    "个人",
    "学生",
    "创作者",
    "开发者",
    "设计师",
    "营销",
    "销售",
    "客服",
    "场景",
    "适合",
    "面向",
    "目标人群",
    "customer",
    "customers",
    "user",
    "users",
    "team",
    "teams",
    "enterprise",
    "business",
    "student",
    "creator",
    "developer",
    "designer",
    "marketer",
    "sales",
    "support",
    "use case",
    "use-case",
    "persona",
)


def is_persona_source_url(url: str) -> bool:
    normalized = (url or "").lower()
    return any(keyword in normalized for keyword in PERSONA_SOURCE_URL_KEYWORDS)


def can_support_user_persona(source_url: str, claim_text: str = "") -> bool:
    """Return true when source or claim explicitly discusses users/scenarios."""
    normalized_claim = (claim_text or "").lower()
    return is_persona_source_url(source_url) or any(
        keyword in normalized_claim for keyword in PERSONA_CLAIM_KEYWORDS
    )
