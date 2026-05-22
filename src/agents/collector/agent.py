"""CollectorAgent - 竞品信息采集Agent

负责从公开网页采集竞品数据，输出带溯源的结构化信息。
使用Jina Reader（主力）和Playwright（JS渲染页面）作为采集工具。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

from agents.base import BaseAgent, AgentConfig
from agents.collector.prompts import COLLECTOR_SYSTEM_PROMPT, COLLECT_USER_PROMPT_TEMPLATE
from agents.collector.tools import FetchResult, jina_reader, playwright_fetch
from schemas.competitor import EvidencedClaim, SourceReference, SourceType
from schemas.message import AgentMessage, CollectRequest, MessageType


class CollectorAgent(BaseAgent):
    """信息采集Agent

    工作流程：
    1. 解析CollectRequest，确定采集目标和维度
    2. 使用Jina Reader获取网页内容（失败时降级到Playwright）
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
        """获取URL内容，仅用Jina Reader（测试阶段跳过Playwright降级）"""
        return await jina_reader(url)

    async def _extract_info(
        self,
        competitor_name: str,
        dimensions: list[str],
        url: str,
        title: str,
        content: str,
        snapshot_hash: str,
    ) -> list[dict[str, Any]]:
        """调用LLM从网页内容中提取结构化信息"""
        user_prompt = COLLECT_USER_PROMPT_TEMPLATE.format(
            competitor_name=competitor_name,
            dimensions="、".join(dimensions),
            url=url,
            title=title,
            content=content,
        )

        response = await self.call_llm(
            messages=[{"role": "user", "content": user_prompt}]
        )

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
        return (
            content[:half]
            + "\n\n... [内容过长，中间部分已省略] ...\n\n"
            + content[-half:]
        )

    def _get_default_urls(self, target: str, scope: list[str]) -> list[str]:
        """根据竞品名称和采集维度生成默认URL列表"""
        url_map: dict[str, dict[str, list[str]]] = {
            "Notion": {
                "pricing": ["https://www.notion.so/pricing"],
                "features": ["https://www.notion.so/product"],
                "integrations": ["https://www.notion.so/integrations"],
                "ai_features": ["https://www.notion.so/product/ai"],
            },
            "Feishu": {
                "pricing": ["https://www.feishu.cn/pricing"],
                "features": ["https://www.feishu.cn/product/docs"],
                "integrations": ["https://www.feishu.cn/ecosystem"],
                "ai_features": ["https://www.feishu.cn/product/ai"],
            },
            "ClickUp": {
                "pricing": ["https://clickup.com/pricing"],
                "features": ["https://clickup.com/features"],
                "integrations": ["https://clickup.com/integrations"],
                "ai_features": ["https://clickup.com/ai"],
            },
        }

        urls: list[str] = []
        target_urls = url_map.get(target, {})
        for dim in scope:
            urls.extend(target_urls.get(dim, []))

        # 如果没有预定义URL，至少返回一个搜索入口
        if not urls:
            urls = [f"https://www.google.com/search?q={target}+{'+'.join(scope)}"]

        return urls
