"""离线重算 A(QA开)/B(QA关) 两次有效运行的执行记录，产出简历素材数字。

不联网、不调用任何 LLM，只读 benchmark/results 下已落盘的数据：

    python -m benchmark.mine_ab_facts \
        --run-a benchmark/results/20261029T100328Z-327af616 \
        --run-b benchmark/results/20261101T121038Z-ca0c76a4 \
        --out benchmark/results/ab_facts.md

输出 ab_facts.md（人读）与 ab_facts.json（机读）。
每个数字都带口径标注；算不出来的写进"不可宣称"清单，禁止进简历。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

RUN_A_DEFAULT = "benchmark/results/20261029T100328Z-327af616"
RUN_B_DEFAULT = "benchmark/results/20261101T121038Z-ca0c76a4"


def _load_run(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    tasks = {}
    for path in sorted((run_dir / "raw").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        tasks[record["task_id"]] = record
    return {"dir": run_dir, "manifest": manifest, "metrics": metrics, "tasks": tasks}


def _paired_metrics(run: dict[str, Any], key: str) -> dict[str, list[float]]:
    """按 case_id|repeat 取配对任务指标（c1/c2 先合并到 repeat 级取均值）。"""
    per_repeat: dict[str, list[float]] = {}
    for task in run["metrics"].get("tasks", []):
        value = (task.get("metrics") or {}).get(key, {}).get("value")
        if value is None:
            continue
        per_repeat.setdefault(f"{task['case_id']}|{task['repeat']}", []).append(float(value))
    return {k: statistics.mean(v) for k, v in per_repeat.items()}


def _latency_stats(tasks: dict[str, dict]) -> dict[str, float]:
    values = [t["latency_seconds"] for t in tasks.values() if t.get("latency_seconds")]
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 1),
        "median": round(statistics.median(values), 1),
        "p90": round(sorted(values)[max(0, int(len(values) * 0.9) - 1)], 1),
        "max": round(max(values), 1),
    }


def _final_status_breakdown(tasks: dict[str, dict]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for task in tasks.values():
        counter[str(task["state"].get("final_status") or "unknown")] += 1
    return dict(counter)


def _issue_stats(tasks: dict[str, dict]) -> dict[str, Any]:
    severities: Counter[str] = Counter()
    types: Counter[str] = Counter()
    field_paths: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    revised_tasks = 0
    first_scores: list[float] = []
    bonuses: list[float] = []
    for task in tasks.values():
        history = task["state"].get("feedback_history") or []
        if not history:
            continue
        verdicts[history[0]["verdict"]] += 1
        if any(record["verdict"] in ("revise", "reject") for record in history):
            revised_tasks += 1
        first_scores.append(history[0].get("raw_score", history[0].get("score", 0.0)))
        for record in history:
            bonuses.append(record.get("improvement_bonus", 0.0) or 0.0)
            for issue in record.get("issues", []):
                severities[issue.get("severity", "?")] += 1
                types[issue.get("issue_type", "?")] += 1
                field_paths[issue.get("field_path", "?")] += 1
    return {
        "tasks_with_qa_feedback": sum(verdicts.values()),
        "tasks_revised_or_rejected": revised_tasks,
        "first_qa_verdicts": dict(verdicts),
        "first_qa_score_mean": round(statistics.mean(first_scores), 3) if first_scores else None,
        "first_qa_score_min": min(first_scores) if first_scores else None,
        "first_qa_score_max": max(first_scores) if first_scores else None,
        "improvement_bonus_nonzero_count": sum(1 for b in bonuses if b > 0),
        "issues_by_severity": dict(severities),
        "issues_by_type": dict(types),
        "top_field_paths": field_paths.most_common(8),
    }


def _rework_block_reasons(tasks: dict[str, dict]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for task in tasks.values():
        history = task["state"].get("feedback_history") or []
        if not any(r["verdict"] in ("revise", "reject") for r in history):
            continue
        reason = task["state"].get("rework_blocked_reason")
        counter[str(reason or "not_blocked")] += 1
    return dict(counter)


def _field_diff_totals(tasks: dict[str, dict]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    tasks_with_diff = 0
    for task in tasks.values():
        for record in task["state"].get("feedback_history") or []:
            if not record.get("resolved_fields") and not record.get("persisted_fields"):
                continue
            tasks_with_diff += 1
            totals["resolved"] += len(record.get("resolved_fields") or [])
            totals["regressed"] += len(record.get("regressed_fields") or [])
            totals["persisted"] += len(record.get("persisted_fields") or [])
    totals["tasks_with_diff_records"] = tasks_with_diff
    return dict(totals)


def _retry_distribution(run: dict[str, Any]) -> dict[str, int]:
    counter: Counter[int] = Counter()
    for task in run["metrics"].get("tasks", []):
        metric = (task.get("metrics") or {}).get("retry_count", {}).get("value")
        if metric is not None:
            counter[int(metric)] += 1
    return {str(k): v for k, v in sorted(counter.items())}


def _token_totals(tasks: dict[str, dict]) -> dict[str, Any]:
    inp = out = calls = tasks_with = 0
    for task in tasks.values():
        task_calls = [e for e in task.get("execution_metadata", []) if e.get("kind") == "llm"]
        if not task_calls:
            continue
        tasks_with += 1
        for event in task_calls:
            inp += event.get("input_tokens") or 0
            out += event.get("output_tokens") or 0
        calls += len(task_calls)
    return {
        "tasks_with_llm_events": tasks_with,
        "llm_calls": calls,
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "mean_tokens_per_task": round((inp + out) / tasks_with) if tasks_with else None,
    }


def mine(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    tasks_a, tasks_b = run_a["tasks"], run_b["tasks"]
    paired = {}
    for key in ("schema_valid", "citation_coverage", "dimension_coverage", "workflow_success"):
        pa, pb = _paired_metrics(run_a, key), _paired_metrics(run_b, key)
        common = sorted(set(pa) & set(pb))
        paired[key] = {
            "paired_repeats": len(common),
            "a_mean": round(statistics.mean(pa[k] for k in common), 4) if common else None,
            "b_mean": round(statistics.mean(pb[k] for k in common), 4) if common else None,
            "delta_b_minus_a": (
                round(
                    statistics.mean(pb[k] for k in common) - statistics.mean(pa[k] for k in common),
                    4,
                )
                if common
                else None
            ),
        }
    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": {
            "run_a": {
                "dir": str(run_a["dir"]),
                "label": "QA 开（返工修复前的旧行为：revise 全部被源限制拦停）",
                "git": run_a["manifest"].get("git", {}),
                "config": run_a["manifest"].get("config", {}),
                "note": "运行代码为返工修复(commit 8b699b6)之前版本，其返工行为不代表修复后效果",
            },
            "run_b": {
                "dir": str(run_b["dir"]),
                "label": "QA 关（基线）",
                "git": run_b["manifest"].get("git", {}),
                "config": run_b["manifest"].get("config", {}),
            },
            "same_commit": run_a["manifest"].get("git", {}).get("commit")
            == run_b["manifest"].get("git", {}).get("commit"),
            "both_dirty": bool(
                run_a["manifest"].get("git", {}).get("dirty")
                or run_b["manifest"].get("git", {}).get("dirty")
            ),
        },
        "task_counts": {"run_a": len(tasks_a), "run_b": len(tasks_b)},
        "final_status": {
            "a_qa_on": _final_status_breakdown(tasks_a),
            "b_qa_off": _final_status_breakdown(tasks_b),
        },
        "rework_dynamics_a": {
            "issues": _issue_stats(tasks_a),
            "block_reasons": _rework_block_reasons(tasks_a),
            "field_diff": _field_diff_totals(tasks_a),
            "retry_distribution": _retry_distribution(run_a),
        },
        "latency": {"a_qa_on": _latency_stats(tasks_a), "b_qa_off": _latency_stats(tasks_b)},
        "token_usage": {
            "a_qa_on": _token_totals(tasks_a),
            "b_qa_off": _token_totals(tasks_b),
        },
        "paired_structural_metrics": paired,
        "not_computable": [
            "内容准确率（supported/unsupported 比例）："
            "这两次运行没有对内容做过黄金标签核验，只有结构性指标",
            "修复后返工链路的实际效果：这两次运行早于返工修复 commit 8b699b6，"
            "revise 均被源限制拦停，不能当'返工有效'的证据",
            "每轮新增证据量（按 iteration 切分的 claims）：旧运行落盘的 claims 没有轮次标记",
            "token 成本换算成金额：记录里只有 token 数，"
            "没有当次运行的单价快照，只能报 token 量与比值",
            "统计显著性：n=20 配对、且两次运行仓库均为 dirty 状态，只能报描述性差异",
        ],
    }


def render_markdown(facts: dict[str, Any]) -> str:
    lines = ["# A/B 有效实验离线重算事实", ""]
    prov = facts["provenance"]
    for side, name in (("run_a", "A（QA 开）"), ("run_b", "B（QA 关）")):
        info = prov[side]
        git = info["git"]
        lines.append(
            f"- {name}: `{Path(info['dir']).name}` @ {git.get('commit', '?')[:8]}"
            f"（dirty={git.get('dirty')}）"
        )
    lines.append(f"- 同 commit 对比: {prov['same_commit']}")
    lines.append(f"- 任务数: A={facts['task_counts']['run_a']}, B={facts['task_counts']['run_b']}")
    lines.append("")
    lines.append("## 终态分布")
    for side, label in (("a_qa_on", "A(QA开)"), ("b_qa_off", "B(QA关)")):
        items = ", ".join(f"{k}: {v}" for k, v in sorted(facts["final_status"][side].items()))
        lines.append(f"- {label}: {items}")
    lines.append("")
    dyn = facts["rework_dynamics_a"]
    iss = dyn["issues"]
    lines.append("## A 组返工过程（修复前行为）")
    lines.append(
        f"- 收到 QA 反馈的任务 {iss['tasks_with_qa_feedback']}/{facts['task_counts']['run_a']}，"
        f"其中判 revise/reject 的 {iss['tasks_revised_or_rejected']} 个"
    )
    lines.append(
        f"- 首轮 QA 均分 {iss['first_qa_score_mean']}"
        f"（区间 {iss['first_qa_score_min']}~{iss['first_qa_score_max']}），"
        f"首轮判定分布 {iss['first_qa_verdicts']}，"
        f"改善奖励非零 {iss['improvement_bonus_nonzero_count']} 次"
    )
    lines.append(f"- 问题按严重度: {iss['issues_by_severity']}；按类型: {iss['issues_by_type']}")
    lines.append(f"- 问题最多的字段路径: {iss['top_field_paths']}")
    lines.append(f"- 返工被拦原因: {dyn['block_reasons']}")
    lines.append(f"- 字段级修复记账（第2轮起才有 diff 记录）: {dyn['field_diff']}")
    lines.append(f"- 实际返工重试次数分布: {dyn['retry_distribution']}")
    lines.append("")
    lines.append("## 延迟（秒）")
    for side, label in (("a_qa_on", "A(QA开)"), ("b_qa_off", "B(QA关)")):
        s = facts["latency"][side]
        lines.append(
            f"- {label}: n={s['n']} 均值={s['mean']} 中位={s['median']} "
            f"p90={s['p90']} 最大={s['max']}"
        )
    lines.append("")
    lines.append("## 配对结构指标（同 case×repeat，失败计 0 口径已在评测器内处理）")
    for key, v in facts["paired_structural_metrics"].items():
        lines.append(
            f"- {key}: 配对样本 {v['paired_repeats']}, "
            f"A={v['a_mean']}, B={v['b_mean']}, B−A={v['delta_b_minus_a']}"
        )
    lines.append("")
    lines.append("## 成本（执行记录中上报的 LLM 调用与 token 总量）")
    tok = facts["token_usage"]
    for side, label in (("a_qa_on", "A(QA开)"), ("b_qa_off", "B(QA关)")):
        s = tok[side]
        lines.append(
            f"- {label}: 任务 {s['tasks_with_llm_events']} 个、LLM 调用 {s['llm_calls']} 次、"
            f"token 合计 {s['total_tokens']}"
            f"（输入 {s['input_tokens']} / 输出 {s['output_tokens']}），"
            f"均值 ≈{s['mean_tokens_per_task']}/任务"
        )
    a_tok, b_tok = tok["a_qa_on"], tok["b_qa_off"]
    if a_tok["total_tokens"] and b_tok["total_tokens"]:
        ratio = round(a_tok["total_tokens"] / b_tok["total_tokens"], 2)
        calls_ratio = round(a_tok["llm_calls"] / b_tok["llm_calls"], 2)
        lines.append(f"- A/B 比值: token {ratio}x、LLM 调用 {calls_ratio}x（QA 轮与返工轮的增量）")
    la, lb = facts["latency"]["a_qa_on"], facts["latency"]["b_qa_off"]
    lat_ratio = round(la["mean"] / lb["mean"], 2) if lb["mean"] else None
    lines.append(f"- 延迟比值: A 均值 {la['mean']}s vs B {lb['mean']}s ≈ {lat_ratio}x")
    lines.append("")
    lines.append("## 不可宣称清单（禁止写进简历）")
    for item in facts["not_computable"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-a", default=RUN_A_DEFAULT)
    parser.add_argument("--run-b", default=RUN_B_DEFAULT)
    parser.add_argument("--out", default="benchmark/results/ab_facts.md")
    args = parser.parse_args()

    run_a = _load_run(Path(args.run_a))
    run_b = _load_run(Path(args.run_b))
    facts = mine(run_a, run_b)

    out_md = Path(args.out)
    out_md.write_text(render_markdown(facts), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_md} and {out_json}")


if __name__ == "__main__":
    main()
