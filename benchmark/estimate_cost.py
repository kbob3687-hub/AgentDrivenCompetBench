"""Offline token/latency forecast for the frozen formal benchmark matrix (no LLM calls).

Calibration basis (measured, not assumed):
- single-LLM baseline arm: run 20261102T133459Z-2ca7bede, one call, input_tokens=13809
  against clickup-core-001-c1 -> chars-per-token for this endpoint and prompt shape.
- multi-agent arm with QA: run 20261102T131235Z-aab72c4d, same bundle, 267273 tokens / 377s.
- multi-agent arm without QA: no replay measurement exists; 0.88x comes from the live
  QA on/off pair (20261029T100328Z vs 20261101T121038Z) and is the weakest estimate here.
"""

import argparse
import copy
import json
from pathlib import Path

from benchmark.baselines.single_llm import PROMPT_TEMPLATE, build_pages_text
from benchmark.models import BenchmarkCase, RunConfig
from benchmark.replay import SnapshotBundle
from benchmark.runner import load_replay_bundles
from schemas.competitor import CompetitorProfile

ROOT = Path(__file__).resolve().parent.parent
CALIB_BUNDLE = "clickup-core-001-c1"
CALIB_INPUT_TOKENS = 13809
BASE_OUT_TOKENS = 19368
BASE_LATENCY = 89.86
MULTI_TOTAL_TOKENS = 267273
MULTI_LATENCY = 376.97
NO_QA_RATIO = 0.88
DIMENSIONS = ["features", "pricing", "persona", "swot"]


def prompt_for(bundle: SnapshotBundle, competitor: str) -> str:
    pages, _ = build_pages_text(bundle)
    return PROMPT_TEMPLATE.format(
        competitor=competitor,
        dimensions="、".join(DIMENSIONS),
        schema=json.dumps(CompetitorProfile.model_json_schema(), ensure_ascii=False),
        pages=pages,
    )


def measure(bundle_root: Path) -> tuple[float, int]:
    """Return (chars per token, reference prompt chars) from the calibration bundle."""
    reference = prompt_for(SnapshotBundle.load(bundle_root / CALIB_BUNDLE), "ClickUp")
    return len(reference) / CALIB_INPUT_TOKENS, len(reference)


def forecast(bundle_root: Path) -> list[dict]:
    cases = [
        BenchmarkCase(**raw)
        for raw in json.loads((ROOT / "benchmark/cases/final_cases.json").read_text("utf-8"))
    ]
    bundles = load_replay_bundles(copy.deepcopy(cases), RunConfig(replay_root=str(bundle_root)))
    ratio, reference_chars = measure(bundle_root)
    rows = []
    for case in cases:
        key = f"{case.id}-c1"
        bundle = bundles[key]
        prompt_chars = len(prompt_for(bundle, case.competitors[0]))
        volume = prompt_chars / reference_chars
        rows.append(
            {
                "case_id": case.id,
                "pages": len(bundle.urls),
                "prompt_chars": prompt_chars,
                "baseline_tokens": round(prompt_chars / ratio + BASE_OUT_TOKENS),
                # One call, output-dominated: measured latency is reused as a flat estimate.
                "baseline_seconds": round(BASE_LATENCY),
                "multi_agent_tokens": round(MULTI_TOTAL_TOKENS * volume),
                "multi_agent_seconds": round(MULTI_LATENCY * volume),
            }
        )
    return rows


def totals(rows: list[dict], repeat: int) -> dict:
    per = {
        "single_llm": sum(r["baseline_tokens"] for r in rows),
        "multi_agent_qa_fixed": sum(r["multi_agent_tokens"] for r in rows),
        "multi_agent_no_qa": round(sum(r["multi_agent_tokens"] for r in rows) * NO_QA_RATIO),
    }
    seconds = {
        "single_llm": sum(r["baseline_seconds"] for r in rows),
        "multi_agent_qa_fixed": sum(r["multi_agent_seconds"] for r in rows),
        "multi_agent_no_qa": round(sum(r["multi_agent_seconds"] for r in rows) * NO_QA_RATIO),
    }
    return {
        "repeat": repeat,
        "tasks": len(rows) * repeat * 3,
        "tokens_by_arm": per,
        "tokens_total": sum(per.values()) * repeat,
        "minutes_serial": round(sum(seconds.values()) * repeat / 60),
    }


