import json
from pathlib import Path

import pytest

from benchmark.gold import blind_shuffle


@pytest.fixture
def gold():
    return {
        "kind": "formal_gold_slots",
        "status": "frozen",
        "cases": {
            "case-a": {
                "snapshot_bundle": "benchmark/replay_bundles/case-a-c1",
                "slots": [
                    {"slot_id": "case-a-s1", "slot_type": "pricing_fact", "claim_zh": "结论一"},
                    {"slot_id": "case-a-s2", "slot_type": "missing_dimension", "claim_zh": "缺"},
                ],
            }
        },
    }


def _make_run(tmp_path: Path, run_id: str, arm: str, case: str = "case-a", repeat: int = 1) -> Path:
    run_dir = tmp_path / run_id
    (run_dir / "raw").mkdir(parents=True)
    manifest = {"run_id": run_id}
    if arm == "single_llm":
        manifest["provenance"] = "replayed_single_llm_baseline"
        manifest["enable_qa"] = False
    else:
        manifest["provenance"] = "replayed_workflow"
        manifest["enable_qa"] = arm == "multi_agent_qa_fixed"
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    task = {
        "task_id": f"{case}-r{repeat}-c1",
        "case_id": case,
        "repeat": repeat,
        "state": {"report_markdown": "# 竞品分析报告\n\n正文。", "final_status": "ended"},
    }
    (run_dir / "raw" / f"{case}-r{repeat}-c1.json").write_text(
        json.dumps(task, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def _three_runs(tmp_path: Path, repeat: int = 1) -> list[Path]:
    return [
        _make_run(tmp_path, "run-qa", "multi_agent_qa_fixed", repeat=repeat),
        _make_run(tmp_path, "run-noqa", "multi_agent_no_qa", repeat=repeat),
        _make_run(tmp_path, "run-base", "single_llm", repeat=repeat),
    ]


def test_blind_hides_arm_names_and_shuffle_is_reproducible(tmp_path, gold):
    runs = _three_runs(tmp_path)
    blind_shuffle.blind(runs, gold, tmp_path / "out1", seed=7)
    queue_text = (tmp_path / "out1" / "blind_queue.json").read_text("utf-8")
    for secret in ("multi_agent", "single_llm", "run-qa", "run-noqa", "run-base"):
        assert secret not in queue_text
    mapping = json.loads((tmp_path / "out1" / "blind_mapping.json").read_text("utf-8"))
    assert {entry["arm"] for entry in mapping["samples"]} == set(blind_shuffle.EXPECTED_ARMS)
    assert {entry["anon_id"][-1] for entry in mapping["samples"]} == {"A", "B", "C"}

    (tmp_path / "out1").rename(tmp_path / "out1-moved")
    blind_shuffle.blind(runs, gold, tmp_path / "out2", seed=7)
    assignment_1 = {
        e["anon_id"]: e["arm"]
        for e in json.loads((tmp_path / "out1-moved" / "blind_mapping.json").read_text("utf-8"))[
            "samples"
        ]
    }
    mapping_2 = json.loads((tmp_path / "out2" / "blind_mapping.json").read_text("utf-8"))
    assignment_2 = {e["anon_id"]: e["arm"] for e in mapping_2["samples"]}
    assert assignment_1 == assignment_2


def test_blind_refuses_overwrite_and_missing_arm(tmp_path, gold):
    runs = _three_runs(tmp_path)
    out_dir = tmp_path / "out"
    blind_shuffle.blind(runs, gold, out_dir, seed=1)
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        blind_shuffle.blind(runs, gold, out_dir, seed=1)

    (out_dir / "blind_queue.json").unlink()
    (out_dir / "blind_mapping.json").unlink()
    (runs[2] / "raw" / "case-a-r1-c1.json").unlink()
    with pytest.raises(ValueError, match="missing arms"):
        blind_shuffle.blind(runs, gold, out_dir, seed=1)


def test_blind_rejects_duplicate_arm_for_same_case(tmp_path, gold):
    _make_run(tmp_path, "run-qa-2", "multi_agent_qa_fixed")
    runs = _three_runs(tmp_path) + [tmp_path / "run-qa-2"]
    with pytest.raises(ValueError, match="two outputs"):
        blind_shuffle.blind(runs, gold, tmp_path / "out", seed=1)


def _fill(mapping_path: Path, gold: dict, verdict="supported") -> dict:
    mapping = json.loads(Path(mapping_path).read_text("utf-8"))
    return {
        "kind": "formal_blind_filled",
        "status": "human_reviewed",
        "reviewed_by": "硝酸铜",
        "reviewed_at": "2026-11-12T10:00:00+08:00",
        "judgments": [
            {
                "anon_id": entry["anon_id"],
                "slot_id": slot["slot_id"],
                "verdict": verdict,
                "evidence": "报告第 2 段",
                "reason": "与快照一致",
            }
            for entry in mapping["samples"]
            for slot in gold["cases"][entry["case"]]["slots"]
        ],
    }


def test_unblind_roundtrip_restores_arms(tmp_path, gold):
    runs = _three_runs(tmp_path)
    result = blind_shuffle.blind(runs, gold, tmp_path / "out", seed=3)
    mapping = json.loads(Path(result["mapping"]).read_text("utf-8"))
    filled = _fill(result["mapping"], gold)
    out = blind_shuffle.unblind(filled, mapping, gold)
    by_arm = {j["arm"] for j in out["judgments"]}
    assert by_arm == set(blind_shuffle.EXPECTED_ARMS)
    assert all(j["run_id"].startswith("run-") for j in out["judgments"])
    assert len(out["judgments"]) == 6
    assert out["reviewed_by"] == "硝酸铜"


def test_unblind_reports_missing_judgment_count(tmp_path, gold):
    runs = _three_runs(tmp_path)
    result = blind_shuffle.blind(runs, gold, tmp_path / "out", seed=3)
    filled = _fill(result["mapping"], gold)
    filled["judgments"] = filled["judgments"][:-1]
    with pytest.raises(ValueError, match="1 judgments still missing"):
        blind_shuffle.unblind(filled, json.loads(Path(result["mapping"]).read_text("utf-8")), gold)


def test_unblind_rejects_bad_verdict_and_duplicate(tmp_path, gold):
    runs = _three_runs(tmp_path)
    result = blind_shuffle.blind(runs, gold, tmp_path / "out", seed=3)
    mapping = json.loads(Path(result["mapping"]).read_text("utf-8"))
    filled = _fill(result["mapping"], gold)
    filled["judgments"][0]["verdict"] = "great"
    with pytest.raises(ValueError, match="Invalid verdict"):
        blind_shuffle.unblind(filled, mapping, gold)
    filled = _fill(result["mapping"], gold)
    filled["judgments"].append(dict(filled["judgments"][0]))
    with pytest.raises(ValueError, match="Duplicate judgment"):
        blind_shuffle.unblind(filled, mapping, gold)
