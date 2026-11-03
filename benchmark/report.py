"""Transparent task-macro summaries and Markdown reports; no synthetic baselines."""

from statistics import mean
from typing import Any

from benchmark.models import BenchmarkCase, Metric, TaskRecord

REWORK_REASONS = {
    "no_new_urls_within_target_urls": "指定的 URL 均已采集，没有可补充的新来源",
    "discovery_found_no_new_urls": "重新发现后没有找到未采集过的 URL",
    "new_urls_added_no_claims_or_sources": "新 URL 未带来新的 Claim 或引用",
}

# Quality metrics whose absent value means the planned task produced no usable evidence.
ALL_TASK_QUALITY_METRICS = (
    "schema_valid",
    "citation_coverage",
    "citation_validity",
    "dimension_coverage",
    "workflow_success",
)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = list(rows[0]["metrics"]) if rows else []
    summary = {}
    for name in names:
        values = [
            r["metrics"][name]["value"] for r in rows if r["metrics"][name]["value"] is not None
        ]
        summary[name] = {
            "mean": mean(values) if values else None,
            "available": len(values),
            "missing": len(rows) - len(values),
            "tasks": len(rows),
        }
    return summary


def aggregate_all_tasks(
    rows: list[dict[str, Any]], planned: int, names: tuple[str, ...] = ALL_TASK_QUALITY_METRICS
) -> dict[str, Any]:
    """Mean over all planned tasks; unfinished or null-valued tasks count as zero."""
    summary = {}
    for name in names:
        values = [
            r["metrics"][name]["value"]
            for r in rows
            if name in r["metrics"] and r["metrics"][name]["value"] is not None
        ]
        summary[name] = {
            "mean": sum(values) / planned if planned else None,
            "available": len(values),
            "missing": planned - len(values),
            "tasks": planned,
        }
    return summary


def task_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"completed": 0, "error": 0, "timeout": 0}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    return counts


def build_metrics(
    records: list[TaskRecord],
    cases: list[BenchmarkCase],
    metrics: list[dict[str, Metric]],
    repeat: int | None = None,
) -> dict[str, Any]:
    rows = [
        {
            "task_id": record.task_id,
            "case_id": record.case_id,
            "competitor": record.competitor,
            "repeat": record.repeat,
            "outcome": record.outcome,
            "final_status": record.state.get("final_status"),
            "rework_blocked_reason": record.state.get("rework_blocked_reason"),
            "missing_dimensions": record.state.get("missing_dimensions") or [],
            "metrics": {key: value.model_dump(mode="json") for key, value in evaluated.items()},
        }
        for record, evaluated in zip(records, metrics, strict=True)
    ]
    grouped = {}
    for case in cases:
        selected = [row for row in rows if row["case_id"] == case.id]
        planned = len(case.competitors) * (
            repeat or max((row["repeat"] for row in selected), default=1)
        )
        grouped[case.id] = {
            "summary": aggregate(selected),
            "all_tasks_summary": aggregate_all_tasks(selected, planned),
            "task_counts": {**task_counts(selected), "planned": planned},
            "all_workflows_succeeded": bool(selected)
            and all(row["metrics"]["workflow_success"]["value"] for row in selected),
        }
    planned_total = sum(group["task_counts"]["planned"] for group in grouped.values())
    return {
        "metric_version": "1.1",
        "workflow_id": "standalone",
        "tasks": rows,
        "cases": grouped,
        "summary": aggregate(rows),
        "all_tasks_summary": aggregate_all_tasks(rows, planned_total),
        "task_counts": {**task_counts(rows), "planned": planned_total},
        "aggregation": (
            "task macro mean; null excluded with missing count; booleans as rates; "
            "all_tasks_summary counts unfinished or null quality tasks as zero"
        ),
    }


