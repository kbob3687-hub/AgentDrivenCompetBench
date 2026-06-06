"""WriterAgent - 竞品报告撰写Agent

接收AnalystAgent输出的CompetitorProfile，生成带溯源角标的Markdown报告。
使用Claude（需要高质量文字表达能力）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from agents.base import AgentConfig, BaseAgent
from agents.writer.prompts import WRITE_USER_PROMPT_TEMPLATE, WRITER_SYSTEM_PROMPT
from schemas.message import AgentMessage, MessageType


class WriterAgent(BaseAgent):
    """报告撰写Agent

    工作流程：
    1. 接收CompetitorProfile（来自Analyst）
    2. 调用Claude生成带角标的Markdown报告
    3. 后处理：验证角标完整性，补充来源附录
    4. 返回完整报告文本
    """

    def default_config(self) -> AgentConfig:
        return AgentConfig(
            provider="openai_compat",
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            max_tokens=16384,
            temperature=0.2,
        )

    @property
    def role(self) -> str:
        return "writer"

    @property
    def system_prompt(self) -> str:
        return WRITER_SYSTEM_PROMPT

    async def run(self, message: AgentMessage) -> AgentMessage:
        """执行报告撰写任务"""
        args = message.arguments
        competitor_name = args.get("competitor_name", "")
        profile = args.get("profile", {})

        if not profile or not profile.get("company_name"):
            print(
                f"  [Writer] Profile is empty or missing company_name. Keys: {list(profile.keys()) if profile else 'None'}"
            )
            return self.build_message(
                to_agent="orchestrator",
                function_name="write_result",
                arguments={
                    "error": "no profile data to write report",
                    "profile_keys": list(profile.keys()) if profile else [],
                },
                trace_id=message.trace_id,
                message_type=MessageType.TASK_RESULT,
                parent_message_id=message.message_id,
                context=message.context,
            )

        # 构造prompt
        profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
        if len(profile_json) > 15000:
            profile_json = self._compact_profile(profile)

        user_prompt = WRITE_USER_PROMPT_TEMPLATE.format(
            competitor_name=competitor_name,
            profile_json=profile_json,
        )

        # 调用Claude生成报告
        response = await self.call_llm(messages=[{"role": "user", "content": user_prompt}])

        report_md = response.text

        # 后处理：提取sources列表用于QA验证
        sources = self._extract_all_sources(profile)
        footnote_count = report_md.count("[") - report_md.count("[]")

        return self.build_message(
            to_agent="orchestrator",
            function_name="write_result",
            arguments={
                "competitor_name": competitor_name,
                "report_markdown": report_md,
                "report_length": len(report_md),
                "footnote_count": footnote_count,
                "sources_referenced": len(sources),
                "generated_at": datetime.now().isoformat(),
                "profile": profile,
            },
            trace_id=message.trace_id,
            message_type=MessageType.TASK_RESULT,
            parent_message_id=message.message_id,
            context=message.context,
        )

    def _compact_profile(self, profile: dict[str, Any]) -> str:
        """压缩过长的profile，保留关键字段"""
        compact = {
            "company_name": profile.get("company_name"),
            "product_name": profile.get("product_name"),
            "website": profile.get("website"),
            "industry": profile.get("industry"),
            "one_liner": profile.get("one_liner"),
            "pricing": profile.get("pricing"),
            "feature_tree": profile.get("feature_tree"),
            "user_personas": profile.get("user_personas"),
            "swot": profile.get("swot"),
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)

    def _extract_all_sources(self, profile: dict[str, Any]) -> list[dict[str, str]]:
        """从profile中提取所有source引用"""
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                if "sources" in obj and isinstance(obj["sources"], list):
                    for src in obj["sources"]:
                        url = src.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            sources.append(
                                {
                                    "url": url,
                                    "title": src.get("title", ""),
                                    "snippet": src.get("snippet", ""),
                                }
                            )
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(profile)
        return sources
