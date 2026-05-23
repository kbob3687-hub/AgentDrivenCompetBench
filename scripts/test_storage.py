"""Quick integration test for storage layer"""
import asyncio
import sys
import uuid

sys.path.insert(0, "src")


async def test():
    from storage.engine import init_engine, dispose_engine, get_engine
    from storage.models import Base
    from storage.crud import save_run, get_run, list_runs

    engine = await init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("1. Engine init + table created")

    task_id = str(uuid.uuid4())
    mock_state = {
        "competitor_name": "TestCompany",
        "industry": "saas",
        "qa_score": 0.75,
        "qa_verdict": "pass",
        "iteration": 2,
        "report_length": 2500,
        "sources_fetched": 5,
        "started_at": "2025-05-23T10:00:00",
        "completed_at": "2025-05-23T10:02:00",
        "report_markdown": "# Test Report\n\nThis is a test.",
        "claims": [{"claim": "test claim", "confidence": 0.9}],
        "profile": {"company_name": "TestCompany"},
        "feedback_history": [{"iteration": 1, "verdict": "revise"}],
    }
    await save_run(mock_state, task_id, "completed")
    print(f"2. Saved run {task_id}")

    result = await get_run(task_id)
    assert result is not None, "get_run returned None!"
    assert result["status"] == "completed"
    assert result["result"]["competitor_name"] == "TestCompany"
    print(f"3. Retrieved run, status={result['status']}")

    items, total = await list_runs(page=1, page_size=10)
    assert total >= 1
    found = any(i["task_id"] == task_id for i in items)
    assert found, "Saved run not in list!"
    print(f"4. list_runs: total={total}, found our run")

    items2, total2 = await list_runs(competitor_name="TestComp")
    assert total2 >= 1
    print(f"5. Filter by competitor_name: {total2} results")

    await dispose_engine()
    print("\nAll storage tests passed!")


asyncio.run(test())
