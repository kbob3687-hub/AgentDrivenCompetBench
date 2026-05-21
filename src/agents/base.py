"""BaseAgent - 所有Agent的抽象基类

集成Langfuse可观测性，内置重试机制，统一消息收发格式。
所有Agent继承此类后自动获得：trace/span记录、token统计、异常处理。
支持双模型路由：Anthropic (Claude) / OpenAI兼容 (DeepSeek等)。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import anthropic
import httpx
from langfuse import Langfuse
from openai import AsyncOpenAI
from pydantic import BaseModel

from schemas.message import AgentMessage, MessageContext, MessageType


class LLMResponse(BaseModel):
    """统一的LLM响应格式，屏蔽不同provider差异"""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    raw: Any = None

    model_config = {"arbitrary_types_allowed": True}


class AgentConfig(BaseModel):
    """Agent配置"""

    provider: str = "anthropic"  # "anthropic" or "openai_compat"
    model: str = "claude-sonnet-4-6-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0
    max_retries: int = 3
    retry_delay: float = 2.0


class BaseAgent(ABC):
    """所有Agent的抽象基类

    子类只需实现:
    - role: 角色名称
    - system_prompt: 系统提示词
    - run(): 核心处理逻辑
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        langfuse: Langfuse | None = None,
    ):
        self.config = config or self.default_config()
        self.langfuse = langfuse or Langfuse()

        if self.config.provider == "anthropic":
            self.anthropic_client = anthropic.AsyncAnthropic(
                base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
            )
            self.openai_client = None
        else:
            self.anthropic_client = None
            self.openai_client = AsyncOpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )

    def default_config(self) -> AgentConfig:
        """子类可重写以提供默认配置"""
        return AgentConfig()

    @property
    @abstractmethod
    def role(self) -> str:
        """Agent角色标识: collector/analyst/writer/qa"""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Agent的system prompt"""
        ...

    @abstractmethod
    async def run(self, message: AgentMessage) -> AgentMessage:
        """核心处理逻辑 - 子类必须实现

        Args:
            message: 接收到的AgentMessage

        Returns:
            处理结果AgentMessage
        """
        ...

    async def execute(self, message: AgentMessage) -> AgentMessage:
        """执行入口 - 包装run()方法，添加Langfuse追踪和重试机制

        不要重写此方法，重写run()即可。
        """
        span = self.langfuse.start_observation(
            name=f"{self.role}.execute",
            input=message.model_dump(mode="json"),
            metadata={
                "agent_role": self.role,
                "function_name": message.function_name,
                "iteration": message.context.iteration,
                "trace_id": message.trace_id,
            },
        )

        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                result = await self.run(message)

                span.update(
                    output=result.model_dump(mode="json"),
                    level="DEFAULT",
                    status_message=f"completed on attempt {attempt}",
                ).end()
                self.langfuse.flush()
                return result

            except Exception as e:
                last_error = e
                error_msg = f"[{self.role}] attempt {attempt}/{self.config.max_retries} failed: {type(e).__name__}: {e}"

                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * attempt)
                else:
                    span.update(
                        output={"error": str(e), "attempts": attempt},
                        level="ERROR",
                        status_message=f"failed after {attempt} attempts: {e}",
                    ).end()
                    self.langfuse.flush()

        return self._build_error_response(message, last_error)

    async def call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: Any = None,
    ) -> LLMResponse:
        """调用LLM - 根据provider路由到不同后端，自动记录到Langfuse

        Returns:
            统一的LLMResponse对象
        """
        generation = self.langfuse.start_observation(
            name=f"{self.role}.llm_call",
            input={"messages": messages, "system": self.system_prompt[:200] + "..."},
            metadata={"model": self.config.model, "provider": self.config.provider},
            model=self.config.model,
        )

        try:
            if self.config.provider == "anthropic":
                result = await self._call_anthropic(messages, tools, response_format)
            else:
                result = await self._call_openai_compat(messages, tools, response_format)

            generation.update(
                output=result.text,
                usage_details={
                    "input": result.input_tokens,
                    "output": result.output_tokens,
                    "total": result.input_tokens + result.output_tokens,
                },
                model=result.model,
                level="DEFAULT",
            ).end()
            return result

        except Exception as e:
            generation.update(
                output={"error": str(e)},
                level="ERROR",
                status_message=str(e),
            ).end()
            raise

    async def _call_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: Any = None,
    ) -> LLMResponse:
        """调用Anthropic Claude API"""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format

        response = await self.anthropic_client.messages.create(**kwargs)

        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        return LLMResponse(
            text="\n".join(text_parts),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            raw=response,
        )

    async def _call_openai_compat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: Any = None,
    ) -> LLMResponse:
        """调用OpenAI兼容API (DeepSeek等)"""
        oai_messages = [{"role": "system", "content": self.system_prompt}]
        oai_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": oai_messages,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await self.openai_client.chat.completions.create(**kwargs)

        text = response.choices[0].message.content or ""
        usage = response.usage

        return LLMResponse(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self.config.model,
            raw=response,
        )

    def build_message(
        self,
        to_agent: str,
        function_name: str,
        arguments: dict[str, Any],
        trace_id: str,
        message_type: MessageType = MessageType.TASK_RESULT,
        parent_message_id: str | None = None,
        context: MessageContext | None = None,
    ) -> AgentMessage:
        """构造标准化的Agent间消息"""
        return AgentMessage(
            message_id=str(uuid.uuid4()),
            trace_id=trace_id,
            message_type=message_type,
            from_agent=self.role,
            to_agent=to_agent,
            function_name=function_name,
            arguments=arguments,
            parent_message_id=parent_message_id,
            context=context or MessageContext(),
        )

    def _build_error_response(
        self, original: AgentMessage, error: Exception | None
    ) -> AgentMessage:
        """构造错误响应消息"""
        return self.build_message(
            to_agent=original.from_agent,
            function_name="report_error",
            arguments={
                "error": str(error) if error else "unknown error",
                "error_type": type(error).__name__ if error else "Unknown",
                "original_function": original.function_name,
                "agent": self.role,
            },
            trace_id=original.trace_id,
            message_type=MessageType.STATUS_UPDATE,
            parent_message_id=original.message_id,
            context=original.context,
        )
