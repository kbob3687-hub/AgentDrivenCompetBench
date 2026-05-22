"""测试脚本：触发真实revise场景

场景设计：
  - 初始采集scope: ["pricing"]（故意不完整）
  - 期望维度: ["pricing", "features", "integrations"]
  - QA的check_dimension_coverage会发现features和integrations缺失
  - 触发revise → Collector补采 → Analyst重分析 → Writer重写 → QA再检

预期流程：
  第1轮: Collector(pricing) → Analyst → Writer → QA(revise: features,integrations缺失)
  第2轮: Collector(pricing+features+integrations) → Analyst → Writer → QA(pass或再revise)
  第3轮(如有): 最终pass或max_iterations_reached

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/test_revise_scenario.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from orchestrator.graph import build_graph
from orchestrator.state import GraphState


def print_banner(text: str, char: str = "=") -> None:
    width = 70
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def print_iteration_header(iteration: int, node: str) -> None:
    print(f"\n  {'─' * 60}")
    print(f"  │ 第{iteration}轮 → [{node}]")
    print(f"  {'─' * 60}")


async def main():
    print_banner("竞品分析多Agent系统 - 真实Revise场景测试")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标: Notion")
    print(f"  初始scope: ['pricing'] (故意不完整)")
    print(f"  期望维度: ['pricing', 'features', 'integrations']")
    print(f"  max_iterations: 3")
    print(f"  预期: QA发现缺失维度 → revise → 补采 → 最终pass")
    print()

    required_keys = ["DEEPSEEK_API_KEY"]
    missing = [k for k in required_keys if not os.getenv(k)]
    if missing:
        print(f"  [FAIL] 缺少环境变量: {missing}")
        return

    app = build_graph()

    seed = f"revise_test_{int(time.time())}"
    trace_id_hex = hashlib.md5(seed.encode()).hexdigest()
    print(f"  trace_id (Langfuse): {trace_id_hex}")
    print(f"  trace_seed: {seed}")
    print()

    initial_state: GraphState = {
        "competitor_name": "Notion",
        "collect_scope": ["pricing"],
        "target_urls": [],
        "expected_dimensions": ["pricing", "features", "integrations"],
        "iteration": 1,
        "max_iterations": 3,
        "feedback_history": [],
        "missing_dimensions": [],
        "trace_id": trace_id_hex,
        "started_at": datetime.now().isoformat(),
        "final_status": "running",
    }

    config = {"recursion_limit": 20}

    print_banner("开始执行Pipeline (含反馈循环)", char="─")
    start_time = time.time()

    final_state = await app.ainvoke(initial_state, config=config)

    elapsed = time.time() - start_time

    # ====== 结果分析 ======
    print_banner("执行结果")

    final_status = final_state.get("final_status", "unknown")
    total_iterations = final_state.get("iteration", 1) - 1
    qa_verdict = final_state.get("qa_verdict", "N/A")
    qa_score = final_state.get("qa_score", 0)

    print(f"  最终状态:   {final_status}")
    print(f"  总迭代数:   {total_iterations}")
    print(f"  QA判定:     {qa_verdict}")
    print(f"  QA评分:     {qa_score:.2f}")
    print(f"  耗时:       {elapsed:.1f}s")

    # ====== 反馈轨迹（核心展示） ======
    print_banner("QA反馈轨迹 (多Agent协作证据)", char="─")
    feedback_history = final_state.get("feedback_history", [])

    if not feedback_history:
        print("  (无反馈记录 - 异常)")
    else:
        for i, record in enumerate(feedback_history, 1):
            verdict = record.get("verdict", "?")
            score = record.get("score", 0)
            issues = record.get("issues_count", 0)
            critical = record.get("critical_issues", 0)
            action = record.get("action_taken", "")
            summary = record.get("feedback_summary", "")

            icon = {"pass": "[PASS]", "revise": "[REVISE]", "reject": "[REJECT]"}.get(verdict, "[?]")
            print(f"\n  第{i}轮 {icon}")
            print(f"    verdict:  {verdict}")
            print(f"    score:    {score:.2f}")
            print(f"    issues:   {issues} (critical: {critical})")
            print(f"    action:   {action}")
            if summary:
                print(f"    summary:  {summary[:100]}")

    # ====== 验证revise是否真的发生了 ======
    print_banner("Revise验证", char="─")
    revise_count = sum(1 for r in feedback_history if r.get("verdict") == "revise")
    pass_count = sum(1 for r in feedback_history if r.get("verdict") == "pass")

    if revise_count > 0:
        print(f"  [OK] Revise触发成功！共{revise_count}次revise")
        print(f"  [OK] 反馈循环工作正常：QA检测到缺失维度并打回Collector补采")
    else:
        print(f"  [WARN] 未触发revise - 可能原因：")
        print(f"    - Collector第一轮就采到了所有维度的数据")
        print(f"    - QA评分直接>=0.80通过了")

    if pass_count > 0:
        print(f"  [OK] 最终通过QA质检")
    elif final_status.startswith("max_iterations"):
        print(f"  [INFO] 达到最大迭代次数后结束")
    elif final_status.startswith("rejected"):
        print(f"  [WARN] 被QA拒绝")

    # ====== 数据统计 ======
    print_banner("数据统计", char="─")
    claims = final_state.get("claims", [])
    profile = final_state.get("profile", {})
    report = final_state.get("report_markdown", "")

    print(f"  Claims总数:     {len(claims)}")
    print(f"  采集维度覆盖:   {final_state.get('collect_scope', [])}")
    print(f"  Profile定价层级: {len(profile.get('pricing', {}).get('tiers', []))}")
    print(f"  Profile功能节点: {len(profile.get('feature_tree', []))}")
    print(f"  SWOT条目:       {sum(len(s.get('items', [])) for s in profile.get('swot', []))}")
    print(f"  报告长度:       {len(report)} 字符")

    # ====== 保存输出 ======
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if report:
        report_path = output_dir / f"revise_test_report_{ts}.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\n  报告: {report_path}")

    state_path = output_dir / f"revise_test_state_{ts}.json"
    serializable = {
        k: v for k, v in final_state.items()
        if isinstance(v, (str, int, float, bool, list, dict, type(None)))
    }
    state_path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  State: {state_path}")

    # Langfuse trace链接
    langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    print(f"\n  Langfuse Trace: {langfuse_host}/trace/{trace_id_hex}")

    print_banner("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
