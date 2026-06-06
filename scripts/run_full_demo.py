"""三竞品完整Pipeline演示：Notion vs Feishu vs ClickUp

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/run_full_demo.py

功能：
1. 通过LangGraph StateGraph（build_graph）依次对三竞品运行完整pipeline
2. 每个竞品经过conditional routing，QA pass/revise/reject真实生效
3. 打印每个竞品经过的节点路径（astream追踪）
4. 三竞品都拿到CompetitorProfile后生成对比报告
5. 最终输出保存到 reports/full_demo.md
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from orchestrator.graph import _make_trace_id, build_graph
from orchestrator.state import GraphState

# ============================================================
# 常量
# ============================================================
COMPETITORS = [
    {
        "name": "Notion",
        "scope": ["pricing", "features", "integrations", "ai_features"],
    },
    {
        "name": "Feishu",
        "scope": ["pricing", "features", "integrations", "ai_features"],
    },
    {
        "name": "ClickUp",
        "scope": ["pricing", "features", "integrations", "ai_features"],
    },
]

MAX_QA_ITERATIONS = 3


def sep(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


# ============================================================
# 单竞品：通过LangGraph astream运行，追踪节点路径
# ============================================================
async def run_via_graph(
    app,
    competitor_name: str,
    scope: list[str],
) -> tuple[dict[str, any], list[str]]:
    """通过LangGraph StateGraph运行单竞品pipeline

    使用astream逐节点流式输出，追踪实际经过的节点路径。
    返回 (final_state, node_path)
    """
    initial_state: GraphState = {
        "competitor_name": competitor_name,
        "collect_scope": scope,
        "target_urls": [],
        "expected_dimensions": scope,
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
        "max_iterations": MAX_QA_ITERATIONS,
        "feedback_history": [],
        "trace_id": _make_trace_id(),
        "started_at": datetime.now().isoformat(),
        "completed_at": "",
        "final_status": "running",
        "error": "",
    }

    config: dict = {"recursion_limit": MAX_QA_ITERATIONS * 5}
    node_path: list[str] = []
    final_state: dict = {}

    # astream逐节点输出
    async for event in app.astream(initial_state, config=config):
        # event格式: {node_name: state_update}
        for node_name, state_update in event.items():
            if node_name == "__end__":
                continue
            node_path.append(node_name)

            # 打印节点执行信息
            if node_name == "collector":
                claims_count = len(state_update.get("claims", []))
                fetched = state_update.get("sources_fetched", 0)
                print(f"    collector:  +{claims_count} claims (fetched={fetched})")
            elif node_name == "analyst":
                comp = state_update.get("completeness_score", 0)
                print(f"    analyst:    completeness={comp:.0%}")
            elif node_name == "writer":
                rlen = state_update.get("report_length", 0)
                print(f"    writer:     report={rlen} chars")
            elif node_name == "qa":
                verdict = state_update.get("qa_verdict", "?")
                score = state_update.get("qa_score", 0)
                missing = state_update.get("missing_dimensions", [])
                print(f"    qa:         verdict={verdict}, score={score:.2f}, missing={missing}")

            # 累积state（astream只给增量，需手动合并）
            if not final_state:
                final_state = dict(initial_state)
            final_state.update(state_update)

    return final_state, node_path


# ============================================================
# 对比报告生成
# ============================================================
async def generate_comparison_report(profiles: list[dict]) -> str:
    """基于三个竞品的profile生成对比报告（直接调WriterAgent LLM）"""
    sep("Generating Comparison Report")

    from agents.writer.agent import WriterAgent

    names = [p["name"] for p in profiles]

    compact_profiles = []
    for p in profiles:
        prof = p["profile"]
        compact = {
            "name": p["name"],
            "one_liner": prof.get("one_liner"),
            "pricing": prof.get("pricing"),
            "feature_tree_summary": [
                {"name": fn.get("name", ""), "category": fn.get("category")}
                for fn in prof.get("feature_tree", [])[:20]
            ],
            "swot_summary": [
                {"category": s.get("category"), "count": len(s.get("items", []))}
                for s in prof.get("swot", [])
            ],
            "extensions": prof.get("extensions", {}),
        }
        compact_profiles.append(compact)

    profiles_json = json.dumps(compact_profiles, ensure_ascii=False, indent=2)

    compare_prompt = f"""请基于以下三个竞品的结构化数据，生成一份竞品对比报告。

竞品列表: {", ".join(names)}

## 各竞品数据
{profiles_json}

---

请生成Markdown格式的竞品对比报告，包含以下章节：

### 1. 竞品概览对比
用表格展示三个竞品的基本信息：产品名、定位、定价模式。

### 2. 定价对比
用表格横向对比三个竞品的各定价层级，列：竞品 | 层级 | 价格 | 核心功能 | 限制。

### 3. 核心功能对比矩阵
按功能维度（如文档协作、项目管理、AI能力、集成生态等）用表格对比三个竞品，用 ✓/✗/部分 标注支持情况。

### 4. AI能力对比
专门对比三个竞品的AI功能差异，包括AI功能名称、使用场景、差异化亮点。

### 5. 综合推荐结论
- 各竞品最佳适用场景
- 团队选型建议（小团队/中型团队/大型企业分别推荐什么）
- 总结性评价

