"""问卷设计 + 访谈提纲生成路由（纯 LLM，不走 pipeline）"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter
from openai import OpenAI
from pydantic import BaseModel

router = APIRouter(prefix="/api/survey", tags=["survey"])


class SurveyRequest(BaseModel):
    competitor_name: str
    industry: str = "saas"
    focus: str = ""


class SurveyResponse(BaseModel):
    competitor_name: str
    questionnaire: str
    interview_guide: str


def _call_llm(prompt: str) -> str:
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        max_tokens=2048,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


@router.post("", response_model=SurveyResponse)
async def generate_survey(req: SurveyRequest) -> SurveyResponse:
    focus_hint = f"，重点关注 {req.focus}" if req.focus else ""
    name = req.competitor_name
    industry = req.industry

    questionnaire_prompt = f"""你是一名资深产品经理，需要设计一份针对竞品 **{name}**（{industry} 行业）的用户调研问卷{focus_hint}。

要求：
- 15-20 道题，覆盖：使用频率、核心功能满意度、定价感知、痛点、与替代品对比
- 包含单选、多选、李克特量表（1-5分）、开放题，各类型均有
- 每道题标注题型（[单选]/[多选]/[量表]/[开放]）
- 输出 Markdown 格式，有清晰的章节标题

直接输出问卷内容，不要前言。"""

    interview_prompt = f"""你是一名资深产品研究员，需要设计一份针对竞品 **{name}**（{industry} 行业）用户的访谈提纲{focus_hint}。

要求：
- 访谈时长约 45 分钟
- 分为 5 个模块：背景了解、使用旅程、核心功能评价、痛点与缺口、替代方案探索
- 每个模块 3-5 个问题，包含追问引导语
- 开放式问题为主，避免引导性提问
- 输出 Markdown 格式

直接输出访谈提纲，不要前言。"""

    loop = asyncio.get_event_loop()
    questionnaire, interview_guide = await asyncio.gather(
        loop.run_in_executor(None, _call_llm, questionnaire_prompt),
        loop.run_in_executor(None, _call_llm, interview_prompt),
    )

    return SurveyResponse(
        competitor_name=name,
        questionnaire=questionnaire,
        interview_guide=interview_guide,
    )
