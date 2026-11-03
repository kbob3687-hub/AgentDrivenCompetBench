"""Deterministic evidence depth in schema-declared profile dimensions."""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError

from benchmark.evaluators.citation_eval import claim_slots, source_errors
from benchmark.models import Metric
from schemas.competitor import PricingTier

DIMENSIONS = {
    "feature": ("feature_tree", list),
    "pricing": ("pricing", dict),
    "persona": ("user_personas", list),
    "swot": ("swot", list),
}
URL_ADAPTER = TypeAdapter(HttpUrl)


def canonical_url(url: str) -> str:
    """Deduplicate HTTP URLs by normalized scheme/host/port and without fragments.

    Keep path (including case), query text and query order unchanged. Treat an empty
    path as '/'. Pydantic's HttpUrl normalization also removes default ports.
    """
    parsed = urlsplit(str(URL_ADAPTER.validate_python(url)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _dimension_state(profile: dict[str, Any], key: str, expected: type) -> str | None:
    if key not in profile:
        return f"{key}_missing"
    value = profile[key]
    if key == "pricing" and value is None:
        return None  # An explicit absent optional pricing model contains zero evidence.
    if not isinstance(value, expected):
        return f"{key}_invalid"
    return None


def _evidence_urls(claim: Any) -> set[str] | None:
    if not isinstance(claim, dict) or not isinstance(claim.get("claim"), str):
        return None
    if not claim["claim"].strip() or not isinstance(claim.get("sources"), list):
        return None
    urls = set()
    for source in claim["sources"]:
        if not source_errors(source):
            try:
                urls.add(canonical_url(source["url"]))
            except (KeyError, TypeError, ValueError, ValidationError):
                continue
    return urls or None


def _unknown_metrics(reason: str) -> dict[str, Metric]:
    names = ["evidence_count", "unique_source_count"]
    for dimension in DIMENSIONS:
        names += [f"{dimension}_evidence_count", f"{dimension}_unique_source_count"]
    names += ["pricing_tier_count", "pricing_has_tiers"]
    return {name: Metric(value=None, reason=reason) for name in names}


def evaluate(profile: Any, template: str | None = None) -> dict[str, Metric]:
    """Count cited claim slots and distinct valid source URLs, without fetching URLs.

    A claim counts as evidenced only with nonblank text and at least one structurally
    valid SourceReference. Missing/malformed dimension containers are unknown; an
    explicit empty container has count zero. Extensions contribute to overall counts.
    """
    if not isinstance(profile, dict) or not profile:
        return _unknown_metrics("no_profile")

    slots = claim_slots(profile, template)
    by_dimension: dict[str, list[set[str]]] = {key: [] for key in (*DIMENSIONS, "extension")}
    for path, claim in slots:
        root = path.split(".", 1)[0].split("[", 1)[0]
        dimension = next((name for name, (field, _) in DIMENSIONS.items() if field == root), None)
        if dimension is None:
            if root != "extensions":
                continue
            dimension = "extension"
        urls = _evidence_urls(claim)
        if urls:
            by_dimension[dimension].append(urls)

    metrics: dict[str, Metric] = {}
    reasons = {}
    for dimension, (field, expected) in DIMENSIONS.items():
        reason = _dimension_state(profile, field, expected)
        reasons[dimension] = reason
        groups = by_dimension[dimension]
        for suffix, value in (
            ("evidence_count", len(groups)),
            ("unique_source_count", len(set().union(*groups))),
        ):
            metrics[f"{dimension}_{suffix}"] = Metric(
                value=None if reason else value, reason=reason
            )

    unavailable = [reason for reason in reasons.values() if reason]
    overall_reason = "incomplete_profile_dimensions" if unavailable else None
    all_groups = [group for groups in by_dimension.values() for group in groups]
    metrics["evidence_count"] = Metric(
        value=None if overall_reason else len(all_groups),
        reason=overall_reason,
        details={"missing_or_invalid": unavailable} if unavailable else {},
    )
    metrics["unique_source_count"] = Metric(
        value=None if overall_reason else len(set().union(*all_groups)),
        reason=overall_reason,
        details={"missing_or_invalid": unavailable} if unavailable else {},
    )

    pricing = profile.get("pricing")
    if "pricing" not in profile or pricing is None:
        tier_reason = "pricing_missing"
    elif not isinstance(pricing, dict):
        tier_reason = "pricing_invalid"
    elif "tiers" not in pricing:
        tier_reason = "pricing_tiers_missing"
    elif not isinstance(pricing["tiers"], list):
        tier_reason = "pricing_tiers_invalid"
    else:
        try:
            for tier in pricing["tiers"]:
                PricingTier.model_validate(tier)
            tier_reason = None
        except (ValidationError, TypeError, ValueError):
            tier_reason = "pricing_tiers_invalid"
    count = len(pricing["tiers"]) if tier_reason is None else None
    metrics["pricing_tier_count"] = Metric(value=count, reason=tier_reason)
    metrics["pricing_has_tiers"] = Metric(
        value=(count > 0) if count is not None else None, reason=tier_reason
    )
    return metrics
