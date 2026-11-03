"""Prepare and validate a human-reviewed quality set; never infer human labels."""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from benchmark.gold.snapshot_sources import HERE, ROOT, sha256

VERDICTS = {
    "pricing_basis": {"supported", "partial", "unsupported", "unverifiable"},
    "snippet_support": {"supported", "partial", "unsupported", "unverifiable"},
    "missing_disclosure": {"honest", "misleading", "not_applicable", "unverifiable"},
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def prepare(queue: dict, index: dict) -> dict:
    tasks = {item["id"]: item for item in index["tasks"]}
    sources = {item["url"]: item for item in index["sources"]}
    checks = []
    for check in queue["checks"]:
        if check["criterion"] not in VERDICTS or check["task"] not in tasks:
            raise ValueError(f"Unknown criterion/task in {check['id']}")
        urls = check["source_urls"]
        if any(url not in sources for url in urls):
            # An uncited comparison page may reveal that a report overstates absence.
            raise ValueError(f"Unknown source URL in {check['id']}")
        checks.append(
            {
                **check,
                "raw_sha256": tasks[check["task"]]["raw_sha256"],
                "source_sha256": {url: sources[url]["content_sha256"] for url in urls},
                "verdict": None,
                "rationale": None,
                "evidence_quote_or_location": None,
            }
        )
    return {
        "status": "awaiting_human_review",
        "snapshot_kind": index["snapshot_kind"],
        "reviewed_by": None,
        "reviewed_at": None,
        "checks": checks,
    }


def validate_review(review: dict, queue: dict, index: dict) -> dict:
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

    expected = {item["id"]: item for item in prepare(queue, index)["checks"]}
    if review.get("snapshot_kind") != index["snapshot_kind"]:
        raise ValueError("Snapshot provenance changed")
    actual = review.get("checks")
    if not isinstance(actual, list) or {x.get("id") for x in actual} != set(expected):
        raise ValueError("Review must cover every queued check exactly once")
    if len(actual) != len(expected):
        raise ValueError("Duplicate review check IDs")
    tasks = {item["id"]: item for item in index["tasks"]}
    sources = {item["url"]: item for item in index["sources"]}
    for item in actual:
        baseline = expected[item["id"]]
        for field in (
            "task",
            "criterion",
            "locator",
            "focus",
            "source_urls",
            "raw_sha256",
            "source_sha256",
        ):
            if item.get(field) != baseline[field]:
                raise ValueError(f"Review provenance changed: {item['id']}.{field}")
        if item.get("verdict") not in VERDICTS[item["criterion"]]:
            raise ValueError(f"Invalid verdict: {item['id']}")
        for field in ("rationale", "evidence_quote_or_location"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing reviewer {field}: {item['id']}")
        raw_path = ROOT / tasks[item["task"]]["raw"]
        if sha256(raw_path.read_bytes()) != item["raw_sha256"]:
            raise ValueError(f"Raw task changed: {item['id']}")
        for url, digest in item["source_sha256"].items():
            source = sources[url]
            if digest is None:
                if item["verdict"] != "unverifiable" and len(item["source_urls"]) == 1:
                    raise ValueError(f"Unavailable sole source requires unverifiable: {item['id']}")
                continue
            path = HERE / source["content_path"]
            if sha256(path.read_bytes()) != digest:
                raise ValueError(f"Snapshot changed: {item['id']} {url}")
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
        "snapshot_kind": review["snapshot_kind"],
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "check_counts": by_criterion,
        "note": "Counts of human judgments only; no composite score or automated truth claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--review", type=Path, help="Completed human review JSON to validate")
    args = parser.parse_args()
    if args.prepare == bool(args.review):
        parser.error("Choose exactly one of --prepare or --review")
    queue = read_json(HERE / "review_queue.json")
    index = read_json(HERE / "snapshots/index.json")
    if args.prepare:
        draft = prepare(queue, index)
        path = HERE / "review.draft.json"
        if path.exists():
            raise FileExistsError("Review draft already exists; refusing to overwrite")
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)
    else:
        summary = validate_review(read_json(args.review), queue, index)
        path = args.review.with_name("review.summary.json")
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
