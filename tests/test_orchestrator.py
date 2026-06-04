"""Tests for orchestrator graph structure and routing logic."""

from types import SimpleNamespace

import pytest

from api.runner import (
    _apply_manual_url_resume,
    _normalize_manual_urls,
    _usable_pre_fetched_content,
    collector_node,
    qa_node as sse_qa_node,
)
from orchestrator.edges import qa_routing
from orchestrator.graph import build_graph
from orchestrator.nodes import qa_node
from orchestrator.routing import classify_no_profile_failure
from orchestrator.state import FeedbackRecord, GraphState


class TestQARouting:
    def test_pass_routes_to_end(self):
        state: GraphState = {"qa_verdict": "pass", "iteration": 1, "max_iterations": 3}
        assert qa_routing(state) == "end"

    def test_reject_routes_to_target_agent(self):
        state: GraphState = {
            "qa_verdict": "reject", "iteration": 1, "max_iterations": 3,
            "qa_target_agent": "analyst",
        }
        assert qa_routing(state) == "analyst"

    def test_reject_running_status_does_not_override_target_agent(self):
        state: GraphState = {
            "qa_verdict": "reject",
            "iteration": 2,
            "max_iterations": 3,
            "final_status": "running",
            "qa_target_agent": "analyst",
        }
        assert qa_routing(state) == "analyst"

    def test_pass_running_status_still_reruns_from_collector(self):
        state: GraphState = {
            "qa_verdict": "pass",
            "iteration": 2,
            "max_iterations": 3,
            "final_status": "running",
            "qa_target_agent": "writer",
        }
        assert qa_routing(state) == "collector"

    def test_reject_defaults_to_collector(self):
        state: GraphState = {"qa_verdict": "reject", "iteration": 1, "max_iterations": 3}
        assert qa_routing(state) == "collector"

    def test_revise_routes_to_target_agent(self):
        state: GraphState = {
            "qa_verdict": "revise", "iteration": 1, "max_iterations": 3,
            "qa_target_agent": "writer",
        }
        assert qa_routing(state) == "writer"

    def test_revise_defaults_to_collector(self):
        state: GraphState = {"qa_verdict": "revise", "iteration": 1, "max_iterations": 3}
        assert qa_routing(state) == "collector"

    def test_max_iterations_routes_to_end(self):
        state: GraphState = {"qa_verdict": "revise", "iteration": 4, "max_iterations": 3}
        assert qa_routing(state) == "end"

    def test_invalid_target_agent_falls_back_to_collector(self):
        state: GraphState = {
            "qa_verdict": "revise", "iteration": 1, "max_iterations": 3,
            "qa_target_agent": "invalid_agent",
        }
        assert qa_routing(state) == "collector"


