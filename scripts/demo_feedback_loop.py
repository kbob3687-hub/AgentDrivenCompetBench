"""答辩演示脚本：反馈闭环 (Feedback Loop Demo)

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/demo_feedback_loop.py

演示目标：
1. 第一轮：只采集Notion的pricing维度
2. QA检测到维度缺失，触发revise，LangGraph条件边路由回Collector
3. 第二轮：Collector自动补采缺失维度，重走Analyst→Writer→QA
4. QA第二轮通过，闭环完成

关键：全程走LangGraph StateGraph，revise回collector是conditional_edges的路由，
不是手动if/else。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from orchestrator.graph import build_graph, _make_trace_id
from orchestrator.state import GraphState

# ============================================================
# 全量维度（QA期望）与第一轮故意只采pricing
# ============================================================
ALL_DIMENSIONS = ["pricing", "features", "integrations", "ai_features"]
FIRST_ROUND_SCOPE = ["pricing"]  # 故意只采一个维度
MAX_ITERATIONS = 3


def banner(text: str, char: str = "=") -> None:
    print(f"\n{char * 70}")
    print(f"  {text}")
    print(f"{char * 70}")


async def main():
    banner("FEEDBACK LOOP DEMO: Notion (LangGraph Conditional Edge)", "=")

    required = ["DEEPSEEK_API_KEY"]
    missing_env = [k for k in required if not os.getenv(k)]
    if missing_env:
        print(f"[FAIL] Missing env vars: {missing_env}")
        return

    competitor = "Notion"
    print(f"  Competitor: {competitor}")
    print(f"  Round 1 scope: {FIRST_ROUND_SCOPE}  (deliberately incomplete)")
    print(f"  QA expects:    {ALL_DIMENSIONS}")
    print(f"  Graph: build_graph() — conditional_edges qa_routing")

    # 编译LangGraph
    app = build_graph(checkpointer=None)

    # 初始state：scope只采pricing，但expected_dimensions传全量
    initial_state: GraphState = {
        "competitor_name": competitor,
        "collect_scope": FIRST_ROUND_SCOPE,
        "target_urls": [],
        "expected_dimensions": ALL_DIMENSIONS,  # QA用全量维度检查
        "claims": [],
        "sources_fetched": 0,
        "sources_failed": 0,
        "collect_errors": [],
        "profile": {},
        "completeness_score": 0.0,
        "dimensions_analyzed": [],
        "report_markdown": "",
        "report_length": 0,
        "footnote_count": 0,
        "qa_verdict": "",
        "qa_score": 0.0,
        "qa_issues": [],
        "qa_feedback_summary": "",
        "missing_dimensions": [],
        "iteration": 1,
        "max_iterations": MAX_ITERATIONS,
        "feedback_history": [],
        "trace_id": _make_trace_id(),
        "started_at": datetime.now().isoformat(),
        "completed_at": "",
        "final_status": "running",
        "error": "",
    }

    config: dict = {"recursion_limit": MAX_ITERATIONS * 5}
    node_path: list[str] = []
    final_state: dict = {}

    banner("Running LangGraph astream...", "-")

    # astream逐节点追踪
    async for event in app.astream(initial_state, config=config):
        for node_name, state_update in event.items():
            if node_name == "__end__":
                continue
            node_path.append(node_name)

            # 打印节点信息
            if node_name == "collector":
                claims = state_update.get("claims", [])
                fetched = state_update.get("sources_fetched", 0)
                scope_now = state_update.get("collect_scope", [])
                print(f"\n  [{len(node_path)}] COLLECTOR")
                print(f"      scope: {scope_now}")
                print(f"      claims: +{len(claims)}, fetched: {fetched}")
            elif node_name == "analyst":
                comp = state_update.get("completeness_score", 0)
                print(f"\n  [{len(node_path)}] ANALYST")
                print(f"      completeness: {comp:.0%}")
            elif node_name == "writer":
                rlen = state_update.get("report_length", 0)
                print(f"\n  [{len(node_path)}] WRITER")
                print(f"      report: {rlen} chars")
            elif node_name == "qa":
                verdict = state_update.get("qa_verdict", "?")
                score = state_update.get("qa_score", 0)
                missing = state_update.get("missing_dimensions", [])
                history = state_update.get("feedback_history", [])
                print(f"\n  [{len(node_path)}] QA")
                print(f"      verdict: {verdict.upper()}")
                print(f"      score: {score:.2f}")
                print(f"      missing_dimensions: {missing}")
                # qa_routing逻辑: missing非空或verdict=revise → collector; pass → end
                if verdict == "pass":
                    print(f"      >> CONDITIONAL EDGE: qa_routing() -> 'end' (pass)")
                elif verdict == "revise":
                    print(f"      >> CONDITIONAL EDGE: qa_routing() -> 'collector' (revise, score<0.70 or missing dims)")
                else:
                    print(f"      >> CONDITIONAL EDGE: qa_routing() -> 'end' (reject)")

            # 累积state
            if not final_state:
                final_state = dict(initial_state)
            final_state.update(state_update)

    # ============================================================
    # 结果展示
    # ============================================================
    banner("RESULT", "=")

    path_str = " → ".join(node_path)
    print(f"\n  Node path: {path_str}")
    print(f"  Expected:  collector → analyst → writer → qa → collector → analyst → writer → qa")

    verdict = final_state.get("qa_verdict", "unknown")
    score = final_state.get("qa_score", 0)
    feedback_history = final_state.get("feedback_history", [])
    claims = final_state.get("claims", [])
    completeness = final_state.get("completeness_score", 0)

    print(f"\n  Final verdict: {verdict.upper()}")
    print(f"  Final score:   {score:.2f}")
    print(f"  Total claims:  {len(claims)}")
    print(f"  Completeness:  {completeness:.0%}")
    print(f"  Iterations:    {len(feedback_history)}")

    # 打印feedback历史
    if feedback_history:
        print(f"\n  Feedback history:")
        for i, fb in enumerate(feedback_history, 1):
            print(f"    Round {i}: verdict={fb.get('verdict')}, score={fb.get('score'):.2f}, action={fb.get('action_taken')}")

    # 验证路径包含revise回路
    has_loop = node_path.count("collector") >= 2 and node_path.count("qa") >= 2
    if has_loop:
        print(f"\n  [OK] Feedback loop confirmed: collector appears {node_path.count('collector')}x, qa appears {node_path.count('qa')}x")
    else:
        print(f"\n  [WARN] No feedback loop detected — may have passed on first round")

    # 保存报告
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "feedback_loop_demo.md"

    report_md = final_state.get("report_markdown", "")

    final_report = f"""# 反馈闭环演示报告 (Feedback Loop Demo)

