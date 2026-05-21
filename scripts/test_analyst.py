"""AnalystAgent单独测试脚本

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/test_analyst.py

测试链路：CollectorAgent (DeepSeek) -> AnalystAgent (Claude) -> CompetitorProfile
"""

from __future__ import annotations

import asyncio
import json
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
from schemas.message import AgentMessage, CollectRequest, MessageContext, MessageType


async def main():
    print("\n" + "=" * 70)
    print("Collector -> Analyst Pipeline Test")
    print("=" * 70)

    required = ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[FAIL] Missing env vars: {missing}")
        return

    # ====================================================
    # STEP 1: Collector 采集 Notion 定价信息
    # ====================================================
    print("\n[STEP 1] CollectorAgent fetching Notion pricing...")
    collector = CollectorAgent()
    trace_id = f"test_{uuid.uuid4().hex[:8]}"

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

    collect_response = await collector.execute(collect_msg)
    claims = collect_response.arguments.get("claims", [])

    print(f"  -> Collected {len(claims)} claims")
    if not claims:
        print("[FAIL] No claims collected, abort")
        return

    # ====================================================
    # STEP 2: Analyst 分析claims，生成CompetitorProfile
    # ====================================================
    print(f"\n[STEP 2] AnalystAgent analyzing {len(claims)} claims (using Claude)...")
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

    analyze_response = await analyst.execute(analyze_msg)

    # ====================================================
    # 输出结果
    # ====================================================
    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)

    if "error" in analyze_response.arguments:
        print(f"[FAIL] {analyze_response.arguments['error']}")
        if "raw_output" in analyze_response.arguments:
            print(f"\nRaw output:\n{analyze_response.arguments['raw_output']}")
        return

    profile = analyze_response.arguments.get("profile", {})
    completeness = analyze_response.arguments.get("completeness_score", 0)

    print(f"\nCompany: {profile.get('company_name')}")
    print(f"Product: {profile.get('product_name')}")
    print(f"Industry: {profile.get('industry')}")
    print(f"One-liner: {profile.get('one_liner')}")
    print(f"Completeness: {completeness:.2%}")

    pricing = profile.get("pricing")
    if pricing:
        print(f"\n=== Pricing ===")
        print(f"Model type: {pricing.get('model_type')}")
        print(f"Currency: {pricing.get('currency')}")
        print(f"Confidence: {pricing.get('evidence', {}).get('confidence')}")
        for tier in pricing.get("tiers", []):
            print(f"  - {tier.get('name')}: {tier.get('price')} ({tier.get('billing_cycle', 'N/A')})")
            features = tier.get("features", [])
            if features:
                print(f"      features: {', '.join(features[:3])}{'...' if len(features) > 3 else ''}")

    feature_tree = profile.get("feature_tree", [])
    if feature_tree:
        print(f"\n=== Feature Tree ({len(feature_tree)} nodes) ===")
        for node in feature_tree[:5]:
            print(f"  - {node.get('name')} (confidence: {node.get('description', {}).get('confidence')})")
            for sub in node.get("sub_features", [])[:3]:
                print(f"      * {sub.get('name')}")

    swot = profile.get("swot", [])
    if swot:
        print(f"\n=== SWOT ===")
        for item in swot:
            cat = item.get("category")
            count = len(item.get("items", []))
            print(f"  {cat}: {count} items")
            for c in item.get("items", [])[:2]:
                print(f"      - {c.get('claim')[:80]}")

    print("\n" + "=" * 70)
    print("[OK] PIPELINE TEST PASSED")
    print(f"Trace ID: {trace_id}")
    print("Check: https://cloud.langfuse.com")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
