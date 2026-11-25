"""Blind the three arms' outputs before human judgment (docs §9.3 step 4).

For every (case, repeat) group, shuffle the three arms' reports into anonymous
A/B/C codes so the human judge cannot tell which architecture produced which
report. Writes a blind queue (no arm info) plus a separate mapping file;
after judging, `unblind` converts the filled judgments into the input format
of content_metrics. Same seed reproduces the same assignment.
"""

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from benchmark.gold.content_metrics import VERDICTS, _check_header

CODES = ("A", "B", "C")
EXPECTED_ARMS = ("multi_agent_qa_fixed", "multi_agent_no_qa", "single_llm")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def arm_of(manifest: dict) -> str:
    provenance = manifest.get("provenance", "")
    if "single_llm" in provenance:
        return "single_llm"
    if "workflow" in provenance:
        return "multi_agent_qa_fixed" if manifest.get("enable_qa") else "multi_agent_no_qa"
    raise ValueError(f"Cannot determine arm from manifest provenance: {provenance!r}")


def load_reports(run_dir: Path, include_failed: bool = False) -> dict[tuple[str, int], dict]:
    run_id = run_dir.name
    manifest = read_json(run_dir / "manifest.json")
    arm = arm_of(manifest)
    found: dict[tuple[str, int], dict] = {}
    for raw in sorted((run_dir / "raw").glob("*.json")):
        data = read_json(raw)
        report = (data.get("state") or {}).get("report_markdown")
        report_missing = not isinstance(report, str) or not report.strip()
        if report_missing:
            if not include_failed:
                print(f"warning: no report in {run_id}/raw/{raw.name}, skipped")
                continue
            report = "[TASK_FAILED_NO_REPORT]"
        key = (data["case_id"], int(data["repeat"]))
        if key in found:
            raise ValueError(f"{run_id} has two reports for {key}")
        found[key] = {
            "arm": arm,
            "run_id": run_id,
            "task_id": data.get("task_id", raw.stem),
            "final_status": (data.get("state") or {}).get("final_status", ""),
            "report_markdown": report,
            "report_missing": report_missing,
        }
    return found


def _group_outputs(reports: dict[Path, dict[tuple[str, int], dict]]) -> dict[tuple[str, int], dict]:
    groups: dict[tuple[str, int], dict] = {}
    for run_dir, entries in reports.items():
        for key, entry in entries.items():
            group = groups.setdefault(key, {})
            if entry["arm"] in group:
                raise ValueError(f"{key} has two outputs from {entry['arm']}")
            group[entry["arm"]] = entry
    for key, group in groups.items():
        missing = set(EXPECTED_ARMS) - set(group)
        if missing:
            raise ValueError(f"{key} is missing arms: {sorted(missing)}")
    return groups