**竞品**: {competitor}
**编排引擎**: LangGraph StateGraph (`orchestrator.graph.build_graph`)
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Graph执行路径

```
{path_str}
```

## 闭环说明

1. **Round 1** — `collect_scope=["pricing"]`，仅采集定价维度
2. Collector → Analyst → Writer → QA
3. QA检测到 `expected_dimensions` 中 features/integrations/ai_features 缺失
4. `qa_routing()` 返回 `"collector"` → **LangGraph条件边路由回Collector**
5. **Round 2** — Collector读取 `missing_dimensions`，自动扩展scope补采
6. Collector → Analyst → Writer → QA
7. QA判定 PASS → `qa_routing()` 返回 `"end"` → 流程结束

## QA结果

| 指标 | 值 |
|------|-----|
| QA分数 | {score:.2f} |
| QA判定 | {verdict} |
| 迭代轮次 | {len(feedback_history)} |
| 总Claims数 | {len(claims)} |
| 完整度 | {completeness:.0%} |

## Feedback历史

"""
    for i, fb in enumerate(feedback_history, 1):
        final_report += f"### Round {i}\n"
        final_report += f"- Verdict: {fb.get('verdict')}\n"
        final_report += f"- Score: {fb.get('score'):.2f}\n"
        final_report += f"- Action: {fb.get('action_taken')}\n"
        final_report += f"- Summary: {fb.get('feedback_summary')}\n\n"

    final_report += f"## 竞品报告\n\n{report_md}\n"

    report_path.write_text(final_report, encoding="utf-8")
    print(f"\n  Report saved: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