要求：
- 表格内容简洁，单元格不超过20字
- 不编造数据，只基于输入数据撰写
- 直接输出Markdown，不要包裹代码块
"""

    writer = WriterAgent()
    response = await writer.call_llm(messages=[{"role": "user", "content": compare_prompt}])
    return response.text


# ============================================================
# 主流程
# ============================================================
async def main():
    sep("FULL DEMO: Notion vs Feishu vs ClickUp (LangGraph StateGraph)")

    required = ["DEEPSEEK_API_KEY"]
    missing_env = [k for k in required if not os.getenv(k)]
    if missing_env:
        print(f"[FAIL] Missing env vars: {missing_env}")
        return

    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Competitors: {', '.join(c['name'] for c in COMPETITORS)}")
    print("Graph: orchestrator.graph.build_graph() — StateGraph with conditional_edges")
    print(f"Max QA iterations: {MAX_QA_ITERATIONS}")

    # 编译一次LangGraph，三个竞品复用同一个graph实例
    app = build_graph(checkpointer=None)

    all_results: list[dict] = []
    all_paths: dict[str, list[str]] = {}

    for comp in COMPETITORS:
        sep(f"[{comp['name']}] Running through LangGraph StateGraph")
        print("  Nodes: collector → analyst → writer → qa (→ collector on revise)")
        print(f"  Scope: {comp['scope']}")

        final_state, node_path = await run_via_graph(app, comp["name"], comp["scope"])

        all_paths[comp["name"]] = node_path

        # 提取结果
        result = {
            "name": comp["name"],
            "trace_id": final_state.get("trace_id", ""),
            "claims": final_state.get("claims", []),
            "profile": final_state.get("profile", {}),
            "report_markdown": final_state.get("report_markdown", ""),
            "qa_score": final_state.get("qa_score", 0.0),
            "qa_verdict": final_state.get("qa_verdict", "unknown"),
            "completeness": final_state.get("completeness_score", 0.0),
            "feedback_history": final_state.get("feedback_history", []),
            "final_status": final_state.get("final_status", ""),
        }
        result["iterations"] = len([f for f in result["feedback_history"] if f]) or 1
        all_results.append(result)

        # 打印节点路径
        path_str = " → ".join(node_path)
        print(f"\n  Node path: {path_str}")
        print(f"  Final: {result['final_status']}")

    # 生成对比报告
    comparison_md = ""
    successful = [r for r in all_results if r["profile"]]
    if len(successful) >= 2:
        comparison_md = await generate_comparison_report(successful)

    # ============================================================
    # 汇总输出
    # ============================================================
    sep("FINAL RESULTS")

    # 节点路径汇总
    print("\n  GRAPH EXECUTION PATHS:")
    print("  " + "-" * 60)
    for name, path in all_paths.items():
        path_str = " → ".join(path)
        print(f"  {name:10s}: {path_str}")
    print("  " + "-" * 60)

    # 结果汇总表
    print("\n  QA RESULTS:")
    print("  " + "-" * 60)
    for r in all_results:
        status = "[OK]" if r["qa_verdict"] == "pass" else "[--]"
        print(
            f"  {status} {r['name']:10s}  claims={len(r['claims']):3d}  "
            f"complete={r['completeness']:.0%}  qa_score={r['qa_score']:.2f}  "
            f"iter={r['iterations']}  status={r['final_status']}"
        )
    print("  " + "-" * 60)

    # 构建并保存报告
    summary_lines = []
    summary_lines.append("# 竞品分析完整Pipeline演示报告\n")
    summary_lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    summary_lines.append("**编排引擎**: LangGraph StateGraph (`orchestrator.graph.build_graph`)\n")
    summary_lines.append("**竞品**: Notion vs Feishu vs ClickUp\n\n")

    # 节点路径
    summary_lines.append("## Graph执行路径\n")
    summary_lines.append("每个竞品通过同一个StateGraph实例运行，QA条件路由真实生效：\n")
    summary_lines.append("```")
    for name, path in all_paths.items():
        summary_lines.append(f"{name}: {' → '.join(path)}")
    summary_lines.append("```\n")

    # QA结果汇总表
    summary_lines.append("## Pipeline执行摘要\n")
    summary_lines.append("| 竞品 | Claims数 | 完整度 | QA分数 | QA判定 | 迭代次数 | 最终状态 |")
    summary_lines.append("|------|---------|--------|--------|--------|---------|---------|")
    for r in all_results:
        status = "PASS" if r["qa_verdict"] == "pass" else r["qa_verdict"].upper()
        summary_lines.append(
            f"| {r['name']} | {len(r['claims'])} | {r['completeness']:.0%} "
            f"| {r['qa_score']:.2f} | {status} | {r['iterations']} | {r['final_status']} |"
        )
    summary_lines.append("")

    # 各竞品报告
    for r in all_results:
        summary_lines.append(f"## {r['name']} 详细报告\n")
        summary_lines.append(f"**Trace ID**: `{r['trace_id']}`\n")
        summary_lines.append(
            f"**QA Score**: {r['qa_score']:.2f} | **Verdict**: {r['qa_verdict']} | **Iterations**: {r['iterations']}\n"
        )
        if r["report_markdown"]:
            summary_lines.append(r["report_markdown"])
        summary_lines.append("\n---\n")

    # 对比报告
    if comparison_md:
        summary_lines.append("## 竞品对比报告\n")
        summary_lines.append(comparison_md)

    final_report = "\n".join(summary_lines)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "full_demo.md"
    report_path.write_text(final_report, encoding="utf-8")
    print(f"\n  Report saved: {report_path}")
    print("  Check Langfuse: https://cloud.langfuse.com")


if __name__ == "__main__":
    asyncio.run(main())
