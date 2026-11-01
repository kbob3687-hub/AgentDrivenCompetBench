"""A QA revision must acquire new evidence before collecting again."""

from types import SimpleNamespace

from agents.collector.agent import CollectorAgent
from agents.collector.tools import FetchResult
from api import runner as sse_runner
from orchestrator import graph, nodes
from schemas.message import AgentMessage, MessageType


def _stub_downstream(monkeypatch, qa_result):
    called = {"collector": [], "qa": 0, "writer": 0}

    async def collector(state):
        urls = list(state.get("discovered_urls", []))
        called["collector"].append(urls)
        return {
            "claims": [{"claim": url, "sources": [{"url": url}]} for url in urls],
            "attempted_urls": list(dict.fromkeys(state.get("attempted_urls", []) + urls)),
        }

    async def analyst(state):
        return {"profile": {"company_name": "Fixture"}}

    async def writer(state):
        called["writer"] += 1
        return {"report_markdown": "Fixture report"}

    async def qa(state):
        called["qa"] += 1
        return qa_result(state, called["qa"])

    monkeypatch.setattr(graph, "collector_node", collector)
    monkeypatch.setattr(graph, "analyst_node", analyst)
    monkeypatch.setattr(graph, "writer_node", writer)
    monkeypatch.setattr(graph, "qa_node", qa)
    return called


def _revise(state, count):
    return {
        "qa_verdict": "revise",
        "qa_target_agent": "collector",
        "missing_dimensions": ["pricing"],
        "repair_action": "fetch_more",
        "suggested_strategy": "open_search",
        "iteration": state["iteration"] + 1,
    }


async def test_explicit_source_limit_ends_without_second_collection(monkeypatch):
    called = _stub_downstream(monkeypatch, _revise)
    state = await graph.run_pipeline(
        "Fixture", target_urls=["https://example.com/customers"], max_iterations=3
    )

    assert called == {
        "collector": [["https://example.com/customers"]],
        "qa": 1,
        "writer": 1,
    }
    assert state["final_status"] == "source_limited"
    assert state["rework_blocked_reason"] == "no_new_urls_within_target_urls"
    assert state["qa_verdict"] == "revise"
    assert state["report_markdown"].startswith("Fixture report")
    assert "## 数据限制" in state["report_markdown"]
    assert "pricing" in state["report_markdown"]
    assert not state.get("error")


async def test_auto_discovery_only_collects_new_urls_on_rework(monkeypatch):
    seen_strategies = []

    class Discovery:
        async def discover(self, target, scope, *, strategy, trusted_domains):
            seen_strategies.append(strategy)
            urls = ["https://example.com/customers"]
            if len(seen_strategies) > 1:
                urls += ["https://example.com/customers", "https://example.com/pricing"]
            return {"path": "fixture", "urls": urls, "domain": "example.com"}

    monkeypatch.setattr(nodes, "DiscoveryAgent", Discovery)

    def qa_result(state, count):
        if count == 1:
            return _revise(state, count)
        return {"qa_verdict": "pass", "final_status": "completed"}

    called = _stub_downstream(monkeypatch, qa_result)
    state = await graph.run_pipeline("Fixture", max_iterations=3)

    assert seen_strategies == ["official_only", "open_search"]
    assert called["collector"] == [
        ["https://example.com/customers"],
        ["https://example.com/pricing"],
    ]
    assert called["qa"] == 2
    assert state["attempted_urls"] == [
        "https://example.com/customers",
        "https://example.com/pricing",
    ]
    assert state["qa_verdict"] == "pass"


async def test_auto_discovery_stops_when_it_only_finds_old_urls(monkeypatch):
    class Discovery:
        async def discover(self, target, scope, *, strategy, trusted_domains):
            return {
                "path": "fixture",
                "urls": ["https://example.com/customers", "https://example.com/customers"],
                "domain": "example.com",
            }

    monkeypatch.setattr(nodes, "DiscoveryAgent", Discovery)
    called = _stub_downstream(monkeypatch, _revise)
    state = await graph.run_pipeline("Fixture", max_iterations=3)

    assert called["collector"] == [["https://example.com/customers"]]
    assert called["qa"] == 1
    assert state["final_status"] == "source_limited"
    assert state["rework_blocked_reason"] == "discovery_found_no_new_urls"


