import json
from datetime import datetime, timedelta, timezone

import pytest

from benchmark.gold import formal_signoff


def _sha(text: str) -> str:
    return formal_signoff.sha256(text.encode("utf-8"))


@pytest.fixture
def signoff_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(formal_signoff, "ROOT", tmp_path)
    case = "fixture-case-001"
    quote_text = "Custom domain costs $8/month/domain billed annually."
    content_sha = _sha(quote_text)
    bundle = tmp_path / "benchmark/replay_bundles" / f"{case}-c1"
    bundle.mkdir(parents=True)
    (bundle / "index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "url": "https://example.com/pricing",
                        "content_sha256": content_sha,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    truth_slot = {
        "slot_id": f"{case}-s1",
        "slot_type": "pricing_fact",
        "claim_zh": "自定义域名年付 8 美元每月。",
        "claim_en": "Custom domains cost $8/month annually.",
        "quote": quote_text,
        "url": "https://example.com/pricing",
        "content_sha256": content_sha,
    }
    missing_slot = {
        "slot_id": f"{case}-s2",
        "slot_type": "missing_dimension",
        "claim_zh": "快照完全没有安全认证信息。",
        "missing_keywords": [{"keyword": "SOC 2", "hits_expected": 0}],
        "urls_searched": ["https://example.com/pricing"],
    }
    draft = {
        "kind": "formal_gold_slots",
        "status": "awaiting_human_review",
        "slot_selection_rule": "each normal case gets 1 pricing + 1 feature fact",
        "cases": {
            case: {
                "snapshot_bundle": f"benchmark/replay_bundles/{case}-c1",
                "slots": [truth_slot, missing_slot],
            }
        },
    }
    review = json.loads(json.dumps(draft))
    review["status"] = "human_reviewed"
    review["reviewed_by"] = "硝酸铜"
    review["reviewed_at"] = datetime(
        2026, 11, 6, 10, 0, tzinfo=timezone(timedelta(hours=8))
    ).isoformat(timespec="seconds")
    for slot in review["cases"][case]["slots"]:
        slot["verdict"] = "confirmed"
    return draft, review


def test_signoff_accepts_confirmed_review_and_emits_gold(signoff_fixture):
    draft, review = signoff_fixture
    summary, gold = formal_signoff.validate_signoff(review, draft)
    assert summary["slots_kept"] == 2
    assert summary["slots_rejected"] == 0
    assert gold["status"] == "frozen"
    kept = gold["cases"]["fixture-case-001"]["slots"]
    assert [s["slot_id"] for s in kept] == ["fixture-case-001-s1", "fixture-case-001-s2"]
    assert kept[0]["quote"].startswith("Custom domain costs")


def test_signoff_rejects_missing_reviewer(signoff_fixture):
    draft, review = signoff_fixture
    review["reviewed_by"] = "  "
    with pytest.raises(ValueError, match="reviewer identity"):
        formal_signoff.validate_signoff(review, draft)


def test_signoff_rejects_naive_timestamp(signoff_fixture):
    draft, review = signoff_fixture
    review["reviewed_at"] = "2026-11-06T10:00:00"
    with pytest.raises(ValueError, match="timezone"):
        formal_signoff.validate_signoff(review, draft)


def test_signoff_rejects_changed_provenance(signoff_fixture):
    draft, review = signoff_fixture
    review["slot_selection_rule"] = "something else"
    with pytest.raises(ValueError, match="slot_selection_rule"):
        formal_signoff.validate_signoff(review, draft)


def test_signoff_rejects_incomplete_slot_coverage(signoff_fixture):
    draft, review = signoff_fixture
    review["cases"]["fixture-case-001"]["slots"] = [
        review["cases"]["fixture-case-001"]["slots"][0]
    ]
    with pytest.raises(ValueError, match="every queued slot"):
        formal_signoff.validate_signoff(review, draft)


def test_signoff_rejects_confirmed_slot_with_changed_quote(signoff_fixture):
    draft, review = signoff_fixture
    slots = review["cases"]["fixture-case-001"]["slots"]
    slots[0]["quote"] = "totally different"
    with pytest.raises(ValueError, match="Confirmed slot changed"):
        formal_signoff.validate_signoff(review, draft)


def test_signoff_merges_corrected_slot_and_requires_reason(signoff_fixture):
    draft, review = signoff_fixture
    slots = review["cases"]["fixture-case-001"]["slots"]
    corrected = dict(slots[0], verdict="corrected", claim_zh="改后的结论", reason="原文少看了半句")
    slots[0] = corrected
    summary, gold = formal_signoff.validate_signoff(review, draft)
    assert gold["cases"]["fixture-case-001"]["slots"][0]["claim_zh"] == "改后的结论"

    bad = json.loads(json.dumps(review))
    bad["cases"]["fixture-case-001"]["slots"][0].pop("reason")
    with pytest.raises(ValueError, match="needs a reason"):
        formal_signoff.validate_signoff(bad, draft)


def test_signoff_requires_reason_for_rejected_slot(signoff_fixture):
    draft, review = signoff_fixture
    slots = review["cases"]["fixture-case-001"]["slots"]
    slots[1] = dict(slots[1], verdict="rejected")
    with pytest.raises(ValueError, match="Rejected slot needs a reason"):
        formal_signoff.validate_signoff(review, draft)
    slots[1]["reason"] = "当时快照里其实有这一条"
    summary, _ = formal_signoff.validate_signoff(review, draft)
    assert summary["slots_rejected"] == 1 and summary["slots_kept"] == 1


def test_signoff_rejects_slot_hash_not_in_bundle(signoff_fixture):
    draft, review = signoff_fixture
    slots = review["cases"]["fixture-case-001"]["slots"]
    slots[0] = dict(
        slots[0], verdict="corrected", content_sha256="0" * 64, reason="更正引用页"
    )
    with pytest.raises(ValueError, match="does not match frozen bundle"):
        formal_signoff.validate_signoff(review, draft)
