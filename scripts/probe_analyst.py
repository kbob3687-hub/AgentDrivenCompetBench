"""Quick probe: feed minimal claims to AnalystAgent, see if profile builds."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "src")
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


async def main():
    from agents.analyst.agent import AnalystAgent
    from schemas.message import AgentMessage, MessageContext, MessageType

    claims = [
        {
            "dimension": "pricing",
            "claim": "Notion Free plan offers unlimited blocks for personal use",
            "confidence": 0.9,
            "sources": [
                {
                    "url": "https://notion.so/pricing",
                    "snippet": "Free Forever",
                    "source_type": "official_doc",
                    "title": "Notion Pricing",
                }
            ],
        },
        {
            "dimension": "pricing",
            "claim": "Plus plan is $10/user/month billed annually",
            "confidence": 0.9,
            "sources": [
                {
                    "url": "https://notion.so/pricing",
                    "snippet": "Plus $10",
                    "source_type": "official_doc",
                    "title": "Notion Pricing",
                }
            ],
        },
        {
            "dimension": "features",
            "claim": "Notion AI provides writing assistance and Q&A",
            "confidence": 0.85,
            "sources": [
                {
                    "url": "https://notion.so/product/ai",
                    "snippet": "AI assistant",
                    "source_type": "official_doc",
                    "title": "Notion AI",
                }
            ],
        },
    ]

    msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="analyst",
        function_name="analyze_competitor",
        arguments={
            "competitor_name": "Notion",
            "claims": claims,
            "dimensions_requested": ["pricing", "features"],
            "industry": "saas",
        },
        context=MessageContext(
            competitor_name="Notion",
            iteration=1,
            max_iterations=3,
            previous_feedback=[],
        ),
    )

    agent = AnalystAgent()
    print("[probe] calling analyst.execute...", flush=True)
    result = await agent.execute(msg)
    args = result.arguments
    print("[probe] keys:", list(args.keys()), flush=True)
    if args.get("error"):
        print("[probe] ERROR:", args["error"], flush=True)
        if args.get("raw_output"):
            print("[probe] raw[:500]:", args["raw_output"][:500], flush=True)
    else:
        profile = args.get("profile", {})
        print("[probe] profile keys:", list(profile.keys()), flush=True)
        print("[probe] feature_tree count:", len(profile.get("feature_tree", [])), flush=True)
        print("[probe] has pricing:", profile.get("pricing") is not None, flush=True)
        print("[probe] completeness:", args.get("completeness_score"), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
