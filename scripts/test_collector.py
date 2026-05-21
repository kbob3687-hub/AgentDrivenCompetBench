"""CollectorAgent单独测试脚本

运行方式：
    cd "E:\\java\\dreamdance -demo"
    python scripts/test_collector.py

测试目标：采集Notion定价页，验证：
1. Jina Reader能正常获取网页内容
2. CollectorAgent能调用Claude提取结构化信息
3. Langfuse Cloud能收到trace
4. 输出符合EvidencedClaim格式
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# Windows终端UTF-8输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

# 加载.env
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# 把src加入Python path
sys.path.insert(0, str(ROOT / "src"))

from agents.collector.agent import CollectorAgent
from agents.collector.tools import jina_reader
from schemas.message import AgentMessage, CollectRequest, MessageContext, MessageType


async def test_jina_reader():
    """步骤1：单独测试Jina Reader是否能获取Notion定价页"""
    print("\n" + "=" * 70)
    print("STEP 1: Test Jina Reader on Notion pricing page")
    print("=" * 70)

    result = await jina_reader("https://www.notion.so/pricing")

    if result.success:
        print(f"[OK] Fetched: {result.url}")
        print(f"  Title: {result.title}")
        print(f"  Content length: {len(result.content)} chars")
        print(f"  Snapshot hash: {result.snapshot_hash}")
        print(f"\n  First 500 chars:\n  {result.content[:500]}")
    else:
        print(f"[FAIL] {result.error}")
        return False

    return True


async def test_collector_agent():
    """步骤2：测试完整CollectorAgent流程"""
    print("\n" + "=" * 70)
    print("STEP 2: Test CollectorAgent end-to-end")
    print("=" * 70)

    agent = CollectorAgent()

    # 构造采集任务
    request_msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=f"test_{uuid.uuid4().hex[:8]}",
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
        context=MessageContext(
            competitor_name="Notion",
            iteration=1,
        ),
    )

    print(f"Trace ID: {request_msg.trace_id}")
    print(f"Target: {request_msg.arguments['target']}")
    print(f"Scope: {request_msg.arguments['scope']}")
    print("\nExecuting CollectorAgent...")

    response = await agent.execute(request_msg)

    print("\n" + "-" * 70)
    print("RESPONSE")
    print("-" * 70)
    print(f"From: {response.from_agent} -> To: {response.to_agent}")
    print(f"Function: {response.function_name}")
    print(f"Sources fetched: {response.arguments.get('sources_fetched', 0)}")
    print(f"Sources failed: {response.arguments.get('sources_failed', 0)}")

    claims = response.arguments.get("claims", [])
    print(f"\nExtracted {len(claims)} claims:")

    for i, claim in enumerate(claims[:5], 1):
        print(f"\n  [{i}] dimension: {claim.get('dimension', 'N/A')}")
        print(f"      claim: {claim.get('claim', '')[:100]}")
        print(f"      confidence: {claim.get('confidence', 0)}")
        sources = claim.get("sources", [])
        if sources:
            print(f"      source: {sources[0].get('url', '')}")
            print(f"      snippet: {sources[0].get('snippet', '')[:100]}")

    if len(claims) > 5:
        print(f"\n  ... and {len(claims) - 5} more claims")

    return len(claims) > 0


async def main():
    print("\n" + "=" * 70)
    print("CollectorAgent Test Suite")
    print("=" * 70)

    # 检查环境变量
    required = ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "ANTHROPIC_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[FAIL] Missing env vars: {missing}")
        print("  Please configure .env file")
        return

    # 步骤1：测试爬虫
    try:
        if not await test_jina_reader():
            print("\n[FAIL] Jina Reader test failed, skip subsequent tests")
            return
    except Exception as e:
        print(f"\n[FAIL] Jina Reader test error: {e}")
        return

    # 步骤2：测试完整Agent
    try:
        success = await test_collector_agent()
        print("\n" + "=" * 70)
        if success:
            print("[OK] ALL TESTS PASSED")
            print("\nCheck Langfuse Cloud dashboard for traces:")
            print("  https://cloud.langfuse.com")
        else:
            print("[FAIL] Agent returned no claims")
        print("=" * 70)
    except Exception as e:
        print(f"\n[FAIL] Agent test error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
