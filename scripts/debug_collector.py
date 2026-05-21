"""Quick debug: test Collector.run() directly to see errors"""
import sys, asyncio, uuid
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from agents.collector.agent import CollectorAgent
from schemas.message import AgentMessage, CollectRequest, MessageContext, MessageType

async def test():
    collector = CollectorAgent()
    msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        trace_id="debug",
        message_type=MessageType.TASK_ASSIGN,
        from_agent="orchestrator",
        to_agent="collector",
        function_name="collect",
        arguments=CollectRequest(target="Notion", collect_type="web_scrape", scope=["pricing"], max_sources=1).model_dump(),
        context=MessageContext(competitor_name="Notion"),
    )
    try:
        result = await collector.run(msg)
        print(f"Sources fetched: {result.arguments.get('sources_fetched')}")
        print(f"Sources failed: {result.arguments.get('sources_failed')}")
        print(f"Errors: {result.arguments.get('errors')}")
        print(f"Claims count: {len(result.arguments.get('claims', []))}")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())