async def test_new_url_without_new_evidence_stops_before_analyst(monkeypatch):
    class Discovery:
        async def discover(self, target, scope, *, strategy, trusted_domains):
            urls = ["https://example.com/first"]
            if strategy == "open_search":
                urls.append("https://example.com/second")
            return {"path": "fixture", "urls": urls, "domain": "example.com"}

    class Collector:
        async def execute(self, message):
            url = message.arguments["target_urls"][0]
            claims = (
                [{"dimension": "pricing", "claim": "Free plan", "sources": [{"url": url}]}]
                if url.endswith("first")
                else []
            )
            return SimpleNamespace(arguments={"claims": claims, "source_urls_attempted": [url]})

    monkeypatch.setattr(nodes, "DiscoveryAgent", Discovery)
    monkeypatch.setattr(nodes, "CollectorAgent", Collector)
    called = _stub_downstream(monkeypatch, _revise)
    monkeypatch.setattr(graph, "collector_node", nodes.collector_node)
    state = await graph.run_pipeline("Fixture", max_iterations=3)

    assert called["qa"] == 1
    assert called["writer"] == 1
    assert state["final_status"] == "source_limited"
    assert state["rework_blocked_reason"] == "new_urls_added_no_claims_or_sources"
    assert "## 数据限制" in state["report_markdown"]
    assert state["attempted_urls"] == [
        "https://example.com/first",
        "https://example.com/second",
    ]


async def test_analyst_rework_skips_collection_and_carries_feedback(monkeypatch):
    seen = []

    def qa_result(state, count):
        if count == 1:
            return {
                "qa_verdict": "revise",
                "qa_target_agent": "analyst",
                "qa_issues": [
                    {
                        "field_path": "pricing.tiers[0].price",
                        "issue_type": "inconsistency",
                        "severity": "major",
                    }
                ],
                "missing_dimensions": [],
                "repair_action": "repair_content",
                "iteration": state["iteration"] + 1,
            }
        return {"qa_verdict": "pass", "repair_action": "", "final_status": "completed"}

    called = _stub_downstream(monkeypatch, qa_result)

    async def analyst(state):
        seen.append(
            {
                "action": state.get("repair_action", ""),
                "issues": state.get("qa_issues", []),
                "previous_profile": state.get("profile", {}),
            }
        )
        return {"profile": {"company_name": "Fixture", "revision": len(seen)}}

    monkeypatch.setattr(graph, "analyst_node", analyst)
    state = await graph.run_pipeline(
        "Fixture", target_urls=["https://example.com/pricing"], max_iterations=3
    )

    assert called["collector"] == [["https://example.com/pricing"]]
    assert called["writer"] == called["qa"] == 2
    assert [entry["action"] for entry in seen] == ["", "repair_content"]
    assert seen[1]["issues"][0]["field_path"] == "pricing.tiers[0].price"
    assert seen[1]["previous_profile"]["revision"] == 1
    assert state["final_status"] == "completed"


async def test_writer_rework_skips_analyst_and_collection(monkeypatch):
    analyst_calls = 0

    def qa_result(state, count):
        if count == 1:
            return {
                "qa_verdict": "revise",
                "qa_target_agent": "writer",
                "qa_issues": [
                    {
                        "field_path": "report.sources",
                        "issue_type": "schema_violation",
                        "severity": "major",
                    }
                ],
                "missing_dimensions": [],
                "repair_action": "repair_content",
                "iteration": state["iteration"] + 1,
            }
        return {"qa_verdict": "pass", "repair_action": "", "final_status": "completed"}

    called = _stub_downstream(monkeypatch, qa_result)

    async def analyst(state):
        nonlocal analyst_calls
        analyst_calls += 1
        return {"profile": {"company_name": "Fixture"}}

    monkeypatch.setattr(graph, "analyst_node", analyst)
    state = await graph.run_pipeline(
        "Fixture", target_urls=["https://example.com/pricing"], max_iterations=3
    )

    assert analyst_calls == 1
    assert called["collector"] == [["https://example.com/pricing"]]
    assert called["writer"] == called["qa"] == 2
    assert state["final_status"] == "completed"


async def test_no_new_url_falls_back_to_drop_or_disclose_for_field_issue(monkeypatch):
    analyst_actions = []

    def qa_result(state, count):
        if count == 1:
            return {
                "qa_verdict": "revise",
                "qa_target_agent": "collector",
                "qa_issues": [
                    {
                        "field_path": "feature_tree[0]",
                        "issue_type": "missing_source",
                        "severity": "critical",
                    }
                ],
                "missing_dimensions": [],
                "repair_action": "fetch_more",
                "iteration": state["iteration"] + 1,
            }
        return {"qa_verdict": "pass", "repair_action": "", "final_status": "completed"}

    called = _stub_downstream(monkeypatch, qa_result)

    async def analyst(state):
        analyst_actions.append(state.get("repair_action", ""))
        return {"profile": {"company_name": "Fixture"}}

    monkeypatch.setattr(graph, "analyst_node", analyst)
    state = await graph.run_pipeline(
        "Fixture", target_urls=["https://example.com/features"], max_iterations=3
    )

    assert called["collector"] == [["https://example.com/features"]]
    assert called["writer"] == called["qa"] == 2
    assert analyst_actions == ["", "drop_or_disclose"]
    assert state["rework_blocked_reason"] == "no_new_urls_within_target_urls"
    assert state["final_status"] == "completed"