class TestNoProfileAttribution:
    def test_no_profile_without_claims_routes_to_collector(self):
        state: GraphState = {
            "claims": [],
            "discovered_urls": [],
            "collect_scope": ["pricing", "features"],
        }

        failure = classify_no_profile_failure(state)

        assert failure["target_agent"] == "collector"
        assert failure["reason"] == "collector_no_sources"
        assert failure["missing_dimensions"] == ["pricing", "features"]

    def test_no_profile_after_fetch_failures_routes_to_collector(self):
        state: GraphState = {
            "claims": [],
            "discovered_urls": ["https://example.com/pricing"],
            "collect_errors": [
                "https://example.com/pricing: 所有抓取方法均失败: "
                "HTTP(内容过短 (9 字符)，可能需要JS渲染) | "
                "Playwright(NotImplementedError: ) | "
                "Jina(disabled (set ENABLE_JINA=true to enable)) | "
                "Firecrawl(PaymentRequiredError: Payment Required: Insufficient credits)"
            ],
            "collect_scope": ["pricing"],
            "discovery_strategy": "official_only",
        }

        failure = classify_no_profile_failure(state)

        assert failure["target_agent"] == "collector"
        assert failure["reason"] == "collector_fetch_failed"
        assert failure["missing_dimensions"] == ["pricing"]
        assert "已发现 1 个 URL" in failure["message"]
        assert "Firecrawl 额度不足" in failure["message"]
        assert "HTTP 只抓到 JS 空壳/短内容" in failure["message"]
        assert "Playwright 本地渲染不可用" in failure["message"]
        assert failure["suggested_strategy"] == "open_search"
        assert failure["error_samples"]

    def test_no_profile_with_claims_routes_to_analyst(self, sample_claims):
        state: GraphState = {
            "claims": sample_claims,
            "discovered_urls": ["https://www.notion.so/pricing"],
            "collect_scope": ["pricing", "features"],
        }

        failure = classify_no_profile_failure(state)

        assert failure["target_agent"] == "analyst"
        assert failure["reason"] == "analyst_empty_profile"
        assert failure["missing_dimensions"] == []

    @pytest.mark.asyncio
    async def test_qa_node_no_profile_without_claims_targets_collector(self):
        state: GraphState = {
            "iteration": 1,
            "max_iterations": 3,
            "profile": {},
            "claims": [],
            "discovered_urls": [],
            "collect_scope": ["pricing", "features"],
            "feedback_history": [],
        }

        update = await qa_node(state)

        assert update["qa_verdict"] == "reject"
        assert update["qa_target_agent"] == "collector"
        assert update["missing_dimensions"] == ["pricing", "features"]
        assert update["feedback_history"][0]["action_taken"] == "reject(no profile) -> collector"

    @pytest.mark.asyncio
    async def test_qa_node_no_profile_with_claims_targets_analyst(self, sample_claims):
        state: GraphState = {
            "iteration": 1,
            "max_iterations": 3,
            "profile": {},
            "claims": sample_claims,
            "discovered_urls": ["https://www.notion.so/pricing"],
            "collect_scope": ["pricing", "features"],
            "feedback_history": [],
        }

        update = await qa_node(state)

        assert update["qa_verdict"] == "reject"
        assert update["qa_target_agent"] == "analyst"
        assert update["missing_dimensions"] == []
        assert update["feedback_history"][0]["action_taken"] == "reject(no profile) -> analyst"


class TestHitlManualUrls:
    def test_normalize_manual_urls_filters_invalid_and_dedupes(self):
        urls = _normalize_manual_urls([
            " https://example.com/product ",
            "not-a-url",
            "ftp://example.com/file",
            "https://example.com/product",
            "http://example.com/support",
        ])

        assert urls == [
            "https://example.com/product",
            "http://example.com/support",
        ]

    def test_manual_url_resume_routes_next_iteration_to_collector(self):
        update = {
            "iteration": 4,
            "qa_target_agent": "analyst",
            "collect_errors": ["https://old.example: timeout"],
        }
        payload = {
            "decision": "continue",
            "urls": ["https://source.example/product"],
        }

        _apply_manual_url_resume(
            update,
            payload,
            current_iteration=3,
            max_iterations=3,
        )

        assert update["target_urls"] == ["https://source.example/product"]
        assert update["discovered_urls"] == ["https://source.example/product"]
        assert update["collect_errors"] == []
        assert update["qa_target_agent"] == "collector"
        assert update["final_status"] == "running"
        assert update["max_iterations"] == 4

    def test_manual_url_resume_ignores_non_continue_decisions(self):
        update = {"iteration": 2}
        payload = {
            "decision": "abort",
            "urls": ["https://source.example/product"],
        }

        _apply_manual_url_resume(
            update,
            payload,
            current_iteration=1,
            max_iterations=3,
        )

        assert update == {"iteration": 2}


