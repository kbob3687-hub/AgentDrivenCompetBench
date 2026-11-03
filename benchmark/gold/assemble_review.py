"""Combine three successful captured tasks into one unlabeled review packet."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def assemble(selection: dict) -> dict:
    if len(selection.get("tasks", [])) != 3:
        raise ValueError("Select exactly three real tasks")
    tasks = []
    checks = []
    seen_cases = set()
    for choice in selection["tasks"]:
        run = ROOT / choice["run"]
        manifest = json.loads((run / "manifest.json").read_text("utf-8"))
        if manifest.get("provenance") != "live_workflow" or not manifest.get("config", {}).get(
            "capture_sources"
        ):
            raise ValueError(f"Not a captured live workflow: {run}")
        queue = json.loads((run / "review_queue.draft.json").read_text("utf-8"))
        metrics = json.loads((run / "metrics.json").read_text("utf-8"))
        task = next((t for t in queue["tasks"] if t["task_id"] == choice["task_id"]), None)
        row = next((t for t in metrics["tasks"] if t["task_id"] == choice["task_id"]), None)
        if not task or not row or row["metrics"]["workflow_success"]["value"] is not True:
            raise ValueError(f"Task lacks successful real output: {choice['task_id']}")
        if task["sources_captured"] < 1 or not task["report_path"]:
            raise ValueError(f"Task lacks source text or report: {choice['task_id']}")
        if not (run / task["report_path"]).is_file():
            raise ValueError(f"Report file missing: {choice['task_id']}")
        raw_path = run / task["raw_path"]
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != task["raw_sha256"]:
            raise ValueError(f"Raw task hash mismatch: {choice['task_id']}")
        snapshot_entries = json.loads((run / task["snapshot_index_path"]).read_text("utf-8"))
        snapshot_dir = (run / task["snapshot_index_path"]).parent
        for entry in snapshot_entries:
            if entry.get("capture_kind") != "collector_fetch_exact_redacted_text":
                raise ValueError(f"Not an in-workflow source capture: {choice['task_id']}")
            if entry.get("content_path"):
                content = (snapshot_dir / entry["content_path"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != entry["content_sha256"]:
                    raise ValueError(f"Snapshot hash mismatch: {choice['task_id']}")
        if task["case_id"] in seen_cases:
            raise ValueError("Select three distinct case IDs")
        seen_cases.add(task["case_id"])
        tasks.append({**task, "run": choice["run"]})
        selected_checks = [c for c in queue["checks"] if c["task_id"] == choice["task_id"]]
        if len(selected_checks) != 5 or any(c["verdict"] is not None for c in selected_checks):
            raise ValueError(f"Expected five unlabeled checks: {choice['task_id']}")
        checks.extend({**check, "run": choice["run"]} for check in selected_checks)
    return {
        "status": "awaiting_human_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "case_count": 3,
        "selection_rule": (
            "One pricing, first feature/persona/SWOT claim, and missing-data disclosure per case"
        ),
        "tasks": tasks,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text("utf-8"))
    bundle = assemble(selection)
    destination = args.selection.with_name("phase1_review.draft.json")
    if destination.exists():
        raise FileExistsError(f"Review packet already exists: {destination}")
    destination.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(bundle['checks'])} unlabeled checks: {destination}")


if __name__ == "__main__":
    main()
