"""Content metrics from human output judgments (docs §9.4-9.5).

Consumes the frozen gold set (formal_signoff output) plus a human-reviewed file
of per-output judgments — one verdict per (slot, arm, run) — and reports the six
§9.5 formulas per arm, always with numerator and denominator. Never infers
labels and never reuses a label across runs; every judgment names its own run.
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VERDICTS = ("supported", "partial", "unsupported", "honest_unknown", "missing")
EXPECT_UNKNOWN_TYPE = "missing_dimension"
ARMS = ("multi_agent_qa_fixed", "multi_agent_no_qa", "single_llm")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _check_header(review: dict) -> None:
    if review.get("status") != "human_reviewed":
        raise ValueError("Judgments are not marked human_reviewed")
    if not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip():
        raise ValueError("Human reviewer identity is required")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Valid reviewed_at timestamp is required") from exc
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include timezone")


def gold_slot_list(gold: dict) -> list[dict]:
    return [slot for case in gold["cases"].values() for slot in case["slots"]]


def validate_judgments(judgments: dict, gold: dict) -> list[dict]:
    _check_header(judgments)
    known = {slot["slot_id"] for slot in gold_slot_list(gold)}
    entries = judgments.get("judgments")
    if not isinstance(entries, list) or not entries:
        raise ValueError("judgments.judgments must be a non-empty list")
    seen: set[tuple[str, str, str]] = set()
    for item in entries:
        key = (item.get("slot_id"), item.get("arm"), item.get("run_id"))
        if not all(isinstance(part, str) and part.strip() for part in key):
            raise ValueError("Each judgment needs slot_id, arm, and run_id")
        if key in seen:
            raise ValueError(f"Duplicate judgment for slot/arm/run: {key}")
        seen.add(key)
        if key[0] not in known:
            raise ValueError(f"Unknown slot_id: {key[0]}")
        if item.get("verdict") not in VERDICTS:
            raise ValueError(f"Invalid verdict: {key[0]} -> {item.get('verdict')}")
        for field in ("evidence", "reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing judgment {field}: {key}")
    return entries


def _rate(numerator: float, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (numerator / denominator) if denominator else None,
    }


def compute(gold: dict, judgments: dict) -> dict:
    entries = validate_judgments(judgments, gold)
    slots = gold_slot_list(gold)
    g = len(slots)
    expect_unknown_ids = {
        slot["slot_id"] for slot in slots if slot["slot_type"] == EXPECT_UNKNOWN_TYPE
    }

    per_arm: dict[str, list[dict]] = defaultdict(list)
    for item in entries:
        per_arm[item["arm"]].append(item)

    arms: dict[str, dict] = {}
    for arm in sorted(per_arm):
        items = per_arm[arm]
        counts: dict[str, int] = {verdict: 0 for verdict in VERDICTS}
        for item in items:
            if item["verdict"] == "honest_unknown" and item["slot_id"] not in expect_unknown_ids:
                raise ValueError(
                    f"honest_unknown only valid for {EXPECT_UNKNOWN_TYPE} slots: {item['slot_id']}"
                )
            counts[item["verdict"]] += 1
        runs = len({item["run_id"] for item in items})
        judged_pairs = {(item["run_id"], item["slot_id"]) for item in items}
        expected_pairs = runs * g
        evidence = counts["supported"] + counts["partial"] + counts["unsupported"]
        arms[arm] = {
            "runs_judged": runs,
            "slots_per_run": g,
            "complete_matrix": len(judged_pairs) == expected_pairs,
            "metrics": {
                "gold_coverage": _rate(counts["supported"] + counts["partial"], expected_pairs),
                "full_support_rate": _rate(counts["supported"], evidence),
                "unsupported_rate": _rate(counts["unsupported"], evidence),
                "partial_rate": _rate(counts["partial"], evidence),
                "honest_unknown_rate": _rate(
                    counts["honest_unknown"], runs * len(expect_unknown_ids)
                ),
                "missing_rate": _rate(counts["missing"], expected_pairs),
            },
            "verdict_counts": counts,
        }

    return {
        "status": "human_reviewed",
        "reviewed_by": judgments["reviewed_by"],
        "reviewed_at": judgments["reviewed_at"],
        "gold_slots": g,
        "expect_unknown_slots": len(expect_unknown_ids),
        "arms": arms,
        "note": (
            "Denominators scale with judged runs; complete_matrix=False means some "
            "slot/run cells are unjudged and the rates cover only what was judged. "
            "partial counts as neither full support nor unsupported."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True, help="Frozen gold set from signoff")
    parser.add_argument("--judgments", type=Path, required=True, help="Human output judgments JSON")
    parser.add_argument(
        "--out", type=Path, help="Summary path (default: alongside the judgments file)"
    )
    args = parser.parse_args()
    summary = compute(read_json(args.gold), read_json(args.judgments))
    out = args.out or args.judgments.with_name("formal_content_metrics.summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