class TestCollectorPreFetchedContent:
    def test_usable_pre_fetched_content_requires_meaningful_length(self):
        assert _usable_pre_fetched_content(None) == ""
        assert _usable_pre_fetched_content("  short  ") == ""
        assert _usable_pre_fetched_content(" x" * 300).startswith("x")

    @pytest.mark.asyncio
    async def test_collector_reuses_pre_fetched_content_without_fetching(self, monkeypatch):
        url = "https://example.com/pricing"
        extracted_claims = [
            {
                "claim": "Example has a pricing page",
                "confidence": 0.9,
                "dimension": "pricing",
                "sources": [{"url": url}],
            }
        ]

        class FakeCollector:
            config = SimpleNamespace(model="fake-model")

            async def _fetch_url(self, fetch_url: str):
                raise AssertionError(f"should not fetch pre-fetched URL: {fetch_url}")

            def _truncate_content(self, content: str, max_chars: int = 12000) -> str:
                return content[:max_chars]

            async def _extract_info(self, **kwargs):
                assert kwargs["url"] == url
                assert "Pricing details" in kwargs["content"]
                return extracted_claims

        async def noop_publish(*args, **kwargs):
            return None

        monkeypatch.setattr("api.runner.CollectorAgent", lambda: FakeCollector())
        monkeypatch.setattr("api.runner._publish", noop_publish)

        state: GraphState = {
            "trace_id": "test-trace",
            "iteration": 1,
            "competitor_name": "Example",
            "collect_scope": ["pricing"],
            "discovered_urls": [url],
            "pre_fetched_content": {
                url: "Pricing details. " * 40,
            },
            "claims": [],
            "industry_fields": [],
            "target_urls": [],
            "discovery_strategy": "open_search",
        }

        update = await collector_node(state)

        assert update["claims"] == extracted_claims
        assert update["sources_fetched"] == 1
        assert update["sources_failed"] == 0
        assert update["collect_errors"] == []


class TestSseQaNode:
    @pytest.mark.asyncio
    async def test_qa_agent_error_does_not_route_to_collector(self, monkeypatch, sample_profile):
        class FakeResult:
            arguments = {
                "error": "failed to parse QA output",
                "error_type": "ValueError",
            }

        class FakeQAAgent:
            config = SimpleNamespace(model="fake-qa")

            async def execute(self, message):
                return FakeResult()

        async def noop_publish(*args, **kwargs):
            return None

        monkeypatch.setattr("api.runner.QAAgent", lambda: FakeQAAgent())
        monkeypatch.setattr("api.runner._publish", noop_publish)

        state: GraphState = {
            "trace_id": "test-trace",
            "iteration": 1,
            "max_iterations": 3,
            "competitor_name": "Notion",
            "profile": sample_profile,
            "report_markdown": "report",
            "claims": [{"dimension": "pricing"}],
            "expected_dimensions": ["pricing"],
            "industry": "saas",
            "feedback_history": [],
        }

        update = await sse_qa_node(state)

        assert update["final_status"] == "qa_failed"
        assert update["qa_target_agent"] == "qa"
        assert "QA failed: ValueError" in update["error"]


class TestGraphStructure:
    def test_graph_compiles_without_checkpointer(self):
        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_graph_has_five_nodes(self):
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {"discovery", "collector", "analyst", "writer", "qa", "__start__", "__end__"}
        assert expected.issubset(node_names)


class TestFeedbackRecord:
    def test_record_creation(self):
        record = FeedbackRecord(
            iteration=1,
            verdict="revise",
            score=0.65,
            issues_count=3,
            critical_issues=1,
            action_taken="打回Collector补采['ai_features']",
            feedback_summary="缺少AI功能维度数据",
        )
        assert record.iteration == 1
        assert record.verdict == "revise"
        assert record.score == 0.65

    def test_record_serialization(self):
        record = FeedbackRecord(
            iteration=2,
            verdict="pass",
            score=0.82,
            issues_count=1,
            critical_issues=0,
            action_taken="通过",
        )
        data = record.model_dump(mode="json")
        assert data["verdict"] == "pass"
        assert data["score"] == 0.82
        assert "timestamp" in data
