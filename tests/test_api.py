"""测试 API 路由：compare 端点、全局错误处理、历史兜底"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from api.routes.analyze import _tasks


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
async def test_compare_returns_same_industry_extension_fields(client):
    _tasks.clear()
    _tasks["consumer-a"] = {
        "status": "completed",
        "result": {
            "competitor_name": "Pop Mart",
            "industry": "consumer",
            "qa_score": 0.82,
            "profile": {
                "one_liner": "潮玩品牌",
                "pricing": None,
                "feature_tree": [],
                "swot": [],
                "user_personas": [],
                "extensions": {
                    "distribution_channels": ["天猫旗舰店", "线下门店"],
                    "price_range": "mid_range",
                },
            },
        },
    }
    _tasks["consumer-b"] = {
        "status": "completed",
        "result": {
            "competitor_name": "Luckin",
            "industry": "consumer",
            "qa_score": 0.78,
            "profile": {
                "one_liner": "连锁咖啡品牌",
                "pricing": None,
                "feature_tree": [],
                "swot": [],
                "user_personas": [],
                "extensions": {
                    "distribution_channels": ["小程序", "线下门店"],
                    "price_range": "budget",
                },
            },
        },
    }

    resp = await client.post(
        "/api/analyze/compare",
        json={"task_ids": ["consumer-a", "consumer-b"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["common_industry"] == "consumer"
    assert data["mixed_industries"] is False
    field_names = [field["field_name"] for field in data["extension_fields"]]
    assert "distribution_channels" in field_names
    assert "price_range" in field_names
    labels = {field["field_name"]: field["label"] for field in data["extension_fields"]}
    assert labels["distribution_channels"] == "销售渠道分布"


@pytest.mark.asyncio
async def test_compare_hides_extension_fields_for_mixed_industries(client):
    _tasks.clear()
    _tasks["saas-a"] = {
        "status": "completed",
        "result": {
            "competitor_name": "Notion",
            "industry": "saas",
            "qa_score": 0.9,
            "profile": {
                "one_liner": "协作文档工具",
                "pricing": None,
                "feature_tree": [],
                "swot": [],
                "user_personas": [],
                "extensions": {"api_openness": "提供公开 API"},
            },
        },
    }
    _tasks["hardware-a"] = {
        "status": "completed",
        "result": {
            "competitor_name": "Insta360",
            "industry": "hardware",
            "qa_score": 0.76,
            "profile": {
                "one_liner": "运动相机品牌",
                "pricing": None,
                "feature_tree": [],
                "swot": [],
                "user_personas": [],
                "extensions": {"core_specs": ["8K", "防抖"]},
            },
        },
    }

    resp = await client.post(
        "/api/analyze/compare",
        json={"task_ids": ["saas-a", "hardware-a"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["common_industry"] is None
    assert data["mixed_industries"] is True
    assert data["extension_fields"] == []


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
