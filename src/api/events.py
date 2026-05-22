"""SSE事件系统 - 基于asyncio.Queue的发布/订阅

每个分析任务有一个独立的事件队列，SSE endpoint从队列读取事件推送给前端。
单进程架构，不依赖Redis pub/sub。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    LOG = "log"
    QA_VERDICT = "qa_verdict"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class SSEEvent:
    event_type: EventType
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False)
        return f"event: {self.event_type.value}\ndata: {payload}\n\n"


class EventBus:
    """任务级事件总线 - 管理所有活跃任务的事件队列"""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[SSEEvent | None]] = {}

    def create_task(self, task_id: str) -> None:
        self._queues[task_id] = asyncio.Queue()

    def remove_task(self, task_id: str) -> None:
        self._queues.pop(task_id, None)

    async def publish(self, task_id: str, event: SSEEvent) -> None:
        queue = self._queues.get(task_id)
        if queue:
            await queue.put(event)

    async def subscribe(self, task_id: str):
        """异步生成器 - SSE endpoint用此方法消费事件"""
        queue = self._queues.get(task_id)
        if not queue:
            return

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def close(self, task_id: str) -> None:
        """发送终止信号，让subscriber退出"""
        queue = self._queues.get(task_id)
        if queue:
            await queue.put(None)

    def has_task(self, task_id: str) -> bool:
        return task_id in self._queues


event_bus = EventBus()
