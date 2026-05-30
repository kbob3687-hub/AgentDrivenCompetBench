"""测试 API 路由：compare 端点、全局错误处理、历史兜底"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_compare_requires_min_two_tasks(client):
    resp = await client.post("/api/analyze/compare", json={"task_ids": ["one"]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_not_found_tasks(client):
    resp = await client.post(
        "/api/analyze/compare",
        json={"task_ids": ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_history_returns_empty_without_pg(client):
    resp = await client.get("/api/analyze/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_global_error_handler_returns_json(client):
    resp = await client.get("/api/analyze/nonexistent-task-id")
    assert resp.status_code in (404, 500)
    data = resp.json()
    assert "error" in data or "detail" in data
