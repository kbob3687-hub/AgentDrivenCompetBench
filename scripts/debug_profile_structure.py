"""Debug: run collector+analyst for ClickUp, print profile structure"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()

import uuid

from agents.analyst.agent import AnalystAgent
from agents.collector.agent import CollectorAgent
from schemas.message import AgentMessage, MessageContext, MessageType


async def main():
    # Minimal collector run - just 1 URL
    collector = CollectorAgent()
    url = "https://clickup.com/pricing"

    fetch_result = await collector._fetch_url(url)
    if not fetch_result.success:
        print(f"Fetch failed: {fetch_result.error}")
        return

    content = collector._truncate_content(fetch_result.content, max_chars=12000)
    claims = await collector._extract_info(
        competitor_name="ClickUp",
        dimensions=["pricing", "features"],
        url=url,
        title=fetch_result.title,
        content=content,
        snapshot_hash=fetch_result.snapshot_hash,
    )
    print(f"Extracted {len(claims)} claims")
    if not claims:
        print("No claims extracted!")
        return

    # Run analyst
    analyst = AnalystAgent()
    msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="analyst",
        function_name="analyze_competitor",
        arguments={
            "competitor_name": "ClickUp",
            "claims": claims,
            "dimensions_requested": ["pricing", "features"],
            "industry_fields": [],
            "industry": "saas",
        },
        context=MessageContext(competitor_name="ClickUp", iteration=1, max_iterations=3),
    )

    result = await analyst.execute(msg)
    profile = result.arguments.get("profile", {})

    print(f"\n=== Profile keys: {list(profile.keys())}")
    print(f"feature_tree length: {len(profile.get('feature_tree', []))}")
    print(f"swot length: {len(profile.get('swot', []))}")
    print(f"user_personas length: {len(profile.get('user_personas', []))}")
    print(f"extensions keys: {list(profile.get('extensions', {}).keys())}")
    print(f"pricing: {bool(profile.get('pricing'))}")

    # Check confidence structure
    ft = profile.get("feature_tree", [])
    if ft:
        print(f"\nfeature_tree[0] keys: {list(ft[0].keys())}")
        desc = ft[0].get("description", {})
        print(f"feature_tree[0].description type: {type(desc)}")
        print(
            f"feature_tree[0].description keys: {list(desc.keys()) if isinstance(desc, dict) else 'NOT A DICT'}"
        )

    pricing = profile.get("pricing")
    if pricing:
        print(f"\npricing keys: {list(pricing.keys())}")
        ev = pricing.get("evidence", {})
        print(f"pricing.evidence keys: {list(ev.keys()) if isinstance(ev, dict) else 'NOT A DICT'}")

    swot = profile.get("swot", [])
    if swot:
        print(f"\nswot[0] keys: {list(swot[0].keys())}")
        items = swot[0].get("items", [])
        if items:
            print(f"swot[0].items[0] keys: {list(items[0].keys())}")


asyncio.run(main())
