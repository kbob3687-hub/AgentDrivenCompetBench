import json
from datetime import datetime, timedelta, timezone

import pytest

from benchmark.gold import phase1_signoff


@pytest.fixture
def signoff_fixture(tmp_path, monkeypatch):
    run = tmp_path / "run"
    snap_dir = run / "source_snapshots/task-a-r1-c1"
    snap_dir.mkdir(parents=True)
    raw = run / "raw/task-a-r1-c1.json"
    raw.parent.mkdir()
    raw.write_text('{"state": {"profile": {}}}', encoding="utf-8")
    report = run / "raw/task-a-r1-c1.md"
    report.write_text("# report", encoding="utf-8")
    source = snap_dir / "page.txt"
    source.write_text("Start free trial", encoding="utf-8")
    index = snap_dir / "index.json"
    index.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.com/pricing",
                    "capture_kind": "collector_fetch_exact_redacted_text",
                    "content_path": "page.txt",
                    "content_sha256": phase1_signoff.sha256(source.read_bytes()),
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(phase1_signoff, "ROOT", tmp_path)
    task = {
        "task_id": "task-a-r1-c1",
        "case_id": "task-a",
        "competitor": "TaskA",
        "raw_path": "raw/task-a-r1-c1.json",
        "raw_sha256": phase1_signoff.sha256(raw.read_bytes()),
        "report_path": "raw/task-a-r1-c1.md",
        "snapshot_index_path": "source_snapshots/task-a-r1-c1/index.json",
        "run": "run",
    }
    checks = [
        {
            "id": f"task-a-r1-c1:{criterion}",
            "task_id": "task-a-r1-c1",
            "criterion": criterion,
            "locator": "profile.pricing",
            "claim": "claim",
            "sources": [],
            "run": "run",
        }
        for criterion in ("pricing_basis", "missing_disclosure")
    ]
    draft = {
        "status": "awaiting_human_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "case_count": 1,
        "selection_rule": "test",
        "tasks": [task],
        "checks": checks,
    }
    completed = json.loads(json.dumps(draft))
    completed["status"] = "human_reviewed"
    completed["reviewed_by"] = "硝酸铜"
    completed["reviewed_at"] = datetime(2026, 10, 28, 21, 0, tzinfo=timezone(timedelta(hours=8)))
    completed["reviewed_at"] = completed["reviewed_at"].isoformat(timespec="seconds")
    for check, verdict in zip(completed["checks"], ("partial", "honest"), strict=True):
        check["verdict"] = verdict
        check["reviewer_evidence"] = "evidence"
        check["reviewer_reason"] = "reason"
    return draft, completed


def test_signoff_validates_complete_review(signoff_fixture):
    draft, completed = signoff_fixture
    summary = phase1_signoff.validate_signoff(completed, draft)
    assert summary["status"] == "human_reviewed"
    assert summary["reviewed_by"] == "硝酸铜"
    assert summary["check_counts"]["pricing_basis"]["partial"] == 1
    assert summary["check_counts"]["missing_disclosure"]["honest"] == 1


def test_signoff_rejects_unlabeled_checks(signoff_fixture):
    draft, completed = signoff_fixture
    completed["checks"][0]["verdict"] = None
    with pytest.raises(ValueError, match="Invalid verdict"):
        phase1_signoff.validate_signoff(completed, draft)


def test_signoff_rejects_missing_reviewer(signoff_fixture):
    draft, completed = signoff_fixture
    completed["reviewed_by"] = "  "
    with pytest.raises(ValueError, match="reviewer identity"):
        phase1_signoff.validate_signoff(completed, draft)


def test_signoff_rejects_tampered_raw_on_disk(signoff_fixture):
    draft, completed = signoff_fixture
    raw = phase1_signoff.ROOT / "run/raw/task-a-r1-c1.json"
    raw.write_text('{"state": {"profile": {"tampered": true}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Raw task changed"):
        phase1_signoff.validate_signoff(completed, draft)


def test_signoff_rejects_tampered_snapshot_on_disk(signoff_fixture):
    draft, completed = signoff_fixture
    page = phase1_signoff.ROOT / "run/source_snapshots/task-a-r1-c1/page.txt"
    page.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="Snapshot hash mismatch"):
        phase1_signoff.validate_signoff(completed, draft)
