"""Human sign-off validator for the 24 formal gold slots (docs §9.2-9.4).

Reads the immutable draft (provenance baseline) plus a completed human review of
every slot and refuses to emit the frozen gold set unless each slot is confirmed
(as-is), corrected (changed fields + reason), or rejected (reason), the reviewer
identity/time are real, and every kept fact's quote URL/content hash still
matches the frozen replay bundle on disk. Never invents labels.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DRAFT = Path(__file__).with_name("formal_gold_slots.draft.json")

TRUTH_FIELDS = ("claim_zh", "claim_en", "quote", "url", "content_sha256")
MISSING_FIELDS = ("claim_zh", "missing_keywords", "urls_searched")
VERDICTS = ("confirmed", "corrected", "rejected")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _check_header(review: dict) -> None:
    if review.get("status") != "human_reviewed":
        raise ValueError("Review is not marked human_reviewed")
    if not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip():
        raise ValueError("Human reviewer identity is required")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Valid reviewed_at timestamp is required") from exc
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include timezone")


def _bundle_entries(case: str) -> list[dict]:
    index = ROOT / "benchmark/replay_bundles" / f"{case}-c1" / "index.json"
    return read_json(index)["entries"]


def _verify_against_bundle(case: str, slot: dict) -> None:
    if not slot.get("url") or not slot.get("content_sha256"):
        return
    entries = _bundle_entries(case)
    if not any(
        entry.get("url") == slot["url"] and entry.get("content_sha256") == slot["content_sha256"]
        for entry in entries
    ):
        raise ValueError(f"Slot {slot['slot_id']} does not match frozen bundle {case}-c1")


def validate_signoff(review: dict, draft: dict) -> tuple[dict, dict]:
    _check_header(review)
    if review.get("slot_selection_rule") != draft["slot_selection_rule"]:
        raise ValueError("Review provenance changed: slot_selection_rule")
    if set(review.get("cases") or {}) != set(draft["cases"]):
        raise ValueError("Review must cover exactly the draft's cases")

    gold_cases: dict[str, dict] = {}
    kept, rejected = 0, 0
    for case, case_review in review["cases"].items():
        case_draft = draft["cases"][case]
        if case_review.get("snapshot_bundle") != case_draft["snapshot_bundle"]:
            raise ValueError(f"Review provenance changed: {case}.snapshot_bundle")
        expected = {slot["slot_id"]: slot for slot in case_draft["slots"]}
        actual = case_review.get("slots")
        if not isinstance(actual, list) or {x.get("slot_id") for x in actual} != set(expected):
            raise ValueError(f"Review must cover every queued slot exactly once: {case}")
        if len(actual) != len(expected):
            raise ValueError(f"Duplicate review slot IDs: {case}")

        kept_slots = []
        for entry in actual:
            baseline = dict(expected[entry["slot_id"]])
            verdict = entry.get("verdict")
            if verdict not in VERDICTS:
                raise ValueError(f"Invalid verdict: {entry['slot_id']}")
            if verdict == "confirmed":
                for field in baseline:
                    if field != "slot_type" and entry.get(field) not in (None, baseline[field]):
                        raise ValueError(f"Confirmed slot changed: {entry['slot_id']}.{field}")
                kept += 1
                kept_slots.append(baseline)
            elif verdict == "corrected":
                for field in baseline:
                    if entry.get(field) is not None and field != "slot_type":
                        baseline[field] = entry[field]
                required = (
                    MISSING_FIELDS if baseline["slot_type"] == "missing_dimension" else TRUTH_FIELDS
                )
                for field in required:
                    if baseline.get(field) in (None, "", []):
                        raise ValueError(
                            f"Corrected slot lost required field: {entry['slot_id']}.{field}"
                        )
                if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                    raise ValueError(f"Corrected slot needs a reason: {entry['slot_id']}")
                kept += 1
                kept_slots.append(baseline)
            else:
                if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                    raise ValueError(f"Rejected slot needs a reason: {entry['slot_id']}")
                rejected += 1

        for slot in kept_slots:
            _verify_against_bundle(case, slot)

        gold_cases[case] = {
            "snapshot_bundle": case_draft["snapshot_bundle"],
            "slots": kept_slots,
        }

    gold = {
        "kind": "formal_gold_slots",
        "status": "frozen",
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "slot_selection_rule": draft["slot_selection_rule"],
        "cases": gold_cases,
    }
    summary = {
        "status": "human_reviewed",
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "slots_kept": kept,
        "slots_rejected": rejected,
        "note": "Frozen gold set only; output judgments are separate and never reused across runs.",
    }
    return summary, gold


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True, help="Completed slot review JSON")
    parser.add_argument("--draft", type=Path, default=DRAFT, help="Provenance baseline draft")
    args = parser.parse_args()
    summary, gold = validate_signoff(read_json(args.review), read_json(args.draft))
    gold_path = args.review.with_name("formal_gold_slots.gold.json")
    summary_path = args.review.with_name("formal_gold_slots.summary.json")
    gold_path.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{gold_path}\n{summary_path}")


if __name__ == "__main__":
    main()
