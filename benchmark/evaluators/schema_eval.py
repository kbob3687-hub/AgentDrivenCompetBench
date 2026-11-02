"""Validate the original profile without repairing or dropping invalid claims."""

from typing import Any

from pydantic import ValidationError

from benchmark.models import Metric
from schemas.competitor import CompetitorProfile


def evaluate(profile: Any) -> Metric:
    try:
        CompetitorProfile.model_validate(profile)
    except ValidationError as exc:
        return Metric(
            value=False,
            details={
                "errors": exc.errors(include_url=False, include_context=False, include_input=False)
            },
        )
    return Metric(value=True)
