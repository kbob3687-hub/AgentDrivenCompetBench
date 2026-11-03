import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import AgentConfig, BaseAgent, LLMResponse, execution_records
from orchestrator import graph


@pytest.mark.parametrize("enable_qa", [True, False])
async def test_real_graph_qa_ablation_and_metadata(monkeypatch, enable_qa):
    called = []

    def node(name, update):
        async def invoke(state):
            called.append(name)
            return update

        return invoke

    monkeypatch.setattr(graph, "discovery_node", node("discovery", {}))
    monkeypatch.setattr(graph, "collector_node", node("collector", {"claims": []}))
    monkeypatch.setattr(graph, "analyst_node", node("analyst", {"profile": {"fixture": True}}))
    monkeypatch.setattr(graph, "writer_node", node("writer", {"report_markdown": "Fixture"}))
    monkeypatch.setattr(
        graph, "qa_node", node("qa", {"qa_verdict": "pass", "final_status": "completed"})
    )
    records = []
    state = await graph.run_pipeline("Fixture", enable_qa=enable_qa, execution_metadata=records)
    assert ("qa" in called) == enable_qa
    assert ("qa_verdict" in state) == enable_qa
    assert len(records) == (5 if enable_qa else 4)
    assert execution_records.get() is None
    assert all(item["latency_seconds"] >= 0 for item in records)


async def test_cancellation_preserves_started_nodes_and_resets_context(monkeypatch):
    async def blocked(state):
        await asyncio.sleep(1)

    monkeypatch.setattr(graph, "discovery_node", blocked)
    records = []
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(graph.run_pipeline("Fixture", execution_metadata=records), 0.02)
    assert records[0]["status"] == "cancelled"
    assert execution_records.get() is None


async def test_openai_missing_usage_is_unknown():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Fixture"))],
            usage=None,
            model="fixture",
        )
    )
    dummy = SimpleNamespace(
        system_prompt="fixture",
        config=AgentConfig(provider="openai_compat"),
        openai_client=client,
    )
    result = await BaseAgent._call_openai_compat(dummy, [])
    assert result.usage_known is False


@pytest.mark.parametrize("known", [True, False])
async def test_call_llm_audit_preserves_usage_availability(known):
    dummy = SimpleNamespace(
        role="writer",
        system_prompt="fixture",
        config=AgentConfig(provider="openai_compat"),
        langfuse=MagicMock(),
        token_usage={"input": 0, "output": 0, "model": ""},
        _call_openai_compat=AsyncMock(
            return_value=LLMResponse(
                text="fixture", input_tokens=2, output_tokens=3, usage_known=known
            )
        ),
    )
    records = []
    token = execution_records.set(records)
    try:
        await BaseAgent.call_llm(dummy, [])
    finally:
        execution_records.reset(token)
    assert records[0]["input_tokens"] == (2 if known else None)
    assert records[0]["output_tokens"] == (3 if known else None)


async def test_concurrent_pipeline_records_are_isolated(monkeypatch):
    async def discovery(state):
        await asyncio.sleep(0)
        return {"discovery_domain": state["competitor_name"]}

    async def empty(state):
        return {}

    monkeypatch.setattr(graph, "discovery_node", discovery)
    for name in ("collector_node", "analyst_node", "writer_node"):
        monkeypatch.setattr(graph, name, empty)
    left, right = [], []
    await asyncio.gather(
        graph.run_pipeline("Left", enable_qa=False, execution_metadata=left),
        graph.run_pipeline("Right", enable_qa=False, execution_metadata=right),
    )
    assert len(left) == len(right) == 4
    assert left[0]["state_update"]["discovery_domain"] == "Left"
    assert right[0]["state_update"]["discovery_domain"] == "Right"


async def test_qa_error_remains_distinct_from_quality_reject(monkeypatch, profile):
    from orchestrator import nodes

    agent = MagicMock()
    agent.execute = AsyncMock(return_value=SimpleNamespace(arguments={"error": "fixture failure"}))
    monkeypatch.setattr(nodes, "QAAgent", lambda: agent)
    result = await nodes.qa_node({"profile": profile, "competitor_name": "Fixture"})
    assert result["qa_verdict"] == "reject"
    assert result["error"] == "fixture failure"
