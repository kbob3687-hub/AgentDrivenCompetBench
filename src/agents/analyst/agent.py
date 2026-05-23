"""AnalystAgent - 竞品分析Agent

接收CollectorAgent输出的claims，整合为结构化CompetitorProfile。
使用Claude（核心推理任务，需要高质量分析能力）。
"""

from __future__ import annotations

import json
import os
from typing import Any

from agents.base import AgentConfig, BaseAgent
from agents.analyst.prompts import ANALYST_SYSTEM_PROMPT, ANALYZE_USER_PROMPT_TEMPLATE
from agents.analyst.tools import (
    build_competitor_profile,
    group_claims_by_dimension,
)
from schemas.competitor import CompetitorProfile
from schemas.message import AgentMessage, AnalyzeRequest, MessageType


class AnalystAgent(BaseAgent):
    """竞品分析Agent

    工作流程：
    1. 接收Collector输出的claims列表
    2. 按维度分组，构造分析prompt
    3. 调用Claude进行深度分析和结构化
    4. 将LLM输出转换为CompetitorProfile
    5. 返回带完整溯源的分析结果
    """

    def default_config(self) -> AgentConfig:
        return AgentConfig(
            provider="openai_compat",
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            max_tokens=8192,
            temperature=0.0,
        )

    @property
    def role(self) -> str:
        return "analyst"

    @property
    def system_prompt(self) -> str:
        return ANALYST_SYSTEM_PROMPT

    async def run(self, message: AgentMessage) -> AgentMessage:
        """执行分析任务"""
        args = message.arguments
        competitor_name = args.get("competitor_name", "")
        claims = args.get("claims", [])
        dimensions = args.get("dimensions_requested", [])

        if not claims:
            return self.build_message(
                to_agent="orchestrator",
                function_name="analyze_result",
                arguments={
                    "error": "no claims to analyze",
                    "competitor_name": competitor_name,
                },
                trace_id=message.trace_id,
                message_type=MessageType.TASK_RESULT,
                parent_message_id=message.message_id,
                context=message.context,
            )

        # 按维度分组，用于prompt展示
        grouped = group_claims_by_dimension(claims)
        dimensions_summary = ", ".join(
            f"{dim}({len(items)}条)" for dim, items in grouped.items()
        )

        # 构造claims的JSON表示（带索引）
        indexed_claims = []
        for i, claim in enumerate(claims):
            source_url = claim.get("sources", [{}])[0].get("url", "") if claim.get("sources") else ""
            is_customer_source = any(
                kw in source_url for kw in ["/customers", "/customer-stories", "/case-studies"]
            )
            indexed_claims.append({
                "index": i,
                "dimension": claim.get("dimension", "unknown"),
                "claim": claim.get("claim", ""),
                "confidence": claim.get("confidence", 0.5),
                "source_url": source_url,
                "snippet": claim.get("sources", [{}])[0].get("snippet", "") if claim.get("sources") else "",
                "is_customer_source": is_customer_source,
            })

        user_prompt = ANALYZE_USER_PROMPT_TEMPLATE.format(
            competitor_name=competitor_name,
            dimensions=dimensions_summary,
            claim_count=len(claims),
            claims_json=json.dumps(indexed_claims, ensure_ascii=False, indent=2),
        )

        # 调用Claude进行分析
        response = await self.call_llm(
            messages=[{"role": "user", "content": user_prompt}]
        )

        # 解析LLM输出
        llm_output = self._parse_llm_output(response.text)
        if not llm_output:
            return self.build_message(
                to_agent="orchestrator",
                function_name="analyze_result",
                arguments={
                    "error": "failed to parse LLM analysis output",
                    "raw_output": response.text[:2000],
                    "competitor_name": competitor_name,
                },
                trace_id=message.trace_id,
                message_type=MessageType.TASK_RESULT,
                parent_message_id=message.message_id,
                context=message.context,
            )

        # 构建CompetitorProfile
        profile = build_competitor_profile(competitor_name, llm_output, claims)

        return self.build_message(
            to_agent="orchestrator",
            function_name="analyze_result",
            arguments={
                "competitor_name": competitor_name,
                "profile": profile.model_dump(mode="json"),
                "completeness_score": profile.completeness_score,
                "dimensions_analyzed": list(grouped.keys()),
                "claims_processed": len(claims),
                "summary": llm_output.get("analysis_summary", {}),
            },
            trace_id=message.trace_id,
            message_type=MessageType.TASK_RESULT,
            parent_message_id=message.message_id,
            context=message.context,
        )

    def _parse_llm_output(self, text: str) -> dict[str, Any] | None:
        """解析LLM的JSON输出"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        return None
