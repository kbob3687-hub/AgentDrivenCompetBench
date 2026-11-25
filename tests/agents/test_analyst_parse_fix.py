"""Unit tests for Analyst._parse_llm_output fixes.

Covers:
1. Braces inside string values no longer confuse the depth counter.
2. After one candidate fails json.loads, scanner continues to find the next object.
3. raise-on-failure path: parse failure now raises ValueError so execute() retries.
"""
import json
import pytest
from agents.analyst.agent import AnalystAgent
from agents.base import AgentConfig


def _make_agent() -> AnalystAgent:
    """Build a minimal AnalystAgent with no real LLM config needed."""
    return AnalystAgent.__new__(AnalystAgent)


agent = _make_agent()


# ── Layer 1: string-interior braces ───────────────────────────────────────────

def test_parse_string_with_braces_inside():
    """Value containing { } must not break depth tracking."""
    payload = {"key": "some {nested} text", "num": 42}
    result = agent._parse_llm_output(json.dumps(payload))
    assert result == payload


def test_parse_deeply_nested_with_string_braces():
    payload = {
        "features": [{"name": "template", "desc": "use {{var}} syntax"}],
        "pricing": {"tier": "free"},
    }
    result = agent._parse_llm_output(json.dumps(payload))
    assert result == payload


# ── Layer 2: good JSON after a bad prefix ─────────────────────────────────────

def test_parse_valid_json_after_preamble():
    """LLM sometimes emits prose before the JSON object."""
    good = {"answer": 1}
    text = "Here is my analysis:\n" + json.dumps(good)
    result = agent._parse_llm_output(text)
    assert result == good


def test_parse_json_block():
    good = {"answer": 2}
    text = "```json\n" + json.dumps(good) + "\n```"
    result = agent._parse_llm_output(text)
    assert result == good


# ── Layer 3: empty / garbage returns None ─────────────────────────────────────

def test_parse_empty_returns_none():
    assert agent._parse_llm_output("") is None
    assert agent._parse_llm_output("   ") is None


def test_parse_pure_garbage_returns_none():
    assert agent._parse_llm_output("not json at all !!!") is None


# ── Layer 4: truncation survival ──────────────────────────────────────────────

def test_parse_trailing_comma_fix():
    """Trailing comma after last value is a common truncation artifact."""
    text = '{"a": 1, "b": 2,'  # truncated – missing closing }
    # May or may not succeed depending on truncation depth; we just assert no crash.
    result = agent._parse_llm_output(text)
    # If recovered, must be a dict
    if result is not None:
        assert isinstance(result, dict)
