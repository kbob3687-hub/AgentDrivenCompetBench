"""Versioned inputs, raw task records, and auditable metric values."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    competitors: list[str] = Field(min_length=1)
    required_dimensions: list[str] = Field(min_length=1)
    collect_scope: list[str] | None = None
    target_urls: dict[str, list[str]] = Field(default_factory=dict)
    template: str | None = None

    @field_validator("competitors", "required_dimensions", "collect_scope")
    @classmethod
    def unique_nonempty(cls, values: list[str] | None) -> list[str] | None:
        if values is not None:
            if not values or any(not v.strip() for v in values):
                raise ValueError("values must be nonempty")
            if len(set(values)) != len(values):
                raise ValueError("duplicate values")
        return values


class RunConfig(BaseModel):
    workflow_id: Literal["standalone"] = "standalone"
    enable_qa: bool = True
    max_iterations: int = Field(default=3, ge=1)
    repeat: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=900, gt=0)
    capture_sources: bool = False
    task_concurrency: int = Field(default=1, ge=1)
    replay_root: str | None = None


class Metric(BaseModel):
    value: bool | int | float | None
    numerator: int | None = None
    denominator: int | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def ratio(numerator: int, denominator: int, *, reason: str, **details: Any) -> Metric:
    return Metric(
        value=numerator / denominator if denominator else None,
        numerator=numerator,
        denominator=denominator,
        reason=reason if not denominator else None,
        details=details,
    )


class TaskRecord(BaseModel):
    task_id: str
    case_id: str
    competitor: str
    repeat: int
    enable_qa: bool
    started_at: str
    completed_at: str
    latency_seconds: float
    outcome: Literal["completed", "error", "timeout"]
    state: dict[str, Any] = Field(default_factory=dict)
    execution_metadata: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
