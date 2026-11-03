"""Pairwise A/B comparison of two saved benchmark runs, keyed by case/competitor/repeat."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from benchmark.report import aggregate_all_tasks, task_counts

COMPARABLE_CONFIG_FIELDS = (
    "workflow_id",
    "max_iterations",
    "repeat",
    "timeout_seconds",
    "task_concurrency",
    "replay_root",
)


def planned_tasks(manifest: dict[str, Any]) -> int:
    repeat = manifest["config"].get("repeat", 1)
    return sum(len(case["competitors"]) for case in manifest["cases"]) * repeat


def run_task_counts(metrics: dict[str, Any], manifest: dict[str, Any]) -> dict[str, int]:
    counts = metrics.get("task_counts") or task_counts(metrics["tasks"])
    return {**counts, "planned": planned_tasks(manifest)}


def load_run(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    metrics_path = directory / "metrics.json"
    if not metrics_path.exists():
        raise ValueError(f"{directory} 缺少 metrics.json，不能用于对比")
    metrics = json.loads(metrics_path.read_text("utf-8"))
    return manifest, metrics


def require_source_snapshots(directory: Path) -> None:
    snapshots = directory / "source_snapshots"
    if not snapshots.is_dir() or not list(snapshots.glob("*/index.json")):
        raise ValueError(
            f"{directory} 缺少 source_snapshots/<task>/index.json；"
            "没有运行当时的网页原文，无法人工复核，不能用于正式质量对比"
        )


def assert_comparable(manifest_a: dict[str, Any], manifest_b: dict[str, Any]) -> None:
    if manifest_a["cases"] != manifest_b["cases"]:
        raise ValueError("两个 run 的 cases 不一致，不能配对比较")
    if manifest_a["models"] != manifest_b["models"]:
        raise ValueError("两个 run 的模型配置不一致，不能配对比较")
    if manifest_a["git"]["commit"] != manifest_b["git"]["commit"]:
        raise ValueError("两个 run 的 Git commit 不一致，不能配对比较")
    for field in COMPARABLE_CONFIG_FIELDS:
        if manifest_a["config"].get(field) != manifest_b["config"].get(field):
            raise ValueError(f"两个 run 的配置 {field} 不一致，不能配对比较")


def task_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (row["case_id"], row["competitor"], row["repeat"])


def mean_or_none(values: list[Any]) -> float | None:
    values = [value for value in values if value is not None]
    return mean(values) if values else None


def compare(
    manifest_a: dict[str, Any],
    metrics_a: dict[str, Any],
    manifest_b: dict[str, Any],
    metrics_b: dict[str, Any],
) -> dict[str, Any]:
    rows_a = {task_key(row): row for row in metrics_a["tasks"]}
    rows_b = {task_key(row): row for row in metrics_b["tasks"]}
    paired = sorted(set(rows_a) & set(rows_b))
    names = sorted({name for key in paired for name in rows_a[key]["metrics"]})
    metric_comparison = {}
    for name in names:
        deltas = []
        available = 0
        for key in paired:
            value_a = rows_a[key]["metrics"].get(name, {}).get("value")
            value_b = rows_b[key]["metrics"].get(name, {}).get("value")
            if value_a is None or value_b is None:
                continue
            available += 1
            deltas.append(value_b - value_a)
        metric_comparison[name] = {
            "a_mean": mean_or_none([rows_a[key]["metrics"][name]["value"] for key in paired]),
            "b_mean": mean_or_none([rows_b[key]["metrics"][name]["value"] for key in paired]),
            "mean_delta_b_minus_a": mean(deltas) if deltas else None,
            "paired_available": available,
            "paired_missing": len(paired) - available,
        }
    return {
        "paired_tasks": len(paired),
        "a_only_tasks": sorted("-".join(map(str, key)) for key in set(rows_a) - set(rows_b)),
        "b_only_tasks": sorted("-".join(map(str, key)) for key in set(rows_b) - set(rows_a)),
        "task_counts": {
            "a": run_task_counts(metrics_a, manifest_a),
            "b": run_task_counts(metrics_b, manifest_b),
        },
        "all_tasks_summary": {
            "a": aggregate_all_tasks(metrics_a["tasks"], planned_tasks(manifest_a)),
            "b": aggregate_all_tasks(metrics_b["tasks"], planned_tasks(manifest_b)),
        },
        "metrics": metric_comparison,
    }


def render(manifest_a: dict[str, Any], manifest_b: dict[str, Any], result: dict[str, Any]) -> str:
    def show(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        return f"{value:.4f}" if isinstance(value, float) else str(value)

    lines = [
        "# Benchmark A/B 对比",
        "",
        f"Run A: `{manifest_a['run_id']}` · enable_qa={manifest_a['config']['enable_qa']}",
        f"Run B: `{manifest_b['run_id']}` · enable_qa={manifest_b['config']['enable_qa']}",
        "",
        f"配对任务数: {result['paired_tasks']}",
        f"仅 A 有: {', '.join(result['a_only_tasks']) or '无'}",
        f"仅 B 有: {', '.join(result['b_only_tasks']) or '无'}",
        "",
        "## 指标对比（配对任务）",
        "",
        "| 指标 | A 均值 | B 均值 | B-A 配对差值 | 可用配对 | 缺失 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stat in result["metrics"].items():
        lines.append(
            f"| {name} | {show(stat['a_mean'])} | {show(stat['b_mean'])} "
            f"| {show(stat['mean_delta_b_minus_a'])} | {stat['paired_available']} "
            f"| {stat['paired_missing']} |"
        )
    lines += [
        "",
        "## 任务口径",
        "",
        "| 组 | 计划 | 完成 | 失败 | 超时 |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, counts in (("A", result["task_counts"]["a"]), ("B", result["task_counts"]["b"])):
        lines.append(
            f"| {label} | {counts.get('planned', 0)} | {counts.get('completed', 0)} "
            f"| {counts.get('error', 0)} | {counts.get('timeout', 0)} |"
        )
    lines += [
        "",
        "## 全任务质量口径（失败/缺失记 0）",
        "",
        "| 指标 | A 全任务 | B 全任务 |",
        "|---|---:|---:|",
    ]
    names = sorted(set(result["all_tasks_summary"]["a"]) | set(result["all_tasks_summary"]["b"]))
    for name in names:
        lines.append(
            f"| {name} | {show(result['all_tasks_summary']['a'].get(name, {}).get('mean'))} "
            f"| {show(result['all_tasks_summary']['b'].get(name, {}).get('mean'))} |"
        )
    lines += [
        "",
        "配对差值只统计同一 case/competitor/repeat 且两侧均有值的任务；",
        "缺失配对不会进入差值均值，但会在上方列出。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a", type=Path)
    parser.add_argument("run_b", type=Path)
    parser.add_argument("--out", type=Path, help="Write compare.json/compare.md to this directory")
    parser.add_argument(
        "--allow-missing-sources",
        action="store_true",
        help="Exploratory only: compare runs without saved source snapshots",
    )
    args = parser.parse_args()
    for directory in (args.run_a, args.run_b):
        if not args.allow_missing_sources:
            require_source_snapshots(directory.resolve())
    manifest_a, metrics_a = load_run(args.run_a.resolve())
    manifest_b, metrics_b = load_run(args.run_b.resolve())
    assert_comparable(manifest_a, manifest_b)
    result = compare(manifest_a, metrics_a, manifest_b, metrics_b)
    markdown = render(manifest_a, manifest_b, result)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "compare.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        (args.out / "compare.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
