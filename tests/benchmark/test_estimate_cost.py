"""成本估算是离线推算：只读冻结快照，不调用 LLM、不联网。"""

from benchmark import estimate_cost


def _row(case_id, prompt_chars, baseline_tokens, multi_tokens, multi_seconds):
    return {
        "case_id": case_id,
        "pages": 1,
        "prompt_chars": prompt_chars,
        "baseline_tokens": baseline_tokens,
        "baseline_seconds": 90,
        "multi_agent_tokens": multi_tokens,
        "multi_agent_seconds": multi_seconds,
    }


def _rows():
    return [
        _row("a-normal-001", 50000, 30000, 200000, 300),
        _row("b-normal-001", 30000, 27000, 120000, 200),
        _row("c-stress-001", 20000, 25000, 100000, 150),
        _row("d-stress-001", 10000, 22000, 60000, 100),
    ]


def _by_keyword(scenarios, keyword):
    return next(s for s in scenarios if keyword in s["name"])


def test_all_arms_sums_three_arm_tokens():
    tokens, seconds = estimate_cost.all_arms(_row("x", 0, 100, 1000, 100))
    ratio = estimate_cost.NO_QA_RATIO
    assert tokens == 100 + 1000 + round(1000 * ratio)
    assert seconds == 90 + 100 + round(100 * ratio)


def test_scenarios_cover_the_four_documented_blocks():
    scenarios = estimate_cost.scenarios(_rows())
    assert len(scenarios) == 4
    for keyword in ("成本闸门", "主实验", "返工", "实时"):
        assert _by_keyword(scenarios, keyword)["tokens"] > 0


def test_gate_uses_the_largest_middle_and_smallest_cases():
    gate = _by_keyword(estimate_cost.scenarios(_rows()), "成本闸门")
    assert gate["tasks"] == 9
    assert "a-normal-001" in gate["cases"]
    assert "b-normal-001" in gate["cases"]
    assert "d-stress-001" in gate["cases"]
    assert "c-stress-001" not in gate["cases"]
    expected = sum(estimate_cost.all_arms(r)[0] for r in _rows() if r["case_id"] != "c-stress-001")
    assert gate["tokens"] == expected


def test_rework_uses_stress_cases_and_smoke_uses_normal_cases():
    scenarios = estimate_cost.scenarios(_rows())
    rework = _by_keyword(scenarios, "返工")
    assert rework["tasks"] == 24
    assert rework["tokens"] == (100000 + 60000) * 4
    assert rework["minutes_serial"] == round((150 + 100) * 4 / 60)
    smoke = _by_keyword(scenarios, "实时")
    assert smoke["tasks"] == 6
    assert smoke["tokens"] == 200000 + 120000
    assert "估算" in smoke["note"]


def test_main_block_matches_totals_and_is_the_biggest():
    scenarios = estimate_cost.scenarios(_rows())
    main = _by_keyword(scenarios, "主实验")
    expected = estimate_cost.totals(_rows(), 2)
    assert main["tasks"] == expected["tasks"] == 24
    assert main["tokens"] == expected["tokens_total"]
    assert main["tokens"] > _by_keyword(scenarios, "成本闸门")["tokens"]


def test_markdown_lists_every_case_and_every_block():
    rows = _rows()
    doc = estimate_cost.markdown(rows)
    for row in rows:
        assert f"| {row['case_id']} |" in doc
    for scenario in estimate_cost.scenarios(rows):
        assert scenario["name"] in doc


def test_forecast_reads_frozen_bundles():
    rows = estimate_cost.forecast(estimate_cost.ROOT / "benchmark/replay_bundles")
    bundles_root = estimate_cost.ROOT / "benchmark/replay_bundles"
    assert len(rows) == 12
    assert all(r["pages"] > 0 and r["prompt_chars"] > 0 for r in rows)

    ratio, _ = estimate_cost.measure(bundles_root)
    biggest = max(rows, key=lambda r: r["prompt_chars"])
    assert (
        biggest["baseline_tokens"]
        == round(biggest["prompt_chars"] / ratio) + estimate_cost.BASE_OUT_TOKENS
    )
    assert max(r["multi_agent_tokens"] for r in rows) == biggest["multi_agent_tokens"]