async def test_analyst_node_passes_repair_context_to_agent(monkeypatch):
    captured = {}

    class Analyst:
        async def execute(self, message):
            captured.update(message.arguments)
            return SimpleNamespace(
                arguments={
                    "profile": {"company_name": "Fixture"},
                    "completeness_score": 0.8,
                    "dimensions_analyzed": ["pricing"],
                }
            )

    monkeypatch.setattr(nodes, "AnalystAgent", Analyst)
    issues = [{"field_path": "pricing", "issue_type": "inconsistency"}]
    await nodes.analyst_node(
        {
            "competitor_name": "Fixture",
            "claims": [{"dimension": "pricing", "claim": "Free", "sources": []}],
            "profile": {"company_name": "Fixture", "pricing": None},
            "qa_target_agent": "analyst",
            "qa_issues": issues,
            "repair_action": "repair_content",
        }
    )

    assert captured["previous_profile"] == {"company_name": "Fixture", "pricing": None}
    assert captured["qa_issues"] == issues
    assert captured["repair_action"] == "repair_content"


async def test_sse_writer_node_passes_repair_context_to_agent(monkeypatch):
    captured = {}

    class Writer:
        config = SimpleNamespace(model="fixture")
        token_usage = {"input": 0, "output": 0}

        async def execute(self, message):
            captured.update(message.arguments)
            return SimpleNamespace(
                arguments={
                    "report_markdown": "# Fixed report",
                    "report_length": 14,
                    "footnote_count": 0,
                }
            )

    async def publish(*args, **kwargs):
        return None

    monkeypatch.setattr(sse_runner, "WriterAgent", Writer)
    monkeypatch.setattr(sse_runner, "_publish", publish)
    issues = [{"field_path": "report.sources", "issue_type": "schema_violation"}]
    await sse_runner.writer_node(
        {
            "trace_id": "repair-context-test",
            "competitor_name": "Fixture",
            "profile": {"company_name": "Fixture"},
            "report_markdown": "# Old report",
            "qa_target_agent": "writer",
            "qa_issues": issues,
            "repair_action": "repair_content",
        }
    )
    sse_runner._task_traces.pop("repair-context-test", None)

    assert captured["previous_report"] == "# Old report"
    assert captured["qa_issues"] == issues
    assert captured["repair_action"] == "repair_content"


async def test_analyst_error_preserves_cause_and_stops_downstream(monkeypatch):
    called = _stub_downstream(monkeypatch, _revise)

    async def fail_analyst(state):
        return {"error": "profile build failed: malformed tiers", "profile": {}}

    monkeypatch.setattr(graph, "analyst_node", fail_analyst)
    state = await graph.run_pipeline("Fixture", target_urls=["https://example.com"])

    assert called["writer"] == called["qa"] == 0
    assert state["error"] == "profile build failed: malformed tiers"
    assert state["final_status"] == "failed"


async def test_collector_keeps_previous_claim_and_merges_new_source(monkeypatch):
    class Collector:
        async def execute(self, message):
            url = message.arguments["target_urls"][0]
            return SimpleNamespace(
                arguments={
                    "claims": [
                        {"dimension": "pricing", "claim": "Free plan", "sources": [{"url": url}]}
                    ],
                    "source_urls_attempted": [url],
                }
            )

    monkeypatch.setattr(nodes, "CollectorAgent", Collector)
    initial = {
        "competitor_name": "Fixture",
        "collect_scope": ["pricing"],
        "discovered_urls": ["https://example.com/first"],
        "attempted_urls": [],
    }
    first = await nodes.collector_node(initial)
    second = await nodes.collector_node(
        {**initial, **first, "discovered_urls": ["https://example.com/second"], "iteration": 2}
    )

    assert second["attempted_urls"] == [
        "https://example.com/first",
        "https://example.com/second",
    ]
    assert len(second["claims"]) == 1
    assert [source["url"] for source in second["claims"][0]["sources"]] == [
        "https://example.com/first",
        "https://example.com/second",
    ]


async def test_collector_agent_fetches_duplicate_url_once(monkeypatch):
    fetched = []

    async def fetch(self, url):
        fetched.append(url)
        return FetchResult(url=url, title="Fixture", content="Fixture content")

    async def extract(self, **kwargs):
        return []

    monkeypatch.setattr(CollectorAgent, "_fetch_url", fetch)
    monkeypatch.setattr(CollectorAgent, "_extract_info", extract)
    agent = object.__new__(CollectorAgent)
    message = AgentMessage(
        message_id="fixture",
        trace_id="fixture",
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="collector",
        function_name="collect_competitor_data",
        arguments={
            "target": "Fixture",
            "collect_type": "web_scrape",
            "scope": ["pricing"],
            "max_sources": 2,
            "target_urls": [
                "https://example.com/a",
                "https://example.com/a",
                "https://example.com/b",
            ],
        },
    )
    result = await agent.run(message)

    assert fetched == ["https://example.com/a", "https://example.com/b"]
    assert result.arguments["source_urls_attempted"] == fetched
    assert result.arguments["sources_fetched"] == 2
