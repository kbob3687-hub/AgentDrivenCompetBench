"""Build an unlabeled human review queue from one captured live benchmark run."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark.evaluators.citation_eval import claim_slots


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(report: str, heading: str) -> str:
    start = report.find(heading)
    if start < 0:
        return ""
    end = report.find("\n## ", start + len(heading))
    return report[start : end if end >= 0 else None][:3500]


def first_claim(profile: Any, root: str) -> tuple[str | None, dict | None]:
    for path, claim in claim_slots(profile):
        if (
            path.startswith(root)
            and isinstance(claim, dict)
            and str(claim.get("claim", "")).strip()
        ):
            return path, claim
    return None, None


def sources_for(claim: dict | None, captured: dict[str, list[dict]], run: Path) -> list[dict]:
    sources = []
    for source in (claim or {}).get("sources") or []:
        if not isinstance(source, dict):
            sources.append({"raw_source": source, "capture_status": "invalid_reference"})
            continue
        url = source.get("url")
        snapshots = captured.get(url, [])
        for snapshot in snapshots:
            content_path = snapshot.get("content_path")
            if content_path:
                path = run / content_path
                if digest(path) != snapshot["content_sha256"]:
                    raise ValueError(f"Captured source hash mismatch: {path}")
        sources.append(
            {
                "url": url,
                "title": source.get("title"),
                "snippet": source.get("snippet"),
                "capture_status": (
                    "captured"
                    if any(item.get("content_path") for item in snapshots)
                    else "fetch_failed"
                    if snapshots
                    else "not_captured"
                ),
                "captures": [
                    {
                        "observed_at": item.get("observed_at"),
                        "snapshot_path": item.get("content_path"),
                        "snapshot_sha256": item.get("content_sha256"),
                        "collector_snapshot_hash": item.get("collector_snapshot_hash"),
                    }
                    for item in snapshots
                ],
            }
        )
    return sources


def prepare(run: Path, expected_tasks: int = 3) -> dict:
    manifest = json.loads((run / "manifest.json").read_text("utf-8"))
    if manifest.get("provenance") != "live_workflow" or not manifest["config"].get(
        "capture_sources"
    ):
        raise ValueError("A real workflow run with --capture-sources is required")
    if manifest.get("workflow_id") != "standalone":
        raise ValueError("Only standalone workflow runs are supported")
    raw_paths = sorted((run / "raw").glob("*.json"))
    if len(raw_paths) != expected_tasks:
        raise ValueError(
            f"Expected exactly {expected_tasks} real task records, found {len(raw_paths)}"
        )

    tasks = []
    checks = []
    for path in raw_paths:
        raw = json.loads(path.read_text("utf-8"))
        task_id = raw["task_id"]
        snapshot_dir = run / "source_snapshots" / task_id
        snapshot_index = snapshot_dir / "index.json"
        entries = json.loads(snapshot_index.read_text("utf-8"))
        captured: dict[str, list[dict]] = {}
        for entry in entries:
            relative = entry.get("content_path")
            captured.setdefault(entry["url"], []).append(
                {
                    **entry,
                    "content_path": (
                        str((snapshot_dir / relative).relative_to(run)).replace("\\", "/")
                        if relative
                        else None
                    ),
                }
            )
        state = raw.get("state", {})
        profile = state.get("profile") or {}
        report = state.get("report_markdown") or ""
        tasks.append(
            {
                "task_id": task_id,
                "case_id": raw["case_id"],
                "competitor": raw["competitor"],
                "raw_path": str(path.relative_to(run)).replace("\\", "/"),
                "raw_sha256": digest(path),
                "report_path": (
                    f"raw/{task_id}.md" if (run / "raw" / f"{task_id}.md").exists() else None
                ),
                "snapshot_index_path": str(snapshot_index.relative_to(run)).replace("\\", "/"),
                "sources_attempted": len(entries),
                "sources_captured": sum(bool(entry.get("content_path")) for entry in entries),
                "workflow_final_status": state.get("final_status"),
                "qa_verdict": state.get("qa_verdict"),
            }
        )

        def add(
            kind: str, focus: str, locator: str | None, claim: dict | None, context: Any
        ) -> None:
            checks.append(
                {
                    "id": f"{task_id}:{kind}",
                    "task_id": task_id,
                    "criterion": kind,
                    "focus": focus,
                    "locator": locator,
                    "claim": claim.get("claim") if claim else None,
                    "sources": sources_for(claim, captured, run),
                    "context": context,
                    "verdict": None,
                    "reviewer_evidence": None,
                    "reviewer_reason": None,
                }
            )

        pricing = profile.get("pricing") if isinstance(profile, dict) else None
        pricing = pricing if isinstance(pricing, dict) else {}
        add(
            "pricing_basis",
            "定价层级及价格是否有充分的实际来源依据；逐项核对币种、账期与限制",
            "profile.pricing",
            pricing.get("evidence"),
            {
                "tiers": pricing.get("tiers"),
                "model_type": pricing.get("model_type"),
                "report_excerpt": section(report, "## 2. 定价分析"),
            },
        )
        for root, label in (
            ("feature_tree", "feature_snippet_support"),
            ("user_personas", "persona_snippet_support"),
            ("swot", "swot_snippet_support"),
        ):
            locator, claim = first_claim(profile, root)
            add(
                label,
                "完整结论是否得到它实际引用的 snippet 支持；多个子事实需逐一核对",
                f"profile.{locator}" if locator else None,
                claim,
                None,
            )
        add(
            "missing_disclosure",
            "缺失或抓取失败的信息是否明确标为本轮未知，避免把未知说成产品没有",
            "report_markdown",
            None,
            {
                "missing_dimensions": state.get("missing_dimensions") or [],
                "collect_errors": state.get("collect_errors") or [],
                "qa_issues": state.get("qa_issues") or [],
                "pricing_excerpt": section(report, "## 2. 定价分析"),
                "user_feedback_excerpt": section(report, "## 5. 用户真实反馈"),
            },
        )
    return {
        "status": "awaiting_human_review",
        "workflow_id": "standalone",
        "run_id": manifest["run_id"],
        "manifest_sha256": digest(run / "manifest.json"),
        "selection_rule": (
            "One pricing, first nonblank feature/persona/SWOT claim, "
            "and missing-data disclosure per task"
        ),
        "tasks": tasks,
        "checks": checks,
        "reviewed_by": None,
        "reviewed_at": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-tasks", type=int, default=3)
    args = parser.parse_args()
    run = args.run.resolve()
    queue = prepare(run, args.expected_tasks)
    path = run / "review_queue.draft.json"
    if path.exists():
        raise FileExistsError(f"Review queue already exists: {path}")
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(queue['checks'])} unlabeled checks: {path}")


if __name__ == "__main__":
    main()
