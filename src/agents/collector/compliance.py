"""合规与隐私工具

- robots.txt 检查：抓取前确认目标站点允许该 User-Agent 访问
- PII 脱敏：对网页正文中的手机号、邮箱、身份证号等做正则掩码
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "AgentDrivenCompetBench/1.0 (+research; respects robots.txt)"

_robots_cache: dict[str, RobotFileParser | None] = {}


async def is_allowed_by_robots(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """检查 url 是否被目标站点的 robots.txt 允许。

    Returns:
        (allowed, reason)
        - allowed=True 时 reason 是简短说明（"allowed" 或 "no robots.txt"）
        - allowed=False 时 reason 是禁止规则的描述
    """
    parsed = urlparse(url)
    if not parsed.netloc:
        return True, "no host"

    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{origin}/robots.txt"

    if origin not in _robots_cache:
        rp = await _fetch_robots(robots_url, timeout)
        _robots_cache[origin] = rp

    rp = _robots_cache[origin]
    if rp is None:
        # 没有 robots.txt 或抓取失败 → 默认放行（行业惯例）
        return True, "no robots.txt"

    if rp.can_fetch(USER_AGENT, url):
        return True, "allowed by robots.txt"
    return False, f"disallowed by {robots_url}"


async def _fetch_robots(robots_url: str, timeout: float) -> RobotFileParser | None:
    """异步拉取并解析 robots.txt。失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 400:
                return None
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
    except Exception:
        return None


# ===== PII 脱敏 =====

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 中国大陆身份证号（18 位，含校验位 X）
    (re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"), "[身份证]"),
    # 中国大陆手机号（11 位，1 开头）
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
    # 邮箱
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[邮箱]"),
    # 银行卡号（13-19 位连续数字，避免误伤要求前后非数字）
    (re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), "[银行卡]"),
]


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """对文本中的 PII 做掩码。

    Returns:
        (redacted_text, counts) — counts 形如 {"[手机号]": 2, "[邮箱]": 1}
    """
    if not text:
        return text, {}

    counts: dict[str, int] = {}
    for pattern, placeholder in _PII_PATTERNS:
        new_text, n = pattern.subn(placeholder, text)
        if n:
            counts[placeholder] = counts.get(placeholder, 0) + n
            text = new_text

    return text, counts
