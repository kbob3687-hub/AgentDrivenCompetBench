"""Sign-off validator for the phase1 15-check human review packet.

Reads the immutable draft (provenance baseline) plus a completed human review and
refuses to summarize unless every check has a real verdict, evidence, reason, reviewer
identity/time, and unchanged raw/snapshot content hashes. Never infers human labels.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DRAFT = Path(__file__).with_name("phase1_review.draft.json")

SNIPPET_CRITERIA = ("feature_snippet_support", "persona_snippet_support", "swot_snippet_support")
VERDICTS = {
    "pricing_basis": {"supported", "partial", "unsupported", "unverifiable"},
    **{name: {"supported", "partial", "unsupported", "unverifiable"} for name in SNIPPET_CRITERIA},
    "missing_disclosure": {"honest", "misleading", "not_applicable", "unverifiable"},
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def validate_signoff(review: dict, draft: dict) -> dict:
    if review.get("status") != "human_reviewed":
        raise ValueError("Review is not marked human_reviewed")
    if not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip():
        raise ValueError("Human reviewer identity is required")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"])
        if reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at must include timezone")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Valid reviewed_at timestamp is required") from exc

    for field in ("selection_rule", "case_count", "tasks"):
        if review.get(field) != draft[field]:
            raise ValueError(f"Review provenance changed: {field}")

    expected = {item["id"]: item for item in draft["checks"]}
    actual = review.get("checks")
    if not isinstance(actual, list) or {x.get("id") for x in actual} != set(expected):
        raise ValueError("Review must cover every queued check exactly once")
    if len(actual) != len(expected):
        raise ValueError("Duplicate review check IDs")

    for item in actual:
        baseline = expected[item["id"]]
        for field in ("task_id", "criterion", "locator", "claim", "sources", "run"):
            if item.get(field) != baseline[field]:
                raise ValueError(f"Review provenance changed: {item['id']}.{field}")
        if item.get("verdict") not in VERDICTS[item["criterion"]]:
            raise ValueError(f"Invalid verdict: {item['id']}")
        for field in ("reviewer_evidence", "reviewer_reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing reviewer {field}: {item['id']}")

    for task in review["tasks"]:
        run = ROOT / task["run"]
        raw_path = run / task["raw_path"]
        if sha256(raw_path.read_bytes()) != task["raw_sha256"]:
            raise ValueError(f"Raw task changed: {task['task_id']}")
        if not (run / task["report_path"]).is_file():
            raise ValueError(f"Report file missing: {task['task_id']}")
        snapshot_dir = run / task["snapshot_index_path"]
        for entry in json.loads(snapshot_dir.read_text("utf-8")):
            if entry.get("capture_kind") != "collector_fetch_exact_redacted_text":
                raise ValueError(f"Not an in-workflow source capture: {task['task_id']}")
            if entry.get("content_path"):
                content = (snapshot_dir.parent / entry["content_path"]).read_bytes()
                if sha256(content) != entry["content_sha256"]:
                    raise ValueError(f"Snapshot hash mismatch: {task['task_id']}")

    return summarize(review)


def summarize(review: dict) -> dict:
    by_criterion = {}
    for criterion in VERDICTS:
        counts = Counter(
            item["verdict"] for item in review["checks"] if item["criterion"] == criterion
        )
        by_criterion[criterion] = {name: counts[name] for name in sorted(VERDICTS[criterion])}
    return {
        "status": "human_reviewed",
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "check_counts": by_criterion,
        "note": "Counts of human judgments only; no composite score or automated truth claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review", type=Path, help="Completed phase1 review JSON to validate", required=True
    )
    parser.add_argument(
        "--draft", type=Path, default=DRAFT, help="Provenance baseline (default: phase1 draft)"
    )
    args = parser.parse_args()
    summary = validate_signoff(read_json(args.review), read_json(args.draft))
    path = args.review.with_name("phase1_review.summary.json")
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
