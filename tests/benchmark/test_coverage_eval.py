import pytest

from benchmark.evaluators.coverage_eval import evaluate
from benchmark.models import BenchmarkCase
from benchmark.workflow import collect_dimensions


def test_aliases_and_swot(profile):
    result = evaluate(profile, ["features", "pricing", "persona", "swot"])
    assert result.value == 1
    profile["swot"].pop()
    result = evaluate(profile, ["features", "pricing", "persona", "swot"])
    assert result.value == 0.75
    assert result.details["swot_categories"]["threat"] is False


def test_empty_placeholders_not_covered():
    result = evaluate(
        {
            "pricing": {},
            "feature_tree": [{}],
            "user_personas": [{}],
            "swot": [{"category": "strength", "items": []}],
        },
        ["features", "pricing", "persona", "swot"],
    )
    assert result.value == 0


def test_template_dimension_allows_zero():
    assert (
        evaluate(
            {"extensions": {"integration_count": 0}}, ["extensions.integration_count"], "saas"
        ).value
        == 1
    )


def test_unknown_dimension_rejected():
    with pytest.raises(ValueError, match="Unknown dimensions"):
        evaluate({}, ["typo"])


def test_nontext_core_fields_do_not_count_as_content():
    result = evaluate(
        {
            "feature_tree": [{"name": False}],
            "pricing": {"model_type": 0},
            "user_personas": [{"segment": 42}],
        },
        ["features", "pricing", "persona"],
    )
    assert result.value == 0


def test_swot_not_collected():
    case = BenchmarkCase(id="test", competitors=["Notion"], required_dimensions=["swot"])
    assert "swot" not in collect_dimensions(case)
    case.collect_scope = ["swot"]
    with pytest.raises(ValueError, match="SWOT"):
        collect_dimensions(case)
