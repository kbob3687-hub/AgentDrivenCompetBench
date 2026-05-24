"""Tests for orchestrator graph structure and routing logic."""

import pytest

from orchestrator.edges import qa_routing
from orchestrator.graph import build_graph
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
