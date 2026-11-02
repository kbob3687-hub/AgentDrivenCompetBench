import json
from copy import deepcopy

import pytest

from agents.collector.agent import CollectorAgent, source_fetch_observer
from agents.collector.tools import FetchResult
from benchmark.gold import review, snapshot_sources
from schemas.message import AgentMessage, MessageType


@pytest.fixture
def review_fixture(tmp_path, monkeypatch):
    gold = tmp_path / "gold"
    (gold / "snapshots").mkdir(parents=True)
    raw = tmp_path / "raw.json"
    raw.write_text('{"state": {"profile": {}}}', encoding="utf-8")
    source = gold / "snapshots/source.txt"
    source.write_text("Price is $10", encoding="utf-8")
    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setattr(review, "HERE", gold)
    queue = {
        "checks": [
            {
                "id": "A1",
                "task": "real-task-placeholder",
                "criterion": "pricing_basis",
                "locator": "report_markdown:## 2",
                "focus": "price",
                "source_urls": ["https://example.com/pricing"],
            }
        ]
    }
    index = {
        "snapshot_kind": "retrospective_review_capture",
        "tasks": [
            {
                "id": "real-task-placeholder",
                "raw": "raw.json",
                "raw_sha256": review.sha256(raw.read_bytes()),
                "urls": ["https://example.com/pricing"],
            }
        ],
        "sources": [
            {
                "url": "https://example.com/pricing",
                "content_path": "snapshots/source.txt",
                "content_sha256": review.sha256(source.read_bytes()),
            }
        ],
    }
    return queue, index, source


def test_draft_has_no_invented_human_verdict(review_fixture):
    queue, index, _ = review_fixture
    draft = review.prepare(queue, index)
    assert draft["status"] == "awaiting_human_review"
    assert draft["reviewed_by"] is None
    assert draft["checks"][0]["verdict"] is None
    with pytest.raises(ValueError, match="human_reviewed"):
        review.validate_review(draft, queue, index)


def test_complete_review_counts_and_pins_source_hash(review_fixture):
    queue, index, source = review_fixture
    completed = review.prepare(queue, index)
    completed.update(
        status="human_reviewed", reviewed_by="test reviewer", reviewed_at="2026-09-23T12:00:00Z"
    )
    completed["checks"][0].update(
        verdict="supported", rationale="The price is visible", evidence_quote_or_location="$10"
    )
    summary = review.validate_review(completed, queue, index)
    assert summary["check_counts"]["pricing_basis"]["supported"] == 1
    source.write_text("Price changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Snapshot changed"):
        review.validate_review(completed, queue, index)


def test_review_rejects_tampering_and_missing_explanation(review_fixture):
    queue, index, _ = review_fixture
    completed = review.prepare(queue, index)
    completed.update(
        status="human_reviewed", reviewed_by="test reviewer", reviewed_at="2026-09-23T12:00:00Z"
    )
    completed["checks"][0].update(
        verdict="partial", rationale="Some evidence", evidence_quote_or_location="price table"
    )
    tampered = deepcopy(completed)
    tampered["checks"][0]["focus"] = "another question"
    with pytest.raises(ValueError, match="provenance changed"):
        review.validate_review(tampered, queue, index)
    completed["checks"][0]["rationale"] = " "
    with pytest.raises(ValueError, match="Missing reviewer rationale"):
        review.validate_review(completed, queue, index)


def test_cited_urls_from_real_schema_slots(evidence):
    profile = {"pricing": {"evidence": evidence}}
    raw = {"state": {"profile": profile}}
    assert snapshot_sources.cited_urls(raw) == {"https://example.com/test"}
    assert snapshot_sources.cited_urls({"state": {"profile": {}}}) == set()


def test_review_queue_and_corpus_have_unique_ids():
    here = snapshot_sources.HERE
    corpus = json.loads((here / "corpus.json").read_text("utf-8"))
    queue = json.loads((here / "review_queue.json").read_text("utf-8"))
    task_ids = [task["id"] for task in corpus["tasks"]]
    check_ids = [check["id"] for check in queue["checks"]]
    assert len(task_ids) == len(set(task_ids)) == 4
    assert len(check_ids) == len(set(check_ids))
    assert {check["task"] for check in queue["checks"]} == set(task_ids)


async def test_collector_observer_receives_actual_fetch_result(monkeypatch):
    async def fetch(self, url):
        return FetchResult(url=url, title="Page", content="Text after redaction")

    async def extract(self, **kwargs):
        return []

    monkeypatch.setattr(CollectorAgent, "_fetch_url", fetch)
    monkeypatch.setattr(CollectorAgent, "_extract_info", extract)
    seen = []
    token = source_fetch_observer.set(seen.append)
    try:
        agent = object.__new__(CollectorAgent)
        await agent.run(
            AgentMessage(
                message_id="test",
                trace_id="test",
                message_type=MessageType.TASK_ASSIGN,
                from_agent="orchestrator",
                to_agent="collector",
                function_name="collect_competitor_data",
                arguments={
                    "target": "Fixture",
                    "collect_type": "web_scrape",
                    "scope": ["pricing"],
                    "target_urls": ["https://example.com/pricing"],
                },
            )
        )
    finally:
        source_fetch_observer.reset(token)
    assert len(seen) == 1
    assert seen[0].content == "Text after redaction"
