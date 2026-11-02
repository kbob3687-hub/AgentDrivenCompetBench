"""Evidence coverage and source format validity, with no network requests."""

from typing import Any, get_args, get_origin

from pydantic import BaseModel, HttpUrl, TypeAdapter, ValidationError

from benchmark.models import Metric, ratio
from schemas.competitor import CompetitorProfile, EvidencedClaim, SourceReference
from schemas.extensions import load_template


def claim_slots(profile: Any, template: str | None = None) -> list[tuple[str, Any]]:
    """Walk schema-declared claim slots, including absent required evidence fields.

    An absent optional parent dimension contributes no claims (coverage_eval catches it).
    A present feature/pricing object with missing evidence DOES contribute a missing slot.
    """
    slots: list[tuple[str, Any]] = []

    def walk(annotation: Any, value: Any, path: str) -> None:
        if annotation is EvidencedClaim:
            slots.append((path, value))
        elif get_origin(annotation) is list:
            if isinstance(value, list):
                for i, item in enumerate(value):
                    walk(get_args(annotation)[0], item, f"{path}[{i}]")
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if value is not None:
                value = value if isinstance(value, dict) else {}
                for name, field in annotation.model_fields.items():
                    walk(field.annotation, value.get(name), f"{path}.{name}".strip("."))
        else:
            for arg in get_args(annotation):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    walk(arg, value, path)

    walk(CompetitorProfile, profile, "")
    extensions = profile.get("extensions", {}) if isinstance(profile, dict) else {}
    if not isinstance(extensions, dict):
        extensions = {}
    declared = set()
    if template:
        for field in load_template(template).fields:
            if field.field_type == "evidenced_claim" and field.field_name in extensions:
                declared.add(field.field_name)
                slots.append((f"extensions.{field.field_name}", extensions[field.field_name]))

    def extension_walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if "claim" in value or "sources" in value:
                slots.append((path, value))
            else:
                for key, item in value.items():
                    extension_walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                extension_walk(item, f"{path}[{i}]")

    for key, value in extensions.items():
        if key not in declared:
            extension_walk(value, f"extensions.{key}")
    return slots


def source_errors(source: Any) -> list[str]:
    if not isinstance(source, dict):
        return ["source_not_object"]
    errors = []
    try:
        SourceReference.model_validate(source)
    except ValidationError:
        errors.append("invalid_source_schema")
    url = source.get("url")
    try:
        if not isinstance(url, str) or any(c.isspace() for c in url):
            raise ValueError("invalid URL")
        TypeAdapter(HttpUrl).validate_python(url)
    except (ValueError, ValidationError):
        errors.append("invalid_http_url")
    for field in ("title", "snippet"):
        if not isinstance(source.get(field), str) or not source[field].strip():
            errors.append(f"empty_{field}")
    return errors


def evaluate(profile: Any, template: str | None = None) -> dict[str, Metric]:
    slots = claim_slots(profile, template)
    covered = 0
    sources = []
    missing = []
    for path, claim in slots:
        refs = claim.get("sources") if isinstance(claim, dict) else None
        # A malformed scalar source is still an existing invalid reference.
        refs = refs if isinstance(refs, list) else ([] if refs is None else [refs])
        if any(isinstance(ref, dict) for ref in refs):
            covered += 1
        else:
            missing.append(path)
        sources.extend((f"{path}.sources[{i}]", ref) for i, ref in enumerate(refs))
    invalid = []
    for path, source in sources:
        errors = source_errors(source)
        if errors:
            invalid.append({"path": path, "errors": errors})
    return {
        "citation_coverage": ratio(
            covered, len(slots), reason="no_claims", missing_claim_paths=missing
        ),
        "citation_validity": ratio(
            len(sources) - len(invalid), len(sources), reason="no_sources", invalid_sources=invalid
        ),
    }
