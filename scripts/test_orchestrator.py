"""LangGraph编排层端到端测试

运行完整pipeline：Collector → Analyst → Writer → QA（含反馈循环）
展示多Agent协作轨迹和FeedbackRecord。
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加src到path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from orchestrator.graph import run_pipeline


async def main():
    print("=" * 70)
    print("  竞品分析多Agent系统 - LangGraph编排层测试")
    print("  场景：维度补全反馈循环")
    print("=" * 70)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标竞品: Notion")
    print(f"  初始采集: pricing（故意不完整）")
    print(f"  期望维度: pricing, features（QA会发现features缺失）")
    print(f"  预期流程: 第1轮revise → 第2轮补采features → pass")
    print(f"  最大迭代: 3")
    print("=" * 70)
    print()

    result = await run_pipeline(
        competitor_name="Notion",
        collect_scope=["pricing"],
        expected_dimensions=["pricing", "features"],
        max_iterations=3,
    )

    # ====== 输出结果 ======
    print("\n" + "=" * 70)
    print("  Pipeline执行完成")
    print("=" * 70)

    print(f"\n  最终状态: {result.get('final_status', 'unknown')}")
    print(f"  总迭代数: {result.get('iteration', 1) - 1}")
    print(f"  QA评分:   {result.get('qa_score', 0):.2f}")
    print(f"  QA判定:   {result.get('qa_verdict', 'N/A')}")
    print(f"  开始时间: {result.get('started_at', 'N/A')}")
    print(f"  结束时间: {result.get('completed_at', 'N/A')}")

    # ====== Collector统计 ======
    print(f"\n--- Collector ---")
    print(f"  采集成功: {result.get('sources_fetched', 0)} 个来源")
    print(f"  采集失败: {result.get('sources_failed', 0)} 个来源")
    print(f"  Claims数: {len(result.get('claims', []))}")

    # ====== Analyst统计 ======
    print(f"\n--- Analyst ---")
    profile = result.get("profile", {})
    print(f"  Profile完整度: {result.get('completeness_score', 0):.0%}")
    print(f"  分析维度: {result.get('dimensions_analyzed', [])}")
    if profile:
        print(f"  定价层级: {len(profile.get('pricing', {}).get('tiers', []))} 个")
        print(f"  功能节点: {len(profile.get('feature_tree', []))} 个")
        print(f"  SWOT条目: {sum(len(s.get('items', [])) for s in profile.get('swot', []))} 条")

    # ====== Writer统计 ======
    print(f"\n--- Writer ---")
    report = result.get("report_markdown", "")
    print(f"  报告长度: {len(report)} 字符")
    print(f"  角标数量: {result.get('footnote_count', 0)}")

    # ====== QA反馈轨迹 ======
    print(f"\n--- QA反馈轨迹 (FeedbackHistory) ---")
    feedback_history = result.get("feedback_history", [])
    if feedback_history:
        for record in feedback_history:
            print(f"  第{record['iteration']}轮: "
                  f"verdict={record['verdict']}, "
                  f"score={record['score']:.2f}, "
                  f"issues={record['issues_count']}, "
                  f"action={record['action_taken']}")
    else:
        print("  (无反馈记录)")

    # ====== 保存报告 ======
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    if report:
        report_path = output_dir / f"notion_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\n  报告已保存: {report_path}")

    # 保存完整state（用于调试）
    state_path = output_dir / f"pipeline_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    serializable_state = {
        k: v for k, v in result.items()
        if isinstance(v, (str, int, float, bool, list, dict, type(None)))
    }
    state_path.write_text(
        json.dumps(serializable_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  State已保存: {state_path}")

    # ====== 错误信息 ======
    if result.get("error"):
        print(f"\n  [ERROR] {result['error']}")

    print("\n" + "=" * 70)
    print("  测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
