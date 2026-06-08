"""四段链路完整测试：Collector -> Analyst -> Writer -> QA

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/test_pipeline.py

验证完整的Agent协作流程，输出每个阶段的关键指标。
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from agents.analyst.agent import AnalystAgent
from agents.collector.agent import CollectorAgent
from agents.qa.agent import QAAgent
from agents.writer.agent import WriterAgent
from schemas.message import AgentMessage, CollectRequest, MessageContext, MessageType


def separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


async def main():
    separator("FULL PIPELINE TEST: Collector -> Analyst -> Writer -> QA")

    required = [
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[FAIL] Missing env vars: {missing}")
        return

    trace_id = f"pipeline_{uuid.uuid4().hex[:8]}"
    print(f"Trace ID: {trace_id}")
    print("Target: Notion (pricing)")

    # ====================================================
    # STAGE 1: Collector (DeepSeek)
    # ====================================================
    separator("STAGE 1/4: Collector (DeepSeek)")
    collector = CollectorAgent()

    collect_msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=trace_id,
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="collector",
        function_name="collect_competitor_data",
        arguments=CollectRequest(
            target="Notion",
            collect_type="web_scrape",
            scope=["pricing"],
            depth="standard",
            max_sources=1,
        ).model_dump(),
        context=MessageContext(competitor_name="Notion", iteration=1),
    )

    collect_result = await collector.execute(collect_msg)
    claims = collect_result.arguments.get("claims", [])
    print(f"  [OK] Collected {len(claims)} claims")
    print(f"  Sources fetched: {collect_result.arguments.get('sources_fetched')}")
    print(f"  Sources failed: {collect_result.arguments.get('sources_failed')}")

    if not claims:
        print("  [FAIL] No claims, abort pipeline")
        return

    # ====================================================
    # STAGE 2: Analyst (Claude)
    # ====================================================
    separator("STAGE 2/4: Analyst (Claude)")
    analyst = AnalystAgent()

    analyze_msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=trace_id,
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="analyst",
        function_name="analyze_competitor_data",
        arguments={
            "competitor_name": "Notion",
            "claims": claims,
            "dimensions_requested": ["pricing"],
        },
        context=MessageContext(competitor_name="Notion", iteration=1),
    )

    analyze_result = await analyst.execute(analyze_msg)

    if "error" in analyze_result.arguments:
        print(f"  [FAIL] Analyst error: {analyze_result.arguments['error']}")
        return

    profile = analyze_result.arguments.get("profile", {})
    completeness = analyze_result.arguments.get("completeness_score", 0)
    print("  [OK] Profile generated")
    print(f"  Completeness: {completeness:.0%}")
    print(f"  Pricing tiers: {len(profile.get('pricing', {}).get('tiers', []))}")
    print(f"  Feature nodes: {len(profile.get('feature_tree', []))}")
    print(f"  SWOT items: {sum(len(s.get('items', [])) for s in profile.get('swot', []))}")

    # ====================================================
    # STAGE 3: Writer (Claude)
    # ====================================================
    separator("STAGE 3/4: Writer (Claude)")
    writer = WriterAgent()

    write_msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=trace_id,
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="writer",
        function_name="write_report",
        arguments={
            "competitor_name": "Notion",
            "profile": profile,
        },
        context=MessageContext(competitor_name="Notion", iteration=1),
    )

    write_result = await writer.execute(write_msg)

    if "error" in write_result.arguments:
        print(f"  [FAIL] Writer error: {write_result.arguments['error']}")
        return

    report_md = write_result.arguments.get("report_markdown", "")
    print("  [OK] Report generated")
    print(f"  Length: {len(report_md)} chars")
    print(f"  Footnotes: {write_result.arguments.get('footnote_count', 0)}")
    print("\n  --- Report Preview (first 500 chars) ---")
    print(f"  {report_md[:500]}")
    print("  --- End Preview ---")

    # ====================================================
    # STAGE 4: QA (Claude)
    # ====================================================
    separator("STAGE 4/4: QA (Claude)")
    qa = QAAgent()

    qa_msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=trace_id,
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="qa",
        function_name="quality_check",
        arguments={
            "competitor_name": "Notion",
            "profile": profile,
            "report_markdown": report_md,
            "original_claims": claims,
        },
        context=MessageContext(competitor_name="Notion", iteration=1),
    )

    qa_result = await qa.execute(qa_msg)

    verdict = qa_result.arguments.get("verdict", "unknown")
    overall_score = qa_result.arguments.get("overall_score", 0)
    issues_count = qa_result.arguments.get("issues_count", 0)
    critical = qa_result.arguments.get("critical_issues", 0)

    print(f"  [{'OK' if verdict == 'pass' else 'WARN'}] Verdict: {verdict}")
    print(f"  Overall score: {overall_score:.2f}")
    print(f"  Issues found: {issues_count} (critical: {critical})")

    feedback = qa_result.arguments.get("feedback", {})
    if feedback:
        print(f"  Summary: {feedback.get('summary', '')}")
        issues = feedback.get("issues", [])
        if issues:
            print("\n  Top issues:")
            for issue in issues[:5]:
                sev = issue.get("severity", "?")
                desc = issue.get("description", "")[:80]
                print(f"    [{sev}] {desc}")

    # ====================================================
    # FINAL SUMMARY
    # ====================================================
    separator("PIPELINE SUMMARY")
    print(f"""
  Trace ID:       {trace_id}
  Target:         Notion
  Claims:         {len(claims)}
  Completeness:   {completeness:.0%}
  Report length:  {len(report_md)} chars
  QA verdict:     {verdict} (score: {overall_score:.2f})
  Total issues:   {issues_count}

  Models used:
    Collector -> DeepSeek (openai_compat)
    Analyst   -> Claude (anthropic)
    Writer    -> Claude (anthropic)
    QA        -> Claude (anthropic)
""")

    if verdict == "pass":
        print("  [OK] PIPELINE PASSED - Report ready for delivery")
    elif verdict == "revise":
        print("  [WARN] PIPELINE NEEDS REVISION - QA found fixable issues")
        print("  In production: Orchestrator would route back to Writer/Analyst")
    else:
        print("  [FAIL] PIPELINE REJECTED - Major quality issues")
        print("  In production: Orchestrator would route back to Collector")

    # 保存报告到文件
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / f"notion_report_{trace_id}.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n  Report saved: {report_path}")
    print("\n  Check Langfuse: https://cloud.langfuse.com")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
