import hashlib
import json
from pathlib import Path

import pytest

from benchmark.gold import assemble_review
from benchmark.gold.prepare_live import prepare


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_prepare_creates_only_unlabeled_checks_from_captured_run(tmp_path, profile):
    write_json(
        tmp_path / "manifest.json",
        {
            "provenance": "live_workflow",
            "workflow_id": "standalone",
            "run_id": "fixture-run",
            "config": {"capture_sources": True},
        },
    )
    for number in range(3):
        task_id = f"case-{number}-r1-c1"
        write_json(
            tmp_path / "raw" / f"{task_id}.json",
            {
                "task_id": task_id,
                "case_id": f"case-{number}",
                "competitor": "Fixture",
                "state": {
                    "profile": profile,
                    "report_markdown": "## 2. 定价分析\nPrice\n## 5. 用户真实反馈\nUnknown",
                },
            },
        )
        snapshot = tmp_path / "source_snapshots" / task_id
        snapshot.mkdir(parents=True)
        content = snapshot / "source.txt"
        content.write_text("Page body", encoding="utf-8")
        write_json(
            snapshot / "index.json",
            [
                {
                    "url": "https://example.com/test",
                    "content_path": "source.txt",
                    "content_sha256": hashlib.sha256(content.read_bytes()).hexdigest(),
                }
            ],
        )
    queue = prepare(tmp_path)
    assert len(queue["tasks"]) == 3
    assert len(queue["checks"]) == 15
    assert all(check["verdict"] is None for check in queue["checks"])
    assert all(check["reviewer_reason"] is None for check in queue["checks"])
    assert queue["checks"][0]["sources"][0]["capture_status"] == "captured"


def test_prepare_requires_source_capture(tmp_path):
    write_json(
        tmp_path / "manifest.json",
        {"provenance": "live_workflow", "workflow_id": "standalone", "config": {}},
    )
    with pytest.raises(ValueError, match="capture-sources"):
        prepare(tmp_path)


def test_assemble_requires_three_successful_distinct_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(assemble_review, "ROOT", tmp_path)
    selections = []
    for number in range(3):
        run = tmp_path / f"run-{number}"
        task_id = f"case-{number}-r1-c1"
        write_json(
            run / "manifest.json",
            {"provenance": "live_workflow", "config": {"capture_sources": True}},
        )
        raw_path = run / "raw" / f"{task_id}.json"
        write_json(raw_path, {"task_id": task_id})
        (run / "raw" / f"{task_id}.md").write_text("Fixture report", encoding="utf-8")
        snapshot = run / "source_snapshots" / task_id
        snapshot.mkdir(parents=True)
        content = snapshot / "source.txt"
        content.write_text("Actual page", encoding="utf-8")
        write_json(
            snapshot / "index.json",
            [
                {
                    "capture_kind": "collector_fetch_exact_redacted_text",
                    "content_path": "source.txt",
                    "content_sha256": hashlib.sha256(content.read_bytes()).hexdigest(),
                }
            ],
        )
        write_json(
            run / "review_queue.draft.json",
            {
                "tasks": [
                    {
                        "task_id": task_id,
                        "case_id": f"case-{number}",
                        "sources_captured": 1,
                        "report_path": f"raw/{task_id}.md",
                        "raw_path": f"raw/{task_id}.json",
                        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        "snapshot_index_path": f"source_snapshots/{task_id}/index.json",
                    }
                ],
                "checks": [
                    {"task_id": task_id, "verdict": None, "criterion": str(i)} for i in range(5)
                ],
            },
        )
        write_json(
            run / "metrics.json",
            {"tasks": [{"task_id": task_id, "metrics": {"workflow_success": {"value": True}}}]},
        )
        selections.append({"run": f"run-{number}", "task_id": task_id})
    bundle = assemble_review.assemble({"tasks": selections})
    assert bundle["case_count"] == 3
    assert len(bundle["checks"]) == 15
    assert all(item["verdict"] is None for item in bundle["checks"])
    first_metrics = tmp_path / "run-0/metrics.json"
    write_json(
        first_metrics,
        {
            "tasks": [
                {
                    "task_id": "case-0-r1-c1",
                    "metrics": {"workflow_success": {"value": False}},
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="lacks successful real output"):
        assemble_review.assemble({"tasks": selections})
