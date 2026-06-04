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
    ITERATION_SUMMARY = "iteration_summary"
    SUB_AGENT_START = "sub_agent_start"
    SUB_AGENT_END = "sub_agent_end"
    HITL_PAUSE = "hitl_pause"
    HITL_RESUME = "hitl_resume"
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
        self._history: dict[str, list[SSEEvent]] = {}
        self._closed: set[str] = set()

    def create_task(self, task_id: str) -> None:
        self._queues[task_id] = asyncio.Queue()
        self._history[task_id] = []
        self._closed.discard(task_id)

    def remove_task(self, task_id: str) -> None:
        self._queues.pop(task_id, None)
        self._history.pop(task_id, None)
        self._closed.discard(task_id)

    async def publish(self, task_id: str, event: SSEEvent) -> None:
        queue = self._queues.get(task_id)
        if queue:
            await queue.put(event)
        history = self._history.get(task_id)
        if history is not None:
            history.append(event)

    def get_history(self, task_id: str) -> list[SSEEvent]:
        return self._history.get(task_id, [])

    async def subscribe(self, task_id: str):
        """异步生成器 - 先回放历史事件，再实时消费新事件"""
        # 回放历史（客户端晚连也能收到之前的事件）
        replayed_events = list(self.get_history(task_id))
        replayed_ids = {id(event) for event in replayed_events}
        for event in replayed_events:
            yield event

        # 如果任务已结束，不再等待新事件
        if task_id in self._closed:
            return

        queue = self._queues.get(task_id)
        if not queue:
            return

        # 任务启动后，SSE 客户端通常会晚几百毫秒接入。此时早期事件既在
        # history 中，也还留在 queue 中；直接消费会导致前端看到重复日志。
        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if event is None:
                return
            if id(event) in replayed_ids:
                continue
            yield event

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def close(self, task_id: str) -> None:
        """标记任务结束，发送终止信号让subscriber退出"""
        self._closed.add(task_id)
        queue = self._queues.get(task_id)
        if queue:
            await queue.put(None)

    def has_task(self, task_id: str) -> bool:
        return task_id in self._queues or task_id in self._closed


event_bus = EventBus()
