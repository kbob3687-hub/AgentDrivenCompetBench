"""测试合规工具：robots.txt 检查 + PII 脱敏"""

from __future__ import annotations

import pytest

from agents.collector.compliance import _robots_cache, redact_pii


@pytest.fixture(autouse=True)
def clear_robots_cache():
    """每个测试隔离 robots 缓存，避免互相影响。"""
    _robots_cache.clear()
    yield
    _robots_cache.clear()


def test_redact_pii_phone():
    text = "联系电话 13812345678 或 18900001111"
    out, counts = redact_pii(text)
    assert "13812345678" not in out
    assert "18900001111" not in out
    assert out.count("[手机号]") == 2
    assert counts["[手机号]"] == 2


def test_redact_pii_email():
    text = "support@notion.so 反馈到 user.name+tag@company.co.uk"
    out, counts = redact_pii(text)
    assert "@" not in out
    assert counts["[邮箱]"] == 2


def test_redact_pii_id_card():
    # 18 位身份证（虚构号，符合格式）
    text = "员工身份证 110101199003078765 已登记"
    out, counts = redact_pii(text)
    assert "110101199003078765" not in out
    assert counts.get("[身份证]") == 1


def test_redact_pii_no_match():
    text = "This is a simple Notion pricing page with $10/month plan."
    out, counts = redact_pii(text)
    assert out == text
    assert counts == {}


def test_redact_pii_empty():
    out, counts = redact_pii("")
    assert out == ""
    assert counts == {}


def test_redact_pii_phone_in_serial_number_not_matched():
    """手机号 regex 用了前后断言，避免误伤连续数字串中的 11 位片段。"""
    # 连续的长数字串不应该被识别为手机号
    text = "订单号 99913812345678456789 (这不是手机号)"
    out, counts = redact_pii(text)
    # 因为前后都是数字，11 位手机号子串不被匹配
    assert "[手机号]" not in out


@pytest.mark.asyncio
async def test_is_allowed_by_robots_no_host():
    """非法 URL（无 host）默认放行。"""
    from agents.collector.compliance import is_allowed_by_robots

    allowed, reason = await is_allowed_by_robots("not-a-url")
    assert allowed
    assert reason == "no host"


@pytest.mark.asyncio
async def test_is_allowed_by_robots_disallow(monkeypatch):
    """模拟一个 Disallow: /private/ 的 robots.txt。"""
    from agents.collector import compliance

    async def fake_fetch(robots_url, timeout):
        from urllib.robotparser import RobotFileParser

        rp = RobotFileParser()
        rp.parse(["User-agent: *", "Disallow: /private/"])
        return rp

    monkeypatch.setattr(compliance, "_fetch_robots", fake_fetch)

    allowed, _ = await compliance.is_allowed_by_robots("https://example.com/public/page")
    assert allowed

    blocked, reason = await compliance.is_allowed_by_robots("https://example.com/private/secret")
    assert not blocked
    assert "disallowed" in reason


@pytest.mark.asyncio
async def test_is_allowed_by_robots_no_robots(monkeypatch):
    """没有 robots.txt（404 / 抓取失败）默认放行。"""
    from agents.collector import compliance

    async def fake_fetch(robots_url, timeout):
        return None

    monkeypatch.setattr(compliance, "_fetch_robots", fake_fetch)

    allowed, reason = await compliance.is_allowed_by_robots("https://example.com/anywhere")
    assert allowed
    assert reason == "no robots.txt"
