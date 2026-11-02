"""Single-LLM baseline produces evaluator-ready records without any network."""

import json
from typing import Any

from agents.base import LLMResponse
from benchmark.baselines.single_llm import SingleLLMBaselineAgent, parse_profile_report, run_case
from benchmark.evaluators import evaluate
from benchmark.models import BenchmarkCase
from benchmark.replay import SnapshotBundle

PROFILE: dict[str, Any] = {
    "company_name": "Alpha",
    "product_name": "Alpha Product",
    "website": "https://a.example.com",
    "industry": "SaaS",
    "one_liner": "A fixture product.",
    "schema_version": "1.0",
    "feature_tree": [
        {
            "name": "Feature A",
            "description": {
                "claim": "Does A",
                "confidence": 0.9,
                "reasoning": "Stated on the pricing page.",
                "sources": [{"url": "https://a.example.com", "source_type": "web_page"}],
            },
        }
    ],
}


def _bundle(tmp_path) -> SnapshotBundle:
    import hashlib

    directory = tmp_path / "case-c1"
    directory.mkdir()
    text = "Alpha pricing page content"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (directory / f"{digest}.txt").write_text(text, encoding="utf-8")
    index = {
        "snapshot_kind": "frozen_replay_bundle",
        "entries": [
            {
                "url": "https://a.example.com",
                "title": "Alpha",
                "success": True,
                "error": None,
                "content_sha256": digest,
                "content_path": f"{digest}.txt",
            }
        ],
    }
    (directory / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return SnapshotBundle.load(directory)


def test_parse_profile_report_accepts_json_reply() -> None:
    reply = f"```json\n{json.dumps({'profile': PROFILE, 'report_markdown': '# Report'})}\n```"
    profile, report, error = parse_profile_report(reply)
    assert error is None
    assert profile["company_name"] == "Alpha"
    assert report == "# Report"


def test_parse_profile_report_rejects_garbage() -> None:
    for reply in ("no json here", "{'profile':", '{"profile": {}}'):
        profile, report, error = parse_profile_report(reply)
        assert profile is None or error
        assert error


async def test_run_case_completes_and_records_usage(tmp_path, monkeypatch) -> None:
    case = BenchmarkCase(id="case", competitors=["Alpha"], required_dimensions=["pricing"])
    reply = json.dumps({"profile": PROFILE, "report_markdown": "# Report"})

    async def fake_call_llm(self, messages, tools=None, response_format=None):
        return LLMResponse(
            text=reply, input_tokens=1000, output_tokens=500, usage_known=True, model="fixture"
        )

    monkeypatch.setattr(SingleLLMBaselineAgent, "call_llm", fake_call_llm)
    record = await run_case(case, "Alpha", _bundle(tmp_path))

    assert record.outcome == "completed"
    assert record.enable_qa is False
    assert record.state["profile"]["company_name"] == "Alpha"
    assert record.state["pages_urls"] == ["https://a.example.com"]
    llm_events = [e for e in record.execution_metadata if e["kind"] == "llm"]
    assert llm_events and llm_events[0]["input_tokens"] == 1000

    metrics = evaluate(record, case)
    assert metrics["workflow_success"].value is True
    assert metrics["qa_passed"].value is None
    assert metrics["schema_valid"].value is True


async def test_run_case_records_error_on_bad_reply(tmp_path, monkeypatch) -> None:
    case = BenchmarkCase(id="case", competitors=["Alpha"], required_dimensions=["pricing"])

    async def fake_call_llm(self, messages, tools=None, response_format=None):
        return LLMResponse(text="sorry, not json", usage_known=False, model="fixture")

    monkeypatch.setattr(SingleLLMBaselineAgent, "call_llm", fake_call_llm)
    record = await run_case(case, "Alpha", _bundle(tmp_path))

    assert record.outcome == "error"
    assert "JSON" in (record.error or "")
    llm_events = [e for e in record.execution_metadata if e["kind"] == "llm"]
    assert llm_events[0]["input_tokens"] is None
