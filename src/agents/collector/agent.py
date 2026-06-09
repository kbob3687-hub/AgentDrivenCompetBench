"""CollectorAgent - 竞品信息采集Agent

负责从公开网页采集竞品数据，输出带溯源的结构化信息。
默认使用免费抓取链路，Jina/Firecrawl 只在显式开启时作为付费兜底。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from agents.base import AgentConfig, BaseAgent
from agents.collector.compliance import is_allowed_by_robots, redact_pii
from agents.collector.prompts import COLLECT_USER_PROMPT_TEMPLATE, COLLECTOR_SYSTEM_PROMPT
from agents.collector.tools import (
    FetchResult,
    direct_http_fetch,
    firecrawl_fetch,
    jina_reader,
    playwright_fetch,
    reddit_fetch,
)
from schemas.competitor import SourceType
from schemas.message import AgentMessage, CollectRequest, MessageType


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CollectorAgent(BaseAgent):
    """信息采集Agent

    工作流程：
    1. 解析CollectRequest，确定采集目标和维度
    2. 使用免费抓取链路获取网页内容（失败时降级到Playwright）
    3. 调用LLM从网页内容中提取结构化信息
    4. 将提取结果封装为EvidencedClaim列表
    5. 返回带完整溯源信息的AgentMessage

    默认使用DeepSeek（结构化提取任务，性价比高）。
    """

    def default_config(self) -> AgentConfig:
        return AgentConfig(
            provider="openai_compat",
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            max_tokens=4096,
            temperature=0.0,
        )

    @property
    def role(self) -> str:
        return "collector"

    @property
    def system_prompt(self) -> str:
        return COLLECTOR_SYSTEM_PROMPT

    async def run(self, message: AgentMessage) -> AgentMessage:
        """执行采集任务"""
        request = CollectRequest(**message.arguments)

        # 确定要采集的URL列表
        urls = request.target_urls
        if not urls:
            urls = self._get_default_urls(request.target, request.scope)

        # 采集所有URL
        all_claims: list[dict[str, Any]] = []
        fetch_errors: list[str] = []

        for url in urls[: request.max_sources]:
            print(f"  [Collector] 正在抓取: {url[:60]}...")
            fetch_result = await self._fetch_url(url)

            if not fetch_result.success:
                print(f"  [Collector] 失败: {fetch_result.error}")
                fetch_errors.append(f"{url}: {fetch_result.error}")
                continue

            print(f"  [Collector] 成功: {len(fetch_result.content)} 字符")

            # 内容过长时截断，避免超出上下文窗口
            content = self._truncate_content(fetch_result.content, max_chars=12000)

            # 调用LLM提取结构化信息
            extracted = await self._extract_info(
                competitor_name=request.target,
                dimensions=request.scope,
                url=url,
                title=fetch_result.title,
                content=content,
                snapshot_hash=fetch_result.snapshot_hash,
            )
            all_claims.extend(extracted)

        # 构造响应
        return self.build_message(
            to_agent="orchestrator",
            function_name="collect_result",
            arguments={
                "competitor_name": request.target,
                "claims": all_claims,
                "sources_fetched": len(urls) - len(fetch_errors),
                "sources_failed": len(fetch_errors),
                "errors": fetch_errors,
                "dimensions_requested": request.scope,
            },
            trace_id=message.trace_id,
            message_type=MessageType.TASK_RESULT,
            parent_message_id=message.message_id,
            context=message.context,
        )

    async def _fetch_url(self, url: str) -> FetchResult:
        """获取URL内容。

        Reddit JSON API → Firecrawl（有key时）→ 直接HTTP → Playwright。
        """
        # Reddit JSON API 直接走专用工具，跳过 robots 检查
        if "reddit.com" in url and ".json" in url:
            return await reddit_fetch(url)

        allowed, reason = await is_allowed_by_robots(url)
        if not allowed:
            return FetchResult(
                url=url,
                success=False,
                error=f"robots.txt disallowed: {reason}",
                robots_status="disallowed",
                fetch_method="blocked",
            )

        def _apply_pii(r: FetchResult) -> FetchResult:
            r.robots_status = reason
            if r.content:
                r.content, r.pii_redactions = redact_pii(r.content)
            return r

        # 第1级：Firecrawl（最可靠，反爬能力强）
        firecrawl_error = "disabled (no FIRECRAWL_API_KEY)"
        if os.getenv("FIRECRAWL_API_KEY"):
            result = await firecrawl_fetch(url)
            if result.success:
                return _apply_pii(result)
            firecrawl_error = result.error or "unknown"
            print(f"  [Collector] Firecrawl失败 ({url[:50]}): {firecrawl_error}，降级到HTTP")

        # 第2级：直接HTTP（静态页面兜底）
        result = await direct_http_fetch(url)
        if result.success:
            return _apply_pii(result)

        http_error = result.error or "unknown"
        print(f"  [Collector] 直接HTTP失败 ({url[:50]}): {http_error}，降级到Playwright")

        # 第3级：Playwright（JS渲染兜底）
        result = await playwright_fetch(url)
        if result.success and result.content:
            return _apply_pii(result)

        playwright_error = result.error or "unknown"

        jina_error = "disabled"
        if _env_flag("ENABLE_JINA"):
            result = await jina_reader(url)
            if result.success:
                return _apply_pii(result)
            jina_error = result.error or "unknown"

        return FetchResult(
            url=url,
            success=False,
            error=(
                "所有抓取方法均失败: "
                f"HTTP({http_error}) | "
                f"Playwright({playwright_error}) | "
                f"Jina({jina_error}) | "
                f"Firecrawl({firecrawl_error})"
            ),
            robots_status=reason,
            fetch_method="failed",
        )

    async def _extract_info(
        self,
        competitor_name: str,
        dimensions: list[str],
        url: str,
        title: str,
        content: str,
        snapshot_hash: str,
        industry_fields: list[str] | None = None,
        priority_dimensions: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """调用LLM从网页内容中提取结构化信息"""
        # 构建行业扩展字段提示段
        if industry_fields:
            fields_str = "、".join(industry_fields[:8])
            industry_fields_section = (
                f"\n## 行业扩展字段（请重点关注）\n"
                f"除基础维度外，请特别留意以下行业相关信息：{fields_str}\n"
                f"如果网页中包含这些字段的相关信息，请一并提取（dimension 标记为对应字段名）。\n\n"
            )
        else:
            industry_fields_section = "\n"

        # 补采维度强调段
        if priority_dimensions:
            dims_str = "、".join(priority_dimensions)
            industry_fields_section += (
                f"## 重点补采维度\n"
                f"以下维度数据不足，请从本页面尽可能多地提取相关claim：{dims_str}\n"
                f"每个重点维度至少提取3条独立的claim（不同角度/不同事实）。\n\n"
            )

        user_prompt = COLLECT_USER_PROMPT_TEMPLATE.format(
            competitor_name=competitor_name,
            dimensions="、".join(dimensions),
            url=url,
            title=title,
            content=content,
            industry_fields_section=industry_fields_section,
        )

        response = await self.call_llm(messages=[{"role": "user", "content": user_prompt}])

        # 解析LLM输出
        parsed = self._parse_llm_output(response.text)
        if not parsed:
            return []

        # 转换为EvidencedClaim格式
        claims = []
        for item in parsed.get("collected_items", []):
            claim_dict = {
                "claim": item.get("claim", ""),
                "confidence": item.get("confidence", 0.5),
                "reasoning": f"从{title}页面提取",
                "sources": [
                    {
                        "source_type": SourceType.WEB_PAGE.value,
                        "url": url,
                        "title": title,
                        "snippet": item.get("snippet", ""),
                        "accessed_at": datetime.now().isoformat(),
                        "snapshot_hash": snapshot_hash,
                    }
                ],
                "dimension": item.get("dimension", "unknown"),
            }
            claims.append(claim_dict)

        return claims

    def _parse_llm_output(self, text: str) -> dict[str, Any] | None:
        """解析LLM的JSON输出，容错处理"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取```json```代码块
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # 尝试找到第一个{和最后一个}
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            try:
                return json.loads(text[first_brace : last_brace + 1])
            except json.JSONDecodeError:
                pass

        return None

    def _truncate_content(self, content: str, max_chars: int = 12000) -> str:
        """截断过长内容，保留前后部分"""
        if len(content) <= max_chars:
            return content
        half = max_chars // 2
        return content[:half] + "\n\n... [内容过长，中间部分已省略] ...\n\n" + content[-half:]

    def _get_default_urls(self, target: str, scope: list[str]) -> list[str]:
        """已知竞品的 warm-path URL 兜底（warm-path map）。

        未知竞品**不再自动拼装**搜索端点 URL —— 那是 Discovery 的职责。
        Discovery 0 URL 时由上层 (runner) 触发明确错误 / HITL，而不是让 collector
        盲目去抓 `s.jina.ai/xxx` 这种搜索端点（会被 robots.txt 直接拒）。
        """
        url_map: dict[str, dict[str, list[str]]] = {
            "notion": {
                "pricing": ["https://www.notion.so/pricing"],
                "features": ["https://www.notion.so/product"],
                "integrations": ["https://www.notion.so/integrations"],
                "ai_features": ["https://www.notion.so/product/ai"],
                "user_personas": ["https://www.notion.so/customers"],
            },
            "feishu": {
                "pricing": ["https://www.feishu.cn/pricing"],
                "features": ["https://www.feishu.cn/product/docs"],
                "integrations": ["https://www.feishu.cn/ecosystem"],
                "ai_features": ["https://www.feishu.cn/product/ai"],
                "user_personas": ["https://www.feishu.cn/customers"],
            },
            "clickup": {
                "pricing": ["https://clickup.com/pricing"],
                "features": ["https://clickup.com/features"],
                "integrations": ["https://clickup.com/integrations"],
                "ai_features": ["https://clickup.com/ai"],
                "user_personas": ["https://clickup.com/customers"],
            },
            # ---- 消费品（consumer 模板） ----
            "xiaomi": {
                "pricing": ["https://www.mi.com"],
                "features": ["https://www.mi.com/shop"],
                "user_personas": ["https://www.mi.com/community"],
            },
            "anker": {
                "pricing": ["https://www.anker.com/collections"],
                "features": ["https://www.anker.com/collections/cables"],
                "user_personas": ["https://www.anker.com/blogs"],
            },
            # ---- 硬件（hardware 模板） ----
            "dji": {
                "pricing": ["https://store.dji.com"],
                "features": ["https://www.dji.com/products"],
                "user_personas": ["https://www.dji.com/newsroom"],
            },
            "insta360": {
                "pricing": ["https://store.insta360.com"],
                "features": ["https://www.insta360.com/product"],
                "user_personas": ["https://www.insta360.com/explore"],
            },
        }

        aliases: dict[str, str] = {
            "飞书": "feishu",
            "lark": "feishu",
            "click up": "clickup",
            "小米": "xiaomi",
            "大疆": "dji",
            "安克": "anker",
            "安克创新": "anker",
            "影石": "insta360",
        }

        key = target.lower().strip()
        key = aliases.get(key, key)

        target_urls = url_map.get(key, {})
        if not target_urls:
            # 未知竞品：返回空 → 由上层路由到 Discovery 或 HITL
            return []

        urls: list[str] = []
        for dim in scope:
            urls.extend(target_urls.get(dim, []))
        if "user_personas" not in scope:
            urls.extend(target_urls.get("user_personas", []))
        return urls