def render(manifest: dict[str, Any], metrics: dict[str, Any]) -> str:
    def show(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        return f"{value:.4f}" if isinstance(value, float) else str(value)

    lines = [
        "# Agent Benchmark V1.1",
        "",
        f"Run: `{manifest['run_id']}`",
        f"Evaluator metric_version: {metrics['metric_version']}",
        "",
        "workflow_id = standalone；只代表 orchestrator.graph.run_pipeline()，不代表 API/SSE。",
        f"enable_qa = {manifest['config']['enable_qa']}",
        "",
        f"Started: {manifest['started_at']} · Completed: {manifest.get('completed_at')}",
        f"Git: `{manifest['git']['commit']}` · dirty: {manifest['git']['dirty']}",
        "",
        "workflow_success 与 qa_passed 独立。正常 reject 且有产出可以执行成功。",
        "引用仅检查结构与格式，不联网验证真实性。LLM Judge 未启用。",
        "",
        "## 汇总",
        "",
        "| 指标 | 均值 / 布尔比例 | 有值 | null |",
        "|---|---:|---:|---:|",
    ]
    for key, stat in metrics["summary"].items():
        lines.append(f"| {key} | {show(stat['mean'])} | {stat['available']} | {stat['missing']} |")
    counts = metrics.get("task_counts", {})
    lines += [
        "",
        "## 任务口径",
        "",
        "| 计划任务 | 完成 | 失败 | 超时 |",
        "|---:|---:|---:|---:|",
        f"| {counts.get('planned', len(metrics['tasks']))} | {counts.get('completed', 0)} "
        f"| {counts.get('error', 0)} | {counts.get('timeout', 0)} |",
        "",
        "## 全任务质量口径（失败/缺失记 0）",
        "",
        "| 指标 | 条件均值 | 全任务均值 | 记零任务数 |",
        "|---|---:|---:|---:|",
    ]
    for key, stat in metrics.get("all_tasks_summary", {}).items():
        conditional = metrics["summary"].get(key, {}).get("mean")
        lines.append(f"| {key} | {show(conditional)} | {show(stat['mean'])} | {stat['missing']} |")
    lines += [
        "",
        "按任务等权平均；null 不进入条件均值，但保留缺失计数。失败任务保留在结果中，",
        "并在全任务口径中记 0，避免失败样本从质量比较中消失。",
        "",
        "## Case 聚合",
        "",
        "| Case | 所有子任务成功 | workflow_success rate | 全任务 workflow_success |",
        "|---|---|---:|---:|",
    ]
    for case_id, result in metrics["cases"].items():
        rate = result["summary"].get("workflow_success", {}).get("mean")
        all_tasks = result["all_tasks_summary"].get("workflow_success", {}).get("mean")
        lines.append(
            f"| {case_id} | {show(result['all_workflows_succeeded'])} | {show(rate)} "
            f"| {show(all_tasks)} |"
        )
    for row in metrics["tasks"]:
        lines += [
            "",
            f"## {row['task_id']} — {row['competitor']}",
            "",
            f"case: {row['case_id']} · repeat: {row['repeat']} · outcome: {row['outcome']}",
            f"final_status: {row.get('final_status') or 'unknown'}",
            f"原始记录：[raw/{row['task_id']}.json](raw/{row['task_id']}.json)",
        ]
        if row.get("rework_blocked_reason"):
            reason = row["rework_blocked_reason"]
            lines.append(f"返工停止原因: {REWORK_REASONS.get(reason, reason)} (`{reason}`)")
            if row.get("missing_dimensions"):
                lines.append(f"未补齐维度: {', '.join(row['missing_dimensions'])}")
        if row.get("final_status") == "source_limited":
            lines.append("QA 未通过；当前报告是待补证据的草稿。")
        lines += ["", "| 指标 | 值 | 分子 / 分母 | 原因 |", "|---|---:|---|---|"]
        for key, item in row["metrics"].items():
            fraction = (
                f"{item['numerator']} / {item['denominator']}"
                if item["denominator"] is not None
                else "—"
            )
            lines.append(f"| {key} | {show(item['value'])} | {fraction} | {item['reason'] or ''} |")
    return "\n".join(lines) + "\n"
