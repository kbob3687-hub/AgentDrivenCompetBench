"""Final-output dimension presence, separate from Collector dimensions and QA scores."""

from typing import Any

from benchmark.models import Metric, ratio
from schemas.competitor import CompetitorProfile
from schemas.extensions import load_template

ALIASES = {"features": "feature_tree", "persona": "user_personas"}
SWOT_CATEGORIES = ("strength", "weakness", "opportunity", "threat")


def has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value) and any(
            nonempty(v) for v in (value.values() if isinstance(value, dict) else value)
        )
    return value is not None  # 0 and False are meaningful extension values.


def normalize_dimensions(dimensions: list[str], template: str | None) -> list[str]:
    allowed = set(CompetitorProfile.model_fields)
    if template:
        allowed.update(f"extensions.{f.field_name}" for f in load_template(template).fields)
    normalized = list(dict.fromkeys(ALIASES.get(d, d) for d in dimensions))
    unknown = set(normalized) - allowed
    if unknown:
        raise ValueError(f"Unknown dimensions: {sorted(unknown)}")
    return normalized


def evaluate(profile: Any, dimensions: list[str], template: str | None = None) -> Metric:
    dimensions = normalize_dimensions(dimensions, template)
    profile = profile if isinstance(profile, dict) else {}
    checks = {}
    swot = profile.get("swot")
    swot = swot if isinstance(swot, list) else []
    swot_checks = {
        category: any(
            isinstance(item, dict)
            and item.get("category") == category
            and isinstance(item.get("items"), list)
            and any(isinstance(c, dict) and has_text(c.get("claim")) for c in item["items"])
            for item in swot
        )
        for category in SWOT_CATEGORIES
    }
    for dimension in dimensions:
        if dimension == "swot":
            checks[dimension] = all(swot_checks.values())
        elif dimension.startswith("extensions."):
            extensions = profile.get("extensions")
            checks[dimension] = isinstance(extensions, dict) and nonempty(
                extensions.get(dimension.split(".", 1)[1])
            )
        elif dimension in ("feature_tree", "user_personas"):
            key = "name" if dimension == "feature_tree" else "segment"
            values = profile.get(dimension)
            checks[dimension] = isinstance(values, list) and any(
                isinstance(v, dict) and has_text(v.get(key)) for v in values
            )
        elif dimension == "pricing":
            pricing = profile.get("pricing")
            checks[dimension] = isinstance(pricing, dict) and has_text(pricing.get("model_type"))
        else:
            checks[dimension] = nonempty(profile.get(dimension))
    return ratio(
        sum(checks.values()),
        len(checks),
        reason="no_required_dimensions",
        dimensions=checks,
        swot_categories=swot_checks,
    )