def blind(
    runs: list[Path], gold: dict, out_dir: Path, seed: int, include_failed: bool = False
) -> dict:
    slots_by_case = {case: data["slots"] for case, data in gold["cases"].items()}
    groups = _group_outputs({run: load_reports(run, include_failed=include_failed) for run in runs})
    unknown = {key[0] for key in groups} - set(slots_by_case)
    if unknown:
        raise ValueError(f"Outputs reference cases absent from gold set: {sorted(unknown)}")

    rng = random.Random(seed)
    samples, mapping_entries = [], []
    for case, repeat in sorted(groups):
        entries = list(groups[(case, repeat)].values())
        rng.shuffle(entries)
        for code, entry in zip(CODES, entries, strict=True):
            anon_id = f"{case}-r{repeat}-{code}"
            samples.append(
                {
                    "anon_id": anon_id,
                    "case": case,
                    "repeat": repeat,
                    "report_markdown": entry["report_markdown"],
                    "slots": slots_by_case[case],
                }
            )
            mapping_entries.append(
                {
                    "anon_id": anon_id,
                    "arm": entry["arm"],
                    "run_id": entry["run_id"],
                    "task_id": entry["task_id"],
                    "final_status": entry["final_status"],
                    "report_missing": bool(entry.get("report_missing", False)),
                    "case": case,
                    "repeat": repeat,
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path = out_dir / "blind_queue.json"
    mapping_path = out_dir / "blind_mapping.json"
    for path in (queue_path, mapping_path):
        if path.exists():
            raise ValueError(f"Refusing to overwrite: {path}")
    queue = {
        "kind": "formal_blind_queue",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "Anonymous samples only; arm identity is in blind_mapping.json.",
        "samples": samples,
    }
    mapping = {
        "kind": "formal_blind_mapping",
        "seed": seed,
        "runs": [run.name for run in runs],
        "samples": mapping_entries,
    }
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"queue": queue_path, "mapping": mapping_path, "samples": len(samples)}


def unblind(filled: dict, mapping: dict, gold: dict) -> dict:
    _check_header(filled)
    slots_by_case = {case: data["slots"] for case, data in gold["cases"].items()}
    by_anon = {entry["anon_id"]: entry for entry in mapping["samples"]}
    if len(by_anon) != len(mapping["samples"]):
        raise ValueError("Duplicate anon_id in mapping")

    seen: set[tuple[str, str]] = set()
    judgments: list[dict] = []
    for item in filled.get("judgments") or []:
        anon_id, slot_id = item.get("anon_id"), item.get("slot_id")
        if not isinstance(anon_id, str) or anon_id not in by_anon:
            raise ValueError(f"Unknown anon_id: {anon_id!r}")
        if item.get("verdict") not in VERDICTS:
            raise ValueError(f"Invalid verdict: {anon_id}/{slot_id} -> {item.get('verdict')}")
        for field in ("evidence", "reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing judgment {field}: {anon_id}/{slot_id}")
        key = (anon_id, slot_id)
        if key in seen:
            raise ValueError(f"Duplicate judgment: {key}")
        seen.add(key)
        entry = by_anon[anon_id]
        judgments.append(
            {
                "slot_id": slot_id,
                "arm": entry["arm"],
                "run_id": entry["run_id"],
                "verdict": item["verdict"],
                "evidence": item["evidence"],
                "reason": item["reason"],
            }
        )

    missing: list[str] = []
    for entry in mapping["samples"]:
        for slot in slots_by_case[entry["case"]]:
            if (entry["anon_id"], slot["slot_id"]) not in seen:
                missing.append(f"{entry['anon_id']}/{slot['slot_id']}")
    if missing:
        raise ValueError(f"{len(missing)} judgments still missing, e.g.: {missing[:5]}")

    return {
        "kind": "formal_gold_output_review",
        "status": "human_reviewed",
        "reviewed_by": filled["reviewed_by"],
        "reviewed_at": filled["reviewed_at"],
        "judgments": judgments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_blind = sub.add_parser("blind", help="Build the blind queue and the secret mapping")
    p_blind.add_argument("--runs", type=Path, nargs="+", required=True, help="One dir per arm")
    p_blind.add_argument("--gold", type=Path, required=True, help="Frozen gold set from signoff")
    p_blind.add_argument("--out-dir", type=Path, required=True)
    p_blind.add_argument("--seed", type=int, default=0)
    p_blind.add_argument(
        "--include-failed",
        action="store_true",
        help="Keep recorded failed tasks with a report placeholder instead of aborting",
    )

    p_unblind = sub.add_parser("unblind", help="Convert filled blind judgments for content_metrics")
    p_unblind.add_argument("--filled", type=Path, required=True)
    p_unblind.add_argument("--mapping", type=Path, required=True)
    p_unblind.add_argument("--gold", type=Path, required=True)
    p_unblind.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "blind":
        result = blind(
            args.runs,
            read_json(args.gold),
            args.out_dir,
            args.seed,
            include_failed=args.include_failed,
        )
        print(f"{result['queue']}\n{result['mapping']}\nsamples: {result['samples']}")
        return
    filled = read_json(args.filled)
    out = unblind(filled, read_json(args.mapping), read_json(args.gold))
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
