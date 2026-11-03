from benchmark.evaluators.schema_eval import evaluate


def test_valid_profile(profile):
    assert evaluate(profile).value is True


def test_missing_source_fails_without_repair(profile):
    profile["pricing"]["evidence"]["sources"] = []
    result = evaluate(profile)
    assert result.value is False
    assert result.details["errors"]
    assert profile["pricing"]["evidence"]["sources"] == []


def test_empty_profile_fails():
    assert evaluate({}).value is False


def test_schema_allows_missing_dimensions():
    assert (
        evaluate({"company_name": "x", "product_name": "x", "website": "x", "industry": "x"}).value
        is True
    )