def all_arms(row: dict) -> tuple[int, int]:
    """(tokens, seconds) for one case across the three core arms."""
    tokens = row["baseline_tokens"] + round(row["multi_agent_tokens"] * (1 + NO_QA_RATIO))
    seconds = row["baseline_seconds"] + round(row["multi_agent_seconds"] * (1 + NO_QA_RATIO))
    return tokens, seconds


def scenarios(rows: list[dict]) -> list[dict]:
    def qa_only(selected: list[dict], runs_per_case: int) -> tuple[int, int]:
        tokens = sum(r["multi_agent_tokens"] for r in selected) * runs_per_case
        seconds = sum(r["multi_agent_seconds"] for r in selected) * runs_per_case
        return tokens, seconds

    def block(name: str, tasks: int, tokens: int, seconds: int, cases: str, note: str = "") -> dict:
        return {
            "name": name,
            "tasks": tasks,
            "tokens": tokens,
            "minutes_serial": round(seconds / 60),
            "cases": cases,
            "note": note,
        }

    stress = [r for r in rows if "-stress-" in r["case_id"]]
    normal = [r for r in rows if "-normal-" in r["case_id"]]
    by_size = sorted(rows, key=lambda r: r["prompt_chars"])
    gate = [by_size[-1], by_size[len(by_size) // 2], by_size[0]]
    gate_cases = "体量最大/中间/最小：" + "、".join(r["case_id"] for r in gate)

    main = totals(rows, 2)
    main_seconds = sum(all_arms(r)[1] for r in rows) * 2
    rework = qa_only(stress, 4)
    smoke = qa_only(normal, 1)
    return [
        block(
            "成本闸门（3 case × 3 臂 × 1）",
            9,
            sum(all_arms(r)[0] for r in gate),
            sum(all_arms(r)[1] for r in gate),
            gate_cases,
        ),
        block(
            "主实验（12 case × 2 repeat × 3 臂）",
            main["tasks"],
            main["tokens_total"],
            main_seconds,
            "全部 12 个 case",
        ),
        block(
            "返工修复对照（6 压力 case × 2 repeat × 2 代码版本）",
            24,
            rework[0],
            rework[1],
            "6 个压力 case",
            "只跑多 Agent 带 QA 臂，对照旧/新返工实现",
        ),
        block(
            "实时网页冒烟（6 常规 case × 1，需联网）",
            6,
            smoke[0],
            smoke[1],
            "6 个常规 case",
            "实时页面体量与冻结包不同且可能采集失败，此列仅按冻结包量级估算",
        ),
    ]


def markdown(rows: list[dict]) -> str:
    lines = [
        "# 主实验成本预测（离线推算，未调用模型）",
        "",
        "口径：每页 12000 字符截断后拼成基线提示词；字符/token 由 11-02 实测 input_tokens 反推。",
        "多 Agent 两臂按提示词体量相对校准包线性缩放；",
        "无 QA 臂缺回放实测点，按历史 QA 开关比 0.88 折算。",
        "金额无法给出：历史 manifest 只存 token 数、未存当时单价快照，且当前用的是中转端点。",
        "",
        "列名：基线 = 单次 LLM 臂；无QA / 带QA = 多 Agent 臂（QA 关 / 开）。",
        "",
        "| case | 页数 | 提示词字符 | 基线 token | 无QA token | 带QA token | 带QA 秒 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case_id']} | {r['pages']} | {r['prompt_chars']:,} | {r['baseline_tokens']:,} "
            f"| {round(r['multi_agent_tokens'] * NO_QA_RATIO):,} | {r['multi_agent_tokens']:,} "
            f"| {r['multi_agent_seconds']} |"
        )
    lines += [
        "",
        "## 四个实验块的总量（文档 §5.3 / §5.4）",
        "",
        "| 实验块 | 任务次数 | token 估算 | 串行时长估算 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for s in scenarios(rows):
        detail = s["cases"] if not s["note"] else f"{s['cases']}。{s['note']}"
        lines.append(
            f"| {s['name']} | {s['tasks']} | {s['tokens']:,} | {s['minutes_serial']} 分钟 "
            f"| {detail} |"
        )
    one = totals(rows, 1)
    lines.append(
        f"\n若主实验只做 repeat=1：{one['tasks']} 次任务 ≈ {one['tokens_total']:,} token，"
        f"串行约 {one['minutes_serial']} 分钟。"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, default=ROOT / "benchmark/replay_bundles")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = forecast(args.replay_root.resolve())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown(rows), encoding="utf-8")
    print(
        json.dumps(
            {"rows": rows, "scenarios": scenarios(rows)},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
